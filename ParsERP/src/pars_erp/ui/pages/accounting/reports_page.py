"""Financial reports: journal book, ledgers, turnover, trial balance, statements.

Every report page follows one path: the service computes the numbers, the page
converts them into a :class:`ReportTable`, and *that* object feeds the grid on
screen, the print preview, the PDF and the Excel file. One source of truth means
a figure cannot differ between the screen and the exported file.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.core.money import format_amount
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_NUMBER,
    KIND_TEXT,
    ReportColumn,
    ReportRenderer,
    ReportTable,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui import report_tables
from pars_erp.ui.pages.accounting.widgets import AccountPicker, JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AMOUNT, DATE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.pagination import PaginationBar
from pars_erp.ui.widgets.table import DataTable

_KIND_TO_SPEC = {KIND_TEXT: TEXT, KIND_AMOUNT: AMOUNT, KIND_NUMBER: NUMBER, KIND_DATE: DATE}


def _specs(table: ReportTable) -> tuple[ColumnSpec, ...]:
    return tuple(
        ColumnSpec(column.key, column.title_fa, _KIND_TO_SPEC.get(column.kind, TEXT),
                   max(70, int(column.width * 96)) if column.width < 6 else None,
                   "left" if column.kind in (KIND_AMOUNT, KIND_NUMBER) else "right")
        for column in table.columns)


class ReportPageBase(PageBase):
    """Shared shell: filters, grid, totals and the three export buttons."""

    title_fa = "گزارش"
    subtitle_fa = ""

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._report: ReportTable | None = None
        self._page_no = 1

        self.header = PageHeader(self.title_fa, self.subtitle_fa)
        self.header.add_action("نمایش", slot=self.refresh, tooltip="محاسبه مجدد گزارش")
        self.header.add_action("پیش‌نمایش چاپ", variant="ghost", slot=self._preview)
        self.header.add_action("خروجی PDF", variant="ghost", slot=lambda: self._export("pdf"))
        self.header.add_action("خروجی Excel", variant="ghost", slot=lambda: self._export("xlsx"))
        self.root.addWidget(self.header)

        self.filters_card = CardPanel()
        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(8)
        self.filters_card.add_layout(self.filter_row)
        self.root.addWidget(self.filters_card)
        self.build_filters()

        self.table_card = CardPanel()
        self.table = DataTable((ColumnSpec("empty", "—"),), formatter=self.formatter)
        self.table_card.add(self.table, 1)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SectionTitle")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.table_card.add(self.summary_label)
        self.pagination = PaginationBar()
        self.pagination.pageChanged.connect(self._on_page_changed)
        self.pagination.setVisible(False)  # only paged reports (روزنامه) show it
        self.table_card.add(self.pagination)
        self.root.addWidget(self.table_card, 1)

        self.date_from = None
        self.date_to = None

    # ------------------------------------------------------------------ setup
    def build_filters(self) -> None:  # pragma: no cover - overridden
        """Fill ``self.filter_row`` with the report's own filters."""

    def add_date_range(self, *, default_year: int | None = None) -> None:
        today = _dt.date.today()
        # default window = current Jalali fiscal year (Farvardin 1 … today)
        try:
            from pars_erp.core.jalali import JalaliDate, jalali_year_range

            start, _year_end = jalali_year_range(JalaliDate.today().year)
        except Exception:  # pragma: no cover - defensive
            start = _dt.date(today.year, 1, 1)
        try:
            active = self.services.periods.active_period(self.ctx)
            if active is not None:
                start, today = active.start_date, min(today, active.end_date)
        except AppError:
            pass
        self.date_from = JalaliDateEdit(start, persian_digits=self.formatter.persian_digits)
        self.date_to = JalaliDateEdit(today, persian_digits=self.formatter.persian_digits)
        self.register_filter("از تاریخ", self.date_from)
        self.register_filter("تا تاریخ", self.date_to)

    def register_filter(self, label: str, widget: QWidget) -> None:
        if label:
            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            self.filter_row.addWidget(caption)
        self.filter_row.addWidget(widget)

    def add_stretch(self) -> None:
        self.filter_row.addStretch(1)

    def on_filter_changed(self, *_args) -> None:
        if not hasattr(self, "table"):
            return  # a filter fired while the page was still being built
        self._page_no = 1
        self.refresh()

    def _on_page_changed(self, page: int) -> None:
        self._page_no = page
        self.refresh()

    # ------------------------------------------------------------------- data
    def build_report(self) -> ReportTable:  # pragma: no cover - overridden
        raise NotImplementedError

    def refresh(self) -> None:
        try:
            report = self.build_report()
        except AppError as error:
            show_error(self, self.title_fa, error)
            return
        self._report = report
        self.table.model.beginResetModel()
        self.table.model._columns = list(_specs(report))
        self.table.model.endResetModel()
        self.table.set_rows([dict(zip([column.key for column in report.columns], row))
                             for row in report.rows])
        self._apply_column_widths(report)
        self.summary_label.setText(self._summary_html(report))

    def _apply_column_widths(self, report: ReportTable) -> None:
        for index, column in enumerate(report.columns):
            width = int(column.width * 96)
            if width >= 70:
                self.table.setColumnWidth(index, width)

    def _summary_html(self, report: ReportTable) -> str:
        parts: list[str] = [f"<span>تعداد سطر: <b>{self.formatter.number(len(report.rows))}</b></span>"]
        if report.totals:
            for index, value in enumerate(report.totals):
                if isinstance(value, Decimal):
                    title = report.columns[index].title_fa if index < len(report.columns) else ""
                    parts.append(f"<span>{title}: <b>{self.formatter.amount(value)}</b></span>")
        return " · ".join(parts)

    # ---------------------------------------------------------------- exports
    def _renderer(self) -> ReportRenderer:
        snapshot = self.services.settings.snapshot()
        return ReportRenderer(app_name=snapshot.app_name,
                              persian_digits=self.formatter.persian_digits)

    def _preview(self) -> None:
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        if self._report is None:
            self.refresh()
        if self._report is None:
            return
        ReportPreviewDialog(self._report, self._renderer(), parent=self).exec()

    def _export(self, kind: str) -> None:
        if self._report is None:
            self.refresh()
        if self._report is None:
            return
        suffix = "pdf" if kind == "pdf" else "xlsx"
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیره خروجی", f"{self.title_fa}.{suffix}",
            "PDF (*.pdf)" if kind == "pdf" else "Excel (*.xlsx)")
        if not path:
            return
        try:
            renderer = self._renderer()
            if kind == "pdf":
                outcome = renderer.to_pdf(self._report, Path(path))
            else:
                outcome = renderer.to_excel(self._report, Path(path))
        except AppError as error:
            show_error(self, "خروجی گزارش", error)
            return
        show_info(self, "خروجی گزارش", outcome.message_fa, tone="success")

    # --------------------------------------------------------------- helpers
    def _period_of(self) -> tuple[_dt.date, _dt.date]:
        start = self.date_from.date() if self.date_from else None
        end = self.date_to.date() if self.date_to else None
        if start is None or end is None:
            active = self.services.periods.active_period(self.ctx)
            if active is not None:
                start = start or active.start_date
                end = end or active.end_date
        if start is None or end is None:
            today = _dt.date.today()
            start, end = start or _dt.date(today.year, 1, 1), end or today
        if start > end:
            start, end = end, start
        return start, end

    def _meta(self, start: _dt.date, end: _dt.date) -> tuple[str, ...]:
        company = ""
        try:
            company = self.services.settings.snapshot().company_name
        except AppError:
            company = ""
        snapshot_meta = (
            f"شرکت: {company}" if company else "شرکت: —",
            f"از {self.formatter.date(start)} تا {self.formatter.date(end)}",
            "مبنای گزارش: فقط اسناد ثبت‌نهایی‌شده",
        )
        return snapshot_meta


