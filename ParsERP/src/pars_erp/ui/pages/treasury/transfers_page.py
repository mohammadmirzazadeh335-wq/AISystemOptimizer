"""Fund transfers between cash boxes and bank accounts (with a separate fee)."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.voucher_service import TransferInput, TransferRow
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    FundPicker,
    build_table,
    export_excel,
    form_row,
    show_preview,
    status_key,
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

TRANSFER_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 130, "center"),
    ColumnSpec("transfer_date", "تاریخ", DATE, 96, "center"),
    ColumnSpec("from_label", "از", TEXT, 170),
    ColumnSpec("to_label", "به", TEXT, 170),
    ColumnSpec("amount", "مبلغ", AMOUNT, 130),
    ColumnSpec("fee", "کارمزد", AMOUNT, 100),
    ColumnSpec("tracking_no", "پیگیری", TEXT, 110, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 110, "center",
               getter=lambda row: status_key(row.status)),
)


class TransferDialog(QDialog):
    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.saved = None
        self.setWindowTitle("انتقال وجه جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ *", self.date_edit)
        self.from_picker = FundPicker()
        form.addRow("از *", self.from_picker)
        self.to_picker = FundPicker()
        form.addRow("به *", self.to_picker)
        self.amount_edit = MoneyEdit()
        form.addRow("مبلغ *", self.amount_edit)
        self.fee_edit = MoneyEdit()
        form.addRow("کارمزد", self.fee_edit)
        self.tracking_edit = QLineEdit()
        form.addRow("شماره پیگیری", self.tracking_edit)
        self.description_edit = QLineEdit()
        form.addRow("شرح", self.description_edit)
        layout.addLayout(form)
        hint = QLabel("کارمزد به‌صورت هزینهٔ بانکی جداگانه ثبت می‌شود و از مبدأ کسر "
                      "می‌گردد؛ سند حسابداری به‌صورت اتمیک و یک‌بار صادر می‌شود.")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.balance_label = QLabel("")
        self.balance_label.setObjectName("HintText")
        layout.addWidget(self.balance_label)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ثبت انتقال", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.from_picker.attach(services, ctx)
        self.to_picker.attach(services, ctx)
        self.from_picker.changed.connect(self._show_balances)
        self.to_picker.changed.connect(self._show_balances)
        if self.from_picker.kind_combo.count() > 1:
            self.to_picker.kind_combo.setCurrentIndex(1)
        self.to_picker._reload_funds()
        self._show_balances()

    def _show_balances(self) -> None:
        parts = []
        for label, picker in (("از", self.from_picker), ("به", self.to_picker)):
            fund_id = picker.fund_id()
            if fund_id is None:
                continue
            try:
                if picker.kind() == TC.FUND_CASH:
                    row = self.services.funds.get_cash_box(self.ctx, fund_id)
                else:
                    row = self.services.funds.get_bank_account(self.ctx, fund_id)
                parts.append(f"{label}: موجودی {row.balance:,}")
            except AppError:
                pass
        self.balance_label.setText(" | ".join(parts))

    def _save(self) -> None:
        try:
            from_kind, from_id = self.from_picker.require()
            to_kind, to_id = self.to_picker.require()
            data = TransferInput(
                transfer_date=self.date_edit.date() or _dt.date.today(),
                amount=self.amount_edit.amount,
                from_cash_box_id=from_id if from_kind == TC.FUND_CASH else None,
                from_bank_account_id=from_id if from_kind == TC.FUND_BANK else None,
                to_cash_box_id=to_id if to_kind == TC.FUND_CASH else None,
                to_bank_account_id=to_id if to_kind == TC.FUND_BANK else None,
                fee=self.fee_edit.amount,
                tracking_no=self.tracking_edit.text().strip(),
                description=self.description_edit.text().strip())
            transfer = self.services.vouchers.create_transfer(self.ctx, data)
            self.saved = self.services.vouchers.post_transfer(self.ctx, transfer.id)
        except AppError as error:
            show_error(self, "انتقال وجه", error)
            return
        self.accept()


class TransfersPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows: list[TransferRow] = []
        self.header = PageHeader("انتقال وجه",
                                 "صندوق↔صندوق، بانک↔بانک و صندوق↔بانک با کارمزد مستقل و "
                                 "یک سند حسابداری متوازن")
        self.header.add_action("انتقال جدید", slot=self._create)
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)
        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی شماره یا شرح…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.from_edit = JalaliDateEdit(_dt.date.today().replace(day=1))
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        self.to_edit = JalaliDateEdit(_dt.date.today())
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)
        self.table = DataTable(TRANSFER_COLUMNS, formatter=formatter)
        card = CardPanel("انتقال‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rows = self.services.vouchers.list_transfers(
                self.ctx, date_from=self.from_edit.date(), date_to=self.to_edit.date(),
                search=self.search_input.text() or None)
        except AppError as error:
            show_error(self, "انتقال وجه", error)
            return
        self.table.set_rows(self.rows)
        total = sum((row.amount for row in self.rows), Decimal("0"))
        fees = sum((row.fee for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} انتقال — جمع {total:,} — "
                             f"کارمزد {fees:,}")

    def _create(self) -> None:
        dialog = TransferDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit(f"انتقال {dialog.saved.number} ثبت و قطعی شد.")

    def _table(self):
        headers = tuple(column.title_fa for column in TRANSFER_COLUMNS)
        rows = tuple(tuple(column.value_of(row) for column in TRANSFER_COLUMNS)
                     for row in self.rows)
        return build_table("گزارش انتقال وجه", headers, rows,
                           meta=f"{len(self.rows):,} انتقال",
                           company=self.services.settings.snapshot().company_name)

    def _print(self) -> None:
        if not self.rows:
            show_info(self, "چاپ", "انتقالی برای چاپ وجود ندارد.")
            return
        show_preview(self, self.services, self._table())

    def _excel(self) -> None:
        if not self.rows:
            show_info(self, "Excel", "انتقالی برای خروجی وجود ندارد.")
            return
        export_excel(self, self.services, self._table(), prefix="transfers")
