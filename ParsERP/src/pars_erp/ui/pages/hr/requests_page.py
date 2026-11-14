"""مرخصی، مأموریت و اضافه‌کاری — request, approve, reject, balances."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.core.jalali import JalaliDate
from pars_erp.hr import constants as H
from pars_erp.services.attendance_service import (
    LeaveInput,
    LeaveTypeInput,
    MissionInput,
    OvertimeInput,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import EmployeePicker
from pars_erp.ui.table_specs import BALANCE_COLUMNS, LEAVE_COLUMNS, MISSION_COLUMNS, OVERTIME_COLUMNS
from pars_erp.ui.widgets.table import DataTable


def _year() -> int:
    return JalaliDate.today().year


# --------------------------------------------------------------------- dialogs
class LeaveDialog(FormDialog):
    title_fa = "درخواست مرخصی"
    width = 580

    def __init__(self, services, ctx, *, employee_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        self._employee_id = employee_id
        super().__init__(services, ctx, parent=parent,
                         subtitle="درخواست پس از ثبت در انتظار تأیید است؛ روزها با "
                                  "تقویم کاری محاسبه می‌شود.")

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        if self._employee_id:
            self.employee_picker.set_value(self._employee_id)
        self.type_combo = PickCombo()
        try:
            self.type_combo.load(self.services.attendance.leave_type_choices(self.ctx))
        except AppError:
            self.type_combo.load([])
        self.add_pair(("کارمند *", self.employee_picker), ("نوع مرخصی *", self.type_combo),
                      left_required=True, right_required=True)
        self.from_edit = JalaliDateEdit(_dt.date.today())
        self.to_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("از تاریخ *", self.from_edit), ("تا تاریخ *", self.to_edit),
                      left_required=True, right_required=True)
        self.hours_edit = QLineEdit()
        self.hours_edit.setPlaceholderText("برای مرخصی ساعتی")
        self.add_row("ساعت (اختیاری)", self.hours_edit,
                     hint="اگر مرخصی ساعتی است مقدار ساعت را وارد کنید.")
        self.reason_edit = QLineEdit()
        self.add_row("علت", self.reason_edit)

    def save(self):
        hours = self.hours_edit.text().strip()
        data = LeaveInput(
            employee_id=int(self.employee_picker.require()),
            leave_type_id=int(self.type_combo.value() or 0),
            date_from=self.from_edit.date(),
            date_to=self.to_edit.date(),
            hours=Decimal(hours) if hours else None,
            reason=self.reason_edit.text().strip(),
        )
        if not data.leave_type_id:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("نوع مرخصی را انتخاب کنید.", field="leave_type_id")
        return self.services.attendance.request_leave(self.ctx, data)


class LeaveTypeDialog(FormDialog):
    title_fa = "نوع مرخصی"
    width = 560

    def _build(self) -> None:
        self.code_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.add_pair(("کد *", self.code_edit), ("عنوان *", self.title_edit),
                      left_required=True, right_required=True)
        self.kind_combo = fill_combo(QComboBox(), H.LEAVE_KINDS, current=H.LEAVE_PAID,
                                     placeholder="")
        self.quota_edit = QLineEdit()
        self.quota_edit.setPlaceholderText("مثلاً 26")
        self.add_pair(("نوع", self.kind_combo), ("سهمیهٔ سالانه (روز)", self.quota_edit))
        self.paid_check = QCheckBox("مرخصی با حقوق است")
        self.paid_check.setChecked(True)
        self.approval_check = QCheckBox("نیازمند تأیید")
        self.approval_check.setChecked(True)
        self.balance_check = QCheckBox("در ماندهٔ مرخصی محاسبه شود")
        self.balance_check.setChecked(True)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for box in (self.paid_check, self.approval_check, self.balance_check):
            row.addWidget(box)
        self.add_widget(holder)
        self.description_edit = QLineEdit()
        self.add_row("توضیحات", self.description_edit)

    def save(self):
        quota = self.quota_edit.text().strip() or "0"
        data = LeaveTypeInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            is_paid=self.paid_check.isChecked(),
            requires_approval=self.approval_check.isChecked(),
            annual_quota_days=Decimal(quota),
            counts_in_balance=self.balance_check.isChecked(),
            description=self.description_edit.text().strip(),
        )
        return self.services.attendance.create_leave_type(self.ctx, data)


class MissionDialog(FormDialog):
    title_fa = "مأموریت"
    width = 600

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        self.destination_edit = QLineEdit()
        self.add_pair(("کارمند *", self.employee_picker), ("مقصد *", self.destination_edit),
                      left_required=True, right_required=True)
        self.from_edit = JalaliDateEdit(_dt.date.today())
        self.to_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("از تاریخ *", self.from_edit), ("تا تاریخ", self.to_edit),
                      left_required=True)
        self.purpose_edit = QLineEdit()
        self.transport_edit = QLineEdit()
        self.add_pair(("هدف مأموریت", self.purpose_edit), ("وسیله سفر", self.transport_edit))
        self.cost_edit = MoneyEdit()
        self.allowance_edit = MoneyEdit()
        self.add_pair(("هزینه", self.cost_edit), ("کمک‌هزینه", self.allowance_edit))

    def save(self):
        return self.services.attendance.create_mission(self.ctx, MissionInput(
            employee_id=int(self.employee_picker.require()),
            destination=self.destination_edit.text().strip(),
            date_from=self.from_edit.date(),
            date_to=self.to_edit.date(),
            purpose=self.purpose_edit.text().strip(),
            transport=self.transport_edit.text().strip(),
            cost=self.cost_edit.amount,
            allowance=self.allowance_edit.amount,
        ))


class OvertimeDialog(FormDialog):
    title_fa = "درخواست اضافه‌کاری"
    width = 540

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("کارمند *", self.employee_picker), ("تاریخ *", self.date_edit),
                      left_required=True, right_required=True)
        self.hours_edit = QLineEdit()
        self.hours_edit.setPlaceholderText("مثلاً 2.5")
        self.holiday_check = QCheckBox("اضافه‌کاری روز تعطیل")
        self.add_pair(("ساعت اضافه‌کاری *", self.hours_edit), ("", self.holiday_check),
                      left_required=True)
        self.reason_edit = QLineEdit()
        self.add_row("علت", self.reason_edit)

    def save(self):
        text = self.hours_edit.text().strip() or "0"
        return self.services.attendance.request_overtime(self.ctx, OvertimeInput(
            employee_id=int(self.employee_picker.require()),
            work_date=self.date_edit.date(),
            hours=Decimal(text),
            is_holiday=self.holiday_check.isChecked(),
            reason=self.reason_edit.text().strip(),
        ))


# ----------------------------------------------------------------------- page
class LeaveMissionOvertimePage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.leave_rows = []
        self.mission_rows = []
        self.overtime_rows = []
        self.header = PageHeader(
            "مرخصی، مأموریت و اضافه‌کاری",
            "درخواست، تأیید یا رد با یادداشت، ماندهٔ مرخصی و ورودی محاسبهٔ حقوق")
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_leave_tab(), "مرخصی")
        self.tabs.addTab(self._build_mission_tab(), "مأموریت")
        self.tabs.addTab(self._build_overtime_tab(), "اضافه‌کاری")
        self.root.addWidget(self.tabs, 1)

        self.leave_new.setEnabled(self.can("hr.leave.request"))
        self.leave_type_new.setEnabled(self.can("hr.org.edit"))
        self.leave_approve.setEnabled(self.can("hr.leave.approve"))
        self.leave_reject.setEnabled(self.can("hr.leave.approve"))
        self.leave_cancel.setEnabled(self.can("hr.leave.request"))
        self.mission_new.setEnabled(self.can("hr.leave.request"))
        self.mission_approve.setEnabled(self.can("hr.overtime.approve"))
        self.mission_reject.setEnabled(self.can("hr.overtime.approve"))
        self.overtime_new.setEnabled(self.can("hr.leave.request"))
        self.overtime_approve.setEnabled(self.can("hr.overtime.approve"))
        self.overtime_reject.setEnabled(self.can("hr.overtime.approve"))
        self.refresh()

    # ------------------------------------------------------------------ layout
    @staticmethod
    def _button(text: str, slot, variant: str = "primary") -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", variant)
        button.setMinimumHeight(32)
        button.clicked.connect(slot)
        return button

    def _tab(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        return page, layout

    def _build_leave_tab(self) -> QWidget:
        page, layout = self._tab()
        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.leave_employee = PickCombo()
        self.leave_employee.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("کارمند", self.leave_employee), 2)
        self.leave_status = QComboBox()
        self.leave_status.addItem("همهٔ وضعیت‌ها", None)
        for value, title in H.LEAVE_STATUSES:
            self.leave_status.addItem(title, value)
        self.leave_status.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت", self.leave_status), 1)
        self.leave_year = QComboBox()
        for value in (_year(), _year() - 1):
            self.leave_year.addItem(self.formatter.number(value), value)
        self.leave_year.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("سال", self.leave_year), 1)
        bar.add_layout(row)
        layout.addWidget(bar)

        actions = QHBoxLayout()
        self.leave_new = self._button("درخواست مرخصی", self._new_leave)
        self.leave_type_new = self._button("نوع مرخصی جدید", self._new_leave_type,
                                           "secondary")
        self.leave_approve = self._button("تأیید", self._approve_leave, "secondary")
        self.leave_reject = self._button("رد", self._reject_leave, "secondary")
        self.leave_cancel = self._button("لغو", self._cancel_leave, "secondary")
        self.leave_balance = self._button("ماندهٔ مرخصی", self._show_balance, "secondary")
        for button in (self.leave_new, self.leave_type_new, self.leave_approve,
                       self.leave_reject, self.leave_cancel, self.leave_balance):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.leave_table = DataTable(LEAVE_COLUMNS, formatter=self.formatter)
        card = CardPanel("درخواست‌های مرخصی")
        self.leave_summary = QLabel("")
        self.leave_summary.setObjectName("HintText")
        card.add_header_widget(self.leave_summary)
        card.add(self.leave_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_mission_tab(self) -> QWidget:
        page, layout = self._tab()
        actions = QHBoxLayout()
        self.mission_new = self._button("مأموریت جدید", self._new_mission)
        self.mission_approve = self._button("تأیید", self._approve_mission, "secondary")
        self.mission_reject = self._button("رد", self._reject_mission, "secondary")
        for button in (self.mission_new, self.mission_approve, self.mission_reject):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.mission_table = DataTable(MISSION_COLUMNS, formatter=self.formatter)
        card = CardPanel("مأموریت‌ها")
        card.add(self.mission_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_overtime_tab(self) -> QWidget:
        page, layout = self._tab()
        actions = QHBoxLayout()
        self.overtime_new = self._button("درخواست اضافه‌کاری", self._new_overtime)
        self.overtime_approve = self._button("تأیید", self._approve_overtime, "secondary")
        self.overtime_reject = self._button("رد", self._reject_overtime, "secondary")
        for button in (self.overtime_new, self.overtime_approve, self.overtime_reject):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.overtime_table = DataTable(OVERTIME_COLUMNS, formatter=self.formatter)
        card = CardPanel("اضافه‌کاری‌ها")
        card.add(self.overtime_table, 1)
        layout.addWidget(card, 1)
        return page

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        for combo in (self.leave_employee,):
            try:
                choices = self.services.hr.employee_choices(self.ctx, active_only=False)
            except AppError:
                choices = []
            combo.load(choices)
        try:
            self.leave_rows = self.services.attendance.list_leave(
                self.ctx, employee_id=self.leave_employee.value(),
                status=self.leave_status.currentData(),
                year=int(self.leave_year.currentData()))
            self.mission_rows = self.services.attendance.list_missions(self.ctx)
            self.overtime_rows = self.services.attendance.list_overtime(self.ctx)
        except AppError as error:
            show_error(self, "مرخصی و مأموریت", error)
            return
        self.set_rows(self.leave_table, self.leave_rows)
        self.set_rows(self.mission_table, self.mission_rows)
        self.set_rows(self.overtime_table, self.overtime_rows)
        pending = sum(1 for row in self.leave_rows if row.status == H.LEAVE_SUBMITTED)
        days = sum((row.days for row in self.leave_rows), Decimal("0"))
        self.leave_summary.setText(f"{len(self.leave_rows):,} درخواست — "
                                   f"{pending:,} در انتظار تأیید — جمع {days:,} روز")

    def _selected(self, table, rows):
        index = table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    # -------------------------------------------------------------- leave ops
    def _new_leave(self) -> None:
        dialog = LeaveDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"درخواست مرخصی {dialog.saved.number} ثبت شد.")

    def _new_leave_type(self) -> None:
        dialog = LeaveTypeDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"نوع مرخصی «{dialog.saved.title_fa}» تعریف شد.")

    def _approve_leave(self) -> None:
        row = self._selected(self.leave_table, self.leave_rows)
        if row is None:
            show_info(self, "تأیید مرخصی", "ابتدا یک درخواست را انتخاب کنید.")
            return
        try:
            self.services.attendance.approve_leave(self.ctx, row.id)
        except AppError as error:
            show_error(self, "تأیید مرخصی", error)
            return
        self.refresh()
        self.notify(f"مرخصی {row.number} تأیید شد.")

    def _reject_leave(self) -> None:
        row = self._selected(self.leave_table, self.leave_rows)
        if row is None:
            show_info(self, "رد مرخصی", "ابتدا یک درخواست را انتخاب کنید.")
            return
        note = ask_reason(self, "رد مرخصی", "دلیل رد را وارد کنید:")
        if not note:
            return
        try:
            self.services.attendance.reject_leave(self.ctx, row.id, note=note)
        except AppError as error:
            show_error(self, "رد مرخصی", error)
            return
        self.refresh()
        self.notify(f"مرخصی {row.number} رد شد.")

    def _cancel_leave(self) -> None:
        row = self._selected(self.leave_table, self.leave_rows)
        if row is None:
            show_info(self, "لغو مرخصی", "ابتدا یک درخواست را انتخاب کنید.")
            return
        note = ask_reason(self, "لغو مرخصی", "علت لغو را وارد کنید:")
        if not note:
            return
        try:
            self.services.attendance.cancel_leave(self.ctx, row.id, note=note)
        except AppError as error:
            show_error(self, "لغو مرخصی", error)
            return
        self.refresh()
        self.notify(f"مرخصی {row.number} لغو شد.")

    def _show_balance(self) -> None:
        employee_id = self.leave_employee.value()
        if employee_id is None:
            show_info(self, "ماندهٔ مرخصی", "ابتدا یک کارمند را انتخاب کنید.")
            return
        try:
            balances = self.services.attendance.balances(
                self.ctx, int(employee_id), year=int(self.leave_year.currentData()))
        except AppError as error:
            show_error(self, "ماندهٔ مرخصی", error)
            return
        show_rows(self, "ماندهٔ مرخصی", BALANCE_COLUMNS, balances,
                  formatter=self.formatter,
                  subtitle="سهمیه، انتقالی، تعدیل، استفاده‌شده و ماندهٔ هر نوع مرخصی")

    # ------------------------------------------------------------ mission ops
    def _new_mission(self) -> None:
        dialog = MissionDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"مأموریت {dialog.saved.number} ثبت شد.")

    def _decide_mission(self, approve: bool) -> None:
        row = self._selected(self.mission_table, self.mission_rows)
        if row is None:
            show_info(self, "مأموریت", "ابتدا یک مأموریت را انتخاب کنید.")
            return
        note = ""
        if not approve:
            note = ask_reason(self, "رد مأموریت", "دلیل رد را وارد کنید:") or ""
            if not note:
                return
        try:
            self.services.attendance.decide_mission(self.ctx, row.id, approve=approve,
                                                    note=note)
        except AppError as error:
            show_error(self, "مأموریت", error)
            return
        self.refresh()
        self.notify("مأموریت " + ("تأیید" if approve else "رد") + " شد.")

    def _approve_mission(self) -> None:
        self._decide_mission(True)

    def _reject_mission(self) -> None:
        self._decide_mission(False)

    # ----------------------------------------------------------- overtime ops
    def _new_overtime(self) -> None:
        dialog = OvertimeDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("درخواست اضافه‌کاری ثبت شد.")

    def _decide_overtime(self, approve: bool) -> None:
        row = self._selected(self.overtime_table, self.overtime_rows)
        if row is None:
            show_info(self, "اضافه‌کاری", "ابتدا یک درخواست را انتخاب کنید.")
            return
        note = ""
        if not approve:
            note = ask_reason(self, "رد اضافه‌کاری", "دلیل رد را وارد کنید:") or ""
            if not note:
                return
        try:
            self.services.attendance.decide_overtime(self.ctx, row.id, approve=approve,
                                                     note=note)
        except AppError as error:
            show_error(self, "اضافه‌کاری", error)
            return
        self.refresh()
        self.notify("اضافه‌کاری " + ("تأیید" if approve else "رد") + " شد.")

    def _approve_overtime(self) -> None:
        self._decide_overtime(True)

    def _reject_overtime(self) -> None:
        self._decide_overtime(False)