class JournalBookPage(ReportPageBase):
    title_fa = "دفتر روزنامه"
    subtitle_fa = "تمام سطرهای اسناد ثبت‌نهایی‌شده به ترتیب تاریخ و شماره سند"

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        self.search_input = SearchInput("جست‌وجو در شرح سند، ارجاع یا حساب…")
        self.account_picker = AccountPicker()
        super().__init__(services, ctx, formatter, parent=parent)

    def build_filters(self) -> None:
        self.add_date_range()
        self.search_input.searchChanged.connect(self.on_filter_changed)
        self.register_filter("جست‌وجو", self.search_input)
        self.account_picker.setMinimumWidth(260)
        self.account_picker.accountChanged.connect(self.on_filter_changed)
        self.register_filter("حساب", self.account_picker)
        self.add_stretch()
        try:
            self.account_picker.load(
                [(account_id, label) for account_id, label
                 in self.services.accounts.choices(self.ctx, level=None)],
                placeholder="— همه حساب‌ها —")
        except AppError:
            pass

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        table, page = report_tables.journal_book_table(
            self.services, self.ctx, self.formatter, start=start, end=end,
            account_id=self.account_picker.current_account_id(),
            search=self.search_input.text().strip() or None,
            page=self._page_no, page_size=200)
        self.pagination.setVisible(True)
        self.pagination.update_page(page)
        return table


