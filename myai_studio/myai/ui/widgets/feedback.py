"""Toasts, skeletons, spinners and meters."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from ..theme import runtime
from .buttons import IconButton
from .painting import paint_event


class Toast(QFrame):
    dismissed = Signal(object)

    def __init__(self, message: str, level: str = "info", timeout: int = 3400, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("panel", "toast")
        self._level = level
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(12), runtime.px(8), runtime.px(8), runtime.px(8))
        layout.setSpacing(runtime.px(9))
        self._icon = QLabel()
        self._icon.setFixedSize(runtime.px(18), runtime.px(18))
        layout.addWidget(self._icon)
        self._label = QLabel(message)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(runtime.px(420))
        layout.addWidget(self._label, 1)
        close = IconButton("close", "Close", 24, icon_size=12)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(runtime.px(30))
        shadow.setOffset(0, runtime.px(8))
        color = QColor(runtime.theme().color("shadow"))
        color.setAlpha(140)
        shadow.setColor(color)
        self.setGraphicsEffect(shadow)

        # A widget can own a single graphics effect; the drop shadow is used
        # and the toast is revealed with a short position animation.
        self.setGraphicsEffect(shadow)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self.dismiss)
        if timeout > 0:
            self._timeout.start(timeout)
        self._refresh()

    def _refresh(self) -> None:
        c = runtime.theme().color
        tone = {"success": "success", "error": "danger", "warning": "warning", "info": "accent"}.get(
            self._level, "accent"
        )
        icon = {"success": "check", "error": "alert", "warning": "alert", "info": "info"}.get(self._level, "info")
        self._icon.setPixmap(runtime.icons().px(icon, 16, "normal"))
        self._label.setStyleSheet(f"color: {c('text')}; font-size: {runtime.px(12)}px;")
        border = c(tone)
        self.setStyleSheet(
            f"QFrame#Toast {{ background-color: {c('surface_2')}; border: 1px solid {border};"
            f" border-radius: {runtime.px(12)}px; }}"
        )

    def dismiss(self) -> None:
        self._timeout.stop()
        self.hide()
        self.dismissed.emit(self)
        self.deleteLater()


class ToastManager(QObject):
    """Stacks transient notifications above the composer."""

    def __init__(self, host: QWidget, bottom_margin: int = 110) -> None:
        super().__init__(host)
        self._host = host
        self._toasts: list[Toast] = []
        self._bottom_margin = bottom_margin
        host.installEventFilter(self)

    def show(self, message: str, level: str = "info", timeout: int = 3400) -> Toast:
        toast = Toast(message, level, timeout, self._host)
        toast.dismissed.connect(self._remove)
        self._toasts.append(toast)
        while len(self._toasts) > 3:
            oldest = self._toasts.pop(0)
            oldest.hide()
            oldest.deleteLater()
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self._layout_toasts(animate=True)
        return toast

    def set_bottom_margin(self, margin: int) -> None:
        """Toasts sit above the composer in chat, near the edge on full pages."""
        self._bottom_margin = margin
        self._layout_toasts(animate=False)

    def clear(self) -> None:
        for toast in self._toasts:
            toast.hide()
            toast.deleteLater()
        self._toasts.clear()

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout_toasts(animate=True)

    def _layout_toasts(self, animate: bool = False) -> None:
        if not self._toasts:
            return
        spacing = runtime.px(8)
        bottom = self._host.height() - runtime.px(self._bottom_margin)
        for toast in reversed(self._toasts):
            toast.adjustSize()
            width = min(toast.width(), self._host.width() - runtime.px(48))
            x = (self._host.width() - width) // 2
            y = bottom - toast.height()
            target = QPoint(x, y)
            if animate:
                start = toast.pos() if toast.pos().y() else QPoint(x, y + runtime.px(16))
                anim = QPropertyAnimation(toast, b"pos", toast)
                anim.setDuration(180)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setStartValue(start)
                anim.setEndValue(target)
                anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            else:
                toast.move(target)
            bottom = y - spacing

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self._host and event.type() == event.Type.Resize:
            self._layout_toasts(animate=False)
        return False


class Skeleton(QWidget):
    def __init__(self, height: int = 12, radius: int = 6, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._radius = radius
        self.setFixedHeight(runtime.px(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(33)

    def _tick(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def showEvent(self, event) -> None:  # noqa: ANN001
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: ANN001
        self._timer.stop()
        super().hideEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        base = QColor(c("skeleton"))
        highlight = QColor(c("skeleton_highlight"))
        gradient = QLinearGradient(0, 0, self.width(), 0)
        pos = self._phase
        gradient.setColorAt(max(0.0, pos - 0.2), base)
        gradient.setColorAt(pos, highlight)
        gradient.setColorAt(min(1.0, pos + 0.2), base)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(self.rect(), runtime.px(self._radius), runtime.px(self._radius))
class Spinner(QWidget):
    def __init__(self, size: int = 22, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(runtime.px(size), runtime.px(size))
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setVisible(False)

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def start(self) -> None:
        self.show()
        self._timer.start(28)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        pen = QPen(QColor(c("surface_3")), runtime.px(2))
        painter.setPen(pen)
        painter.drawEllipse(rect)
        pen.setColor(QColor(c("accent")))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, int(self._angle * 16), 100 * 16)
class DonutMeter(QWidget):
    value_changed = Signal(float)

    def __init__(self, size: int = 96, parent: QWidget | None = None, *, center_text: str = "") -> None:
        super().__init__(parent)
        self.setFixedSize(runtime.px(size), runtime.px(size))
        self._value = 0.0
        self._target = 0.0
        self._center_text = center_text
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def set_value(self, value: float, *, animate: bool = True, center_text: str | None = None) -> None:
        value = max(0.0, min(1.0, float(value)))
        if center_text is not None:
            self._center_text = center_text
        self._target = value
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(value)
            self._anim.start()
        else:
            self._value = value
            self.update()
        self.value_changed.emit(value)

    def _on_anim(self, value) -> None:  # noqa: ANN001
        self._value = float(value)
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        thickness = runtime.px(7)
        rect = QRectF(self.rect()).adjusted(thickness / 2 + 1, thickness / 2 + 1, -thickness / 2 - 1, -thickness / 2 - 1)
        track = QPen(QColor(c("surface_3")), thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)
        if self._value > 0.001:
            conical = QConicalGradient(rect.center(), 90)
            conical.setColorAt(0.0, QColor(c("accent")))
            conical.setColorAt(0.85, QColor(c("violet")))
            conical.setColorAt(1.0, QColor(c("accent")))
            pen = QPen(conical, thickness)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * self._value))
        text = self._center_text or f"{round(self._value * 100)}%"
        painter.setFont(runtime.ui_font(13 if self.width() < runtime.px(80) else 16, 700))
        painter.setPen(QColor(c("text")))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)
class BarMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(runtime.px(6))
        self._value = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c("surface_3")))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._value > 0:
            width = self.width() * self._value
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0, QColor(c("accent")))
            gradient.setColorAt(1, QColor(c("violet")))
            painter.setBrush(gradient)
            painter.drawRoundedRect(QRectF(0, 0, max(6.0, width), self.height()), 3, 3)
class TypewriterText(QLabel):
    """Used by the welcome header for a subtle entrance effect."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full = text
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._index = len(text)

    def animate_in(self) -> None:
        self._index = 0
        self.setText("")
        self._timer.start(16)

    def _tick(self) -> None:
        self._index = min(len(self._full), self._index + 2)
        self.setText(self._full[: self._index])
        if self._index >= len(self._full):
            self._timer.stop()
