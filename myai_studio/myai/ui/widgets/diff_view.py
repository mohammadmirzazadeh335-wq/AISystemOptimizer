"""Two-column diff renderer used by the Review page.

Every row is a real line from the two files; changed lines carry character
ranges computed by :mod:`myai.services.review`, so the eye lands on the word
that moved instead of the whole line. The widget is height-for-content inside a
scroll area, never a scroll area itself, which keeps wheel handling and
keyboard focus in the page.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...services.review import DiffResult, DiffRow
from ..theme import runtime
from .painting import paint_event

KIND_TONE = {
    "equal": None,
    "add": "success",
    "remove": "danger",
    "change": "warning",
}
def _tint(theme, token: str, alpha: float) -> QColor:  # noqa: ANN001
    """Theme colour at an alpha.

    ``Theme.alpha`` returns a CSS ``rgba(r, g, b, 0.24)`` string, which QColor
    parses as an invalid colour — painted black. Building the QColor from the
    hex token and setting the alpha keeps light themes honest.
    """
    colour = QColor(theme.color(token))
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


KIND_SOFT = {
    "add": "success_soft",
    "remove": "danger_soft",
    "change": "warning_soft",
}


class DiffView(QWidget):
    """Paints a :class:`DiffResult`; call :meth:`set_diff` when data changes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diff: DiffResult | None = None
        self._old_name = "old"
        self._new_name = "new"
        self._font: QFont = runtime.mono_font(12)
        self._row_height = 20
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        # Expanding: when the diff is shorter than its viewport the extra
        # strip must still be painted in code_bg, not left as card white.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setMinimumWidth(runtime.px(420))

    # ------------------------------------------------------------------- data
    def set_diff(self, diff: DiffResult | None, *, old_name: str = "old", new_name: str = "new") -> None:
        self._diff = diff
        self._old_name = old_name
        self._new_name = new_name
        self._font = runtime.mono_font(12)
        self._row_height = QFontMetrics(self._font).height() + runtime.px(7)
        rows = len(diff.rows) if diff else 0
        height = self._header_height() + rows * self._row_height + runtime.px(12)
        self.setFixedHeight(max(runtime.px(120), height))
        self.update()
        self.updateGeometry()

    def diff(self) -> DiffResult | None:
        return self._diff

    def row_count(self) -> int:
        return len(self._diff.rows) if self._diff else 0

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(runtime.px(760), self.height())

    def _header_height(self) -> int:
        return runtime.px(28)

    # ----------------------------------------------------------------- drawing
    def _columns(self) -> tuple[float, float, float]:
        """Return (divider x, separator gap, number width)."""
        width = self.width()
        gap = runtime.px(18)
        divider = width / 2
        digits = 3
        if self._diff:
            numbers = [row.old_no or 0 for row in self._diff.rows] + [row.new_no or 0 for row in self._diff.rows]
            digits = max(2, len(str(max(numbers, default=0))))
        number_width = QFontMetrics(self._font).horizontalAdvance("9" * digits) + runtime.px(14)
        return divider, gap, number_width

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: N802, ARG002
        theme = runtime.theme()
        # Code is left-to-right even in a Persian UI: without this the painter
        # inherits the application's RTL direction and every line is re-ordered.
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(theme.color("code_bg")))
        if self._diff is None:
            return

        divider, gap, number_width = self._columns()
        top = self._header_height()
        metrics = QFontMetrics(self._font)
        text_color = QColor(theme.color("text"))
        faint = QColor(theme.color("text_faint"))
        border = QColor(theme.color("border"))

        # Header band: the two file names, so a screenshot is self-describing.
        painter.fillRect(QRectF(0, 0, self.width(), top), QColor(theme.color("surface_2")))
        painter.setPen(QPen(border, 1))
        painter.drawLine(0, int(top), self.width(), int(top))
        painter.setFont(runtime.ui_font(10, 600))
        painter.setPen(QColor(theme.color("text_muted")))
        name_rect_left = QRectF(runtime.px(10), 0, divider - gap, top)
        name_rect_right = QRectF(divider + gap / 2, 0, divider - gap, top)
        painter.drawText(
            name_rect_left,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(self._old_name, Qt.TextElideMode.ElideMiddle, int(name_rect_left.width())),
        )
        painter.drawText(
            name_rect_right,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(self._new_name, Qt.TextElideMode.ElideMiddle, int(name_rect_right.width())),
        )

        painter.setFont(self._font)
        for index, row in enumerate(self._diff.rows):
            y = top + index * self._row_height
            if y > self.height():
                break
            self._paint_row(
                painter, row, y, divider, gap, number_width, metrics, text_color, faint, theme
            )

        # Centre divider.
        painter.setPen(QPen(_tint(theme, "border", 0.9), 1))
        painter.drawLine(int(divider), top, int(divider), self.height())

    def _paint_row(  # noqa: PLR0913 - a paint helper legitimately needs its state
        self,
        painter: QPainter,
        row: DiffRow,
        y: float,
        divider: float,
        gap: float,
        number_width: float,
        metrics: QFontMetrics,
        text_color: QColor,
        faint: QColor,
        theme,  # noqa: ANN001
    ) -> None:
        height = self._row_height
        tone = KIND_TONE.get(row.kind)
        if tone:
            painter.fillRect(
                QRectF(0, y, self.width(), height), _tint(theme, KIND_SOFT[row.kind], 0.9)
            )
        elif row.kind == "equal":
            # Barely-there striping keeps long context readable.
            if int(y / height) % 2 == 0:
                painter.fillRect(
                    QRectF(0, y, self.width(), height), _tint(theme, "surface_2", 0.55)
                )

        marker = {"add": "+", "remove": "−", "change": "~"}.get(row.kind, " ")
        if row.kind != "equal":
            painter.setPen(QColor(theme.color(tone or "text_muted")))
            painter.setFont(runtime.ui_font(10, 700))
            painter.drawText(
                QRectF(runtime.px(4), y, runtime.px(12), height),
                Qt.AlignmentFlag.AlignCenter,
                marker,
            )
        painter.setFont(self._font)

        # Left pane (old) and right pane (new), each with its own line number.
        panes = (
            (row.old_text, row.old_no, row.old_spans, row.kind in {"remove", "change"}),
            (row.new_text, row.new_no, row.new_spans, row.kind in {"add", "change"}),
        )
        for pane_index, (text, number, spans, active) in enumerate(panes):
            x0 = runtime.px(18) if pane_index == 0 else divider + gap / 2
            width = divider - gap - runtime.px(18) if pane_index == 0 else self.width() - x0 - runtime.px(8)
            number_rect = QRectF(x0, y, number_width, height)
            painter.setPen(faint if number is not None else QColor(theme.color("border_strong")))
            painter.setFont(runtime.ui_font(10))
            painter.drawText(
                number_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                str(number) if number is not None else "",
            )
            text_x = x0 + number_width + runtime.px(4)
            text_width = max(0.0, width - number_width)
            text_rect = QRectF(text_x, y, text_width, height)

            if spans and active:
                painter.setFont(self._font)
                for start, end in spans:
                    prefix = metrics.horizontalAdvance(text[:start])
                    span_width = metrics.horizontalAdvance(text[start:end])
                    if prefix > text_width:
                        break
                    painter.fillRect(
                        QRectF(
                            text_x + prefix,
                            y + runtime.px(3),
                            min(span_width, text_width - prefix),
                            height - runtime.px(6),
                        ),
                        _tint(theme, tone or "accent", 0.22),
                    )
            # An empty line still needs a visible row body; only the *other*
            # pane of a one-sided row (remove/add) is intentionally blank.
            blank = text == "" and row.kind in {"remove", "add"}
            painter.setPen(QColor(theme.color("text_faint")) if blank else text_color)
            painter.setFont(self._font)
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(text_width))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                elided,
            )

    # ------------------------------------------------------------------ hover
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        point = event.position()
        top = self._header_height()
        if self._diff and point.y() >= top:
            index = int((point.y() - top) // self._row_height)
            if 0 <= index < len(self._diff.rows):
                row = self._diff.rows[index]
                text = row.new_text or row.old_text
                self.setToolTip(text if len(text) > 60 else "")
                return
        self.setToolTip("")
        super().mouseMoveEvent(event)


__all__ = ["DiffView"]
