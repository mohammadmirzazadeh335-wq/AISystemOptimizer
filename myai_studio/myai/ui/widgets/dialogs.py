"""Frameless, design-system native modal dialogs.

Windows' default message boxes break the visual language, so the app ships
its own confirm/prompt dialogs with a dimmed backdrop, keyboard support and
accessible focus order.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import runtime
from .buttons import IconButton
from .fields import InlineError
from .foundation import IconBadge
from .painting import paint_event


class _Backdrop(QWidget):
    """Dimmed, click-blocking layer painted behind a modal dialog.

    The fade animates a plain float instead of a QGraphicsEffect; effects and
    animations targeting widgets that are about to be deleted are a reliable
    source of shutdown crashes, so this keeps teardown trivial.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._alpha = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.show()

    def fade(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._alpha)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _on_value(self, value) -> None:  # noqa: ANN001
        self._alpha = float(value)
        self.update()

    def stop(self) -> None:
        self._anim.stop()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001
        color = QColor(runtime.theme().color("overlay"))
        maximum = 150 if runtime.theme().is_dark else 80
        color.setAlpha(int(maximum * self._alpha))
        painter.fillRect(self.rect(), color)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        event.accept()  # block interaction with the workspace


class ModalDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, subtitle: str = "", width: int = 520) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._backdrop: _Backdrop | None = None
        self._drag_origin: QPoint | None = None
        self._width = width
        self._fixed_size: tuple[int, int] | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(runtime.px(18), runtime.px(18), runtime.px(18), runtime.px(18))
        self.card = QFrame()
        self.card.setObjectName("ModalCard")
        self.card.setStyleSheet(
            f"QFrame#ModalCard {{ background-color: {runtime.theme().color('surface')};"
            f" border: 1px solid {runtime.theme().color('border_strong')};"
            f" border-radius: {runtime.px(16)}px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(runtime.px(46))
        shadow.setOffset(0, runtime.px(14))
        color = QColor(runtime.theme().color("shadow"))
        color.setAlpha(170 if runtime.theme().is_dark else 90)
        shadow.setColor(color)
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(runtime.px(22), runtime.px(18), runtime.px(22), runtime.px(18))
        card_layout.setSpacing(runtime.px(14))

        header = QHBoxLayout()
        header.setSpacing(runtime.px(10))
        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(runtime.px(3))
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "h2")
        title_wrap.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "muted")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        title_wrap.addWidget(self.subtitle_label)
        header.addLayout(title_wrap, 1)
        close = IconButton("close", "Close", 30, icon_size=14)
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(runtime.px(10))
        card_layout.addLayout(self.body)

        self.footer = QHBoxLayout()
        self.footer.setSpacing(runtime.px(8))
        card_layout.addLayout(self.footer)

        self.setMinimumWidth(runtime.px(min(width, 560)))
        self.setMaximumWidth(runtime.px(max(width, 560)))
        self.card.installEventFilter(self)

    # ------------------------------------------------------------------ layout
    def showEvent(self, event) -> None:  # noqa: ANN001
        parent = self.parentWidget()
        if parent is not None:
            self._backdrop = _Backdrop(parent)
            self._backdrop.setGeometry(parent.rect())
            self._backdrop.fade(1.0)
            self._backdrop.raise_()
        self._apply_geometry()
        self._center_on_parent()
        super().showEvent(event)

    def _apply_geometry(self) -> None:
        if self._fixed_size is not None:
            width, height = self._fixed_size
            self.resize(width, height)
        else:
            self.adjustSize()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        geo = parent.frameGeometry()
        self.move(geo.center() - self.rect().center())

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self.card:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            elif event.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
                self.move(event.globalPosition().toPoint() - self._drag_origin)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
        return super().eventFilter(watched, event)

    def _drop_backdrop(self) -> None:
        backdrop = self._backdrop
        self._backdrop = None
        if backdrop is not None:
            backdrop.stop()
            backdrop.hide()
            backdrop.setParent(None)
            backdrop.deleteLater()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._drop_backdrop()
        super().closeEvent(event)

    def reject(self) -> None:
        self._drop_backdrop()
        super().reject()

    def accept(self) -> None:
        self._drop_backdrop()
        super().accept()

    # ---------------------------------------------------------------- helpers
    def set_fixed_size(self, width: int, height: int) -> None:
        self._fixed_size = (width, height)
        self.setFixedSize(width, height)

    def add_button(self, text: str, variant: str = "secondary", *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if variant:
            button.setProperty("variant", variant)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            button.setDefault(True)
        self.footer.addWidget(button)
        return button


class ConfirmDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        *,
        confirm_text: str,
        cancel_text: str,
        danger: bool = False,
        icon: str = "alert",
    ) -> None:
        super().__init__(parent, title, width=460)
        self.subtitle_label.hide()
        dialogue = QHBoxLayout()
        dialogue.setSpacing(runtime.px(12))
        badge = IconBadge(icon, "danger" if danger else "accent", 38)
        dialogue.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setProperty("role", "muted")
        dialogue.addWidget(text, 1)
        self.body.addLayout(dialogue)
        self.footer.addStretch(1)

        cancel = self.add_button(cancel_text, "ghost")
        cancel.clicked.connect(self.reject)
        confirm = self.add_button(confirm_text, "danger" if danger else "primary", primary=True)
        confirm.clicked.connect(self.accept)
        confirm.setDefault(True)
        cancel.setAutoDefault(False)


class PromptDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        label: str,
        *,
        value: str = "",
        placeholder: str = "",
        confirm_text: str,
        cancel_text: str,
        required_text: str = "Required",
    ) -> None:
        super().__init__(parent, title, width=480)
        self._required_text = required_text
        self.subtitle_label.hide()
        self.label = QLabel(label)
        self.label.setProperty("role", "muted")
        self.body.addWidget(self.label)
        self.input = QLineEdit(value)
        self.input.setPlaceholderText(placeholder)
        self.input.setMinimumHeight(runtime.px(38))
        self.body.addWidget(self.input)
        self.error = InlineError()
        self.body.addWidget(self.error)
        self.footer.addStretch(1)
        cancel = self.add_button(cancel_text, "ghost")
        cancel.clicked.connect(self.reject)
        self.confirm = self.add_button(confirm_text, "primary", primary=True)
        self.confirm.clicked.connect(self._submit)
        cancel.setAutoDefault(False)
        self.input.returnPressed.connect(self._submit)
        self.input.selectAll()

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.error.show_error(self._required_text)
            self.input.setFocus()
            return
        self.accept()

    def value(self) -> str:
        return self.input.text().strip()
