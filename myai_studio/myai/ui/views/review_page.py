"""Review: a real diff bench for the open project, plus patch control.

Two modes that share one page:

* **Compare** — pick two files, see the aligned diff with word-level marks, and
  save it as a unified diff in Output Studio.
* **Patch** — paste a unified diff, preview it in memory, and only then write it
  through ``ProjectService.write`` after a confirmation.

Nothing here simulates a diff: the rows come from ``services.review`` and the
patch is parsed and applied by ``services.patches`` — the same code the agent
tool uses.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...services.projects import BINARY_EXTENSIONS, Project, ProjectService
from ...services.review import DiffResult, compare_texts, preview_patch, unified_diff
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.diff_view import DiffView
from ..widgets.foundation import Badge, EmptyState
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)


class ReviewPage(PageShell):
    notify = Signal(str, str)
    open_code = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("review.title", "review.subtitle", icon_name="git")
        self.context = context
        self.projects = ProjectService(context.paths, context.settings, history=getattr(context, "history", None))
        self.project: Project | None = None
        self._files: list[str] = []
        self._left = ""
        self._right = ""
        self._diff: DiffResult | None = None
        self._pending_patch = ""
        self._patch_ok = False
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        # ------------------------------------------------------------ compare
        card, layout = self.card("review.compare_title", "git")
        self.compare_card = card
        top = QHBoxLayout()
        top.setSpacing(runtime.px(8))
        self.project_badge = Badge("", "muted")
        top.addWidget(self.project_badge)
        top.addStretch(1)
        self.open_code_button = ghost_button(tr("review.open_code"), "code")
        self.open_code_button.clicked.connect(self.open_code)
        top.addWidget(self.open_code_button)
        self.swap_button = ghost_button(tr("review.swap"), "refresh")
        self.swap_button.clicked.connect(self._swap)
        top.addWidget(self.swap_button)
        self.refresh_button = ghost_button(tr("review.refresh"), "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        pickers = QHBoxLayout()
        pickers.setSpacing(runtime.px(10))
        left_column = QVBoxLayout()
        left_column.setSpacing(runtime.px(3))
        left_column.addWidget(hint_label(tr("review.left"), tone="faint"))
        self.left_combo = QComboBox()
        self.left_combo.setAccessibleName(tr("review.left"))
        self.left_combo.currentIndexChanged.connect(self._left_changed)
        left_column.addWidget(self.left_combo)
        pickers.addLayout(left_column, 1)
        divider = QFrame()
        divider.setProperty("panel", "vdivider")
        divider.setFixedWidth(1)
        pickers.addWidget(divider)
        right_column = QVBoxLayout()
        right_column.setSpacing(runtime.px(3))
        right_column.addWidget(hint_label(tr("review.right"), tone="faint"))
        self.right_combo = QComboBox()
        self.right_combo.setAccessibleName(tr("review.right"))
        self.right_combo.currentIndexChanged.connect(self._right_changed)
        right_column.addWidget(self.right_combo)
        pickers.addLayout(right_column, 1)
        layout.addLayout(pickers)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(runtime.px(6))
        self.added_badge = Badge("", "success")
        self.removed_badge = Badge("", "danger")
        self.changed_badge = Badge("", "warning")
        self.similarity_badge = Badge("", "muted")
        for badge in (self.added_badge, self.removed_badge, self.changed_badge, self.similarity_badge):
            stats_row.addWidget(badge)
        stats_row.addStretch(1)
        self.save_diff_button = ghost_button(tr("review.save_diff"), "download")
        self.save_diff_button.setEnabled(False)
        self.save_diff_button.clicked.connect(self._save_diff)
        stats_row.addWidget(self.save_diff_button)
        layout.addLayout(stats_row)

        self.diff_stack = QStackedWidget()
        self.diff_stack.setMinimumHeight(runtime.px(240))
        self.diff_empty = EmptyState(
            tr("review.no_files_title"),
            tr("review.no_files_body"),
            "git",
            action=self._empty_action(),
        )
        empty_wrap = QWidget()
        empty_layout = QVBoxLayout(empty_wrap)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.diff_empty)
        empty_layout.addStretch(1)
        self.diff_stack.addWidget(empty_wrap)
        self.diff_view = DiffView()
        self.diff_scroll = QScrollArea()
        self.diff_scroll.setWidgetResizable(True)
        self.diff_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.diff_scroll.setWidget(self.diff_view)
        self.diff_stack.addWidget(self.diff_scroll)
        layout.addWidget(self.diff_stack, 1)

        self.truncated_label = hint_label(tr("review.truncated"), tone="warning")
        self.truncated_label.setVisible(False)
        layout.addWidget(self.truncated_label)

        # -------------------------------------------------------------- patch
        patch_card, patch_layout = self.card("review.patch_title", "braces")
        self.patch_card = patch_card
        target_row = QHBoxLayout()
        target_row.setSpacing(runtime.px(8))
        target_row.addWidget(hint_label(tr("review.patch_target"), tone="faint"))
        self.target_combo = QComboBox()
        self.target_combo.setAccessibleName(tr("review.patch_target"))
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        target_row.addWidget(self.target_combo, 1)
        patch_layout.addLayout(target_row)

        self.patch_editor = QPlainTextEdit()
        self.patch_editor.setPlaceholderText(tr("review.patch_placeholder"))
        self.patch_editor.setMinimumHeight(runtime.px(150))
        self.patch_editor.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        # A unified diff is code: pin the base direction so an RTL translation
        # of the hint line cannot re-order the ASCII sample underneath it.
        option = self.patch_editor.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        self.patch_editor.document().setDefaultTextOption(option)
        self.patch_editor.setAccessibleName(tr("review.patch_title"))
        font = runtime.mono_font(12)
        self.patch_editor.setFont(font)
        self.patch_editor.textChanged.connect(self._patch_edited)
        patch_layout.addWidget(self.patch_editor)
        if self._pending_patch:
            self.patch_editor.setPlainText(self._pending_patch)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(6))
        self.preview_button = ghost_button(tr("review.patch_preview"), "eye")
        self.preview_button.clicked.connect(self._preview_patch)
        actions.addWidget(self.preview_button)
        actions.addStretch(1)
        self.apply_button = primary_button(tr("review.patch_apply"), "check")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_patch)
        actions.addWidget(self.apply_button)
        patch_layout.addLayout(actions)
        self.patch_status = QLabel("")
        self.patch_status.setWordWrap(True)
        self.patch_status.setProperty("role", "faint")
        patch_layout.addWidget(self.patch_status)

    def _empty_action(self) -> QWidget:
        button = primary_button(tr("review.go_to_code"), "code")
        button.clicked.connect(self.open_code)
        return button

    # ------------------------------------------------------------------- data
    def set_project(self, project: Project | None) -> None:
        self.project = project
        self._left = ""
        self._right = ""
        self.refresh()

    def refresh(self) -> None:  # noqa: D401 - page contract
        files: list[str] = []
        if self.project is not None:
            try:
                entries = self.projects.tree(self.project)
            except Exception as exc:  # noqa: BLE001 - a vanished folder is a message
                logger.warning("review_tree_failed error=%s", exc)
                entries = []
            for entry in entries:
                if entry.is_dir or entry.size > 2_000_000:
                    continue
                suffix = "." + entry.name.rsplit(".", 1)[-1].lower() if "." in entry.name else ""
                if suffix in BINARY_EXTENSIONS:
                    continue
                files.append(entry.relative)
        files.sort()
        self._files = files
        self.project_badge.setText(self.project.name if self.project else tr("review.no_project"))
        self.project_badge.set_tone("accent" if self.project else "muted")
        for combo in (self.left_combo, self.right_combo, self.target_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(files)
            combo.blockSignals(False)
        self._restore_selection()

        has_files = len(files) >= 2
        self.diff_stack.setCurrentIndex(1 if has_files and self._diff else 0)
        if self.project is None:
            self.diff_empty.title_label.setText(tr("review.no_project_title"))
            self.diff_empty.body_label.setText(tr("review.no_project_body"))
        else:
            self.diff_empty.title_label.setText(tr("review.no_files_title"))
            self.diff_empty.body_label.setText(tr("review.no_files_body"))
        self._compare()

    def _restore_selection(self) -> None:
        files = self._files
        if not files:
            self._left = self._right = ""
            return
        if self._left not in files:
            self._left = files[0]
        if self._right not in files:
            self._right = files[1] if len(files) > 1 else files[0]
        self.left_combo.blockSignals(True)
        self.left_combo.setCurrentText(self._left)
        self.left_combo.blockSignals(False)
        self.right_combo.blockSignals(True)
        self.right_combo.setCurrentText(self._right)
        self.right_combo.blockSignals(False)
        if self.target_combo.currentText() not in files:
            self.target_combo.blockSignals(True)
            self.target_combo.setCurrentText(self._left)
            self.target_combo.blockSignals(False)

    # --------------------------------------------------------------- compare
    def _left_changed(self, index: int) -> None:
        if index >= 0:
            self._left = self.left_combo.currentText()
            self._compare()

    def _right_changed(self, index: int) -> None:
        if index >= 0:
            self._right = self.right_combo.currentText()
            self._compare()

    def _swap(self) -> None:
        if len(self._files) < 2:
            return
        self._left, self._right = self._right, self._left
        self.left_combo.blockSignals(True)
        self.left_combo.setCurrentText(self._left)
        self.left_combo.blockSignals(False)
        self.right_combo.blockSignals(True)
        self.right_combo.setCurrentText(self._right)
        self.right_combo.blockSignals(False)
        self._compare()

    def _compare(self) -> None:
        if self.project is None or not self._left or not self._right:
            self._diff = None
            self.diff_view.set_diff(None)
            self.diff_stack.setCurrentIndex(0)
            self.save_diff_button.setEnabled(False)
            return
        try:
            old = self.projects.read(self.project, self._left)
            new = self.projects.read(self.project, self._right)
        except Exception as exc:  # noqa: BLE001 - the file may have been deleted
            logger.info("review_compare_failed error=%s", exc)
            self.notify.emit(str(exc), "error")
            self.diff_stack.setCurrentIndex(0)
            return
        if old.binary or new.binary:
            self.notify.emit(tr("review.binary"), "warning")
            self.diff_stack.setCurrentIndex(0)
            return
        self._diff = compare_texts(old.text, new.text)
        self.diff_view.set_diff(self._diff, old_name=self._left, new_name=self._right)
        stats = self._diff.stats
        self.added_badge.setText(tr("review.added", count=stats.added))
        self.removed_badge.setText(tr("review.removed", count=stats.removed))
        self.changed_badge.setText(tr("review.changed", count=stats.changed))
        self.similarity_badge.setText(tr("review.similarity", percent=round(stats.similarity * 100)))
        self.truncated_label.setVisible(self._diff.truncated)
        self.diff_stack.setCurrentIndex(1)
        self.save_diff_button.setEnabled(True)

    # ----------------------------------------------------------------- saving
    def _save_diff(self) -> None:
        if self.project is None or self._diff is None:
            return
        old = self.projects.read(self.project, self._left)
        new = self.projects.read(self.project, self._right)
        text = unified_diff(old.text, new.text, self._left, self._right) or tr("review.identical")
        safe = f"diff-{self._left.replace('/', '_')}-{self._right.replace('/', '_')}"
        try:
            entry = self.context.outputs.create(safe, text, kind="text", language="diff")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.notify.emit(tr("review.saved", name=entry.name), "success")

    # ----------------------------------------------------------------- patch
    def _target_changed(self, index: int) -> None:
        if index >= 0:
            self._patch_ok = False
            self.apply_button.setEnabled(False)
            self.patch_status.setText("")

    def _patch_edited(self) -> None:
        self._pending_patch = self.patch_editor.toPlainText()
        self._patch_ok = False
        self.apply_button.setEnabled(False)
        self.patch_status.setText("")

    def _read_target(self) -> str | None:
        if self.project is None:
            return None
        target = self.target_combo.currentText()
        if not target:
            return None
        return self.projects.read(self.project, target).text

    def _preview_patch(self) -> None:
        text = self._read_target()
        if text is None:
            self.notify.emit(tr("review.no_project"), "warning")
            return
        preview = preview_patch(text, self.patch_editor.toPlainText())
        if not preview.ok:
            self._patch_ok = False
            self.apply_button.setEnabled(False)
            self.patch_status.setProperty("role", "danger")
            self.patch_status.setText(tr("review.patch_invalid", reason=preview.error))
            self.patch_status.style().unpolish(self.patch_status)
            self.patch_status.style().polish(self.patch_status)
            return
        self._patch_ok = True
        self.apply_button.setEnabled(True)
        self.patch_status.setProperty("role", "success")
        self.patch_status.setText(tr("review.patch_valid", hunks=preview.hunks))
        self.patch_status.style().unpolish(self.patch_status)
        self.patch_status.style().polish(self.patch_status)

    def _apply_patch(self) -> None:
        if not self._patch_ok or self.project is None:
            return
        target = self.target_combo.currentText()
        text = self._read_target()
        if text is None:
            return
        preview = preview_patch(text, self.patch_editor.toPlainText())
        if not preview.ok:
            self._patch_ok = False
            self.apply_button.setEnabled(False)
            self.patch_status.setText(tr("review.patch_invalid", reason=preview.error))
            return
        dialog = ConfirmDialog(
            self,
            tr("review.apply_confirm_title"),
            tr("review.apply_confirm_body", file=target, hunks=preview.hunks),
            confirm_text=tr("review.patch_apply"),
            cancel_text=tr("common.cancel"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.projects.write(self.project, target, preview.updated, reason="patch")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self._patch_ok = False
        self.apply_button.setEnabled(False)
        self.patch_status.setText(tr("review.patch_done", file=target, hunks=preview.hunks))
        self.patch_editor.clear()
        self.notify.emit(tr("review.patch_done", file=target, hunks=preview.hunks), "success")
        self.refresh()

    # ----------------------------------------------------------- page contract
    def rebuild(self) -> None:
        self._pending_patch = self.patch_editor.toPlainText()
        super().rebuild()

    def retranslate(self) -> None:
        super().retranslate()
        # The diff renderer is painted, not composed of labels: it only re-reads
        # the theme/font when the data is handed to it again.
        if self._diff is not None:
            self.diff_view.set_diff(self._diff, old_name=self._left, new_name=self._right)
        self.open_code_button.setText(tr("review.open_code"))
        self.swap_button.setText(tr("review.swap"))
        self.refresh_button.setText(tr("review.refresh"))
        self.save_diff_button.setText(tr("review.save_diff"))
        self.preview_button.setText(tr("review.patch_preview"))
        self.apply_button.setText(tr("review.patch_apply"))
        self.patch_editor.setPlaceholderText(tr("review.patch_placeholder"))
        self.project_badge.setText(self.project.name if self.project else tr("review.no_project"))


__all__ = ["ReviewPage"]
