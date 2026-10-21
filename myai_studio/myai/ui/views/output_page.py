"""Output Studio: code / text / prompt / Markdown / JSON editing with history.

Layout: a file rail on the left, the editor in the middle, and a right-hand
inspector that switches between live preview, revision history and diff. The
same widgets serve every artefact kind; only the preview mode changes.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...core.timeutil import format_datetime
from ...i18n import current_language, tr
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog, PromptDialog
from ..widgets.fields import FlowLayout, SelectField
from ..widgets.markdown_view import MarkdownView
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

KIND_KEYS = {
    "code": "studio.kind_code",
    "text": "studio.kind_text",
    "prompt": "studio.kind_prompt",
    "markdown": "studio.kind_markdown",
    "json": "studio.kind_json",
}


def _resize_splitter(splitter, sizes: list[int]) -> None:  # noqa: ANN001
    """Apply splitter sizes if the widget still exists (deferred Qt callback)."""
    try:
        from shiboken6 import isValid

        if not isValid(splitter):
            return
        splitter.setSizes(sizes)
    except RuntimeError:
        return


class OutputPage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("studio.title", "studio.subtitle", icon_name="code")
        self.context = context
        self._current_id: str | None = None
        self._loading = False
        self._dirty = False
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.actions_flow = None
        self.add_action(primary_button(tr("studio.new"), "plus"), self._new_output)
        self.add_action(secondary_button(tr("studio.import"), "folder"), self._import_file)

        # Rail on one side, then editor above the preview/history/diff panel.
        # A three-column split was tested and squeezed the editor to unusable
        # widths once the 360 px inspector was open at 1440 px.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(True)
        splitter.setHandleWidth(runtime.px(10))
        splitter.addWidget(self._build_rail())
        work = QSplitter(Qt.Orientation.Vertical)
        work.setChildrenCollapsible(False)
        work.setHandleWidth(runtime.px(10))
        work.addWidget(self._build_editor())
        work.addWidget(self._build_inspector())
        work.setStretchFactor(0, 3)
        work.setStretchFactor(1, 2)
        work.setSizes([runtime.px(430), runtime.px(300)])
        splitter.addWidget(work)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([runtime.px(200), runtime.px(560)])
        self.splitter = splitter
        self.add_widget(splitter)
        self.body.addStretch(1)

    def add_action(self, button: QWidget, handler) -> None:  # noqa: ANN001
        button.clicked.connect(handler)
        self.actions_row.addWidget(button)

    def _build_rail(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        frame.setMinimumWidth(runtime.px(150))
        self.rail = frame
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(10), runtime.px(11), runtime.px(10), runtime.px(10))
        layout.setSpacing(runtime.px(7))
        header = QLabel(tr("studio.files"))
        header.setProperty("role", "section")
        layout.addWidget(header)
        self.file_list = QListWidget()
        self.file_list.setFrameShape(QFrame.Shape.NoFrame)
        self.file_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; }}"
            f" QListWidget::item {{ padding: {runtime.px(6)}px {runtime.px(4)}px;"
            f" border-radius: {runtime.px(7)}px; }}"
            f" QListWidget::item:selected {{ background: {runtime.theme().alpha('accent', 0.16)};"
            f" color: {runtime.theme().color('text')}; }}"
        )
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        layout.addWidget(self.file_list, 1)
        self.rail_empty = QLabel(tr("studio.no_files"))
        self.rail_empty.setProperty("role", "faint")
        self.rail_empty.setWordWrap(True)
        layout.addWidget(self.rail_empty)
        return frame

    def _build_editor(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(13), runtime.px(11), runtime.px(13), runtime.px(12))
        layout.setSpacing(runtime.px(7))

        top = QHBoxLayout()
        top.setSpacing(runtime.px(8))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("studio.name_placeholder"))
        self.name_input.setMinimumHeight(runtime.px(30))
        self.name_input.textChanged.connect(self._mark_dirty)
        top.addWidget(self.name_input, 1)
        self.kind_picker = SelectField(
            [(k, tr(v)) for k, v in KIND_KEYS.items()], placeholder=tr("studio.kind"), compact=True
        )
        self.kind_picker.value_changed.connect(self._on_kind_changed)
        top.addWidget(self.kind_picker)
        layout.addLayout(top)

        self.meta_label = QLabel("")
        self.meta_label.setProperty("role", "faint")
        self.meta_label.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        layout.addWidget(self.meta_label)

        self.editor = QPlainTextEdit()
        self.editor.setFont(runtime.mono_font(12))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(QFontMetrics(runtime.mono_font(12)).horizontalAdvance(" ") * 4)
        self.editor.setMinimumHeight(runtime.px(220))
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        auto_direction(self.editor)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        # A wrapping row keeps every action reachable when the editor is narrow
        # (1.5x font scale at the minimum window size) instead of clipping them.
        actions = FlowLayout(spacing=runtime.px(7))
        self.save_button = primary_button(tr("studio.save"), "check")
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        self.format_button = ghost_button(tr("studio.format_json"))
        self.format_button.clicked.connect(self._format_json)
        actions.addWidget(self.format_button)
        self.export_button = secondary_button(tr("studio.export"), "download")
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.export_button)
        self.delete_button = danger_button(tr("studio.delete"), "trash")
        self.delete_button.clicked.connect(self._delete)
        actions.addWidget(self.delete_button)
        self.editor_status = QLabel("")
        self.editor_status.setProperty("role", "faint")
        actions.addWidget(self.editor_status)
        actions_host = QWidget()
        actions_host.setLayout(actions)
        self.actions_host = actions_host
        self.actions_flow = actions
        layout.addWidget(actions_host)
        return frame

    def _build_inspector(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("panel", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(runtime.px(12), runtime.px(11), runtime.px(12), runtime.px(11))
        layout.setSpacing(runtime.px(7))
        self.preview_tabs = QStackedWidget()
        header = QHBoxLayout()
        header.setSpacing(runtime.px(5))
        self.tab_preview = ghost_button(tr("studio.tab_preview"), "eye")
        self.tab_history = ghost_button(tr("studio.tab_history"), "history")
        self.tab_diff = ghost_button(tr("studio.tab_diff"), "git")
        for index, button in enumerate((self.tab_preview, self.tab_history, self.tab_diff)):
            button.clicked.connect(lambda _=False, i=index: self.preview_tabs.setCurrentIndex(i))
            header.addWidget(button)
        header.addStretch(1)
        layout.addLayout(header)

        self.preview_tabs.addWidget(self._build_preview_pane())
        self.preview_tabs.addWidget(self._build_history_pane())
        self.preview_tabs.addWidget(self._build_diff_pane())
        self.preview_tabs.setMinimumHeight(runtime.px(240))
        layout.addWidget(self.preview_tabs, 1)
        return frame

    def _build_preview_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(6))
        self.markdown_preview = MarkdownView()
        self.markdown_preview.setMinimumHeight(runtime.px(240))
        layout.addWidget(self.markdown_preview)
        self.json_preview = QTextBrowser()
        self.json_preview.setFrameShape(QFrame.Shape.NoFrame)
        self.json_preview.setFont(runtime.mono_font(10))
        self.json_preview.setVisible(False)
        layout.addWidget(self.json_preview)
        self.preview_note = hint_label(tr("studio.preview_hint"))
        layout.addWidget(self.preview_note)
        layout.addStretch(1)
        return pane

    def _build_history_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(6))
        layout.addWidget(hint_label(tr("studio.history_hint")))
        self.history_list = QListWidget()
        self.history_list.setFrameShape(QFrame.Shape.NoFrame)
        self.history_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; }}"
            f" QListWidget::item {{ padding: {runtime.px(6)}px; }}"
        )
        self.history_list.itemDoubleClicked.connect(self._restore_selected_revision)
        layout.addWidget(self.history_list, 1)
        row = QHBoxLayout()
        self.restore_button = secondary_button(tr("studio.restore"), "refresh")
        self.restore_button.clicked.connect(self._restore_selected_revision)
        row.addWidget(self.restore_button)
        row.addStretch(1)
        layout.addLayout(row)
        return pane

    def _build_diff_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(6))
        top = QHBoxLayout()
        top.setSpacing(runtime.px(6))
        self.revision_picker = SelectField([], placeholder=tr("studio.no_revisions"))
        top.addWidget(self.revision_picker)
        self.diff_button = secondary_button(tr("studio.show_diff"), "git")
        self.diff_button.clicked.connect(self._show_diff)
        top.addWidget(self.diff_button)
        top.addStretch(1)
        layout.addLayout(top)
        self.diff_summary = QLabel("")
        self.diff_summary.setProperty("role", "faint")
        layout.addWidget(self.diff_summary)
        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(runtime.mono_font(10))
        self.diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff_view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {runtime.theme().color('surface_2')}; }}"
        )
        layout.addWidget(self.diff_view, 1)
        return pane

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        outputs = self.context.outputs.list()
        current = self._current_id
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for entry in outputs:
            item = QListWidgetItem(f"{entry.name}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(tr("studio.item_tooltip", kind=entry.kind, lines=entry.line_count))
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self.rail_empty.setVisible(not outputs)
        self.file_list.setVisible(bool(outputs))
        if current and any(entry.id == current for entry in outputs):
            self._select_in_list(current)
            if not self._dirty:
                self._load_output(current)
        elif outputs:
            self._select_in_list(outputs[0].id)
        else:
            self._load_output(None)

    def _select_in_list(self, output_id: str) -> None:
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == output_id:
                self.file_list.setCurrentItem(item)
                return

    def _on_file_selected(self, current: QListWidgetItem | None, _previous=None) -> None:  # noqa: ANN001
        if current is None:
            return
        output_id = current.data(Qt.ItemDataRole.UserRole)
        if output_id != self._current_id:
            self._load_output(output_id)

    def _load_output(self, output_id: str | None) -> None:
        self._loading = True
        try:
            self._current_id = output_id
            if output_id is None:
                self.name_input.clear()
                self.editor.clear()
                self.meta_label.setText("")
                self.history_list.clear()
                self.diff_view.clear()
                self.revision_picker.set_items([])
                self.markdown_preview.set_markdown(tr("studio.empty_preview"))
                self.json_preview.setPlainText("")
                self.save_button.setEnabled(False)
                self.export_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                self.format_button.setEnabled(False)
                return
            entry = self.context.outputs.get(output_id)
            self.name_input.setText(entry.name)
            self.kind_picker.set_items([(k, tr(v)) for k, v in KIND_KEYS.items()])
            self.kind_picker.set_value(entry.kind)
            self.editor.setPlainText(entry.content)
            self.meta_label.setText(
                tr(
                    "studio.meta",
                    kind=entry.kind,
                    lang=entry.language,
                    lines=entry.line_count,
                    bytes=entry.size_bytes,
                )
            )
            from ...i18n import tn

            self.editor_status.setText(tn("studio.revisions", entry.revision_count))
            self.save_button.setEnabled(True)
            self.export_button.setEnabled(True)
            self.delete_button.setEnabled(True)
            self.format_button.setEnabled(entry.kind == "json")
            self._refresh_history()
            self._render_preview(entry.kind, entry.content)
            self._dirty = False
            self.editor_status.setText(tr("studio.loaded"))
        except AppError as exc:
            self.notify.emit(exc.message, "error")
        finally:
            self._loading = False

    def _refresh_history(self) -> None:
        self.history_list.clear()
        revisions = self.context.outputs.revisions(self._current_id) if self._current_id else []
        for index, revision in enumerate(revisions, start=1):
            label = tr(
                "studio.revision_item",
                index=index,
                when=format_datetime(revision.created_at, current_language()),
                bytes=revision.size_bytes,
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, revision.id)
            self.history_list.addItem(item)
        self.revision_picker.set_items(
            [(revision.id, f"#{index}") for index, revision in enumerate(revisions, start=1)]
        )
        self.revision_picker.set_placeholder(
            tr("studio.no_revisions") if not revisions else tr("studio.pick_revision")
        )
        self.restore_button.setEnabled(bool(revisions))
        self.diff_button.setEnabled(bool(revisions))

    def _render_preview(self, kind: str, content: str) -> None:
        if kind == "markdown":
            self.markdown_preview.set_markdown(content or tr("studio.empty_preview"))
            self.markdown_preview.show()
            self.json_preview.hide()
            self.preview_note.setText(tr("studio.preview_markdown"))
            return
        if kind == "json":
            valid, message = self.context.outputs.validate_json(content)
            status = tr("studio.json_valid") if valid else tr("studio.json_invalid", error=message)
            try:
                formatted = self.context.outputs.format_json(content) if valid else content
            except AppError:
                formatted = content
            self.json_preview.setPlainText(formatted)
            self.preview_note.setText(status)
            self.markdown_preview.hide()
            self.json_preview.show()
            return
        language = self.kind_picker.value or kind
        fence = "```"
        preview = f"{fence}{self._preview_language(language)}\n{content}\n{fence}"
        self.markdown_preview.set_markdown(preview if content else tr("studio.empty_preview"))
        self.markdown_preview.show()
        self.json_preview.hide()
        self.preview_note.setText(tr("studio.preview_hint"))

    @staticmethod
    def _preview_language(kind: str) -> str:
        return {"code": "", "text": "text", "prompt": "text"}.get(kind, "")

    # ------------------------------------------------------------------ edits
    def _mark_dirty(self, *args) -> None:  # noqa: ANN002
        if self._loading:
            return
        self._dirty = True
        self.editor_status.setText(tr("studio.unsaved"))

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._mark_dirty()
        QTimer.singleShot(180, self._update_live_preview)

    def _update_live_preview(self) -> None:
        if self._loading or not self._current_id:
            return
        kind = self.kind_picker.value or "text"
        self._render_preview(kind, self.editor.toPlainText())

    def _on_kind_changed(self, kind: str) -> None:
        if self._loading:
            return
        self.format_button.setEnabled(kind == "json")
        self._render_preview(kind, self.editor.toPlainText())
        self._mark_dirty()

    def _new_output(self) -> None:
        dialog = PromptDialog(
            self,
            tr("studio.new_title"),
            tr("studio.name"),
            value="untitled.md",
            confirm_text=tr("studio.create"),
            cancel_text=tr("dialog.cancel"),
            required_text=tr("studio.name_required"),
        )
        if not dialog.exec():
            return
        try:
            entry = self.context.outputs.create(
                dialog.value(),
                "",
                conversation_id=self._conversation_id(),
            )
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._current_id = entry.id
        self.refresh()
        self._select_in_list(entry.id)
        self.editor.setFocus()

    def _conversation_id(self) -> str | None:
        chat = getattr(self.context, "current_conversation_id", None)
        return chat

    def _save(self) -> None:
        if not self._current_id:
            return
        try:
            self.context.outputs.update(
                self._current_id,
                content=self.editor.toPlainText(),
                name=self.name_input.text() or "untitled.txt",
            )
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._dirty = False
        self.editor_status.setText(tr("studio.saved"))
        self.notify.emit(tr("studio.saved_toast"), "success")
        self.refresh()

    def _format_json(self) -> None:
        try:
            formatted = self.context.outputs.format_json(self.editor.toPlainText())
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.editor.setPlainText(formatted)
        self.editor_status.setText(tr("studio.formatted"))

    def _export(self) -> None:
        if not self._current_id:
            return
        suggested = str(self.context.paths.outputs_dir / self.name_input.text())
        path, _ = QFileDialog.getSaveFileName(
            self, tr("studio.export_title"), suggested, "All files (*)"
        )
        if not path:
            return
        try:
            saved = self.context.outputs.save_to_file(self._current_id, path)
        except (AppError, OSError) as exc:
            self.notify.emit(exc.message if isinstance(exc, AppError) else str(exc), "error")
            return
        self.notify.emit(tr("studio.exported", path=str(saved)), "success")

    def _delete(self) -> None:
        if not self._current_id:
            return
        dialog = ConfirmDialog(
            self,
            tr("studio.delete_title"),
            tr("studio.delete_body"),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        self.context.outputs.delete(self._current_id)
        self._current_id = None
        self.refresh()
        self.notify.emit(tr("studio.deleted_toast"), "info")

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("studio.import_title"), str(self.context.paths.home), "All files (*)"
        )
        if not path:
            return
        from pathlib import Path

        try:
            entry = self.context.outputs.import_file(Path(path))
        except (AppError, OSError) as exc:
            self.notify.emit(exc.message if isinstance(exc, AppError) else str(exc), "error")
            return
        self._current_id = entry.id
        self.refresh()
        self._select_in_list(entry.id)

    # --------------------------------------------------------------- history
    def _restore_selected_revision(self) -> None:
        item = self.history_list.currentItem()
        if item is None or not self._current_id:
            return
        revision_id = item.data(Qt.ItemDataRole.UserRole)
        dialog = ConfirmDialog(
            self,
            tr("studio.restore_title"),
            tr("studio.restore_body"),
            confirm_text=tr("studio.restore"),
            cancel_text=tr("dialog.cancel"),
            icon="refresh",
        )
        if not dialog.exec():
            return
        try:
            self.context.outputs.restore(self._current_id, revision_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self._load_output(self._current_id)
        self.notify.emit(tr("studio.restored_toast"), "success")

    def _show_diff(self) -> None:
        if not self._current_id:
            return
        revision_id = self.revision_picker.value or None
        try:
            result = self.context.outputs.diff(self._current_id, revision_id)
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.diff_view.setPlainText(result.unified or tr("studio.diff_empty"))
        self.diff_summary.setText(
            tr("studio.diff_summary", added=result.added, removed=result.removed)
        )
        self.preview_tabs.setCurrentIndex(2)

    # ---------------------------------------------------------------- public
    def open_output(self, output_id: str | None = None) -> None:
        if output_id:
            self._current_id = output_id
        self.refresh()
        if output_id:
            self._select_in_list(output_id)

    def open_draft(self, name: str, content: str, *, kind: str = "code") -> None:
        """Create an output from a chat message and focus it."""
        self._current_id = self.context.outputs.create(
            name or "draft.txt", content, kind=kind, conversation_id=self._conversation_id()
        ).id
        self.refresh()
        self._select_in_list(self._current_id)

    def rebuild(self) -> None:
        """Keep unsaved editor text across a language or theme switch."""
        pending = self.editor.toPlainText() if self._dirty and self._current_id else None
        super().rebuild()
        # The FlowLayout instance is recreated by _build; drop the stale one so
        # the direction-change hook cannot touch a deleted layout.
        if self.actions_flow is not None:
            self.actions_flow.invalidate()
        if pending is not None:
            self.editor.setPlainText(pending)
            self._dirty = True
            self.editor_status.setText(tr("studio.unsaved"))
            self._update_live_preview()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._apply_compact_layout(event.size().width())

    def changeEvent(self, event) -> None:  # noqa: ANN001
        super().changeEvent(event)
        # QLayout does not re-run a custom geometry pass when the base
        # direction flips, so the wrapping action row is explicitly redone.
        if event.type() == event.Type.LayoutDirectionChange and self.actions_flow is not None:
            self.actions_flow.invalidate()
            self.actions_flow.activate()

    def _apply_compact_layout(self, width: int) -> None:
        """Hide the file rail when the page is too narrow to hold it.

        Below ~560 logical px the rail steals the space the editor needs; the
        file list stays reachable through the same panel once the window grows.
        """
        if not hasattr(self, "rail"):
            return
        compact = width < runtime.px(560)
        changed = False
        if compact and self.rail.isVisible():
            self.rail.hide()
            changed = True
        elif not compact and not self.rail.isVisible():
            self.rail.show()
            changed = True
        if changed:
            # A hidden splitter child keeps its old width budget, which would
            # push the editor past the page edge; redistribute explicitly once
            # the layout has settled.
            sizes = [0, max(1, width)] if compact else [runtime.px(200), max(1, width - runtime.px(200))]
            self.splitter.setSizes(sizes)
            # The deferred pass can outlive the widget tree (window closed or a
            # language change rebuilt the page); guard it instead of raising
            # "Internal C++ object already deleted".
            QTimer.singleShot(0, lambda: _resize_splitter(self.splitter, sizes))

    def refresh_theme(self) -> None:
        self.preview_tabs.setCurrentIndex(self.preview_tabs.currentIndex())
        if self._current_id:
            self._load_output(self._current_id)

    def retranslate(self) -> None:
        super().retranslate()
        self.kind_picker.set_items([(k, tr(v)) for k, v in KIND_KEYS.items()])
        self.kind_picker.set_value(self.kind_picker.value or "code")
        self.name_input.setPlaceholderText(tr("studio.name_placeholder"))
        self.tab_preview.setText(tr("studio.tab_preview"))
        self.tab_history.setText(tr("studio.tab_history"))
        self.tab_diff.setText(tr("studio.tab_diff"))
        self.preview_note.setText(tr("studio.preview_hint"))
        if self._current_id:
            self._refresh_history()
