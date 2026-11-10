"""وام و مساعده — request, approve, pay through the treasury and settle."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QWidget

from pars_erp.core.errors import AppError, ValidationError
from pars_erp.payroll import constants as P
from pars_erp.services.loans_service import LoanInput, LoanPaymentInput
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import EmployeePicker, YearMonthPicker, hint_label, month_choices
from pars_erp.ui.pages.treasury.widgets import FundPicker
from pars_erp.ui.table_specs import INSTALLMENT_COLUMNS, LOAN_COLUMNS
from pars_erp.ui.widgets.table import DataTable


class LoanDialog(FormDialog):
    title_fa = "وام / مساعدهٔ کارمند"
    width = 620

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        self.add_row("کارمند *", self.employee_picker, required=True)
        self.kind_combo = fill_combo(QComboBox(), P.LOAN_KINDS,
                                     current=P.LOAN_KIND_LOAN, placeholder="")
        self.amount_edit = MoneyEdit()
        self.add_pair(("نوع", self.kind_combo), ("مبلغ *", self.amount_edit),
                      right_required=True)
        self.installments_spin = QSpinBox()
        self.installments_spin.setRange(1, 60)
        self.installments_spin.setValue(12)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("تعداد قسط", self.installments_spin), ("تاریخ درخواست", self.date_edit))
        self.start_picker = YearMonthPicker()
        self.add_row("شروع بازپرداخت", self.start_picker,
                     hint="اولین ماهی که قسط از حقوق کسر می‌شود.")
        self.reason_edit = QLineEdit()
        self.add_row("علت/توضیح", self.reason_edit)
        self.add_widget(hint_label(
            "سقف وام نسبت به حقوق در تنظیمات دورهٔ حقوق (loan_max_share_of_salary) "
            "تعیین می‌شود و در محاسبهٔ حقوق اعمال می‌گردد."))

    def save(self):
        year, month = self.start_picker.value()
        return self.services.loans.create(self.ctx, LoanInput(
            employee_id=int(self.employee_picker.require()),
            amount=self.amount_edit.amount,
            kind=str(self.kind_combo.currentData()),
            request_date=self.date_edit.date(),
            installments=self.installments_spin.value(),
            repayment_start_year=year,
            repayment_start_month=month,
            reason=self.reason_edit.text().strip(),
        ))


class LoanPaymentDialog(FormDialog):
    title_fa = "پرداخت وام"
    width = 560

    def __init__(self, services, ctx, loan, parent: QWidget | None = None) -> None:
        self.loan = loan
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"پرداخت {loan.number} — {loan.employee_name}؛ "
                                  "سند خزانه و بدهی کارمند هم‌زمان ثبت می‌شود.")

    def _build(self) -> None:
        self.fund_picker = FundPicker()
        self.fund_picker.attach(self.services, self.ctx)
        self.add_row("منبع پرداخت *", self.fund_picker, required=True)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_row("تاریخ پرداخت", self.date_edit)
        self.method_combo = fill_combo(QComboBox(), TC.PAYMENT_METHODS,
                                       current=TC.METHOD_CASH, placeholder="")
        self.tracking_edit = QLineEdit()
        self.add_pair(("روش", self.method_combo), ("شماره پیگیری", self.tracking_edit))

    def save(self):
        kind, fund_id = self.fund_picker.require()
        return self.services.loans.pay(self.ctx, self.loan.id, LoanPaymentInput(
            payment_date=self.date_edit.date(),
            cash_box_id=fund_id if kind == TC.FUND_CASH else None,
            bank_account_id=fund_id if kind == TC.FUND_BANK else None,
            method=str(self.method_combo.currentData()),
            tracking_no=self.tracking_edit.text().strip(),
        ))


class LoansPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "وام و مساعده",
            "درخواست، تأیید، پرداخت از خزانه، اقساط، تسویه و بدهی هر کارمند")
        self.new_button = self.header.add_action("وام جدید", slot=self._new)
        self.approve_button = self.header.add_action("تأیید", variant="secondary",
                                                     slot=self._approve)
        self.reject_button = self.header.add_action("رد", variant="secondary",
                                                    slot=self._reject)
        self.pay_button = self.header.add_action("پرداخت", variant="secondary",
                                                 slot=self._pay)
        self.settle_button = self.header.add_action("تسویه", variant="secondary",
                                                    slot=self._settle)
        self.installments_button = self.header.add_action("اقساط", variant="secondary",
                                                          slot=self._installments)
        self.debt_button = self.header.add_action("بدهی کارمند", variant="secondary",
                                                  slot=self._debt)
        self.root.addWidget(self.header)

        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.employee_combo = PickCombo()
        self.employee_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("کارمند", self.employee_combo), 2)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in P.LOAN_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_combo), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)

        self.table = DataTable(LOAN_COLUMNS, formatter=formatter)
        card = CardPanel("وام‌ها و مساعده‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        can_manage = self.can("payroll.loans.manage")
        for button in (self.new_button, self.approve_button, self.reject_button,
                       self.pay_button, self.settle_button):
            button.setEnabled(can_manage)
        viewer = can_manage or self.can("payroll.view")
        self.installments_button.setEnabled(viewer)
        self.debt_button.setEnabled(viewer)
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.employee_combo.load(self.services.hr.employee_choices(self.ctx,
                                                                      active_only=False))
        except AppError:
            self.employee_combo.load([])
        try:
            self.rows = self.services.loans.list_loans(
                self.ctx, employee_id=self.employee_combo.value(),
                status=self.status_combo.currentData())
        except AppError as error:
            show_error(self, "وام و مساعده", error)
            return
        self.set_rows(self.table, self.rows)
        open_debt = sum((row.remaining_debt for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} پرونده — بدهی باز "
                             f"{self.formatter.amount(open_debt)}")

    def _selected(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = LoanDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"درخواست {dialog.saved.number} ثبت شد.")

    def _decide(self, approve: bool) -> None:
        loan = self._selected()
        if loan is None:
            show_info(self, "وام", "ابتدا یک پرونده را انتخاب کنید.")
            return
        try:
            if approve:
                self.services.loans.approve(self.ctx, loan.id)
            else:
                reason = ask_reason(self, "رد وام", "دلیل رد را وارد کنید:")
                if not reason:
                    return
                self.services.loans.reject(self.ctx, loan.id, reason=reason)
        except AppError as error:
            show_error(self, "وام", error)
            return
        self.refresh()
        self.notify(f"پروندهٔ {loan.number} " + ("تأیید" if approve else "رد") + " شد.")

    def _approve(self) -> None:
        self._decide(True)

    def _reject(self) -> None:
        self._decide(False)

    def _pay(self) -> None:
        loan = self._selected()
        if loan is None:
            show_info(self, "پرداخت وام", "ابتدا یک پرونده را انتخاب کنید.")
            return
        dialog = LoanPaymentDialog(self.services, self.ctx, loan, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"پرداخت {loan.number} ثبت و سند خزانه صادر شد.")

    def _settle(self) -> None:
        loan = self._selected()
        if loan is None:
            show_info(self, "تسویه", "ابتدا یک پرونده را انتخاب کنید.")
            return
        if not confirm(self, "تسویهٔ زودهنگام",
                       f"باقیماندهٔ اقساط {loan.number} تسویه شود؟", danger=True):
            return
        try:
            self.services.loans.settle(self.ctx, loan.id)
        except AppError as error:
            show_error(self, "تسویه", error)
            return
        self.refresh()
        self.notify(f"پروندهٔ {loan.number} تسویه شد.")

    def _installments(self) -> None:
        loan = self._selected()
        if loan is None:
            show_info(self, "اقساط", "ابتدا یک پرونده را انتخاب کنید.")
            return
        show_rows(self, f"اقساط {loan.number}", INSTALLMENT_COLUMNS,
                  loan.installments_rows or [], formatter=self.formatter,
                  subtitle=f"مبلغ هر قسط {self.formatter.amount(loan.installment_amount)}")

    def _debt(self) -> None:
        employee_id = self.employee_combo.value()
        if employee_id is None:
            show_info(self, "بدهی کارمند", "ابتدا یک کارمند را انتخاب کنید.")
            return
        try:
            debt = self.services.loans.employee_debt(self.ctx, int(employee_id))
        except AppError as error:
            show_error(self, "بدهی کارمند", error)
            return
        show_info(self, "بدهی کارمند",
                  f"مانده بدهی وام و مساعده: {self.formatter.amount(debt)}")
