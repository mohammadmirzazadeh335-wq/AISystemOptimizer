"""Inputs and settings rows."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..theme import runtime
from ..theme.icons import draw as draw_icon
from .buttons import IconButton, ToggleSwitch
from .foundation import Badge, repolish
from .painting import paint_event


class SearchField(QFrame):
    text_changed = Signal(str)

    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SearchBox")
        self.setFixedHeight(runtime.px(36))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(10), 0, runtime.px(4), 0)
        layout.setSpacing(runtime.px(6))
        self._icon = QLabel()
        self._icon.setPixmap(runtime.icons().px("search", 15, "muted"))
        layout.addWidget(self._icon)
        self._edit = QLineEdit()
        self._edit.setObjectName("SearchInput")
        self._edit.setLayoutDirection(self.layoutDirection())
        self._edit.setPlaceholderText(placeholder)
        self._edit.setClearButtonEnabled(False)
        layout.addWidget(self._edit, 1)
        self._kbd = QLabel("Ctrl K")
        self._kbd.setProperty("role", "mono")
        layout.addWidget(self._kbd, 0, Qt.AlignmentFlag.AlignVCenter)
        self._clear = IconButton("close", "Clear", 24, icon_size=13)
        self._clear.hide()
        layout.addWidget(self._clear)
        self._edit.textChanged.connect(self._on_text)
        self._edit.installEventFilter(self)
        self._clear.clicked.connect(self.clear)
        self._kbd.setContentsMargins(0, 0, runtime.px(4), 0)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if watched is self._edit:
            if event.type() == event.Type.FocusIn:
                self.setProperty("focused", "true")
                repolish(self)
                self._kbd.hide()
            elif event.type() == event.Type.FocusOut:
                self.setProperty("focused", "false")
                repolish(self)
                if not self._edit.text():
                    self._kbd.show()
        return super().eventFilter(watched, event)

    def _on_text(self, text: str) -> None:
        self._clear.setVisible(bool(text))
        self.text_changed.emit(text)

    def clear(self) -> None:
        self._edit.clear()
        self.text_changed.emit("")

    def text(self) -> str:
        return self._edit.text()

    def set_kbd_hint(self, text: str) -> None:
        self._kbd.setText(text)

    def set_placeholder(self, text: str) -> None:
        self._edit.setPlaceholderText(text)

    def focus(self) -> None:
        self._edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._edit.selectAll()


class AttachmentChip(QFrame):
    removed = Signal(str)

    def __init__(self, name: str, subtitle: str, icon_name: str = "file", parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("AttachmentChip")
        self.attachment_name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(8), runtime.px(4), runtime.px(4), runtime.px(4))
        layout.setSpacing(runtime.px(6))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px(icon_name, 14, "muted"))
        layout.addWidget(icon)
        text_wrap = QWidget()
        text_layout = QVBoxLayout(text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        title = QLabel(name)
        title.setProperty("role", "mono")
        title.setStyleSheet("color: inherit;")
        metrics = QFontMetrics(title.font())
        title.setText(metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, runtime.px(150)))
        title.setToolTip(name)
        text_layout.addWidget(title)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setProperty("role", "faint")
            sub.setStyleSheet(f"font-size: {runtime.px(9)}px;")
            text_layout.addWidget(sub)
        layout.addWidget(text_wrap)
        remove = IconButton("close", "Remove", 20, icon_size=11)
        remove.clicked.connect(lambda: self.removed.emit(name))
        layout.addWidget(remove)


class SelectField(QAbstractButton):
    """A quiet dropdown that matches the rest of the design language."""

    value_changed = Signal(str)

    def __init__(
        self,
        items: Iterable[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
        *,
        placeholder: str = "Select",
        icon_name: str = "",
        compact: bool = False,
        empty_action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = list(items or [])
        self._empty_action = empty_action
        self._value = ""
        self._placeholder = placeholder
        self._icon_name = icon_name
        self._compact = compact
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(runtime.px(30 if compact else 34))
        self._recalc()

    def _recalc(self) -> None:
        font = runtime.ui_font(12, 500)
        metrics = QFontMetrics(font)
        label = self._current_label() or self._placeholder
        # Glyph space: icon when present + chevron + both paddings + gap
        glyphs = (runtime.px(14) * (2 if self._icon_name else 1)) + runtime.px(14)
        width = metrics.horizontalAdvance(label) + glyphs
        # Compact chips size to their label; wide fields get room for real model
        # names without eliding them to a single letter.
        floor = runtime.px(92 if self._compact else 168)
        self.setFixedWidth(max(floor, min(width, runtime.px(320))))
        self.updateGeometry()

    def refresh_metrics(self) -> None:
        """Adopt the current font scale (width and height are computed once)."""
        self.setFixedHeight(runtime.px(30 if self._compact else 34))
        self._recalc()

    def _current_label(self) -> str:
        for value, label in self._items:
            if value == self._value:
                return label
        return ""

    def set_items(self, items: Iterable[tuple[str, str]]) -> None:
        self._items = list(items)
        if self._value and self._value not in {v for v, _ in self._items}:
            self._value = ""
        self._recalc()
        self.update()

    def set_value(self, value: str) -> None:
        self._value = value
        self._recalc()
        self.update()

    @property
    def value(self) -> str:
        return self._value

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self._recalc()
        self.update()

    def _show_menu(self) -> None:
        menu = QMenu(self)
        menu.setLayoutDirection(self.layoutDirection())
        if not self._items:
            empty = menu.addAction(self._placeholder)
            empty.setEnabled(False)
            if self._empty_action is not None:
                label, callback = self._empty_action
                menu.addSeparator()
                action = menu.addAction(label)
                action.triggered.connect(callback)
        for value, label in self._items:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == self._value)
            action.triggered.connect(lambda _=False, v=value: self._select(v))
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def _select(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self._recalc()
            self.update()
            self.value_changed.emit(value)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._show_menu()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self._show_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRect(self.rect()).adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(rect, runtime.px(9), runtime.px(9))
        if self.underMouse():
            painter.setPen(QPen(QColor(c("border_strong")), 1))
            painter.drawRoundedRect(rect, runtime.px(9), runtime.px(9))
        if self.hasFocus():
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect, runtime.px(9), runtime.px(9))

        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        pad = runtime.px(10)
        gap = runtime.px(6)
        glyph = runtime.px(14)
        icon_rect = QRect(0, 0, 0, 0)
        chevron_rect = QRect(0, 0, 0, 0)
        if rtl:
            icon_rect = QRect(self.width() - pad - glyph, (self.height() - glyph) // 2, glyph, glyph)
            chevron_rect = QRect(pad, (self.height() - glyph) // 2, glyph, glyph)
        else:
            icon_rect = QRect(pad, (self.height() - glyph) // 2, glyph, glyph)
            chevron_rect = QRect(self.width() - pad - glyph, (self.height() - glyph) // 2, glyph, glyph)
        if self._icon_name:
            draw_icon(painter, self._icon_name, icon_rect, c("text_muted"), 1.8)
        draw_icon(painter, "chevron-down", chevron_rect, c("text_muted"), 1.8)

        # Text occupies the space between the two glyphs, never underneath them.
        if rtl:
            text_left = chevron_rect.right() + gap
            text_right = (icon_rect.left() - gap) if self._icon_name else (self.width() - pad)
        else:
            text_left = (icon_rect.right() + gap) if self._icon_name else pad
            text_right = chevron_rect.left() - gap
        text_rect = QRect(text_left, 0, max(10, text_right - text_left), self.height())
        label = self._current_label()
        painter.setFont(runtime.ui_font(12, 500))
        painter.setPen(QColor(c("text") if label else c("text_faint")))
        metrics = QFontMetrics(painter.font())
        elided = metrics.elidedText(label or self._placeholder, Qt.TextElideMode.ElideRight, text_rect.width())
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        painter.drawText(text_rect, align | Qt.AlignmentFlag.AlignVCenter, elided)


class SliderRow(QWidget):
    value_changed = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float, step: float = 0.05, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._scale = 100
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(10))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(minimum * self._scale), int(maximum * self._scale))
        self.slider.setSingleStep(int(step * self._scale))
        self.slider.setPageStep(int(step * self._scale) * 2)
        self.slider.setValue(int(value * self._scale))
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.slider, 1)
        self._label = QLabel(f"{value:.2f}×")
        self._label.setProperty("role", "mono")
        self._label.setFixedWidth(runtime.px(46))
        self._label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, raw: int) -> None:
        value = raw / self._scale
        self._label.setText(f"{value:.2f}×")
        self.value_changed.emit(value)

    def value(self) -> float:
        return self.slider.value() / self._scale


class SettingRow(QFrame):
    def __init__(
        self,
        title: str,
        description: str = "",
        control: QWidget | None = None,
        *,
        badge_text: str = "",
        badge_tone: str = "muted",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(14), runtime.px(11), runtime.px(12), runtime.px(11))
        layout.setSpacing(runtime.px(14))
        text_wrap = QWidget()
        text_layout = QVBoxLayout(text_wrap)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(runtime.px(2))
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(runtime.px(8))
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "h3")
        title_row.addWidget(self.title_label)
        if badge_text:
            title_row.addWidget(Badge(badge_text, badge_tone))
        title_row.addStretch(1)
        text_layout.addLayout(title_row)
        if description:
            desc = QLabel(description)
            desc.setProperty("role", "muted")
            desc.setWordWrap(True)
            text_layout.addWidget(desc)
        layout.addWidget(text_wrap, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


def toggle_row(
    title: str,
    description: str,
    value: bool,
    on_change: Callable[[bool], None],
    *,
    badge_text: str = "",
    badge_tone: str = "muted",
    enabled: bool = True,
) -> SettingRow:
    toggle = ToggleSwitch(on=value)
    toggle.toggled.connect(on_change)
    toggle.setEnabled(enabled)
    return SettingRow(title, description, toggle, badge_text=badge_text, badge_tone=badge_tone)


class LanguageCard(QAbstractButton):
    def __init__(self, code: str, title: str, native: str, sample: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.code = code
        self._title = title
        self._native = native
        self._sample = sample
        self._rtl = code in {"fa", "ar"}
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(runtime.px(96))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor(c("accent")), 2) if self.isChecked() else QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(rect, runtime.px(12), runtime.px(12))
        pad = runtime.px(14)
        painter.setFont(runtime.ui_font(13, 600))
        painter.setPen(QColor(c("text")))
        painter.drawText(
            QRect(pad, pad, rect.width() - pad * 2, runtime.px(20)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title,
        )
        painter.setFont(runtime.ui_font(11))
        painter.setPen(QColor(c("text_muted")))
        painter.drawText(
            QRect(pad, pad + runtime.px(22), rect.width() - pad * 2, runtime.px(18)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._native,
        )
        painter.setFont(runtime.ui_font(12))
        painter.setPen(QColor(c("text_faint")))
        sample_rect = QRect(pad, pad + runtime.px(44), rect.width() - pad * 2, runtime.px(28))
        painter.drawText(
            sample_rect,
            (Qt.AlignmentFlag.AlignRight if self._rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter,
            self._sample,
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), runtime.px(10), runtime.px(10))
class FlowLayout(QLayout):
    """Wrapping layout for attachment chips (adapted from the Qt example)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: ANN001
        self._items.append(item)

    def count(self) -> int:
        return len(self._prune_dead())

    def itemAt(self, index: int):  # noqa: ANN201
        items = self._prune_dead()
        return items[index] if 0 <= index < len(items) else None

    def takeAt(self, index: int):  # noqa: ANN201
        items = self._prune_dead()
        return items.pop(index) if 0 <= index < len(items) else None

    def expandingDirections(self):  # noqa: ANN201
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:  # noqa: ANN001
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._prune_dead():
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _prune_dead(self) -> list:
        """Drop items whose widget is already gone.

        A page rebuild reparents and deletes its action row; the layout object can
        still be asked for its minimum size while the deletion is queued, and
        touching a dead QWidgetItem there crashed the process.
        """
        if not self._items:
            return []
        try:
            import shiboken6
        except ImportError:  # pragma: no cover - PySide6 always ships it
            return list(self._items)
        alive = []
        for item in self._items:
            # Qt deletes the QWidgetItem when its widget dies, so the Python
            # wrapper itself can already be dangling; check it before use.
            if not shiboken6.isValid(item):
                continue
            widget = item.widget()
            if widget is None or shiboken6.isValid(widget):
                alive.append(item)
        if len(alive) != len(self._items):
            self._items = alive
        return alive

    def _do_layout(self, rect, test_only: bool) -> int:  # noqa: ANN001
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        rtl = self.parentWidget() is not None and (
            self.parentWidget().layoutDirection() == Qt.LayoutDirection.RightToLeft
        )
        # In RTL the row fills from the right edge, so the first widget keeps
        # the primary position instead of jumping to the far left.
        cursor = effective.right() if rtl else effective.x()
        y = effective.y()
        line_height = 0
        for item in self._prune_dead():
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            if rtl:
                next_cursor = cursor - hint.width()
                overflow = next_cursor < effective.x()
                if overflow and line_height > 0:
                    cursor = effective.right()
                    y = y + line_height + self._spacing
                    next_cursor = cursor - hint.width()
                    line_height = 0
                if not test_only:
                    item.setGeometry(QRect(QPoint(next_cursor, y), hint))
                cursor = next_cursor - self._spacing
            else:
                next_cursor = cursor + hint.width()
                overflow = next_cursor > effective.right()
                if overflow and line_height > 0:
                    cursor = effective.x()
                    y = y + line_height + self._spacing
                    next_cursor = cursor + hint.width()
                    line_height = 0
                if not test_only:
                    item.setGeometry(QRect(QPoint(cursor, y), hint))
                cursor = next_cursor + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()

    def addWidget(self, widget) -> None:  # noqa: ANN001, N802 - Qt API name
        # QLayout::addWidget reparents the child and then calls our addItem.
        # Building the QWidgetItem by hand left the button without a parent, so
        # it never appeared on screen.
        super().addWidget(widget)
        self.invalidate()

    def detach_items(self) -> None:
        """Forget the items before their widgets are deleted.

        Python owns these QWidgetItems, so Qt cannot remove them when a child
        dies; holding them past that point leaves dangling pointers that crash
        the next layout pass.
        """
        self._items = []


