"""کارکنان — employee files, history, movement, end of service."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.hr import constants as H
from pars_erp.services.hr_service import EmployeeFilter, EmployeeInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo, select_combo
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import EmployeePicker, masked
from pars_erp.ui.table_specs import HISTORY_COLUMNS, EMPLOYEE_COLUMNS
from pars_erp.ui.widgets.common import InfoRow, SearchInput
from pars_erp.ui.widgets.table import DataTable


class EmployeeDialog(FormDialog):
    """Create or edit an employee file."""

    title_fa = "پروندهٔ کارمند"
    save_text = "ذخیره"
    width = 760

    def __init__(self, services, ctx, *, employee_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        self.employee_id = employee_id
        self.raw: dict = {}
        if employee_id is not None:
            try:
                self.raw = services.hr.employee_form_data(ctx, employee_id)
            except AppError:
                self.raw = {}
        super().__init__(services, ctx, parent=parent,
                         subtitle="کد پرسنلی خالی بماند به‌صورت خودکار ساخته می‌شود."
                         if employee_id is None else f"ویرایش پرونده {self.raw.get('full_name', '')}")

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        raw = self.raw
        sensitive = bool(raw.get("sensitive_visible", self.can("hr.employees.sensitive")))
        self.code_edit = QLineEdit(str(raw.get("code") or ""))
        self.code_edit.setPlaceholderText("خودکار")
        self.first_edit = QLineEdit(str(raw.get("first_name") or ""))
        self.last_edit = QLineEdit(str(raw.get("last_name") or ""))
        self.add_pair(("کد پرسنلی", self.code_edit),
                      ("نام *", self.first_edit), right_required=True)
        self.add_row("نام خانوادگی *", self.last_edit, required=True)

        self.father_edit = QLineEdit(str(raw.get("father_name") or ""))
        self.national_edit = QLineEdit(str(raw.get("national_id") or ""))
        if not sensitive and not self.can("hr.employees.sensitive"):
            self.national_edit.setPlaceholderText("نیازمند مجوز مشاهدهٔ اطلاعات حساس")
        self.add_pair(("نام پدر", self.father_edit), ("کد ملی", self.national_edit))

        self.birth_edit = JalaliDateEdit(raw.get("birth_date"), allow_empty=True)
        self.birth_place_edit = QLineEdit(str(raw.get("birth_place") or ""))
        self.add_pair(("تاریخ تولد", self.birth_edit), ("محل تولد", self.birth_place_edit))

        self.gender_combo = fill_combo(QComboBox(), H.GENDERS, current=raw.get("gender"))
        self.marital_combo = fill_combo(QComboBox(), H.MARITAL_STATUSES,
                                        current=raw.get("marital_status"))
        self.add_pair(("جنسیت", self.gender_combo), ("وضعیت تأهل", self.marital_combo))

        self.children_spin = QSpinBox()
        self.children_spin.setRange(0, 30)
        self.children_spin.setValue(int(raw.get("children_count") or 0))
        self.mobile_edit = QLineEdit(str(raw.get("mobile") or ""))
        self.add_pair(("تعداد فرزند", self.children_spin), ("تلفن همراه", self.mobile_edit))

        self.phone_edit = QLineEdit(str(raw.get("phone") or ""))
        self.email_edit = QLineEdit(str(raw.get("email") or ""))
        self.add_pair(("تلفن ثابت", self.phone_edit), ("ایمیل", self.email_edit))
        self.address_edit = QLineEdit(str(raw.get("address") or ""))
        self.emergency_edit = QLineEdit(str(raw.get("emergency_contact") or ""))
        self.add_pair(("نشانی", self.address_edit), ("تماس اضطراری", self.emergency_edit))

        self.add_section("اطلاعات شغلی")
        self.hire_edit = JalaliDateEdit(raw.get("hire_date"))
        self.end_edit = JalaliDateEdit(raw.get("end_date"), allow_empty=True)
        self.add_pair(("تاریخ استخدام *", self.hire_edit),
                      ("تاریخ پایان همکاری", self.end_edit), left_required=True)

        self.employment_combo = fill_combo(QComboBox(), H.EMPLOYMENT_TYPES,
                                           current=raw.get("employment_type")
                                           or H.EMPLOYMENT_FULL_TIME)
        self.collab_combo = fill_combo(QComboBox(), H.COLLAB_STATUSES,
                                       current=raw.get("collaboration_status")
                                       or H.COLLAB_ACTIVE)
        self.add_pair(("نوع استخدام *", self.employment_combo),
                      ("وضعیت همکاری *", self.collab_combo))

        self.unit_combo = PickCombo()
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        self.unit_combo.set_value(raw.get("org_unit_id"))
        self.job_edit = QLineEdit(str(raw.get("job_title") or ""))
        self.add_pair(("واحد سازمانی", self.unit_combo), ("عنوان شغلی", self.job_edit))

        self.position_edit = QLineEdit(str(raw.get("position") or ""))
        self.manager_picker = EmployeePicker()
        self.manager_picker.attach(self.services, self.ctx)
        self.manager_picker.set_value(raw.get("manager_id"))
        self.add_pair(("پست سازمانی", self.position_edit), ("مدیر مستقیم", self.manager_picker))

        self.add_section("حقوق و اطلاعات بانکی")
        self.salary_edit = MoneyEdit()
        if raw.get("base_salary") is not None:
            self.salary_edit.set_amount(raw["base_salary"])
        self.insurance_edit = QLineEdit(str(raw.get("insurance_no") or ""))
        self.add_pair(("حقوق پایه", self.salary_edit), ("شماره بیمه", self.insurance_edit))

        self.tax_file_edit = QLineEdit(str(raw.get("tax_file_no") or ""))
        self.bank_edit = QLineEdit(str(raw.get("bank_name") or ""))
        self.add_pair(("شماره پرونده مالیاتی", self.tax_file_edit), ("بانک", self.bank_edit))
        self.account_edit = QLineEdit(str(raw.get("bank_account_no") or ""))
        self.iban_edit = QLineEdit(str(raw.get("iban") or ""))
        self.add_pair(("شماره حساب", self.account_edit), ("شبا", self.iban_edit))

        self.notes_edit = QLineEdit(str(raw.get("notes") or ""))
        self.add_row("یادداشت", self.notes_edit)
        self.active_check = QCheckBox("پرونده فعال است")
        self.active_check.setChecked(bool(raw.get("is_active", True)))
        self.add_widget(self.active_check)

    # ------------------------------------------------------------------- save
    def save(self):
        data = EmployeeInput(
            code=self.code_edit.text().strip(),
            first_name=self.first_edit.text().strip(),
            last_name=self.last_edit.text().strip(),
            person_id=self.raw.get("person_id"),
            father_name=self.father_edit.text().strip(),
            national_id=self.national_edit.text().strip(),
            birth_date=self.birth_edit.date(),
            birth_place=self.birth_place_edit.text().strip(),
            gender=self.gender_combo.currentData(),
            marital_status=self.marital_combo.currentData(),
            children_count=self.children_spin.value(),
            phone=self.phone_edit.text().strip(),
            mobile=self.mobile_edit.text().strip(),
            email=self.email_edit.text().strip(),
            address=self.address_edit.text().strip(),
            emergency_contact=self.emergency_edit.text().strip(),
            hire_date=self.hire_edit.date(),
            end_date=self.end_edit.date(),
            employment_type=str(self.employment_combo.currentData()),
            collaboration_status=str(self.collab_combo.currentData()),
            org_unit_id=self.unit_combo.value(),
            job_title=self.job_edit.text().strip(),
            position=self.position_edit.text().strip(),
            manager_id=self.manager_picker.value(),
            base_salary=self.salary_edit.amount,
            insurance_no=self.insurance_edit.text().strip(),
            tax_file_no=self.tax_file_edit.text().strip(),
            bank_name=self.bank_edit.text().strip(),
            bank_account_no=self.account_edit.text().strip(),
            iban=self.iban_edit.text().strip(),
            user_id=self.raw.get("user_id"),
            attachment_path=self.raw.get("attachment_path") or "",
            notes=self.notes_edit.text().strip(),
            is_active=self.active_check.isChecked(),
        )
        if self.employee_id is None:
            return self.services.hr.create_employee(self.ctx, data)
        return self.services.hr.update_employee(self.ctx, self.employee_id, data)


class EmployeesPage(PageBase):
    """List + detail of the employee files."""

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "کارکنان", "پروندهٔ پرسنلی، سابقهٔ تغییرات، اطلاعات شغلی و بانکی")
        self.new_button = self.header.add_action("کارمند جدید", slot=self._new)
        self.edit_button = self.header.add_action("ویرایش", variant="secondary",
                                                  slot=self._edit)
        self.history_button = self.header.add_action("تاریخچه", variant="secondary",
                                                     slot=self._history)
        self.end_button = self.header.add_action("پایان همکاری", variant="secondary",
                                                 slot=self._end_service)
        self.print_button = self.header.add_action("چاپ / PDF", variant="secondary",
                                                   slot=self._print)
        self.root.addWidget(self.header)

        bar = CardPanel("جست‌وجو و فیلتر")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی نام، کد پرسنلی یا کد ملی…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.unit_combo = PickCombo()
        row.addWidget(form_row("واحد سازمانی", self.unit_combo), 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for code, title in H.COLLAB_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت همکاری", self.status_combo), 1)
        self.type_combo = QComboBox()
        self.type_combo.addItem("همهٔ انواع استخدام", None)
        for code, title in H.EMPLOYMENT_TYPES:
            self.type_combo.addItem(title, code)
        self.type_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("نوع استخدام", self.type_combo), 1)
        self.active_only = QCheckBox("فقط شاغلان")
        self.active_only.setChecked(True)
        self.active_only.stateChanged.connect(lambda _state: self.refresh())
        row.addWidget(self.active_only)
        bar.add_layout(row)
        self.root.addWidget(bar)

        body = QHBoxLayout()
        table_card = CardPanel("فهرست کارکنان")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        table_card.add_header_widget(self.summary)
        self.table = DataTable(EMPLOYEE_COLUMNS, formatter=formatter)
        self.table.on_selection_changed(self._show_detail)
        table_card.add(self.table, 1)
        body.addWidget(table_card, 3)

        detail_card = CardPanel("جزئیات پرونده")
        detail_card.setMinimumWidth(300)
        detail_card.setMaximumWidth(360)
        self.detail_layout = QVBoxLayout()
        self.detail_layout.setSpacing(4)
        detail_card.add_layout(self.detail_layout)
        self.empty_detail = QLabel("یک کارمند را از فهرست انتخاب کنید.")
        self.empty_detail.setObjectName("HintText")
        self.empty_detail.setWordWrap(True)
        self.detail_layout.addWidget(self.empty_detail)
        self.detail_rows: dict[str, InfoRow] = {}
        for key, label in (("code", "کد پرسنلی"), ("name", "نام"), ("unit", "واحد سازمانی"),
                           ("job", "عنوان شغلی"), ("hire", "تاریخ استخدام"),
                           ("employment", "نوع استخدام"), ("status", "وضعیت همکاری"),
                           ("service", "سابقه (سال)"), ("contract", "قرارداد جاری"),
                           ("salary", "حقوق پایه"), ("mobile", "همراه"),
                           ("national_id", "کد ملی"), ("bank", "شماره حساب")):
            info = InfoRow(label)
            self.detail_rows[key] = info
            self.detail_layout.addWidget(info)
        self.detail_layout.addStretch(1)
        body.addWidget(detail_card, 1)
        self.root.addLayout(body, 1)

        self._apply_permissions()
        self.refresh()

    # ------------------------------------------------------------- permission
    def _apply_permissions(self) -> None:
        self.new_button.setEnabled(self.can("hr.employees.create"))
        self.edit_button.setEnabled(self.can("hr.employees.edit"))
        self.end_button.setEnabled(self.can("hr.employees.edit"))
        self.print_button.setEnabled(self.can("hr.print") or self.can("hr.reports"))

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.unit_combo.load(self.services.hr.unit_choices(self.ctx))
        except AppError:
            self.unit_combo.load([])
        filters = EmployeeFilter(
            search=self.search_input.text().strip(),
            org_unit_id=self.unit_combo.value(),
            collaboration_status=self.status_combo.currentData(),
            employment_type=self.type_combo.currentData(),
            active_only=self.active_only.isChecked(),
        )
        try:
            self.rows = self.services.hr.list_employees(self.ctx, filters)
        except AppError as error:
            show_error(self, "کارکنان", error)
            return
        self.set_rows(self.table, self.rows)
        active = sum(1 for row in self.rows
                     if row.collaboration_status == H.COLLAB_ACTIVE)
        self.summary.setText(f"{len(self.rows):,} پرونده — {active:,} شاغل")
        self._show_detail()

    def _selected(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self.rows):
            return None
        return self.rows[index]

    def _show_detail(self) -> None:
        row = self._selected()
        visible = row is not None
        self.empty_detail.setVisible(not visible)
        for info in self.detail_rows.values():
            info.setVisible(visible)
        if row is None:
            return
        sensitive = row.sensitive_visible
        self.detail_rows["code"].set_value(row.code)
        self.detail_rows["name"].set_value(row.full_name)
        self.detail_rows["unit"].set_value(row.org_unit_title or "—")
        self.detail_rows["job"].set_value(row.job_title or row.position or "—")
        self.detail_rows["hire"].set_value(self.formatter.date(row.hire_date))
        self.detail_rows["employment"].set_value(row.employment_type_fa)
        self.detail_rows["status"].set_value(row.collaboration_status_fa)
        self.detail_rows["service"].set_value(
            self.formatter.number(int(row.years_of_service or 0)))
        self.detail_rows["contract"].set_value(row.active_contract or "—")
        self.detail_rows["salary"].set_value(
            self.formatter.amount(row.base_salary) if sensitive else masked(None, visible=False))
        self.detail_rows["mobile"].set_value(row.mobile or "—")
        self.detail_rows["national_id"].set_value(masked(row.national_id, visible=sensitive))
        self.detail_rows["bank"].set_value(masked(row.bank_account_no, visible=sensitive))

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = EmployeeDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"پروندهٔ {dialog.saved.full_name} ایجاد شد.")

    def _edit(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "ویرایش", "ابتدا یک کارمند را انتخاب کنید.")
            return
        dialog = EmployeeDialog(self.services, self.ctx, employee_id=row.id, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"پروندهٔ {dialog.saved.full_name} به‌روزرسانی شد.")

    def _history(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "تاریخچه", "ابتدا یک کارمند را انتخاب کنید.")
            return
        try:
            history = self.services.hr.history(self.ctx, row.id)
        except AppError as error:
            show_error(self, "تاریخچه", error)
            return
        show_rows(self, f"تاریخچهٔ تغییرات — {row.full_name}", HISTORY_COLUMNS, history,
                  formatter=self.formatter,
                  subtitle="فقط رکوردهای ثبت‌شده؛ تغییر گذشته حذف نمی‌شود.")

    def _end_service(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "پایان همکاری", "ابتدا یک کارمند را انتخاب کنید.")
            return
        reason = ask_reason(self, "پایان همکاری",
                            f"علت پایان همکاری «{row.full_name}» را وارد کنید:")
        if not reason:
            return
        if not confirm(self, "پایان همکاری",
                       f"پروندهٔ {row.full_name} غیرفعال شود؟ سابقه حذف نمی‌شود.",
                       danger=True):
            return
        try:
            self.services.hr.deactivate_employee(self.ctx, row.id, reason=reason)
        except AppError as error:
            show_error(self, "پایان همکاری", error)
            return
        self.refresh()
        self.notify(f"همکاری {row.full_name} پایان یافت.")

    def _print(self) -> None:
        from pars_erp.services.report_render_service import ReportRenderer
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog
        from pars_erp.ui.pages.report_view import render_table

        try:
            table = self.services.hr_reports.staff_list(
                self.ctx, status=self.status_combo.currentData(),
                org_unit_id=self.unit_combo.value(),
                search=self.search_input.text().strip(),
                include_sensitive=self.can("hr.employees.sensitive"))
        except AppError as error:
            show_error(self, "چاپ", error)
            return
        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.persian_digits)
        ReportPreviewDialog(render_table(self.services, table), renderer,
                            parent=self).exec()
