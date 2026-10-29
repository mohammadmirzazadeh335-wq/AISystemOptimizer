"""The conversation composer.

Enter sends, Shift+Enter adds a line, files are validated before attaching and
the whole card reacts to focus.  Capabilities that arrive in later phases are
present but explicitly labelled instead of pretending to work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...services.attachments import MAX_FILE_BYTES as ATTACHMENT_MAX_BYTES
from ...services.attachments import SUPPORTED_EXTENSIONS, dialog_filters
from ..theme import runtime
from ..widgets.buttons import IconButton, SendButton
from ..widgets.fields import AttachmentChip, PillToggle, SelectField
from ..widgets.foundation import Kbd, repolish

#: One list, shared with the extraction service, so the picker can never offer a
#: file the sender will refuse.
ALLOWED_EXTENSIONS = SUPPORTED_EXTENSIONS
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico"}
MAX_FILE_BYTES = ATTACHMENT_MAX_BYTES
MAX_ATTACHMENTS = 8


@dataclass
class Attachment:
    name: str
    path: str
    size: int
    kind: str  # "image" | "file"

    def to_meta(self) -> dict:
        return {"name": self.name, "path": self.path, "size": self.size, "kind": self.kind}


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class Composer(QWidget):
    send_requested = Signal(str, list)
    stop_requested = Signal()
    settings_requested = Signal()
    prompt_library_requested = Signal()
    preview_requested = Signal(str)
    agent_mode_requested = Signal()
    notify = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._attachments: list[Attachment] = []
        self._generating = False
        self._pending = False
        self.setAcceptDrops(True)
        self._build()
        self._update_send_state()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(runtime.px(26), 0, runtime.px(26), runtime.px(12))
        outer.setSpacing(runtime.px(7))

        self.notice = QFrame()
        self.notice.setObjectName("ComposerNotice")
        notice_layout = QHBoxLayout(self.notice)
        notice_layout.setContentsMargins(runtime.px(11), runtime.px(6), runtime.px(8), runtime.px(6))
        notice_layout.setSpacing(runtime.px(7))
        notice_icon = QLabel()
        notice_icon.setPixmap(runtime.icons().px("info", 13, "warning"))
        notice_layout.addWidget(notice_icon)
        self.notice_label = QLabel(tr("chat.phase_lock_hint"))
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        notice_layout.addWidget(self.notice_label, 1)
        self.notice_action = QPushButton(tr("nav.settings"))
        self.notice_action.setProperty("variant", "link")
        self.notice_action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.notice_action.clicked.connect(self.settings_requested)
        notice_layout.addWidget(self.notice_action)
        self._style_notice()
        outer.addWidget(self.notice)

        self.attachment_area = QScrollArea()
        self.attachment_area.setWidgetResizable(True)
        self.attachment_area.setFixedHeight(runtime.px(40))
        self.attachment_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attachment_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.attachment_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.attachment_host = QWidget()
        self.attachment_row = QHBoxLayout(self.attachment_host)
        self.attachment_row.setContentsMargins(0, 0, 0, 0)
        self.attachment_row.setSpacing(runtime.px(6))
        self.attachment_row.addStretch(1)
        self.attachment_area.setWidget(self.attachment_host)
        self.attachment_area.hide()
        outer.addWidget(self.attachment_area)

        self.card = QFrame()
        self.card.setProperty("panel", "composer")
        self.card.setObjectName("ComposerCard")
        self.shadow = QGraphicsDropShadowEffect(self.card)
        self.shadow.setBlurRadius(runtime.px(34))
        self.shadow.setOffset(0, runtime.px(10))
        color = QColor(runtime.theme().color("shadow"))
        color.setAlpha(110 if runtime.theme().is_dark else 55)
        self.shadow.setColor(color)
        self.card.setGraphicsEffect(self.shadow)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(runtime.px(12), runtime.px(10), runtime.px(10), runtime.px(8))
        card_layout.setSpacing(runtime.px(4))

        self.input = QTextEdit()
        self.input.setObjectName("ComposerInput")
        self.input.setLayoutDirection(self.layoutDirection())
        self.input.setAcceptRichText(False)
        self.input.setPlaceholderText(tr("chat.placeholder"))
        self.input.setFixedHeight(runtime.px(56))
        # Tab must leave the composer: a keyboard user cannot otherwise reach
        # the send button or the rest of the window.
        self.input.setTabChangesFocus(True)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.textChanged.connect(self._on_text_changed)
        self.input.installEventFilter(self)
        card_layout.addWidget(self.input)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(runtime.px(2), 0, 0, 0)
        toolbar.setSpacing(runtime.px(5))
        self.attach_button = IconButton("attach", tr("chat.attach_file"), 30, icon_size=16)
        self.attach_button.clicked.connect(self._pick_files)
        toolbar.addWidget(self.attach_button)
        self.prompt_button = IconButton("book", tr("composer.prompt_library"), 30, icon_size=16)
        self.prompt_button.clicked.connect(self.prompt_library_requested)
        toolbar.addWidget(self.prompt_button)
        # Web search has no provider in this build; the pill says why instead of
        # pretending to switch something on.
        self.web_toggle = PillToggle("globe", tr("chat.web_search"), tooltip=tr("web.search_blocked"))
        self.web_toggle.setEnabled(True)
        self.web_toggle.clicked.connect(self._on_web_toggled)
        toolbar.addWidget(self.web_toggle)
        self.agent_toggle = PillToggle("sparkles", tr("chat.agent_mode"), tooltip=tr("composer.agent_hint"))
        self.agent_toggle.clicked.connect(self._on_agent_toggled)
        toolbar.addWidget(self.agent_toggle)
        toolbar.addStretch(1)
        self.model_chip = SelectField(
            [],
            placeholder=tr("header.no_model"),
            compact=True,
            empty_action=(tr("inspector.open_settings"), self.settings_requested.emit),
            searchable=True,
            search_placeholder=tr("picker.search"),
        )
        toolbar.addWidget(self.model_chip)
        self.send_button = SendButton()
        self.send_button.setToolTip(tr("chat.send"))
        self.send_button.clicked.connect(self._on_send_clicked)
        toolbar.addWidget(self.send_button)
        card_layout.addLayout(toolbar)
        outer.addWidget(self.card)

        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(runtime.px(6), runtime.px(1), runtime.px(6), 0)
        hint_row.setSpacing(runtime.px(5))
        hint_row.addWidget(Kbd("Enter"))
        self.enter_label = QLabel(tr("composer.enter_send"))
        self.enter_label.setProperty("role", "faint")
        self.enter_label.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        hint_row.addWidget(self.enter_label)
        hint_row.addSpacing(runtime.px(4))
        hint_row.addWidget(Kbd("Shift+Enter"))
        self.shift_label = QLabel(tr("composer.shift_newline"))
        self.shift_label.setProperty("role", "faint")
        self.shift_label.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        hint_row.addWidget(self.shift_label)
        hint_row.addStretch(1)
        self.local_badge = QLabel(tr("chat.memory_on"))
        self.local_badge.setProperty("role", "faint")
        self.local_badge.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        self.local_badge.hide()
        hint_row.addWidget(self.local_badge)
        outer.addLayout(hint_row)

    def _style_notice(self) -> None:
        c = runtime.theme().color
        self.notice.setStyleSheet(
            f"QFrame#ComposerNotice {{ background-color: {c('warning_soft')};"
            f" border: 1px solid {runtime.theme().alpha('warning', 0.35)};"
            f" border-radius: {runtime.px(9)}px; }}"
        )
        self.notice_label.setStyleSheet(f"color: {c('warning')}; font-size: {runtime.px(10)}px;")

    # ------------------------------------------------------------------ state
    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.send_button.set_mode("stop" if generating else "send")
        self.send_button.setToolTip(tr("chat.stop") if generating else tr("chat.send"))
        self._update_send_state()

    def set_model_ready(self, ready: bool) -> None:
        self.notice.setVisible(not ready)

    def set_notice_visibility(self, visible: bool) -> None:
        self.notice.setVisible(visible)

    def set_models(self, items: list[tuple[str, str]], current: str = "") -> None:
        self.model_chip.set_items(items)
        if current:
            self.model_chip.set_value(current)

    def set_model_choices(self, choices, current: str = "") -> None:
        """Rich rows for the searchable picker (name, id and capability tags)."""
        self.model_chip.set_choices(choices, current)

    def model_value(self) -> str:
        return self.model_chip.value

    def _on_text_changed(self) -> None:
        self._adjust_height()
        self._update_send_state()

    def _adjust_height(self) -> None:
        document = self.input.document()
        document.setTextWidth(self.input.viewport().width())
        height = document.size().height() + runtime.px(12)
        target = max(runtime.px(52), min(runtime.px(168), int(height)))
        if target != self.input.height():
            self.input.setFixedHeight(target)

    def _update_send_state(self) -> None:
        text = self.input.toPlainText().strip()
        if self._generating:
            self.send_button.setEnabled(True)
            return
        self.send_button.setEnabled(bool(text or self._attachments) and not self._pending)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self.input:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    self._submit()
                    return True
            elif event.type() == QEvent.Type.FocusIn:
                self.card.setProperty("focused", "true")
                repolish(self.card)
            elif event.type() == QEvent.Type.FocusOut:
                self.card.setProperty("focused", "false")
                repolish(self.card)
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------- attachments
    def pick_files(self) -> None:
        """Public entry point used by the palette and keyboard shortcuts."""
        self._pick_files()

    def _pick_files(self) -> None:
        # The dialog lists the same extensions the validator accepts, grouped by
        # family, so a file the dialog offers can never be rejected a second later.
        filters = ";;".join(
            f"{tr(key)} ({patterns})" for key, patterns in dialog_filters()
        )
        paths, _ = QFileDialog.getOpenFileNames(
            self.window(),
            tr("chat.attach_file"),
            str(Path.home()),
            f"{filters};;{tr('composer.filter_everything')} (*)",
        )
        for path in paths:
            self._add_attachment(path)

    def _on_web_toggled(self, checked: bool) -> None:  # noqa: ARG002
        self.web_toggle.setChecked(False)
        self.notify.emit(tr("web.search_blocked"), "warning")

    def _on_agent_toggled(self, checked: bool) -> None:  # noqa: ARG002
        self.agent_toggle.setChecked(False)
        self.agent_mode_requested.emit()

    # ------------------------------------------------------------------- drops
    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self._add_attachment(url.toLocalFile())
        event.acceptProposedAction()

    def _add_attachment(self, path: str) -> None:
        if len(self._attachments) >= MAX_ATTACHMENTS:
            self.notify.emit(tr("composer.too_many", count=MAX_ATTACHMENTS), "warning")
            return
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            self.notify.emit(tr("composer.unsupported_file"), "error")
            return
        try:
            size = file_path.stat().st_size
        except OSError:
            self.notify.emit(tr("composer.unsupported_file"), "error")
            return
        if size > MAX_FILE_BYTES:
            self.notify.emit(tr("composer.file_too_large", size=20), "error")
            return
        if any(item.path == str(file_path) for item in self._attachments):
            return
        kind = "image" if suffix in IMAGE_EXTENSIONS else "file"
        attachment = Attachment(name=file_path.name, path=str(file_path), size=size, kind=kind)
        self._attachments.append(attachment)
        self._rebuild_attachment_row()
        self._update_send_state()  # a file alone is enough to send
        self.notify.emit(tr("composer.attachment_added", name=file_path.name), "success")

    def _rebuild_attachment_row(self) -> None:
        while self.attachment_row.count() > 1:
            item = self.attachment_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for attachment in self._attachments:
            chip = AttachmentChip(
                attachment.name,
                human_size(attachment.size),
                "image" if attachment.kind == "image" else "file",
                ident=attachment.path,
                previewable=True,
            )
            chip.removed.connect(self._remove_attachment)
            chip.opened.connect(self.preview_requested.emit)
            self.attachment_row.insertWidget(self.attachment_row.count() - 1, chip)
        self.attachment_area.setVisible(bool(self._attachments))

    def _remove_attachment(self, ident: str) -> None:
        # Identify by path, not by name: two folders can both hold ``main.py``.
        self._attachments = [item for item in self._attachments if item.path != ident]
        self._rebuild_attachment_row()
        self._update_send_state()

    def attachments(self) -> list[Attachment]:
        return list(self._attachments)

    # ------------------------------------------------------------------ submit
    def _on_send_clicked(self) -> None:
        if self._generating:
            self.stop_requested.emit()
            return
        self._submit()

    def _submit(self) -> None:
        text = self.input.toPlainText().strip()
        if (not text and not self._attachments) or self._pending:
            return
        self._pending = True
        self._update_send_state()
        self.send_requested.emit(text, [item.to_meta() for item in self._attachments])

    def mark_sent(self) -> None:
        self._pending = False
        self.input.clear()
        self._attachments.clear()
        self._rebuild_attachment_row()
        self._adjust_height()
        self._update_send_state()
        self.input.setFocus()

    def restore_draft(self, text: str) -> None:
        self._pending = False
        self.input.setPlainText(text)
        self._update_send_state()

    def set_text(self, text: str, *, focus: bool = True) -> None:
        self.input.setPlainText(text)
        self.input.moveCursor(self.input.textCursor().MoveOperation.End)
        if focus:
            self.input.setFocus()

    def focus_input(self) -> None:
        self.input.setFocus()

    # ------------------------------------------------------------ theme / i18n
    def refresh_theme(self) -> None:
        self._style_notice()
        self.send_button.update()
        for child in self.findChildren(AttachmentChip):
            child.update()
        color = QColor(runtime.theme().color("shadow"))
        color.setAlpha(110 if runtime.theme().is_dark else 55)
        self.shadow.setColor(color)
        self.shadow.setBlurRadius(runtime.px(34))
        self.shadow.setOffset(0, runtime.px(10))

    def retranslate(self) -> None:
        self.input.setPlaceholderText(tr("chat.placeholder"))
        self.attach_button.setToolTip(tr("chat.attach_file"))
        self.prompt_button.setToolTip(tr("composer.prompt_library"))
        self.model_chip.set_placeholder(tr("header.no_model"))
        self.model_chip._empty_action = (tr("inspector.open_settings"), self.settings_requested.emit)
        self.send_button.setToolTip(tr("chat.stop") if self._generating else tr("chat.send"))
        self.notice_label.setText(tr("chat.phase_lock_hint"))
        self.notice_action.setText(tr("nav.settings"))
        self.enter_label.setText(tr("composer.enter_send"))
        self.shift_label.setText(tr("composer.shift_newline"))
        self.web_toggle.set_text(tr("chat.web_search"))
        self.agent_toggle.set_text(tr("chat.agent_mode"))
        self.web_toggle.setToolTip(tr("web.search_blocked"))
        self.agent_toggle.setToolTip(tr("composer.agent_hint"))
