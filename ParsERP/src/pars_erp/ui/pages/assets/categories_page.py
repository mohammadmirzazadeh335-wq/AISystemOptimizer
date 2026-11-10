"""دسته‌های دارایی ثابت — عمر مفید پیش‌فرض، روش استهلاک و سه حساب هر دسته."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from pars_erp.accounting import constants as C
from pars_erp.assets import constants as A
from pars_erp.core.errors import AppError
from pars_erp.services.assets_service import CategoryInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import AccountPicker
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.widgets import hint_label
from pars_erp.ui.table_specs import ASSET_CATEGORY_COLUMNS, TEXT, AMOUNT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable


class CategoryDialog(FormDialog):
    title_fa = "دستهٔ دارایی ثابت"
    width = 660

    def __init__(self, services, ctx, *, category=None, parent: QWidget | None = None) -> None:
        self.category = category
        super().__init__(services, ctx, parent=parent,
                         subtitle="هر دسته سه حساب دارد: دارایی، استهلاک انباشته و هزینهٔ "
                                  "استهلاک. سند استهلاک از همین سه حساب ساخته می‌شود.")

    def _account_choices(self):
        try:
            return [(row.id, row.display) for row in self.services.accounts.list_accounts(
                self.ctx, level=C.LEVEL_SUBSIDIARY, active=None)]
        except AppError:
            return []

    def _build(self) -> None:
        category = self.category
        self.code_edit = QLineEdit(category.code if category else "")
        self.code_edit.setPlaceholderText("خودکار")
        self.title_edit = QLineEdit(category.title_fa if category else "")
        self.add_pair(("کد دسته", self.code_edit), ("عنوان *", self.title_edit),
                      right_required=True)
        self.kind_combo = fill_combo(QComboBox(), A.CATEGORY_KINDS,
                                     current=category.kind if category else A.CAT_EQUIPMENT,
                                     placeholder="")
        self.life_spin = QSpinBox()
        self.life_spin.setRange(1, 100)
        self.life_spin.setSuffix(" سال")
        self.life_spin.setValue(int(category.default_useful_life_years) if category else 5)
        self.add_pair(("نوع دارایی", self.kind_combo), ("عمر مفید پیش‌فرض", self.life_spin))

        choices = self._account_choices()
        self.asset_picker = AccountPicker()
        self.asset_picker.load(choices, placeholder="— حساب دارایی —")
        if category is not None:
            self.asset_picker.set_account(category.asset_account_id)
        self.accumulated_picker = AccountPicker()
        self.accumulated_picker.load(choices, placeholder="— حساب استهلاک انباشته —")
        if category is not None:
            self.accumulated_picker.set_account(category.accumulated_account_id)
        self.add_pair(("حساب دارایی *", self.asset_picker),
                      ("حساب استهلاک انباشته *", self.accumulated_picker),
                      left_required=True, right_required=True)
        self.expense_picker = AccountPicker()
        self.expense_picker.load(choices, placeholder="— حساب هزینهٔ استهلاک —")
        if category is not None:
            self.expense_picker.set_account(category.expense_account_id)
        self.method_combo = fill_combo(QComboBox(), A.METHODS,
                                       current=category.default_method if category
                                       else A.METHOD_STRAIGHT_LINE, placeholder="")
        self.add_pair(("حساب هزینهٔ استهلاک *", self.expense_picker), ("روش پیش‌فرض", self.method_combo),
                      left_required=True)
        self.salvage_edit = QLineEdit(
            f"{Decimal(category.default_salvage_percent or 0):f}" if category else "0")
        self.add_row("درصد ارزش اسقاط پیش‌فرض", self.salvage_edit,
                     hint="درصدی از بهای تمام‌شده که مستهلک نمی‌شود.")
        self.description_edit = QLineEdit(
            category.description if category and hasattr(category, "description") else "")
        self.add_row("توضیحات", self.description_edit)
        self.active_check = QCheckBox("دسته فعال است")
        self.active_check.setChecked(bool(category.is_active) if category else True)
        self.add_widget(self.active_check)

    def save(self):
        data = CategoryInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            asset_account_id=self.asset_picker.current_account_id(),
            accumulated_account_id=self.accumulated_picker.current_account_id(),
            expense_account_id=self.expense_picker.current_account_id(),
            default_useful_life_years=self.life_spin.value(),
            default_method=str(self.method_combo.currentData()),
            default_salvage_percent=Decimal(self.salvage_edit.text().strip() or "0"),
            is_active=self.active_check.isChecked(),
            description=self.description_edit.text().strip(),
        )
        if self.category is None:
            return self.services.assets.create_category(self.ctx, data)
        return self.services.assets.update_category(self.ctx, self.category.id, data)


class AssetCategoriesPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "دسته‌های دارایی", "گروه‌بندی دارایی‌ها با عمر مفید، روش استهلاک و حساب‌های "
                              "پیش‌فرض هر دسته")
        self.new_button = self.header.add_action("دستهٔ جدید", slot=self._new)
        self.edit_button = self.header.add_action("ویرایش", variant="secondary",
                                                  slot=self._edit)
        self.root.addWidget(self.header)

        self.table = DataTable(ASSET_CATEGORY_COLUMNS, formatter=formatter)
        card = CardPanel("دسته‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        can_edit = self.can("assets.register")
        self.new_button.setEnabled(can_edit)
        self.edit_button.setEnabled(can_edit)
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rows = self.services.assets.list_categories(self.ctx)
        except AppError as error:
            show_error(self, "دسته‌های دارایی", error)
            return
        self.set_rows(self.table, self.rows)
        assets = sum(row.assets_count for row in self.rows)
        self.summary.setText(f"{len(self.rows):,} دسته — {assets:,} دارایی")

    def _selected(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    def _new(self) -> None:
        dialog = CategoryDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"دستهٔ «{dialog.saved.title_fa}» ایجاد شد.")

    def _edit(self) -> None:
        category = self._selected()
        if category is None:
            show_info(self, "ویرایش", "ابتدا یک دسته را انتخاب کنید.")
            return
        dialog = CategoryDialog(self.services, self.ctx, category=category, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("دسته به‌روزرسانی شد.")
