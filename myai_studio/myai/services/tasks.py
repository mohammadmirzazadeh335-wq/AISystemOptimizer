"""Task centre (Phase 5).

Every row here is written **after** a real run finishes: an agent run from Phase 4
or a program run from Code Studio. The page can therefore only show work that
actually happened, with the status the run itself reported.

Phase 4 kept agent history in memory for the session; this service is the
persisted replacement, and the agent page now also records into it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select

from ..core.errors import NotFoundError, ValidationError
from ..core.events import Events, SignalBus
from ..data.db import Database
from ..data.models import TaskRun

logger = logging.getLogger(__name__)

AGENT = "agent"
CODE = "code"
KINDS = (AGENT, CODE)
STATUSES = ("ok", "error", "cancelled", "limit", "running")
MAX_TITLE = 4000


@dataclass(frozen=True)
class TaskEntry:
    id: str
    kind: str
    title: str
    status: str
    detail: str
    model_id: str
    project: str
    tool_count: int
    duration_ms: int
    steps: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None


class TaskService:
    def __init__(self, db: Database, bus: SignalBus | None = None) -> None:
        self._db = db
        self._bus = bus

    # -------------------------------------------------------------------- write
    def record(
        self,
        *,
        kind: str,
        title: str,
        status: str,
        detail: str = "",
        model_id: str = "",
        project: str = "",
        tool_count: int = 0,
        duration_ms: int = 0,
        steps: list[dict[str, Any]] | None = None,
    ) -> TaskEntry:
        if kind not in KINDS:
            raise ValidationError(f"Unknown task kind '{kind}'")
        status = status if status in STATUSES else "ok"
        with self._db.session() as session:
            row = TaskRun(
                kind=kind,
                title=str(title or "").strip()[:MAX_TITLE] or "(no task text)",
                status=status,
                detail=str(detail or "").strip(),
                model_id=str(model_id or ""),
                project=str(project or ""),
                tool_count=max(0, int(tool_count or 0)),
                duration_ms=max(0, int(duration_ms or 0)),
                steps=list(steps or []),
            )
            session.add(row)
            session.flush()
            entry = self._to_entry(row)
        if self._bus is not None:
            self._bus.emit(Events.TASK_FINISHED, task_id=entry.id, kind=kind, status=status)
        logger.info("task_recorded id=%s kind=%s status=%s", entry.id, kind, status)
        return entry

    def record_agent_run(self, run) -> TaskEntry:  # noqa: ANN001 - AgentRun duck type
        """Adapter used by ``AgentService``; keeps the service free of that import."""
        steps = []
        for step in getattr(run, "steps", []) or []:
            tool = getattr(step, "tool", None)
            steps.append(
                {
                    "index": step.index,
                    "kind": step.kind,
                    "text": (step.text or "")[:2000],
                    "tool": getattr(tool, "tool_id", "") if tool is not None else "",
                    "ok": bool(getattr(tool, "ok", True)) if tool is not None else True,
                    "error": (getattr(tool, "error", "") or "")[:600] if tool is not None else "",
                }
            )
        return self.record(
            kind=AGENT,
            title=getattr(run, "task", "") or "",
            status=getattr(run, "status", "ok"),
            detail=(getattr(run, "final_text", "") or "")[:4000],
            model_id=getattr(run, "model_id", "") or "",
            project=getattr(run, "project", "") or "",
            tool_count=int(getattr(run, "tool_count", 0) or 0),
            duration_ms=int(getattr(run, "duration_ms", 0) or 0),
            steps=steps,
        )

    def delete(self, task_id: str) -> None:
        with self._db.session() as session:
            row = session.get(TaskRun, task_id)
            if row is None:
                raise NotFoundError("Task not found")
            session.delete(row)
        if self._bus is not None:
            self._bus.emit(Events.TASK_UPDATED, action="deleted", task_id=task_id)

    def clear(self, kind: str | None = None) -> int:
        with self._db.session() as session:
            stmt = delete(TaskRun)
            if kind in KINDS:
                stmt = stmt.where(TaskRun.kind == kind)
            result = session.execute(stmt)
        count = int(result.rowcount or 0)
        if count and self._bus is not None:
            self._bus.emit(Events.TASK_UPDATED, action="cleared", kind=kind or "")
        return count

    # --------------------------------------------------------------------- read
    def list(self, kind: str | None = None, *, search: str = "", limit: int = 200) -> list[TaskEntry]:
        with self._db.session() as session:
            stmt = select(TaskRun)
            if kind in KINDS:
                stmt = stmt.where(TaskRun.kind == kind)
            term = search.strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.where(TaskRun.title.ilike(like) | TaskRun.detail.ilike(like))
            stmt = stmt.order_by(TaskRun.created_at.desc()).limit(max(1, min(limit, 1000)))
            return [self._to_entry(row) for row in session.scalars(stmt)]

    def get(self, task_id: str) -> TaskEntry:
        with self._db.session() as session:
            row = session.get(TaskRun, task_id)
            if row is None:
                raise NotFoundError("Task not found")
            return self._to_entry(row)

    def count(self, kind: str | None = None) -> int:
        with self._db.session() as session:
            stmt = select(func.count()).select_from(TaskRun)
            if kind in KINDS:
                stmt = stmt.where(TaskRun.kind == kind)
            return int(session.scalar(stmt) or 0)

    def summary(self) -> dict[str, int]:
        with self._db.session() as session:
            rows = session.execute(
                select(TaskRun.kind, TaskRun.status, func.count()).group_by(TaskRun.kind, TaskRun.status)
            ).all()
        summary: dict[str, int] = {"agent": 0, "code": 0, "ok": 0, "error": 0, "cancelled": 0, "limit": 0}
        for kind, status, count in rows:
            summary[kind] = summary.get(kind, 0) + int(count)
            summary[status] = summary.get(status, 0) + int(count)
        return summary

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _to_entry(row: TaskRun) -> TaskEntry:
        return TaskEntry(
            id=row.id,
            kind=row.kind,
            title=row.title or "",
            status=row.status or "ok",
            detail=row.detail or "",
            model_id=row.model_id or "",
            project=row.project or "",
            tool_count=int(row.tool_count or 0),
            duration_ms=int(row.duration_ms or 0),
            steps=list(row.steps or []),
            created_at=row.created_at,
        )
