"""Agent Mode: a bounded loop around validated tools.

The model proposes tool calls; this service validates the arguments, asks the
caller for confirmation on anything that writes, executes or reaches the
network, runs the tool, feeds the real result back, and stops at the configured
step limit. Nothing here can invent a tool result or bypass the registry.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import AppError, CancelledError, ValidationError
from ..core.events import Events, SignalBus
from ..core.timeutil import utcnow
from .activity import ActivityService
from .chat import ChatService
from .openrouter import ChatResult
from .settings import SettingsService
from .tools import (
    SENSITIVE,
    ToolContext,
    ToolDenied,
    ToolRegistry,
    ToolSpec,
    ToolUnavailable,
    describe_for_prompt,
)

logger = logging.getLogger(__name__)

MAX_STEPS_RANGE = (1, 50)
MAX_TOOL_MESSAGE = 8_000

SYSTEM_PROMPT = """You are the agent inside MyAI Studio Ultimate, a local-first desktop app.

Rules:
1. Act only through the tools listed below. Never invent file contents, command
   output or web results; if a tool fails, say what failed.
2. Read before you write. Prefer the smallest change that solves the task.
3. Paths are relative to the opened project folder. Never use absolute paths or '..'.
4. Tools marked unavailable cannot run on this machine. Say so; do not pretend.
5. When the task is complete, answer without calling a tool, in the user's language.
6. A declined tool call is a decision by the user, not an error to work around."""


@dataclass
class ToolRun:
    call_id: str
    tool_id: str
    risk: str
    arguments: dict[str, Any]
    approved: bool | None = None
    ok: bool = False
    output: str = ""
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "risk": self.risk,
            "arguments": self.arguments,
            "approved": self.approved,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentStep:
    index: int
    kind: str  # thinking | tool | denied | error | final
    text: str = ""
    tool: ToolRun | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "text": self.text,
            "tool": self.tool.to_dict() if self.tool else None,
        }


@dataclass
class AgentRun:
    id: str
    task: str
    model_id: str
    status: str = "running"  # ok | cancelled | limit | error
    steps: list[AgentStep] = field(default_factory=list)
    final_text: str = ""
    project: str = ""
    error: dict[str, Any] | None = None
    started_at: str = field(default_factory=lambda: utcnow().isoformat())
    duration_ms: int = 0
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_count(self) -> int:
        """Every tool the model called, including failed and declined ones."""
        return sum(1 for step in self.steps if step.tool is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "model_id": self.model_id,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "final_text": self.final_text,
            "error": self.error,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "tool_count": self.tool_count,
            "project": self.project,
            "usage": self.usage,
        }


Confirm = Callable[[ToolSpec, dict[str, Any]], bool]


class AgentService:
    def __init__(
        self,
        *,
        chat: ChatService,
        tools: ToolRegistry,
        settings: SettingsService,
        bus: SignalBus,
        activity: ActivityService | None = None,
    ) -> None:
        self._chat = chat
        self._tools = tools
        self._settings = settings
        self._bus = bus
        self._activity = activity
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._active = False
        self._history: list[AgentRun] = []
        self._recorder: Callable[[AgentRun], object] | None = None

    # ------------------------------------------------------------------ state
    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def is_running(self) -> bool:
        return self._active

    def cancel(self) -> None:
        self._cancel.set()

    def set_recorder(self, recorder: Callable[[AgentRun], object] | None) -> None:
        """Register the task-centre sink; a failing sink must never break a run."""
        self._recorder = recorder

    def history(self, limit: int = 20) -> list[AgentRun]:
        return list(self._history[:limit])

    def max_steps(self) -> int:
        value = self._settings.get("agent.max_steps", 12)
        try:
            steps = int(value)
        except (TypeError, ValueError):
            return 12
        return max(MAX_STEPS_RANGE[0], min(MAX_STEPS_RANGE[1], steps))

    # -------------------------------------------------------------------- run
    def run(
        self,
        task: str,
        *,
        model_id: str,
        context: ToolContext,
        confirm: Confirm | None = None,
        cancel: threading.Event | None = None,
        on_step: Callable[[AgentStep], None] | None = None,
        on_delta: Callable[[str], None] | None = None,
        history: list[dict[str, Any]] | None = None,
        project: str = "",
    ) -> AgentRun:
        text = (task or "").strip()
        if not text:
            raise ValidationError("Task is empty", message_key="error.empty_task")
        if not model_id or not str(model_id).strip():
            raise ValidationError("No model selected", message_key="error.no_model")

        with self._lock:
            if self._active:
                raise ValidationError("An agent run is already active", message_key="error.busy")
            self._active = True
            self._cancel.clear()

        cancel_event = self._cancel if cancel is None else cancel
        previous_cancel = context.cancel
        context.cancel = cancel_event
        run = AgentRun(id=uuid.uuid4().hex, task=text, model_id=model_id, project=project)
        started = time.perf_counter()
        messages = self._initial_messages(text, context, history)
        tools_payload = self._tools.to_openai(context)
        require_confirmation = bool(self._settings.get("agent.require_confirmation", True))
        steps = self.max_steps()

        self._bus.emit(Events.AGENT_STARTED, run_id=run.id, task=text, model_id=model_id)
        try:
            client = self._chat.client()
            for index in range(1, steps + 1):
                if cancel_event.is_set():
                    run.status = "cancelled"
                    break
                result: ChatResult = client.stream_chat(
                    model=model_id,
                    messages=messages,
                    temperature=float(self._settings.get("ai.temperature", 0.7)),
                    max_tokens=int(self._settings.get("ai.max_tokens", 4096)),
                    cancel=cancel_event,
                    on_delta=on_delta,
                    tools=tools_payload or None,
                )
                run.usage = result.stats.to_dict()
                if result.cancelled:
                    run.status = "cancelled"
                    run.final_text = result.text.strip()
                    break
                if result.text.strip() and result.tool_calls:
                    # Narration before a tool call is a thought, not the answer.
                    step = AgentStep(index=index, kind="thinking", text=result.text.strip())
                    self._append(run, step, on_step)
                if not result.tool_calls:
                    run.status = "ok"
                    run.final_text = result.text.strip()
                    self._append(run, AgentStep(index=index, kind="final", text=run.final_text), on_step)
                    break

                messages.append(self._assistant_message(result))
                for call in result.tool_calls:
                    tool_run = self._execute_call(
                        call_id=call.id,
                        name=call.name,
                        raw_arguments=call.arguments,
                        context=context,
                        confirm=confirm,
                        require_confirmation=require_confirmation,
                        cancel_event=cancel_event,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id or tool_run.call_id,
                            "content": self._tool_message(tool_run),
                        }
                    )
                    kind = (
                        "denied"
                        if tool_run.approved is False
                        else ("tool" if tool_run.ok else "error")
                    )
                    self._append(
                        run,
                        AgentStep(index=index, kind=kind, text=tool_run.error or "", tool=tool_run),
                        on_step,
                    )
                    self._bus.emit(
                        Events.AGENT_TOOL_FINISHED,
                        run_id=run.id,
                        tool=tool_run.to_dict(),
                    )
                    if cancel_event.is_set():
                        break
            else:
                run.status = "limit"
                run.final_text = ""

            if run.status == "running":  # cancelled inside the tool loop
                run.status = "cancelled"
        except CancelledError:
            run.status = "cancelled"
        except AppError as exc:
            run.status = "error"
            run.error = exc.to_dict()
            self._append(run, AgentStep(index=len(run.steps) + 1, kind="error", text=exc.message), on_step)
            logger.warning("agent_failed code=%s", exc.code)
        except Exception as exc:  # noqa: BLE001 - never leak a traceback into the UI
            logger.exception("agent_unexpected_error")
            run.status = "error"
            run.error = {"code": "agent.error", "message": "The agent stopped unexpectedly.",
                         "details": type(exc).__name__}
            self._append(
                run,
                AgentStep(index=len(run.steps) + 1, kind="error",
                          text=f"The agent stopped unexpectedly ({type(exc).__name__})."),
                on_step,
            )
        finally:
            context.cancel = previous_cancel
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            with self._lock:
                self._active = False
            self._cancel.clear()
            self._history.insert(0, run)
            del self._history[20:]
            if self._recorder is not None:
                try:
                    self._recorder(run)
                except Exception:  # noqa: BLE001 - persistence must not kill the run
                    logger.exception("agent_run_not_recorded")
            self._bus.emit(Events.AGENT_FINISHED, run=run.to_dict())
            if self._activity is not None:
                self._activity.record(
                    key="agent.activity_run",
                    kwargs={
                        "status_key": f"agent.status_{run.status}",
                        "tools": run.tool_count,
                    },
                    kind="agent",
                )
            logger.info(
                "agent_run_done status=%s steps=%s tools=%s ms=%s",
                run.status, len(run.steps), run.tool_count, run.duration_ms,
            )
        return run

    # ---------------------------------------------------------------- helpers
    def _initial_messages(
        self,
        task: str,
        context: ToolContext,
        history: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        system = SYSTEM_PROMPT + "\n\n" + describe_for_prompt(self._tools, context)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for item in (history or [])[-12:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": task})
        return messages

    @staticmethod
    def _assistant_message(result: ChatResult) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": result.text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments or "{}"},
                }
                for call in result.tool_calls
            ],
        }

    def _execute_call(
        self,
        *,
        call_id: str,
        name: str,
        raw_arguments: str,
        context: ToolContext,
        confirm: Confirm | None,
        require_confirmation: bool,
        cancel_event: threading.Event,
    ) -> ToolRun:
        spec = self._tools.get(name)
        tool_run = ToolRun(
            call_id=call_id or uuid.uuid4().hex,
            tool_id=name,
            risk=spec.risk if spec else "unknown",
            arguments={},
        )
        self._bus.emit(
            Events.AGENT_TOOL_STARTED,
            tool=name,
            call_id=tool_run.call_id,
            risk=tool_run.risk,
            arguments=raw_arguments,
        )
        started = time.perf_counter()
        try:
            if spec is not None:
                import json as _json

                try:
                    arguments = _json.loads(raw_arguments or "{}")
                except _json.JSONDecodeError as exc:
                    raise ValidationError(
                        f"{name}: arguments are not valid JSON ({exc.msg})",
                        message_key="agent.bad_arguments",
                    ) from exc
                if not isinstance(arguments, dict):
                    raise ValidationError(
                        f"{name}: arguments must be a JSON object",
                        message_key="agent.bad_arguments",
                    )
                tool_run.arguments = arguments
                wrapped_confirm: Confirm | None = None
                if confirm is not None and spec.risk in SENSITIVE and require_confirmation:
                    def wrapped_confirm(spec_: ToolSpec, args: dict[str, Any]) -> bool:
                        approved = bool(confirm(spec_, args))
                        tool_run.approved = approved
                        return approved
                result = self._tools.execute(
                    name,
                    tool_run.arguments,
                    context,
                    confirm=wrapped_confirm,
                    require_confirmation=require_confirmation,
                )
                tool_run.ok = result.ok
                tool_run.output = result.output
                if tool_run.approved is None and spec.risk not in SENSITIVE:
                    tool_run.approved = True
            else:
                raise ValidationError(f"Unknown tool '{name}'", message_key="agent.unknown_tool")
        except ToolDenied as exc:
            tool_run.approved = False
            tool_run.ok = False
            tool_run.error = exc.message
        except ToolUnavailable as exc:
            tool_run.ok = False
            tool_run.error = f"Unavailable: {exc.message}"
        except AppError as exc:
            tool_run.ok = False
            tool_run.error = exc.message
        except Exception as exc:  # noqa: BLE001 - the loop must survive a bad tool
            logger.exception("agent_tool_crashed tool=%s", name)
            tool_run.ok = False
            tool_run.error = f"The tool failed unexpectedly ({type(exc).__name__})."
        finally:
            tool_run.duration_ms = int((time.perf_counter() - started) * 1000)
            if cancel_event.is_set():
                tool_run.error = tool_run.error or "Cancelled."
        return tool_run

    @staticmethod
    def _tool_message(tool_run: ToolRun) -> str:
        if tool_run.ok:
            return tool_run.output[:MAX_TOOL_MESSAGE] or "(no output)"
        prefix = "DECLINED" if tool_run.approved is False else "ERROR"
        return f"{prefix}: {tool_run.error}"[:MAX_TOOL_MESSAGE]

    def _append(
        self,
        run: AgentRun,
        step: AgentStep,
        on_step: Callable[[AgentStep], None] | None,
    ) -> None:
        run.steps.append(step)
        if on_step is not None:
            on_step(step)
        self._bus.emit(Events.AGENT_STEP, run_id=run.id, step=step.to_dict())
