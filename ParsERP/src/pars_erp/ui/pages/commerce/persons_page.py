"""Customers and suppliers (persons) with ledger balance and turnover."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.services.persons_service import PersonFilter, PersonInput, PersonRow
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import confirm
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

PERSON_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 96, "center"),
    ColumnSpec("name", "نام شخص", TEXT, None),
    ColumnSpec("roles_fa", "نقش", TEXT, 140),
    ColumnSpec("person_type_fa", "نوع", TEXT, 70, "center"),
    ColumnSpec("mobile", "همراه", TEXT, 110, "center"),
    ColumnSpec("phone", "تلفن", TEXT, 110, "center"),
    ColumnSpec("economic_code", "کد اقتصادی", TEXT, 120, "center"),
    ColumnSpec("credit_limit", "سقف اعتبار", AMOUNT, 110),
    ColumnSpec("balance", "مانده", AMOUNT, 120),
    ColumnSpec("account_label", "حساب معین", TEXT, 190),
    ColumnSpec("status_fa", "وضعیت", BADGE, 74, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)


class PersonDialog(QDialog):
    def __init__(self, services, ctx, *, person: PersonRow | None = None,
                 default_role: str = "customer", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.person = person
        self.saved: PersonRow | None = None
        self.setWindowTitle("ویرایش شخص" if person else "شخص جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        tabs = QTabWidget()

        basic = QWidget()
        form = QFormLayout(basic)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.code_edit = QLineEdit()
        form.addRow("کد شخص *", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("نام / عنوان *", self.name_edit)
        self.role_combo = QComboBox()
        for role, title in (("customer", "مشتری"), ("supplier", "تأمین‌کننده"),
                            ("both", "مشتری و تأمین‌کننده")):
            self.role_combo.addItem(title, role)
        form.addRow("نقش", self.role_combo)
        self.type_combo = QComboBox()
        for person_type in CC.PERSON_TYPES:
            self.type_combo.addItem(CC.PERSON_TYPE_TITLES_FA[person_type], person_type)
        form.addRow("نوع شخص", self.type_combo)
        self.phone_edit = QLineEdit()
        form.addRow("تلفن", self.phone_edit)
        self.mobile_edit = QLineEdit()
        form.addRow("همراه", self.mobile_edit)
        self.email_edit = QLineEdit()
        form.addRow("ایمیل", self.email_edit)
        self.address_edit = QPlainTextEdit()
        self.address_edit.setFixedHeight(52)
        form.addRow("نشانی", self.address_edit)
        tabs.addTab(basic, "مشخصات")

        legal = QWidget()
        lf = QFormLayout(legal)
        lf.setSpacing(8)
        lf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.national_edit = QLineEdit()
        lf.addRow("کد ملی / شناسه ملی", self.national_edit)
        self.economic_edit = QLineEdit()
        lf.addRow("کد اقتصادی", self.economic_edit)
        self.registration_edit = QLineEdit()
        lf.addRow("شماره ثبت", self.registration_edit)
        self.credit_limit = MoneyEdit()
        lf.addRow("سقف اعتبار", self.credit_limit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(52)
        lf.addRow("توضیحات", self.description_edit)
        self.active_check = QCheckBox("شخص فعال است")
        self.active_check.setChecked(True)
        lf.addRow("", self.active_check)
        tabs.addTab(legal, "اعتبار و شناسه‌ها")
        layout.addWidget(tabs)

        hint = QLabel("حساب معین به‌صورت خودکار از کدینگ حسابداری انتخاب می‌شود "
                      "(مشتری: حساب‌های دریافتنی، تأمین‌کننده: حساب‌های پرداختنی).")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if person is not None:
            self._load(person)
        else:
            self.role_combo.setCurrentIndex(
                max(0, self.role_combo.findData(default_role)))

    def _load(self, person: PersonRow) -> None:
        self.code_edit.setText(person.code)
        self.name_edit.setText(person.name)
        self.role_combo.setCurrentIndex(max(0, self.role_combo.findData(person.role)))
        self.type_combo.setCurrentIndex(
            max(0, self.type_combo.findData(person.person_type)))
        self.phone_edit.setText(person.phone)
        self.mobile_edit.setText(person.mobile)
        self.email_edit.setText(person.email)
        self.address_edit.setPlainText(person.address)
        self.national_edit.setText(person.national_id)
        self.economic_edit.setText(person.economic_code)
        self.registration_edit.setText(person.registration_no)
        self.credit_limit.set_amount(person.credit_limit)
        self.description_edit.setPlainText(person.description)
        self.active_check.setChecked(person.is_active)

    def _save(self) -> None:
        data = PersonInput(
            code=self.code_edit.text().strip(),
            name=self.name_edit.text().strip(),
            role=str(self.role_combo.currentData()),
            person_type=str(self.type_combo.currentData()),
            phone=self.phone_edit.text().strip(),
            mobile=self.mobile_edit.text().strip(),
            email=self.email_edit.text().strip(),
            address=self.address_edit.toPlainText().strip(),
            national_id=self.national_edit.text().strip(),
            economic_code=self.economic_edit.text().strip(),
            registration_no=self.registration_edit.text().strip(),
            credit_limit=self.credit_limit.amount,
            description=self.description_edit.toPlainText().strip(),
            is_active=self.active_check.isChecked(),
        )
        try:
            if self.person is None:
                self.saved = self.services.persons.create(self.ctx, data)
            else:
                self.saved = self.services.persons.update(self.ctx, self.person.id, data)
        except AppError as error:
            show_error(self, "ثبت شخص", error)
            return
        self.accept()


class PersonAccountDialog(QDialog):
    """Invoices, turnover and the subsidiary ledger of one person."""

    def __init__(self, services, ctx, person: PersonRow, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"حساب شخص — {person.name}")
        self.resize(960, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        head = QLabel(f"{person.code} — {person.name} | {person.roles_fa} | "
                      f"مانده: {person.balance_fa}")
        head.setObjectName("SectionTitle")
        layout.addWidget(head)
        try:
            turnover = services.persons.turnover(ctx, person.id)
            summary = QLabel(
                f"خرید خالص: {turnover.net_purchase:,}   |   "
                f"فروش خالص: {turnover.net_sale:,}   |   "
                f"سقف اعتبار: {person.credit_limit:,}")
            summary.setObjectName("HintText")
            layout.addWidget(summary)
        except AppError as error:
            show_error(self, "گردش شخص", error)

        tabs = QTabWidget()
        invoices = DataTable((
            ColumnSpec("number", "شماره", TEXT, 140, "center"),
            ColumnSpec("invoice_date", "تاریخ", DATE, 100, "center"),
            ColumnSpec("kind_fa", "نوع", TEXT, 130),
            ColumnSpec("net_total", "مبلغ خالص", AMOUNT, 130),
            ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
        ))
        invoices.set_rows(services.persons.invoices(ctx, person.id))
        tabs.addTab(invoices, "فاکتورها")

        ledger = DataTable((
            ColumnSpec("entry_date", "تاریخ", DATE, 100, "center"),
            ColumnSpec("number", "شماره سند", TEXT, 90, "center"),
            ColumnSpec("title", "شرح", TEXT, None),
            ColumnSpec("account_label", "حساب", TEXT, 200),
            ColumnSpec("debit", "بدهکار", AMOUNT, 120),
            ColumnSpec("credit", "بستانکار", AMOUNT, 120),
            ColumnSpec("balance", "مانده", AMOUNT, 120),
        ))
        ledger.set_rows(services.persons.statement(ctx, person.id))
        tabs.addTab(ledger, "دفتر معین")
        layout.addWidget(tabs, 1)

        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignLeft)


class PersonsPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header = PageHeader("مشتریان و تأمین‌کنندگان",
                                 "اشخاص حقیقی و حقوقی، سقف اعتبار، مانده حساب و گردش")
        self.header.add_action("شخص جدید", slot=self._new)
        self.header.add_action("ویرایش", variant="secondary", slot=self._edit)
        self.header.add_action("حساب و گردش", variant="secondary", slot=self._account)
        self.header.add_action("غیرفعال/فعال", variant="ghost", slot=self._toggle)
        self.root.addWidget(self.header)

        filters = CardPanel("جست‌وجو و فیلتر")
        row = QHBoxLayout()
        self.search = SearchInput("جست‌وجو با نام، کد، تلفن یا کد ملی…")
        self.search.searchChanged.connect(self.refresh)
        row.addWidget(self.search, 2)
        self.role_combo = QComboBox()
        for label, value in (("همه", None), ("مشتریان", "customer"),
                             ("تأمین‌کنندگان", "supplier")):
            self.role_combo.addItem(label, value)
        self.role_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.role_combo, 1)
        self.type_combo = QComboBox()
        self.type_combo.addItem("همهٔ انواع", None)
        for person_type in CC.PERSON_TYPES:
            self.type_combo.addItem(CC.PERSON_TYPE_TITLES_FA[person_type], person_type)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.type_combo, 1)
        self.debt_check = QCheckBox("فقط بدهکاران")
        self.debt_check.stateChanged.connect(self.refresh)
        row.addWidget(self.debt_check)
        filters.add_layout(row)
        self.root.addWidget(filters)

        self.table = DataTable(PERSON_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._edit())
        card = CardPanel("فهرست اشخاص")
        self.count_label = QLabel("")
        self.count_label.setObjectName("HintText")
        card.add_header_widget(self.count_label)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.services.persons.list_persons(self.ctx, PersonFilter(
                search=self.search.text().strip(),
                role=self.role_combo.currentData(),
                person_type=self.type_combo.currentData(),
                has_debt=self.debt_check.isChecked()))
        except AppError as error:
            show_error(self, "فهرست اشخاص", error)
            return
        self.table.set_rows(rows)
        self.count_label.setText(f"{len(rows):,} شخص")

    def _selected(self) -> PersonRow | None:
        index = self.table.selected_row_index()
        if index is None:
            show_info(self, "انتخاب شخص", "ابتدا یک شخص را از فهرست انتخاب کنید.")
            return None
        return self.table.model.row_at(index)

    def _new(self) -> None:
        role = self.role_combo.currentData() or "customer"
        dialog = PersonDialog(self.services, self.ctx, default_role=role, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"شخص «{dialog.saved.name}» ثبت شد.")

    def _edit(self) -> None:
        person = self._selected()
        if person is None:
            return
        dialog = PersonDialog(self.services, self.ctx, person=person, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"شخص «{dialog.saved.name}» به‌روزرسانی شد.")

    def _account(self) -> None:
        person = self._selected()
        if person is None:
            return
        PersonAccountDialog(self.services, self.ctx, person, parent=self).exec()

    def _toggle(self) -> None:
        person = self._selected()
        if person is None:
            return
        action = "غیرفعال" if person.is_active else "فعال"
        if not confirm(self, f"{action}سازی شخص",
                       f"شخص «{person.name}» {action} شود؟", danger=person.is_active):
            return
        try:
            self.services.persons.set_active(self.ctx, person.id, not person.is_active)
        except AppError as error:
            show_error(self, "تغییر وضعیت شخص", error)
            return
        self.refresh()
        self.notify(f"شخص «{person.name}» {action} شد.")
