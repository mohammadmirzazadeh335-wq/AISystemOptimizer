"""Performance monitor (Phase 5).

Every number on this page is sampled from the running process or from the real
workspace on disk by :class:`myai.services.performance.PerformanceService`.
Nothing is extrapolated: when a platform cannot report a value the tile says so
instead of showing a plausible-looking constant.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.timeutil import format_bytes
from ...i18n import tr
from ...services.performance import PerformanceSnapshot
from ..theme import runtime
from ..widgets.fields import ToggleSwitch
from ..widgets.foundation import Badge
from .page_base import PageShell, ghost_button, hint_label

logger = logging.getLogger(__name__)

REFRESH_MS = 2000


def _uptime(seconds: float) -> str:
    total = int(max(0, seconds))
    if total >= 3600:
        return tr("performance.uptime_hm", hours=total // 3600, minutes=(total % 3600) // 60)
    if total >= 60:
        return tr("performance.uptime_ms", minutes=total // 60, seconds=total % 60)
    return tr("performance.uptime_s", seconds=total)


class MeterBar(QWidget):
    """Thin token-coloured meter; the value is a 0–1 ratio."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio: float | None = None
        self.setFixedHeight(runtime.px(8))
        self.setMinimumWidth(runtime.px(80))

    def set_ratio(self, ratio: float | None) -> None:
        self._ratio = None if ratio is None else max(0.0, min(1.0, float(ratio)))
        self.update()

    def ratio(self) -> float | None:
        return self._ratio

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        theme = runtime.theme()
        track = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2
        painter.setBrush(QColor(theme.color("surface_3")))
        painter.drawRoundedRect(track, radius, radius)
        if self._ratio:
            width = max(self.height(), track.width() * self._ratio)
            fill = QRectF(0, 0, width, self.height())
            colour = theme.color("accent")
            if self._ratio >= 0.9:
                colour = theme.color("danger")
            elif self._ratio >= 0.75:
                colour = theme.color("warning")
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(fill, radius, radius)
        painter.end()


