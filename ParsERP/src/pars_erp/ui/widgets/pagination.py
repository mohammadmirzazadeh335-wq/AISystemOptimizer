"""Pagination bar used by every paged list."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from pars_erp.services.common import Page
from pars_erp.ui.formatting import to_display_digits


class PaginationBar(QWidget):
    pageChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._page = 1
        self._pages = 1
        self._total = 0
        self._persian = True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        layout.addWidget(self.summary)
        layout.addStretch(1)
        self.first_button = self._button("⏮", "صفحه اول")
        self.previous_button = self._button("قبلی", "صفحه قبل")
        self.page_label = QLabel("")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumWidth(110)
        self.next_button = self._button("بعدی", "صفحه بعد")
        self.last_button = self._button("⏭", "صفحه آخر")
        for widget in (self.first_button, self.previous_button, self.page_label,
                       self.next_button, self.last_button):
            layout.addWidget(widget)
        self.first_button.clicked.connect(lambda: self._goto(1))
        self.previous_button.clicked.connect(lambda: self._goto(self._page - 1))
        self.next_button.clicked.connect(lambda: self._goto(self._page + 1))
        self.last_button.clicked.connect(lambda: self._goto(self._pages))

    def _button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "ghost")
        button.setToolTip(tooltip)
        button.setFixedHeight(28)
        return button

    def _goto(self, page: int) -> None:
        target = max(1, min(int(page), self._pages))
        if target != self._page:
            self.pageChanged.emit(target)

    def set_persian_digits(self, enabled: bool) -> None:
        self._persian = enabled
        self._render()

    def update_page(self, page: Page) -> None:
        self._page = page.page
        self._pages = page.pages
        self._total = page.total
        self._render()

    def _render(self) -> None:
        digits = to_display_digits
        self.page_label.setText(
            f"صفحه {digits(str(self._page), self._persian)} از "
            f"{digits(str(self._pages), self._persian)}")
        self.summary.setText(
            digits(f"{self._total:,} رکورد", self._persian) if self._total else "بدون رکورد")
        self.first_button.setEnabled(self._page > 1)
        self.previous_button.setEnabled(self._page > 1)
        self.next_button.setEnabled(self._page < self._pages)
        self.last_button.setEnabled(self._page < self._pages)
