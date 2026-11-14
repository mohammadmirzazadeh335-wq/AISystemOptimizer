"""Purchase requests/orders and sales orders with their status history."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.services.order_service import OrderInput, OrderLineInput, OrderRow
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.table_specs import AMOUNT, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

ORDER_COLUMNS = (
    ColumnSpec("number", "شماره", TEXT, 130, "center"),
    ColumnSpec("doc_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 130),
    ColumnSpec("party_name", "شخص", TEXT, None),
    ColumnSpec("warehouse_title", "انبار", TEXT, 130),
    ColumnSpec("total", "مبلغ", AMOUNT, 130),
    ColumnSpec("status_fa", "وضعیت", TEXT, 110, "center"),
)


class OrderDialog(QDialog):
    def __init__(self, services, ctx, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.kind = kind
        self.saved: OrderRow | None = None
        self.setWindowTitle(CC.ORDER_TITLES_FA.get(kind, kind))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(880, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.party_combo = PickCombo()
        role = "supplier" if kind != CC.ORDER_SALES else "customer"
        self.party_combo.load(services.persons.choices(ctx, role=role))
        top.addWidget(form_row("شخص", self.party_combo), 2)
        self.warehouse_combo = PickCombo()
        self.warehouse_combo.load(services.inventory.warehouse_choices(ctx))
        top.addWidget(form_row("انبار", self.warehouse_combo), 1)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        top.addWidget(form_row("تاریخ", self.date_edit), 1)
        layout.addLayout(top)

        self.lines = QTableWidget(0, 3)
        self.lines.setHorizontalHeaderLabels(["کالا", "مقدار", "بهای واحد"])
        self.lines.verticalHeader().setVisible(False)
        self.lines.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.lines.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.lines, 1)
        add = QPushButton("افزودن ردیف")
        add.clicked.connect(self._add_row)
        layout.addWidget(add, alignment=Qt.AlignmentFlag.AlignRight)

        self.notes_edit = QLineEdit()
        layout.addWidget(form_row("توضیحات", self.notes_edit))

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._products = services.catalogue.product_choices(ctx, active_only=True, limit=500)
        self._add_row()

    def _add_row(self) -> None:
        row = self.lines.rowCount()
        self.lines.insertRow(row)
        combo = PickCombo()
        combo.load(self._products)
        self.lines.setCellWidget(row, 0, combo)
        self.lines.setItem(row, 1, QTableWidgetItem("1"))
        self.lines.setItem(row, 2, QTableWidgetItem("0"))

    def _save(self) -> None:
        lines = []
        for row in range(self.lines.rowCount()):
            combo = self.lines.cellWidget(row, 0)
            product_id = combo.value() if combo else None
            if product_id is None:
                continue
            lines.append(OrderLineInput(
                product_id=product_id,
                quantity=(self.lines.item(row, 1).text()
                          if self.lines.item(row, 1) else "0") or 0,
                unit_price=(self.lines.item(row, 2).text()
                            if self.lines.item(row, 2) else 0) or 0))
        if not lines:
            show_info(self, "ثبت سفارش", "حداقل یک ردیف وارد کنید.")
            return
        try:
            self.saved = self.services.orders.create(self.ctx, OrderInput(
                kind=self.kind, doc_date=self.date_edit.date() or _dt.date.today(),
                party_detail_id=self.party_combo.value(),
                warehouse_id=self.warehouse_combo.value(),
                lines=tuple(lines), notes=self.notes_edit.text().strip()))
        except AppError as error:
            show_error(self, "ثبت سفارش", error)
            return
        self.accept()


class OrderHistoryDialog(QDialog):
    def __init__(self, order: OrderRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"تاریخچهٔ وضعیت — {order.number}")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        head = QLabel(f"{order.kind_fa} {order.number} — {order.party_name}")
        head.setObjectName("SectionTitle")
        layout.addWidget(head)
        history = DataTable((
            ColumnSpec("from_status_fa", "از وضعیت", TEXT, 140),
            ColumnSpec("to_status_fa", "به وضعیت", TEXT, 140),
            ColumnSpec("changed_at", "زمان", TEXT, 180, "center"),
            ColumnSpec("note", "توضیح", TEXT, None),
        ))
        history.set_rows(order.history)
        layout.addWidget(history, 1)
        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignLeft)


class OrdersPage(PageBase):
    def __init__(self, *args, family: str = "purchase", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.family = family
        purchase = family == "purchase"
        self.header = PageHeader(
            "درخواست و سفارش خرید" if purchase else "سفارش فروش",
            "گردش وضعیت از پیش‌نویس تا تکمیل، با تاریخچهٔ کامل تغییر وضعیت")
        self.header.add_action("درخواست خرید" if purchase else "سفارش فروش",
                               slot=lambda: self._new(
                                   CC.ORDER_PURCHASE_REQUEST if purchase
                                   else CC.ORDER_SALES))
        if purchase:
            self.header.add_action("سفارش خرید", variant="secondary",
                                   slot=lambda: self._new(CC.ORDER_PURCHASE))
        self.header.add_action("تغییر وضعیت", variant="secondary", slot=self._advance)
        self.header.add_action("تاریخچه", variant="ghost", slot=self._history)
        self.root.addWidget(self.header)

        filters = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.search = SearchInput("جست‌وجوی شماره سفارش…")
        self.search.searchChanged.connect(self.refresh)
        row.addWidget(self.search, 2)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for status in CC.ORDER_STATUSES:
            self.status_combo.addItem(CC.ORDER_STATUS_TITLES_FA[status], status)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.status_combo, 1)
        filters.add_layout(row)
        self.root.addWidget(filters)

        self.table = DataTable(ORDER_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._advance())
        card = CardPanel("فهرست سفارش‌ها")
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def _kinds(self) -> set[str]:
        return ({CC.ORDER_PURCHASE_REQUEST, CC.ORDER_PURCHASE} if self.family == "purchase"
                else {CC.ORDER_SALES})

    def refresh(self) -> None:
        try:
            rows = self.services.orders.list(
                self.ctx, status=self.status_combo.currentData(),
                search=self.search.text().strip())
        except AppError as error:
            show_error(self, "فهرست سفارش‌ها", error)
            return
        self.table.set_rows([row for row in rows if row.kind in self._kinds()])

    def _selected(self) -> OrderRow | None:
        index = self.table.selected_row_index()
        if index is None:
            show_info(self, "انتخاب سفارش", "ابتدا یک سفارش را انتخاب کنید.")
            return None
        return self.table.model.row_at(index)

    def _new(self, kind: str) -> None:
        dialog = OrderDialog(self.services, self.ctx, kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"سفارش {dialog.saved.number} ثبت شد.")

    def _advance(self) -> None:
        order = self._selected()
        if order is None:
            return
        allowed = CC.ORDER_ALLOWED_TRANSITIONS.get(order.status, ())
        if not allowed:
            show_info(self, "تغییر وضعیت",
                      f"سفارش در وضعیت «{order.status_fa}» قابل تغییر نیست.")
            return
        dialog = QDialog(self)
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        dialog.setWindowTitle("تغییر وضعیت سفارش")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"سفارش {order.number} — وضعیت فعلی: {order.status_fa}"))
        status_combo = QComboBox()
        for status in allowed:
            status_combo.addItem(CC.ORDER_STATUS_TITLES_FA[status], status)
        layout.addWidget(form_row("وضعیت جدید", status_combo))
        note_edit = QLineEdit()
        layout.addWidget(form_row("توضیح", note_edit))
        buttons = QDialogButtonBox()
        ok = buttons.addButton("ثبت", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            updated = self.services.orders.transition(
                self.ctx, order.id, str(status_combo.currentData()),
                note_edit.text().strip())
        except AppError as error:
            show_error(self, "تغییر وضعیت سفارش", error)
            return
        self.refresh()
        self.notify(f"وضعیت سفارش {order.number}: {updated.status_fa}")

    def _history(self) -> None:
        order = self._selected()
        if order is None:
            return
        try:
            fresh = self.services.orders.get(self.ctx, order.id)
        except AppError as error:
            show_error(self, "تاریخچه", error)
            return
        OrderHistoryDialog(fresh, parent=self).exec()
