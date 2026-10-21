"""OpenRouter client tests.

These exercise the real client code — request building, SSE parsing, error
mapping, cancellation and timing — against ``httpx.MockTransport``. No network
is touched, so the suite is deterministic and runs in the sandbox where
``openrouter.ai`` is unreachable. A separate, clearly-labelled test documents
the live check (skipped without a key + network).
"""

from __future__ import annotations

import json
import os
import threading
import time

import httpx
import pytest

from myai.core.errors import (
    AuthenticationError,
    ConfigurationError,
    InsufficientCreditError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ValidationError,
)
from myai.services.openrouter import (
    OpenRouterClient,
    TimeoutProviderError,
    parse_model,
)

CATALOGUE = {
    "data": [
        {
            "id": "anthropic/claude-3.5-sonnet",
            "name": "Claude 3.5 Sonnet",
            "context_length": 200000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "architecture": {"modality": "text->text", "input_modalities": ["text", "image"]},
            "supported_parameters": ["tools", "temperature", "max_tokens"],
        },
        {
            "id": "google/gemini-flash-1.5",
            "name": "Gemini Flash 1.5",
            "context_length": 1000000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"modality": "text->text", "input_modalities": ["text"]},
            "supported_parameters": ["temperature"],
        },
    ]
}


def sse(*events: dict | str) -> bytes:
    out = []
    for event in events:
        if isinstance(event, str):
            out.append(f"data: {event}\n\n")
        else:
            out.append(f"data: {json.dumps(event)}\n\n")
    out.append("data: [DONE]\n\n")
    return "".join(out).encode()


def event_only(*events: dict | str) -> bytes:
    """One or more SSE events without the terminal [DONE] marker."""
    out = []
    for event in events:
        text = event if isinstance(event, str) else json.dumps(event)
        out.append(f"data: {text}\n\n")
    return "".join(out).encode()


def delta(content: str, finish: str | None = None) -> dict:
    return {
        "choices": [{"delta": {"content": content}, "finish_reason": finish}],
        "model": "test/model",
    }


def client_with(handler, key: str | None = "sk-or-v1-test") -> OpenRouterClient:
    return OpenRouterClient(
        lambda: key,
        base_url="https://openrouter.example/api/v1",
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )


# ------------------------------------------------------------------ catalogue
def test_list_models_parses_and_sorts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"
        assert request.headers["X-Title"] == "MyAI Studio Ultimate"
        return httpx.Response(200, json=CATALOGUE)

    models = client_with(handler).list_models()
    assert [m.id for m in models] == ["anthropic/claude-3.5-sonnet", "google/gemini-flash-1.5"]
    claude = models[0]
    assert claude.context_length == 200_000
    assert claude.prompt_price == pytest.approx(3.0)
    assert claude.completion_price == pytest.approx(15.0)
    assert claude.supports_tools is True
    assert claude.supports_vision is True
    assert claude.context_label() == "200k"
    assert models[1].is_free() is True


def test_model_capabilities_are_not_guessed() -> None:
    plain = parse_model({"id": "x/y", "name": "Y", "pricing": {}, "architecture": {}})
    assert plain.supports_tools is False
    assert plain.supports_vision is False
    assert plain.context_length == 0
    rich = parse_model(
        {
            "id": "a/b",
            "name": "B",
            "supported_parameters": ["tools"],
            "architecture": {"input_modalities": ["image"]},
        }
    )
    assert rich.supports_tools is True
    assert rich.supports_vision is True


def test_catalogue_is_cached() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=CATALOGUE)

    client = client_with(handler)
    client.list_models()
    client.list_models()
    assert calls["n"] == 1
    client.list_models(refresh=True)
    assert calls["n"] == 2


def test_connection_test_reports_success_and_failure() -> None:
    ok = client_with(lambda request: httpx.Response(200, json=CATALOGUE)).test_connection()
    assert ok.ok and ok.model_count == 2 and ok.latency_ms >= 0

    def unauthorised(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "No auth credentials found"}})

    failed = client_with(unauthorised).test_connection()
    assert failed.ok is False
    assert failed.error_code == "provider.auth"
    assert "credentials" in failed.message


# -------------------------------------------------------------------- errors
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (402, InsufficientCreditError),
        (429, RateLimitError),
        (404, ProviderError),
        (500, ProviderError),
        (503, ProviderError),
        (400, ProviderError),
    ],
)
def test_http_errors_map_to_typed_errors(status: int, expected: type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    with pytest.raises(expected) as info:
        client_with(handler).list_models(refresh=True)
    assert info.value.message_key


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError) as info:
        client_with(lambda request: httpx.Response(200), key=None).list_models()
    assert info.value.message_key == "error.api_key_missing"


