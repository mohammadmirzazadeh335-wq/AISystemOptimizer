"""Turn a phase-5 ``ReportTable`` into a real screen.

The phase-5 report services return the phase-3/4 ``ReportTable`` (plain column
titles + row tuples). This module builds the *one* description of a report that
feeds the grid, the print preview and the Excel export, so what the accountant
sees is exactly what is printed.

Because the report services already applied permissions and computed every
figure from posted documents, nothing here does arithmetic - it only maps types
to display kinds and formats.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from pars_erp.core.errors import AppError
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.services.commerce_reports_service import ReportTable as DataReportTable
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_NUMBER,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AMOUNT, DATE, DATETIME, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

_RENDER_KIND = {AMOUNT: KIND_AMOUNT, DATE: KIND_DATE, DATETIME: KIND_DATE,
                NUMBER: KIND_NUMBER, TEXT: KIND_TEXT}


def kind_of(value) -> str:
    """Pick the display kind of a column from the first non-empty value."""
    if value is None:
        return TEXT
    if isinstance(value, bool):
        return TEXT
    if isinstance(value, _dt.datetime):
        return DATETIME
    if isinstance(value, _dt.date):
        return DATE
    if isinstance(value, Decimal):
        return AMOUNT
    if isinstance(value, int):
        return NUMBER
    return TEXT


def specs_for(table: DataReportTable) -> tuple[ColumnSpec, ...]:
    specs = []
    for index, title in enumerate(table.columns):
        sample = None
        for row in table.rows:
            if index < len(row) and row[index] is not None:
                sample = row[index]
                break
        kind = kind_of(sample)
        specs.append(ColumnSpec(
            f"c{index}", str(title), kind,
            None if kind == TEXT else 128,
            "right" if kind == TEXT else "center"))
    return tuple(specs)


def rows_for(table: DataReportTable) -> list[dict]:
    keys = [f"c{index}" for index in range(len(table.columns))]
    return [{key: (row[index] if index < len(row) else None)
             for index, key in enumerate(keys)} for row in table.rows]


def render_table(services, table: DataReportTable) -> ReportTable:
    """The printable version of a grid table (same rows, same totals)."""
    specs = specs_for(table)
    columns = tuple(
        ReportColumn(spec.key, spec.title_fa, _RENDER_KIND.get(spec.kind, KIND_TEXT))
        for spec in specs)
    totals = table.totals()
    totals_row = None
    if totals and any(value is not None for value in totals):
        totals_row = tuple(["جمع"] + [value if value is not None else ""
                                      for value in totals]
                           + [""] * max(0, len(columns) - len(totals) - 1))
    snapshot = services.settings.snapshot()
    meta = tuple(part for part in (table.meta_fa,
                                   f"شرکت: {snapshot.company_name}" if snapshot.company_name else "")
                 if part)
    return ReportTable(title=table.title_fa, columns=columns, rows=table.rows,
                       company=snapshot.company_name, meta=meta, totals=totals_row,
                       currency_code=snapshot.currency_code,
                       notes=("مبنای گزارش: فقط اسناد و رکوردهای ثبت‌شده در پایگاه‌داده",))


class ReportPageBase(PageBase):
    """Report shell: report picker, period, filters, grid, print and Excel."""

    title_fa = "گزارش"
    subtitle_fa = ""
    report_choices: tuple[tuple[str, str], ...] = ()
    report_permission = ""
    export_permission = ""

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.current: DataReportTable | None = None

        self.header = PageHeader(self.title_fa, self.subtitle_fa)
        self.header.add_action("نمایش گزارش", slot=self.run_report)
        self._print_button = self.header.add_action(
            "چاپ / PDF", variant="secondary", slot=self._print)
        self._excel_button = self.header.add_action(
            "Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)

        bar = CardPanel("انتخاب گزارش و بازه")
        row = QHBoxLayout()
        self.report_combo = QComboBox()
        for key, title in self.report_choices:
            self.report_combo.addItem(title, key)
        self.report_combo.currentIndexChanged.connect(lambda _index: self._report_changed())
        row.addWidget(form_row("گزارش", self.report_combo), 2)
        today = _dt.date.today()
        from pars_erp.core.jalali import JalaliDate

        jalali = JalaliDate.from_gregorian(today)
        self.from_edit = JalaliDateEdit(JalaliDate(jalali.year, 1, 1).to_gregorian())
        self.to_edit = JalaliDateEdit(today)
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        bar.add_layout(row)

        self.filters_row = QHBoxLayout()
        self.filters_row.setSpacing(10)
        bar.add_layout(self.filters_row)
        self.root.addWidget(bar)

        self.table = DataTable((ColumnSpec("c0", "—", TEXT, None),), formatter=formatter)
        card = CardPanel("نتیجه")
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("HintText")
        card.add_header_widget(self.meta_label)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        self.add_filters()
        self._apply_permissions()
        self._report_changed(initial=True)

    # ------------------------------------------------------------------ hooks
    def add_filters(self) -> None:
        """Subclasses add their own combos to :attr:`filters_row`."""

    def period(self) -> ReportPeriod:
        today = _dt.date.today()
        return ReportPeriod(self.from_edit.date() or today, self.to_edit.date() or today)

    def build_report(self, key: str) -> DataReportTable:  # pragma: no cover
        raise NotImplementedError

    def _report_changed(self, *, initial: bool = False) -> None:
        self.run_report()

    # ------------------------------------------------------------------- show
    def run_report(self) -> None:
        key = str(self.report_combo.currentData())
        try:
            table = self.build_report(key)
        except AppError as error:
            show_error(self, self.title_fa, error)
            return
        self.current = table
        self.table.set_columns(specs_for(table))
        self.table.set_rows(rows_for(table))
        self.meta_label.setText(
            f"{table.title_fa} — {table.row_count:,} ردیف"
            + (f" — {table.meta_fa}" if table.meta_fa else ""))

    def _print(self) -> None:
        if self.current is None:
            show_info(self, "چاپ", "ابتدا یک گزارش نمایش دهید.")
            return
        from pars_erp.services.report_render_service import ReportRenderer
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.persian_digits)
        ReportPreviewDialog(render_table(self.services, self.current), renderer,
                            parent=self).exec()

    def _excel(self) -> None:
        if self.current is None:
            show_info(self, "Excel", "ابتدا یک گزارش نمایش دهید.")
            return
        from pars_erp.services.report_render_service import ReportRenderer

        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.persian_digits)
        self.services.paths.exports_dir.mkdir(parents=True, exist_ok=True)
        path = self.services.paths.exports_dir / (
            f"report_{self.current.key}_{_dt.datetime.now():%Y%m%d_%H%M%S}.xlsx")
        try:
            outcome = renderer.to_excel(render_table(self.services, self.current), path)
        except AppError as error:
            show_error(self, "خروجی Excel", error)
            return
        show_info(self, "خروجی Excel", outcome.message_fa, tone="success")

    # ------------------------------------------------------------- permissions
    def _apply_permissions(self) -> None:
        allowed = not self.report_permission or self.can(self.report_permission)
        can_export = not self.export_permission or self.can(self.export_permission)
        self._print_button.setEnabled(allowed and can_export)
        self._excel_button.setEnabled(allowed and can_export)
        if not allowed:
            self.meta_label.setText("برای این گزارش مجوز ندارید.")
