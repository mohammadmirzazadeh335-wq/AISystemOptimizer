"""The MyAI Studio identity: vector mark, wordmark and application icon.

The mark is drawn with QPainter so it stays crisp at every DPI and can adopt
the active accent colour.  It is intentionally simple: a gradient tile, an
abstract "M" built from one continuous stroke, and an orbital spark.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from .theme import runtime
from .widgets.painting import paint_event


def paint_mark(painter: QPainter, rect: QRectF, *, accent: str = "", violet: str = "", detailed: bool = True) -> None:
    theme = runtime.theme()
    accent = accent or theme.color("accent")
    violet = violet or theme.color("violet")
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    radius = rect.width() * 0.30
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor(accent))
    gradient.setColorAt(0.55, QColor(accent))
    gradient.setColorAt(1.0, QColor(violet))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)

    # top sheen
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 46))
    sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
    painter.setBrush(sheen)
    painter.setClipPath(_rounded_path(rect, radius))
    painter.drawRect(rect)
    painter.setClipping(False)


    # The "M" stroke
    stroke = QPen(QColor(255, 255, 255), max(1.6, rect.width() * 0.078))
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(stroke)
    path = QPainterPath()
    path.moveTo(rect.x() + rect.width() * 0.30, rect.y() + rect.height() * 0.68)
    path.lineTo(rect.x() + rect.width() * 0.30, rect.y() + rect.height() * 0.34)
    path.lineTo(rect.x() + rect.width() * 0.50, rect.y() + rect.height() * 0.52)
    path.lineTo(rect.x() + rect.width() * 0.70, rect.y() + rect.height() * 0.34)
    path.lineTo(rect.x() + rect.width() * 0.70, rect.y() + rect.height() * 0.68)
    painter.drawPath(path)

    if detailed:
        spark = QRectF(
            rect.x() + rect.width() * 0.705,
            rect.y() + rect.height() * 0.245,
            rect.width() * 0.13,
            rect.width() * 0.13,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(spark)
    painter.restore()


def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def mark_pixmap(size: int, dpr: float = 2.0) -> QPixmap:
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    paint_mark(painter, QRectF(0, 0, size, size), detailed=size >= 28)
    painter.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(mark_pixmap(size, dpr=1.0))
    return icon


class LogoMark(QWidget):
    def __init__(self, size: int = 34, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._size = size
        self.setFixedSize(runtime.px(size), runtime.px(size))
        runtime.signals.changed.connect(lambda *_: self.update())

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        paint_mark(painter, QRectF(0, 0, self.width(), self.height()), detailed=self._size >= 26)
class Wordmark(QWidget):
    """Two-line lockup: MyAI Studio / ULTIMATE, always left-to-right."""

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setMinimumHeight(runtime.px(34))
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())
        runtime.signals.changed.connect(lambda *_: self.update())

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        theme = runtime.theme()
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        painter.setFont(runtime.ui_font(14, 700))
        painter.setPen(QColor(theme.color("text")))
        painter.drawText(
            QRect(0, 0, self.width(), runtime.px(19)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "MyAI Studio",
        )
        font = runtime.ui_font(8, 700)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.2)
        painter.setFont(font)
        painter.setPen(QColor(theme.color("text_faint")))
        painter.drawText(
            QRect(0, runtime.px(18), self.width(), runtime.px(13)),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "U L T I M A T E",
        )
    def sizeHint(self):  # noqa: ANN201

        return QSize(runtime.px(130), runtime.px(34))