class GeneralLedgerPage(ReportPageBase):
    title_fa = "دفتر کل"
    subtitle_fa = "مانده ابتدای دوره، گردش و مانده پایان دوره به تفکیک حساب"

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        self.level_combo = QComboBox()
        super().__init__(services, ctx, formatter, parent=parent)

    def build_filters(self) -> None:
        self.add_date_range()
        for level in C.ACCOUNT_LEVELS:
            self.level_combo.addItem(C.LEVEL_TITLES_FA[level], level)
        self.level_combo.setCurrentIndex(max(0, self.level_combo.findData(C.LEVEL_SUBSIDIARY)))
        self.level_combo.currentIndexChanged.connect(self.on_filter_changed)
        self.register_filter("سطح حساب", self.level_combo)
        self.add_stretch()

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        return report_tables.general_ledger_table(
            self.services, self.ctx, self.formatter, start=start, end=end,
            level=self.level_combo.currentData())


class SubsidiaryLedgerPage(ReportPageBase):
    title_fa = "دفتر معین"
    subtitle_fa = "ریز گردش یک حساب با ماندهٔ جاری (گردش حساب)"

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        self.account_picker = AccountPicker()
        self.detail_picker = QComboBox()
        super().__init__(services, ctx, formatter, parent=parent)

    def build_filters(self) -> None:
        self.add_date_range()
        self.account_picker.setMinimumWidth(300)
        self.account_picker.accountChanged.connect(self._reload_details)
        self.register_filter("حساب معین", self.account_picker)
        self.detail_picker.setMinimumWidth(180)
        self.detail_picker.currentIndexChanged.connect(self.on_filter_changed)
        self.register_filter("تفصیلی", self.detail_picker)
        self.add_stretch()
        try:
            choices = self.services.accounts.choices(self.ctx)
            self.account_picker.load(choices, placeholder="— انتخاب حساب —")
            if choices:
                # preselect the first معین so the page shows data immediately
                self.account_picker.blockSignals(True)
                self.account_picker.set_account(choices[0][0])
                self.account_picker.blockSignals(False)
                self._reload_details(choices[0][0])
        except AppError:
            pass

    def _reload_details(self, account_id) -> None:
        self.detail_picker.blockSignals(True)
        self.detail_picker.clear()
        self.detail_picker.addItem("— همه تفصیلی‌ها —", None)
        if account_id:
            try:
                for detail_id, label in self.services.parties.choices(self.ctx, account_id):
                    self.detail_picker.addItem(label, detail_id)
            except AppError:
                pass
        self.detail_picker.blockSignals(False)
        self.on_filter_changed()

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        return report_tables.subsidiary_ledger_table(
            self.services, self.ctx, self.formatter,
            account_id=self.account_picker.current_account_id(), start=start, end=end,
            detail_id=self.detail_picker.currentData())


