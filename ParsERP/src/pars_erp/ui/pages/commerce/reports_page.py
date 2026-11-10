"""Management reports: purchases, sales, inventory and persons."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.commerce_reports_service import ReportPeriod, ReportTable
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

#: report key → (title, needs a period, grouping options)
REPORT_CHOICES: tuple[tuple[str, str, bool, tuple[tuple[str, str], ...]], ...] = (
    ("purchase_monthly", "خرید ماهانه", True, ()),
    ("purchase_daily", "خرید روزانه", True, ()),
    ("purchase_yearly", "خرید سالانه", True, ()),
    ("purchase_supplier", "خرید به تفکیک تأمین‌کننده", True, ()),
    ("purchase_product", "خرید به تفکیک کالا", True, ()),
    ("sales_monthly", "فروش ماهانه", True, ()),
    ("sales_daily", "فروش روزانه", True, ()),
    ("sales_yearly", "فروش سالانه", True, ()),
    ("sales_customer", "فروش به تفکیک مشتری", True, ()),
    ("sales_category", "فروش به تفکیک گروه کالا", True, ()),
    ("sales_product", "فروش به تفکیک کالا", True, ()),
    ("best_sellers", "پرفروش‌ترین کالاها", True, ()),
    ("slow_movers", "کالاهای کم‌گردش", True, ()),
    ("discounts", "گزارش تخفیف‌ها", True, ()),
    ("stock_value", "ارزش موجودی", False, ()),
    ("low_stock", "کالاهای زیر نقطهٔ سفارش", False, ()),
    ("idle_stock", "کالاهای راکد", False, ()),
    ("transfers", "انتقال‌های انبار", True, ()),
    ("count_discrepancies", "مغایرت‌های انبارگردانی", True, ()),
    ("person_turnover", "گردش خرید و فروش اشخاص", True, ()),
    ("debtors", "بدهکاران (مانده مشتریان)", False, ()),
    ("creditors", "بستانکاران (مانده تأمین‌کنندگان)", False, ()),
)


class CommerceReportsPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.current: ReportTable | None = None
        self.header = PageHeader("گزارش‌های بازرگانی",
                                 "خرید، فروش، موجودی و اشخاص با فیلتر تاریخ، چاپ و Excel/PDF")
        self.header.add_action("نمایش گزارش", slot=self._run)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)

        controls = CardPanel("انتخاب گزارش")
        row = QHBoxLayout()
        self.report_combo = QComboBox()
        for key, title, _needs_period, _options in REPORT_CHOICES:
            self.report_combo.addItem(title, key)
        self.report_combo.currentIndexChanged.connect(self._run)
        row.addWidget(form_row("گزارش", self.report_combo), 2)
        today = _dt.date.today()
        self.from_edit = JalaliDateEdit(_dt.date(today.year, 1, 1))
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(today)
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        controls.add_layout(row)
        self.root.addWidget(controls)

        self.table = DataTable((ColumnSpec("placeholder", "—", TEXT, None),),
                               formatter=self.formatter)
        card = CardPanel("نتیجه")
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("HintText")
        card.add_header_widget(self.meta_label)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self._run()

    def _period(self) -> ReportPeriod:
        return ReportPeriod(self.from_edit.date() or _dt.date.today(),
                            self.to_edit.date() or _dt.date.today())

    def _build(self) -> ReportTable:
        key = str(self.report_combo.currentData())
        reports = self.services.commerce_reports
        period = self._period()
        mapping = {
            "purchase_monthly": lambda: reports.purchase_summary(
                self.ctx, period, group_by="monthly"),
            "purchase_daily": lambda: reports.purchase_summary(
                self.ctx, period, group_by="daily"),
            "purchase_yearly": lambda: reports.purchase_summary(
                self.ctx, period, group_by="yearly"),
            "purchase_supplier": lambda: reports.purchase_summary(
                self.ctx, period, group_by="supplier"),
            "purchase_product": lambda: reports.purchase_by_product(self.ctx, period),
            "sales_monthly": lambda: reports.sales_summary(
                self.ctx, period, group_by="monthly"),
            "sales_daily": lambda: reports.sales_summary(
                self.ctx, period, group_by="daily"),
            "sales_yearly": lambda: reports.sales_summary(
                self.ctx, period, group_by="yearly"),
            "sales_customer": lambda: reports.sales_summary(
                self.ctx, period, group_by="customer"),
            "sales_category": lambda: reports.sales_summary(
                self.ctx, period, group_by="category"),
            "sales_product": lambda: reports.sales_by_product(self.ctx, period),
            "best_sellers": lambda: reports.best_sellers(self.ctx, period),
            "slow_movers": lambda: reports.slow_movers(self.ctx, period),
            "discounts": lambda: reports.discount_report(self.ctx, period),
            "stock_value": lambda: reports.stock_value(self.ctx),
            "low_stock": lambda: reports.low_stock(self.ctx),
            "idle_stock": lambda: reports.idle_stock(self.ctx),
            "transfers": lambda: reports.transfers(self.ctx, period),
            "count_discrepancies": lambda: reports.count_discrepancies(self.ctx, period),
            "person_turnover": lambda: reports.person_turnover(self.ctx, period),
            "debtors": lambda: reports.person_balances(self.ctx, role="customer"),
            "creditors": lambda: reports.person_balances(self.ctx, role="supplier"),
        }
        return mapping[key]()

    def _run(self) -> None:
        try:
            table = self._build()
        except AppError as error:
            show_error(self, "گزارش", error)
            return
        columns = tuple(ColumnSpec(f"c{index}", title,
                                   "amount" if index else TEXT,
                                   None if index == 0 else 130,
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

    def _renderer(self):
        from pars_erp.services.report_render_service import ReportRenderer

        snapshot = self.services.settings.snapshot()
        return ReportRenderer(app_name=snapshot.app_name,
                              persian_digits=snapshot.persian_digits)

    def _render_table(self):
        from pars_erp.services.report_render_service import ReportColumn, ReportTable

        if self.current is None:
            return None
        columns = tuple(ReportColumn(f"c{index}", title, height_kind(title), 1.0)
                        for index, title in enumerate(self.current.columns))
        snapshot = self.services.settings.snapshot()
        return ReportTable(title=self.current.title_fa, columns=columns,
                           rows=self.current.rows,
                           company=snapshot.company_name,
                           currency_code=snapshot.currency_code,
                           meta=(self.current.meta_fa,),
                           totals=self.current.totals())

    def _print(self) -> None:
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        table = self._render_table()
        if table is None:
            show_info(self, "چاپ", "ابتدا یک گزارش نمایش دهید.")
            return
        ReportPreviewDialog(table, self._renderer(), parent=self).exec()

    def _excel(self) -> None:
        table = self._render_table()
        if table is None:
            show_info(self, "Excel", "ابتدا یک گزارش نمایش دهید.")
            return
        self.services.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.services.paths.exports_dir / (
            f"commerce_report_{_dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        try:
            outcome = self._renderer().to_excel(table, path)
        except AppError as error:
            show_error(self, "خروجی Excel", error)
            return
        show_info(self, "خروجی Excel", outcome.message_fa, tone="success")


def height_kind(title: str) -> str:
    from pars_erp.services.report_render_service import KIND_AMOUNT, KIND_TEXT

    money_words = ("مبلغ", "ارزش", "تخفیف", "مالیات", "بهای", "سود", "مانده", "خرید",
                   "فروش", "برگشت", "خالص", "بدهکار", "بستانکار")
    if any(word in title for word in money_words):
        return KIND_AMOUNT
    return KIND_TEXT
