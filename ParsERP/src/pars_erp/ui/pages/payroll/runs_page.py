"""دوره‌های حقوق — create, calculate, approve, post and cancel a payroll run."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from pars_erp.core.errors import AppError
from pars_erp.payroll import constants as P
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import ask_reason, confirm
from pars_erp.ui.pages.form_dialog import FormDialog
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import YearMonthPicker
from pars_erp.ui.table_specs import PAYSLIP_COLUMNS, PAY_RUN_COLUMNS
from pars_erp.ui.widgets.common import InfoRow
from pars_erp.ui.widgets.table import DataTable


class RunDialog(FormDialog):
    title_fa = "دورهٔ حقوق جدید"
    width = 520

    def _build(self) -> None:
        self.period_picker = YearMonthPicker()
        self.add_row("دورهٔ حقوق *", self.period_picker, required=True)
        self.notes_edit = QLineEdit()
        self.add_row("یادداشت", self.notes_edit)

    def save(self):
        year, month = self.period_picker.value()
        return self.services.payroll.create_run(self.ctx, year=year, month=month,
                                                notes=self.notes_edit.text().strip())


class PayrollRunsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "دوره‌های حقوق",
            "ایجاد دوره، محاسبهٔ فیش‌ها از اسناد واقعی، تأیید، ثبت سند و لغو")
        self.new_button = self.header.add_action("دورهٔ جدید", slot=self._new)
        self.calc_button = self.header.add_action("محاسبه", variant="secondary",
                                                  slot=self._calculate)
        self.approve_button = self.header.add_action("تأیید", variant="secondary",
                                                     slot=self._approve)
        self.post_button = self.header.add_action("ثبت سند", variant="secondary",
                                                  slot=self._post)
        self.slips_button = self.header.add_action("فیش‌ها", variant="secondary",
                                                   slot=self._show_slips)
        self.cancel_button = self.header.add_action("لغو دوره", variant="secondary",
                                                    slot=self._cancel)
        self.root.addWidget(self.header)

        body = QHBoxLayout()
        table_card = CardPanel("دوره‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        table_card.add_header_widget(self.summary)
        self.table = DataTable(PAY_RUN_COLUMNS, formatter=formatter)
        self.table.on_selection_changed(self._show_detail)
        table_card.add(self.table, 1)
        body.addWidget(table_card, 3)

        detail_card = CardPanel("جزئیات دوره")
        detail_card.setMaximumWidth(340)
        layout = QVBoxLayout()
        layout.setSpacing(4)
        self.detail: dict[str, InfoRow] = {}
        for key, label in (("number", "شماره"), ("status", "وضعیت"), ("period", "بازه"),
                           ("version", "نسخهٔ تنظیمات"), ("employees", "تعداد کارمند"),
                           ("gross", "جمع ناخالص"), ("deductions", "جمع کسور"),
                           ("net", "جمع خالص"), ("insurance", "بیمهٔ سهم کارمند"),
                           ("tax", "مالیات"), ("journal", "سند حسابداری")):
            info = InfoRow(label)
            self.detail[key] = info
            layout.addWidget(info)
        layout.addStretch(1)
        detail_card.add_layout(layout)
        body.addWidget(detail_card, 1)
        self.root.addLayout(body, 1)

        can_calc = self.can("payroll.calculate")
        self.new_button.setEnabled(can_calc)
        self.calc_button.setEnabled(can_calc)
        self.approve_button.setEnabled(self.can("payroll.approve"))
        self.post_button.setEnabled(self.can("payroll.approve"))
        self.cancel_button.setEnabled(self.can("payroll.approve"))
        self.slips_button.setEnabled(self.can("payroll.view") or self.can("payroll.payslip.view"))
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.rows = self.services.payroll.list_runs(self.ctx)
        except AppError as error:
            show_error(self, "دوره‌های حقوق", error)
            return
        self.set_rows(self.table, self.rows)
        open_runs = sum(1 for row in self.rows if row.status in (P.RUN_DRAFT, P.RUN_CALCULATED))
        self.summary.setText(f"{len(self.rows):,} دوره — {open_runs:,} در جریان")
        self._show_detail()

    def _selected(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self.rows):
            return None
        return self.rows[index]

    def _show_detail(self) -> None:
        run = self._selected()
        visible = run is not None
        for info in self.detail.values():
            info.setVisible(visible)
        if run is None:
            return
        self.detail["number"].set_value(run.number)
        self.detail["status"].set_value(run.status_fa)
        self.detail["period"].set_value(
            f"{self.formatter.date(run.period_start)} — {self.formatter.date(run.period_end)}")
        self.detail["version"].set_value(run.settings_version or "—")
        self.detail["employees"].set_value(self.formatter.number(run.employees_count))
        self.detail["gross"].set_value(self.formatter.amount(run.gross_total))
        self.detail["deductions"].set_value(self.formatter.amount(run.deductions_total))
        self.detail["net"].set_value(self.formatter.amount(run.net_total))
        self.detail["insurance"].set_value(self.formatter.amount(run.insurance_total))
        self.detail["tax"].set_value(self.formatter.amount(run.tax_total))
        self.detail["journal"].set_value(
            str(run.journal_id) if run.journal_id else "—")

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = RunDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دورهٔ {dialog.saved.number} ایجاد شد.")

    def _calculate(self) -> None:
        run = self._selected()
        if run is None:
            show_info(self, "محاسبه", "ابتدا یک دوره را انتخاب کنید.")
            return
        if not confirm(self, "محاسبهٔ حقوق",
                       f"فیش‌های دورهٔ {run.number} از اسناد موجود دوباره محاسبه شود؟"):
            return
        try:
            summary = self.services.payroll.calculate(self.ctx, run.id)
        except AppError as error:
            show_error(self, "محاسبهٔ حقوق", error)
            return
        self.refresh()
        skipped = f" — {summary.skipped:,} کارمند بدون حقوق رد شد" if summary.skipped else ""
        self.notify(f"{summary.employees:,} فیش محاسبه شد؛ خالص "
                    f"{self.formatter.amount(summary.net)}{skipped}")

    def _approve(self) -> None:
        run = self._selected()
        if run is None:
            show_info(self, "تأیید", "ابتدا یک دوره را انتخاب کنید.")
            return
        try:
            self.services.payroll.approve(self.ctx, run.id)
        except AppError as error:
            show_error(self, "تأیید دوره", error)
            return
        self.refresh()
        self.notify(f"دورهٔ {run.number} تأیید شد.")

    def _post(self) -> None:
        run = self._selected()
        if run is None:
            show_info(self, "ثبت سند", "ابتدا یک دوره را انتخاب کنید.")
            return
        if not confirm(self, "ثبت سند حقوق",
                       "سند حسابداری دوره به‌صورت قطعی ثبت شود؟ ثبت دوباره ممکن نیست.",
                       danger=True):
            return
        try:
            posted = self.services.payroll.post(self.ctx, run.id)
        except AppError as error:
            show_error(self, "ثبت سند حقوق", error)
            return
        self.refresh()
        self.notify(f"سند دورهٔ {posted.number} ثبت شد.")

    def _show_slips(self) -> None:
        run = self._selected()
        if run is None:
            show_info(self, "فیش‌ها", "ابتدا یک دوره را انتخاب کنید.")
            return
        try:
            slips = self.services.payroll.payslips(self.ctx, run.id)
        except AppError as error:
            show_error(self, "فیش‌ها", error)
            return
        show_rows(self, f"فیش‌های حقوق — {run.number}", PAYSLIP_COLUMNS, slips,
                  formatter=self.formatter,
                  subtitle="برای چاپ یک فیش، از صفحهٔ «فیش حقوقی» استفاده کنید.")

    def _cancel(self) -> None:
        run = self._selected()
        if run is None:
            show_info(self, "لغو دوره", "ابتدا یک دوره را انتخاب کنید.")
            return
        reason = ask_reason(self, "لغو دورهٔ حقوق", "دلیل لغو را وارد کنید:")
        if not reason:
            return
        try:
            self.services.payroll.cancel_run(self.ctx, run.id, reason=reason)
        except AppError as error:
            show_error(self, "لغو دوره", error)
            return
        self.refresh()
        self.notify(f"دورهٔ {run.number} لغو شد.")
