"""گزارش‌های دارایی ثابت."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox

from pars_erp.assets import constants as A
from pars_erp.core.errors import AppError
from pars_erp.ui.pages.accounting.widgets import form_row
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.pages.hr.widgets import YearMonthPicker
from pars_erp.ui.pages.report_view import ReportPageBase

CHOICES = (
    ("register", "فهرست دارایی‌ها"),
    ("by_category", "گزارش بر اساس دسته"),
    ("by_location", "گزارش بر اساس محل"),
    ("by_custodian", "گزارش بر اساس امانت‌دار"),
    ("depreciation", "استهلاک دوره"),
    ("disposals", "واگذاری‌ها"),
    ("sold_or_retired", "دارایی‌های فروخته/کنارگذاشته‌شده"),
    ("maintenance", "تعمیر و نگهداری"),
)


class AssetReportsPage(ReportPageBase):
    title_fa = "گزارش‌های دارایی ثابت"
    subtitle_fa = ("فهرست دارایی، دسته، محل، امانت‌دار، استهلاک، واگذاری و تعمیرات با "
                   "چاپ، PDF و Excel")
    report_choices = CHOICES
    report_permission = "assets.reports"
    export_permission = "assets.print"

    def add_filters(self) -> None:
        self.category_combo = PickCombo()
        try:
            self.category_combo.load(self.services.assets.category_choices(self.ctx))
        except AppError:
            self.category_combo.load([])
        self.category_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("دسته", self.category_combo))

        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in A.ASSET_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.run_report())
        self.filters_row.addWidget(form_row("وضعیت", self.status_combo))

        self.period_picker = YearMonthPicker()
        self.period_picker.setToolTip("برای گزارش استهلاک")
        self.filters_row.addWidget(form_row("دورهٔ استهلاک", self.period_picker))

        self.book_check = QCheckBox("نمایش ارزش دفتری")
        self.book_check.stateChanged.connect(lambda _state: self.run_report())
        self.filters_row.addWidget(self.book_check)
        self.filters_row.addStretch(1)

    def build_report(self, key: str):
        reports = self.services.asset_reports
        if key == "register":
            return reports.register(self.ctx, category_id=self.category_combo.value(),
                                    status=self.status_combo.currentData(),
                                    with_book_value=self.book_check.isChecked())
        if key == "by_category":
            return reports.by_category(self.ctx)
        if key == "by_location":
            return reports.by_location(self.ctx)
        if key == "by_custodian":
            return reports.by_custodian(self.ctx)
        if key == "depreciation":
            year, month = self.period_picker.value()
            return reports.depreciation(self.ctx, year=year, month=month)
        if key == "disposals":
            return reports.disposals(self.ctx)
        if key == "sold_or_retired":
            return reports.sold_or_retired(self.ctx)
        if key == "maintenance":
            return reports.maintenance(self.ctx)
        raise AppError("گزارش انتخاب‌شده پشتیبانی می‌شود.")  # pragma: no cover
