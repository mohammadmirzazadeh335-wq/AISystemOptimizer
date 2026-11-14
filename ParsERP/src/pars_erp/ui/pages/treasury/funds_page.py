"""Bank accounts and cash boxes: definitions, balances and statements."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.funds_service import BankAccountInput, CashBoxInput
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    PickCombo,
    build_table,
    export_excel,
    show_preview,
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

BANK_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 80, "center"),
    ColumnSpec("bank_name", "بانک", TEXT, 150),
    ColumnSpec("branch_name", "شعبه", TEXT, 120),
    ColumnSpec("account_number", "شماره حساب", TEXT, 150, "center"),
    ColumnSpec("iban", "شبا", TEXT, 200, "center"),
    ColumnSpec("account_label", "حساب معین", TEXT, 190),
    ColumnSpec("opening_balance", "موجودی اولیه", AMOUNT, 130),
    ColumnSpec("balance", "موجودی", AMOUNT, 130),
    ColumnSpec("status_fa", "وضعیت", BADGE, 80, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)

CASH_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 80, "center"),
    ColumnSpec("title_fa", "صندوق", TEXT, 170),
    ColumnSpec("keeper_name", "مسئول", TEXT, 150),
    ColumnSpec("account_label", "حساب معین", TEXT, 190),
    ColumnSpec("opening_balance", "موجودی اولیه", AMOUNT, 130),
    ColumnSpec("balance", "موجودی", AMOUNT, 130),
    ColumnSpec("user_count", "کاربران مجاز", TEXT, 110, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 80, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)

MOVEMENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("movement_date", "تاریخ", DATE, 96, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 110),
    ColumnSpec("number", "سند", TEXT, 100, "center"),
    ColumnSpec("description", "شرح", TEXT, None),
    ColumnSpec("amount_in", "ورود", AMOUNT, 130),
    ColumnSpec("amount_out", "خروج", AMOUNT, 130),
    ColumnSpec("balance", "مانده", AMOUNT, 140),
)


class BankAccountDialog(QDialog):
    def __init__(self, services, ctx, *, row=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.row = row
        self.saved = None
        self.setWindowTitle("ویرایش حساب بانکی" if row else "حساب بانکی جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.code_edit = QLineEdit()
        form.addRow("کد *", self.code_edit)
        self.bank_edit = QLineEdit()
        form.addRow("نام بانک *", self.bank_edit)
        self.branch_edit = QLineEdit()
        form.addRow("شعبه", self.branch_edit)
        self.number_edit = QLineEdit()
        form.addRow("شماره حساب *", self.number_edit)
        self.iban_edit = QLineEdit()
        self.iban_edit.setPlaceholderText("IR" + "۰" * 24)
        form.addRow("شبا", self.iban_edit)
        self.card_edit = QLineEdit()
        form.addRow("شماره کارت", self.card_edit)
        self.holder_edit = QLineEdit()
        form.addRow("صاحب حساب", self.holder_edit)
        self.account_combo = PickCombo()
        try:
            self.account_combo.load(services.accounts.choices(ctx, level="subsidiary"))
        except AppError:
            self.account_combo.load([])
        form.addRow("حساب معین *", self.account_combo)
        self.parent_combo = PickCombo()
        try:
            self.parent_combo.load([
                (row.id, f"{row.code} — {row.title_fa}")
                for row in services.accounts.list_accounts(ctx)
                if row.code in (TC.DEFAULT_BANK_PARENT_CODE, TC.DEFAULT_CASH_PARENT_CODE)])
        except AppError:
            self.parent_combo.load([])
        form.addRow("یا ایجاد معین زیر حساب", self.parent_combo)
        self.currency_edit = QLineEdit("IRR")
        form.addRow("ارز", self.currency_edit)
        self.opening_edit = MoneyEdit()
        form.addRow("موجودی اولیه", self.opening_edit)
        self.opening_date = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ موجودی اولیه", self.opening_date)
        self.active_check = QCheckBox("حساب فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(52)
        form.addRow("توضیحات", self.description_edit)
        layout.addLayout(form)
        hint = QLabel("اگر «حساب معین» انتخاب نشود، برنامه معین اختصاصی همین حساب را "
                      "زیر حساب بانک‌ها ایجاد می‌کند؛ دو حساب نمی‌توانند یک معین داشته باشند.")
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
        if row is not None:
            self.code_edit.setText(row.code)
            self.bank_edit.setText(row.bank_name)
            self.branch_edit.setText(row.branch_name)
            self.number_edit.setText(row.account_number)
            self.iban_edit.setText(row.iban)
            self.card_edit.setText(row.card_number)
            self.holder_edit.setText(row.holder_name)
            self.account_combo.set_value(row.account_id)
            self.currency_edit.setText(row.currency_code)
            self.opening_edit.set_amount(row.opening_balance)
            self.opening_date.set_date(row.opening_date)
            self.active_check.setChecked(row.is_active)
            self.description_edit.setPlainText(row.description)

    def _save(self) -> None:
        data = BankAccountInput(
            code=self.code_edit.text().strip(), bank_name=self.bank_edit.text().strip(),
            account_number=self.number_edit.text().strip(),
            account_id=self.account_combo.value() or None,
            parent_account_id=self.parent_combo.value() or None,
            branch_name=self.branch_edit.text().strip(),
            iban=self.iban_edit.text().strip(), card_number=self.card_edit.text().strip(),
            holder_name=self.holder_edit.text().strip(),
            currency_code=self.currency_edit.text().strip() or "IRR",
            opening_balance=self.opening_edit.amount,
            opening_date=self.opening_date.date(),
            is_active=self.active_check.isChecked(),
            description=self.description_edit.toPlainText().strip())
        try:
            if self.row is None:
                self.saved = self.services.funds.create_bank_account(self.ctx, data)
            else:
                self.saved = self.services.funds.update_bank_account(
                    self.ctx, self.row.id, data)
        except AppError as error:
            show_error(self, "حساب بانکی", error)
            return
        self.accept()


class CashBoxDialog(QDialog):
    def __init__(self, services, ctx, *, row=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.row = row
        self.saved = None
        self.setWindowTitle("ویرایش صندوق" if row else "صندوق جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        basic = QWidget()
        form = QFormLayout(basic)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.code_edit = QLineEdit()
        form.addRow("کد *", self.code_edit)
        self.title_edit = QLineEdit()
        form.addRow("نام صندوق *", self.title_edit)
        self.keeper_edit = QLineEdit()
        form.addRow("مسئول صندوق", self.keeper_edit)
        self.account_combo = PickCombo()
        try:
            self.account_combo.load(services.accounts.choices(ctx, level="subsidiary"))
        except AppError:
            self.account_combo.load([])
        form.addRow("حساب معین", self.account_combo)
        self.parent_combo = PickCombo()
        try:
            self.parent_combo.load([
                (row.id, f"{row.code} — {row.title_fa}")
                for row in services.accounts.list_accounts(ctx)
                if row.code == TC.DEFAULT_CASH_PARENT_CODE])
        except AppError:
            self.parent_combo.load([])
        form.addRow("یا ایجاد معین زیر", self.parent_combo)
        self.opening_edit = MoneyEdit()
        form.addRow("موجودی اولیه", self.opening_edit)
        self.opening_date = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ موجودی اولیه", self.opening_date)
        self.active_check = QCheckBox("صندوق فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(52)
        form.addRow("توضیحات", self.description_edit)
        tabs.addTab(basic, "مشخصات")

        access = QWidget()
        access_layout = QVBoxLayout(access)
        access_hint = QLabel("اگر هیچ کاربری انتخاب نشود، همهٔ کاربران دارای مجوز صندوق "
                             "به آن دسترسی دارند.")
        access_hint.setObjectName("HintText")
        access_hint.setWordWrap(True)
        access_layout.addWidget(access_hint)
        self.users_table = DataTable((
            ColumnSpec("pick", "انتخاب", TEXT, 70, "center"),
            ColumnSpec("full_name", "کاربر", TEXT, None),
            ColumnSpec("roles_fa", "نقش‌ها", TEXT, 200),
        ))
        access_layout.addWidget(self.users_table, 1)
        self._user_rows = []
        tabs.addTab(access, "دسترسی کاربران")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_users(row.allowed_users if row is not None else ())
        if row is not None:
            self.code_edit.setText(row.code)
            self.title_edit.setText(row.title_fa)
            self.keeper_edit.setText(row.keeper_name)
            self.account_combo.set_value(row.account_id)
            self.opening_edit.set_amount(row.opening_balance)
            self.opening_date.set_date(row.opening_date)
            self.active_check.setChecked(row.is_active)
            self.description_edit.setPlainText(row.description)

    def _load_users(self, allowed: tuple[int, ...]) -> None:
        try:
            users = self.services.users.list_users(self.ctx)
        except AppError:
            users = []
        rows = []
        for user in users:
            rows.append({"id": user.id, "full_name": user.full_name,
                         "roles_fa": "، ".join(user.role_codes),
                         "pick": "✓" if user.id in allowed else ""})
        self._user_rows = rows
        self.users_table.set_rows(rows)

    def _selected_users(self) -> tuple[int, ...]:
        chosen = []
        model = self.users_table.model
        for index, row in enumerate(model.rows()):
            text = str(row.get("pick", "") or "").strip()
            if text in ("✓", "1", "بله", "true", "True"):
                chosen.append(int(row["id"]))
        return tuple(chosen)

    def _save(self) -> None:
        data = CashBoxInput(
            code=self.code_edit.text().strip(), title_fa=self.title_edit.text().strip(),
            account_id=self.account_combo.value() or None,
            parent_account_id=self.parent_combo.value() or None,
            keeper_name=self.keeper_edit.text().strip(),
            opening_balance=self.opening_edit.amount,
            opening_date=self.opening_date.date(),
            is_active=self.active_check.isChecked(),
            description=self.description_edit.toPlainText().strip())
        try:
            if self.row is None:
                self.saved = self.services.funds.create_cash_box(self.ctx, data)
            else:
                self.saved = self.services.funds.update_cash_box(self.ctx, self.row.id, data)
            self.services.funds.set_cash_box_users(
                self.ctx, self.saved.id, self._selected_users())
        except AppError as error:
            show_error(self, "صندوق", error)
            return
        self.accept()


class _FundsPageBase(PageBase):
    """Shared layout: filter bar, table, statement panel and reporting."""

    columns: tuple[ColumnSpec, ...] = ()
    dialog_class = None
    title_fa = ""
    subtitle_fa = ""

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows: list = []
        self.movements: list = []
        self.header = PageHeader(self.title_fa, self.subtitle_fa)
        self.header.add_action("تعریف جدید", slot=self._create)
        self.header.add_action("ویرایش", variant="secondary", slot=self._edit)
        self.header.add_action("فعال/غیرفعال", variant="secondary", slot=self._toggle)
        self.header.add_action("صورت‌حساب", variant="secondary", slot=self._statement)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)
        self.table = DataTable(self.columns, formatter=formatter)
        self.table.rowActivated.connect(lambda _row: self._edit())
        card = CardPanel("فهرست")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 2)
        self.movement_table = DataTable(MOVEMENT_COLUMNS, formatter=formatter)
        statement_card = CardPanel("صورت‌حساب / گردش")
        self.statement_label = QLabel("یک ردیف را انتخاب کنید و «صورت‌حساب» را بزنید.")
        self.statement_label.setObjectName("HintText")
        statement_card.add_header_widget(self.statement_label)
        statement_card.add(self.movement_table, 1)
        self.root.addWidget(statement_card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def _load(self) -> list:
        raise NotImplementedError

    def refresh(self) -> None:
        try:
            self.rows = self._load()
        except AppError as error:
            show_error(self, self.title_fa, error)
            return
        self.table.set_rows(self.rows)
        total = sum((row.balance for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} مورد — جمع موجودی {total:,}")

    def _selected(self):
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        return self.rows[index.row()]

    # --------------------------------------------------------------- actions
    def _create(self) -> None:
        dialog = self.dialog_class(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit("تعریف جدید ذخیره شد.")

    def _edit(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "ویرایش", "یک ردیف را انتخاب کنید.")
            return
        dialog = self.dialog_class(self.services, self.ctx, row=row, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit("تغییرات ذخیره شد.")

    def _toggle(self) -> None:
        raise NotImplementedError

    def _movements_of(self, row) -> list:
        raise NotImplementedError

    def _statement(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "صورت‌حساب", "یک ردیف را انتخاب کنید.")
            return
        try:
            self.movements = self._movements_of(row)
        except AppError as error:
            show_error(self, "صورت‌حساب", error)
            return
        self.movement_table.set_rows(self.movements)
        closing = self.movements[-1].balance if self.movements else Decimal("0")
        self.statement_label.setText(
            f"{row.code} — {len(self.movements):,} ردیف — مانده پایانی {closing:,}")

    # ------------------------------------------------------------- reporting
    def _table(self):
        headers = tuple(column.title_fa for column in self.columns)
        rows = []
        for row in self.rows:
            values = []
            for column in self.columns:
                value = column.value_of(row)
                values.append(value if value is not None else "")
            rows.append(tuple(values))
        return build_table(self.title_fa, headers, tuple(rows),
                           meta=f"{len(self.rows):,} مورد",
                           company=self.services.settings.snapshot().company_name)

    def _print(self) -> None:
        show_preview(self, self.services, self._table())

    def _excel(self) -> None:
        export_excel(self, self.services, self._table(), prefix="funds")


class BankAccountsPage(_FundsPageBase):
    columns = BANK_COLUMNS

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.dialog_class = BankAccountDialog
        self.title_fa = "حساب‌های بانکی"
        self.subtitle_fa = ("شبا، کارت، حساب معین، موجودی و صورت‌حساب؛ هر حساب یک معین "
                            "اختصاصی دارد")
        super().__init__(services, ctx, formatter, parent)

    def _load(self) -> list:
        return self.services.funds.list_bank_accounts(self.ctx)

    def _toggle(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "وضعیت", "یک حساب را انتخاب کنید.")
            return
        try:
            self.services.funds.set_bank_account_active(self.ctx, row.id, not row.is_active)
        except AppError as error:
            show_error(self, "وضعیت حساب", error)
            return
        self.refresh()

    def _movements_of(self, row) -> list:
        return self.services.funds.fund_movements(self.ctx, bank_account_id=row.id)


class CashBoxesPage(_FundsPageBase):
    columns = CASH_COLUMNS

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.dialog_class = CashBoxDialog
        self.title_fa = "صندوق‌ها"
        self.subtitle_fa = "چند صندوق مستقل، مسئول صندوق، دسترسی کاربران و گردش صندوق"
        super().__init__(services, ctx, formatter, parent)

    def _load(self) -> list:
        rows = self.services.funds.list_cash_boxes(self.ctx)
        return [_CashRow(row) for row in rows]

    def _toggle(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "وضعیت", "یک صندوق را انتخاب کنید.")
            return
        current = self.services.funds.get_cash_box(self.ctx, row.id)
        try:
            self.services.funds.update_cash_box(self.ctx, row.id, CashBoxInput(
                code=current.code, title_fa=current.title_fa,
                account_id=current.account_id, keeper_name=current.keeper_name,
                opening_balance=current.opening_balance,
                opening_date=current.opening_date,
                is_active=not current.is_active, description=current.description))
        except AppError as error:
            show_error(self, "وضعیت صندوق", error)
            return
        self.refresh()

    def _movements_of(self, row) -> list:
        return self.services.funds.fund_movements(self.ctx, cash_box_id=row.id)


class _CashRow:
    """Cash-box row plus the number of users explicitly allowed on it."""

    def __init__(self, row) -> None:
        self._row = row

    def __getattr__(self, item):
        return getattr(self._row, item)

    @property
    def user_count(self) -> str:
        return f"{len(self._row.allowed_users):,}"
