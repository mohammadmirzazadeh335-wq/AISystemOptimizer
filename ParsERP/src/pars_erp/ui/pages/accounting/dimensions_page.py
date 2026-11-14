"""Cost centres, projects and currency rates.

All three are optional dimensions: a journal line may carry them, which is what
makes «گزارش گردش مرکز هزینه» and «گردش پروژه» possible later.
"""

from __future__ import annotations

import datetime as _dt

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
    QVBoxLayout,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.services.dimensions_service import DimensionInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

DIMENSION_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 100, "center"),
    ColumnSpec("title_fa", "عنوان", TEXT, None),
    ColumnSpec("kind", "نوع/دسته", TEXT, 140),
    ColumnSpec("start_date", "شروع", DATE, 100, "center"),
    ColumnSpec("end_date", "پایان", DATE, 100, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 92, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
    ColumnSpec("description", "توضیحات", TEXT, 220),
)

RATE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("currency_code", "ارز", TEXT, 90, "center"),
    ColumnSpec("rate_date", "تاریخ", DATE, 110, "center"),
    ColumnSpec("rate", "نرخ (به ارز پایه)", AMOUNT, 160, "left"),
    ColumnSpec("note", "یادداشت", TEXT, None),
)


class DimensionDialog(QDialog):
    def __init__(self, services, ctx, *, dimension: str, item=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.dimension = dimension
        self.item = item
        self.saved = None
        title = "مرکز هزینه" if dimension == "cost_center" else "پروژه"
        self.setWindowTitle(f"ویرایش {title}" if item else f"{title} جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.code_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.kind_edit = QLineEdit()
        self.kind_edit.setPlaceholderText("مثلاً: اداری، تولیدی، عمرانی")
        self.start_edit = JalaliDateEdit(None, allow_empty=True)
        self.end_edit = JalaliDateEdit(None, allow_empty=True)
        self.status_combo = QComboBox()
        for status, title_fa in C.PROJECT_STATUS_TITLES_FA.items():
            self.status_combo.addItem(title_fa, status)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(58)
        self.active_check = QCheckBox("فعال است")
        self.active_check.setChecked(True)

        form.addRow("کد", self.code_edit)
        form.addRow("عنوان", self.title_edit)
        form.addRow("دسته/نوع", self.kind_edit)
        if dimension == "project":
            form.addRow("وضعیت پروژه", self.status_combo)
            form.addRow("تاریخ شروع", self.start_edit)
            form.addRow("تاریخ پایان", self.end_edit)
        form.addRow("", self.active_check)
        form.addRow("توضیحات", self.description_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if item is not None:
            self.code_edit.setText(item.code)
            self.title_edit.setText(item.title_fa)
            self.kind_edit.setText(item.kind or "")
            self.start_edit.set_date(item.start_date)
            self.end_edit.set_date(item.end_date)
            self.active_check.setChecked(item.is_active)
            self.description_edit.setPlainText(item.description or "")
            self.status_combo.setCurrentIndex(
                max(0, self.status_combo.findData(item.status)))

    def _save(self) -> None:
        data = DimensionInput(
            code=self.code_edit.text().strip(), title_fa=self.title_edit.text().strip(),
            kind=self.kind_edit.text().strip(), description=self.description_edit.toPlainText().strip(),
            is_active=self.active_check.isChecked(),
            status=str(self.status_combo.currentData() or C.PROJECT_ACTIVE),
            start_date=self.start_edit.date(), end_date=self.end_edit.date())
        try:
            if self.dimension == "cost_center":
                if self.item is None:
                    self.saved = self.services.dimensions.create_cost_center(self.ctx, data)
                else:
                    self.saved = self.services.dimensions.update_cost_center(
                        self.ctx, self.item.id, data)
            else:
                if self.item is None:
                    self.saved = self.services.dimensions.create_project(self.ctx, data)
                else:
                    self.saved = self.services.dimensions.update_project(
                        self.ctx, self.item.id, data)
        except AppError as error:
            show_error(self, "ثبت", error)
            return
        self.accept()


class DimensionsPage(PageBase):
    """Two tabs: cost centres and projects."""

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader("مراکز هزینه و پروژه‌ها",
                                 "ابعاد اختیاری سطرهای سند برای گزارش‌گیری مدیریتی")
        self.new_button = self.header.add_action("مرکز هزینه جدید", slot=self._new_cost_center)
        self.header.add_action("پروژه جدید", variant="ghost", slot=self._new_project)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        from PySide6.QtWidgets import QTabWidget

        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)

        self.cost_table = DataTable(DIMENSION_COLUMNS, formatter=self.formatter)
        self.project_table = DataTable(DIMENSION_COLUMNS, formatter=self.formatter)
        for table, label, dimension in (
                (self.cost_table, "مراکز هزینه", "cost_center"),
                (self.project_table, "پروژه‌ها", "project")):
            card = CardPanel(label)
            card.add(table, 1)
            buttons = QHBoxLayout()
            edit = QPushButton("ویرایش")
            edit.setProperty("variant", "ghost")
            edit.clicked.connect(lambda _c=False, d=dimension, t=table: self._edit(d, t))
            buttons.addWidget(edit)
            deactivate = QPushButton("فعال/غیرفعال")
            deactivate.setProperty("variant", "ghost")
            deactivate.clicked.connect(
                lambda _c=False, d=dimension, t=table: self._toggle(d, t))
            buttons.addWidget(deactivate)
            buttons.addStretch(1)
            card.add_layout(buttons)
            self.tabs.addTab(card, label)
            table.rowActivated.connect(lambda _i, d=dimension, t=table: self._edit(d, t))

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.cost_table.set_rows(self.services.dimensions.list_cost_centers(self.ctx))
            self.project_table.set_rows(self.services.dimensions.list_projects(self.ctx))
        except AppError as error:
            show_error(self, "مراکز هزینه و پروژه‌ها", error)

    # ---------------------------------------------------------------- actions
    def _new_cost_center(self) -> None:
        self._create("cost_center")

    def _new_project(self) -> None:
        self._create("project")

    def _create(self, dimension: str) -> None:
        if not self.can("dimensions.edit"):
            self.notify("برای تعریف ابعاد، مجوز «ویرایش ابعاد» لازم است.")
            return
        dialog = DimensionDialog(self.services, self.ctx, dimension=dimension, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify("با موفقیت ثبت شد.")
            self.refresh()

    def _edit(self, dimension: str, table: DataTable) -> None:
        row = table.current_row()
        if row is None:
            self.notify("ابتدا یک ردیف را انتخاب کنید.")
            return
        if not self.can("dimensions.edit"):
            self.notify("برای ویرایش، مجوز «ویرایش ابعاد» لازم است.")
            return
        dialog = DimensionDialog(self.services, self.ctx, dimension=dimension, item=row,
                                 parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify("به‌روزرسانی شد.")
            self.refresh()

    def _toggle(self, dimension: str, table: DataTable) -> None:
        row = table.current_row()
        if row is None:
            self.notify("ابتدا یک ردیف را انتخاب کنید.")
            return
        if not self.can("dimensions.edit"):
            self.notify("برای تغییر وضعیت، مجوز «ویرایش ابعاد» لازم است.")
            return
        try:
            updated = DimensionInput(
                code=row.code, title_fa=row.title_fa, kind=row.kind,
                description=row.description, is_active=not row.is_active,
                status=row.status, start_date=row.start_date, end_date=row.end_date)
            if dimension == "cost_center":
                self.services.dimensions.update_cost_center(self.ctx, row.id, updated)
            else:
                self.services.dimensions.update_project(self.ctx, row.id, updated)
        except AppError as error:
            show_error(self, "تغییر وضعیت", error)
            return
        self.refresh()


class CurrenciesPage(PageBase):
    """Currency rates: the base currency plus historical rates per date."""

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader("ارزها و نرخ‌ها",
                                 "نرخ هر ارز در تاریخ ثبت می‌شود و در سند ذخیره می‌ماند")
        self.header.add_action("ثبت نرخ", slot=self._add_rate)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        filter_card = CardPanel()
        row = QHBoxLayout()
        self.currency_filter = QComboBox()
        self.currency_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(QLabel("ارز"))
        row.addWidget(self.currency_filter)
        row.addStretch(1)
        filter_card.add_layout(row)
        self.root.addWidget(filter_card)

        card = CardPanel("نرخ‌های ثبت‌شده")
        self.table = DataTable(RATE_COLUMNS, formatter=self.formatter)
        card.add(self.table, 1)
        self.note = QLabel("")
        self.note.setObjectName("HintText")
        self.note.setWordWrap(True)
        card.add(self.note)
        self.root.addWidget(card, 1)

    def refresh(self) -> None:
        if self.currency_filter.count() == 0:
            try:
                self.currency_filter.blockSignals(True)
                self.currency_filter.addItem("همه ارزها", None)
                for code, title in self.services.currency.currency_choices():
                    self.currency_filter.addItem(f"{title} ({code})", code)
                self.currency_filter.blockSignals(False)
            except AppError:
                pass
        try:
            base = self.services.currency.base_currency()
            rows = self.services.currency.rates(self.ctx,
                                                self.currency_filter.currentData())
        except AppError as error:
            show_error(self, "ارزها", error)
            return
        self.table.set_rows(rows)
        self.note.setText(f"ارز پایه: {base}. برای ارز پایه نرخ ثبت نمی‌شود؛ نرخ سایر ارزها "
                          "در تاریخ سند استفاده می‌شود.")

    def _add_rate(self) -> None:
        if not self.can("accounting.settings"):
            self.notify("برای ثبت نرخ ارز مجوز «تنظیمات حسابداری» لازم است.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("ثبت نرخ ارز")
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        currency_combo = QComboBox()
        try:
            for code, title in self.services.currency.currency_choices():
                currency_combo.addItem(f"{title} ({code})", code)
        except AppError:
            pass
        date_edit = JalaliDateEdit(_dt.date.today())
        rate_edit = MoneyEdit()
        note_edit = QLineEdit()
        form.addRow("ارز", currency_combo)
        form.addRow("تاریخ", date_edit)
        form.addRow("نرخ (هر واحد به ارز پایه)", rate_edit)
        form.addRow("یادداشت", note_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox()
        buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.currency.set_rate(
                self.ctx, str(currency_combo.currentData()), date_edit.date() or _dt.date.today(),
                rate_edit.amount, note_edit.text().strip())
        except AppError as error:
            show_error(self, "ثبت نرخ ارز", error)
            return
        show_info(self, "ثبت نرخ ارز", "نرخ ارز ذخیره شد.", tone="success")
        self.refresh()
