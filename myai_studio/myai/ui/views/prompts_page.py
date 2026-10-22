"""Prompt library (Phase 5).

Search, filter, create, edit, duplicate, delete and **use** prompts. Using a
prompt is a real action: it hands the body to the composer (or to the agent task
field) and increments the prompt's use counter.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...i18n import tr
from ...services.prompts import BUILTIN, MAX_BODY, PromptEntry
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog, ModalDialog
from ..widgets.fields import SearchField, SelectField
from ..widgets.foundation import Badge
from .page_base import PageShell, auto_direction, ghost_button, primary_button, secondary_button

logger = logging.getLogger(__name__)


class PromptEditor(ModalDialog):
    """Create or edit one prompt. Validation errors are shown inline."""

    def __init__(
        self,
        parent: QWidget,
        *,
        entry: PromptEntry | None = None,
        categories: list[str] | None = None,
    ) -> None:
        title = tr("prompts.edit_title") if entry else tr("prompts.new_title")
        super().__init__(parent, title, tr("prompts.dialog_hint"), width=640)
        self._entry = entry
        self._body_edit = QPlainTextEdit()
        self._body_edit.setObjectName("PromptBody")
        self._body_edit.setPlainText(entry.body if entry else "")
        self._body_edit.setPlaceholderText(tr("prompts.body_hint"))
        self._body_edit.setAccessibleName(tr("prompts.field_body"))
        auto_direction(self._body_edit)
        self._body_edit.setFixedHeight(runtime.px(230))
        self.body.addWidget(self._label(tr("prompts.field_body")))
        self.body.addWidget(self._body_edit)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(10))
        self._title_edit = QLineEdit(entry.title if entry else "")
        self._title_edit.setPlaceholderText(tr("prompts.title_hint"))
        self._title_edit.setMaxLength(240)
        self._title_edit.setAccessibleName(tr("prompts.field_title"))
        title_col = QVBoxLayout()
        title_col.setSpacing(runtime.px(4))
        title_col.addWidget(self._label(tr("prompts.field_title")))
        title_col.addWidget(self._title_edit)
        row.addLayout(title_col, 3)

        known = sorted({c for c in (categories or []) if c} | {"general", "code", "writing", "research"})
        self._category = SelectField([(c, c) for c in known], placeholder="general")
        self._category.set_value(entry.category if entry else "general")
        cat_col = QVBoxLayout()
        cat_col.setSpacing(runtime.px(4))
        cat_col.addWidget(self._label(tr("prompts.field_category")))
        cat_col.addWidget(self._category)
        row.addLayout(cat_col, 1)
        self.body.addLayout(row)

        self._tags_edit = QLineEdit(", ".join(entry.tags) if entry else "")
        self._tags_edit.setPlaceholderText(tr("prompts.tags_hint"))
        self._tags_edit.setAccessibleName(tr("prompts.field_tags"))
        self.body.addWidget(self._label(tr("prompts.field_tags")))
        self.body.addWidget(self._tags_edit)

        self._error = QLabel("")
        self._error.setProperty("role", "danger")
        self._error.setVisible(False)
        self.body.addWidget(self._error)

        self.footer.addStretch(1)
        cancel = self.add_button(tr("dialog.cancel"), "ghost")
        cancel.clicked.connect(self.reject)
        save = self.add_button(tr("prompts.save"), "primary", primary=True)
        save.setObjectName("PromptSave")
        save.clicked.connect(self._save)
        self._title_edit.setFocus()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "faint")
        return label

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def result_data(self) -> dict:
        tags = [part.strip() for part in self._tags_edit.text().split(",") if part.strip()]
        return {
            "title": self._title_edit.text(),
            "body": self._body_edit.toPlainText(),
            "category": self._category.value or "general",
            "tags": tags,
        }

    def _save(self) -> None:
        data = self.result_data()
        if not data["title"].strip():
            self._show_error(tr("prompts.title_required"))
            self._title_edit.setFocus()
            return
        if not data["body"].strip():
            self._show_error(tr("prompts.body_required"))
            self._body_edit.setFocus()
            return
        if len(data["body"]) > MAX_BODY:
            self._show_error(tr("prompts.body_too_long"))
            return
        self.accept()


class PromptCard(QFrame):
    use_requested = Signal(str)
    edit_requested = Signal(str)
    duplicate_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, entry: PromptEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("PromptCard")
        self.setProperty("panel", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(14), runtime.px(11), runtime.px(14), runtime.px(11))
        layout.setSpacing(runtime.px(7))

        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        title = QLabel(entry.title)
        title.setProperty("role", "section")
        title.setWordWrap(True)
        head.addWidget(title, 1)
        if entry.source == BUILTIN:
            head.addWidget(Badge(tr("prompts.builtin"), "muted"))
        elif entry.from_plugin:
            head.addWidget(Badge(tr("prompts.from_plugin", name=entry.from_plugin), "violet"))
        head.addWidget(Badge(entry.category, "accent"))
        layout.addLayout(head)

        snippet = QLabel(self._snippet(entry.body))
        snippet.setProperty("role", "muted")
        snippet.setWordWrap(True)
        layout.addWidget(snippet)

        if entry.tags:
            tags = QHBoxLayout()
            tags.setSpacing(runtime.px(5))
            for tag in entry.tags:
                tags.addWidget(Badge(f"#{tag}", "muted"))
            tags.addStretch(1)
            layout.addLayout(tags)

        footer = QHBoxLayout()
        footer.setSpacing(runtime.px(6))
        uses = QLabel(tr("prompts.uses", count=entry.uses))
        uses.setProperty("role", "faint")
        footer.addWidget(uses)
        footer.addStretch(1)
        use = primary_button(tr("prompts.use"), "play")
        use.setObjectName("PromptUse")
        use.clicked.connect(lambda: self.use_requested.emit(self.entry.id))
        footer.addWidget(use)
        copy = ghost_button("", "copy")
        copy.setAccessibleName(tr("prompts.copy"))
        copy.setToolTip(tr("prompts.copy"))
        copy.clicked.connect(lambda: self.duplicate_requested.emit(self.entry.id))
        footer.addWidget(copy)
        edit = ghost_button("", "edit")
        edit.setAccessibleName(tr("prompts.edit"))
        edit.setToolTip(tr("prompts.edit"))
        edit.clicked.connect(lambda: self.edit_requested.emit(self.entry.id))
        footer.addWidget(edit)
        remove = ghost_button("", "trash")
        remove.setAccessibleName(tr("prompts.delete"))
        remove.setToolTip(tr("prompts.delete"))
        remove.clicked.connect(lambda: self.delete_requested.emit(self.entry.id))
        footer.addWidget(remove)
        layout.addLayout(footer)

    @staticmethod
    def _snippet(body: str) -> str:
        text = " ".join(body.split())
        return text[:220] + ("…" if len(text) > 220 else "")


class PromptsPage(PageShell):
    notify = Signal(str, str)
    use_prompt = Signal(str, str)  # body, title

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("prompts.title", "prompts.subtitle", icon_name="book")
        self.context = context
        self.service = context.prompts
        self._category = ""
        self._search_cache: list[PromptEntry] = []
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(runtime.px(8))
        self.search = SearchField(tr("prompts.search"))
        self.search.setMinimumWidth(runtime.px(220))
        self.search.text_changed.connect(lambda _text: self.refresh())
        bar.addWidget(self.search, 1)
        self.category_select = SelectField([], placeholder=tr("prompts.all_categories"), compact=True)
        self.category_select.value_changed.connect(self._on_category)
        bar.addWidget(self.category_select)
        self.new_button = primary_button(tr("prompts.new"), "plus")
        self.new_button.setObjectName("PromptNew")
        self.new_button.clicked.connect(self.create_prompt)
        bar.addWidget(self.new_button)
        self.restore_button = secondary_button(tr("prompts.restore"), "refresh")
        self.restore_button.clicked.connect(self.restore_defaults)
        bar.addWidget(self.restore_button)

        holder = QWidget()
        holder.setLayout(bar)
        self.add_widget(holder)

        self.empty = QLabel("")
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        self.empty.setVisible(False)
        self.add_widget(self.empty)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(runtime.px(9))
        self.list_layout.addStretch(1)
        self.add_widget(self.list_host)

    def _on_category(self, value: str) -> None:
        self._category = value
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        categories = ["", *self.service.categories()]
        current = self._category
        self.category_select.blockSignals(True)
        self.category_select.set_items(
            [(c, tr("prompts.all_categories") if not c else c) for c in categories]
        )
        self.category_select.set_value(current if current in categories else "")
        self.category_select.blockSignals(False)
        self._category = self.category_select.value

        entries = self.service.list(self.search.text(), self._category)
        self._search_cache = entries
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for entry in entries:
            card = PromptCard(entry)
            card.use_requested.connect(self._use)
            card.edit_requested.connect(self._edit)
            card.duplicate_requested.connect(self._duplicate)
            card.delete_requested.connect(self._delete)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        self.empty.setVisible(not entries)
        self.empty.setText(
            tr("prompts.empty_search") if self.search.text().strip() else tr("prompts.empty")
        )

    # ----------------------------------------------------------------- actions
    def create_prompt(self) -> None:
        dialog = PromptEditor(self.window(), categories=self.service.categories())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.create(**dialog.result_data())
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("prompts.created"), "success")

    def _edit(self, prompt_id: str) -> None:
        try:
            entry = self.service.get(prompt_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        dialog = PromptEditor(self.window(), entry=entry, categories=self.service.categories())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.update(prompt_id, **dialog.result_data())
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("prompts.updated"), "success")

    def _duplicate(self, prompt_id: str) -> None:
        try:
            entry = self.service.get(prompt_id)
            copy_title = tr("prompts.copy_of", title=entry.title)
            self.service.create(
                copy_title,
                entry.body,
                category=entry.category,
                tags=list(entry.tags),
            )
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("prompts.copied"), "info")

    def _delete(self, prompt_id: str) -> None:
        try:
            entry = self.service.get(prompt_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        dialog = ConfirmDialog(
            self.window(),
            tr("prompts.delete_title"),
            tr("prompts.delete_body", title=entry.title),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.service.delete(prompt_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.notify.emit(tr("prompts.deleted"), "info")

    def _use(self, prompt_id: str) -> None:
        try:
            entry = self.service.touch(prompt_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.refresh()
        self.use_prompt.emit(entry.body, entry.title)

    def restore_defaults(self) -> None:
        added = self.service.restore_defaults()
        self.refresh()
        if added:
            self.notify.emit(tr("prompts.restored", count=added), "success")
        else:
            self.notify.emit(tr("prompts.restore_none"), "info")

    # --------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.search.set_placeholder(tr("prompts.search"))
        self.new_button.setText(tr("prompts.new"))
        self.restore_button.setText(tr("prompts.restore"))
        self.empty.setText(tr("prompts.empty"))
        self.refresh()
