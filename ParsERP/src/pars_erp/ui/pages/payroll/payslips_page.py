"""فیش حقوقی — payslips of a run, their lines and a printable payslip."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from pars_erp.core.errors import AppError
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.table_specs import PAYSLIP_COLUMNS, PAYSLIP_LINE_COLUMNS
from pars_erp.ui.widgets.common import InfoRow
from pars_erp.ui.widgets.table import DataTable


def payslip_table(services, row, formatter) -> ReportTable:
    """Printable payslip: employee header + every earning/deduction line."""
    snapshot = services.settings.snapshot()
    lines = row.lines or ()
    rows = tuple((line.title_fa, "درآمد" if line.side == "earning" else "کسور",
                  line.amount, line.detail or "")
                 for line in lines)
    notes = (
        f"کارمند: {row.employee_name} ({row.employee_code})",
        f"واحد: {row.org_unit or '—'} — سمت: {row.job_title or '—'}",
        f"روز کارکرد: {formatter.number(row.worked_days)} — غیبت: "
        f"{formatter.number(row.absent_days)} — اضافه‌کار: "
        f"{formatter.number(row.overtime_hours)} ساعت",
        f"جمع حقوق و مزایا: {formatter.amount(row.gross)} — جمع کسور: "
        f"{formatter.amount(row.deductions_total)}",
        f"خالص پرداختی: {formatter.amount(row.net)}",
        "این فیش از محاسبات ثبت‌شدهٔ دوره ساخته شده است؛ تغییر تنظیمات بعدی آن را "
        "تغییر نمی‌دهد.",
    )
    return ReportTable(
        title=f"فیش حقوقی — {row.number}",
        columns=(
            ReportColumn("title", "عنوان", KIND_TEXT, 2.2),
            ReportColumn("side", "نوع", KIND_TEXT, 0.9, "center"),
            ReportColumn("amount", "مبلغ", KIND_AMOUNT, 1.3),
            ReportColumn("detail", "توضیح محاسبه", KIND_TEXT, 2.6),
        ),
        rows=rows, company=snapshot.company_name,
        meta=(f"دورهٔ {row.period_year}/{row.period_month:02d}",),
        totals=("جمع خالص", "", row.net, ""),
        notes=notes, currency_code=snapshot.currency_code)


class PayslipsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "فیش حقوقی",
            "فیش‌های هر دوره، اقلام محاسبه‌شده و چاپ فیش با PDF")
        self.print_button = self.header.add_action("چاپ / PDF فیش", slot=self._print)
        self.root.addWidget(self.header)

        bar = CardPanel("انتخاب دوره")
        row = QHBoxLayout()
        self.run_combo = PickCombo()
        self.run_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("دورهٔ حقوق", self.run_combo), 2)
        self.org_filter = QComboBox()
        self.org_filter.addItem("همهٔ واحدها", None)
        self.org_filter.currentIndexChanged.connect(lambda _index: self._apply_filter())
        row.addWidget(form_row("واحد", self.org_filter), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)

        body = QHBoxLayout()
        table_card = CardPanel("فیش‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        table_card.add_header_widget(self.summary)
        self.table = DataTable(PAYSLIP_COLUMNS, formatter=formatter)
        self.table.on_selection_changed(self._show_detail)
        table_card.add(self.table, 1)
        body.addWidget(table_card, 3)

        detail_card = CardPanel("جزئیات فیش")
        detail_card.setMaximumWidth(380)
        layout = QVBoxLayout()
        layout.setSpacing(4)
        self.detail: dict[str, InfoRow] = {}
        for key, label in (("employee", "کارمند"), ("unit", "واحد"), ("worked", "روز کارکرد"),
                           ("overtime", "ساعت اضافه‌کار"), ("base", "حقوق پایه"),
                           ("benefits", "مزایا"), ("gross", "جمع حقوق"),
                           ("deductions", "جمع کسور"), ("net", "پرداختی"),
                           ("status", "وضعیت")):
            info = InfoRow(label)
            self.detail[key] = info
            layout.addWidget(info)
        self.lines_table = DataTable(PAYSLIP_LINE_COLUMNS, formatter=formatter)
        layout.addWidget(QLabel("اقلام فیش"))
        layout.addWidget(self.lines_table, 1)
        detail_card.add_layout(layout)
        body.addWidget(detail_card, 2)
        self.root.addLayout(body, 1)

        self.print_button.setEnabled(self.can("payroll.payslip.view") and
                                     self.can("payroll.print"))
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            runs = self.services.payroll.list_runs(self.ctx)
            self.run_combo.load([(run.id, f"{run.number} — {run.status_fa}") for run in runs])
            if self.run_combo.value() is None and runs:
                # the newest run is the one an accountant wants to see first
                self.run_combo.set_value(runs[0].id)
            run_id = self.run_combo.value()
            self.rows = self.services.payroll.payslips(self.ctx, run_id) if run_id else []
        except AppError as error:
            show_error(self, "فیش حقوقی", error)
            return
        units = sorted({row.org_unit for row in self.rows if row.org_unit})
        current = self.org_filter.currentData()
        self.org_filter.blockSignals(True)
        self.org_filter.clear()
        self.org_filter.addItem("همهٔ واحدها", None)
        for unit in units:
            self.org_filter.addItem(unit, unit)
        index = self.org_filter.findData(current)
        self.org_filter.setCurrentIndex(index if index >= 0 else 0)
        self.org_filter.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self) -> None:
        unit = self.org_filter.currentData()
        rows = [row for row in self.rows if not unit or row.org_unit == unit]
        self.set_rows(self.table, rows)
        net = sum((row.net for row in rows), Decimal("0"))
        self.summary.setText(f"{len(rows):,} فیش — جمع پرداختی "
                             f"{self.formatter.amount(net)}")
        self._show_detail()

    def _selected(self):
        index = self.table.selected_row_index()
        rows = self.table.model.rows()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    def _show_detail(self) -> None:
        row = self._selected()
        if row is not None and not row.lines:
            # the list row carries totals only; the full payslip brings the lines
            try:
                row = self.services.payroll.payslip(self.ctx, row.id)
            except AppError:
                row = None
        for info in self.detail.values():
            info.setVisible(row is not None)
        self.lines_table.setVisible(row is not None)
        if row is None:
            self.lines_table.set_rows([])
            return
        self.detail["employee"].set_value(f"{row.employee_name} ({row.employee_code})")
        self.detail["unit"].set_value(row.org_unit or "—")
        self.detail["worked"].set_value(self.formatter.number(row.worked_days))
        self.detail["overtime"].set_value(self.formatter.number(row.overtime_hours))
        self.detail["base"].set_value(self.formatter.amount(row.base_salary))
        self.detail["benefits"].set_value(self.formatter.amount(row.benefits_total))
        self.detail["gross"].set_value(self.formatter.amount(row.gross))
        self.detail["deductions"].set_value(self.formatter.amount(row.deductions_total))
        self.detail["net"].set_value(self.formatter.amount(row.net))
        self.detail["status"].set_value(row.status_fa)
        self.lines_table.set_rows(row.lines or ())
        self._detail_row = row

    def _print(self) -> None:
        from pars_erp.services.report_render_service import ReportRenderer
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        row = getattr(self, "_detail_row", None) or self._selected()
        if row is None:
            show_info(self, "چاپ فیش", "ابتدا یک فیش را انتخاب کنید.")
            return
        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.persian_digits)
        ReportPreviewDialog(payslip_table(self.services, row, self.formatter), renderer,
                            parent=self).exec()
