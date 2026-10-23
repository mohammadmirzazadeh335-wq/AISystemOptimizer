"""Global search overlay (Ctrl+Shift+F).

One field, grouped results from every local source, arrows to move and Enter to
open.  The overlay itself never navigates: it hands the chosen
:class:`~myai.services.search.SearchHit` back to the window, which knows where
each source lives.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
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
from ...services.search import MIN_QUERY, SearchHit
from ..theme import runtime
from .dialogs import ModalDialog
from .foundation import Kbd, repolish

SOURCE_ICON = {
    "conversation": "chat",
    "message": "book-open",
    "prompt": "sparkles",
    "memory": "database",
    "output": "file",
    "task": "list-check",
    "file": "code",
}
SOURCE_LABEL = {
    "conversation": "search.source_conversation",
    "message": "search.source_message",
    "prompt": "search.source_prompt",
    "memory": "search.source_memory",
    "output": "search.source_output",
    "task": "search.source_task",
    "file": "search.source_file",
}


class _HitRow(QPushButton):
    def __init__(self, hit: SearchHit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hit = hit
        self.setProperty("paletteRow", "true")
        self.setProperty("selected", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(runtime.px(48))
        self.setAccessibleName(hit.title)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(10), runtime.px(6), runtime.px(12), runtime.px(6))
        layout.setSpacing(runtime.px(9))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px(SOURCE_ICON.get(hit.source, "file"), 15, "muted"))
        icon.setFixedWidth(runtime.px(18))
        layout.addWidget(icon)

        column = QVBoxLayout()
        column.setSpacing(0)
        width = runtime.px(560)
        title = QLabel(QFontMetrics(self.font()).elidedText(hit.title, Qt.TextElideMode.ElideRight, width))
        title.setStyleSheet("background: transparent; font-weight: 600;")
        title.setToolTip(hit.title)
        column.addWidget(title)
        detail = QLabel()
        detail.setProperty("role", "faint")
        detail.setStyleSheet(f"font-size: {runtime.px(10)}px; background: transparent;")
        detail.setText(
            QFontMetrics(detail.font()).elidedText(hit.snippet, Qt.TextElideMode.ElideRight, width)
        )
        detail.setToolTip(hit.snippet)
        column.addWidget(detail)
        layout.addLayout(column, 1)

        badge = QLabel()
        badge.setStyleSheet(
            f"font-size: {runtime.px(9)}px; color: {runtime.theme().color('text_faint')};"
            f" background: {runtime.theme().color('surface_2')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(6)}px; padding: {runtime.px(1)}px {runtime.px(7)}px;"
        )
        line_no = (hit.extra or {}).get("line")
        extra = tr("search.line", number=line_no) if line_no else (hit.subtitle or "")
        badge.setText(QFontMetrics(badge.font()).elidedText(extra, Qt.TextElideMode.ElideRight, runtime.px(90)))
        badge.setVisible(bool(extra))
        layout.addWidget(badge)

        hover = runtime.theme().alpha("accent", 0.12)
        ring = runtime.theme().alpha("accent", 0.4)
        self.setStyleSheet(
            'QPushButton[paletteRow="true"] {'
            " text-align: left; border: 1px solid transparent;"
            f" border-radius: {runtime.px(9)}px; background: transparent; padding: 0; }}"
            'QPushButton[paletteRow="true"]:hover,'
            'QPushButton[paletteRow="true"][selected="true"] {'
            f" background: {hover}; border: 1px solid {ring}; }}"
        )


class GlobalSearchDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget,
        service,  # noqa: ANN001
        on_open: Callable[[SearchHit, str], None],
        *,
        project=None,  # noqa: ANN001
        conversation_id: str | None = None,
    ) -> None:
        super().__init__(parent, tr("search.title"), tr("search.subtitle"), width=720)
        self._service = service
        self._project = project
        self._conversation_id = conversation_id
        self._on_open = on_open
        self._rows: list[_HitRow] = []
        self._index = -1
        self.hits: list[SearchHit] = []

        box = QFrame()
        box.setObjectName("GlobalSearchField")
        box.setStyleSheet(
            f"QFrame#GlobalSearchField {{ background-color: {runtime.theme().color('surface_2')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(10)}px; }}"
        )
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(runtime.px(12), runtime.px(4), runtime.px(12), runtime.px(4))
        box_layout.setSpacing(runtime.px(8))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px("search", 15, "muted"))
        box_layout.addWidget(icon)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search.placeholder"))
        self.search.setAccessibleName(tr("search.placeholder"))
        self.search.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            f" font-size: {runtime.px(14)}px; padding: {runtime.px(6)}px 0; }}"
        )
        self.search.textChanged.connect(self._queue)
        self.search.returnPressed.connect(self._open_current)
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
        self.scroll.setMinimumHeight(runtime.px(320))
        self.scroll.setMaximumHeight(runtime.px(420))
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.host = QWidget()
        self.results = QVBoxLayout(self.host)
        self.results.setContentsMargins(0, 0, runtime.px(4), 0)
        self.results.setSpacing(runtime.px(2))
        self.scroll.setWidget(self.host)
        self.body.addWidget(self.scroll)

        self.state = QLabel(tr("search.hint"))
        self.state.setProperty("role", "faint")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state.setMinimumHeight(runtime.px(120))
        self.state.setWordWrap(True)
        self.body.addWidget(self.state)

        for key, text in (
            ("search.footer_move", "↑ ↓"),
            ("search.footer_open", "Enter"),
            ("search.footer_close", "Esc"),
        ):
            label = QLabel(tr(key))
            label.setProperty("role", "faint")
            self.footer.addWidget(label)
            self.footer.addWidget(Kbd(text))

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(170)
        self._timer.timeout.connect(self._run_search)
        self.search.setFocus()
        self._render()
        self.resize(runtime.px(760), runtime.px(560))

    # --------------------------------------------------------------- searching
    def _queue(self, _text: str) -> None:
        self._timer.start()

    def _run_search(self) -> None:
        query = self.search.text().strip()
        if len(query) < MIN_QUERY:
            self.hits = []
            self._render()
            return
        try:
            self.hits = self._service.search(
                query,
                project=self._project,
                conversation_id=self._conversation_id,
                per_source=5,
            )
        except Exception:  # noqa: BLE001 - the overlay must stay usable
            self.hits = []
        self._render()

    # ------------------------------------------------------------------ render
    def _clear(self) -> None:
        while self.results.count():
            item = self.results.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        self._index = -1

    def _render(self) -> None:
        self._clear()
        query = self.search.text().strip()
        has_query = len(query) >= MIN_QUERY
        self.state.setVisible(not self.hits)
        if not has_query:
            self.state.setText(tr("search.hint"))
            self.count.setText("")
            return
        if not self.hits:
            self.state.setText(tr("search.empty", query=query))
            self.count.setText("")
            return
        self.state.setVisible(False)
        self.count.setText(tr("search.count", count=len(self.hits)))
        grouped: dict[str, list[SearchHit]] = {}
        for hit in self.hits:
            grouped.setdefault(hit.source, []).append(hit)
        first = True
        for source, hits in grouped.items():
            if not first:
                spacer = QWidget()
                spacer.setFixedHeight(runtime.px(4))
                self.results.addWidget(spacer)
            first = False
            header = QWidget()
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(runtime.px(10), runtime.px(4), runtime.px(10), 0)
            header_layout.setSpacing(runtime.px(6))
            icon = QLabel()
            icon.setPixmap(runtime.icons().px(SOURCE_ICON.get(source, "file"), 12, "faint"))
            header_layout.addWidget(icon)
            label = QLabel(tr(SOURCE_LABEL.get(source, "search.source_output")))
            label.setProperty("role", "section")
            header_layout.addWidget(label)
            header_layout.addStretch(1)
            counter = QLabel(str(len(hits)))
            counter.setProperty("role", "faint")
            header_layout.addWidget(counter)
            self.results.addWidget(header)
            for hit in hits:
                row = _HitRow(hit)
                row.clicked.connect(lambda _checked=False, h=hit: self._open(h))
                row.installEventFilter(self)
                self.results.addWidget(row)
                self._rows.append(row)
        self.results.addStretch(1)
        self._select(0)

    # ---------------------------------------------------------------- keyboard
    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._open_current()
                return True
        return super().eventFilter(watched, event)

    def _select(self, index: int) -> None:
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

    def _open_current(self) -> None:
        if 0 <= self._index < len(self._rows):
            self._open(self._rows[self._index].hit)
        elif self._rows:
            self._open(self._rows[0].hit)

    def _open(self, hit: SearchHit) -> None:
        query = self.search.text().strip()
        self.accept()
        self._on_open(hit, query)
