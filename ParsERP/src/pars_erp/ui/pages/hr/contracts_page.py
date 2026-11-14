"""قراردادها — create, renew, amend and terminate employee contracts."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.hr import constants as H
from pars_erp.services.hr_service import ContractInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.widgets import EmployeePicker
from pars_erp.ui.table_specs import CONTRACT_COLUMNS
from pars_erp.ui.widgets.common import SearchInput  # noqa: F401
from pars_erp.ui.widgets.table import DataTable


class ContractDialog(FormDialog):
    title_fa = "قرارداد کار"
    width = 700

    def __init__(self, services, ctx, *, contract=None, employee_id: int | None = None,
                 mode: str = "new", parent: QWidget | None = None) -> None:
        self.contract = contract
        self.mode = mode
        self._employee_id = employee_id
        title = {"new": "قرارداد جدید", "renew": "تمدید قرارداد"}.get(mode, "قرارداد")
        super().__init__(services, ctx, parent=parent,
                         subtitle="قرارداد تمدیدشده قرارداد قبلی را می‌بندد و سابقه حفظ می‌شود."
                         if mode == "renew" else "")
        self.setWindowTitle(title)

    def _build(self) -> None:
        contract = self.contract
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        if contract is not None:
            self.employee_picker.set_value(contract.employee_id)
            self.employee_picker.setEnabled(False)
        elif self._employee_id is not None:
            self.employee_picker.set_value(self._employee_id)
        self.type_combo = fill_combo(QComboBox(), H.CONTRACT_TYPES,
                                     current=H.CONTRACT_FIXED, placeholder="")
        self.add_pair(("کارمند *", self.employee_picker), ("نوع قرارداد *", self.type_combo),
                      left_required=True)

        default_start = _dt.date.today()
        if contract is not None and self.mode == "renew":
            default_start = (contract.end_date or _dt.date.today()) + _dt.timedelta(days=1)
        self.start_edit = JalaliDateEdit(default_start)
        # a renewal starts after the old contract, so the old end date is cleared
        previous_end = (getattr(contract, "end_date", None)
                        if self.mode != "renew" else None)
        self.end_edit = JalaliDateEdit(previous_end, allow_empty=True)
        self.add_pair(("تاریخ شروع *", self.start_edit), ("تاریخ پایان", self.end_edit),
                      left_required=True)

        self.salary_edit = MoneyEdit()
        self.salary_edit.set_amount(contract.base_salary if contract else Decimal(0))
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(1, 168)
        self.hours_spin.setValue(int(contract.working_hours_weekly) if contract else 44)
        self.add_pair(("حقوق پایه *", self.salary_edit), ("ساعت هفتگی", self.hours_spin),
                      left_required=True)

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 7)
        self.days_spin.setValue(int(contract.working_days_weekly) if contract else 5)
        self.signed_edit = JalaliDateEdit(_dt.date.today(), allow_empty=True)
        self.add_pair(("روز کاری هفتگی", self.days_spin), ("تاریخ امضا", self.signed_edit))

        self.job_edit = QLineEdit(getattr(contract, "job_title", "") or "")
        self.unit_combo = PickCombo()
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        self.add_pair(("عنوان شغلی", self.job_edit), ("واحد سازمانی", self.unit_combo))

        self.payment_edit = QLineEdit()
        self.benefits_edit = QLineEdit()
        self.add_pair(("شرایط پرداخت", self.payment_edit), ("مزایا", self.benefits_edit))
        self.deductions_edit = QLineEdit()
        self.notes_edit = QLineEdit()
        self.add_pair(("کسور قرارداد", self.deductions_edit), ("یادداشت", self.notes_edit))

    def save(self):
        data = ContractInput(
            employee_id=int(self.employee_picker.require()),
            contract_type=str(self.type_combo.currentData()),
            start_date=self.start_edit.date(),
            end_date=self.end_edit.date(),
            base_salary=self.salary_edit.amount,
            working_hours_weekly=Decimal(self.hours_spin.value()),
            working_days_weekly=self.days_spin.value(),
            payment_terms=self.payment_edit.text().strip(),
            benefits=self.benefits_edit.text().strip(),
            deductions=self.deductions_edit.text().strip(),
            job_title=self.job_edit.text().strip(),
            org_unit_id=self.unit_combo.value(),
            signed_date=self.signed_edit.date(),
            file_path="",
            notes=self.notes_edit.text().strip(),
        )
        if self.mode == "renew" and self.contract is not None:
            return self.services.hr.renew_contract(self.ctx, self.contract.id, data)
        return self.services.hr.create_contract(self.ctx, data)


class AmendContractDialog(FormDialog):
    title_fa = "اصلاح قرارداد"
    width = 520

    def __init__(self, services, ctx, contract, parent: QWidget | None = None) -> None:
        self.contract = contract
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"قرارداد {contract.number} — {contract.employee_name}")

    def _build(self) -> None:
        self.salary_edit = MoneyEdit()
        self.salary_edit.set_amount(self.contract.base_salary)
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(1, 168)
        self.hours_spin.setValue(int(self.contract.working_hours_weekly or 44))
        self.add_pair(("حقوق پایهٔ جدید", self.salary_edit), ("ساعت هفتگی", self.hours_spin))
        self.end_edit = JalaliDateEdit(self.contract.end_date, allow_empty=True)
        self.add_row("تاریخ پایان جدید", self.end_edit)
        self.note_edit = QLineEdit()
        self.add_row("دلیل اصلاح *", self.note_edit, required=True)

    def save(self):
        return self.services.hr.amend_contract(
            self.ctx, self.contract.id, base_salary=self.salary_edit.amount,
            end_date=self.end_edit.date(),
            working_hours_weekly=Decimal(self.hours_spin.value()),
            note=self.note_edit.text().strip())


class ContractsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "قراردادها", "قرارداد کار، تمدید، اصلاح، خاتمه و هشدار انقضا")
        self.new_button = self.header.add_action("قرارداد جدید", slot=self._new)
        self.renew_button = self.header.add_action("تمدید", variant="secondary",
                                                   slot=self._renew)
        self.amend_button = self.header.add_action("اصلاح", variant="secondary",
                                                   slot=self._amend)
        self.terminate_button = self.header.add_action("خاتمه", variant="secondary",
                                                       slot=self._terminate)
        self.root.addWidget(self.header)

        bar = CardPanel("فیلتر قراردادها")
        row = QHBoxLayout()
        self.employee_combo = PickCombo()
        row.addWidget(form_row("کارمند", self.employee_combo), 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in H.CONTRACT_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_combo), 1)
        self.expiring_only = QCheckBox("فقط قراردادهای نزدیک انقضا (۳۰ روز)")
        self.expiring_only.stateChanged.connect(lambda _state: self.refresh())
        row.addWidget(self.expiring_only)
        bar.add_layout(row)
        self.root.addWidget(bar)

        self.table = DataTable(CONTRACT_COLUMNS, formatter=formatter)
        card = CardPanel("قراردادها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        self.employee_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        self._apply_permissions()
        self.refresh()

    def _apply_permissions(self) -> None:
        can_manage = self.can("hr.contracts.manage")
        for button in (self.new_button, self.renew_button, self.amend_button,
                       self.terminate_button):
            button.setEnabled(can_manage)

    def refresh(self) -> None:
        try:
            self.employee_combo.load(self.services.hr.employee_choices(self.ctx,
                                                                     active_only=False))
        except AppError:
            self.employee_combo.load([])
        employee_id = self.employee_combo.value()
        try:
            if self.expiring_only.isChecked() and employee_id is None:
                self.rows = self.services.hr.expiring_contracts(self.ctx, days=30)
            else:
                self.rows = self.services.hr.list_contracts(
                    self.ctx, employee_id=employee_id,
                    status=self.status_combo.currentData())
        except AppError as error:
            show_error(self, "قراردادها", error)
            return
        self.set_rows(self.table, self.rows)
        expiring = sum(1 for row in self.rows
                       if row.days_to_expiry is not None and 0 <= row.days_to_expiry <= 30)
        self.summary.setText(f"{len(self.rows):,} قرارداد — {expiring:,} نزدیک انقضا")

    def _selected(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self.rows):
            return None
        return self.rows[index]

    def _new(self) -> None:
        dialog = ContractDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"قرارداد {dialog.saved.number} ثبت شد.")

    def _renew(self) -> None:
        contract = self._selected()
        if contract is None:
            show_info(self, "تمدید", "ابتدا یک قرارداد را انتخاب کنید.")
            return
        dialog = ContractDialog(self.services, self.ctx, contract=contract, mode="renew",
                                parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"قرارداد جدید {dialog.saved.number} از تمدید ساخته شد.")

    def _amend(self) -> None:
        contract = self._selected()
        if contract is None:
            show_info(self, "اصلاح", "ابتدا یک قرارداد را انتخاب کنید.")
            return
        dialog = AmendContractDialog(self.services, self.ctx, contract, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"قرارداد {contract.number} اصلاح شد.")

    def _terminate(self) -> None:
        contract = self._selected()
        if contract is None:
            show_info(self, "خاتمه", "ابتدا یک قرارداد را انتخاب کنید.")
            return
        reason = ask_reason(self, "خاتمهٔ قرارداد",
                            f"علت خاتمهٔ قرارداد {contract.number} را وارد کنید:")
        if not reason:
            return
        if not confirm(self, "خاتمهٔ قرارداد",
                       f"قرارداد {contract.number} ({contract.employee_name}) خاتمه یابد؟",
                       danger=True):
            return
        try:
            self.services.hr.terminate_contract(self.ctx, contract.id, reason=reason)
        except AppError as error:
            show_error(self, "خاتمهٔ قرارداد", error)
            return
        self.refresh()
        self.notify(f"قرارداد {contract.number} خاتمه یافت.")
