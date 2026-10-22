"""Agent loop: validation → confirmation → real execution → feedback.

The provider is scripted (the network is unreachable in this sandbox) but every
tool call runs the real handler against the temporary workspace, so these tests
prove the loop's ordering, its gates and its honesty about failures.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from myai.core.errors import RateLimitError, ValidationError
from myai.core.events import Events
from myai.services.agent import AgentService, AgentStep
from myai.services.openrouter import ChatResult, StreamStats, ToolCall
from myai.services.projects import ProjectService
from myai.services.runner import Runner
from myai.services.tools import ToolContext, ToolDenied, registry


class FakeChat:
    def __init__(self, client) -> None:  # noqa: ANN001
        self._client = client

    def client(self):  # noqa: ANN201
        return self._client


class ScriptedClient:
    """Returns prepared results (or raises) and records every request."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[dict] = []

    def stream_chat(self, **kwargs):  # noqa: ANN201
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(kwargs)
        return item


def answer(text: str) -> ChatResult:
    return ChatResult(text=text, stats=StreamStats(completion_tokens=3, total_tokens=9))


def call(name: str, arguments: dict | str = "{}", *, call_id: str = "call_1",
         text: str = "") -> ChatResult:
    payload = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ChatResult(
        text=text,
        stats=StreamStats(finish_reason="tool_calls"),
        tool_calls=[ToolCall(id=call_id, name=name, arguments=payload)],
    )


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    root = tmp_path / "agent-project"
    root.mkdir()
    (root / "app.py").write_text("print('agent ran me')\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\n", encoding="utf-8")
    return root


@pytest.fixture()
def service(ctx, workdir: Path, monkeypatch: pytest.MonkeyPatch):
    projects = ProjectService(ctx.paths, ctx.settings)
    project = projects.open_folder(workdir)
    tool_context = ToolContext(
        projects=projects,
        project=project,
        runner=Runner(),
        memory=ctx.memory,
        outputs=ctx.outputs,
        settings=ctx.settings,
        secrets=ctx.secrets,
    )
    holder: dict = {}

    def build(script: list) -> tuple[AgentService, ScriptedClient]:
        client = ScriptedClient(script)
        agent = AgentService(
            chat=FakeChat(client),  # type: ignore[arg-type]
            tools=registry(),
            settings=ctx.settings,
            bus=ctx.bus,
            activity=ctx.activity,
        )
        holder["agent"] = agent
        return agent, client

    yield build, tool_context, holder


def run_agent(build, tool_context, script, *, confirm=None, task="Read app.py", **kwargs):  # noqa: ANN001
    agent, client = build(script)
    run = agent.run(
        task,
        model_id="test/model",
        context=tool_context,
        confirm=confirm,
        **kwargs,
    )
    return run, client, agent


