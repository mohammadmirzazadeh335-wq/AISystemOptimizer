"""Management dashboard: KPI cards and charts, every number from the database.

The page draws only what :class:`ManagementDashboardService` returns; a card that
the caller may not see is not created at all, and an empty module produces no
chart instead of a flat line at zero pretending to be data.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.core.money import format_amount
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.ui.dialogs.common_dialogs import show_error
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.widgets.common import BarChart, KpiCard


class ManagementDashboardPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate

        self.header = PageHeader("داشبورد مدیریتی",
                                 "تصویر واقعی کسب‌وکار از اسناد ثبت‌شدهٔ پایگاه داده")
        self.header.add_action("بازخوانی", slot=self.refresh)
        self.header.add_action("مرکز گزارش‌ها", variant="ghost",
                               slot=lambda: self._navigate("report_center"))
        self.root.addWidget(self.header)

        filters = QHBoxLayout()
        today = _dt.date.today()
        self.date_from = JalaliDateEdit(today.replace(day=1),
                                        persian_digits=formatter.persian_digits)
        self.date_to = JalaliDateEdit(today, persian_digits=formatter.persian_digits)
        filters.addWidget(QLabel("از تاریخ:"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("تا تاریخ:"))
        filters.addWidget(self.date_to)
        filters.addStretch(1)
        self.root.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)

        self.empty_label = QLabel("")
        self.empty_label.setObjectName("HintText")
        self.empty_label.setWordWrap(True)
        content.addWidget(self.empty_label)

        self.cards_layout = QGridLayout()
        self.cards_layout.setSpacing(12)
        content.addLayout(self.cards_layout)

        self.charts_layout = QGridLayout()
        self.charts_layout.setSpacing(14)
        content.addLayout(self.charts_layout)
        content.addStretch(1)
        scroll.setWidget(container)
        self.root.addWidget(scroll, 1)

        self._cards: list[KpiCard] = []
        self._charts: list[tuple[CardPanel, BarChart]] = []

    def refresh(self) -> None:
        period = ReportPeriod(self.date_from.date(), self.date_to.date())
        try:
            dashboard = self.services.management_dashboard.overview(self.ctx, period=period)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._render(dashboard)

    def _render(self, dashboard) -> None:
        for card in self._cards:
            card.setParent(None)
        for panel, _chart in self._charts:
            panel.setParent(None)
        self._cards.clear()
        self._charts.clear()

        if not dashboard.cards and not dashboard.charts:
            self.empty_label.setText(
                "برای نقش شما هیچ کارت یا نموداری مجاز نیست. مجوزهای گزارش‌ها را "
                "با مدیر سیستم بررسی کنید.")
            return
        self.empty_label.setText("")

        for index, card in enumerate(dashboard.cards):
            tile = KpiCard(
                card.title_fa, self._value_text(card), self._hint_text(card),
                tone=self._tone(card))
            if card.link_page and self._on_navigate is not None:
                page = card.link_page
                tile.clicked.connect(lambda page=page: self._navigate(page))
            self.cards_layout.addWidget(tile, index // 4, index % 4)
            self._cards.append(tile)

        for index, chart in enumerate(dashboard.charts):
            panel = CardPanel(chart.title_fa, chart.note_fa)
            widget = BarChart()
            widget.setMinimumHeight(170)
            persian = self.services.settings.snapshot().bool("persian_digits")
            widget.set_digits(persian)
            widget.set_data([bar.label_fa for bar in chart.bars],
                            [int(bar.value) for bar in chart.bars])
            panel.add(widget, 1)
            self.charts_layout.addWidget(panel, index // 2, index % 2)
            self._charts.append((panel, widget))

    # ---------------------------------------------------------------- helpers
    def _value_text(self, card) -> str:
        if card.kind == "amount":
            return format_amount(card.value, self.services.settings.snapshot().currency_code,
                                 persian_digits=self.formatter.persian_digits,
                                 with_symbol=True)
        text = f"{int(card.value):,}"
        return text

    @staticmethod
    def _hint_text(card) -> str:
        hint = card.subtitle_fa
        if card.delta_percent is not None:
            hint = f"{hint} · تغییر {card.delta_percent}٪".strip(" ·")
        if card.link_hint_fa:
            hint = f"{hint} — {card.link_hint_fa}".strip(" —")
        return hint

    @staticmethod
    def _tone(card) -> str:
        if card.key in ("payables", "cheques_due", "alerts_open"):
            return "warning"
        if card.key in ("receivables", "net_flow"):
            return "info"
        if card.key in ("gross_profit", "sales_month", "sales_today"):
            return "success"
        return "primary"

    def _navigate(self, key: str) -> None:
        if self._on_navigate is not None:
            self._on_navigate(key)
