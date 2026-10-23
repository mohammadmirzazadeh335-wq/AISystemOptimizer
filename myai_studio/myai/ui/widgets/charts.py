"""Small, token-driven charts: donut, gauge and a stacked proportion bar.

They are painted with QPainter instead of a charting dependency, animate only
when Qt gives them a valid window (a hidden test window never starts a timer
storm), and read every colour from the live theme so a theme switch repaints
correctly without rebuilding the page.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import runtime
from .painting import paint_event


@dataclass(frozen=True)
class Slice:
    label: str
    value: float
    color: str


class DonutChart(QWidget):
    """Ring chart with a large centre value and a caption underneath.

    ``set_segments`` takes real numbers; zero values are skipped so an empty
    category cannot draw a hairline that looks like data.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[Slice] = []
        self._fill: float | None = None
        self._center = "—"
        self._caption = ""
        self._progress = 1.0
        self._animation: QPropertyAnimation | None = None
        self.setMinimumSize(runtime.px(190), runtime.px(190))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(520)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ------------------------------------------------------------- properties
    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def set_segments(self, segments: list[Slice]) -> None:
        self._segments = [segment for segment in segments if segment.value > 0]
        self.update()

    def segments(self) -> list[Slice]:
        return list(self._segments)

    def set_center(self, value: str, caption: str = "") -> None:
        self._center = value
        self._caption = caption
        self.update()

    def set_data(
        self,
        segments: list[Slice],
        center: str,
        caption: str = "",
        fill: float | None = None,
    ) -> None:
        """``fill`` (0..1) draws the composition inside that share of the ring.

        The Context Map passes the used share of the model window here, so an
        almost-empty request looks almost empty instead of painting a full
        multicolour ring next to the words "0%".
        """
        self._fill = None if fill is None else max(0.0, min(1.0, float(fill)))
        self.set_segments(segments)
        self.set_center(center, caption)
        self.replay()

    def replay(self) -> None:
        """Animate from zero — only when a real window is visible."""
        if not self.isVisible() or self.window().windowHandle() is None:
            self.set_progress(1.0)
            return
        self._animation.stop()
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

    # ---------------------------------------------------------------- painting
    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: N802, ARG002
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        theme = runtime.theme()
        side = min(self.width(), self.height())
        thickness = max(runtime.px(12), side * 0.11)
        margin = thickness / 2 + runtime.px(6)
        rect = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        track_pen = QPen(QColor(theme.color("surface_3")))
        track_pen.setWidthF(thickness)
        track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        total = sum(segment.value for segment in self._segments)
        fill = 1.0 if self._fill is None else self._fill
        if total > 0 and self._progress > 0 and fill > 0:
            start = 90 * 16
            gap = 2.2 * 16 if len(self._segments) > 1 else 0
            # A 0.1% share still has to be visible as *something*: a minimum
            # arc keeps the ring honest (the caption carries the number) while
            # showing that the composition is not empty.
            arc = max(int(360 * 16 * fill), 7 * 16)
            for segment in self._segments:
                span = arc * (segment.value / total) * self._progress
                if span <= 0:
                    continue
                pen = QPen(QColor(segment.color))
                pen.setWidthF(thickness)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                # The separator gap must never eat a thin slice: below three
                # gaps of width the slice is drawn whole.
                drawn = int(span) if int(span) <= gap * 3 else int(span) - gap
                painter.drawArc(rect, start - int(span), max(0, drawn))
                start -= int(span)

        painter.setPen(QColor(theme.color("text")))
        font = QFont(runtime.ui_font(max(20, int(side * 0.16)), 600))
        painter.setFont(font)
        center_rect = QRectF(rect.x(), rect.y() + rect.height() * 0.30, rect.width(), rect.height() * 0.30)
        painter.drawText(center_rect, Qt.AlignmentFlag.AlignCenter, self._center)
        if self._caption:
            painter.setPen(QColor(theme.color("text_muted")))
            painter.setFont(QFont(runtime.ui_font(10)))
            caption_rect = QRectF(rect.x(), rect.y() + rect.height() * 0.56, rect.width(), rect.height() * 0.18)
            painter.drawText(caption_rect, Qt.AlignmentFlag.AlignCenter, self._caption)


