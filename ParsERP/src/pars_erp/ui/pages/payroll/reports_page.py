"""گزارش‌های حقوق و دستمزد."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from pars_erp.core.errors import AppError, ValidationError
from pars_erp.ui.pages.accounting.widgets import form_row
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.pages.hr.widgets import current_jalali_year_month
from pars_erp.ui.pages.report_view import ReportPageBase

CHOICES = (
    ("runs", "فهرست دوره‌های حقوق"),
    ("register", "دفتر حقوق (لیست حقوق)"),
    ("components", "ریز اقلام حقوق"),
    ("payments", "پرداخت‌های حقوق"),
    ("loan_balances", "ماندهٔ وام و مساعده"),
    ("advances", "مساعده‌های پرداخت‌شده"),
)


class PayrollReportsPage(ReportPageBase):
    title_fa = "گزارش‌های حقوق و دستمزد"
    subtitle_fa = ("دوره‌ها، دفتر حقوق، ریز اقلام، پرداخت‌ها، ماندهٔ وام و مساعده با "
                   "چاپ، PDF و Excel")
    report_choices = CHOICES
    report_permission = "payroll.reports"
    export_permission = "payroll.print"

    def add_filters(self) -> None:
        self.run_combo = PickCombo()
        try:
            runs = self.services.payroll.list_runs(self.ctx)
        except AppError:
            runs = []
        self.run_combo.load([(run.id, f"{run.number} — {run.status_fa}") for run in runs])
        if runs:
            self.run_combo.set_value(runs[0].id)
        self.run_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("دورهٔ حقوق", self.run_combo))

        year, _month = current_jalali_year_month()
        self.year_combo = QComboBox()
        for value in (year, year - 1, year - 2):
            self.year_combo.addItem(self.formatter.number(value), value)
        self.year_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("سال", self.year_combo))
        self.filters_row.addStretch(1)

    def build_report(self, key: str):
        reports = self.services.payroll_reports
        year = int(self.year_combo.currentData())
        if key == "runs":
            return reports.runs(self.ctx, year=year)
        if key == "loan_balances":
            return reports.loan_balances(self.ctx)
        if key == "advances":
            return reports.advances(self.ctx, year=year)
        run_id = self.run_combo.value()
        if run_id is None:
            raise ValidationError("برای این گزارش ابتدا یک دورهٔ حقوق را انتخاب کنید.")
        if key == "register":
            return reports.register(self.ctx, int(run_id))
        if key == "components":
            return reports.components(self.ctx, int(run_id))
        if key == "payments":
            return reports.payments(self.ctx, int(run_id))
        raise ValidationError("گزارش انتخاب‌شده پشتیبانی می‌شود.")  # pragma: no cover
