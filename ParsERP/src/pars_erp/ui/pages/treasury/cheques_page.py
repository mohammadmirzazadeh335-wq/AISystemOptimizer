"""Cheques: received, issued, management and cheque books."""

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
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.cheque_service import ChequeBookInput, ChequeRow
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
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
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

CHEQUE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره چک", TEXT, 110, "center"),
    ColumnSpec("party_name", "شخص", TEXT, None),
    ColumnSpec("bank_name", "بانک", TEXT, 140),
    ColumnSpec("issue_date", "صدور", DATE, 96, "center"),
    ColumnSpec("due_date", "سررسید", DATE, 96, "center"),
    ColumnSpec("base_amount", "مبلغ", AMOUNT, 130),
    ColumnSpec("days_to_due", "روز تا سررسید", NUMBER, 110, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 130, "center",
               getter=lambda row: row.status),
    ColumnSpec("book_serial", "دسته‌چک", TEXT, 110, "center"),
)

BOOK_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("serial_no", "سریال", TEXT, 110, "center"),
    ColumnSpec("bank_label", "حساب بانکی", TEXT, None),
    ColumnSpec("first_no", "از شماره", NUMBER, 100, "center"),
    ColumnSpec("last_no", "تا شماره", NUMBER, 100, "center"),
    ColumnSpec("total_leaves", "تعداد برگ", NUMBER, 90, "center"),
    ColumnSpec("used_leaves", "مصرف‌شده", NUMBER, 90, "center"),
    ColumnSpec("void_leaves", "باطل", NUMBER, 80, "center"),
    ColumnSpec("free_leaves", "بافرگ", NUMBER, 80, "center"),
    ColumnSpec("received_date", "تاریخ دریافت", DATE, 110, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 100, "center",
               getter=lambda row: "active" if row.status == TC.BOOK_ACTIVE else "cancelled"),
)

STATUS_REASON_STATUSES = (TC.CHQ_COLLECTED, TC.CHQ_PAID, TC.CHQ_BOUNCED, TC.CHQ_RETURNED)


