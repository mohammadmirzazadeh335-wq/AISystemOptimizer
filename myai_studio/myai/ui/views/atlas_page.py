"""Project Atlas: the import graph of the open project, drawn for humans.

Every edge comes from a real import statement resolved to a real file by
``services.atlas``. Clicking a node opens that file in Code Studio; the hub list
names the files the rest of the project depends on, which is usually the answer
to "where do I start reading?".
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import tr
from ...services.atlas import Atlas, build_atlas
from ...services.projects import Project
from ..theme import runtime
from ..widgets.foundation import Badge, EmptyState
from ..widgets.graph_canvas import AtlasCanvas
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)


class _Stat(QFrame):
    """Compact number + label used above the canvas."""

    def __init__(self, label: str, tone: str = "accent", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(12), runtime.px(9), runtime.px(12), runtime.px(9))
        layout.setSpacing(runtime.px(1))
        self.value = QLabel("—")
        self.value.setProperty("role", "h2")
        self.value.setStyleSheet(f"color: {runtime.theme().color(tone)};")
        layout.addWidget(self.value)
        self.caption = QLabel(label)
        self.caption.setProperty("role", "faint")
        self.caption.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        layout.addWidget(self.caption)


class AtlasPage(PageShell):
    notify = Signal(str, str)
    open_file = Signal(str)
    open_code = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("atlas.title", "atlas.subtitle", icon_name="route")
        self.context = context
        self.project: Project | None = None
        self.atlas: Atlas | None = None
        self._selected = ""
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        stats_card, stats_layout = self.card()
        stats_row = QHBoxLayout()
        stats_row.setSpacing(runtime.px(8))
        self.files_stat = _Stat(tr("atlas.files"), "accent")
        self.edges_stat = _Stat(tr("atlas.edges"), "success")
        self.lines_stat = _Stat(tr("atlas.lines"), "violet")
        self.orphans_stat = _Stat(tr("atlas.orphans"), "warning")
        for stat in (self.files_stat, self.edges_stat, self.lines_stat, self.orphans_stat):
            stats_row.addWidget(stat, 1)
        stats_layout.addLayout(stats_row)

        graph_card, graph_layout = self.card("atlas.graph_title", "route")
        head = QHBoxLayout()
        head.setSpacing(runtime.px(8))
        self.project_badge = Badge("", "muted")
        head.addWidget(self.project_badge)
        self.truncated_badge = Badge(tr("atlas.truncated"), "warning")
        self.truncated_badge.setVisible(False)
        head.addWidget(self.truncated_badge)
        head.addStretch(1)
        self.open_code_button = ghost_button(tr("atlas.open_code"), "code")
        self.open_code_button.clicked.connect(self.open_code)
        head.addWidget(self.open_code_button)
        self.refresh_button = ghost_button(tr("atlas.refresh"), "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        head.addWidget(self.refresh_button)
        graph_layout.addLayout(head)

        self.graph_stack = QWidget()
        stack_layout = QVBoxLayout(self.graph_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.setSpacing(runtime.px(6))
        self.canvas = AtlasCanvas()
        self.canvas.node_activated.connect(self._node_activated)
        stack_layout.addWidget(self.canvas, 1)
        legend = QHBoxLayout()
        legend.setSpacing(runtime.px(10))
        self.legend_label = hint_label(tr("atlas.legend"), tone="faint")
        legend.addWidget(self.legend_label)
        legend.addStretch(1)
        self.hint = hint_label(tr("atlas.hint"), tone="faint")
        legend.addWidget(self.hint)
        stack_layout.addLayout(legend)
        graph_layout.addWidget(self.graph_stack)

        self.empty = EmptyState(
            tr("atlas.no_project_title"),
            tr("atlas.no_project_body"),
            "route",
            action=self._empty_action(),
        )
        empty_wrap = QWidget()
        empty_layout = QVBoxLayout(empty_wrap)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty)
        empty_layout.addStretch(1)
        graph_layout.addWidget(empty_wrap)

        hubs_card, hubs_layout = self.card("atlas.hubs_title", "zap")
        self.hubs_hint = hint_label(tr("atlas.hubs_hint"))
        hubs_layout.addWidget(self.hubs_hint)
        self.hubs_box = QVBoxLayout()
        self.hubs_box.setSpacing(runtime.px(4))
        hubs_layout.addLayout(self.hubs_box)
        self.hubs_empty = hint_label(tr("atlas.no_hubs"), tone="faint")
        hubs_layout.addWidget(self.hubs_empty)

    def _empty_action(self) -> QWidget:
        button = primary_button(tr("atlas.go_to_code"), "code")
        button.clicked.connect(self.open_code)
        return button

    # ------------------------------------------------------------------- data
    def set_project(self, project: Project | None) -> None:
        self.project = project
        self._selected = ""
        self.refresh()

    def refresh(self) -> None:  # noqa: D401 - page contract
        if self.project is None:
            self.atlas = None
            self.canvas.set_atlas(None)
            self.graph_stack.setVisible(False)
            self.empty.setVisible(True)
            self.project_badge.setText(tr("atlas.no_project"))
            self.project_badge.set_tone("muted")
            for stat in (self.files_stat, self.edges_stat, self.lines_stat, self.orphans_stat):
                stat.value.setText("—")
            self._fill_hubs(None)
            return
        try:
            atlas = build_atlas(self.context_projects(), self.project)
        except Exception as exc:  # noqa: BLE001 - a broken folder is a message
            logger.warning("atlas_failed error=%s", exc)
            self.notify.emit(str(exc), "error")
            atlas = Atlas()
        self.atlas = atlas
        self.project_badge.setText(self.project.name)
        self.project_badge.set_tone("accent")
        self.canvas.set_atlas(atlas)
        has_nodes = bool(atlas.nodes)
        self.graph_stack.setVisible(has_nodes)
        self.empty.setVisible(not has_nodes)
        if not has_nodes:
            self.empty.title_label.setText(tr("atlas.empty_title"))
            self.empty.body_label.setText(tr("atlas.empty_body"))
        stats = atlas.stats
        self.files_stat.value.setText(str(stats.get("files", 0)))
        self.edges_stat.value.setText(str(stats.get("edges", 0)))
        self.lines_stat.value.setText(f"{stats.get('lines', 0):,}")
        self.orphans_stat.value.setText(str(stats.get("orphan_count", 0)))
        self.truncated_badge.setVisible(bool(stats.get("truncated")))
        self._fill_hubs(atlas)

    def context_projects(self):  # noqa: ANN201 - ProjectService
        """Reuse the Code Studio service so path rules stay identical."""
        from ...services.projects import ProjectService

        if not hasattr(self, "_projects"):
            self._projects = ProjectService(self.context.paths, self.context.settings)
        return self._projects

    def _fill_hubs(self, atlas: Atlas | None) -> None:
        while self.hubs_box.count():
            item = self.hubs_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        hubs = (atlas.stats.get("hubs") if atlas else None) or []
        self.hubs_empty.setVisible(not hubs)
        for hub in hubs:
            button = ghost_button(f"{hub['id']}  ·  {hub['incoming']}", "zap")
            button.setStyleSheet("text-align: left; padding-left: 8px;")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tr("atlas.open_hint", file=hub["id"]))
            button.clicked.connect(lambda _=False, path=hub["id"]: self._open_node(path))
            self.hubs_box.addWidget(button)
        if atlas is not None and atlas.stats.get("orphans"):
            self.hubs_hint.setText(
                tr("atlas.hubs_with_orphans", count=len(atlas.stats["orphans"]))
            )
        else:
            self.hubs_hint.setText(tr("atlas.hubs_hint"))

    # ----------------------------------------------------------------- events
    def _node_activated(self, node_id: str) -> None:
        self._selected = node_id
        self.open_file.emit(node_id)

    def _open_node(self, node_id: str) -> None:
        self._selected = node_id
        self.open_file.emit(node_id)

    # ----------------------------------------------------------- page contract
    def retranslate(self) -> None:
        super().retranslate()
        self.project_badge.setText(self.project.name if self.project else tr("atlas.no_project"))
        self.refresh_button.setText(tr("atlas.refresh"))
        self.open_code_button.setText(tr("atlas.open_code"))
        self.truncated_badge.setText(tr("atlas.truncated"))
        self.legend_label.setText(tr("atlas.legend"))
        self.hint.setText(tr("atlas.hint"))
        self.files_stat.caption.setText(tr("atlas.files"))
        self.edges_stat.caption.setText(tr("atlas.edges"))
        self.lines_stat.caption.setText(tr("atlas.lines"))
        self.orphans_stat.caption.setText(tr("atlas.orphans"))

    def rebuild(self) -> None:
        super().rebuild()


__all__ = ["AtlasPage"]