# --------------------------------------------------------------------- happy
def test_tool_round_trip_then_final_answer(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, client, _ = run_agent(
        build,
        context,
        [call("read_file", {"path": "app.py"}), answer("The file prints a line.")],
    )
    assert run.status == "ok"
    assert run.final_text == "The file prints a line."
    assert [step.kind for step in run.steps] == ["tool", "final"]
    tool_step = run.steps[0]
    assert tool_step.tool is not None
    assert tool_step.tool.ok is True
    assert "agent ran me" in tool_step.tool.output
    assert tool_step.tool.approved is True
    assert len(client.requests) == 2
    assert run.tool_count == 1


def test_tool_schemas_are_sent_on_every_turn(service) -> None:  # noqa: ANN001
    build, context, _ = service
    _run, client, _ = run_agent(build, context, [call("list_files"), answer("ok")])
    for request in client.requests:
        names = [row["function"]["name"] for row in request["tools"]]
        assert "read_file" in names
        assert "generate_image" not in names


def test_messages_carry_the_assistant_call_and_the_tool_result(service) -> None:  # noqa: ANN001
    build, context, _ = service
    _run, client, _ = run_agent(build, context, [call("read_file", {"path": "notes.md"}, call_id="abc"),
                                                answer("done")])
    second = client.requests[1]["messages"]
    assistant = second[-2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "abc"
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    tool_message = second[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "abc"
    assert "# Notes" in tool_message["content"]
    assert second[0]["role"] == "system"
    assert "read_file" in second[0]["content"]
    assert second[-3]["role"] == "user"


def test_narration_before_a_tool_call_is_kept_as_a_thought(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build,
        context,
        [call("list_files", text="Looking at the folder first."), answer("Done.")],
    )
    assert [step.kind for step in run.steps] == ["thinking", "tool", "final"]
    assert run.steps[0].text == "Looking at the folder first."


def test_history_from_the_chat_is_replayed(service) -> None:  # noqa: ANN001
    build, context, _ = service
    _run, client, _ = run_agent(
        build,
        context,
        [answer("ok")],
        history=[{"role": "user", "content": "earlier question"},
                 {"role": "assistant", "content": "earlier answer"}],
    )
    roles = [message["role"] for message in client.requests[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_usage_is_recorded_on_the_run(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(build, context, [answer("ok")])
    assert run.usage["total_tokens"] == 9
    assert run.duration_ms >= 0


# --------------------------------------------------------------- confirmation
def test_confirmation_is_requested_for_a_write(service) -> None:  # noqa: ANN001
    build, context, _ = service
    asked: list[str] = []

    def confirm(tool, arguments):  # noqa: ANN001
        asked.append(tool.id)
        assert arguments == {"path": "new.txt", "content": "hello"}
        return True

    run, _client, _ = run_agent(
        build,
        context,
        [call("write_file", {"path": "new.txt", "content": "hello"}), answer("written")],
        confirm=confirm,
    )
    assert asked == ["write_file"]
    assert run.status == "ok"
    assert (context.project.root / "new.txt").read_text(encoding="utf-8") == "hello"


def test_a_declined_write_is_not_executed_and_is_reported(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, client, _ = run_agent(
        build,
        context,
        [call("write_file", {"path": "denied.txt", "content": "x"}), answer("Understood.")],
        confirm=lambda tool, arguments: False,
    )
    assert not (context.project.root / "denied.txt").exists()
    denied = run.steps[0]
    assert denied.kind == "denied"
    assert denied.tool is not None and denied.tool.approved is False
    assert "declined" in (denied.tool.error or "").lower()
    assert client.requests[1]["messages"][-1]["content"].startswith("DECLINED")


def test_confirmation_is_skipped_when_the_setting_is_off(service) -> None:  # noqa: ANN001
    build, context, _ = service
    context.settings.update({"agent.require_confirmation": False})
    run, _client, _ = run_agent(
        build,
        context,
        [call("write_file", {"path": "auto.txt", "content": "x"}), answer("ok")],
    )
    assert run.status == "ok"
    assert (context.project.root / "auto.txt").exists()


def test_confirmation_is_never_requested_for_a_read(service) -> None:  # noqa: ANN001
    build, context, _ = service
    asked: list[str] = []

    def confirm(tool, arguments):  # noqa: ANN001, ARG001
        asked.append(tool.id)
        return False

    run, _client, _ = run_agent(build, context, [call("read_file", {"path": "app.py"}),
                                                 answer("ok")], confirm=confirm)
    assert asked == []
    assert run.steps[0].tool is not None and run.steps[0].tool.ok is True


def test_a_missing_confirmation_channel_becomes_a_denial(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build,
        context,
        [call("delete_file", {"path": "notes.md"}), answer("stopped")],
    )
    assert (context.project.root / "notes.md").exists()
    assert run.steps[0].kind == "denied"


# -------------------------------------------------------------------- limits
def test_step_limit_stops_a_loop_that_never_finishes(service) -> None:  # noqa: ANN001
    build, context, _ = service
    context.settings.update({"agent.max_steps": 2})
    run, client, _ = run_agent(build, context, [call("list_files"), call("list_files")])
    assert run.status == "limit"
    assert run.final_text == ""
    assert len(client.requests) == 2
    assert len([step for step in run.steps if step.kind == "tool"]) == 2


def test_max_steps_is_clamped_to_the_supported_range(ctx) -> None:  # noqa: ANN001
    class StubSettings:
        def __init__(self, value: object) -> None:
            self.value = value

        def get(self, key: str, default=None):  # noqa: ANN001, ANN201
            return self.value if key == "agent.max_steps" else default

    def agent_with(value: object) -> AgentService:
        return AgentService(
            chat=FakeChat(ScriptedClient([])),  # type: ignore[arg-type]
            tools=registry(),
            settings=StubSettings(value),  # type: ignore[arg-type]
            bus=ctx.bus,
        )

    assert agent_with(12).max_steps() == 12
    assert agent_with(99).max_steps() == 50
    assert agent_with(0).max_steps() == 1
    assert agent_with("not a number").max_steps() == 12
    with pytest.raises(ValidationError):
        ctx.settings.update({"agent.max_steps": 99})


def test_cancel_before_the_first_call_never_touches_the_provider(service) -> None:  # noqa: ANN001
    build, context, _ = service
    cancel = threading.Event()
    cancel.set()
    run, client, _ = run_agent(build, context, [answer("ok")], cancel=cancel)
    assert run.status == "cancelled"
    assert client.requests == []


def test_cancel_after_a_tool_stops_before_the_next_turn(service) -> None:  # noqa: ANN001
    build, context, _ = service
    cancel = threading.Event()

    def confirm(tool, arguments):  # noqa: ANN001, ARG001
        cancel.set()
        return True

    run, client, _ = run_agent(
        build,
        context,
        [call("write_file", {"path": "x.txt", "content": "x"}), answer("never")],
        confirm=confirm,
        cancel=cancel,
    )
    assert run.status == "cancelled"
    assert len(client.requests) == 1
    assert (context.project.root / "x.txt").exists()


def test_cancelled_stream_is_reported(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build,
        context,
        [ChatResult(text="partial", cancelled=True)],
    )
    assert run.status == "cancelled"
    assert run.final_text == "partial"


# -------------------------------------------------------------------- errors
def test_provider_failure_is_typed_and_visible(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build,
        context,
        [RateLimitError("Slow down", message_key="error.rate_limit")],
    )
    assert run.status == "error"
    assert run.error is not None and run.error["code"] == "provider.rate_limit"
    assert run.steps[-1].kind == "error"
    assert "Slow down" in run.steps[-1].text


def test_unexpected_crash_is_contained(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(build, context, [RuntimeError("boom")])
    assert run.status == "error"
    assert run.error is not None and run.error["code"] == "agent.error"
    assert "RuntimeError" in (run.steps[-1].text or "")


def test_unknown_tool_is_an_error_step_and_the_loop_continues(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, client, _ = run_agent(
        build, context, [call("format_disk", {}), answer("I cannot do that.")]
    )
    assert run.status == "ok"
    assert run.steps[0].kind == "error"
    assert "Unknown tool" in run.steps[0].text
    assert client.requests[1]["messages"][-1]["content"].startswith("ERROR")


def test_invalid_json_arguments_are_reported_before_any_execution(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build, context, [call("write_file", '{"path": "x.txt", '), answer("retry")]
    )
    assert run.steps[0].kind == "error"
    assert "JSON" in (run.steps[0].text or "")
    assert not (context.project.root / "x.txt").exists()


def test_tool_failure_reaches_the_model_verbatim(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, client, _ = run_agent(
        build, context, [call("read_file", {"path": "ghost.py"}), answer("It is missing.")]
    )
    assert run.steps[0].kind == "error"
    assert "ghost.py" in run.steps[0].text
    assert "ghost.py" in client.requests[1]["messages"][-1]["content"]


def test_unavailable_tool_is_reported_as_unavailable(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, _client, _ = run_agent(
        build, context, [call("web_search", {"query": "x"}), answer("No network.")]
    )
    assert run.steps[0].kind == "error"
    assert "Unavailable" in (run.steps[0].text or "")
    assert "Network access is disabled" in (run.steps[0].text or "")


# --------------------------------------------------------------- validation
def test_empty_task_is_rejected(service) -> None:  # noqa: ANN001
    build, context, _ = service
    agent, _client = build([])
    with pytest.raises(ValidationError):
        agent.run("   ", model_id="m", context=context)


def test_missing_model_is_rejected(service) -> None:  # noqa: ANN001
    build, context, _ = service
    agent, _client = build([])
    with pytest.raises(ValidationError):
        agent.run("do something", model_id="", context=context)


def test_a_second_run_cannot_start_while_one_is_active(service) -> None:  # noqa: ANN001
    build, context, holder = service
    attempted: list[str] = []

    def reenter(kwargs):  # noqa: ANN001, ARG001
        agent = holder["agent"]
        try:
            agent.run("second", model_id="m", context=context)
        except ValidationError:
            attempted.append("rejected")
        return answer("ok")

    run, _client, _ = run_agent(build, context, [reenter])
    assert run.status == "ok"
    assert attempted == ["rejected"]


# ----------------------------------------------------------------- events
def test_events_describe_the_whole_run(ctx, service) -> None:  # noqa: ANN001
    build, context, _ = service
    seen: list[str] = []
    for event in (Events.AGENT_STARTED, Events.AGENT_STEP, Events.AGENT_TOOL_STARTED,
                  Events.AGENT_TOOL_FINISHED, Events.AGENT_FINISHED):
        ctx.bus.subscribe(event, lambda event=event, **kwargs: seen.append(event))  # noqa: ARG005

    run, _client, _ = run_agent(build, context, [call("list_files"), answer("ok")])
    assert seen[0] == Events.AGENT_STARTED
    assert Events.AGENT_STEP in seen
    assert seen.count(Events.AGENT_TOOL_STARTED) == 1
    assert seen.count(Events.AGENT_TOOL_FINISHED) == 1
    assert seen[-1] == Events.AGENT_FINISHED
    assert run.status == "ok"


def test_steps_can_be_observed_live(service) -> None:  # noqa: ANN001
    build, context, _ = service
    live: list[AgentStep] = []
    run, _client, _ = run_agent(
        build, context, [call("list_files"), answer("done")], on_step=live.append
    )
    assert [step.kind for step in live] == ["tool", "final"]
    assert len(live) == len(run.steps)


def test_history_keeps_the_latest_runs(service) -> None:  # noqa: ANN001
    build, context, _ = service
    agent, _client = build([answer("1"), answer("2")])
    first = agent.run("one", model_id="m", context=context)
    second = agent.run("two", model_id="m", context=context)
    history = agent.history()
    assert [run.id for run in history][:2] == [second.id, first.id]
    assert agent.is_running is False


def test_tool_call_without_an_id_gets_a_generated_one(service) -> None:  # noqa: ANN001
    build, context, _ = service
    run, client, _ = run_agent(
        build, context, [call("list_files", call_id=""), answer("ok")]
    )
    tool_message = client.requests[1]["messages"][-1]
    assert tool_message["tool_call_id"]
    assert run.steps[0].tool is not None and run.steps[0].tool.call_id


def test_declined_error_text_names_the_user_decision() -> None:
    from myai.services.agent import ToolRun

    run = ToolRun(call_id="1", tool_id="write_file", risk="write", arguments={}, approved=False)
    assert AgentService._tool_message(run) == "DECLINED: "
    assert ToolDenied("x").code == "tool.denied"
