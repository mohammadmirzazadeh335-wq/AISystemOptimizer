"""Reusable building blocks for the Persian RTL interface."""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pars_erp.security.passwords import password_strength


class Card(QFrame):
    """White surface with a soft border - the base container of every screen."""

    def __init__(self, parent: QWidget | None = None, *, title: str | None = None,
                 subtitle: str | None = None, spacing: int = 12) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(spacing)
        if title:
            header = QVBoxLayout()
            header.setSpacing(2)
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            header.addWidget(title_label)
            if subtitle:
                subtitle_label = QLabel(subtitle)
                subtitle_label.setObjectName("HintText")
                subtitle_label.setWordWrap(True)
                header.addWidget(subtitle_label)
            self._layout.addLayout(header)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def body(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class KpiCard(QFrame):
    """Compact metric tile used on the dashboard."""

    clicked = Signal()

    def __init__(self, title: str, value: str = "—", hint: str = "", *,
                 tone: str = "primary", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._tone = tone
        self.setMinimumHeight(104)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.tone_bar = QFrame()
        self.tone_bar.setFixedSize(34, 4)
        self.tone_bar.setStyleSheet(
            f"background-color: {self._color(tone)}; border-radius: 2px;")
        top.addWidget(self.tone_bar)
        layout.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("KpiValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.value_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("KpiHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                     | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

    @staticmethod
    def _color(tone: str) -> str:
        return {
            "primary": "#2563eb", "success": "#067647", "warning": "#b54708",
            "danger": "#b42318", "info": "#175cd3", "neutral": "#98a2b3",
        }.get(tone, "#2563eb")

    def set_value(self, value: str, hint: str | None = None) -> None:
        self.value_label.setText(value)
        if hint is not None:
            self.hint_label.setText(hint)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Badge(QLabel):
    """Small coloured pill used for statuses and severities."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        colors = {
            "success": ("#e7f6ee", "#067647"),
            "warning": ("#fdf3e7", "#b54708"),
            "danger": ("#fdeceb", "#b42318"),
            "info": ("#e8f0ff", "#175cd3"),
            "neutral": ("#f2f4f7", "#475467"),
        }
        background, foreground = colors.get(tone, colors["neutral"])
        self.setStyleSheet(
            f"background-color: {background}; color: {foreground}; border-radius: 9px;"
            f" padding: 2px 10px; font-weight: 600;")


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFixedHeight(1)


class FieldRow(QWidget):
    """Label + control + inline validation message."""

    def __init__(self, label: str, control: QWidget, *, hint: str | None = None,
                 required: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.label = QLabel(f"{label} *" if required else label)
        self.label.setObjectName("FieldLabel")
        layout.addWidget(self.label)
        self.control = control
        if isinstance(control, QLineEdit):
            control.setMinimumHeight(34)
        layout.addWidget(control)
        self.hint_label = QLabel(hint or "")
        self.hint_label.setObjectName("HintText")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(hint))
        layout.addWidget(self.hint_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

    def set_error(self, message: str | None) -> None:
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        if isinstance(self.control, QLineEdit):
            self.control.setProperty("invalid", bool(message))
            self.control.style().unpolish(self.control)
            self.control.style().polish(self.control)

    def value(self):
        if isinstance(self.control, QLineEdit):
            return self.control.text()
        if isinstance(self.control, QComboBox):
            return self.control.currentData()
        if isinstance(self.control, QCheckBox):
            return self.control.isChecked()
        return None


class SearchInput(QLineEdit):
    """Search box that emits a debounced signal while typing."""

    searchChanged = Signal(str)

    def __init__(self, placeholder: str = "جست‌وجو…", *, delay_ms: int = 250,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(34)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(lambda: self.searchChanged.emit(self.text().strip()))
        self.textChanged.connect(lambda _text: self._timer.start())
        self.returnPressed.connect(self._emit_now)

    def _emit_now(self) -> None:
        self._timer.stop()
        self.searchChanged.emit(self.text().strip())


class PasswordField(QWidget):
    """Password input with a visibility toggle and optional strength meter."""

    def __init__(self, placeholder: str = "رمز عبور", *, show_strength: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        self.input.setPlaceholderText(placeholder)
        self.input.setMinimumHeight(34)
        row.addWidget(self.input, 1)

        self.toggle = QPushButton("نمایش")
        self.toggle.setProperty("variant", "ghost")
        self.toggle.setCheckable(True)
        self.toggle.setFixedWidth(64)
        self.toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggle.toggled.connect(self._on_toggle)
        row.addWidget(self.toggle)
        layout.addLayout(row)

        self.strength_label = QLabel("")
        self.strength_label.setObjectName("HintText")
        self.strength_label.setVisible(show_strength)
        layout.addWidget(self.strength_label)

        if show_strength:
            self.input.textChanged.connect(self._update_strength)

    def _on_toggle(self, checked: bool) -> None:
        self.input.setEchoMode(QLineEdit.EchoMode.Normal if checked
                               else QLineEdit.EchoMode.Password)
        self.toggle.setText("پنهان" if checked else "نمایش")

    def _update_strength(self, text: str) -> None:
        if not text:
            self.strength_label.setText("")
            return
        score, label = password_strength(text)
        colors = ["#b42318", "#b42318", "#b54708", "#067647", "#067647"]
        self.strength_label.setText(f"قدرت رمز: {label}")
        self.strength_label.setStyleSheet(f"color: {colors[score]};")

    def text(self) -> str:
        return self.input.text()

    def setText(self, value: str) -> None:  # noqa: N802 - mirror Qt API
        self.input.setText(value)

    def clear(self) -> None:
        self.input.clear()

    def setFocus(self) -> None:  # noqa: N802
        self.input.setFocus()


class EmptyState(QWidget):
    """Friendly placeholder shown when a list has no rows."""

    def __init__(self, title: str, description: str = "", *, icon: str = "🗂",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 28pt; color: #98a2b3;")
        layout.addWidget(icon_label)
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        if description:
            desc = QLabel(description)
            desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc.setObjectName("HintText")
            desc.setWordWrap(True)
            layout.addWidget(desc)


class InfoRow(QWidget):
    """Read-only label/value pair (detail panels)."""

    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        self.label = QLabel(label)
        self.label.setObjectName("CardTitle")
        self.label.setMinimumWidth(130)
        self.value = QLabel(value)
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label)
        layout.addWidget(self.value, 1)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class BarChart(QWidget):
    """Minimal dependency-free bar chart (Qt Charts is a separate package)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._values: list[int] = []
        self._color = QColor("#2563eb")
        self._soft = QColor("#dbe7ff")
        self._text = QColor("#667085")
        self._persian_digits = True
        self.setMinimumHeight(120)

    def set_theme(self, *, color: str, soft: str, text: str) -> None:
        self._color = QColor(color)
        self._soft = QColor(soft)
        self._text = QColor(text)
        self.update()

    def set_digits(self, persian: bool) -> None:
        self._persian_digits = bool(persian)
        self.update()

    def set_data(self, labels: Iterable[str], values: Iterable[int]) -> None:
        self._labels = [str(label) for label in labels]
        self._values = [max(0, int(value)) for value in values]
        self.update()

    def _text_of(self, value: object) -> str:
        from pars_erp.ui.formatting import to_display_digits

        return to_display_digits(str(value), persian=self._persian_digits)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        if not self._values:
            painter.setPen(self._text)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "داده‌ای برای نمایش نیست")
            painter.end()
            return

        base_y = height - 24
        left, right = 10, width - 10
        count = len(self._values)
        slot = (right - left) / max(1, count)
        bar_width = max(6.0, min(slot * 0.55, 42.0))
        maximum = max(self._values)

        # baseline
        painter.setPen(QPen(self._soft, 1))
        painter.drawLine(QPointF(left, base_y), QPointF(right, base_y))

        if maximum == 0:
            painter.setPen(self._text)
            painter.drawText(QRectF(left, 0, right - left, base_y - 6),
                             Qt.AlignmentFlag.AlignCenter,
                             "در این بازه موردی ثبت نشده است")
            for index in range(count):
                center = left + slot * (count - index - 0.5)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._soft)
                painter.drawRoundedRect(QRectF(center - bar_width / 2, base_y - 3,
                                               bar_width, 3), 2, 2)
                if index < len(self._labels):
                    painter.setPen(self._text)
                    painter.drawText(
                        QRectF(center - slot / 2, base_y + 5, slot, 16),
                        Qt.AlignmentFlag.AlignCenter, self._text_of(self._labels[index]))
            painter.end()
            return

        # bars: the most recent value sits on the left (RTL reading order)
        for index, value in enumerate(self._values):
            center = left + slot * (count - index - 0.5)
            bar_height = (base_y - 26) * (value / maximum) if maximum else 0
            rect = QRectF(center - bar_width / 2, base_y - bar_height, bar_width,
                          max(3.0, bar_height))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color if value else self._soft)
            painter.drawRoundedRect(rect, 4, 4)
            if value and bar_width >= 14:
                painter.setPen(self._text)
                font = painter.font()
                font.setPointSizeF(max(6.5, font.pointSizeF() - 1.0))
                painter.setFont(font)
                painter.drawText(QRectF(center - slot / 2, base_y - bar_height - 16,
                                        slot, 14),
                                 Qt.AlignmentFlag.AlignCenter, self._text_of(value))
            if index < len(self._labels):
                painter.setPen(self._text)
                painter.drawText(QRectF(center - slot / 2, base_y + 5, slot, 16),
                                 Qt.AlignmentFlag.AlignCenter,
                                 self._text_of(self._labels[index]))
        painter.end()


def apply_shadow(widget: QWidget, *, blur: int = 24, color: str = "#101828",
                 alpha: int = 22) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    shadow_color = QColor(color)
    shadow_color.setAlpha(alpha)
    effect.setColor(shadow_color)
    effect.setOffset(0, 4)
    widget.setGraphicsEffect(effect)


def hbox(*widgets: QWidget, spacing: int = 8, stretch_last: bool = False) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch_last:
        layout.addStretch(1)
    return layout


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
