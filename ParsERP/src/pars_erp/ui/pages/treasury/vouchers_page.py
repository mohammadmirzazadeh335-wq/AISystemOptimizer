"""Receipts and payments (one editor, four screens).

The same editor serves «دریافت وجه», «پرداخت وجه», «دریافت از مشتری» and «پرداخت به
تأمین‌کننده»: the page only changes the default document type and which party list
it preloads. Every save goes through :class:`pars_erp.services.voucher_service` so
the journal, the allocation and the cheque are created in one transaction.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.voucher_service import (
    AllocationInput,
    ChequeInput,
    PaymentInput,
    ReceiptInput,
    VoucherRow,
)
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    FundPicker,
    PickCombo,
    ask_reason,
    build_table,
    confirm,
    export_excel,
    form_row,
    show_preview,
    status_key,
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

VOUCHER_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره سند", TEXT, 128, "center"),
    ColumnSpec("voucher_date", "تاریخ", DATE, 96, "center"),
    ColumnSpec("type_fa", "نوع", TEXT, 130),
    ColumnSpec("method_fa", "روش", TEXT, 96, "center"),
    ColumnSpec("fund_label", "صندوق / بانک", TEXT, 170),
    ColumnSpec("party_name", "طرف حساب", TEXT, None),
    ColumnSpec("amount", "مبلغ", AMOUNT, 130),
    ColumnSpec("currency_code", "ارز", TEXT, 58, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 110, "center",
               getter=lambda row: status_key(row.status)),
    ColumnSpec("tracking_no", "پیگیری", TEXT, 100, "center"),
)


class VoucherDialog(QDialog):
    """Create or edit one receipt/payment with settlement allocations."""

    def __init__(self, services, ctx, family: str, *,
                 voucher: VoucherRow | None = None,
                 party_detail_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.family = family
        self.voucher = voucher
        self.saved: VoucherRow | None = None
        self.is_receipt = family == "receipt"
        title = "رسید دریافت" if self.is_receipt else "سند پرداخت"
        self.setWindowTitle(f"ویرایش {title}" if voucher else f"{title} جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        tabs = QTabWidget()
        tabs.addTab(self._build_main(), "مشخصات")
        tabs.addTab(self._build_allocations(), "تسویه فاکتورها")
        self.cheque_tab = self._build_cheque()
        tabs.addTab(self.cheque_tab, "چک")
        self.tabs = tabs
        root.addWidget(tabs)

        self.hint = QLabel("")
        self.hint.setObjectName("HintText")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره پیش‌نویس", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.fund_picker.attach(services, ctx)
        self._load_choices()
        if voucher is not None:
            self._load(voucher)
        elif party_detail_id:
            self.party_combo.set_value(party_detail_id)
        self.party_combo.currentIndexChanged.connect(
            lambda _index: self._fill_open_invoices())
        self.method_combo.currentIndexChanged.connect(self._sync_method)
        self.type_combo.currentIndexChanged.connect(self._sync_method)
        self._sync_method()

    # ------------------------------------------------------------------ build
    def _build_main(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ *", self.date_edit)
        self.type_combo = QComboBox()
        for code, title in (TC.RECEIPT_TYPES if self.is_receipt else TC.PAYMENT_TYPES):
            self.type_combo.addItem(title, code)
        form.addRow("نوع سند", self.type_combo)
        self.method_combo = QComboBox()
        methods = TC.RECEIPT_METHODS if self.is_receipt else TC.PAYMENT_METHODS
        for code, title in methods:
            self.method_combo.addItem(title, code)
        form.addRow("روش", self.method_combo)
        self.fund_picker = FundPicker()
        form.addRow("محل نگهداری", self.fund_picker)
        self.party_combo = PickCombo()
        form.addRow("مشتری" if self.is_receipt else "تأمین‌کننده", self.party_combo)
        self.party_name_edit = QLineEdit()
        self.party_name_edit.setPlaceholderText("اگر طرف حساب در فهرست نیست، نام را بنویسید")
        form.addRow("نام طرف حساب", self.party_name_edit)
        self.amount_edit = MoneyEdit()
        form.addRow("مبلغ *", self.amount_edit)
        self.currency_combo = QComboBox()
        form.addRow("ارز", self.currency_combo)
        self.rate_edit = QLineEdit("1")
        form.addRow("نرخ تبدیل", self.rate_edit)
        self.counter_combo = PickCombo()
        form.addRow("حساب طرف مقابل", self.counter_combo)
        self.tracking_edit = QLineEdit()
        form.addRow("شماره پیگیری", self.tracking_edit)
        self.reference_edit = QLineEdit()
        form.addRow("شماره مرجع", self.reference_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(54)
        form.addRow("شرح", self.description_edit)
        return page

    def _build_allocations(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        info = QLabel("مانده هر فاکتور نمایش داده می‌شود؛ مبلغ تخصیص را می‌توانید "
                      "کامل یا جزئی وارد کنید.")
        info.setObjectName("HintText")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.alloc_table = QTableWidget(0, 6)
        self.alloc_table.setHorizontalHeaderLabels(
            ["شماره فاکتور", "تاریخ", "مبلغ فاکتور", "تسویه‌شده", "مانده", "تخصیص"])
        self.alloc_table.verticalHeader().setVisible(False)
        self.alloc_table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self.alloc_table, 1)
        row = QHBoxLayout()
        full = QPushButton("تخصیص کامل مانده")
        full.clicked.connect(self._allocate_full)
        clear = QPushButton("پاک‌کردن تخصیص‌ها")
        clear.clicked.connect(self._clear_allocations)
        row.addWidget(full)
        row.addWidget(clear)
        row.addStretch(1)
        self.alloc_total = QLabel("جمع تخصیص: ۰")
        row.addWidget(self.alloc_total)
        layout.addLayout(row)
        return page

    def _build_cheque(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cheque_number = QLineEdit()
        form.addRow("شماره چک *", self.cheque_number)
        self.cheque_bank = QLineEdit()
        form.addRow("بانک *", self.cheque_bank)
        self.cheque_branch = QLineEdit()
        form.addRow("شعبه", self.cheque_branch)
        self.cheque_issue = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ صدور", self.cheque_issue)
        self.cheque_due = JalaliDateEdit(_dt.date.today() + _dt.timedelta(days=30))
        form.addRow("سررسید *", self.cheque_due)
        self.cheque_book = PickCombo()
        form.addRow("دسته‌چک", self.cheque_book)
        self.cheque_holder = QLineEdit()
        form.addRow("صاحب چک", self.cheque_holder)
        return page

    # --------------------------------------------------------------- populate
    def _load_choices(self) -> None:
        services, ctx = self.services, self.ctx
        role = "customer" if self.is_receipt else "supplier"
        try:
            self.party_combo.load(services.persons.choices(ctx, role=role))
        except AppError:
            self.party_combo.load([])
        try:
            self.counter_combo.load(
                services.accounts.choices(ctx, level="subsidiary"))
        except AppError:
            self.counter_combo.load([])
        currencies: list[tuple[str, str]] = [("IRR", "ریال")]
        try:
            for code, title in services.currency.currency_choices():
                if code != "IRR":
                    currencies.append((code, f"{code} — {title}"))
        except AppError:
            pass
        for code, title in currencies:
            self.currency_combo.addItem(title, code)
        try:
            self.cheque_book.load([
                (row.id, f"{row.serial_no} ({row.first_no}–{row.last_no})")
                for row in services.cheques.list_books(ctx)])
        except AppError:
            self.cheque_book.load([])

    def _load(self, voucher: VoucherRow) -> None:
        self.date_edit.set_date(voucher.voucher_date)
        self._set_combo(self.type_combo, voucher.type_code)
        self._set_combo(self.method_combo, voucher.method)
        self.amount_edit.set_amount(voucher.amount)
        self._set_combo(self.currency_combo, voucher.currency_code)
        self.rate_edit.setText(str(voucher.exchange_rate))
        self.party_combo.set_value(voucher.party_detail_id)
        self.party_name_edit.setText(voucher.party_name
                                     if not voucher.party_detail_id else "")
        self.tracking_edit.setText(voucher.tracking_no)
        self.reference_edit.setText(voucher.reference_no)
        self.description_edit.setPlainText(voucher.description)
        self._load_allocations(voucher)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _load_allocations(self, voucher: VoucherRow) -> None:
        try:
            allocated = {row["invoice_id"]: row for row in
                         self.services.vouchers.allocations_of(
                             self.ctx, voucher.kind, voucher.id)}
        except AppError:
            allocated = {}
        self._fill_open_invoices(allocated, voucher.party_detail_id)

    def _fill_open_invoices(self, allocated: dict | None = None,
                            party_detail_id: int | None = None) -> None:
        allocated = allocated or {}
        direction = "receipt" if self.is_receipt else "payment"
        party = party_detail_id if party_detail_id is not None else self.party_combo.value()
        try:
            rows = self.services.vouchers.open_invoices(
                self.ctx, direction=direction, party_detail_id=party)
        except AppError:
            rows = []
        self.alloc_table.setRowCount(0)
        currency = self.currency_combo.currentData()
        for row in rows:
            position = self.alloc_table.rowCount()
            self.alloc_table.insertRow(position)
            for column, text in enumerate((
                    row.number, self.formatter_date(row.invoice_date),
                    f"{row.net_total:,}", f"{row.settled:,}", f"{row.open_amount:,}")):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.alloc_table.setItem(position, column, item)
            money = MoneyEdit()
            existing = allocated.get(row.id)
            money.set_amount(existing["amount"] if existing else 0)
            money.valueChanged.connect(self._recalc_total)
            self.alloc_table.setCellWidget(position, 5, money)
            self.alloc_table.item(position, 0).setData(Qt.ItemDataRole.UserRole, row.id)
        self._recalc_total()

    def formatter_date(self, value: _dt.date) -> str:
        from pars_erp.ui.formatting import Formatter

        settings = self.services.settings.snapshot()
        return Formatter(persian_digits=settings.persian_digits).date(value)

    def _allocate_full(self) -> None:
        for row in range(self.alloc_table.rowCount()):
            item = self.alloc_table.item(row, 4)
            money = self.alloc_table.cellWidget(row, 5)
            if item and money is not None:
                money.set_amount(Decimal(item.text().replace(",", "")
                                         .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))))
        self._recalc_total()

    def _clear_allocations(self) -> None:
        for row in range(self.alloc_table.rowCount()):
            money = self.alloc_table.cellWidget(row, 5)
            if money is not None:
                money.set_amount(0)
        self._recalc_total()

    def _recalc_total(self) -> None:
        total = Decimal("0")
        for row in range(self.alloc_table.rowCount()):
            money = self.alloc_table.cellWidget(row, 5)
            if money is not None:
                total += money.amount
        self.alloc_total.setText(f"جمع تخصیص: {total:,}")

    # ------------------------------------------------------------------ state
    def _sync_method(self) -> None:
        method = str(self.method_combo.currentData())
        is_cheque = method == TC.METHOD_CHEQUE
        self.tabs.setTabEnabled(2, is_cheque)
        if not is_cheque and self.tabs.currentIndex() == 2:
            self.tabs.setCurrentIndex(0)
        receipt_type = str(self.type_combo.currentData())
        needs_counter = (receipt_type in (TC.RECEIPT_OTHER,)
                         or (not self.is_receipt and receipt_type in (
                             TC.PAYMENT_EXPENSE, TC.PAYMENT_SALARY)))
        self.counter_combo.setEnabled(needs_counter)
        self.hint.setText(
            "برای این نوع سند، حساب طرف مقابل الزامی است."
            if needs_counter else
            "حساب‌های دریافتنی/پرداختنی از الگوی ثبت خوانده می‌شود.")

    # ------------------------------------------------------------------- save
    def _allocations(self) -> tuple[AllocationInput, ...]:
        rows: list[AllocationInput] = []
        for row in range(self.alloc_table.rowCount()):
            money = self.alloc_table.cellWidget(row, 5)
            item = self.alloc_table.item(row, 0)
            if money is None or item is None:
                continue
            amount = money.amount
            if amount <= 0:
                continue
            rows.append(AllocationInput(
                invoice_id=int(item.data(Qt.ItemDataRole.UserRole)), amount=amount))
        return tuple(rows)

    def _cheque_input(self) -> ChequeInput | None:
        if str(self.method_combo.currentData()) != TC.METHOD_CHEQUE:
            return None
        number = self.cheque_number.text().strip()
        bank = self.cheque_bank.text().strip()
        if not number or not bank:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("برای پرداخت/دریافت با چک، شماره و بانک چک لازم است.",
                                  field="cheque")
        try:
            amount = self.amount_edit.amount
        except Exception:
            amount = 0
        return ChequeInput(
            number=number, bank_name=bank, amount=amount,
            issue_date=self.cheque_issue.date() or _dt.date.today(),
            due_date=self.cheque_due.date() or _dt.date.today(),
            branch_name=self.cheque_branch.text().strip(),
            holder_name=self.cheque_holder.text().strip(),
            cheque_book_id=self.cheque_book.value())

    def _save(self) -> None:
        try:
            kind, fund_id = self.fund_picker.require()
            amount = self.amount_edit.amount
            rate = Decimal(self.rate_edit.text() or "1")
            cash_box_id = fund_id if kind == TC.FUND_CASH else None
            bank_account_id = fund_id if kind == TC.FUND_BANK else None
            party = self.party_combo.value()
            method = str(self.method_combo.currentData())
            doc_date = self.date_edit.date() or _dt.date.today()
            cheque = self._cheque_input()
            allocations = self._allocations()
            if self.is_receipt:
                data = ReceiptInput(
                    receipt_date=doc_date, amount=amount,
                    receipt_type=str(self.type_combo.currentData()), method=method,
                    cash_box_id=cash_box_id, bank_account_id=bank_account_id,
                    payer_detail_id=party,
                    payer_name=self.party_name_edit.text().strip(),
                    counter_account_id=self.counter_combo.value() or None,
                    currency_code=self.currency_combo.currentData(),
                    exchange_rate=rate,
                    tracking_no=self.tracking_edit.text().strip(),
                    reference_no=self.reference_edit.text().strip(),
                    description=self.description_edit.toPlainText().strip(),
                    cheque=cheque, allocations=allocations)
                if self.voucher is not None:
                    self.saved = self.services.vouchers.update_receipt(
                        self.ctx, self.voucher.id, data)
                else:
                    self.saved = self.services.vouchers.create_receipt(self.ctx, data)
            else:
                data = PaymentInput(
                    payment_date=doc_date, amount=amount,
                    payment_type=str(self.type_combo.currentData()), method=method,
                    cash_box_id=cash_box_id, bank_account_id=bank_account_id,
                    payee_detail_id=party,
                    payee_name=self.party_name_edit.text().strip(),
                    counter_account_id=self.counter_combo.value() or None,
                    currency_code=self.currency_combo.currentData(),
                    exchange_rate=rate,
                    tracking_no=self.tracking_edit.text().strip(),
                    reference_no=self.reference_edit.text().strip(),
                    description=self.description_edit.toPlainText().strip(),
                    cheque=cheque, allocations=allocations)
                if self.voucher is not None:
                    self.saved = self.services.vouchers.update_payment(
                        self.ctx, self.voucher.id, data)
                else:
                    self.saved = self.services.vouchers.create_payment(self.ctx, data)
        except AppError as error:
            show_error(self, "ثبت سند", error)
            return
        self.accept()


class VouchersPage(PageBase):
    """List + lifecycle actions for receipts (``family="receipt"``) or payments."""

    def __init__(self, services, ctx, formatter, *, family: str = "receipt",
                 default_type: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.family = family
        self.default_type = default_type
        self.rows: list[VoucherRow] = []
        self.is_receipt = family == "receipt"
        if default_type is None:
            title = "دریافت وجه" if self.is_receipt else "پرداخت وجه"
        else:
            title = "دریافت از مشتری" if self.is_receipt else "پرداخت به تأمین‌کننده"
        self.header = PageHeader(
            title, "ثبت پیش‌نویس، تأیید، ثبت نهایی، چاپ و ابطال — هر سند یک سند حسابداری")
        self.header.add_action("سند جدید", slot=self._create)
        self.header.add_action("تأیید", variant="secondary", slot=self._approve)
        self.header.add_action("ثبت نهایی", variant="secondary", slot=self._post)
        self.header.add_action("ابطال", variant="secondary", slot=self._void)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)

        filters = CardPanel("فیلترها")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی شماره، طرف حساب یا شرح…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.from_edit = JalaliDateEdit(_dt.date.today().replace(day=1))
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(_dt.date.today())
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همه وضعیت‌ها", None)
        for code in TC.STATUSES:
            self.status_combo.addItem(TC.STATUS_TITLES_FA[code], code)
        self.status_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_combo), 1)
        filters.add_layout(row)
        self.root.addWidget(filters)

        self.table = DataTable(VOUCHER_COLUMNS, formatter=formatter)
        self.table.rowActivated.connect(self._open_row)
        card = CardPanel("اسناد")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        try:
            loader = (self.services.vouchers.list_receipts if self.is_receipt
                      else self.services.vouchers.list_payments)
            rows = loader(self.ctx, date_from=self.from_edit.date(),
                          date_to=self.to_edit.date(),
                          status=self.status_combo.currentData(),
                          search=self.search_input.text() or None)
            if self.default_type == "customer":
                rows = [row for row in rows
                        if row.type_code in (TC.RECEIPT_CUSTOMER, TC.RECEIPT_ADVANCE)]
            elif self.default_type == "supplier":
                rows = [row for row in rows
                        if row.type_code in (TC.PAYMENT_SUPPLIER, TC.PAYMENT_ADVANCE)]
        except AppError as error:
            show_error(self, "فهرست اسناد", error)
            return
        self.rows = rows
        self.table.set_rows(rows)
        total = sum((row.base_amount for row in rows), Decimal("0"))
        self.summary.setText(f"{len(rows):,} سند — جمع {total:,} "
                             f"{self.services.settings.snapshot().currency_code}")

    def _selected(self) -> VoucherRow | None:
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        return self.rows[index.row()]

    def _open_row(self, row_index: int) -> None:
        if 0 <= row_index < len(self.rows):
            self._edit(self.rows[row_index])

    # --------------------------------------------------------------- actions
    def _create(self) -> None:
        dialog = VoucherDialog(self.services, self.ctx, self.family, parent=self)
        if self.default_type == "customer":
            dialog.type_combo.setCurrentIndex(
                dialog.type_combo.findData(TC.RECEIPT_CUSTOMER))
        elif self.default_type == "supplier":
            dialog.type_combo.setCurrentIndex(
                dialog.type_combo.findData(TC.PAYMENT_SUPPLIER))
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit(f"سند {dialog.saved.number} ثبت شد.")

    def _edit(self, row: VoucherRow) -> None:
        if row.status != TC.STATUS_DRAFT:
            show_info(self, "ویرایش", "فقط سند پیش‌نویس قابل ویرایش است.")
            return
        dialog = VoucherDialog(self.services, self.ctx, self.family, voucher=row,
                               parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit(f"سند {dialog.saved.number} به‌روزرسانی شد.")

    def _approve(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "تأیید", "یک سند را انتخاب کنید.")
            return
        if not confirm(self, "تأیید سند", f"سند {row.number} تأیید شود؟"):
            return
        try:
            action = (self.services.vouchers.approve_receipt if self.is_receipt
                      else self.services.vouchers.approve_payment)
            action(self.ctx, row.id)
        except AppError as error:
            show_error(self, "تأیید سند", error)
            return
        self.refresh()
        self.statusMessage.emit(f"سند {row.number} تأیید شد.")

    def _post(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "ثبت نهایی", "یک سند را انتخاب کنید.")
            return
        if not confirm(self, "ثبت نهایی",
                       f"سند {row.number} ثبت نهایی شود؟ سند حسابداری صادر می‌شود."):
            return
        try:
            action = (self.services.vouchers.post_receipt if self.is_receipt
                      else self.services.vouchers.post_payment)
            posted = action(self.ctx, row.id)
        except AppError as error:
            show_error(self, "ثبت نهایی", error)
            return
        self.refresh()
        self.statusMessage.emit(f"سند {posted.number} ثبت نهایی شد (سند حسابداری "
                                f"{posted.journal_id}).")

    def _void(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "ابطال", "یک سند را انتخاب کنید.")
            return
        reason = ask_reason(self, "ابطال سند",
                            f"دلیل ابطال سند {row.number} را بنویسید (حداقل ۵ نویسه):")
        if not reason:
            return
        try:
            action = (self.services.vouchers.void_receipt if self.is_receipt
                      else self.services.vouchers.void_payment)
            action(self.ctx, row.id, reason)
        except AppError as error:
            show_error(self, "ابطال سند", error)
            return
        self.refresh()
        self.statusMessage.emit(f"سند {row.number} ابطال شد و سند برگشتی صادر شد.")

    # ------------------------------------------------------------- reporting
    def _table(self):
        headers = ("شماره", "تاریخ", "نوع", "روش", "صندوق/بانک", "طرف حساب",
                   "مبلغ", "وضعیت")
        rows = tuple((row.number, row.voucher_date, row.type_fa, row.method_fa,
                      row.fund_label, row.party_name, row.base_amount, row.status_fa)
                     for row in self.rows)
        title = "گزارش رسیدهای دریافت" if self.is_receipt else "گزارش اسناد پرداخت"
        return build_table(title, headers, rows,
                           meta=f"{len(self.rows):,} سند",
                           company=self.services.settings.snapshot().company_name,
                           totals=("", "", "", "", "", "جمع",
                                   sum((r.base_amount for r in self.rows), Decimal("0")), ""))

    def _print(self) -> None:
        if not self.rows:
            show_info(self, "چاپ", "سندی برای چاپ وجود ندارد.")
            return
        show_preview(self, self.services, self._table())

    def _excel(self) -> None:
        if not self.rows:
            show_info(self, "Excel", "سندی برای خروجی وجود ندارد.")
            return
        export_excel(self, self.services, self._table(),
                     prefix="receipts" if self.is_receipt else "payments")
