"""Treasury dashboard: balances, today's documents, cheques and the trend."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pars_erp.core.errors import AppError
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.ui.dialogs.common_dialogs import show_error
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import form_row
from pars_erp.ui.table_specs import AMOUNT, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

TODAY_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "سند", TEXT, 130, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 90, "center"),
    ColumnSpec("party_name", "طرف حساب", TEXT, None),
    ColumnSpec("amount", "مبلغ", AMOUNT, 140),
    ColumnSpec("status_fa", "وضعیت", TEXT, 130, "center"),
)

WATCH_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("due_date", "سررسید", DATE, 96, "center"),
    ColumnSpec("number", "شماره چک", TEXT, 110, "center"),
    ColumnSpec("direction_fa", "نوع", TEXT, 110, "center"),
    ColumnSpec("party_name", "شخص", TEXT, None),
    ColumnSpec("amount", "مبلغ", AMOUNT, 130),
    ColumnSpec("days_left", "روز باقی‌مانده", TEXT, 110, "center"),
    ColumnSpec("status_fa", "وضعیت", TEXT, 130, "center"),
)

TREND_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("day", "تاریخ", DATE, 110, "center"),
    ColumnSpec("inflow", "ورودی", AMOUNT, 150),
    ColumnSpec("outflow", "خروجی", AMOUNT, 150),
    ColumnSpec("net", "خالص", AMOUNT, 150),
)


class KpiCard(QWidget):
    """One headline figure with a Persian title and an optional caption."""

    def __init__(self, title: str, value: str = "—", caption: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("HintText")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("SectionTitle")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("HintText")
        for widget in (self.title_label, self.value_label, self.caption_label):
            widget.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(widget)

    def set_values(self, value: str, caption: str = "") -> None:
        self.value_label.setText(value)
        self.caption_label.setText(caption)


class TreasuryDashboardPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader(
            "داشبورد خزانه‌داری",
            "موجودی صندوق‌ها و بانک‌ها، دریافتی و پرداختی امروز، چک‌های در جریان و "
            "مطالبات معوق — همه از اسناد ثبت‌شده")
        self.header.add_action("بازخوانی", slot=self.refresh)
        self.root.addWidget(self.header)

        bar = CardPanel("بازه گزارش")
        row = QHBoxLayout()
        today = _dt.date.today()
        self.from_edit = JalaliDateEdit(today.replace(day=1))
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(today)
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        apply_button = self.header.add_action("اعمال بازه", variant="secondary",
                                              slot=self.refresh)
        row.addStretch(1)
        bar.add_layout(row)
        self.root.addWidget(bar)
        self.apply_button = apply_button

        kpis = QGridLayout()
        kpis.setSpacing(10)
        self.cards = {
            "cash": KpiCard("موجودی صندوق‌ها"),
            "bank": KpiCard("موجودی حساب‌های بانکی"),
            "total": KpiCard("جمع نقدینگی"),
            "today_in": KpiCard("دریافتی امروز"),
            "today_out": KpiCard("پرداختی امروز"),
            "period_net": KpiCard("خالص دوره"),
            "due": KpiCard("چک نزدیک سررسید"),
            "overdue": KpiCard("مطالبات/بدهی‌های معوق"),
        }
        for index, card in enumerate(self.cards.values()):
            kpis.addWidget(card, index // 4, index % 4)
        self.root.addLayout(kpis)

        tables = QHBoxLayout()
        today_card = CardPanel("اسناد امروز")
        self.today_table = DataTable(TODAY_COLUMNS, formatter=formatter)
        today_card.add(self.today_table, 1)
        tables.addWidget(today_card, 1)
        watch_card = CardPanel("چک‌های در جریان و نزدیک سررسید")
        self.watch_table = DataTable(WATCH_COLUMNS, formatter=formatter)
        watch_card.add(self.watch_table, 1)
        tables.addWidget(watch_card, 1)
        self.root.addLayout(tables, 2)

        trend_card = CardPanel("دریافتی در مقابل پرداختی (به تفکیک روز)")
        self.trend_table = DataTable(TREND_COLUMNS, formatter=formatter)
        trend_card.add(self.trend_table, 1)
        self.root.addWidget(trend_card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def _period(self) -> ReportPeriod:
        today = _dt.date.today()
        return ReportPeriod(self.from_edit.date() or today.replace(day=1),
                            self.to_edit.date() or today)

    def refresh(self) -> None:
        try:
            period = self._period()
            figures = self.services.treasury_dashboard.figures(self.ctx, period)
            series = self.services.treasury_dashboard.receipts_vs_payments(self.ctx, period)
            today_rows = self.services.treasury_dashboard.today_documents(self.ctx)
            watch = self.services.treasury_dashboard.watch_cheques(self.ctx, days=14)
        except AppError as error:
            show_error(self, "داشبورد خزانه‌داری", error)
            return
        currency = self.services.settings.snapshot().currency_code
        self.cards["cash"].set_values(f"{figures.cash_total:,} {currency}")
        self.cards["bank"].set_values(f"{figures.bank_total:,} {currency}")
        self.cards["total"].set_values(f"{figures.cash_total + figures.bank_total:,} "
                                       f"{currency}")
        self.cards["today_in"].set_values(f"{figures.receipts_today:,} {currency}",
                                          f"دوره: {figures.receipts_period:,}")
        self.cards["today_out"].set_values(f"{figures.payments_today:,} {currency}",
                                           f"دوره: {figures.payments_period:,}")
        self.cards["period_net"].set_values(f"{figures.net_flow:,} {currency}",
                                            "دریافتی منهای پرداختی")
        self.cards["due"].set_values(f"{figures.cheques_due_soon:,} چک",
                                     f"چک در جریان دریافتی: "
                                     f"{figures.receipts_open_cheques:,}")
        self.cards["overdue"].set_values(
            f"{figures.overdue_receivables:,} / {figures.overdue_payables:,}",
            "مطالبات معوق / بدهی معوق")
        self.today_table.set_rows(list(today_rows))
        self.watch_table.set_rows(list(watch))
        self.trend_table.set_rows([{"day": point.day, "inflow": point.inflow,
                                    "outflow": point.outflow, "net": point.net}
                                   for point in series])
