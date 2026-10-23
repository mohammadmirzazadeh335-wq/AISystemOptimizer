"""Dependency-graph canvas for the Project Atlas page.

Edges are quadratic curves between real resolved imports; node radius follows
file size, colour follows language, and a node with many importers gets a halo.
Hover highlights one neighbourhood, click opens the file in Code Studio via a
signal — the canvas itself never touches the filesystem.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...services.atlas import Atlas, AtlasNode
from ..theme import runtime
from .painting import paint_event


class AtlasCanvas(QWidget):
    node_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._atlas: Atlas | None = None
        self._hover: str | None = None
        self._selected: str | None = None
        self._radius_by_id: dict[str, float] = {}
        self.setMinimumHeight(runtime.px(360))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------- data
    def set_atlas(self, atlas: Atlas | None, *, selected: str | None = None) -> None:
        self._atlas = atlas
        self._selected = selected
        self._hover = None
        self.update()

    def atlas(self) -> Atlas | None:
        return self._atlas

    def node_count(self) -> int:
        return len(self._atlas.nodes) if self._atlas else 0

    def edge_count(self) -> int:
        return len(self._atlas.edges) if self._atlas else 0

    def hovered(self) -> str | None:
        return self._hover

    # -------------------------------------------------------------- geometry
    def _points(self) -> dict[str, QPointF]:
        if self._atlas is None:
            return {}
        pad = runtime.px(34)
        width = max(1.0, self.width() - 2 * pad)
        height = max(1.0, self.height() - 2 * pad)
        return {
            node.id: QPointF(pad + node.x * width, pad + node.y * height)
            for node in self._atlas.nodes
        }

    def _radii(self) -> dict[str, float]:
        if self._atlas is None:
            return {}
        if self._radius_by_id:
            return self._radius_by_id
        sizes = [node.size for node in self._atlas.nodes] or [1]
        low, high = min(sizes), max(sizes)
        span = max(1, high - low)
        radii: dict[str, float] = {}
        for node in self._atlas.nodes:
            ratio = (node.size - low) / span
            radius = runtime.px(5.5 + 11.0 * math.sqrt(ratio))
            if node.incoming:
                radius += runtime.px(1.5)
            radii[node.id] = radius
        self._radius_by_id = radii
        return radii

    def _node_at(self, point: QPointF) -> AtlasNode | None:
        if self._atlas is None:
            return None
        points = self._points()
        radii = self._radii()
        best: AtlasNode | None = None
        best_distance = 1e9
        for node in self._atlas.nodes:
            centre = points[node.id]
            distance = math.hypot(centre.x() - point.x(), centre.y() - point.y())
            limit = radii[node.id] + runtime.px(6)
            if distance <= limit and distance < best_distance:
                best, best_distance = node, distance
        return best

    # ---------------------------------------------------------------- painting
    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: N802, ARG002
        if self._atlas is None or not self._atlas.nodes:
            return
        painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        theme = runtime.theme()
        self._paint_grid(painter, theme)
        points = self._points()
        radii = self._radii()
        neighbours: set[str] = set()
        if self._hover:
            neighbours = {self._hover}
            for edge in self._atlas.edges:
                if edge.source == self._hover:
                    neighbours.add(edge.target)
                elif edge.target == self._hover:
                    neighbours.add(edge.source)

        base_edge = QColor(theme.color("accent"))
        base_edge.setAlpha(46)
        active_edge = QColor(theme.color("accent"))
        active_edge.setAlpha(215)

        for edge in self._atlas.edges:
            start = points.get(edge.source)
            end = points.get(edge.target)
            if start is None or end is None:
                continue
            emphasised = bool(neighbours) and edge.source in neighbours and edge.target in neighbours
            pen = QPen(active_edge if emphasised else base_edge)
            pen.setWidthF(runtime.px(1.6) if emphasised else runtime.px(1.0))
            painter.setPen(pen)
            painter.drawPath(_curve(start, end))

        labels: list[tuple[AtlasNode, QPointF, float]] = []
        for node in self._atlas.nodes:
            centre = points[node.id]
            radius = radii[node.id]
            colour = QColor(theme.color(node.tone))
            dimmed = bool(neighbours) and node.id not in neighbours
            if dimmed:
                colour.setAlpha(70)
            if node.incoming:
                halo = QColor(theme.color(node.tone))
                halo.setAlpha(38 if not dimmed else 12)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(centre, radius + runtime.px(5), radius + runtime.px(5))
            painter.setBrush(colour)
            outline = QColor(theme.color("bg"))
            if node.id == self._selected:
                outline = QColor(theme.color("accent"))
            pen = QPen(outline)
            pen.setWidthF(runtime.px(2.0) if node.id == self._selected else runtime.px(1.0))
            painter.setPen(pen)
            painter.drawEllipse(centre, radius, radius)
            if node.id == self._hover:
                glow = QColor(theme.color("accent"))
                glow.setAlpha(90)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(glow, runtime.px(2.0)))
                painter.drawEllipse(centre, radius + runtime.px(9), radius + runtime.px(9))
            if node.incoming or len(self._atlas.nodes) <= 14:
                labels.append((node, centre, radius))

        painter.setFont(runtime.ui_font(9, 500))
        metrics = QFontMetrics(runtime.ui_font(9))
        for node, centre, radius in labels:
            text = metrics.elidedText(node.label, Qt.TextElideMode.ElideMiddle, runtime.px(110))
            rect = QRectF(centre.x() - runtime.px(56), centre.y() + radius + runtime.px(3), runtime.px(112), runtime.px(14))
            painter.setPen(QColor(theme.color("text_muted")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)

    def _paint_grid(self, painter: QPainter, theme) -> None:  # noqa: ANN001
        """A faint dot grid gives the graph a surface to sit on."""
        step = runtime.px(26)
        dot = QColor(theme.color("border"))
        dot.setAlpha(90)
        painter.setPen(QPen(dot, 1.0))
        x = step
        while x < self.width():
            y = step
            while y < self.height():
                painter.drawPoint(int(x), int(y))
                y += step
            x += step

    # ------------------------------------------------------------------ input
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        node = self._node_at(event.position())
        node_id = node.id if node else None
        if node_id != self._hover:
            self._hover = node_id
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if node else Qt.CursorShape.ArrowCursor
            )
            if node:
                self.setToolTip(
                    f"{node.id}\n{node.language} · {node.lines:,} lines\n"
                    f"{node.incoming} imports in · {node.outgoing} out"
                )
            else:
                self.setToolTip("")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._hover:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            node = self._node_at(event.position())
            if node is not None:
                self._selected = node.id
                self.update()
                self.node_activated.emit(node.id)
        super().mouseReleaseEvent(event)


def _curve(start: QPointF, end: QPointF):  # noqa: ANN202 - QPainterPath
    from PySide6.QtGui import QPainterPath

    path = QPainterPath(start)
    mid = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length = max(1.0, math.hypot(dx, dy))
    bend = min(48.0, length * 0.16)
    control = QPointF(mid.x() - dy / length * bend, mid.y() + dx / length * bend)
    path.quadTo(control, end)
    return path


__all__ = ["AtlasCanvas"]
