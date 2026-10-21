"""Honest, well-designed surfaces for capabilities scheduled for later phases.

These are not mock screenshots: they state exactly what exists today and when
the real capability will arrive, so the application never pretends.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...version import PHASE, VERSION
from ..theme import runtime
from ..widgets.foundation import Badge


class FeatureItem(QFrame):
    def __init__(self, icon_name: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FeatureItem")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(11), runtime.px(8), runtime.px(11), runtime.px(8))
        layout.setSpacing(runtime.px(8))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px(icon_name, 14, "muted"))
        layout.addWidget(icon)
        label = QLabel(title)
        label.setProperty("role", "muted")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        self.label = label
        # A wrapped label reports its real height only for a given width, and a
        # frame does not forward that: keep the row at least as tall as the text
        # so a two-line feature is never cut in half.
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        self.setSizePolicy(policy)
        self.setStyleSheet(
            f"QFrame#FeatureItem {{ background-color: {runtime.theme().color('surface_2')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(9)}px; }}"
        )
        self._pad = runtime.px(8) * 2
        self._fit_pending = False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._schedule_fit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._schedule_fit()

    def _schedule_fit(self) -> None:
        """Re-measure after the layout settles.

        Changing a minimum height from inside ``resizeEvent`` re-enters the
        layout while it is still assigning geometry, which left the wrapped
        label at one line high. Deferring keeps each pass consistent.
        """
        if self._fit_pending:
            return
        self._fit_pending = True
        QTimer.singleShot(0, self._fit_text)

    def _fit_text(self) -> None:
        self._fit_pending = False
        width = self.label.width()
        if width < 20:
            return
        needed = self.label.heightForWidth(width) + self._pad
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)


ROUTES = {
    "agent": {
        "icon": "sparkles",
        "phase": 4,
        "title": "placeholder.agent_title",
        "body": "placeholder.agent_body",
        "features": [("route", 1), ("wrench", 2), ("shield", 3)],
    },
    "code": {
        "icon": "code",
        "phase": 3,
        "title": "placeholder.code_title",
        "body": "placeholder.code_body",
        "features": [("file", 1), ("terminal", 2), ("refresh", 3)],
    },
    "images": {
        "icon": "image",
        "phase": 4,
        "title": "placeholder.images_title",
        "body": "placeholder.images_body",
        "features": [("wand", 1), ("grid", 2), ("download", 3)],
    },
    "web": {
        "icon": "globe",
        "phase": 4,
        "title": "placeholder.web_title",
        "body": "placeholder.web_body",
        "features": [("search", 1), ("link", 2), ("book", 3)],
    },
    "prompts": {
        "icon": "book",
        "phase": 5,
        "title": "placeholder.prompts_title",
        "body": "placeholder.prompts_body",
        "features": [("search", 1), ("layers", 2), ("folder", 3)],
    },
    "tasks": {
        "icon": "list-check",
        "phase": 5,
        "title": "placeholder.tasks_title",
        "body": "placeholder.tasks_body",
        "features": [("activity", 1), ("clock", 2), ("file", 3)],
    },
    "performance": {
        "icon": "gauge",
        "phase": 5,
        "title": "placeholder.performance_title",
        "body": "placeholder.performance_body",
        "features": [("cpu", 1), ("hard-drive", 2), ("clock", 3)],
    },
}


class PlaceholderView(QWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._route = "code"
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = _PlaceholderContent()
        self.content.back.clicked.connect(self.back_requested)
        scroll.setWidget(self.content)
        outer.addWidget(scroll)

    def set_route(self, route: str) -> None:
        if route not in ROUTES:
            return
        self._route = route
        data = ROUTES[route]
        self.content.set_content(data)

    def retranslate(self) -> None:
        self.content.set_content(ROUTES.get(self._route, ROUTES["code"]))


class _PlaceholderContent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PlaceholderContent")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(runtime.px(48), runtime.px(40), runtime.px(48), runtime.px(30))
        self.root.setSpacing(runtime.px(14))
        self.root.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("PhaseCard")
        self.card.setProperty("panel", "card")
        self.card.setMaximumWidth(runtime.px(660))
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(runtime.px(28), runtime.px(26), runtime.px(28), runtime.px(24))
        self.card_layout.setSpacing(runtime.px(12))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.card, 10)
        row.addStretch(1)
        self.root.addLayout(row)
        self.root.addStretch(1)

        self.badge = Badge(tr("placeholder.phase_badge", phase=PHASE), "violet")
        self.card_layout.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)
        # The window header already names the feature, so the card opens with
        # its state badge and the explanation instead of a second headline.
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setProperty("role", "muted")
        self.card_layout.addWidget(self.body)
        self.features_grid = QVBoxLayout()
        self.features_grid.setSpacing(runtime.px(7))
        self.card_layout.addLayout(self.features_grid)
        self.note = QLabel(tr("placeholder.note"))
        self.note.setWordWrap(True)
        self.note.setProperty("role", "faint")
        self.note.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        self.card_layout.addWidget(self.note)
        footer = QHBoxLayout()
        self.back = QPushButton(tr("placeholder.go_chat"))
        self.back.setProperty("variant", "secondary")
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.addWidget(self.back)
        footer.addStretch(1)
        self.phase_label = QLabel(f"v{VERSION} · {tr('placeholder.phase_badge', phase=PHASE)}")
        self.phase_label.setProperty("role", "faint")
        self.phase_label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        footer.addWidget(self.phase_label)
        self.card_layout.addLayout(footer)

    def set_content(self, data: dict) -> None:
        while self.features_grid.count():
            item = self.features_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.badge.setText(tr("placeholder.phase_badge", phase=data["phase"]))
        self.body.setText(tr(data["body"]))
        # Written once at construction, so it has to follow the language too.
        self.note.setText(tr("placeholder.note"))
        self.back.setText(tr("placeholder.go_chat"))
        self.card.setAccessibleName(tr(data["title"]))
        key = data["title"].replace("placeholder.", "placeholder.")  # e.g. placeholder.code_title
        route = key[len("placeholder."):-len("_title")]
        for icon_name, index in data["features"]:
            item = FeatureItem(icon_name, tr(f"placeholder.{route}.f{index}"))
            self.features_grid.addWidget(item)
        self.features_grid.invalidate()
        self.phase_label.setText(f"v{VERSION} · {tr('placeholder.phase_badge', phase=PHASE)}")
