"""OpenRouter tool-calling support.

The provider still cannot be reached from this sandbox, so the wire format is
verified against a real ``httpx.MockTransport``: the request must carry the tool
schemas, and streamed ``tool_calls`` fragments must be reassembled instead of
dropped.
"""

from __future__ import annotations

import json

import httpx
import pytest

from myai.core.errors import ValidationError
from myai.services.openrouter import OpenRouterClient, ToolCall

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                           "required": ["path"]},
        },
    }
]


def client_with(handler) -> OpenRouterClient:  # noqa: ANN001
    return OpenRouterClient(
        lambda: "sk-or-v1-test",
        base_url="https://openrouter.example/api/v1",
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )


def stream_body(*events: dict) -> bytes:
    text = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return (text + "data: [DONE]\n\n").encode()


def call_delta(index: int, *, call_id: str | None = None, name: str | None = None,
               arguments: str | None = None) -> dict:
    function: dict = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    call: dict = {"index": index, "function": function}
    if call_id is not None:
        call["id"] = call_id
        call["type"] = "function"
    return {"choices": [{"delta": {"tool_calls": [call]}, "finish_reason": None}]}


def test_tools_and_choice_are_sent_only_when_supplied() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=stream_body({"choices": [{"delta": {"content": "ok"}}]}),
                              headers={"content-type": "text/event-stream"})

    client = client_with(handler)
    client.stream_chat(model="m", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
    client.stream_chat(model="m", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                       tool_choice="auto")
    client.stream_chat(model="m", messages=[{"role": "user", "content": "hi"}])

    assert seen[0]["tools"] == TOOLS
    assert "tool_choice" not in seen[0]
    assert seen[1]["tool_choice"] == "auto"
    assert "tools" not in seen[2]


def test_streamed_tool_call_fragments_are_reassembled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        body = stream_body(
            call_delta(0, call_id="call_1", name="read_file", arguments='{"pa'),
            call_delta(0, arguments='th": "main.py"}'),
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = client_with(handler).stream_chat(
        model="m", messages=[{"role": "user", "content": "x"}], tools=TOOLS
    )
    assert result.text == ""
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert (call.id, call.name) == ("call_1", "read_file")
    assert call.parsed() == {"path": "main.py"}
    assert result.stats.finish_reason == "tool_calls"
    assert result.to_dict()["tool_calls"][0]["name"] == "read_file"


def test_parallel_tool_calls_keep_their_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        body = stream_body(
            call_delta(0, call_id="a", name="list_files", arguments="{}"),
            call_delta(1, call_id="b", name="read_file", arguments='{"path": "x"}'),
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = client_with(handler).stream_chat(
        model="m", messages=[{"role": "user", "content": "x"}], tools=TOOLS
    )
    assert [call.id for call in result.tool_calls] == ["a", "b"]
    assert [call.name for call in result.tool_calls] == ["list_files", "read_file"]


def test_text_and_tool_calls_can_arrive_in_one_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        body = stream_body(
            {"choices": [{"delta": {"content": "Checking the file. "}}]},
            call_delta(0, call_id="c1", name="read_file", arguments='{"path": "a.txt"}'),
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = client_with(handler).stream_chat(
        model="m", messages=[{"role": "user", "content": "x"}], tools=TOOLS
    )
    assert result.text == "Checking the file. "
    assert result.tool_calls[0].parsed() == {"path": "a.txt"}


def test_malformed_tool_arguments_raise_a_typed_error() -> None:
    call = ToolCall(id="x", name="read_file", arguments='{"path": ')
    with pytest.raises(ValidationError) as excinfo:
        call.parsed()
    assert excinfo.value.message_key == "agent.bad_arguments"


def test_non_object_tool_arguments_are_rejected() -> None:
    call = ToolCall(id="x", name="read_file", arguments='["a", "b"]')
    with pytest.raises(ValidationError):
        call.parsed()


def test_cancellation_keeps_the_calls_received_so_far() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        body = stream_body(
            call_delta(0, call_id="a", name="list_files", arguments="{}"),
            {"choices": [{"delta": {"content": "more"}}]},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    import threading

    cancel = threading.Event()

    def stop_after_first(content: str) -> None:  # noqa: ARG001
        cancel.set()

    result = client_with(handler).stream_chat(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        tools=TOOLS,
        cancel=cancel,
        on_delta=stop_after_first,
    )
    assert result.cancelled is True
    assert [call.name for call in result.tool_calls] == ["list_files"]