def test_network_failure_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(NetworkError):
        client_with(handler).list_models()


def test_timeout_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(TimeoutProviderError):
        client_with(handler).list_models()


def test_malformed_catalogue_is_rejected() -> None:
    with pytest.raises(ProviderError):
        client_with(lambda request: httpx.Response(200, json={"oops": 1})).list_models()


# ---------------------------------------------------------------- streaming
def test_streaming_collects_text_usage_and_timings() -> None:
    body = sse(
        delta("Hello"),
        delta(", "),
        delta("world", finish="stop"),
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["model"] == "test/model"
        assert payload["stream"] is True
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"}
        )

    result = client_with(handler).stream_chat(
        model="test/model", messages=[{"role": "user", "content": "hi"}], on_delta=seen.append
    )
    assert result.text == "Hello, world"
    assert seen == ["Hello", ", ", "world"]
    assert result.stats.prompt_tokens == 12
    assert result.stats.completion_tokens == 3
    assert result.stats.total_tokens == 15
    assert result.stats.finish_reason == "stop"
    assert result.stats.chunk_count == 3
    assert result.stats.first_token_ms >= 0
    assert result.stats.total_ms >= result.stats.first_token_ms
    assert result.cancelled is False


def test_first_token_latency_reflects_a_slow_start() -> None:
    def body():
        time.sleep(0.15)
        yield event_only(delta("slow start", finish="stop"))
        yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})

    result = client_with(handler).stream_chat(
        model="test/model", messages=[{"role": "user", "content": "hi"}]
    )
    assert result.text == "slow start"
    assert result.stats.first_token_ms >= 120
    assert result.stats.total_ms >= result.stats.first_token_ms


def test_cancellation_stops_the_stream() -> None:
    cancel = threading.Event()

    def body():
        for i in range(50):
            if cancel.is_set():
                return
            yield event_only(delta(f"chunk{i} "))
            time.sleep(0.01)
        yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body(), headers={"content-type": "text/event-stream"})

    def on_delta(text: str) -> None:
        if text.startswith("chunk3"):
            cancel.set()

    result = client_with(handler).stream_chat(
        model="test/model",
        messages=[{"role": "user", "content": "hi"}],
        cancel=cancel,
        on_delta=on_delta,
    )
    assert result.cancelled is True
    assert result.text.startswith("chunk0")
    assert "chunk49" not in result.text


def test_error_event_inside_the_stream_is_raised() -> None:
    body = sse({"error": {"message": "provider exploded"}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    with pytest.raises(ProviderError) as info:
        client_with(handler).stream_chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert "exploded" in info.value.message


def test_stream_http_error_before_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    with pytest.raises(RateLimitError):
        client_with(handler).stream_chat(model="m", messages=[{"role": "user", "content": "x"}])


def test_empty_model_is_rejected() -> None:
    with pytest.raises(ValidationError):
        client_with(lambda request: httpx.Response(200)).stream_chat(
            model="", messages=[{"role": "user", "content": "x"}]
        )


def test_keepalive_and_garbage_lines_are_ignored() -> None:
    body = b": keep-alive\n\ndata: not-json\n\ndata: " + json.dumps(delta("ok")).encode() + b"\n\ndata: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = client_with(handler).stream_chat(model="m", messages=[{"role": "user", "content": "x"}])
    assert result.text == "ok"


def test_request_carries_sampling_parameters() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200, content=sse(delta("x", finish="stop")), headers={"content-type": "text/event-stream"}
        )

    client_with(handler).stream_chat(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        temperature=0.25,
        max_tokens=512,
        top_p=0.9,
    )
    assert captured["temperature"] == 0.25
    assert captured["max_tokens"] == 512
    assert captured["top_p"] == 0.9


def test_api_key_is_never_logged(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "denied"}})

    with caplog.at_level("DEBUG"):
        with pytest.raises(AuthenticationError):
            client_with(handler).list_models(refresh=True)
    assert "sk-or-v1-test" not in caplog.text


# --------------------------------------------------------------- live (opt-in)
@pytest.mark.skipif(
    not os.environ.get("MYAI_LIVE_API_KEY"),
    reason="live API test: set MYAI_LIVE_API_KEY to run against openrouter.ai",
)
def test_live_openrouter_roundtrip() -> None:
    """Only runs with a real key AND network access; never part of CI."""
    client = OpenRouterClient(lambda: os.environ["MYAI_LIVE_API_KEY"])
    models = client.list_models(refresh=True)
    assert models
    result = client.stream_chat(
        model=models[0].id,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_tokens=8,
    )
    assert result.text.strip()
    assert result.stats.total_ms > 0
