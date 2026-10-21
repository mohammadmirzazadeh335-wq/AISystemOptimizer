"""Interactive controls with hand-painted states.

Qt stylesheets cannot express hover interpolation, moving selection pills or
gradient send buttons, so the most tactile controls are painted directly.
All of them stay keyboard accessible with a visible focus ring.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import (
    QEasingCurve,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..theme import runtime
from ..theme.icons import draw as draw_icon
from ..theme.tokens import build_theme
from .painting import paint_event


class _HoverMixin:
    """Smooth 0..1 hover value shared by painted buttons."""

    def _init_hover(self) -> None:
        self._hover_value = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

    def _on_hover_value(self, value) -> None:  # noqa: ANN001
        self._hover_value = float(value)
        self.update()

    def _animate_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_value)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()


class NavButton(_HoverMixin, QAbstractButton):
    def __init__(
        self,
        text: str,
        icon_name: str,
        parent: QWidget | None = None,
        *,
        badge: str = "",
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._icon = icon_name
        self._badge = badge
        self._collapsed = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(runtime.px(38))
        self.setMaximumHeight(runtime.px(38))
        self._init_hover()
        self.setToolTip(text)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setMinimumHeight(runtime.px(40))
        self.setMaximumHeight(runtime.px(40))
        self.setToolTip(self._text if collapsed else "")
        self.updateGeometry()
        self.update()

    def set_text(self, text: str) -> None:
        self._text = text
        self.setToolTip(text)
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(runtime.ui_font(13, 500))
        width = runtime.px(44) if self._collapsed else metrics.horizontalAdvance(self._text) + runtime.px(58)
        return QSize(width, runtime.px(38))

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._animate_hover(0.0)
        super().leaveEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = runtime.px(10)
        checked = self.isChecked()
        self.underMouse() and not checked

        if checked:
            painter.setBrush(QColor(c("accent_soft")))
            painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.35)), 1))
            painter.drawRoundedRect(rect, radius, radius)
        elif self._hover_value > 0.01:
            hover_color = QColor(c("nav_hover"))
            hover_color.setAlphaF(min(1.0, 0.9 * self._hover_value))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hover_color)
            painter.drawRoundedRect(rect, radius, radius)

        if self.hasFocus():
            painter.setPen(QPen(QColor(c("ring")), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius - 2, radius - 2)

        danger = self.property("tone") == "danger"
        tone_color = c("danger") if danger else (c("accent") if checked else c("text_muted"))
        icon_size = runtime.px(18)
        content_height = self.height()
        if self._collapsed:
            icon_rect = QRectF(
                (self.width() - icon_size) / 2, (content_height - icon_size) / 2, icon_size, icon_size
            )
            draw_icon(painter, self._icon, icon_rect, tone_color, 1.7)
        else:
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            pad = runtime.px(12)
            x = self.width() - pad - icon_size if rtl else pad
            icon_rect = QRectF(x, (content_height - icon_size) / 2, icon_size, icon_size)
            draw_icon(painter, self._icon, icon_rect, tone_color, 1.7)
            painter.setFont(runtime.ui_font(13, 500 if checked else 400))
            painter.setPen(QColor(c("text") if checked else c("text_muted")))
            text_pad = runtime.px(38)
            if rtl:
                text_rect = QRectF(pad, 0, self.width() - text_pad - pad + icon_size - runtime.px(30), content_height)
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            else:
                text_rect = QRectF(pad + icon_size + runtime.px(10), 0, self.width() - icon_size - text_pad - pad - runtime.px(20), content_height)
                align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            metrics = QFontMetrics(painter.font())
            elided = metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, align, elided)
            if self._badge:
                badge_font = runtime.ui_font(9, 600)
                painter.setFont(badge_font)
                bm = QFontMetrics(badge_font)
                bw = bm.horizontalAdvance(self._badge) + runtime.px(12)
                bx = pad if rtl else self.width() - pad - bw
                badge_rect = QRectF(bx, content_height / 2 - runtime.px(8), bw, runtime.px(16))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(runtime.theme().alpha("violet", 0.16)))
                painter.drawRoundedRect(badge_rect, runtime.px(6), runtime.px(6))
                painter.setPen(QColor(c("violet")))
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self._badge)
class IconButton(QAbstractButton):
    """Square icon button with hover tint, tone changes and focus ring."""

    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        size: int = 34,
        parent: QWidget | None = None,
        *,
        icon_size: int = 18,
        tone: str = "muted",
        checkable: bool = False,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = icon_size
        self._tone = tone
        self._size = size
        self.setFixedSize(runtime.px(size), runtime.px(size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCheckable(checkable)
        if tooltip:
            self.setToolTip(tooltip)

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self.update()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self.update()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = runtime.px(9)
        checked = self.isChecked()
        tone = "accent" if checked else self._tone
        if checked:
            painter.setBrush(QColor(c("accent_soft")))
            painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.4)), 1))
            painter.drawRoundedRect(rect, radius, radius)
        elif self.underMouse() and self.isEnabled():
            painter.setBrush(QColor(c("surface_2")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, radius, radius)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect, radius, radius)
        color = c("text_faint") if not self.isEnabled() else c(tone)
        icon_size = runtime.px(self._icon_size)
        draw_icon(
            painter,
            self._icon_name,
            QRectF(
                (self.width() - icon_size) / 2,
                (self.height() - icon_size) / 2,
                icon_size,
                icon_size,
            ),
            color,
            1.75,
        )
class ToggleSwitch(QAbstractButton):
    def __init__(self, parent: QWidget | None = None, *, on: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(runtime.px(40), runtime.px(23))
        self._pos = 1.0 if on else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def _set_pos(self, value) -> None:  # noqa: ANN001
        self._pos = float(value)
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        off = QColor(c("surface_3"))
        on = QColor(c("accent"))
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        painter.setPen(QPen(QColor(c("border_strong") if self._pos < 0.5 else c("accent")), 1))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        knob = QColor("#FFFFFF") if runtime.theme().is_dark else QColor("#FFFFFF")
        d = rect.height() - runtime.px(6)
        x_off = runtime.px(3) + (rect.width() - d - runtime.px(6)) * self._pos
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(x_off, runtime.px(3), d, d))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
class SegmentedControl(QWidget):
    """Animated pill switcher (used for Chat/Agent and density)."""

    changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]],
        parent: QWidget | None = None,
        *,
        current: str | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._current = current or (self._items[0][0] if self._items else "")
        self._index = self._index_of(self._current)
        self._anim_index = float(self._index)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._compact = compact
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._sync_width()

    def _sync_width(self) -> None:
        """Size the pill from the *current* font scale.

        The labels are painted with ``runtime.ui_font`` on every repaint, so a
        width frozen at construction overflowed its segments after the user
        raised the font scale (screenshot: Chat/Agent labels ran together).
        """
        metrics = QFontMetrics(runtime.ui_font(12, 500))
        width = sum(
            metrics.horizontalAdvance(label) + runtime.px(24 if self._compact else 30)
            for _, label in self._items
        ) + runtime.px(8)
        height = runtime.px(30 if self._compact else 34)
        if self.minimumWidth() != width or self.minimumHeight() != height:
            self.setFixedSize(width, height)
        self.updateGeometry()

    def refresh_metrics(self) -> None:
        self._sync_width()

    def _index_of(self, key: str) -> int:
        for index, (item_key, _) in enumerate(self._items):
            if item_key == key:
                return index
        return 0

    @property
    def value(self) -> str:
        return self._current

    def set_items(self, items: Iterable[tuple[str, str]]) -> None:
        self._items = list(items)
        if not any(key == self._current for key, _ in self._items) and self._items:
            self._current = self._items[0][0]
        self._index = self._index_of(self._current)
        self._anim_index = float(self._index)
        self._sync_width()

    def set_value(self, key: str, *, animate: bool = True) -> None:
        if key not in {k for k, _ in self._items} or key == self._current:
            return
        old = self._index
        self._current = key
        self._index = self._index_of(key)
        if animate:
            self._anim.stop()
            self._anim.setStartValue(float(old))
            self._anim.setEndValue(float(self._index))
            self._anim.start()
        else:
            self._anim_index = float(self._index)
            self.update()
        self.changed.emit(key)

    def _on_anim(self, value) -> None:  # noqa: ANN001
        self._anim_index = float(value)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton or not self._items:
            return
        x = event.position().x()
        width = (self.width() - runtime.px(8)) / len(self._items)
        index = min(len(self._items) - 1, max(0, int((x - runtime.px(4)) // width)))
        self.setFocus()
        self.set_value(self._items[index][0])

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if event.key() == Qt.Key.Key_Left else 1
            if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                step *= -1
            index = max(0, min(len(self._items) - 1, self._index + step))
            self.set_value(self._items[index][0])
            event.accept()
            return
        super().keyPressEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = runtime.px(10)
        painter.setPen(QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(rect, radius, radius)

        count = max(1, len(self._items))
        inner = rect.adjusted(runtime.px(3), runtime.px(3), -runtime.px(3), -runtime.px(3))
        seg_width = inner.width() / count
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        visual_index = (count - 1 - self._anim_index) if rtl else self._anim_index
        pill = QRectF(inner.x() + seg_width * visual_index, inner.y(), seg_width, inner.height())
        painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.5)), 1))
        painter.setBrush(QColor(c("surface")))
        painter.drawRoundedRect(pill, radius - runtime.px(4), radius - runtime.px(4))

        painter.setFont(runtime.ui_font(12, 500))
        for index, (key, text) in enumerate(self._items):
            order_index = (count - 1 - index) if rtl else index
            cell = QRectF(
                inner.x() + seg_width * order_index, inner.y(), seg_width, inner.height()
            )
            active = key == self._current
            painter.setPen(QColor(c("text") if active else c("text_muted")))
            painter.setFont(runtime.ui_font(12, 600 if active else 500))
            painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, text)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect, radius, radius)
class SendButton(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(runtime.px(40), runtime.px(40))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Send")
        self._mode = "send"

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    @property
    def mode(self) -> str:
        return self._mode

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        enabled = self.isEnabled()
        hover = self.underMouse() and enabled

        if self._mode == "stop":
            painter.setPen(QPen(QColor(c("border_strong")), 1))
            painter.setBrush(QColor(c("surface_3")) if not hover else QColor(c("danger_soft")))
            painter.drawEllipse(rect)
            icon_color = c("danger")
            icon = "stop"
        elif not enabled:
            painter.setPen(QPen(QColor(c("border")), 1))
            painter.setBrush(QColor(c("surface_2")))
            painter.drawEllipse(rect)
            icon_color = c("text_faint")
            icon = "arrow-up"
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(c("accent_hover")))
            gradient.setColorAt(1.0, QColor(c("accent_pressed")))
            painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.7)), 1))
            painter.setBrush(gradient)
            painter.drawEllipse(rect)
            icon_color = c("accent_contrast")
            icon = "arrow-up"
            if hover:
                glow = QColor(c("accent"))
                glow.setAlpha(40)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(rect.adjusted(-2, -2, 2, 2))

        icon_size = runtime.px(18)
        draw_icon(
            painter,
            icon,
            QRectF(
                (self.width() - icon_size) / 2,
                (self.height() - icon_size) / 2,
                icon_size,
                icon_size,
            ),
            icon_color,
            2.0,
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1.5))
            painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
class AccentSwatch(QAbstractButton):
    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setFixedSize(runtime.px(30), runtime.px(30))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(key.capitalize())

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        from ..theme.tokens import ACCENTS

        theme = runtime.theme()
        accent = ACCENTS.get(self.key, ACCENTS["azure"])
        color = accent["light"] if not theme.is_dark else accent["dark"]
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(rect)
        if self.isChecked():
            painter.setPen(QPen(QColor("#FFFFFF" if theme.is_dark else "#FFFFFF"), 2))
            center = rect.center()
            painter.drawLine(
                int(center.x() - runtime.px(3)),
                int(center.y()),
                int(center.x() - runtime.px(1)),
                int(center.y() + runtime.px(2)),
            )
            painter.drawLine(
                int(center.x() - runtime.px(1)),
                int(center.y() + runtime.px(2)),
                int(center.x() + runtime.px(3)),
                int(center.y() - runtime.px(2)),
            )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.color("ring")), 1))
            painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
class ThemePreview(QAbstractButton):
    """Miniature interface preview used to pick a theme."""

    def __init__(self, theme_key: str, label_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_key = theme_key
        self._label = label_text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(runtime.px(94))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        accent = runtime.theme().accent_key
        system_dark = runtime.theme().is_dark
        preview = build_theme(self.theme_key, accent, system_dark=system_dark)
        c = preview.color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = runtime.px(12)
        painter.setPen(QPen(QColor(c("accent")), 2) if self.isChecked() else QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("bg")))
        painter.drawRoundedRect(rect, radius, radius)

        inset = runtime.px(8)
        preview_rect = rect.adjusted(inset, inset, -inset, -runtime.px(24))
        painter.setClipRect(preview_rect)
        painter.setPen(Qt.PenStyle.NoPen)
        # sidebar
        painter.setBrush(QColor(c("sidebar")))
        painter.drawRoundedRect(
            QRectF(preview_rect.x(), preview_rect.y(), preview_rect.width() * 0.24, preview_rect.height()),
            6,
            6,
        )
        # header
        painter.setBrush(QColor(c("header")))
        painter.drawRect(
            QRectF(
                preview_rect.x() + preview_rect.width() * 0.24,
                preview_rect.y(),
                preview_rect.width() * 0.76,
                runtime.px(10),
            )
        )
        # content cards
        painter.setBrush(QColor(c("surface")))
        painter.drawRoundedRect(
            QRectF(
                preview_rect.x() + preview_rect.width() * 0.30,
                preview_rect.y() + runtime.px(18),
                preview_rect.width() * 0.42,
                preview_rect.height() * 0.48,
            ),
            4,
            4,
        )
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(
            QRectF(
                preview_rect.x() + preview_rect.width() * 0.76,
                preview_rect.y() + runtime.px(18),
                preview_rect.width() * 0.18,
                preview_rect.height() * 0.48,
            ),
            4,
            4,
        )
        painter.setBrush(QColor(c("accent")))
        painter.drawRoundedRect(
            QRectF(
                preview_rect.x() + preview_rect.width() * 0.30,
                preview_rect.y() + preview_rect.height() * 0.72,
                preview_rect.width() * 0.42,
                runtime.px(5),
            ),
            2,
            2,
        )
        painter.setClipping(False)

        # The caption sits inside the preview card, so it must use that
        # palette - a light card on a dark workspace needs dark text.
        painter.setFont(runtime.ui_font(11, 600 if self.isChecked() else 500))
        painter.setPen(QColor(c("text")))
        label_rect = QRectF(rect.x() + runtime.px(12), rect.bottom() - runtime.px(20), rect.width() - runtime.px(24), runtime.px(14))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)
        if self.isChecked():
            check_size = runtime.px(14)
            check_rect = QRectF(
                rect.right() - check_size - runtime.px(8), rect.bottom() - runtime.px(21), check_size, check_size
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c("accent")))
            painter.drawEllipse(check_rect)
            draw_icon(painter, "check", check_rect.adjusted(3, 3, -3, -3), c("accent_contrast"), 2.4)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(runtime.theme().color("ring")), 1))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