class PillToggle(QAbstractButton):
    """Compact toolbar toggle with icon and label (e.g. Web, Agent)."""

    def __init__(
        self,
        icon_name: str,
        text: str,
        parent: QWidget | None = None,
        *,
        checkable: bool = True,
        tooltip: str = "",
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._text = text
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        font = QFontMetrics(runtime.ui_font(11, 500))
        self.setFixedHeight(runtime.px(28))
        self.setMinimumWidth(font.horizontalAdvance(text) + runtime.px(38))
        if tooltip:
            self.setToolTip(tooltip)

    def set_text(self, text: str) -> None:
        self._text = text
        font = QFontMetrics(runtime.ui_font(11, 500))
        self.setMinimumWidth(font.horizontalAdvance(text) + runtime.px(38))
        self.update()

    def _icon_rect(self) -> QRect:
        icon_size = runtime.px(13)
        pad = runtime.px(9)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        ix = self.width() - pad - icon_size if rtl else pad
        return QRect(ix, (self.height() - icon_size) // 2, icon_size, icon_size)

    def _text_rect(self) -> QRect:
        """Label area next to the icon, never underneath it.

        A rect starting at the horizontal padding painted the first letter over
        the glyph (caught in the persona screenshot review).
        """
        icon_size = runtime.px(13)
        pad = runtime.px(9)
        gap = runtime.px(5)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = pad if rtl else pad + icon_size + gap
        return QRect(x, 0, self.width() - pad * 2 - icon_size - gap, self.height())

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = self.rect().adjusted(0, 0, -1, -1)
        active = self.isChecked()
        painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.5)) if active else QColor(c("border")), 1))
        painter.setBrush(QColor(c("accent_soft")) if active else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, runtime.px(8), runtime.px(8))
        if self.underMouse() and not active:
            painter.setBrush(QColor(c("surface_2")))
            painter.drawRoundedRect(rect, runtime.px(8), runtime.px(8))
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        draw_icon(
            painter,
            self._icon_name,
            self._icon_rect(),
            c("accent") if active else c("text_muted"),
            1.8,
        )
        painter.setFont(runtime.ui_font(11, 500))
        painter.setPen(QColor(c("accent") if active else c("text_muted")))
        text_rect = self._text_rect()
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        painter.drawText(text_rect, align | Qt.AlignmentFlag.AlignVCenter, self._text)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), runtime.px(7), runtime.px(7))
class FieldRow(QWidget):
    """Label + arbitrary editor used inside settings pages."""

    def __init__(self, label_text: str, editor: QWidget, hint: str = "", parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(6))
        title = QLabel(label_text)
        title.setProperty("role", "h3")
        layout.addWidget(title)
        layout.addWidget(editor)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "faint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)


class InlineError(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "danger")
        self.setWordWrap(True)
        self.hide()

    def show_error(self, text: str) -> None:
        self.setText(text)
        self.show()

    def clear_error(self) -> None:
        self.clear()
        self.hide()
