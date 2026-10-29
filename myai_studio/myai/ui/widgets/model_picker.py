"""A compact, searchable model picker.

The old dropdown was a ``QMenu`` with one action per model. OpenRouter alone
publishes 300+ entries, so the menu grew taller than the window, had no search
and no visible scrollbar: opening it covered half the page and the only way to
find a model was to scroll by hand.

This widget replaces that menu with a small popup: a search box that keeps the
keyboard, a virtualised list (one delegate paints every row, no widget per
model), hover/selection feedback and a hard height cap — eight rows, never more
than half the screen. Arrow keys move, Enter picks, Escape closes, and typing
filters on both the display name and the model id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..theme import runtime

#: A tag is (text, tone); the tone names a theme colour.
TAG_FREE = ("free", "success")
TAG_PAID = ("paid", "warning")
TAG_TOOLS = ("tools", "violet")
TAG_VISION = ("vision", "accent")


@dataclass(frozen=True)
class Choice:
    """One selectable row."""

    value: str
    label: str
    detail: str = ""
    tags: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    keywords: str = ""

    def haystack(self) -> str:
        texts = [text for text, _tone in self.tags]
        return " ".join((self.label, self.value, self.detail, self.keywords, *texts)).casefold()

    def matches(self, needle: str) -> bool:
        if not needle:
            return True
        haystack = self.haystack()
        return all(token in haystack for token in needle.split())


class ChoiceListModel(QAbstractListModel):
    """Holds the full list and exposes the filtered view."""

    def __init__(self, choices: list[Choice] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all: list[Choice] = list(choices or [])
        self._visible: list[Choice] = list(self._all)

    # ------------------------------------------------------------- mechanics
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._visible)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201, N802
        if not index.isValid() or index.row() >= len(self._visible):
            return None
        choice = self._visible[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return choice.label
        if role == Qt.ItemDataRole.UserRole:
            return choice.value
        if role == Qt.ItemDataRole.UserRole + 1:
            return choice
        return None

    # ------------------------------------------------------------------ state
    def set_choices(self, choices: list[Choice], *, keep_filter: bool = True) -> None:
        needle = ""
        if keep_filter:
            needle = getattr(self, "_needle", "")
        self._all = list(choices)
        self.filter(needle)

    def filter(self, needle: str) -> None:
        self._needle = (needle or "").strip().casefold()
        self.beginResetModel()
        self._visible = [choice for choice in self._all if choice.matches(self._needle)]
        self.endResetModel()

    def visible_choices(self) -> list[Choice]:
        return list(self._visible)

    def total(self) -> int:
        return len(self._all)

    def choice_at(self, row: int) -> Choice | None:
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def row_of(self, value: str) -> int:
        for row, choice in enumerate(self._visible):
            if choice.value == value:
                return row
        return -1


class ChoiceDelegate(QStyledItemDelegate):
    """Paints one two-line row: name + id, with capability tags on the far side."""

    def __init__(self, parent: QWidget | None = None, *, current: str = "") -> None:
        super().__init__(parent)
        self.current = current

    @staticmethod
    def _color(token: str, alpha: float = 1.0) -> QColor:
        """A QColor from a theme token.

        ``Theme.alpha`` returns a CSS ``rgba(...)`` string for stylesheets; a
        QColor cannot parse that and silently becomes black — which painted the
        selected row solid black in the light theme.
        """
        color = QColor(runtime.theme().color(token))
        if alpha < 1.0:
            color.setAlphaF(max(0.0, min(1.0, alpha)))
        return color

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001, N802
        choice = index.data(Qt.ItemDataRole.UserRole + 1)
        tall = bool(getattr(choice, "detail", ""))
        return QSize(option.rect.width(), runtime.px(48 if tall else 42))

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001, N802
        choice: Choice = index.data(Qt.ItemDataRole.UserRole + 1)
        if choice is None:  # pragma: no cover - defensive
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRect(option.rect).adjusted(runtime.px(6), runtime.px(2), -runtime.px(6), -runtime.px(2))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        radius = runtime.px(9)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color("accent", 0.16 if selected else 0.08))
            painter.drawRoundedRect(rect, radius, radius)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color("accent"))
            bar = QRect(rect.left(), rect.top() + runtime.px(8), runtime.px(3), rect.height() - runtime.px(16))
            painter.drawRoundedRect(bar, runtime.px(2), runtime.px(2))

        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        pad = runtime.px(10)
        has_detail = bool(choice.detail)
        text_left = rect.left() + pad + (runtime.px(4) if selected and not rtl else 0)
        text_right = rect.right() - pad
        # Tag pills get measured first: the text is elided into what is left.
        pills: list[tuple[str, str, QRect]] = []
        if choice.tags:
            pill_font = runtime.ui_font(9, 500)
            pill_metrics = QFontMetrics(pill_font)
            x = text_right
            for text, tone in reversed(choice.tags[:3]):
                width = pill_metrics.horizontalAdvance(text) + runtime.px(14)
                height = runtime.px(18)
                top = rect.center().y() - height // 2
                pills.append((text, tone, QRect(x - width, top, width, height)))
                x -= width + runtime.px(5)
            text_right = x - runtime.px(8)
        painter.setFont(runtime.ui_font(12, 600))
        metrics = QFontMetrics(painter.font())
        name_rect = QRect(
            text_left,
            rect.top() + runtime.px(6 if has_detail else 0),
            max(10, text_right - text_left),
            runtime.px(18 if has_detail else rect.height()),
        )
        painter.setPen(self._color("text"))
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        painter.drawText(
            name_rect,
            align | (Qt.AlignmentFlag.AlignTop if has_detail else Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(choice.label, Qt.TextElideMode.ElideRight, name_rect.width()),
        )
        if has_detail:
            painter.setFont(runtime.mono_font(9))
            detail_metrics = QFontMetrics(painter.font())
            detail_rect = QRect(text_left, name_rect.bottom() + runtime.px(1), max(10, text_right - text_left), runtime.px(15))
            painter.setPen(self._color("text_faint"))
            painter.drawText(
                detail_rect,
                align | Qt.AlignmentFlag.AlignTop,
                detail_metrics.elidedText(choice.detail, Qt.TextElideMode.ElideRight, detail_rect.width()),
            )
        for text, tone, pill_rect in pills:
            painter.setPen(QPen(self._color(tone, 0.5), 1))
            painter.setBrush(self._color(tone, 0.15))
            painter.drawRoundedRect(pill_rect, runtime.px(8), runtime.px(8))
            painter.setFont(runtime.ui_font(9, 500))
            painter.setPen(self._color(tone))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
        if choice.value == self.current:
            check_rect = QRect(
                rect.right() - runtime.px(14) if not rtl else rect.left() + runtime.px(2),
                rect.top() + runtime.px(3),
                runtime.px(12),
                runtime.px(12),
            )
            painter.setPen(QPen(self._color("accent"), runtime.px(2)))
            painter.drawLine(check_rect.left() + 1, check_rect.center().y(), check_rect.center().x() - 1, check_rect.bottom() - 2)
            painter.drawLine(check_rect.center().x() - 1, check_rect.bottom() - 2, check_rect.right(), check_rect.top() + 3)
        painter.restore()


class ChoicePopup(QFrame):
    """A popup list with a search field; sized to stay out of the way."""

    chosen = Signal(str)
    dismissed = Signal()

    #: Rows shown before the list starts scrolling. Eight fits a laptop screen
    #: without covering the conversation around it.
    MAX_ROWS = 8

    def __init__(
        self,
        choices: list[Choice] | None = None,
        *,
        current: str = "",
        title: str = "",
        placeholder: str = "",
        empty_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("ChoicePopup")
        self._title = title
        self._chrome: int | None = None
        self._placeholder = placeholder or tr("picker.search")
        self._empty_text = empty_text or tr("picker.empty")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(runtime.px(10), runtime.px(8), runtime.px(10), runtime.px(12))
        outer.setSpacing(0)
        self.panel = QFrame()
        self.panel.setObjectName("ChoicePanel")
        outer.addWidget(self.panel)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(runtime.px(28))
        shadow.setOffset(0, runtime.px(8))
        shadow.setColor(QColor(0, 0, 0, 150))
        self.panel.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(runtime.px(8), runtime.px(8), runtime.px(8), runtime.px(6))
        layout.setSpacing(runtime.px(4))

        if title:
            head = QLabel(title)
            head.setProperty("role", "faint")
            head.setStyleSheet(f"font-size: {runtime.px(9)}px; padding: 0 {runtime.px(6)}px;")
            layout.addWidget(head)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(runtime.px(4), 0, runtime.px(4), 0)
        search_row.setSpacing(runtime.px(6))
        glyph = QLabel()
        glyph.setPixmap(runtime.icons().px("search", 14, "muted"))
        search_row.addWidget(glyph)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self._placeholder)
        self.search.setAccessibleName(self._placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet("QLineEdit { background: transparent; border: none; }")
        self.search.textChanged.connect(self._on_search)
        self.search.installEventFilter(self)
        search_row.addWidget(self.search, 1)
        self.count = QLabel("")
        self.count.setProperty("role", "faint")
        self.count.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        search_row.addWidget(self.count)
        search_box = QFrame()
        search_box.setObjectName("ChoiceSearch")
        search_box.setLayout(search_row)
        layout.addWidget(search_box)

        self.model = ChoiceListModel(choices or [], self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.delegate = ChoiceDelegate(self.view, current=current)
        self.view.setItemDelegate(self.delegate)
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setStyleSheet("QListView { background: transparent; border: none; outline: none; }")
        self.view.clicked.connect(self._on_clicked)
        self.view.installEventFilter(self)
        layout.addWidget(self.view, 1)

        self.empty = QLabel(self._empty_text)
        self.empty.setProperty("role", "faint")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(runtime.px(64))
        layout.addWidget(self.empty)

        self.footer = QLabel(tr("picker.footer"))
        self.footer.setProperty("role", "faint")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.footer.setStyleSheet(f"font-size: {runtime.px(9)}px; padding: 0 {runtime.px(6)}px;")
        layout.addWidget(self.footer)

        self._style()
        runtime.signals.changed.connect(self._style)
        self._refresh()
        self._select_initial()

    # ------------------------------------------------------------------ style
    def _style(self, *_args) -> None:
        theme = runtime.theme()
        self.panel.setStyleSheet(
            "QFrame#ChoicePanel {"
            f" background-color: {theme.color('surface')};"
            f" border: 1px solid {theme.color('border_strong')};"
            f" border-radius: {runtime.px(14)}px; }}"
            "QFrame#ChoiceSearch {"
            f" background-color: {theme.color('surface_2')};"
            f" border: 1px solid {theme.color('border')};"
            f" border-radius: {runtime.px(10)}px; }}"
        )

    # ------------------------------------------------------------------- data
    def set_choices(self, choices: list[Choice], *, current: str = "") -> None:
        self.model.set_choices(choices)
        if current:
            self.delegate.current = current
            self.model.filter(self.search.text())
        self._refresh()

    def show_for(self, anchor: QWidget, *, width: int | None = None) -> None:
        """Place under the anchor, or above it when there is no room below."""
        self._fit(len(self.model.visible_choices()))
        screen = anchor.screen() or QApplication.primaryScreen()
        window = anchor.window()
        desired = width or max(anchor.width(), runtime.px(300))
        if window is not None:
            desired = min(desired, max(runtime.px(260), window.width() - runtime.px(32)))
        desired = max(runtime.px(280), min(desired, runtime.px(460)))
        self.resize(desired, self.height())
        origin = anchor.mapToGlobal(anchor.rect().bottomLeft())
        geometry = screen.availableGeometry() if screen is not None else None
        if geometry is not None and origin.y() + self.height() > geometry.bottom():
            above = anchor.mapToGlobal(anchor.rect().topLeft()).y() - self.height()
            origin.setY(max(geometry.top(), above))
        self.move(origin)
        self.show()
        self.raise_()
        self.search.setFocus()
        self.search.selectAll()
        self._select_initial()

    # ----------------------------------------------------------------- layout
    def _chrome_height(self) -> int:
        """Everything in the popup that is not the list itself.

        Measured once from the real widgets. Reading ``sizeHint`` back after the
        frame has been constrained returns the *squeezed* height, which is how
        the last row ended up painted over the footer.
        """
        if self._chrome is None:
            layout = self.panel.layout()
            parts = [layout.contentsMargins().top() + layout.contentsMargins().bottom()]
            visible = 0
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                if widget is None or widget is self.view or widget is self.empty:
                    continue
                parts.append(widget.sizeHint().height())
                visible += 1
            outer = self.layout().contentsMargins()
            parts.append(outer.top() + outer.bottom())
            parts.append(layout.spacing() * visible)
            self._chrome = sum(parts) + runtime.px(6)
        return self._chrome

    def _fit(self, rows: int) -> None:
        """Size the popup to whole rows, never taller than half the screen."""
        row_height = runtime.px(48)
        screen = QApplication.primaryScreen()
        cap = int(screen.availableGeometry().height() * 0.5) if screen is not None else 10_000
        chrome = self._chrome_height()
        room = max(1, (cap - chrome) // row_height)
        rows = max(1, min(rows, self.MAX_ROWS, room))
        self.view.setFixedHeight(rows * row_height + runtime.px(4))
        self.view.setVisible(True)
        self.setFixedHeight(max(runtime.px(170), min(chrome + self.view.height(), cap)))

    # ----------------------------------------------------------------- events
    def _refresh(self) -> None:
        visible = self.model.visible_choices()
        has_rows = bool(visible)
        self.view.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        total = self.model.total()
        if total:
            self.count.setText(tr("picker.count", shown=len(visible), total=total))
        else:
            self.count.setText("")
        self._fit(len(visible))

    def _on_search(self, text: str) -> None:
        self.model.filter(text)
        self._refresh()
        self._select_initial()

    def _select_initial(self) -> None:
        index = self.model.row_of(self.delegate.current)
        if index < 0 and self.model.rowCount():
            index = 0
        if index >= 0:
            self.view.setCurrentIndex(self.model.index(index, 0))
            self.view.scrollTo(self.model.index(index, 0), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_clicked(self, index: QModelIndex) -> None:
        choice = self.model.choice_at(index.row())
        if choice is not None:
            self._accept(choice)

    def _accept(self, choice: Choice) -> None:
        self.delegate.current = choice.value
        self.chosen.emit(choice.value)
        self.close()

    def choose_current(self) -> None:
        """Accept the highlighted row (Enter, or a test)."""
        index = self.view.currentIndex()
        choice = self.model.choice_at(index.row()) if index.isValid() else None
        if choice is None:
            visible = self.model.visible_choices()
            choice = visible[0] if visible else None
        if choice is not None:
            self._accept(choice)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self.dismissed.emit()
        super().closeEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001, N802
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.choose_current()
                return True
            if key == Qt.Key.Key_PageDown:
                self._move(self.MAX_ROWS - 1)
                return True
            if key == Qt.Key.Key_PageUp:
                self._move(-(self.MAX_ROWS - 1))
                return True
        return super().eventFilter(watched, event)

    def _move(self, step: int) -> None:
        count = self.model.rowCount()
        if not count:
            return
        row = self.view.currentIndex().row()
        if row < 0:
            row = 0
        row = max(0, min(count - 1, row + step))
        self.view.setCurrentIndex(self.model.index(row, 0))
        self.view.scrollTo(self.model.index(row, 0))


def model_tags(
    context_length: int, *, free: bool, tools: bool, vision: bool, paid: bool = False
) -> tuple[tuple[str, str], ...]:
    """The badges a catalogue row shows, in display order.

    ``paid`` is passed only when the catalogue stated a non-zero price. A model
    whose price nobody published gets neither badge: guessing "free" would be a
    lie and guessing "paid" would be a guess.
    """
    tags: list[tuple[str, str]] = []
    if context_length:
        text = f"{context_length // 1000}k" if context_length >= 1000 else str(context_length)
        tags.append((text, "info"))
    if free:
        tags.append((tr("api.free"), TAG_FREE[1]))
    elif paid:
        tags.append((tr("api.paid"), TAG_PAID[1]))
    if tools:
        tags.append((tr("api.tools"), TAG_TOOLS[1]))
    if vision:
        tags.append((tr("api.vision"), TAG_VISION[1]))
    return tuple(tags)


__all__ = ["Choice", "ChoiceDelegate", "ChoiceListModel", "ChoicePopup", "model_tags"]
