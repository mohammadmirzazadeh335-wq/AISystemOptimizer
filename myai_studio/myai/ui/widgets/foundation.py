"""Small building blocks: labels, badges, chips, key caps, avatars, dividers.

Everything reads its colours from design tokens and listens for theme changes,
so light/dark/RTL switching needs no per-widget wiring.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import runtime
from ..theme.icons import draw as draw_icon
from .painting import paint_event


def repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_shadow(widget: QWidget, blur: int = 32, y_offset: int = 10, alpha: int = 110) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    color = QColor(runtime.theme().color("shadow"))
    color.setAlpha(alpha)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)
    return effect


class Badge(QLabel):
    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("badge", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setProperty("badge", tone)
        repolish(self)


class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", "vdivider" if vertical else "divider")
        if vertical:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class Kbd(QFrame):
    """A miniature key cap, e.g. Ctrl K."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        font = runtime.mono_font(9)
        metrics = QFontMetrics(font)
        self.setFixedSize(metrics.horizontalAdvance(text) + runtime.px(14), runtime.px(19))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(c("border_strong")), 1))
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(rect, runtime.px(5), runtime.px(5))
        painter.setFont(runtime.mono_font(9))
        painter.setPen(QColor(c("text_muted")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
class Dot(QWidget):
    def __init__(self, tone: str = "success", size: int = 7, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tone = tone
        self.setFixedSize(runtime.px(size), runtime.px(size))

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        color = QColor(runtime.theme().color(self._tone))
        glow = QColor(color)
        glow.setAlpha(55)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(self.rect())
        painter.setBrush(color)
        inner = self.rect().adjusted(runtime.px(2), runtime.px(2), -runtime.px(2), -runtime.px(2))
        painter.drawEllipse(inner)
class Avatar(QWidget):
    def __init__(self, initials: str = "AI", size: int = 30, accent: bool = False, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._initials = initials
        self._accent = accent
        self._size = size
        self.setFixedSize(runtime.px(size), runtime.px(size))

    def set_initials(self, initials: str) -> None:
        self._initials = initials
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = self.rect()
        if self._accent:
            gradient = QColor(c("accent"))
            gradient.setAlpha(40)
            painter.setPen(QPen(QColor(c("accent")), 1))
            painter.setBrush(gradient)
        else:
            painter.setPen(QPen(QColor(c("border_strong")), 1))
            painter.setBrush(QColor(c("surface_3")))
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
        painter.setFont(runtime.ui_font(10 if self._size < 34 else 12, 600))
        painter.setPen(QColor(c("accent") if self._accent else c("text_muted")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._initials)
class IconCircle(QWidget):
    """Icon inside a soft tinted circle — used by empty states and cards."""

    def __init__(self, name: str, tone: str = "accent", size: int = 40, icon_size: int = 18, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._name = name
        self._tone = tone
        self.setFixedSize(runtime.px(size), runtime.px(size))

    def set_icon(self, name: str) -> None:
        self._name = name
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        tone_color = QColor(c(self._tone))
        soft = QColor(tone_color)
        soft.setAlpha(28)
        painter.setPen(QPen(QColor(c("border")), 1))
        painter.setBrush(soft)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        icon_rect = self.rect().adjusted(
            (self.width() - runtime.px(18)) // 2,
            (self.height() - runtime.px(18)) // 2,
            -(self.width() - runtime.px(18)) // 2,
            -(self.height() - runtime.px(18)) // 2,
        )
        draw_icon(painter, self._name, icon_rect, c(self._tone), 1.8)
class SectionLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "section")


class EmptyState(QWidget):
    def __init__(
        self,
        title: str,
        body: str = "",
        icon: str = "inbox",
        tone: str = "accent",
        action: QWidget | None = None,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(10))
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        circle = IconCircle(icon, tone, 46 if not compact else 38)
        self.circle = circle
        layout.addWidget(circle, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setProperty("role", "h3")
        layout.addWidget(self.title_label)
        self.body_label = QLabel(body)
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_label.setWordWrap(True)
        self.body_label.setProperty("role", "muted")
        self.body_label.setMaximumWidth(runtime.px(320))
        layout.addWidget(self.body_label, 0, Qt.AlignmentFlag.AlignHCenter)
        if action is not None:
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)


class HoverGlow(QWidget):
    """Decorative ambient light; paints two very soft radial gradients."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        w, h = self.width(), self.height()
        glow_a = QColor(c("ambient_a"))
        glow_a.setAlpha(58 if runtime.theme().is_dark else 80)
        glow_b = QColor(c("ambient_b"))
        glow_b.setAlpha(36 if runtime.theme().is_dark else 60)

        from PySide6.QtGui import QRadialGradient

        grad_a = QRadialGradient(w * 0.22, -h * 0.1, max(w, h) * 0.75)
        grad_a.setColorAt(0.0, glow_a)
        grad_a.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad_a)

        grad_b = QRadialGradient(w * 0.92, h * 1.05, max(w, h) * 0.6)
        grad_b.setColorAt(0.0, glow_b)
        grad_b.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad_b)
class BusyIndicator(QWidget):
    """Three softly pulsing dots used in inline status rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(runtime.px(30), runtime.px(12))
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start(240)

    def stop(self) -> None:
        self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 3
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color("accent")
        for i in range(3):
            color = QColor(c)
            color.setAlpha(240 if i == self._phase else 80)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            x = i * runtime.px(9) + runtime.px(3)
            painter.drawEllipse(x, runtime.px(4), runtime.px(4), runtime.px(4))
def label(text: str, role: str = "", wrap: bool = False, size: int | None = None) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    if size:
        font = widget.font()
        font.setPixelSize(runtime.px(size))
        widget.setFont(font)
    return widget


def icon_label(name: str, tone: str = "muted", size: int = 16) -> QLabel:
    widget = QLabel()
    widget.setPixmap(runtime.icons().px(name, size, tone))
    widget.setFixedSize(runtime.px(size), runtime.px(size))
    return widget


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, emphasis: bool = False, padding: int = 14) -> None:
        super().__init__(parent)
        self.setProperty("panel", "card-emphasis" if emphasis else "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            runtime.px(padding), runtime.px(padding), runtime.px(padding), runtime.px(padding)
        )
        self._layout.setSpacing(runtime.px(8))

    def body(self) -> QVBoxLayout:
        return self._layout


class IconBadge(QWidget):
    """Circular tinted icon used in dialogs and notices."""

    def __init__(self, icon: str = "alert", tone: str = "accent", size: int = 38, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._icon = icon
        self._tone = tone
        self.setFixedSize(runtime.px(size), runtime.px(size))

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        tone = runtime.theme().color(self._tone)
        soft = QColor(tone)
        soft.setAlpha(30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft)
        painter.drawEllipse(self.rect())
        inset = self.width() * 0.26
        draw_icon(
            painter,
            self._icon,
            self.rect().adjusted(int(inset), int(inset), -int(inset), -int(inset)),
            tone,
            1.9,
        )
class ElidedLabel(QWidget):
    """Single-line label that elides instead of breaking the layout."""

    def __init__(
        self,
        text: str = "",
        *,
        pixel_size: int = 14,
        weight: int = 600,
        tone: str = "text",
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._pixel_size = pixel_size
        self._weight = weight
        self._tone = tone
        self._alignment = alignment
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(runtime.px(40))

    def setText(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.updateGeometry()
            self.update()

    def text(self) -> str:
        return self._text

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(runtime.ui_font(self._pixel_size, self._weight))
        return QSize(metrics.horizontalAdvance(self._text) + 4, metrics.height() + runtime.px(2))

    def minimumSizeHint(self) -> QSize:
        return QSize(runtime.px(40), self.sizeHint().height())

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        painter.setFont(runtime.ui_font(self._pixel_size, self._weight))
        painter.setPen(QColor(runtime.theme().color(self._tone)))
        metrics = QFontMetrics(painter.font())
        text = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, max(10, self.width() - 2))
        align = self._alignment
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft and align == Qt.AlignmentFlag.AlignLeft:
            align = Qt.AlignmentFlag.AlignRight
        painter.drawText(self.rect(), align | Qt.AlignmentFlag.AlignVCenter, text)
class GradientHeadline(QWidget):
    """Large display text with a restrained accent gradient."""

    def __init__(self, text: str = "", pixel_size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._pixel_size = pixel_size
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(runtime.px(pixel_size + 10))

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(runtime.ui_font(self._pixel_size, 700))
        return QSize(metrics.horizontalAdvance(self._text) + runtime.px(20), metrics.height() + runtime.px(12))

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        font = runtime.ui_font(self._pixel_size, 700)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        width = min(self.width(), metrics.horizontalAdvance(self._text))
        x = (self.width() - width) / 2
        baseline_rect = self.rect()
        gradient = QLinearGradient(x, 0, x + width, 0)
        gradient.setColorAt(0.0, QColor(c("text")))
        gradient.setColorAt(0.62, QColor(c("text")))
        gradient.setColorAt(1.0, QColor(c("accent")))
        painter.setPen(QPen(QBrush(gradient), 1))
        painter.drawText(baseline_rect, Qt.AlignmentFlag.AlignCenter, self._text)
