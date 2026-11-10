"""گزارش‌های منابع انسانی — کارکنان، قرارداد، حضور، تأخیر، مرخصی، مأموریت."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QWidget

from pars_erp.core.errors import AppError, ValidationError
from pars_erp.hr import constants as H
from pars_erp.ui.pages.accounting.widgets import form_row
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.pages.report_view import ReportPageBase

CHOICES = (
    ("staff_list", "فهرست کارکنان"),
    ("contracts", "قراردادها و انقضای نزدیک"),
    ("attendance", "خلاصهٔ حضور و غیاب"),
    ("lateness", "تأخیر و تعجیل"),
    ("leave", "مرخصی‌ها"),
    ("overtime", "اضافه‌کاری"),
    ("missions", "مأموریت‌ها"),
)


class HRReportsPage(ReportPageBase):
    title_fa = "گزارش‌های منابع انسانی"
    subtitle_fa = ("کارکنان، قرارداد، حضور، تأخیر، مرخصی، اضافه‌کاری و مأموریت "
                   "با فیلتر تاریخ، چاپ، PDF و Excel")
    report_choices = CHOICES
    report_permission = "hr.reports"
    export_permission = "hr.print"

    def add_filters(self) -> None:
        self.unit_combo = PickCombo()
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        self.unit_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("واحد سازمانی", self.unit_combo))

        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in H.COLLAB_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("وضعیت همکاری", self.status_combo))

        self.days_combo = QComboBox()
        for days in (15, 30, 60, 90):
            self.days_combo.addItem(f"{days} روز", days)
        self.days_combo.setCurrentIndex(1)
        self.days_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("افق انقضای قرارداد", self.days_combo))

        self.sensitive_check = QCheckBox("نمایش اطلاعات حساس")
        self.sensitive_check.setEnabled(self.can("hr.employees.sensitive"))
        self.sensitive_check.stateChanged.connect(lambda _state: self.run_report())
        self.filters_row.addWidget(self.sensitive_check)
        self.filters_row.addStretch(1)

    def build_report(self, key: str):
        reports = self.services.hr_reports
        if key == "staff_list":
            return reports.staff_list(
                self.ctx, status=self.status_combo.currentData(),
                org_unit_id=self.unit_combo.value(),
                include_sensitive=self.sensitive_check.isChecked())
        if key == "contracts":
            return reports.contracts(
                self.ctx, expiring_within_days=int(self.days_combo.currentData()))
        period = self.period()
        mapping = {
            "attendance": reports.attendance,
            "lateness": reports.lateness,
            "leave": reports.leave,
            "overtime": reports.overtime,
            "missions": reports.missions,
        }
        builder = mapping.get(key)
        if builder is None:  # pragma: no cover - guarded by the combo
            raise ValidationError("گزارش انتخاب‌شده پشتیبانی نمی‌شود.")
        return builder(self.ctx, period)
