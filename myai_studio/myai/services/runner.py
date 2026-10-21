"""Real program execution for Code Studio.

Every run is a real subprocess in the project directory. The service streams
stdout/stderr lines to a callback, enforces a wall-clock limit, supports
cancellation and kills the whole process group (not just the parent) so a
runaway child cannot linger. Nothing here touches Qt or the database, so it can
be called from a worker thread and tested without a window.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .toolchains import RunPlan, RunStep, ToolchainUnavailable, build_plan

logger = logging.getLogger(__name__)

#: Hard cap per stream; beyond this the output is truncated and flagged.
MAX_OUTPUT_CHARS = 200_000
#: Upper bound for the wall-clock limit accepted from settings.
MAX_TIMEOUT = 120.0
DEFAULT_TIMEOUT = 10.0

OutputCallback = Callable[[str, str], None]  # (stream, line) where stream is stdout|stderr|system


@dataclass
class StepResult:
    label: str
    kind: str
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


@dataclass
class RunResult:
    plan: RunPlan
    steps: list[StepResult] = field(default_factory=list)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    cancelled: bool = False
    truncated: bool = False

    @property
    def command(self) -> str:
        return self.plan.command

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.cancelled
            and bool(self.steps)
        )

    @property
    def status(self) -> str:
        if self.cancelled:
            return "cancelled"
        if self.timed_out:
            return "timeout"
        if not self.steps:
            return "failed"
        if self.succeeded:
            return "ok"
        return "failed"

    def to_dict(self) -> dict:
        return {
            "language": self.plan.language,
            "command": self.command,
            "exit_code": self.exit_code,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "truncated": self.truncated,
            "steps": [
                {
                    "label": step.label,
                    "kind": step.kind,
                    "argv": step.argv,
                    "exit_code": step.exit_code,
                    "duration_ms": step.duration_ms,
                    "timed_out": step.timed_out,
                    "cancelled": step.cancelled,
                }
                for step in self.steps
            ],
        }


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Never advertise the app's own environment to the program being run.
    for key in ("MYAI_LIVE_API_KEY",):
        env.pop(key, None)
    return env


def _kill_tree(process: subprocess.Popen) -> None:
    """Kill the process and every child it spawned."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":  # pragma: no cover - Windows only
            subprocess.run(  # noqa: S603,S607
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=5,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass


class Runner:
    """Execute :class:`RunPlan` objects with limits, streaming and cancellation."""

    def __init__(self, *, max_output: int = MAX_OUTPUT_CHARS) -> None:
        self.max_output = max_output

    # ------------------------------------------------------------------ public
    def plan_for(
        self,
        source: Path,
        *,
        cwd: Path,
        timeout_seconds: float | None = None,
    ) -> RunPlan:
        timeout = self._clamp_timeout(timeout_seconds)
        return build_plan(Path(source), cwd=Path(cwd), timeout_seconds=timeout)

    def run(
        self,
        plan: RunPlan,
        *,
        on_output: OutputCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RunResult:
        started = time.monotonic()
        result = RunResult(plan=plan)
        deadline = started + self._clamp_timeout(plan.timeout_seconds)

        for step in plan.steps:
            outcome = self._run_step(
                step,
                plan=plan,
                deadline=deadline,
                on_output=on_output,
                cancel_event=cancel_event,
            )
            result.steps.append(outcome)
            result.stdout += outcome.stdout
            result.stderr += outcome.stderr
            result.exit_code = outcome.exit_code
            if outcome.timed_out:
                result.timed_out = True
            if outcome.cancelled:
                result.cancelled = True
            if not outcome.succeeded:
                break

        result.duration_ms = int((time.monotonic() - started) * 1000)
        if len(result.stdout) > self.max_output or len(result.stderr) > self.max_output:
            result.truncated = True
            result.stdout = result.stdout[: self.max_output]
            result.stderr = result.stderr[: self.max_output]
        logger.info(
            "code_run language=%s status=%s exit=%s duration_ms=%s",
            plan.language,
            result.status,
            result.exit_code,
            result.duration_ms,
        )
        return result

    # ----------------------------------------------------------------- internal
    @staticmethod
    def _clamp_timeout(value: float | None) -> float:
        try:
            number = float(value) if value is not None else DEFAULT_TIMEOUT
        except (TypeError, ValueError):
            number = DEFAULT_TIMEOUT
        return max(1.0, min(MAX_TIMEOUT, number))

    def _run_step(
        self,
        step: RunStep,
        *,
        plan: RunPlan,
        deadline: float,
        on_output: OutputCallback | None,
        cancel_event: threading.Event | None,
    ) -> StepResult:
        started = time.monotonic()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        truncated = False

        def emit(stream: str, text: str) -> None:
            if on_output is not None:
                try:
                    on_output(stream, text)
                except Exception:  # noqa: BLE001 - a UI callback must not kill the run
                    logger.exception("code_run_output_callback_failed")

        emit("system", "$ " + " ".join(step.argv))

        try:
            process = subprocess.Popen(  # noqa: S603 - argv list, never a shell
                step.argv,
                cwd=str(plan.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_child_env(),
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError as exc:
            message = f"{step.argv[0]}: {exc.strerror or 'not found'}"
            stderr_parts.append(message + "\n")
            emit("stderr", message)
            return StepResult(
                label=step.label,
                kind=step.kind,
                argv=step.argv,
                exit_code=None,
                stdout="",
                stderr="".join(stderr_parts),
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        lock = threading.Lock()

        def pump(pipe, stream: str, sink: list[str]) -> None:  # noqa: ANN001
            nonlocal truncated
            try:
                for line in iter(pipe.readline, ""):
                    with lock:
                        if sum(len(part) for part in sink) < self.max_output:
                            sink.append(line)
                        else:
                            truncated = True
                    emit(stream, line.rstrip("\n"))
            except (ValueError, OSError):
                pass
            finally:
                try:
                    pipe.close()
                except OSError:
                    pass

        readers = [
            threading.Thread(target=pump, args=(process.stdout, "stdout", stdout_parts), daemon=True),
            threading.Thread(target=pump, args=(process.stderr, "stderr", stderr_parts), daemon=True),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        cancelled = False
        while True:
            if process.poll() is not None:
                break
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_tree(process)
                break
            if time.monotonic() > deadline:
                timed_out = True
                _kill_tree(process)
                break
            time.sleep(0.03)

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
        for reader in readers:
            reader.join(timeout=2)

        if timed_out:
            emit("stderr", f"[timeout] stopped after {plan.timeout_seconds:.0f}s")
        if cancelled:
            emit("stderr", "[cancelled] stopped by the user")

        return StepResult(
            label=step.label,
            kind=step.kind,
            argv=step.argv,
            exit_code=process.returncode,
            stdout="".join(stdout_parts),
            stderr="".join(stderr_parts),
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
            cancelled=cancelled,
        )


__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_OUTPUT_CHARS",
    "MAX_TIMEOUT",
    "RunResult",
    "Runner",
    "StepResult",
    "ToolchainUnavailable",
]
