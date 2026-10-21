"""Chat orchestration against a mocked provider — no network involved."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from myai.core.errors import InsufficientCreditError, RateLimitError, ValidationError
from myai.core.events import Events
from myai.services.chat import DEFAULT_CONTEXT_WINDOW, ChatService
from myai.services.openrouter import ModelInfo, OpenRouterClient

KEY = "sk-or-v1-secret-value"


def sse_text(*chunks: str) -> bytes:
    parts = []
    for chunk in chunks:
        payload = {"choices": [{"delta": {"content": chunk}, "finish_reason": None}]}
        parts.append(f"data: {json.dumps(payload)}\n\n")
    parts.append('data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                 '"usage":{"prompt_tokens":11,"completion_tokens":4,"total_tokens":15}}\n\n')
    parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


def make_service(ctx, handler, *, model_id="test/model") -> ChatService:
    service = ChatService(
        db=ctx.db,
        bus=ctx.bus,
        conversations=ctx.conversations,
        settings=ctx.settings,
        memory=ctx.memory,
        persona=ctx.persona,
        client_factory=lambda: OpenRouterClient(
            lambda: KEY, transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )
    service.set_models(
        [ModelInfo(id=model_id, name="Test Model", context_length=4096, prompt_price=0.0,
                   completion_price=0.0, supports_tools=True, supports_vision=False)]
    )
    return service


def test_send_streams_persists_and_records_stats(ctx) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, content=sse_text("Hel", "lo ", "world"),
            headers={"content-type": "text/event-stream"},
        )

    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Stream", select=False)
    deltas: list[str] = []
    outcome = service.send(conversation.id, "hi there", model_id="test/model", on_delta=deltas.append)

    assert outcome.error is None
    assert deltas == ["Hel", "lo ", "world"]
    assert outcome.result is not None and outcome.result.text == "Hello world"
    assert captured["auth"] == f"Bearer {KEY}"

    messages = ctx.conversations.messages(conversation.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].content == "Hello world"
    assert messages[1].status == "complete"
    assert messages[1].input_tokens == 11
    assert messages[1].output_tokens == 4
    stats = messages[1].meta["stats"]
    assert stats["completion_tokens"] == 4
    assert stats["first_token_ms"] >= 0
    assert stats["total_ms"] >= stats["first_token_ms"]
    assert captured["payload"]["model"] == "test/model"
    assert captured["payload"]["stream"] is True


def test_conversation_persistence_across_service_instances(ctx) -> None:
    handler = lambda request: httpx.Response(200, content=sse_text("saved"),  # noqa: E731
                                             headers={"content-type": "text/event-stream"})
    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Persisted", select=False)
    service.send(conversation.id, "remember this", model_id="test/model")

    reopened = ctx.conversations.messages(conversation.id)
    assert reopened[-1].content == "saved"


def test_memory_is_injected_and_isolated_per_chat(ctx) -> None:
    payloads: list[list[dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content)["messages"])
        return httpx.Response(200, content=sse_text("ok"), headers={"content-type": "text/event-stream"})

    service = make_service(ctx, handler)
    a = ctx.conversations.create("A", select=False)
    b = ctx.conversations.create("B", select=False)
    ctx.memory.add("GLOBAL-FACT-123", scope="global")
    ctx.memory.add("CHAT-A-FACT-456", scope="conversation", conversation_id=a.id)

    service.send(a.id, "hello A", model_id="test/model")
    service.send(b.id, "hello B", model_id="test/model")

    prompt_a = payloads[0][0]["content"]
    prompt_b = payloads[1][0]["content"]
    assert "GLOBAL-FACT-123" in prompt_a and "CHAT-A-FACT-456" in prompt_a
    assert "GLOBAL-FACT-123" in prompt_b
    assert "CHAT-A-FACT-456" not in prompt_b


def test_persona_and_profile_reach_the_prompt(ctx) -> None:
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][0]["content"])
        return httpx.Response(200, content=sse_text("ok"), headers={"content-type": "text/event-stream"})

    ctx.persona.save(enabled=True, text="PERSONA-MARKER", tone="formal", detail="detailed", language="en")
    ctx.persona.write_profile("- Name: PROFILE-MARKER\n")
    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Persona", select=False)
    service.send(conversation.id, "hi", model_id="test/model")
    assert "PERSONA-MARKER" in prompts[0]
    assert "PROFILE-MARKER" in prompts[0]
    assert "tone: formal" in prompts[0]


def test_rate_limit_and_credit_errors_are_stored_on_the_message(ctx) -> None:
    for status, expected in ((429, RateLimitError), (402, InsufficientCreditError)):
        def handler(request: httpx.Request, status=status) -> httpx.Response:
            return httpx.Response(status, json={"error": {"message": "nope"}})

        service = make_service(ctx, handler)
        conversation = ctx.conversations.create(f"Error {status}", select=False)
        events: list[str] = []
        unsubscribe = ctx.bus.subscribe(
            Events.MESSAGE_FAILED,
            lambda **kw: events.append(kw["error"]["code"]),  # noqa: B023 - fresh list each loop
        )
        outcome = service.send(conversation.id, "hi", model_id="test/model")
        unsubscribe()
        assert isinstance(outcome.error, expected)
        assert outcome.assistant_message is not None
        stored = ctx.conversations.get_message(outcome.assistant_message.id)
        assert stored.status == "error"
        assert stored.error
        assert events == [expected.code]
        # The user turn is preserved so nothing is silently lost.
        assert [m.role for m in ctx.conversations.messages(conversation.id)] == ["user", "assistant"]


def test_cancel_keeps_partial_text(ctx) -> None:
    cancel_seen = threading.Event()

    def body():
        for i in range(40):
            if cancel_seen.is_set():
                return
            yield f"data: {json.dumps({'choices': [{'delta': {'content': f'w{i} '}}]})}\n\n".encode()
            time.sleep(0.01)
        yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})

    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Cancel", select=False)
    seen: list[str] = []

    def on_delta(fragment: str) -> None:
        seen.append(fragment)
        if len(seen) == 3:
            cancel_seen.set()
            service.cancel()

    outcome = service.send(conversation.id, "stream", model_id="test/model", on_delta=on_delta)
    assert outcome.cancelled is True
    assert outcome.error is None
    stored = ctx.conversations.get_message(outcome.assistant_message.id)
    assert stored.status == "cancelled"
    assert stored.content.startswith("w0")
    assert "w39" not in stored.content
    assert service.is_streaming is False


def test_empty_message_and_missing_model_are_rejected(ctx) -> None:
    service = make_service(ctx, lambda request: httpx.Response(200))
    conversation = ctx.conversations.create("Validation", select=False)
    with pytest.raises(ValidationError):
        service.send(conversation.id, "   ", model_id="test/model")
    # Model id falls back to the conversation → settings; blank both.
    ctx.settings.update({"ai.default_model": ""})
    ctx.conversations.set_model(conversation.id, "")
    with pytest.raises(ValidationError):
        service.send(conversation.id, "hi", model_id="")
    assert ctx.conversations.messages(conversation.id) == []


def test_context_status_reports_usage_and_warning(ctx) -> None:
    service = make_service(ctx, lambda request: httpx.Response(200))
    conversation = ctx.conversations.create("Usage", select=False)
    ctx.conversations.set_model(conversation.id, "test/model")
    ctx.conversations.add_message(conversation.id, "user", "x" * 16000)
    ctx.memory.add("a fact", scope="global")
    status = service.context_status(ctx.conversations.get(conversation.id))
    assert status["window"] == 4096
    assert status["history_tokens"] > 0
    assert status["memory_tokens"] > 0
    assert status["estimated"] is True
    # 16000 chars ≈ 4000 estimated tokens on a 4096-token window: above 80%.
    assert status["warning"] is True
    assert 0.9 < status["ratio"] <= 1.0
    assert 0 < status["ratio"] <= 1.0


def test_unknown_model_uses_documented_default_window(ctx) -> None:
    service = make_service(ctx, lambda request: httpx.Response(200))
    assert service.context_window("not/a/real-model") == DEFAULT_CONTEXT_WINDOW


def test_prompt_diagnostics_are_emitted(ctx) -> None:
    captured: list[dict] = []
    ctx.bus.subscribe(Events.STREAM_STARTED, lambda **kw: captured.append(kw))
    handler = lambda request: httpx.Response(200, content=sse_text("x"),  # noqa: E731
                                             headers={"content-type": "text/event-stream"})
    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Diag", select=False)
    service.send(conversation.id, "hello", model_id="test/model")
    assert len(captured) == 1
    diagnostics = captured[0]["diagnostics"]
    assert diagnostics["context_window"] == 4096
    assert diagnostics["estimated"] is True
    assert diagnostics["total_tokens"] > 0


def test_api_key_never_appears_in_stored_messages(ctx) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_text("secret-free"),
                              headers={"content-type": "text/event-stream"})

    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("Leak", select=False)
    outcome = service.send(conversation.id, "hi", model_id="test/model")
    blob = json.dumps([m.meta for m in ctx.conversations.messages(conversation.id)], default=str)
    assert KEY not in blob
    assert outcome.result is not None
    # And not in the exported backup of the DB row either.
    assert KEY not in (ctx.conversations.get_message(outcome.assistant_message.id).content or "")


def test_models_are_shared_with_services(ctx) -> None:
    service = make_service(ctx, lambda request: httpx.Response(200))
    assert [m.id for m in service.models()] == ["test/model"]
    assert service.model_info("test/model").supports_tools is True
    assert service.model_info("missing") is None


def test_missing_usage_falls_back_to_the_prompt_estimate(ctx) -> None:
    """Some providers omit usage; the stored count must stay honest."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"no usage"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    service = make_service(ctx, handler)
    conversation = ctx.conversations.create("No usage", select=False)
    outcome = service.send(conversation.id, "a prompt of some length", model_id="test/model")
    stored = ctx.conversations.get_message(outcome.assistant_message.id)
    assert stored.input_tokens > 0
    assert stored.meta["estimated_usage"] is True
    assert stored.output_tokens > 0
