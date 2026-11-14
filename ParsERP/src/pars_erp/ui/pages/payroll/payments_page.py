"""پرداخت حقوق — batches, bank file export, per-item failure and retry."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.payroll_payment_service import BatchInput
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.widgets import hint_label
from pars_erp.ui.pages.treasury.widgets import FundPicker
from pars_erp.ui.table_specs import BATCH_COLUMNS, BATCH_ITEM_COLUMNS
from pars_erp.ui.widgets.table import DataTable


class BatchDialog(FormDialog):
    title_fa = "دستهٔ پرداخت حقوق"
    width = 600

    def __init__(self, services, ctx, *, run_id: int | None = None,
                 parent: QWidget | None = None) -> None:
        self._run_id = run_id
        super().__init__(services, ctx, parent=parent,
                         subtitle="از فیش‌های تأییدشدهٔ یک دوره؛ هر فیش فقط یک بار در "
                                  "یک دسته قرار می‌گیرد.")

    def _build(self) -> None:
        self.run_combo = PickCombo()
        try:
            runs = self.services.payroll.list_runs(self.ctx)
        except AppError:
            runs = []
        self.run_combo.load([(run.id, f"{run.number} — {run.status_fa}") for run in runs])
        if self._run_id:
            self.run_combo.set_value(self._run_id)
        self.add_row("دورهٔ حقوق *", self.run_combo, required=True)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_row("تاریخ پرداخت *", self.date_edit, required=True)
        self.fund_picker = FundPicker()
        self.fund_picker.attach(self.services, self.ctx)
        self.add_row("منبع پرداخت *", self.fund_picker, required=True)
        self.method_combo = fill_combo(QComboBox(), TC.PAYMENT_METHODS,
                                       current=TC.METHOD_TRANSFER, placeholder="")
        self.add_row("روش پرداخت", self.method_combo)
        self.note_edit = QLineEdit()
        self.add_row("یادداشت", self.note_edit)
        self.add_widget(hint_label(
            "قالب فایل بانکی از تنظیمات «payroll_payment_file_format» خوانده می‌شود؛ "
            "قالب آمادهٔ بانک‌های ایرانی در این نسخه همراه نیست."))

    def save(self):
        run_id = self.run_combo.value()
        if run_id is None:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("دورهٔ حقوق را انتخاب کنید.", field="run_id")
        data = BatchInput(
            run_id=int(run_id),
            payment_date=self.date_edit.date(),
            cash_box_id=self.fund_picker.cash_box_id(),
            bank_account_id=self.fund_picker.bank_account_id(),
            method=str(self.method_combo.currentData()),
            note=self.note_edit.text().strip(),
        )
        return self.services.payroll_payments.create_batch(self.ctx, data)


class TrackingDialog(FormDialog):
    title_fa = "ثبت پرداخت دسته"
    width = 460

    def _build(self) -> None:
        self.tracking_edit = QLineEdit()
        self.add_row("شماره پیگیری/ارجاع", self.tracking_edit)
        self.add_widget(hint_label(
            "با تأیید، سند پرداخت در خزانه ثبت می‌شود و فیش‌های دسته «پرداخت‌شده» می‌شوند."))

    def save(self):
        return self.tracking_edit.text().strip()


class BatchItemsDialog(QDialog):
    """Items of a batch: mark a failure with a reason or retry the failures."""

    def __init__(self, services, ctx, batch, formatter, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.batch = batch
        self.formatter = formatter
        self.setWindowTitle(f"اقلام دسته {batch.number}")
        self.setModal(True)
        self.setMinimumSize(900, 500)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        heading = QLabel(f"اقلام دستهٔ {batch.number} — {batch.status_fa}")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self.table = DataTable(BATCH_ITEM_COLUMNS, formatter=formatter)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.fail_button = self._button("ثبت ناموفق", self._fail)
        self.retry_button = self._button("تلاش مجدد", self._retry, "secondary")
        actions.addWidget(self.fail_button)
        actions.addWidget(self.retry_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.fail_button.setEnabled(ctx.has("payroll.pay"))

        buttons = QDialogButtonBox()
        close = buttons.addButton("بستن", QDialogButtonBox.ButtonRole.AcceptRole)
        close.setProperty("variant", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        self.reload()

    @staticmethod
    def _button(text: str, slot, variant: str = "primary"):
        from PySide6.QtWidgets import QPushButton

        button = QPushButton(text)
        button.setProperty("variant", variant)
        button.clicked.connect(slot)
        return button

    def reload(self) -> None:
        try:
            batch = self.services.payroll_payments.get_batch(self.ctx, self.batch.id)
        except AppError as error:
            show_error(self, "اقلام دسته", error)
            return
        self.batch = batch
        self.table.set_rows(batch.items or [])

    def _selected(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    def _fail(self) -> None:
        item = self._selected()
        if item is None:
            show_info(self, "ثبت ناموفق", "ابتدا یک ردیف را انتخاب کنید.")
            return
        reason = ask_reason(self, "ثبت ناموفق", "علت ناموفق بودن پرداخت را وارد کنید:")
        if not reason:
            return
        try:
            self.services.payroll_payments.fail_item(self.ctx, item.id, reason=reason)
        except AppError as error:
            show_error(self, "ثبت ناموفق", error)
            return
        self.reload()

    def _retry(self) -> None:
        failed = [item for item in (self.batch.items or ()) if item.status == "failed"]
        if not failed:
            show_info(self, "تلاش مجدد", "ردیف ناموفقی در این دسته نیست.")
            return
        if not confirm(self, "تلاش مجدد",
                       f"{len(failed):,} ردیف ناموفق به دستهٔ جدید منتقل شود؟"):
            return
        try:
            batch = self.services.payroll_payments.retry_batch(self.ctx, self.batch.id)
        except AppError as error:
            show_error(self, "تلاش مجدد", error)
            return
        show_info(self, "تلاش مجدد", f"دستهٔ {batch.number} برای ردیف‌های ناموفق ساخته شد.")
        self.reload()


class PayrollPaymentsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "پرداخت حقوق",
            "دستهٔ پرداخت، فایل بانکی، پرداخت از صندوق/بانک، ثبت ناموفق و تلاش مجدد")
        self.new_button = self.header.add_action("دستهٔ پرداخت جدید", slot=self._new)
        self.pay_button = self.header.add_action("پرداخت", variant="secondary",
                                                 slot=self._pay)
        self.file_button = self.header.add_action("فایل بانکی", variant="secondary",
                                                  slot=self._bank_file)
        self.items_button = self.header.add_action("اقلام دسته", variant="secondary",
                                                   slot=self._items)
        self.root.addWidget(self.header)

        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.run_filter = PickCombo()
        self.run_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("دورهٔ حقوق", self.run_filter), 2)
        bar.add_layout(row)
        self.root.addWidget(bar)

        self.table = DataTable(BATCH_COLUMNS, formatter=formatter)
        card = CardPanel("دسته‌های پرداخت")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        can_pay = self.can("payroll.pay")
        for button in (self.new_button, self.pay_button, self.file_button):
            button.setEnabled(can_pay)
        self.items_button.setEnabled(self.can("payroll.view"))
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            runs = self.services.payroll.list_runs(self.ctx)
            self.run_filter.load([(run.id, run.number) for run in runs])
            run_id = self.run_filter.value()
            self.rows = self.services.payroll_payments.list_batches(self.ctx, run_id=run_id)
        except AppError as error:
            show_error(self, "پرداخت حقوق", error)
            return
        self.set_rows(self.table, self.rows)
        paid = sum(1 for row in self.rows if row.status == "paid")
        total = sum((row.total_amount for row in self.rows), Decimal("0"))
        self.summary.setText(f"{len(self.rows):,} دسته — {paid:,} پرداخت‌شده — "
                             f"جمع {self.formatter.amount(total)}")

    def _selected(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = BatchDialog(self.services, self.ctx, run_id=self.run_filter.value(),
                             parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دستهٔ {dialog.saved.number} با "
                        f"{self.formatter.number(dialog.saved.items_count)} فیش ساخته شد.")

    def _pay(self) -> None:
        batch = self._selected()
        if batch is None:
            show_info(self, "پرداخت", "ابتدا یک دسته را انتخاب کنید.")
            return
        dialog = TrackingDialog(self.services, self.ctx, parent=self)
        if not dialog.exec():
            return
        if not confirm(self, "پرداخت دسته",
                       f"دستهٔ {batch.number} پرداخت شود؟ سند خزانه ثبت می‌شود.",
                       danger=True):
            return
        try:
            paid = self.services.payroll_payments.pay(self.ctx, batch.id,
                                                      tracking_no=dialog.saved or "")
        except AppError as error:
            show_error(self, "پرداخت دسته", error)
            return
        self.refresh()
        self.notify(f"دستهٔ {paid.number} پرداخت و سند خزانه ثبت شد.")

    def _bank_file(self) -> None:
        batch = self._selected()
        if batch is None:
            show_info(self, "فایل بانکی", "ابتدا یک دسته را انتخاب کنید.")
            return
        default = f"{batch.number}.txt"
        path, _filter = QFileDialog.getSaveFileName(self, "ذخیرهٔ فایل بانکی", default,
                                                   "Text (*.txt);;CSV (*.csv)")
        if not path:
            return
        try:
            saved = self.services.payroll_payments.export_bank_file(self.ctx, batch.id, path)
        except AppError as error:
            show_error(self, "فایل بانکی", error)
            return
        show_info(self, "فایل بانکی", f"فایل در مسیر زیر ذخیره شد:\n{saved}",
                  tone="success")

    def _items(self) -> None:
        batch = self._selected()
        if batch is None:
            show_info(self, "اقلام دسته", "ابتدا یک دسته را انتخاب کنید.")
            return
        BatchItemsDialog(self.services, self.ctx, batch, self.formatter, parent=self).exec()
        self.refresh()
