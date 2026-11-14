"""The report designer: build a saved report out of the safe catalogue.

A designer report is **not** a query builder over tables. The user picks one of the
catalogue entries they are allowed to run, chooses the columns, the default
filters, the order and the grouping; the engine applies them. That is why the
designer cannot be used to read data the role may not see.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
)

from pars_erp.core.errors import AppError
from pars_erp.reporting.engine import ReportQuery
from pars_erp.services.report_engine_service import SaveReportInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.widgets.table import DataTable


class ReportDesignerPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate
        self._columns: list = []
        self._editing_id: int | None = None

        self.header = PageHeader("طراح گزارش",
                                 "گزارش سفارشی از منابع مجاز بسازید؛ هیچ پرس‌وجوی آزادی اجرا نمی‌شود")
        self.header.add_action("گزارش جدید", variant="ghost", slot=self.reset_form)
        self.header.add_action("ذخیره", slot=self.save)
        self.header.add_action("حذف", variant="ghost", slot=self.delete)
        self.root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(14)

        form_card = CardPanel("تعریف گزارش", "منبع، ستون‌ها و تنظیمات پیش‌فرض")
        form = QFormLayout()
        self.saved_combo = QComboBox()
        self.saved_combo.currentIndexChanged.connect(self._load_saved)
        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.date_from = JalaliDateEdit(_dt.date.today().replace(day=1),
                                        persian_digits=formatter.persian_digits,
                                        allow_empty=True)
        self.date_to = JalaliDateEdit(_dt.date.today(), persian_digits=formatter.persian_digits,
                                      allow_empty=True)
        self.sort_combo = QComboBox()
        self.group_combo = QComboBox()
        self.desc_check = QCheckBox("مرتب‌سازی نزولی")
        self.page_size_box = QSpinBox()
        self.page_size_box.setRange(10, 1000)
        self.page_size_box.setValue(100)
        self.share_roles = QLineEdit()
        self.share_roles.setPlaceholderText("کد نقش‌ها با کاما (اختیاری)")
        form.addRow("گزارش ذخیره‌شده", self.saved_combo)
        form.addRow("نام", self.name_edit)
        form.addRow("توضیح", self.description_edit)
        form.addRow("منبع گزارش", self.source_combo)
        form.addRow("از تاریخ", self.date_from)
        form.addRow("تا تاریخ", self.date_to)
        form.addRow("مرتب‌سازی", self.sort_combo)
        form.addRow("", self.desc_check)
        form.addRow("گروه‌بندی", self.group_combo)
        form.addRow("سطر در صفحه", self.page_size_box)
        form.addRow("اشتراک با نقش‌ها", self.share_roles)
        form_card.add_layout(form)
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setVisible(False)
        form_card.add(self.error_label)
        body.addWidget(form_card, 1)

        columns_card = CardPanel("ستون‌ها", "ستون‌هایی که در گزارش دیده می‌شوند")
        self.columns_list = QListWidget()
        columns_card.add(self.columns_list, 1)
        self.preview_button = QPushButton("پیش‌نمایش")
        self.preview_button.setProperty("variant", "ghost")
        self.preview_button.clicked.connect(self.preview)
        columns_card.add(self.preview_button)
        body.addWidget(columns_card, 1)
        self.root.addLayout(body)

        self.preview_card = CardPanel("پیش‌نمایش نتیجه", "پیش از ذخیره ببینید چه چیزی ساخته می‌شود")
        self.table = DataTable([], formatter=formatter)
        self.preview_card.add(self.table, 1)
        self.root.addWidget(self.preview_card, 1)

        self._fill_sources()
        self._fill_saved()

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._fill_sources()
        self._fill_saved()

    def _fill_sources(self) -> None:
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        if not self.can("reports.designer"):
            # The screen is also reachable programmatically; without the
            # permission it offers nothing and says why.
            self.source_combo.blockSignals(False)
            self.error_label.setText("برای ساخت گزارش سفارشی مجوز «reports.designer» لازم است.")
            self.error_label.setVisible(True)
            return
        try:
            for definition in self.services.report_engine.definitions(self.ctx):
                self.source_combo.addItem(
                    f"{definition.section_title_fa} — {definition.title_fa}", definition.key)
        except AppError:
            pass
        self.source_combo.blockSignals(False)
        self._source_changed()

    def _fill_saved(self) -> None:
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("— گزارش جدید —", None)
        try:
            for row in self.services.report_engine.saved_reports(self.ctx):
                if row.is_mine:
                    self.saved_combo.addItem(row.name, row.id)
        except AppError:
            pass
        self.saved_combo.blockSignals(False)

    def _source_changed(self) -> None:
        key = self.source_combo.currentData()
        self.columns_list.clear()
        self.sort_combo.clear()
        self.group_combo.clear()
        self.sort_combo.addItem("— بدون مرتب‌سازی —", None)
        self.group_combo.addItem("— بدون گروه‌بندی —", None)
        self._columns = []
        if not key:
            return
        try:
            self._columns = list(self.services.report_engine.columns(self.ctx, key))
        except AppError:
            return
        for column in self._columns:
            item = QListWidgetItem()
            box = QCheckBox(column.title_fa)
            box.setChecked(True)
            self.columns_list.addItem(item)
            self.columns_list.setItemWidget(item, box)
            item.setData(Qt.ItemDataRole.UserRole, column.key)
            self.sort_combo.addItem(column.title_fa, column.key)
            self.group_combo.addItem(column.title_fa, column.key)

    def _selected_columns(self) -> list[str]:
        keys = []
        for index in range(self.columns_list.count()):
            item = self.columns_list.item(index)
            box = self.columns_list.itemWidget(item)
            if box is not None and box.isChecked():
                keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return keys

    def _load_saved(self) -> None:
        saved_id = self.saved_combo.currentData()
        if not saved_id:
            return
        try:
            rows = {row.id: row for row in self.services
                    .report_engine.saved_reports(self.ctx)}
            row = rows.get(int(saved_id))
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        if row is None:
            return
        self._editing_id = row.id
        self.name_edit.setText(row.name)
        self.description_edit.setText(row.description)
        index = self.source_combo.findData(row.definition_key)
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        selected = set(row.column_keys)
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            box = self.columns_list.itemWidget(item)
            if box is not None and selected:
                box.setChecked(str(item.data(Qt.ItemDataRole.UserRole)) in selected)
        if row.sort_key:
            index = self.sort_combo.findData(row.sort_key)
            if index >= 0:
                self.sort_combo.setCurrentIndex(index)
        if row.group_by:
            index = self.group_combo.findData(row.group_by)
            if index >= 0:
                self.group_combo.setCurrentIndex(index)
        self.desc_check.setChecked(row.sort_desc)
        self.page_size_box.setValue(row.page_size)

    # ---------------------------------------------------------------- actions
    def reset_form(self) -> None:
        self._editing_id = None
        self.saved_combo.setCurrentIndex(0)
        self.name_edit.clear()
        self.description_edit.clear()
        self.share_roles.clear()
        self.error_label.setVisible(False)

    def _input(self) -> SaveReportInput:
        return SaveReportInput(
            name=self.name_edit.text(),
            definition_key=str(self.source_combo.currentData() or ""),
            description=self.description_edit.text(),
            column_keys=tuple(self._selected_columns()),
            date_from=self.date_from.date(), date_to=self.date_to.date(),
            sort_key=self.sort_combo.currentData(),
            sort_desc=self.desc_check.isChecked(),
            group_by=self.group_combo.currentData(),
            page_size=self.page_size_box.value())

    def save(self) -> None:
        try:
            if self._editing_id:
                saved = self.services.report_engine.update(self.ctx, self._editing_id,
                                                           self._input())
            else:
                saved = self.services.report_engine.save(self.ctx, self._input())
            roles = [code.strip() for code in self.share_roles.text().split(",") if code.strip()]
            if roles and self.can("reports.share"):
                saved = self.services.report_engine.share(self.ctx, saved.id, role_codes=roles)
        except AppError as exc:
            self.error_label.setText(getattr(exc, "message_fa", str(exc)))
            self.error_label.setVisible(True)
            return
        self._editing_id = saved.id
        self._fill_saved()
        show_info(self, "زرین هرمز", f"گزارش «{saved.name}» ذخیره شد.")

    def delete(self) -> None:
        if not self._editing_id:
            show_info(self, "زرین هرمز", "گزارشی را از فهرست انتخاب کنید.")
            return
        try:
            self.services.report_engine.delete(self.ctx, self._editing_id)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self.reset_form()
        self._fill_saved()

    def preview(self) -> None:
        from pars_erp.ui.table_specs import AMOUNT, DATE, NUMBER, TEXT, ColumnSpec
        from pars_erp.reporting.engine import KIND_AMOUNT, KIND_NUMBER
        from pars_erp.services.report_render_service import KIND_DATE

        data = self._input()
        query = ReportQuery(date_from=data.date_from, date_to=data.date_to,
                            sort_key=data.sort_key, sort_desc=data.sort_desc,
                            group_by=data.group_by,
                            column_keys=data.column_keys or None, page_size=100)
        try:
            result = self.services.report_engine.run(
                self.ctx, definition_key=data.definition_key, query=query)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        kind_map = {KIND_AMOUNT: AMOUNT, KIND_NUMBER: NUMBER, KIND_DATE: DATE}
        specs = [ColumnSpec(key=column.key, title_fa=column.title_fa,
                            kind=kind_map.get(column.kind, TEXT),
                            getter=lambda row, i=index: row[i] if i < len(row) else None)
                 for index, column in enumerate(result.columns)]
        self.table.set_columns(specs)
        self.table.set_rows(list(result.rows))
