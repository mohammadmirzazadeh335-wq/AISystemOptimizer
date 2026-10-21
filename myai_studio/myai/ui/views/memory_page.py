"""Memory page: independent global memory and per-conversation memory.

The page mirrors the service contract exactly:

* nothing is deleted without an explicit confirmation;
* summarising produces *candidates* that the user reviews first;
* storage size (characters on disk) and context usage (estimated tokens) are
  displayed separately and never conflated.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...core.timeutil import format_datetime
from ...i18n import current_language, tn, tr
from ...services.memory import CONVERSATION, GLOBAL, MemoryEntry
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import SelectField
from ..widgets.foundation import Badge
from .page_base import (
    PageShell,
    auto_direction,
    danger_button,
    ghost_button,
    hint_label,
    primary_button,
    secondary_button,
)

logger = logging.getLogger(__name__)


class MemoryRow(QFrame):
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    pin_requested = Signal(str, bool)

    def __init__(self, entry: MemoryEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("MemoryRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(11), runtime.px(8), runtime.px(9), runtime.px(8))
        layout.setSpacing(runtime.px(9))

        text_col = QVBoxLayout()
        text_col.setSpacing(runtime.px(2))
        content = QLabel(entry.content)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet(f"font-size: {runtime.px(12)}px;")
        text_col.addWidget(content)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(runtime.px(6))
        age = QLabel(format_datetime(entry.updated_at, current_language()))
        age.setProperty("role", "faint")
        age.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        meta_row.addWidget(age)
        meta_row.addWidget(Badge(entry.source, "outline"))
        if entry.pinned:
            meta_row.addWidget(Badge(tr("memory.pinned"), "success"))
        meta_row.addStretch(1)
        text_col.addLayout(meta_row)
        layout.addLayout(text_col, 1)

        self.pin_button = ghost_button("", "pin")
        self.pin_button.setToolTip(tr("memory.unpin") if entry.pinned else tr("memory.pin"))
        self.pin_button.clicked.connect(lambda: self.pin_requested.emit(entry.id, not entry.pinned))
        layout.addWidget(self.pin_button)
        edit = ghost_button("", "edit")
        edit.setToolTip(tr("memory.edit"))
        edit.clicked.connect(lambda: self.edit_requested.emit(entry.id))
        layout.addWidget(edit)
        delete = ghost_button("", "trash")
        delete.setToolTip(tr("memory.delete"))
        delete.clicked.connect(lambda: self.delete_requested.emit(entry.id))
        layout.addWidget(delete)

        self.setStyleSheet(
            f"QFrame#MemoryRow {{ background-color: {runtime.theme().alpha('surface_2', 0.5)};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(9)}px; }}"
        )


class MemoryPage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("memory.title", "memory.subtitle", icon_name="book-open")
        self.context = context
        self._scope = GLOBAL
        self._conversation_id: str | None = None
        self._editing_id: str | None = None
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        # Rebuilding (language/theme switch) must not leave a stale edit target.
        self._editing_id = None
        self._candidates = []
        self._build_scope_card()
        self._build_usage_card()
        self._build_editor_card()
        self._build_list_card()
        self._build_summary_card()

    def _build_scope_card(self) -> None:
        card, layout = self.card("memory.scope_card", "layers")
        row = QHBoxLayout()
        row.setSpacing(runtime.px(10))
        self.scope_picker = SelectField(
            [(GLOBAL, tr("memory.scope_global")), (CONVERSATION, tr("memory.scope_chat"))],
            placeholder=tr("memory.scope_global"),
        )
        self.scope_picker.set_value(GLOBAL)
        self.scope_picker.value_changed.connect(self._on_scope_changed)
        row.addWidget(self.scope_picker)
        self.chat_picker = SelectField([], placeholder=tr("memory.no_chat"))
        self.chat_picker.value_changed.connect(self._on_chat_changed)
        row.addWidget(self.chat_picker)
        row.addStretch(1)
        layout.addLayout(row)
        self.scope_hint = hint_label(tr("memory.scope_hint"))
        layout.addWidget(self.scope_hint)

    def _build_usage_card(self) -> None:
        card, layout = self.card("memory.usage_card", "gauge")
        grid = QHBoxLayout()
        grid.setSpacing(runtime.px(22))
        self.usage_memory = self._metric(tr("memory.metric_global"), "0")
        self.usage_chat = self._metric(tr("memory.metric_chat"), "0")
        self.usage_storage = self._metric(tr("memory.metric_storage"), "0")
        self.usage_context = self._metric(tr("memory.metric_context"), "0")
        for widget in (self.usage_memory, self.usage_chat, self.usage_storage, self.usage_context):
            grid.addWidget(widget)
        grid.addStretch(1)
        layout.addLayout(grid)
        layout.addWidget(hint_label(tr("memory.usage_hint")))

    def _metric(self, label: str, value: str) -> QWidget:
        wrapper = QWidget()
        col = QVBoxLayout(wrapper)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(runtime.px(1))
        heading = QLabel(label)
        heading.setProperty("role", "faint")
        heading.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        col.addWidget(heading)
        value_label = QLabel(value)
        value_label.setStyleSheet(f"font-size: {runtime.px(17)}px; font-weight: 600;")
        col.addWidget(value_label)
        wrapper._value_label = value_label  # type: ignore[attr-defined]
        wrapper._heading = heading  # type: ignore[attr-defined]
        return wrapper

    def _build_editor_card(self) -> None:
        card, layout = self.card("memory.editor_card", "edit")
        self.editor_title = QLabel(tr("memory.add_title"))
        self.editor_title.setProperty("role", "section")
        layout.addWidget(self.editor_title)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(tr("memory.placeholder"))
        self.editor.setFixedHeight(runtime.px(84))
        auto_direction(self.editor)
        layout.addWidget(self.editor)
        row = QHBoxLayout()
        row.setSpacing(runtime.px(7))
        self.save_button = primary_button(tr("memory.add"), "plus")
        self.save_button.clicked.connect(self._save_entry)
        row.addWidget(self.save_button)
        self.cancel_button = ghost_button(tr("dialog.cancel"), "close")
        self.cancel_button.clicked.connect(self._reset_editor)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        self.editor_error = QLabel("")
        self.editor_error.setProperty("role", "danger")
        self.editor_error.hide()
        row.addWidget(self.editor_error)
        layout.addLayout(row)

    def _build_list_card(self) -> None:
        card, layout = self.card("memory.list_card", "list-check")
        top = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "muted")
        top.addWidget(self.count_label, 1)
        self.clear_button = danger_button(tr("memory.clear_scope"), "trash")
        self.clear_button.clicked.connect(self._clear_scope)
        top.addWidget(self.clear_button)
        layout.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(runtime.px(300))
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(runtime.px(6))
        self.rows_layout.addStretch(1)
        scroll.setWidget(self.rows_host)
        layout.addWidget(scroll)
        self.empty_label = QLabel(tr("memory.empty"))
        self.empty_label.setProperty("role", "faint")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

    def _build_summary_card(self) -> None:
        card, layout = self.card("memory.summary_card", "sparkles")
        layout.addWidget(hint_label(tr("memory.summary_hint")))
        row = QHBoxLayout()
        row.setSpacing(runtime.px(8))
        self.summarize_button = secondary_button(tr("memory.summarize"), "wand")
        self.summarize_button.clicked.connect(self._summarize)
        row.addWidget(self.summarize_button)
        row.addStretch(1)
        self.summary_status = QLabel("")
        self.summary_status.setProperty("role", "faint")
        self.summary_status.setWordWrap(True)
        row.addWidget(self.summary_status, 1)
        layout.addLayout(row)
        self.candidates_host = QWidget()
        self.candidates_layout = QVBoxLayout(self.candidates_host)
        self.candidates_layout.setContentsMargins(0, 0, 0, 0)
        self.candidates_layout.setSpacing(runtime.px(5))
        layout.addWidget(self.candidates_host)
        self.commit_button = primary_button(tr("memory.commit_summary"), "check")
        self.commit_button.clicked.connect(self._commit_summary)
        self.commit_button.hide()
        layout.addWidget(self.commit_button)
        self._candidates: list[tuple[QLineEdit, str]] = []

    # ------------------------------------------------------------------ state
    def set_context(self, conversation_id: str | None, title: str = "") -> None:
        """Called when the user opens the page from a chat."""
        conversations = self.context.conversations.list()[:30]
        items = [(c.id, c.title or tr("chat.untitled")) for c in conversations]
        self.chat_picker.set_items(items)
        if conversation_id:
            self._conversation_id = conversation_id
            self.chat_picker.set_value(conversation_id)
            self._scope = CONVERSATION
            self.scope_picker.set_value(CONVERSATION)
        elif items:
            self._conversation_id = self._conversation_id or items[0][0]
            self.chat_picker.set_value(self._conversation_id)
        self.refresh()

    def _on_scope_changed(self, scope: str) -> None:
        self._scope = scope if scope in {GLOBAL, CONVERSATION} else GLOBAL
        if self._scope == CONVERSATION and not self._conversation_id:
            conversations = self.context.conversations.list()[:30]
            if conversations:
                self._conversation_id = conversations[0].id
                self.chat_picker.set_value(self._conversation_id)
        self._reset_editor()
        self.refresh()

    def _on_chat_changed(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id or None
        if self._scope == CONVERSATION:
            self.refresh()

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        entries = self.context.memory.list(self._scope, self._conversation_id)
        self._render(entries)
        usage = self.context.memory.usage(self._conversation_id)
        self.usage_memory._value_label.setText(str(usage.global_count))
        self.usage_chat._value_label.setText(str(usage.conversation_count))
        self.usage_storage._value_label.setText(f"{usage.storage_bytes:,}")
        report = self.context.memory.context_report(
            self._conversation_id, window=self.context.chat.context_window(
                self._current_model()
            )
        )
        self.usage_context._value_label.setText(f"≈{report['memory_tokens']:,}")
        self.clear_button.setEnabled(bool(entries))
        self._update_headers()

    def _current_model(self) -> str:
        if self._conversation_id:
            try:
                conversation = self.context.conversations.get(self._conversation_id)
                return conversation.model_id or str(self.context.settings.get("ai.default_model", ""))
            except AppError:
                return ""
        return str(self.context.settings.get("ai.default_model", ""))

    def _update_headers(self) -> None:
        if self._scope == GLOBAL:
            self.count_label.setText(
                tn("memory.count_global", len(self.context.memory.list(GLOBAL)))
            )
            self.summary_status.setText(tr("memory.summary_needs_chat"))
            self.summarize_button.setEnabled(False)
        else:
            count = len(self.context.memory.list(CONVERSATION, self._conversation_id)) if self._conversation_id else 0
            self.count_label.setText(tn("memory.count_chat", count))
            self.summarize_button.setEnabled(bool(self._conversation_id))
            if not self.summary_status.text():
                self.summary_status.setText("")

    def _render(self, entries: list[MemoryEntry]) -> None:
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for entry in entries:
            row = MemoryRow(entry)
            row.edit_requested.connect(self._start_edit)
            row.delete_requested.connect(self._delete_entry)
            row.pin_requested.connect(self._toggle_pin)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self.empty_label.setVisible(not entries)
        self.empty_label.setText(
            tr("memory.empty_global") if self._scope == GLOBAL else tr("memory.empty_chat")
        )

    # ------------------------------------------------------------------ edits
    def _save_entry(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self._editor_error(tr("memory.empty_error"))
            return
        try:
            if self._editing_id:
                self.context.memory.update(self._editing_id, text)
                self.notify.emit(tr("memory.updated_toast"), "success")
            else:
                self.context.memory.add(
                    text,
                    scope=self._scope,
                    conversation_id=self._conversation_id if self._scope == CONVERSATION else None,
                )
                self.notify.emit(tr("memory.added_toast"), "success")
        except AppError as exc:
            self._editor_error(exc.message)
            return
        self._reset_editor()
        self.refresh()

    def _editor_error(self, message: str) -> None:
        self.editor_error.setText(message)
        self.editor_error.setVisible(bool(message))

    def _reset_editor(self) -> None:
        self._editing_id = None
        self.editor.clear()
        self.editor_title.setText(tr("memory.add_title"))
        self.save_button.setText(tr("memory.add"))
        self.cancel_button.hide()
        self._editor_error("")

    def _start_edit(self, memory_id: str) -> None:
        try:
            entry = self.context.memory.get(memory_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._editing_id = memory_id
        self.editor.setPlainText(entry.content)
        self.editor_title.setText(tr("memory.edit_title"))
        self.save_button.setText(tr("memory.save_changes"))
        self.cancel_button.show()
        self.editor.setFocus()

    def _delete_entry(self, memory_id: str) -> None:
        dialog = ConfirmDialog(
            self,
            tr("memory.delete_title"),
            tr("memory.delete_body"),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        try:
            self.context.memory.delete(memory_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()

    def _toggle_pin(self, memory_id: str, pinned: bool) -> None:
        try:
            entry = self.context.memory.get(memory_id)
            self.context.memory.update(memory_id, entry.content, pinned=pinned)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()

    def _clear_scope(self) -> None:
        dialog = ConfirmDialog(
            self,
            tr("memory.clear_title"),
            tr("memory.clear_body"),
            confirm_text=tr("memory.clear_confirm"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        self.context.memory.clear(self._scope, self._conversation_id)
        self.refresh()
        self.notify.emit(tr("memory.cleared_toast"), "info")

    # ---------------------------------------------------------------- summary
    def _summarize(self) -> None:
        if not self._conversation_id:
            return
        try:
            candidates = self.context.memory.summarize_conversation(self._conversation_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._clear_candidates()
        if not candidates:
            self.summary_status.setText(tr("memory.summary_empty"))
            return
        self.summary_status.setText(tn("memory.summary_review", len(candidates)))
        for candidate in candidates:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(runtime.px(6))
            field = QLineEdit(candidate.content)
            row_layout.addWidget(field, 1)
            self.candidates_layout.addWidget(row)
            self._candidates.append((field, candidate.content))
        self.commit_button.show()

    def _clear_candidates(self) -> None:
        while self.candidates_layout.count():
            item = self.candidates_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._candidates = []
        self.commit_button.hide()

    def _commit_summary(self) -> None:
        if not self._conversation_id or not self._candidates:
            return
        texts = [field.text().strip() for field, _ in self._candidates if field.text().strip()]
        if not texts:
            self.summary_status.setText(tr("memory.summary_empty"))
            return
        try:
            self.context.memory.commit_summary(self._conversation_id, texts)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._clear_candidates()
        self.summary_status.setText(tn("memory.summary_committed", len(texts)))
        self._scope = CONVERSATION
        self.scope_picker.set_value(CONVERSATION)
        self.refresh()
        self.notify.emit(tr("memory.summary_committed_toast"), "success")

    # --------------------------------------------------------------- visuals
    def retranslate(self) -> None:
        super().retranslate()
        self.scope_picker.set_items(
            [(GLOBAL, tr("memory.scope_global")), (CONVERSATION, tr("memory.scope_chat"))]
        )
        self.scope_picker.set_value(self._scope)
        self.chat_picker.set_placeholder(tr("memory.no_chat"))
        self.usage_memory._heading.setText(tr("memory.metric_global"))
        self.usage_chat._heading.setText(tr("memory.metric_chat"))
        self.usage_storage._heading.setText(tr("memory.metric_storage"))
        self.usage_context._heading.setText(tr("memory.metric_context"))
        self.editor.setPlaceholderText(tr("memory.placeholder"))