class StatTile(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(13), runtime.px(10), runtime.px(13), runtime.px(11))
        layout.setSpacing(runtime.px(2))
        self.caption = QLabel(label)
        self.caption.setProperty("role", "faint")
        layout.addWidget(self.caption)
        self.value = QLabel("—")
        self.value.setProperty("role", "stat")
        layout.addWidget(self.value)
        self.detail = QLabel("")
        self.detail.setProperty("role", "faint")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class PerformancePage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("performance.title", "performance.subtitle", icon_name="gauge")
        self.context = context
        self.service = context.performance
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.sample)
        self._snapshot: PerformanceSnapshot | None = None
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(runtime.px(9))
        self.updated = QLabel("")
        self.updated.setProperty("role", "faint")
        bar.addWidget(self.updated, 1)
        self.auto_label = QLabel(tr("performance.auto"))
        self.auto_label.setProperty("role", "faint")
        bar.addWidget(self.auto_label)
        self.auto_toggle = ToggleSwitch()
        self.auto_toggle.setAccessibleName(tr("performance.auto"))
        self.auto_toggle.setChecked(True)
        self.auto_toggle.toggled.connect(self._on_auto)
        bar.addWidget(self.auto_toggle)
        self.refresh_button = ghost_button(tr("performance.refresh"), "refresh")
        self.refresh_button.clicked.connect(self.sample)
        bar.addWidget(self.refresh_button)
        holder = QWidget()
        holder.setLayout(bar)
        self.add_widget(holder)

        tiles = QHBoxLayout()
        tiles.setSpacing(runtime.px(9))
        self.cpu_tile = StatTile(tr("performance.cpu"))
        self.memory_tile = StatTile(tr("performance.memory"))
        self.threads_tile = StatTile(tr("performance.threads"))
        self.uptime_tile = StatTile(tr("performance.uptime"))
        for tile in (self.cpu_tile, self.memory_tile, self.threads_tile, self.uptime_tile):
            tiles.addWidget(tile, 1)
        tile_holder = QWidget()
        tile_holder.setLayout(tiles)
        self.add_widget(tile_holder)

        memory_card, memory_layout = self.card("performance.system_title", "cpu")
        memory_row = QHBoxLayout()
        memory_row.setSpacing(runtime.px(10))
        self.memory_meter = MeterBar()
        memory_row.addWidget(self.memory_meter, 1)
        self.memory_caption = QLabel("")
        self.memory_caption.setProperty("role", "muted")
        memory_row.addWidget(self.memory_caption)
        memory_layout.addLayout(memory_row)
        memory_layout.addWidget(hint_label(tr("performance.system_hint")))

        disk_card, disk_layout = self.card("performance.disk_title", "hard-drive")
        disk_row = QHBoxLayout()
        disk_row.setSpacing(runtime.px(10))
        self.disk_meter = MeterBar()
        disk_row.addWidget(self.disk_meter, 1)
        self.disk_caption = QLabel("")
        self.disk_caption.setProperty("role", "muted")
        disk_row.addWidget(self.disk_caption)
        disk_layout.addLayout(disk_row)
        self.disk_hint = hint_label("")
        disk_layout.addWidget(self.disk_hint)

        workspace_card, workspace_layout = self.card("performance.workspace_title", "folder")
        self.workspace_badges = QHBoxLayout()
        self.workspace_badges.setSpacing(runtime.px(6))
        workspace_layout.addLayout(self.workspace_badges)
        self.workspace_hint = hint_label("")
        workspace_layout.addWidget(self.workspace_hint)

        self.availability = hint_label("")
        self.add_widget(self.availability)

    # -------------------------------------------------------------------- data
    def _on_auto(self, enabled: bool) -> None:
        if enabled and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.sample()
        if self.auto_toggle.isChecked():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        self.sample()

    def sample(self) -> None:
        try:
            snapshot = self.service.snapshot()
        except Exception as exc:  # noqa: BLE001 - metrics must never crash the page
            logger.exception("performance_sample_failed")
            self.availability.setText(tr("performance.failed", error=type(exc).__name__))
            self.availability.setVisible(True)
            return
        self._snapshot = snapshot
        self._apply(snapshot)
        self.updated.setText(tr("performance.updated", time=datetime.now().strftime("%H:%M:%S")))

    def _apply(self, snap: PerformanceSnapshot) -> None:
        if snap.cpu_percent is None:
            self.cpu_tile.set_value(tr("performance.na"), tr("performance.cpu_na"))
        else:
            self.cpu_tile.set_value(f"{snap.cpu_percent:.1f}%", tr("performance.cpu_hint"))
        self.memory_tile.set_value(
            format_bytes(snap.rss_bytes) if snap.rss_bytes is not None else tr("performance.na"),
            tr("performance.memory_hint"),
        )
        self.threads_tile.set_value(str(snap.threads), tr("performance.threads_hint"))
        self.uptime_tile.set_value(_uptime(snap.uptime_seconds), tr("performance.uptime_hint"))

        ratio = snap.memory_used_ratio
        self.memory_meter.set_ratio(ratio)
        if ratio is None:
            self.memory_caption.setText(tr("performance.na"))
        else:
            self.memory_caption.setText(
                tr(
                    "performance.system_usage",
                    used=format_bytes((snap.memory_total or 0) - (snap.memory_available or 0)),
                    total=format_bytes(snap.memory_total or 0),
                    percent=ratio * 100,
                )
            )

        disk_ratio = snap.disk_used_ratio
        self.disk_meter.set_ratio(disk_ratio)
        if disk_ratio is None:
            self.disk_caption.setText(tr("performance.na"))
            self.disk_hint.setText(tr("performance.disk_na"))
        else:
            self.disk_caption.setText(
                tr(
                    "performance.disk_usage",
                    free=format_bytes(snap.disk_free or 0),
                    total=format_bytes(snap.disk_total or 0),
                )
            )
            self.disk_hint.setText(tr("performance.disk_hint", used=format_bytes(snap.disk_used or 0)))

        while self.workspace_badges.count():
            item = self.workspace_badges.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.workspace_badges.addWidget(
            Badge(tr("performance.workspace_files", count=snap.workspace_files), "accent")
        )
        self.workspace_badges.addWidget(
            Badge(tr("performance.workspace_size", size=format_bytes(snap.workspace_bytes)), "muted")
        )
        self.workspace_badges.addWidget(Badge(tr("performance.db_size", size=format_bytes(snap.db_bytes)), "muted"))
        self.workspace_badges.addWidget(
            Badge(tr("performance.logs_size", size=format_bytes(snap.logs_bytes)), "muted")
        )
        self.workspace_badges.addStretch(1)
        self.workspace_hint.setText(
            tr("performance.workspace_truncated", limit=20000)
            if snap.workspace_truncated
            else tr("performance.workspace_hint", path=str(self.service.home))
        )

        missing = []
        if snap.cpu_percent is None:
            missing.append(tr("performance.missing_cpu"))
        if snap.memory_total is None:
            missing.append(tr("performance.missing_memory"))
        self.availability.setText(tr("performance.unavailable", items=", ".join(missing)) if missing else "")
        self.availability.setVisible(bool(missing))

    # --------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.auto_label.setText(tr("performance.auto"))
        self.refresh_button.setText(tr("performance.refresh"))
        self.cpu_tile.caption.setText(tr("performance.cpu"))
        self.memory_tile.caption.setText(tr("performance.memory"))
        self.threads_tile.caption.setText(tr("performance.threads"))
        self.uptime_tile.caption.setText(tr("performance.uptime"))
        self.sample()