class TurnoverPage(ReportPageBase):
    title_fa = "گردش حساب‌ها"
    subtitle_fa = "گردش بدهکار/بستانکار و مانده هر حساب در بازهٔ انتخابی"

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        self.level_combo = QComboBox()
        super().__init__(services, ctx, formatter, parent=parent)

    def build_filters(self) -> None:
        self.add_date_range()
        for level in C.ACCOUNT_LEVELS:
            self.level_combo.addItem(C.LEVEL_TITLES_FA[level], level)
        self.level_combo.setCurrentIndex(
            max(0, self.level_combo.findData(C.LEVEL_SUBSIDIARY)))
        self.level_combo.currentIndexChanged.connect(self.on_filter_changed)
        self.register_filter("سطح", self.level_combo)
        self.add_stretch()

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        return report_tables.turnover_table(
            self.services, self.ctx, self.formatter, start=start, end=end,
            level=self.level_combo.currentData())


class TrialBalancePage(ReportPageBase):
    title_fa = "تراز آزمایشی"
    subtitle_fa = "تراز دو، چهار و شش‌ستونی از اسناد ثبت‌نهایی‌شده"

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        self.mode_combo = QComboBox()
        self.level_combo = QComboBox()
        super().__init__(services, ctx, formatter, parent=parent)

    def build_filters(self) -> None:
        self.add_date_range()
        for mode in (2, 4, 6):
            self.mode_combo.addItem(f"{mode} ستونی", mode)
        self.mode_combo.setCurrentIndex(2)
        self.mode_combo.currentIndexChanged.connect(self.on_filter_changed)
        self.register_filter("حالت", self.mode_combo)
        for level in C.ACCOUNT_LEVELS:
            self.level_combo.addItem(C.LEVEL_TITLES_FA[level], level)
        self.level_combo.setCurrentIndex(max(0, self.level_combo.findData(C.LEVEL_SUBSIDIARY)))
        self.level_combo.currentIndexChanged.connect(self.on_filter_changed)
        self.register_filter("سطح", self.level_combo)
        self.add_stretch()

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        return report_tables.trial_balance_table(
            self.services, self.ctx, self.formatter, start=start, end=end,
            mode=int(self.mode_combo.currentData() or 2),
            level=self.level_combo.currentData())


class _StatementPageBase(ReportPageBase):
    """Shared shell for the two financial statements."""


class BalanceSheetPage(_StatementPageBase):
    title_fa = "ترازنامه"
    subtitle_fa = "دارایی‌ها، بدهی‌ها و سرمایه در تاریخ انتخابی"

    def build_filters(self) -> None:
        today = _dt.date.today()
        try:
            active = self.services.periods.active_period(self.ctx)
            if active is not None:
                today = min(today, active.end_date)
        except AppError:
            pass
        self.as_of = JalaliDateEdit(today, persian_digits=self.formatter.persian_digits)
        self.as_of.dateChanged.connect(self.on_filter_changed)
        self.register_filter("در تاریخ", self.as_of)
        self.add_stretch()

    def build_report(self) -> ReportTable:
        as_of = self.as_of.date() or _dt.date.today()
        return report_tables.balance_sheet_table(
            self.services, self.ctx, self.formatter, as_of=as_of)


class IncomeStatementPage(_StatementPageBase):
    title_fa = "صورت سود و زیان"
    subtitle_fa = "درآمدها، بهای تمام‌شده و هزینه‌ها در بازهٔ انتخابی"

    def build_filters(self) -> None:
        self.add_date_range()
        self.add_stretch()

    def build_report(self) -> ReportTable:
        start, end = self._period_of()
        return report_tables.income_statement_table(
            self.services, self.ctx, self.formatter, start=start, end=end)
