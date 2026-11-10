"""Dated tax rates and price lists (retail, wholesale, special, seasonal)."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.services.pricing_service import TAX_APPLIES
from pars_erp.ui.dialogs.common_dialogs import show_error
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.table_specs import AMOUNT, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

TAX_COLUMNS = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان", TEXT, None),
    ColumnSpec("percent", "درصد", TEXT, 80, "center"),
    ColumnSpec("applies_to_fa", "دامنه", TEXT, 120),
    ColumnSpec("valid_from", "از تاریخ", DATE, 100, "center"),
    ColumnSpec("valid_to", "تا تاریخ", DATE, 100, "center"),
)

PRICE_LIST_COLUMNS = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان", TEXT, None),
    ColumnSpec("kind_fa", "نوع", TEXT, 110),
    ColumnSpec("party_detail_id", "مشتری", TEXT, 90, "center"),
    ColumnSpec("discount_percent", "تخفیف %", TEXT, 80, "center"),
    ColumnSpec("range_fa", "بازه", TEXT, 200),
)

ITEM_COLUMNS = (
    ColumnSpec("product_code", "کد کالا", TEXT, 90, "center"),
    ColumnSpec("product_name", "نام کالا", TEXT, None),
    ColumnSpec("price", "قیمت", AMOUNT, 120),
    ColumnSpec("discount_percent", "تخفیف %", TEXT, 80, "center"),
    ColumnSpec("final_price", "قیمت نهایی", AMOUNT, 130),
    ColumnSpec("min_price", "حداقل قیمت", AMOUNT, 120),
)


class TaxRateDialog(QDialog):
    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.setWindowTitle("نرخ مالیات جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("کد", self.code_edit)
        self.title_edit = QLineEdit()
        form.addRow("عنوان", self.title_edit)
        self.percent_edit = QLineEdit("0")
        form.addRow("درصد *", self.percent_edit)
        self.applies_combo = QComboBox()
        for value, label in TAX_APPLIES:
            self.applies_combo.addItem(label, value)
        form.addRow("دامنهٔ اعمال", self.applies_combo)
        self.from_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("معتبر از", self.from_edit)
        self.to_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("معتبر تا (اختیاری)", self.to_edit)
        layout.addLayout(form)
        note = QLabel("نرخ‌ها تاریخ‌دار هستند؛ برای تغییر نرخ، رکورد جدید بسازید تا "
                      "فاکتورهای گذشته دست‌نخورده بمانند.")
        note.setObjectName("HintText")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            self.services.pricing.create_tax_rate(
                self.ctx, code=self.code_edit.text().strip(),
                title_fa=self.title_edit.text().strip(),
                percent=self.percent_edit.text().strip() or 0,
                applies_to=str(self.applies_combo.currentData()),
                valid_from=self.from_edit.date(), valid_to=self.to_edit.date())
        except AppError as error:
            show_error(self, "ثبت نرخ مالیات", error)
            return
        self.accept()


class PriceListDialog(QDialog):
    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.saved = None
        self.setWindowTitle("لیست قیمت جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        self.code_edit = QLineEdit()
        form.addRow("کد", self.code_edit)
        self.title_edit = QLineEdit()
        form.addRow("عنوان", self.title_edit)
        self.kind_combo = QComboBox()
        for kind in CC.PRICE_LIST_KINDS:
            self.kind_combo.addItem(CC.PRICE_LIST_TITLES_FA[kind], kind)
        form.addRow("نوع", self.kind_combo)
        self.party_combo = PickCombo()
        self.party_combo.load(services.persons.choices(ctx, role="customer"),
                              placeholder="— بدون مشتری خاص —")
        form.addRow("مشتری (اختیاری)", self.party_combo)
        self.discount_edit = QLineEdit("0")
        form.addRow("تخفیف درصدی", self.discount_edit)
        self.from_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("شروع", self.from_edit)
        self.to_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("پایان", self.to_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ثبت لیست و افزودن قیمت",
                                 QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            self.saved = self.services.pricing.create_price_list(
                self.ctx, code=self.code_edit.text().strip(),
                title_fa=self.title_edit.text().strip(),
                kind=str(self.kind_combo.currentData()),
                party_detail_id=self.party_combo.value(),
                discount_percent=self.discount_edit.text().strip() or 0,
                start_date=self.from_edit.date(), end_date=self.to_edit.date())
        except AppError as error:
            show_error(self, "ثبت لیست قیمت", error)
            return
        self.accept()


class SetPriceDialog(QDialog):
    def __init__(self, services, ctx, price_list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.price_list = price_list
        self.setWindowTitle(f"تعیین قیمت — {price_list.title_fa}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        self.product_combo = PickCombo()
        self.product_combo.load(services.catalogue.product_choices(ctx, limit=500))
        form.addRow("کالا", self.product_combo)
        self.price_edit = MoneyEdit()
        form.addRow("قیمت", self.price_edit)
        self.percent_edit = QLineEdit("0")
        form.addRow("تخفیف درصدی", self.percent_edit)
        self.amount_edit = MoneyEdit()
        form.addRow("تخفیف مبلغی", self.amount_edit)
        self.min_edit = MoneyEdit()
        form.addRow("حداقل قیمت", self.min_edit)
        self.reason_edit = QLineEdit()
        form.addRow("دلیل تغییر *", self.reason_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        if self.product_combo.value() is None:
            show_error(self, "تعیین قیمت", ValueError("کالا را انتخاب کنید."))
            return
        try:
            self.services.pricing.set_item_price(
                self.ctx, self.price_list.id, product_id=self.product_combo.value(),
                price=self.price_edit.amount,
                discount_percent=self.percent_edit.text().strip() or 0,
                discount_amount=self.amount_edit.amount,
                min_price=self.min_edit.amount, reason=self.reason_edit.text().strip())
        except AppError as error:
            show_error(self, "تعیین قیمت", error)
            return
        self.accept()


class PricingPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header = PageHeader("قیمت‌گذاری و مالیات",
                                 "نرخ‌های مالیات تاریخ‌دار و لیست‌های قیمت مشتری/فصلی")
        self.header.add_action("نرخ مالیات جدید", slot=self._new_tax)
        self.header.add_action("لیست قیمت جدید", variant="secondary", slot=self._new_list)
        self.header.add_action("تعیین قیمت", variant="secondary", slot=self._set_price)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        tax_page = QWidget()
        tax_layout = QVBoxLayout(tax_page)
        self.tax_table = DataTable(TAX_COLUMNS, formatter=self.formatter)
        tax_layout.addWidget(self.tax_table, 1)
        self.tabs.addTab(tax_page, "نرخ‌های مالیات")

        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        row = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("همهٔ انواع", None)
        for kind in CC.PRICE_LIST_KINDS:
            self.kind_combo.addItem(CC.PRICE_LIST_TITLES_FA[kind], kind)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.kind_combo, 1)
        row.addStretch(1)
        list_layout.addLayout(row)
        self.list_table = DataTable(PRICE_LIST_COLUMNS, formatter=self.formatter)
        self.list_table.on_selection_changed(self._load_items)
        list_layout.addWidget(self.list_table, 1)
        list_layout.addWidget(QLabel("اقلام لیست انتخاب‌شده"))
        self.item_table = DataTable(ITEM_COLUMNS, formatter=self.formatter)
        list_layout.addWidget(self.item_table, 1)
        self.tabs.addTab(list_page, "لیست‌های قیمت")
        self.root.addWidget(self.tabs, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.tax_table.set_rows(self.services.pricing.list_tax_rates(self.ctx))
            self.list_table.set_rows(self.services.pricing.list_price_lists(
                self.ctx, kind=self.kind_combo.currentData()))
        except AppError as error:
            show_error(self, "قیمت‌گذاری", error)
            return
        self.item_table.set_rows([])

    def _new_tax(self) -> None:
        if TaxRateDialog(self.services, self.ctx, parent=self).exec() == \
                QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify("نرخ مالیات ثبت شد.")

    def _new_list(self) -> None:
        dialog = PriceListDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"لیست قیمت «{dialog.saved.title_fa}» ثبت شد.")

    def _selected_list(self):
        index = self.list_table.selected_row_index()
        return self.list_table.model.row_at(index) if index is not None else None

    def _load_items(self, *_args) -> None:
        price_list = self._selected_list()
        self.item_table.set_rows(list(price_list.items) if price_list else [])

    def _set_price(self) -> None:
        price_list = self._selected_list()
        if price_list is None:
            show_error(self, "تعیین قیمت",
                       ValueError("ابتدا یک لیست قیمت را انتخاب کنید."))
            return
        dialog = SetPriceDialog(self.services, self.ctx, price_list, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify("قیمت لیست به‌روزرسانی شد.")
