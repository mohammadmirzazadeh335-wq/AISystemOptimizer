"""Shared behaviour of every main-window page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pars_erp.security.permissions import SecurityContext
from pars_erp.services.context import AppServices
from pars_erp.ui.formatting import Formatter


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        text_box.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("PageSubtitle")
        self.subtitle_label.setWordWrap(True)
        text_box.addWidget(self.subtitle_label)
        # the text box takes the free space so a longer subtitle never wraps
        # into a clipped second line inside the fixed-height header
        layout.addLayout(text_box, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, text: str, *, variant: str = "primary", slot=None,
                   tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", variant)
        button.setMinimumHeight(32)
        if tooltip:
            button.setToolTip(tooltip)
        if slot is not None:
            button.clicked.connect(slot)
        self.actions.addWidget(button)
        return button

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.updateGeometry()
        self.updateGeometry()


class PageBase(QWidget):
    """Base class: services + context + formatter + status reporting."""

    statusMessage = Signal(str)

    def __init__(self, services: AppServices, ctx: SecurityContext, formatter: Formatter,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.formatter = formatter
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(14)

    # ------------------------------------------------------------------ hooks
    def refresh(self) -> None:  # pragma: no cover - overridden
        """Reload data from the database. Called when the page is shown."""

    def update_context(self, ctx: SecurityContext) -> None:
        self.ctx = ctx

    def update_formatter(self, formatter: Formatter) -> None:
        self.formatter = formatter

    # ---------------------------------------------------------------- helpers
    def notify(self, message: str) -> None:
        self.statusMessage.emit(message)

    def can(self, permission: str) -> bool:
        return self.ctx.has(permission)


class CardPanel(QFrame):
    """Card with a title row that can host action buttons."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)
        self._layout.setSpacing(10)
        self.header_row = QHBoxLayout()
        self.header_row.setSpacing(8)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            self.header_row.addWidget(title_label)
            self._layout.addLayout(self.header_row)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("HintText")
            sub.setWordWrap(True)
            self._layout.addWidget(sub)
        self.header_row.addStretch(1)

    def add_header_widget(self, widget: QWidget) -> QWidget:
        self.header_row.addWidget(widget)
        return widget

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)