class GaugeScore(QWidget):
    """270° gauge used for the health score; the number is the message."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._score = 0
        self._verdict = "healthy"
        self.setMinimumSize(runtime.px(190), runtime.px(150))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(runtime.px(160))

    def set_score(self, score: int, verdict: str = "healthy") -> None:
        self._score = max(0, min(100, int(score)))
        self._verdict = verdict
        self.update()

    def score(self) -> int:
        return self._score

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: N802, ARG002
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        theme = runtime.theme()
        # A 270-degree gauge is not a circle: its lowest drawn points sit at
        # sin(45 deg) below the centre, so the radius has to come from the
        # height (R * 1.707 + pen) or the arc is clipped at the bottom and the
        # "/ 100" caption disappears behind the edge of the widget.
        thickness = max(runtime.px(10), self.height() * 0.075)
        radius = min(
            (self.height() - 2 * thickness) / 1.71,
            (self.width() - 2 * thickness) / 2.0,
        )
        radius = max(runtime.px(20), radius)
        centre_x = self.width() / 2
        centre_y = thickness + radius
        rect = QRectF(centre_x - radius, centre_y - radius, radius * 2, radius * 2)
        # surface_3 is invisible on the light theme's near-white card, so the
        # unused part of the arc uses the stronger border token instead.
        track = QPen(QColor(theme.color("border_strong")))
        track.setWidthF(thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 225 * 16, -270 * 16)

        tone = {"healthy": "success", "attention": "warning", "needs_care": "danger"}.get(
            self._verdict, "warning"
        )
        value = QPen(QColor(theme.color(tone)))
        value.setWidthF(thickness)
        value.setCapStyle(Qt.PenCapStyle.RoundCap)
        value.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(value)
        painter.drawArc(rect, 225 * 16, int(-270 * 16 * (self._score / 100.0)))

        painter.setPen(QColor(theme.color("text")))
        painter.setFont(QFont(runtime.ui_font(max(runtime.px(18), int(radius * 0.42)), 650)))
        painter.drawText(
            QRectF(centre_x - radius, centre_y - radius * 0.70, radius * 2, radius * 0.66),
            Qt.AlignmentFlag.AlignCenter,
            str(self._score),
        )
        painter.setPen(QColor(theme.color("text_faint")))
        painter.setFont(QFont(runtime.ui_font(10)))
        painter.drawText(
            QRectF(centre_x - radius, centre_y - radius * 0.02, radius * 2, radius * 0.34),
            Qt.AlignmentFlag.AlignCenter,
            "/ 100",
        )


class SegmentBar(QWidget):
    """One horizontal bar split by real proportions, with a soft track."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[Slice] = []
        self.setFixedHeight(runtime.px(10))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_segments(self, segments: list[Slice]) -> None:
        self._segments = [segment for segment in segments if segment.value > 0]
        self.update()

    def segments(self) -> list[Slice]:
        return list(self._segments)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: N802, ARG002
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        theme = runtime.theme()
        radius = self.height() / 2
        track = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.color("surface_3")))
        painter.drawRoundedRect(track, radius, radius)
        total = sum(segment.value for segment in self._segments)
        if total <= 0:
            return
        painter.save()
        painter.setClipPath(_rounded_path(track, radius))
        x = 0.0
        for index, segment in enumerate(self._segments):
            width = track.width() * (segment.value / total)
            if index == len(self._segments) - 1:
                width = track.width() - x
            painter.setBrush(QColor(segment.color))
            painter.drawRect(QRectF(x, 0, max(0.0, width - 1), self.height()))
            x += width
        painter.restore()


def _rounded_path(rect: QRectF, radius: float):  # noqa: ANN202 - QPainterPath
    from PySide6.QtGui import QPainterPath

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


__all__ = ["DonutChart", "GaugeScore", "SegmentBar", "Slice"]
