"""Task centre (Phase 5).

Every row is a real finished run persisted by ``TaskService``: an agent run from
Phase 4 (now durable instead of session-only) or a program run from Code Studio.
The page can filter, search, inspect the recorded steps and delete a record; it
never fabricates a task.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...core.timeutil import relative_time
from ...i18n import current_language, tr
from ...services.tasks import AGENT, CODE, TaskEntry
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import SearchField, SelectField
from ..widgets.foundation import Badge, ElidedLabel
from .page_base import PageShell, ghost_button, secondary_button

logger = logging.getLogger(__name__)

def _duration(duration_ms: int) -> str:
    """Under a second the integer second count would read as a fake 0s."""
    ms = max(0, int(duration_ms))
    if ms < 1000:
        return tr("tasks.duration_ms", ms=ms)
    return tr("tasks.duration", seconds=round(ms / 1000, 1))


STATUS_TONE = {
    "ok": "success",
    "error": "danger",
    "cancelled": "warning",
    "limit": "violet",
    "running": "warning",
}


class TaskRow(QFrame):
    open_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, entry: TaskEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("TaskRow")
        self.setProperty("panel", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(14), runtime.px(10), runtime.px(12), runtime.px(10))
        layout.setSpacing(runtime.px(5))

        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px("sparkles" if entry.kind == AGENT else "terminal", 13, "muted"))
        head.addWidget(icon)
        title = QLabel(entry.title or tr("tasks.untitled"))
        title.setProperty("role", "muted")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        head.addWidget(Badge(tr(f"tasks.kind_{entry.kind}"), "muted"))
        head.addWidget(Badge(tr(f"agent.status_{entry.status}") if entry.status in
                             {"ok", "error", "cancelled", "limit"} else entry.status,
                             STATUS_TONE.get(entry.status, "muted")))
        layout.addLayout(head)

        meta_bits = [
            relative_time(entry.created_at, current_language()) if entry.created_at else "",
            tr("tasks.tools", count=entry.tool_count) if entry.kind == AGENT else "",
            _duration(entry.duration_ms),
        ]
        meta = QLabel(" · ".join(bit for bit in meta_bits if bit))
        meta.setProperty("role", "faint")
        layout.addWidget(meta)

        if entry.project:
            project = ElidedLabel(entry.project, pixel_size=11, weight=400, tone="faint")
            layout.addWidget(project)

        self.details = QLabel("")
        self.details.setProperty("role", "faint")
        self.details.setWordWrap(True)
        self.details.setVisible(False)
        layout.addWidget(self.details)

        footer = QHBoxLayout()
        footer.setSpacing(runtime.px(6))
        footer.addStretch(1)
        self.toggle = ghost_button(tr("tasks.show_steps"), "activity")
        self.toggle.setAccessibleName(tr("tasks.show_steps"))
        self.toggle.clicked.connect(self._toggle)
        footer.addWidget(self.toggle)
        remove = ghost_button("", "trash")
        remove.setAccessibleName(tr("tasks.delete"))
        remove.setToolTip(tr("tasks.delete"))
        remove.clicked.connect(lambda: self.delete_requested.emit(self.entry.id))
        footer.addWidget(remove)
        layout.addLayout(footer)

    def _toggle(self) -> None:
        visible = not self.details.isVisible()
        if visible and not self.details.text():
            self.details.setText(self._describe())
        self.details.setVisible(visible)
        self.toggle.setText(tr("tasks.hide_steps") if visible else tr("tasks.show_steps"))

    def _describe(self) -> str:
        lines: list[str] = []
        for step in self.entry.steps:
            kind = str(step.get("kind") or "")
            text = " ".join(str(step.get("text") or "").split())[:220]
            tool = step.get("tool")
            prefix = tr(f"agent.kind_{kind}") if kind in {"thinking", "final", "error", "denied"} else (
                tr("agent.kind_tool") if tool else kind
            )
            mark = "✓" if step.get("ok", True) else "✕"
            lines.append(f"{mark} {prefix}" + (f" · {tool}" if tool else "") + f" — {text}")
        if not lines:
            lines.append(tr("tasks.no_steps"))
        if self.entry.detail:
            lines.append("")
            lines.append(self.entry.detail[:800])
        return "\n".join(lines)


class TasksPage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("tasks.title", "tasks.subtitle", icon_name="list-check")
        self.context = context
        self.service = context.tasks
        self._kind = ""
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(runtime.px(8))
        self.search = SearchField(tr("tasks.search"))
        self.search.text_changed.connect(lambda _text: self.refresh())
        bar.addWidget(self.search, 1)
        self.kind_select = SelectField(
            [("", tr("tasks.all")), (AGENT, tr("tasks.kind_agent")), (CODE, tr("tasks.kind_code"))],
            placeholder=tr("tasks.all"),
            compact=True,
        )
        self.kind_select.value_changed.connect(self._on_kind)
        bar.addWidget(self.kind_select)
        self.clear_button = secondary_button(tr("tasks.clear"), "trash")
        self.clear_button.clicked.connect(self.clear_all)
        bar.addWidget(self.clear_button)
        holder = QWidget()
        holder.setLayout(bar)
        self.add_widget(holder)

        self.summary = QHBoxLayout()
        self.summary.setSpacing(runtime.px(6))
        self.summary_widget = QWidget()
        self.summary_widget.setLayout(self.summary)
        self.add_widget(self.summary_widget)

        self.empty = QLabel("")
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        self.add_widget(self.empty)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(runtime.px(8))
        self.list_layout.addStretch(1)
        self.add_widget(self.list_host)

    def _on_kind(self, value: str) -> None:
        self._kind = value
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        entries = self.service.list(self._kind or None, search=self.search.text())
        summary = self.service.summary()
        while self.summary.count():
            item = self.summary.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for label_key, count, tone in (
            ("tasks.summary_agent", summary.get(AGENT, 0), "accent"),
            ("tasks.summary_code", summary.get(CODE, 0), "violet"),
            ("tasks.summary_failed", summary.get("error", 0), "danger"),
        ):
            badge = Badge(tr(label_key, count=count), tone if count else "muted")
            self.summary.addWidget(badge)
        self.summary.addStretch(1)

        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for entry in entries:
            row = TaskRow(entry)
            row.delete_requested.connect(self._delete)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty.setVisible(not entries)
        self.empty.setText(tr("tasks.empty") if not self.service.count() else tr("tasks.empty_search"))
        self.clear_button.setEnabled(bool(self.service.count()))

    # ----------------------------------------------------------------- actions
    def _delete(self, task_id: str) -> None:
        dialog = ConfirmDialog(
            self.window(),
            tr("tasks.delete_title"),
            tr("tasks.delete_body"),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.delete(task_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("tasks.deleted"), "info")

    def clear_all(self) -> None:
        dialog = ConfirmDialog(
            self.window(),
            tr("tasks.clear_title"),
            tr("tasks.clear_body", count=self.service.count()),
            confirm_text=tr("tasks.clear"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        removed = self.service.clear(self._kind or None)
        self.refresh()
        self.notify.emit(tr("tasks.cleared", count=removed), "info")

    # --------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.search.set_placeholder(tr("tasks.search"))
        self.kind_select.set_items(
            [("", tr("tasks.all")), (AGENT, tr("tasks.kind_agent")), (CODE, tr("tasks.kind_code"))]
        )
        self.clear_button.setText(tr("tasks.clear"))
        self.empty.setText(tr("tasks.empty"))
        self.refresh()
