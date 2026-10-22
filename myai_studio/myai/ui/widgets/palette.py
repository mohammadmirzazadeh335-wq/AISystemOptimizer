"""A keyboard-first command palette (Ctrl+Shift+P).

Every entry runs a real method of the window; there are no decorative rows.
The list is filtered by a case-insensitive substring match on the title and on
the optional keywords (so "settings" finds the theme switch too).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..theme import runtime
from .dialogs import ModalDialog
from .foundation import repolish


@dataclass(frozen=True)
class PaletteAction:
    id: str
    title: str
    hint: str = ""
    icon: str = "arrow-right"
    keywords: tuple[str, ...] = ()
    run: Callable[[], None] = field(default=lambda: None)

    def matches(self, needle: str) -> bool:
        if not needle:
            return True
        haystack = " ".join((self.title, self.hint, *self.keywords)).lower()
        return all(word in haystack for word in needle.lower().split())


class _Row(QPushButton):
    def __init__(self, action: PaletteAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action = action
        self.setProperty("paletteRow", "true")
        self.setProperty("selected", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(action.title)
        self.setToolTip(action.hint)
        # A QPushButton with a child layout has no text of its own, so its
        # size hint collapses to nothing without this.
        self.setMinimumHeight(runtime.px(42))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(runtime.px(42))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(10), runtime.px(7), runtime.px(10), runtime.px(7))
        layout.setSpacing(runtime.px(9))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px(action.icon, 15, "muted"))
        icon.setFixedWidth(runtime.px(18))
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        # Elide instead of clipping: a long hint used to end mid-word at the
        # card edge ("… Every model bel").
        width = runtime.px(420)
        title = QLabel()
        title.setStyleSheet("background: transparent;")
        title.setText(QFontMetrics(title.font()).elidedText(action.title, Qt.TextElideMode.ElideRight, width))
        title.setToolTip(action.title)
        text.addWidget(title)
        if action.hint:
            hint = QLabel()
            hint.setProperty("role", "faint")
            hint.setStyleSheet(f"font-size: {runtime.px(9)}px; background: transparent;")
            hint.setText(
                QFontMetrics(hint.font()).elidedText(action.hint, Qt.TextElideMode.ElideRight, width)
            )
            hint.setToolTip(action.hint)
            text.addWidget(hint)
        layout.addLayout(text, 1)
        radius = runtime.px(9)
        hover = runtime.theme().alpha("accent", 0.14)
        ring = runtime.theme().alpha("accent", 0.4)
        self.setStyleSheet(
            "QPushButton[paletteRow=\"true\"] {"
            f" text-align: left; border: 1px solid transparent; border-radius: {radius}px;"
            " background: transparent; padding: 0; }"
            "QPushButton[paletteRow=\"true\"]:hover,"
            "QPushButton[paletteRow=\"true\"][selected=\"true\"] {"
            f" background: {hover}; border: 1px solid {ring}; }}"
        )


class CommandPalette(ModalDialog):
    """Modal palette: type to filter, arrows to move, Enter to run."""

    def __init__(self, parent: QWidget, actions: list[PaletteAction]) -> None:
        super().__init__(parent, tr("palette.title"), tr("palette.subtitle"), width=640)
        self._actions = list(actions)
        self._rows: list[_Row] = []
        self._index = -1
        self.result: str = ""

        box = QFrame()
        box.setObjectName("PaletteSearch")
        box.setStyleSheet(
            f"QFrame#PaletteSearch {{ background-color: {runtime.theme().color('surface_2')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(10)}px; }}"
        )
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(runtime.px(12), runtime.px(4), runtime.px(12), runtime.px(4))
        box_layout.setSpacing(runtime.px(8))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px("command", 15, "muted"))
        box_layout.addWidget(icon)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("palette.placeholder"))
        self.search.setAccessibleName(tr("palette.placeholder"))
        self.search.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            f" font-size: {runtime.px(14)}px; padding: {runtime.px(6)}px 0; }}"
        )
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.search.installEventFilter(self)
        box_layout.addWidget(self.search, 1)
        self.count = QLabel("")
        self.count.setProperty("role", "faint")
        box_layout.addWidget(self.count)
        self.body.addWidget(box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(runtime.px(300))
        self.scroll.setMaximumHeight(runtime.px(380))
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.host = QWidget()
        self.rows_layout = QVBoxLayout(self.host)
        self.rows_layout.setContentsMargins(0, 0, runtime.px(4), 0)
        self.rows_layout.setSpacing(runtime.px(2))
        self.empty_label = QLabel(tr("palette.empty"))
        self.empty_label.setProperty("role", "faint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(runtime.px(80))
        self.scroll.setWidget(self.host)
        self.body.addWidget(self.scroll)

        self._rebuild()
        self.search.setFocus()

    # --------------------------------------------------------------- filtering
    def _rebuild(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        needle = self.search.text().strip()
        matches = [action for action in self._actions if action.matches(needle)]
        for action in matches:
            row = _Row(action)
            row.clicked.connect(lambda _checked=False, a=action: self._run(a))
            row.installEventFilter(self)
            self.rows_layout.addWidget(row)
            self._rows.append(row)
        if not matches:
            self.rows_layout.addWidget(self.empty_label)
            self.empty_label.show()
        self.rows_layout.addStretch(1)
        self.count.setText(tr("palette.count", count=len(matches)) if matches else "")
        self._select(0 if self._rows else -1)

    def _filter(self, _text: str) -> None:
        self._rebuild()

    # ---------------------------------------------------------------- keyboard
    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_current()
                return True
        return super().eventFilter(watched, event)

    def _select(self, index: int) -> None:
        """Highlight one row; the search box keeps the keyboard focus."""
        self._index = index
        for position, row in enumerate(self._rows):
            wanted = "true" if position == index else "false"
            if row.property("selected") != wanted:
                row.setProperty("selected", wanted)
                repolish(row)
        if 0 <= index < len(self._rows):
            self.scroll.ensureWidgetVisible(self._rows[index])

    def _move(self, step: int) -> None:
        if not self._rows:
            return
        self._select(max(0, min(len(self._rows) - 1, self._index + step)))

    def _run_current(self) -> None:
        if 0 <= self._index < len(self._rows):
            self._run(self._rows[self._index].action)
        elif self._rows:
            self._run(self._rows[0].action)

    def _run(self, action: PaletteAction) -> None:
        self.result = action.id
        self.accept()
        action.run()
