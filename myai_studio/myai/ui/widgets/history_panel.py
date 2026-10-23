"""Version history for one Code Studio file.

The list on the left is the file as it existed on disk at each save; picking an
entry diffs it against what is open now, so a restore is a decision made with
the change in front of you, not a guess from a timestamp.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.timeutil import format_datetime, relative_time
from ...i18n import current_language, tr
from ...services.history import Snapshot
from ...services.review import compare_texts
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog, ModalDialog
from ..widgets.diff_view import DiffView
from ..widgets.foundation import Badge, EmptyState


def _button(text: str, icon_name: str, variant: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", variant)
    button.setProperty("buttonsize", "sm")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        button.setIcon(runtime.icons().get(icon_name, 13, "muted" if variant == "ghost" else "accent"))
    return button


class HistoryDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget,
        service,  # noqa: ANN001
        project_service,  # noqa: ANN001
        project,  # noqa: ANN001
        relative: str,
        current_text: str,
        on_restored: Callable[[str], None],
        on_notify: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(
            parent, tr("history.title"), tr("history.subtitle", name=relative), width=880
        )
        self._service = service
        self._project_service = project_service
        self._project = project
        self._relative = relative
        self._current_text = current_text
        self._on_restored = on_restored
        self._on_notify = on_notify or (lambda _text, _tone: None)
        self._snapshots: list[Snapshot] = []
        self._selection: Snapshot | None = None

        split = QHBoxLayout()
        split.setSpacing(runtime.px(12))

        # ----------------------------------------------------------- version list
        left = QVBoxLayout()
        left.setSpacing(runtime.px(6))
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "faint")
        left.addWidget(self.count_label)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setMinimumWidth(runtime.px(230))
        self.list.setMaximumWidth(runtime.px(270))
        self.list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            f" QListWidget::item {{ padding: {runtime.px(6)}px 8px;"
            f" border-radius: {runtime.px(7)}px; }}"
            f" QListWidget::item:selected {{ background: {runtime.theme().alpha('accent', 0.18)};"
            f" color: {runtime.theme().color('text')}; }}"
        )
        self.list.currentRowChanged.connect(self._on_row)
        left.addWidget(self.list, 1)
        self.empty_hint = QLabel(tr("history.empty_body"))
        self.empty_hint.setProperty("role", "faint")
        self.empty_hint.setWordWrap(True)
        left.addWidget(self.empty_hint)
        split.addLayout(left)

        # -------------------------------------------------------------- preview
        right = QVBoxLayout()
        right.setSpacing(runtime.px(6))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        self.preview_label = QLabel(tr("history.preview_title"))
        self.preview_label.setProperty("role", "section")
        head.addWidget(self.preview_label)
        self.reason_badge = Badge("—", "muted")
        self.reason_badge.setVisible(False)
        head.addWidget(self.reason_badge)
        self.stamp_label = QLabel("")
        self.stamp_label.setProperty("role", "faint")
        head.addWidget(self.stamp_label)
        head.addStretch(1)
        right.addLayout(head)

        self.diff = DiffView()
        self.diff_scroll = QScrollArea()
        self.diff_scroll.setWidgetResizable(True)
        self.diff_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.diff_scroll.setWidget(self.diff)
        self.diff_scroll.setMinimumHeight(runtime.px(300))
        right.addWidget(self.diff_scroll, 1)
        self.preview_empty = EmptyState(
            tr("history.pick_title"), tr("history.pick_body"), "history"
        )
        right.addWidget(self.preview_empty)
        split.addLayout(right, 1)
        self.body.addLayout(split, 1)

        self.restore_button = _button(tr("history.restore"), "refresh", "primary")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._restore)
        self.footer.addStretch(1)
        self.clear_button = _button(tr("history.clear"), "trash", "ghost")
        self.clear_button.clicked.connect(self._clear)
        self.footer.addWidget(self.clear_button)
        self.footer.addWidget(self.restore_button)

        self.resize(runtime.px(920), runtime.px(600))
        self._load()

    # -------------------------------------------------------------------- data
    def _load(self) -> None:
        self.list.clear()
        self._snapshots = self._service.versions(self._project.root, self._relative)
        language = current_language()
        for snapshot in self._snapshots:
            stamp = format_datetime(snapshot.created_at, language)
            reason = self._service.describe(snapshot)
            item = QListWidgetItem(f"{reason}  ·  {relative_time(snapshot.created_at, language)}")
            item.setToolTip(stamp)
            item.setData(Qt.ItemDataRole.UserRole, snapshot.id)
            self.list.addItem(item)
        self.count_label.setText(tr("history.count", count=len(self._snapshots)))
        has_any = bool(self._snapshots)
        self.list.setVisible(has_any)
        self.empty_hint.setVisible(not has_any)
        self.clear_button.setEnabled(has_any)
        self.preview_empty.setVisible(not has_any)
        self.diff_scroll.setVisible(has_any)
        if has_any:
            self.list.setCurrentRow(0)
        else:
            self._selection = None
            self.reason_badge.setVisible(False)
            self.restore_button.setEnabled(False)
            self.stamp_label.setText("")

    def _on_row(self, row: int) -> None:
        if row < 0 or row >= len(self._snapshots):
            self._selection = None
            self.restore_button.setEnabled(False)
            return
        snapshot = self._snapshots[row]
        self._selection = snapshot
        self.restore_button.setEnabled(True)
        self.reason_badge.setVisible(True)
        self.reason_badge.setText(self._service.describe(snapshot))
        tone = {"restore": "warning", "patch": "violet", "create": "success"}.get(
            snapshot.reason, "muted"
        )
        self.reason_badge.set_tone(tone)
        self.stamp_label.setText(format_datetime(snapshot.created_at, current_language()))
        try:
            text = self._service.read(self._project.root, self._relative, snapshot.id)
        except Exception:  # noqa: BLE001 - vanished underneath us
            text = ""
        self.diff.set_diff(
            compare_texts(self._current_text, text),
            old_name=tr("history.current_label"),
            new_name=self._service.describe(snapshot),
        )

    # ----------------------------------------------------------------- actions
    def _restore(self) -> None:
        snapshot = self._selection
        if snapshot is None:
            return
        confirm = ConfirmDialog(
            self,
            tr("history.restore_title"),
            tr("history.restore_body", name=self._relative),
            confirm_text=tr("history.restore"),
            tone="accent",
        )
        if not confirm.exec():
            return
        try:
            text = self._service.restore(
                self._project_service, self._project, self._relative, snapshot.id
            )
        except Exception as exc:  # noqa: BLE001
            self._on_notify(str(exc), "error")
            return
        self._on_notify(tr("history.restored", name=self._relative), "success")
        self._on_restored(text)
        self._load()

    def _clear(self) -> None:
        confirm = ConfirmDialog(
            self,
            tr("history.clear"),
            tr("history.clear_body", name=self._relative),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
        )
        if not confirm.exec():
            return
        removed = self._service.clear(self._project.root, self._relative)
        self._on_notify(tr("history.cleared", count=removed), "info")
        self._load()
