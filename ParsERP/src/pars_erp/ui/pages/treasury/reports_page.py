"""Treasury reports: fund flow (گردش وجوه) and the full treasury report set."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from pars_erp.core.errors import AppError
from pars_erp.services.commerce_reports_service import ReportPeriod, ReportTable
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    FundPicker,
    export_excel,
    form_row,
    show_preview,
)
from pars_erp.ui.table_specs import TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

#: key → (title, needs fund, needs direction)
REPORT_CHOICES = (
    ("bank_ledger", "گردش حساب بانکی", True, False),
    ("cash_ledger", "گردش صندوق", True, False),
    ("bank_balances", "مانده حساب‌های بانکی", False, False),
    ("cash_balances", "مانده صندوق‌ها", False, False),
    ("cheques_received", "چک‌های دریافتی", False, True),
    ("cheques_issued", "چک‌های پرداختی", False, True),
    ("cheques_due", "چک‌های نزدیک سررسید", False, False),
    ("person_receipt", "دریافت از اشخاص", False, False),
    ("person_payment", "پرداخت به اشخاص", False, False),
    ("open_receipt", "فاکتورهای تسویه‌نشده (مطالبات)", False, False),
    ("open_payment", "فاکتورهای تسویه‌نشده (بدهی‌ها)", False, False),
    ("cash_flow", "جریان نقدی روزانه", False, False),
    ("forecast", "پیش‌بینی جریان نقدی", False, False),
    ("liquidity", "نقدینگی و پیش‌بینی", False, False),
)


class _ReportBase(PageBase):
    title_fa = "گزارش"
    subtitle_fa = ""
    choices = REPORT_CHOICES

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.current: ReportTable | None = None
        self.header = PageHeader(self.title_fa, self.subtitle_fa)
        self.header.add_action("نمایش گزارش", slot=self._run)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)

        bar = CardPanel("انتخاب گزارش")
        row = QHBoxLayout()
        self.report_combo = QComboBox()
        for key, title, _fund, _direction in self.choices:
            self.report_combo.addItem(title, key)
        self.report_combo.currentIndexChanged.connect(lambda _i: self._sync_filters())
        row.addWidget(form_row("گزارش", self.report_combo), 2)
        today = _dt.date.today()
        self.from_edit = JalaliDateEdit(today.replace(month=1, day=1))
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(today)
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        bar.add_layout(row)
        row2 = QHBoxLayout()
        self.fund_picker = FundPicker()
        row2.addWidget(self.fund_picker, 2)
        self.direction_combo = QComboBox()
        for code, title in TC.CHEQUE_DIRECTIONS:
            self.direction_combo.addItem(title, code)
        row2.addWidget(form_row("نوع چک", self.direction_combo), 1)
        self.days_edit = QComboBox()
        for days in (7, 14, 30, 60, 90):
            self.days_edit.addItem(f"{days} روز", days)
        self.days_edit.setCurrentIndex(2)
        row2.addWidget(form_row("افق (روز)", self.days_edit), 1)
        bar.add_layout(row2)
        self.root.addWidget(bar)

        self.table = DataTable((ColumnSpec("c0", "—", TEXT, None),), formatter=formatter)
        card = CardPanel("نتیجه")
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("HintText")
        card.add_header_widget(self.meta_label)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.fund_picker.attach(services, ctx)
        self._sync_filters()
        self._run()

    # ------------------------------------------------------------------ build
    def _period(self) -> ReportPeriod:
        today = _dt.date.today()
        return ReportPeriod(self.from_edit.date() or today.replace(month=1, day=1),
                            self.to_edit.date() or today)

    def _sync_filters(self) -> None:
        key = str(self.report_combo.currentData())
        choice = next(entry for entry in self.choices if entry[0] == key)
        _key, _title, needs_fund, needs_direction = choice
        self.fund_picker.setEnabled(needs_fund)
        self.direction_combo.setEnabled(needs_direction)
        self.days_edit.setEnabled(key in ("cheques_due", "forecast"))

    def _build(self) -> ReportTable:
        key = str(self.report_combo.currentData())
        reports = self.services.treasury_reports
        period = self._period()
        fund_id = self.fund_picker.fund_id()
        is_cash = self.fund_picker.kind() == TC.FUND_CASH
        days = int(self.days_edit.currentData())
        mapping = {
            "bank_ledger": lambda: reports.bank_ledger(
                self.ctx, period, None if is_cash else fund_id),
            "cash_ledger": lambda: reports.cash_ledger(
                self.ctx, period, fund_id if is_cash else None),
            "bank_balances": lambda: reports.bank_balances(self.ctx),
            "cash_balances": lambda: reports.cash_balances(self.ctx),
            "cheques_received": lambda: reports.cheques(
                self.ctx, period, direction=TC.CHEQUE_RECEIVED),
            "cheques_issued": lambda: reports.cheques(
                self.ctx, period, direction=TC.CHEQUE_ISSUED),
            "cheques_due": lambda: reports.cheques_due(self.ctx, days=days),
            "person_receipt": lambda: reports.person_flows(self.ctx, period,
                                                           kind="receipt"),
            "person_payment": lambda: reports.person_flows(self.ctx, period,
                                                           kind="payment"),
            "open_receipt": lambda: reports.open_invoices(self.ctx, period,
                                                          direction="receipt"),
            "open_payment": lambda: reports.open_invoices(self.ctx, period,
                                                          direction="payment"),
            "cash_flow": lambda: reports.cash_flow(self.ctx, period),
            "forecast": lambda: reports.forecast(self.ctx, days=days),
            "liquidity": lambda: self._liquidity(period, days),
        }
        return mapping[key]()

    def _liquidity(self, period: ReportPeriod, days: int) -> ReportTable:
        from pars_erp.services.commerce_reports_service import ReportTable

        figures = self.services.treasury_dashboard.figures(self.ctx, period)
        forecast = self.services.treasury_reports.forecast(self.ctx, days=days)
        incoming = sum((row[3] for row in forecast.rows if row[3] > 0),
                       figures.cash_total * 0)
        outgoing = sum((-row[3] for row in forecast.rows if row[3] < 0),
                       figures.cash_total * 0)
        available = figures.cash_total + figures.bank_total
        rows = (
            ("موجودی صندوق‌ها", figures.cash_total),
            ("موجودی حساب‌های بانکی", figures.bank_total),
            ("جمع نقدینگی", available),
            ("ورودی پیش‌بینی‌شده", incoming),
            ("خروجی پیش‌بینی‌شده", outgoing),
            ("نقدینگی پیش‌بینی‌شده", available + incoming - outgoing),
            ("دریافتی دوره", figures.receipts_period),
            ("پرداختی دوره", figures.payments_period),
            ("خالص دوره", figures.net_flow),
        )
        return ReportTable("liquidity", "گزارش نقدینگی", ("شرح", "مبلغ"), rows,
                           f"از {period.date_from} تا {period.date_to} — افق {days} روز")

    # ------------------------------------------------------------------- show
    def _run(self) -> None:
        try:
            table = self._build()
        except AppError as error:
            show_error(self, "گزارش", error)
            return
        columns = tuple(ColumnSpec(f"c{index}", title,
                                   "text" if index == 0 else "amount",
                                   None if index == 0 else 140,
                                   "right" if index == 0 else "center")
                        for index, title in enumerate(table.columns))
        self.table.set_columns(columns)
        self.table.set_rows([
            {f"c{index}": (row[index] if index < len(row) else "")
             for index in range(len(columns))}
            for row in table.rows])
        self.current = table
        self.meta_label.setText(f"{table.title_fa} | {table.meta_fa} | "
                                f"{table.row_count:,} ردیف")

    def _render_table(self):
        from pars_erp.services.report_render_service import (
            KIND_AMOUNT,
            KIND_TEXT,
            ReportColumn,
            ReportTable,
        )

        if self.current is None:
            return None
        columns = tuple(ReportColumn(f"c{index}", title,
                                     KIND_TEXT if index == 0 else KIND_AMOUNT)
                        for index, title in enumerate(self.current.columns))
        snapshot = self.services.settings.snapshot()
        return ReportTable(title=self.current.title_fa, columns=columns,
                           rows=self.current.rows, company=snapshot.company_name,
                           currency_code=snapshot.currency_code,
                           meta=(self.current.meta_fa,), totals=self.current.totals())

    def _print(self) -> None:
        table = self._render_table()
        if table is None:
            show_info(self, "چاپ", "ابتدا یک گزارش نمایش دهید.")
            return
        show_preview(self, self.services, table)

    def _excel(self) -> None:
        table = self._render_table()
        if table is None:
            show_info(self, "Excel", "ابتدا یک گزارش نمایش دهید.")
            return
        export_excel(self, self.services, table, prefix="treasury_report")


class TreasuryReportsPage(_ReportBase):
    title_fa = "گزارش خزانه‌داری"
    subtitle_fa = ("بانک، صندوق، چک، اشخاص و نقدینگی با فیلتر تاریخ، چاپ، PDF و Excel")


class FundFlowPage(_ReportBase):
    title_fa = "گزارش گردش وجوه"
    subtitle_fa = "گردش صندوق و بانک، جریان نقدی روزانه و پیش‌بینی سررسیدها"
    choices = (
        ("bank_ledger", "گردش حساب بانکی", True, False),
        ("cash_ledger", "گردش صندوق", True, False),
        ("cash_flow", "جریان نقدی روزانه", False, False),
        ("forecast", "پیش‌بینی جریان نقدی", False, False),
        ("liquidity", "نقدینگی و پیش‌بینی", False, False),
    )
