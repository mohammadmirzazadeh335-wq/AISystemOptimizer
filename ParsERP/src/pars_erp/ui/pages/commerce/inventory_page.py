"""Warehouses, stock documents, balances/cardex and stock counts."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.services.inventory_service import (
    CountLineInput,
    StockDocFilter,
    StockLineInput,
    WarehouseInput,
    WarehouseRow,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

WAREHOUSE_COLUMNS = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "نام انبار", TEXT, None),
    ColumnSpec("keeper", "انباردار", TEXT, 140),
    ColumnSpec("valuation_fa", "روش ارزش‌گذاری", TEXT, 160),
    ColumnSpec("item_count", "تعداد اقلام", NUMBER, 100, "center"),
    ColumnSpec("total_value", "ارزش موجودی", AMOUNT, 140),
    ColumnSpec("status_fa", "وضعیت", BADGE, 80, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)

DOCUMENT_COLUMNS = (
    ColumnSpec("number", "شماره سند", TEXT, 130, "center"),
    ColumnSpec("doc_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 120),
    ColumnSpec("warehouse_title", "انبار", TEXT, 130),
    ColumnSpec("target_title", "انبار مقصد", TEXT, 120),
    ColumnSpec("line_count", "تعداد ردیف", NUMBER, 90, "center"),
    ColumnSpec("total_value", "ارزش", AMOUNT, 130),
    ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
)

BALANCE_COLUMNS = (
    ColumnSpec("code", "کد کالا", TEXT, 100, "center"),
    ColumnSpec("name_fa", "نام کالا", TEXT, None),
    ColumnSpec("warehouse_title", "انبار", TEXT, 130),
    ColumnSpec("unit_title", "واحد", TEXT, 70, "center"),
    ColumnSpec("quantity", "موجودی", NUMBER, 90, "center"),
    ColumnSpec("average_cost", "بهای میانگین", AMOUNT, 120),
    ColumnSpec("value", "ارزش", AMOUNT, 130),
    ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
)

CARDEX_COLUMNS = (
    ColumnSpec("doc_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("number", "شماره سند", TEXT, 130, "center"),
    ColumnSpec("kind_fa", "نوع عملیات", TEXT, 110),
    ColumnSpec("warehouse_title", "انبار", TEXT, 120),
    ColumnSpec("quantity_in", "ورود", NUMBER, 80, "center"),
    ColumnSpec("quantity_out", "خروج", NUMBER, 80, "center"),
    ColumnSpec("balance", "مانده", NUMBER, 90, "center"),
    ColumnSpec("unit_cost", "بهای واحد", AMOUNT, 110),
    ColumnSpec("value", "ارزش", AMOUNT, 120),
    ColumnSpec("note", "توضیح", TEXT, 160),
)


class WarehouseDialog(QDialog):
    def __init__(self, services, ctx, *, warehouse: WarehouseRow | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.warehouse = warehouse
        self.saved = None
        self.setWindowTitle("ویرایش انبار" if warehouse else "انبار جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.code_edit = QLineEdit()
        form.addRow("کد انبار *", self.code_edit)
        self.title_edit = QLineEdit()
        form.addRow("نام انبار *", self.title_edit)
        self.keeper_edit = QLineEdit()
        form.addRow("انباردار", self.keeper_edit)
        self.address_edit = QPlainTextEdit()
        self.address_edit.setFixedHeight(50)
        form.addRow("نشانی", self.address_edit)
        self.method_combo = QComboBox()
        self.method_combo.addItem("پیش‌فرض شرکت", None)
        for method in CC.VALUATION_METHODS:
            self.method_combo.addItem(CC.VALUATION_TITLES_FA[method], method)
        form.addRow("روش ارزش‌گذاری", self.method_combo)
        self.primary_check = QCheckBox("انبار اصلی است")
        form.addRow("", self.primary_check)
        self.negative_check = QCheckBox("اجازهٔ موجودی منفی (نیازمند مجوز مدیر)")
        form.addRow("", self.negative_check)
        self.active_check = QCheckBox("انبار فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if warehouse is not None:
            self.code_edit.setText(warehouse.code)
            self.title_edit.setText(warehouse.title_fa)
            self.keeper_edit.setText(warehouse.keeper)
            self.address_edit.setPlainText(warehouse.address)
            self.method_combo.setCurrentIndex(
                max(0, self.method_combo.findData(warehouse.valuation_method))
                if warehouse.valuation_method != CC.VALUATION_AVERAGE else 0)
            self.primary_check.setChecked(warehouse.is_primary)
            self.negative_check.setChecked(warehouse.allow_negative)
            self.active_check.setChecked(warehouse.is_active)

    def _save(self) -> None:
        data = WarehouseInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            keeper=self.keeper_edit.text().strip(),
            address=self.address_edit.toPlainText().strip(),
            is_primary=self.primary_check.isChecked(),
            is_active=self.active_check.isChecked(),
            allow_negative=self.negative_check.isChecked(),
            valuation_method=self.method_combo.currentData(),
        )
        try:
            if self.warehouse is None:
                self.saved = self.services.inventory.create_warehouse(self.ctx, data)
            else:
                self.saved = self.services.inventory.update_warehouse(
                    self.ctx, self.warehouse.id, data)
        except AppError as error:
            show_error(self, "ثبت انبار", error)
            return
        self.accept()


class StockDocumentDialog(QDialog):
    """Receipt / issue / transfer / adjustment entry form with line rows."""

    def __init__(self, services, ctx, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.kind = kind
        self.saved = None
        title = CC.STOCK_MOVE_TITLES_FA.get(kind, kind)
        self.setWindowTitle(f"ثبت {title}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(920, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.warehouse_combo = PickCombo()
        warehouses = services.inventory.warehouse_choices(ctx)
        self.warehouse_combo.load(warehouses)
        if warehouses:
            self.warehouse_combo.set_value(warehouses[0][0])  # primary first
        header.addWidget(form_row("انبار مبدأ *", self.warehouse_combo))
        if kind == CC.MOVE_TRANSFER:
            self.target_combo = PickCombo()
            self.target_combo.load(warehouses)
            if len(warehouses) > 1:
                self.target_combo.set_value(warehouses[1][0])
            header.addWidget(form_row("انبار مقصد *", self.target_combo))
        self.date_edit = JalaliDateEdit(_dt.date.today())
        header.addWidget(form_row("تاریخ *", self.date_edit))
        layout.addLayout(header)

        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("توضیح سند؛ برای اصلاح موجودی، دلیل الزامی است")
        layout.addWidget(form_row("توضیح", self.note_edit))

        self.lines = QTableWidget(0, 4 if kind != CC.MOVE_ADJUSTMENT else 5)
        headers = ["کالا", "مقدار", "بهای واحد", "توضیح"]
        if kind == CC.MOVE_ADJUSTMENT:
            headers.insert(2, "جهت")
        self.lines.setHorizontalHeaderLabels(headers)
        self.lines.verticalHeader().setVisible(False)
        self.lines.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.lines.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.lines, 1)

        row_actions = QHBoxLayout()
        add = QPushButton("افزودن ردیف")
        add.clicked.connect(self._add_row)
        row_actions.addWidget(add)
        remove = QPushButton("حذف ردیف")
        remove.setProperty("variant", "ghost")
        remove.clicked.connect(self._remove_row)
        row_actions.addWidget(remove)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        products = services.catalogue.product_choices(ctx, active_only=True, limit=500)
        self._products = products
        self._add_row()

        buttons = QDialogButtonBox()
        save = buttons.addButton("ثبت و قطعی‌سازی", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self) -> None:
        row = self.lines.rowCount()
        self.lines.insertRow(row)
        combo = PickCombo()
        combo.load(self._products)
        self.lines.setCellWidget(row, 0, combo)
        self.lines.setItem(row, 1, QTableWidgetItem("1"))
        if self.kind == CC.MOVE_ADJUSTMENT:
            direction = QComboBox()
            direction.addItem("ورود", "in")
            direction.addItem("خروج", "out")
            self.lines.setCellWidget(row, 2, direction)
            self.lines.setItem(row, 3, QTableWidgetItem("0"))
            self.lines.setItem(row, 4, QTableWidgetItem(""))
        else:
            self.lines.setItem(row, 2, QTableWidgetItem("0"))
            self.lines.setItem(row, 3, QTableWidgetItem(""))

    def _remove_row(self) -> None:
        row = self.lines.currentRow()
        if row >= 0 and self.lines.rowCount() > 1:
            self.lines.removeRow(row)

    def _save(self) -> None:
        warehouse_id = self.warehouse_combo.value()
        if warehouse_id is None:
            show_info(self, "ثبت سند انبار", "انبار را انتخاب کنید.")
            return
        lines = []
        for row in range(self.lines.rowCount()):
            combo = self.lines.cellWidget(row, 0)
            product_id = combo.value() if combo else None
            quantity = (self.lines.item(row, 1).text() if self.lines.item(row, 1) else "0")
            if product_id is None or not str(quantity).strip():
                continue
            if self.kind == CC.MOVE_ADJUSTMENT:
                direction_combo = self.lines.cellWidget(row, 2)
                direction = (direction_combo.currentData() if direction_combo else "in")
                price_item = self.lines.item(row, 3)
                note_item = self.lines.item(row, 4)
            else:
                direction = "in"
                price_item = self.lines.item(row, 2)
                note_item = self.lines.item(row, 3)
            lines.append(StockLineInput(
                product_id=product_id, quantity=quantity, direction=direction,
                unit_cost=(price_item.text() if price_item else 0) or 0,
                note=(note_item.text() if note_item else "") or ""))
        if not lines:
            show_info(self, "ثبت سند انبار", "حداقل یک ردیف کامل وارد کنید.")
            return
        day = self.date_edit.date() or _dt.date.today()
        note = self.note_edit.text().strip()
        try:
            if self.kind == CC.MOVE_RECEIPT:
                self.saved = self.services.inventory.record_receipt(
                    self.ctx, warehouse_id=warehouse_id, lines=tuple(lines),
                    doc_date=day, note=note)
            elif self.kind == CC.MOVE_ISSUE:
                self.saved = self.services.inventory.record_issue(
                    self.ctx, warehouse_id=warehouse_id, lines=tuple(lines),
                    doc_date=day, note=note)
            elif self.kind == CC.MOVE_TRANSFER:
                target = self.target_combo.value()
                if target is None:
                    show_info(self, "انتقال انبار", "انبار مقصد را انتخاب کنید.")
                    return
                self.saved = self.services.inventory.record_transfer(
                    self.ctx, warehouse_id=warehouse_id, target_warehouse_id=target,
                    lines=tuple(lines), doc_date=day, note=note)
            else:
                self.saved = self.services.inventory.record_adjustment(
                    self.ctx, warehouse_id=warehouse_id, lines=tuple(lines),
                    reason=note, doc_date=day)
        except AppError as error:
            show_error(self, "ثبت سند انبار", error)
            return
        self.accept()


class CardexDialog(QDialog):
    def __init__(self, services, ctx, *, product_id: int | None = None,
                 warehouse_id: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("کاردکس کالا")
        self.resize(1000, 560)
        self.services = services
        self.ctx = ctx
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        row = QHBoxLayout()
        self.product_combo = PickCombo()
        self.product_combo.load(services.catalogue.product_choices(ctx, limit=500))
        self.product_combo.set_value(product_id)
        row.addWidget(form_row("کالا", self.product_combo), 2)
        self.warehouse_combo = PickCombo()
        self.warehouse_combo.load(services.inventory.warehouse_choices(ctx))
        self.warehouse_combo.set_value(warehouse_id)
        row.addWidget(form_row("انبار", self.warehouse_combo), 1)
        load = QPushButton("نمایش کاردکس")
        load.setProperty("variant", "primary")
        load.clicked.connect(self._load)
        row.addWidget(load, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        layout.addLayout(row)
        self.table = DataTable(CARDEX_COLUMNS)
        layout.addWidget(self.table, 1)
        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignLeft)
        if product_id:
            self._load()

    def _load(self) -> None:
        product_id = self.product_combo.value()
        if product_id is None:
            show_info(self, "کاردکس", "کالا را انتخاب کنید.")
            return
        try:
            rows = self.services.inventory.cardex(
                self.ctx, product_id, warehouse_id=self.warehouse_combo.value())
        except AppError as error:
            show_error(self, "کاردکس", error)
            return
        self.table.set_rows(rows)


class StockCountDialog(QDialog):
    """Record counted quantities and approve the sheet."""

    def __init__(self, services, ctx, sheet_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.sheet_id = sheet_id
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(900, 620)
        data = services.inventory.count_sheet(ctx, sheet_id)
        self.setWindowTitle(f"انبارگردانی {data['number']}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        head = QLabel(f"شماره {data['number']} | انبار {data['warehouse_title']} | "
                      f"وضعیت {data['status_fa']}")
        head.setObjectName("SectionTitle")
        layout.addWidget(head)

        self.table = QTableWidget(len(data["lines"]), 6)
        self.table.setHorizontalHeaderLabels(
            ["کد", "کالا", "موجودی سیستم", "مقدار شمارش‌شده", "اختلاف", "توضیح"])
        self.table.verticalHeader().setVisible(False)
        self.table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._product_ids: list[int] = []
        for row, line in enumerate(data["lines"]):
            self._product_ids.append(line["product_id"])
            self.table.setItem(row, 0, QTableWidgetItem(line["code"]))
            self.table.setItem(row, 1, QTableWidgetItem(line["name"]))
            self.table.setItem(row, 2, QTableWidgetItem(str(line["system_quantity"])))
            counted = QTableWidgetItem(str(line["counted_quantity"]))
            self.table.setItem(row, 3, counted)
            self.table.setItem(row, 4, QTableWidgetItem(str(line["difference"])))
            self.table.setItem(row, 5, QTableWidgetItem(line["note"]))
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        save = QPushButton("ذخیرهٔ شمارش")
        save.clicked.connect(self._save_counts)
        buttons.addWidget(save)
        approve = QPushButton("تأیید و ثبت اصلاح موجودی")
        approve.setProperty("variant", "primary")
        approve.clicked.connect(self._approve)
        buttons.addWidget(approve)
        buttons.addStretch(1)
        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _entries(self) -> list[CountLineInput]:
        entries = []
        for row, product_id in enumerate(self._product_ids):
            counted = self.table.item(row, 3)
            note = self.table.item(row, 5)
            entries.append(CountLineInput(
                product_id=product_id,
                counted_quantity=(counted.text() if counted else 0) or 0,
                note=(note.text() if note else "") or ""))
        return entries

    def _save_counts(self) -> None:
        try:
            self.services.inventory.record_count(self.ctx, self.sheet_id, self._entries())
        except AppError as error:
            show_error(self, "ثبت شمارش", error)
            return
        show_info(self, "ثبت شمارش", "مقادیر شمارش ذخیره شد.", tone="success")

    def _approve(self) -> None:
        reason = ask_reason(self, "تأیید انبارگردانی",
                            "دلیل/توضیح تأیید مغایرت را بنویسید (حداقل ۵ نویسه):")
        if reason is None:
            show_info(self, "تأیید انبارگردانی", "دلیل تأیید را کامل وارد کنید.")
            return
        try:
            self.services.inventory.record_count(self.ctx, self.sheet_id, self._entries())
            self.services.inventory.approve_count(self.ctx, self.sheet_id, reason)
        except AppError as error:
            show_error(self, "تأیید انبارگردانی", error)
            return
        show_info(self, "انبارگردانی",
                  "برگه تأیید و سند اصلاح موجودی ثبت شد.", tone="success")
        self.accept()


class InventoryPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header = PageHeader("انبارها و موجودی",
                                 "رسید، حواله، انتقال، اصلاح، کاردکس و انبارگردانی")
        self.header.add_action("رسید انبار", slot=lambda: self._new_document("receipt"))
        self.header.add_action("حواله خروج", variant="secondary",
                               slot=lambda: self._new_document("issue"))
        self.header.add_action("انتقال", variant="secondary",
                               slot=lambda: self._new_document("transfer"))
        self.header.add_action("اصلاح موجودی", variant="ghost",
                               slot=lambda: self._new_document("adjustment"))
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_warehouses_tab(), "انبارها")
        self.tabs.addTab(self._build_balances_tab(), "موجودی و کاردکس")
        self.tabs.addTab(self._build_documents_tab(), "اسناد انبار")
        self.tabs.addTab(self._build_counts_tab(), "انبارگردانی")
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        self.root.addWidget(self.tabs, 1)
        self.refresh()

    # ------------------------------------------------------------------ tabs
    def _build_warehouses_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        add = QPushButton("انبار جدید")
        add.setProperty("variant", "primary")
        add.clicked.connect(self._new_warehouse)
        row.addWidget(add)
        edit = QPushButton("ویرایش انبار")
        edit.clicked.connect(self._edit_warehouse)
        row.addWidget(edit)
        row.addStretch(1)
        layout.addLayout(row)
        self.warehouse_table = DataTable(WAREHOUSE_COLUMNS, formatter=self.formatter)
        layout.addWidget(self.warehouse_table, 1)
        return page

    def _build_balances_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.balance_search = SearchInput("جست‌وجوی کالا…")
        self.balance_search.searchChanged.connect(self._refresh_balances)
        row.addWidget(self.balance_search, 2)
        self.balance_warehouse = PickCombo()
        self.balance_warehouse.currentIndexChanged.connect(self._refresh_balances)
        row.addWidget(self.balance_warehouse, 1)
        self.zero_only = QCheckBox("فقط ناموجود")
        self.zero_only.stateChanged.connect(self._refresh_balances)
        row.addWidget(self.zero_only)
        self.low_only = QCheckBox("فقط کم‌موجود")
        self.low_only.stateChanged.connect(self._refresh_balances)
        row.addWidget(self.low_only)
        layout.addLayout(row)
        self.balance_table = DataTable(BALANCE_COLUMNS, formatter=self.formatter)
        self.balance_table.rowActivated.connect(self._open_cardex)
        self.total_label = QLabel("")
        self.total_label.setObjectName("HintText")
        layout.addWidget(self.total_label)
        layout.addWidget(self.balance_table, 1)
        return page

    def _build_documents_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.doc_search = SearchInput("جست‌وجوی شماره سند…")
        self.doc_search.searchChanged.connect(self._refresh_documents)
        row.addWidget(self.doc_search, 2)
        self.doc_kind = QComboBox()
        self.doc_kind.addItem("همهٔ انواع", None)
        for kind in CC.STOCK_MOVE_KINDS:
            self.doc_kind.addItem(CC.STOCK_MOVE_TITLES_FA[kind], kind)
        self.doc_kind.currentIndexChanged.connect(self._refresh_documents)
        row.addWidget(self.doc_kind, 1)
        reverse = QPushButton("برگشت سند")
        reverse.setProperty("variant", "ghost")
        reverse.clicked.connect(self._reverse_document)
        row.addWidget(reverse)
        layout.addLayout(row)
        self.document_table = DataTable(DOCUMENT_COLUMNS, formatter=self.formatter)
        layout.addWidget(self.document_table, 1)
        return page

    def _build_counts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.count_warehouse = PickCombo()
        row.addWidget(form_row("انبار", self.count_warehouse))
        create = QPushButton("ایجاد برگهٔ انبارگردانی")
        create.setProperty("variant", "primary")
        create.clicked.connect(self._create_count)
        row.addWidget(create, alignment=Qt.AlignmentFlag.AlignBottom)
        open_button = QPushButton("باز کردن برگه")
        open_button.clicked.connect(self._open_count)
        row.addWidget(open_button, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        layout.addLayout(row)
        self.count_table = DataTable((
            ColumnSpec("number", "شماره", TEXT, 130, "center"),
            ColumnSpec("count_date", "تاریخ", DATE, 100, "center"),
            ColumnSpec("warehouse", "انبار", TEXT, 140),
            ColumnSpec("lines", "تعداد ردیف", NUMBER, 90, "center"),
            ColumnSpec("differences", "ردیف مغایر", NUMBER, 100, "center"),
            ColumnSpec("status_fa", "وضعیت", TEXT, 100, "center"),
        ), formatter=self.formatter)
        self.count_table.rowActivated.connect(lambda _row: self._open_count())
        layout.addWidget(self.count_table, 1)
        return page

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        try:
            self.warehouse_table.set_rows(self.services.inventory.list_warehouses(self.ctx))
            if self.balance_warehouse.count() == 0:
                self.balance_warehouse.load(
                    self.services.inventory.warehouse_choices(self.ctx))
            if self.count_warehouse.count() == 0:
                self.count_warehouse.load(
                    self.services.inventory.warehouse_choices(self.ctx))
            self._refresh_balances()
            self._refresh_documents()
            self.count_table.set_rows(self.services.inventory.count_sheets(self.ctx))
        except AppError as error:
            show_error(self, "اطلاعات انبار", error)

    def _refresh_balances(self) -> None:
        try:
            rows = self.services.inventory.balances(
                self.ctx, warehouse_id=self.balance_warehouse.value(),
                search=self.balance_search.text().strip(),
                zero_only=self.zero_only.isChecked(), low_only=self.low_only.isChecked())
        except AppError as error:
            show_error(self, "موجودی", error)
            return
        self.balance_table.set_rows(rows)
        total = sum((row.value for row in rows), Decimal("0"))
        self.total_label.setText(f"{len(rows):,} ردیف | ارزش: {total:,}")

    def _refresh_documents(self) -> None:
        try:
            rows = self.services.inventory.list_documents(self.ctx, StockDocFilter(
                kind=self.doc_kind.currentData(),
                search=self.doc_search.text().strip()))
        except AppError as error:
            show_error(self, "اسناد انبار", error)
            return
        self.document_table.set_rows(rows)

    # --------------------------------------------------------------- actions
    def _new_warehouse(self) -> None:
        dialog = WarehouseDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"انبار «{dialog.saved.title_fa}» ثبت شد.")

    def _edit_warehouse(self) -> None:
        index = self.warehouse_table.selected_row_index()
        if index is None:
            show_info(self, "ویرایش انبار", "ابتدا یک انبار را انتخاب کنید.")
            return
        warehouse = self.warehouse_table.model.row_at(index)
        dialog = WarehouseDialog(self.services, self.ctx, warehouse=warehouse, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify("انبار به‌روزرسانی شد.")

    def _new_document(self, kind: str) -> None:
        dialog = StockDocumentDialog(self.services, self.ctx, kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"سند {dialog.saved.number} ثبت و قطعی شد.")

    def _reverse_document(self) -> None:
        index = self.document_table.selected_row_index()
        if index is None:
            show_info(self, "برگشت سند", "ابتدا یک سند را انتخاب کنید.")
            return
        document = self.document_table.model.row_at(index)
        reason = ask_reason(self, "برگشت سند انبار",
                            "دلیل برگشت سند را بنویسید (حداقل ۵ نویسه):")
        if reason is None:
            return
        try:
            reversal = self.services.inventory.reverse_document(self.ctx, document.id,
                                                               reason)
        except AppError as error:
            show_error(self, "برگشت سند", error)
            return
        self.refresh()
        self.notify(f"سند برگشت {reversal.number} ثبت شد.")

    def _open_cardex(self) -> None:
        index = self.balance_table.selected_row_index()
        if index is None:
            return
        row = self.balance_table.model.row_at(index)
        CardexDialog(self.services, self.ctx, product_id=row.product_id,
                     warehouse_id=row.warehouse_id, parent=self).exec()

    def _create_count(self) -> None:
        warehouse_id = self.count_warehouse.value()
        if warehouse_id is None:
            show_info(self, "انبارگردانی", "انبار را انتخاب کنید.")
            return
        try:
            sheet_id = self.services.inventory.create_count_sheet(
                self.ctx, warehouse_id=warehouse_id)
        except AppError as error:
            show_error(self, "ایجاد برگهٔ انبارگردانی", error)
            return
        self.refresh()
        StockCountDialog(self.services, self.ctx, sheet_id, parent=self).exec()
        self.refresh()

    def _open_count(self) -> None:
        index = self.count_table.selected_row_index()
        if index is None:
            show_info(self, "انبارگردانی", "ابتدا یک برگه را انتخاب کنید.")
            return
        row = self.count_table.model.row_at(index)
        StockCountDialog(self.services, self.ctx, row["id"], parent=self).exec()
        self.refresh()