class ChequeStatusDialog(QDialog):
    """Change one cheque's status, with the fund needed by collection/payment."""

    def __init__(self, services, ctx, cheque: ChequeRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.cheque = cheque
        self.changed: ChequeRow | None = None
        self.setWindowTitle(f"تغییر وضعیت چک {cheque.number}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        table = (TC.RECEIVED_TRANSITIONS if cheque.direction == TC.CHEQUE_RECEIVED
                 else TC.ISSUED_TRANSITIONS)
        self.target_combo = QComboBox()
        for code in table.get(cheque.status, ()):
            self.target_combo.addItem(TC.CHEQUE_STATUS_TITLES_FA[code], code)
        form.addRow("وضعیت جدید *", self.target_combo)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ رویداد", self.date_edit)
        self.fund_picker = FundPicker()
        form.addRow("صندوق / بانک (در صورت وصول)", self.fund_picker)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setFixedHeight(60)
        form.addRow("توضیح", self.note_edit)
        layout.addLayout(form)
        self.hint = QLabel("")
        self.hint.setObjectName("HintText")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        buttons = QDialogButtonBox()
        save = buttons.addButton("اعمال", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.fund_picker.attach(services, ctx)
        self.target_combo.currentIndexChanged.connect(self._sync_hint)
        self._sync_hint()

    def _sync_hint(self) -> None:
        target = str(self.target_combo.currentData())
        needs_fund = target in (TC.CHQ_COLLECTED, TC.CHQ_PAID)
        self.fund_picker.setVisible(needs_fund)
        self.hint.setText("برای این تغییر وضعیت، صندوق یا بانک مقصد الزامی است."
                          if needs_fund else
                          "این تغییر وضعیت سند حسابداری جدیدی صادر نمی‌کند.")

    def _save(self) -> None:
        target = str(self.target_combo.currentData())
        if target not in dict(TC.CHEQUE_STATUSES):
            show_info(self, "وضعیت چک", "وضعیت جدید معتبر نیست.")
            return
        try:
            cash_box_id = bank_account_id = None
            if target in (TC.CHQ_COLLECTED, TC.CHQ_PAID):
                kind, fund_id = self.fund_picker.require()
                if kind == TC.FUND_CASH:
                    cash_box_id = fund_id
                else:
                    bank_account_id = fund_id
            self.changed = self.services.cheques.change_status(
                self.ctx, self.cheque.id, target,
                event_date=self.date_edit.date(), note=self.note_edit.toPlainText().strip(),
                cash_box_id=cash_box_id, bank_account_id=bank_account_id)
        except AppError as error:
            show_error(self, "وضعیت چک", error)
            return
        self.accept()


class _ChequesPageBase(PageBase):
    title_fa = "چک‌ها"
    subtitle_fa = ""
    columns = CHEQUE_COLUMNS

    def __init__(self, services, ctx, formatter, *, direction: str | None = None,
                 open_only: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.direction = direction
        self.open_only = open_only
        self.rows: list[ChequeRow] = []
        self.header = PageHeader(self.title_fa, self.subtitle_fa)
        self.header.add_action("تغییر وضعیت", slot=self._change_status)
        self.header.add_action("تاریخچه", variant="secondary", slot=self._history)
        self.header.add_action("ابطال", variant="secondary", slot=self._cancel)
        self.header.add_action("سررسیدها", variant="secondary", slot=self._due)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)
        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی شماره، بانک یا شخص…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.from_edit = JalaliDateEdit(_dt.date.today().replace(day=1))
        row.addWidget(form_row("از سررسید", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(_dt.date.today() + _dt.timedelta(days=180))
        row.addWidget(form_row("تا سررسید", self.to_edit), 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همه وضعیت‌ها", None)
        for code, title in TC.CHEQUE_STATUSES:
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_combo), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)
        self.table = DataTable(self.columns, formatter=formatter)
        self.table.rowActivated.connect(lambda _row: self._change_status())
        card = CardPanel("چک‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.history_table = DataTable((
            ColumnSpec("from_status_fa", "از وضعیت", TEXT, 140),
            ColumnSpec("to_status_fa", "به وضعیت", TEXT, 140),
            ColumnSpec("event_date", "تاریخ", DATE, 100, "center"),
            ColumnSpec("user_name", "کاربر", TEXT, 150),
            ColumnSpec("note", "توضیح", TEXT, None),
        ), formatter=formatter)
        history_card = CardPanel("تاریخچه وضعیت")
        history_card.add(self.history_table, 1)
        self.root.addWidget(history_card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        try:
            self.rows = self.services.cheques.list_cheques(
                self.ctx, direction=self.direction,
                status=self.status_combo.currentData(),
                date_from=self.from_edit.date(), date_to=self.to_edit.date(),
                search=self.search_input.text() or None)
        except AppError as error:
            show_error(self, self.title_fa, error)
            return
        if self.open_only:
            self.rows = [row for row in self.rows if row.is_open]
        self.table.set_rows(self.rows)
        total = sum((row.base_amount for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} چک — جمع {total:,}")

    def _selected(self) -> ChequeRow | None:
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        return self.rows[index.row()]

    # --------------------------------------------------------------- actions
    def _change_status(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "تغییر وضعیت", "یک چک را انتخاب کنید.")
            return
        dialog = ChequeStatusDialog(self.services, self.ctx, row, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit(f"وضعیت چک {row.number} به "
                                    f"{dialog.changed.status_fa} تغییر کرد.")

    def _history(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "تاریخچه", "یک چک را انتخاب کنید.")
            return
        try:
            events = self.services.cheques.history(self.ctx, row.id)
        except AppError as error:
            show_error(self, "تاریخچه چک", error)
            return
        self.history_table.set_rows(events)

    def _cancel(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "ابطال چک", "یک چک را انتخاب کنید.")
            return
        reason = ask_reason(self, "ابطال چک",
                            f"دلیل ابطال چک {row.number} را بنویسید (حداقل ۵ نویسه):")
        if not reason:
            return
        try:
            self.services.cheques.cancel(self.ctx, row.id, reason)
        except AppError as error:
            show_error(self, "ابطال چک", error)
            return
        self.refresh()
        self.statusMessage.emit(f"چک {row.number} ابطال شد.")

    def _due(self) -> None:
        try:
            rows = self.services.cheques.due_soon(self.ctx)
        except AppError as error:
            show_error(self, "سررسیدها", error)
            return
        self.rows = rows
        self.table.set_rows(rows)
        self.summary.setText(f"{len(rows):,} چک نزدیک سررسید")

    # ------------------------------------------------------------- reporting
    def _table(self):
        headers = tuple(column.title_fa for column in self.columns)
        rows = tuple(tuple(column.value_of(row) for column in self.columns)
                     for row in self.rows)
        return build_table(self.title_fa, headers, rows,
                           meta=f"{len(self.rows):,} چک",
                           company=self.services.settings.snapshot().company_name,
                           totals=("", "", "", "", "جمع",
                                   sum((row.base_amount for row in self.rows),
                                       Decimal("0")), "", "", ""))

    def _print(self) -> None:
        if not self.rows:
            show_info(self, "چاپ", "چکی برای چاپ وجود ندارد.")
            return
        show_preview(self, self.services, self._table())

    def _excel(self) -> None:
        if not self.rows:
            show_info(self, "Excel", "چکی برای خروجی وجود ندارد.")
            return
        export_excel(self, self.services, self._table(), prefix="cheques")


class ReceivedChequesPage(_ChequesPageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.title_fa = "دریافت چک"
        self.subtitle_fa = ("چک‌های دریافتی از مشتریان: ثبت، واگذاری به بانک، وصول، برگشت "
                            "و تاریخچهٔ هر تغییر وضعیت")
        super().__init__(services, ctx, formatter, direction=TC.CHEQUE_RECEIVED,
                         parent=parent)


class IssuedChequesPage(_ChequesPageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.title_fa = "پرداخت چک"
        self.subtitle_fa = ("چک‌های صادره: تحویل، انتظار وصول، پرداخت و برگشت با ثبت "
                            "اتمیک سند حسابداری")
        super().__init__(services, ctx, formatter, direction=TC.CHEQUE_ISSUED,
                         parent=parent)


class ChequeManagePage(_ChequesPageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.title_fa = "مدیریت چک‌ها"
        self.subtitle_fa = ("همهٔ چک‌های دریافتی و پرداختی در یک صفحه، با رنگ‌بندی وضعیت، "
                            "تاریخچه، ابطال و فهرست سررسید")
        super().__init__(services, ctx, formatter, direction=None, parent=parent)


class ReceivableDocumentsPage(_ChequesPageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.title_fa = "اسناد دریافتنی"
        self.subtitle_fa = ("چک‌ها و اسناد در جریان وصول با سررسید و مبلغ؛ پس از وصول از "
                            "این فهرست خارج می‌شوند")
        super().__init__(services, ctx, formatter, direction=TC.CHEQUE_RECEIVED,
                         open_only=True, parent=parent)


class PayableDocumentsPage(_ChequesPageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        self.title_fa = "اسناد پرداختنی"
        self.subtitle_fa = "چک‌ها و تعهدات پرداختنی شرکت که هنوز تسویه نشده‌اند"
        super().__init__(services, ctx, formatter, direction=TC.CHEQUE_ISSUED,
                         open_only=True, parent=parent)


class ChequeBookDialog(QDialog):
    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.saved = None
        self.setWindowTitle("دسته‌چک جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.bank_combo = PickCombo()
        try:
            self.bank_combo.load(services.funds.bank_account_choices(ctx))
        except AppError:
            self.bank_combo.load([])
        form.addRow("حساب بانکی *", self.bank_combo)
        self.serial_edit = QLineEdit()
        form.addRow("سریال *", self.serial_edit)
        self.first_edit = QLineEdit("1001")
        form.addRow("از شماره *", self.first_edit)
        self.last_edit = QLineEdit("1025")
        form.addRow("تا شماره *", self.last_edit)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ دریافت", self.date_edit)
        self.note_edit = QLineEdit()
        form.addRow("توضیح", self.note_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            self.saved = self.services.cheques.create_book(self.ctx, ChequeBookInput(
                bank_account_id=self.bank_combo.value() or 0,
                serial_no=self.serial_edit.text().strip(),
                first_no=int(self.first_edit.text() or 0),
                last_no=int(self.last_edit.text() or 0),
                received_date=self.date_edit.date() or _dt.date.today(),
                note=self.note_edit.text().strip()))
        except (AppError, ValueError) as error:
            show_error(self, "دسته‌چک", error if isinstance(error, AppError) else
                       Exception("شماره برگ‌ها باید عدد باشند."))
            return
        self.accept()


class ChequeBooksPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader("دسته‌چک‌ها",
                                 "شمارهٔ برگ‌ها، برگ‌های مصرف‌شده/باطل و جلوگیری از تکرار "
                                 "شماره در یک دسته")
        self.header.add_action("دسته‌چک جدید", slot=self._create)
        self.header.add_action("باطل‌کردن برگ", variant="secondary", slot=self._void_leaf)
        self.header.add_action("پایان دسته", variant="secondary", slot=self._finish)
        self.root.addWidget(self.header)
        self.table = DataTable(BOOK_COLUMNS, formatter=formatter)
        card = CardPanel("دسته‌چک‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rows = self.services.cheques.list_books(self.ctx)
        except AppError as error:
            show_error(self, "دسته‌چک‌ها", error)
            return
        self.table.set_rows(self.rows)
        self.summary.setText(f"{len(self.rows):,} دسته‌چک — "
                             f"{sum(row.free_leaves for row in self.rows):,} برگ آزاد")

    def _selected(self):
        index = self.table.currentIndex()
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        return self.rows[index.row()]

    def _create(self) -> None:
        dialog = ChequeBookDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit("دسته‌چک ثبت شد.")

    def _void_leaf(self) -> None:
        book = self._selected()
        if book is None:
            show_info(self, "باطل‌کردن برگ", "یک دسته‌چک را انتخاب کنید.")
            return
        from PySide6.QtWidgets import QInputDialog

        text, accepted = QInputDialog.getText(
            self, "باطل‌کردن برگ", "شمارهٔ برگ باطل‌شده:")
        if not accepted or not text.strip().isdigit():
            return
        try:
            self.services.cheques.mark_voiced(self.ctx, book.id, int(text.strip()),
                                              "برگ باطل‌شده")
        except AppError as error:
            show_error(self, "باطل‌کردن برگ", error)
            return
        self.refresh()
        self.statusMessage.emit(f"برگ {text.strip()} باطل شد و قابل استفادهٔ مجدد نیست.")

    def _finish(self) -> None:
        book = self._selected()
        if book is None:
            show_info(self, "پایان دسته", "یک دسته‌چک را انتخاب کنید.")
            return
        if not confirm(self, "پایان دسته‌چک", f"دسته‌چک {book.serial_no} پایان‌یافته شود؟"):
            return
        try:
            self.services.cheques.set_book_status(self.ctx, book.id, TC.BOOK_FINISHED)
        except AppError as error:
            show_error(self, "پایان دسته", error)
            return
        self.refresh()
