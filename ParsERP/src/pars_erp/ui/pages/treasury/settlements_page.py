"""Settlement: per-invoice balance, full/partial settlement, open documents."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from pars_erp.core.errors import AppError
from pars_erp.services.voucher_service import OpenInvoiceRow
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    build_table,
    export_excel,
    form_row,
    show_preview,
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

SETTLEMENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره فاکتور", TEXT, 140, "center"),
    ColumnSpec("invoice_date", "تاریخ", DATE, 96, "center"),
    ColumnSpec("party_name", "شخص", TEXT, None),
    ColumnSpec("net_total", "مبلغ فاکتور", AMOUNT, 130),
    ColumnSpec("settled", "تسویه‌شده", AMOUNT, 130),
    ColumnSpec("returned", "برگشتی", AMOUNT, 110),
    ColumnSpec("open_amount", "مانده", AMOUNT, 130),
    ColumnSpec("state", "وضعیت", BADGE, 110, "center",
               getter=lambda row: "pending" if row.is_partial else "unmatched"),
)


class SettlementsPage(PageBase):
    """Open sale/purchase invoices with the amount that each still owes."""

    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows: list[OpenInvoiceRow] = []
        self.header = PageHeader(
            "تسویه‌حساب‌ها",
            "ماندهٔ هر فاکتور، تسویهٔ کامل یا جزئی و نمایش فاکتورهای تسویه‌نشده/جزئی")
        self.header.add_action("دریافت از مشتری", slot=lambda: self._new("receipt"))
        self.header.add_action("پرداخت به تأمین‌کننده", variant="secondary",
                               slot=lambda: self._new("payment"))
        self.header.add_action("چاپ / PDF", variant="secondary", slot=self._print)
        self.header.add_action("Excel", variant="secondary", slot=self._excel)
        self.root.addWidget(self.header)
        bar = CardPanel("فیلتر")
        row = QHBoxLayout()
        self.search_input = SearchInput("جست‌وجوی شماره فاکتور یا شخص…")
        self.search_input.searchChanged.connect(lambda _text: self.refresh())
        row.addWidget(self.search_input, 2)
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("مطالبات (فروش)", "receipt")
        self.direction_combo.addItem("بدهی‌ها (خرید)", "payment")
        self.direction_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(form_row("نوع", self.direction_combo), 1)
        bar.add_layout(row)
        self.root.addWidget(bar)
        self.table = DataTable(SETTLEMENT_COLUMNS, formatter=formatter)
        card = CardPanel("فاکتورهای باز")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def refresh(self) -> None:
        direction = str(self.direction_combo.currentData())
        try:
            rows = self.services.vouchers.open_invoices(self.ctx, direction=direction)
        except AppError as error:
            show_error(self, "تسویه‌حساب‌ها", error)
            return
        needle = self.search_input.text().strip()
        if needle:
            rows = [row for row in rows
                    if needle in row.number or needle in row.party_name]
        self.rows = rows
        self.table.set_rows(rows)
        total = sum((row.open_amount for row in rows), Decimal("0"))
        partial = sum(1 for row in rows if row.is_partial)
        self.summary.setText(f"{len(rows):,} فاکتور باز — {partial:,} فاکتور جزئی — "
                             f"جمع مانده {total:,}")

    def _new(self, family: str) -> None:
        from pars_erp.ui.pages.treasury.vouchers_page import VoucherDialog

        index = self.table.currentIndex()
        party = None
        if index.isValid() and index.row() < len(self.rows):
            party = self.rows[index.row()].party_detail_id
        dialog = VoucherDialog(self.services, self.ctx, family, party_detail_id=party,
                               parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit(f"سند {dialog.saved.number} ثبت شد.")

    def _table(self):
        headers = tuple(column.title_fa for column in SETTLEMENT_COLUMNS[:-1])
        rows = tuple(tuple(column.value_of(row) for column in SETTLEMENT_COLUMNS[:-1])
                     for row in self.rows)
        totals = ("", "", "جمع", "", "", "",
                  sum((row.open_amount for row in self.rows), Decimal("0")))
        return build_table("مانده فاکتورها", headers, rows,
                           meta=f"{len(self.rows):,} فاکتور",
                           company=self.services.settings.snapshot().company_name,
                           totals=totals)

    def _print(self) -> None:
        if not self.rows:
            show_info(self, "چاپ", "فاکتور بازی وجود ندارد.")
            return
        show_preview(self, self.services, self._table())

    def _excel(self) -> None:
        if not self.rows:
            show_info(self, "Excel", "فاکتور بازی وجود ندارد.")
            return
        export_excel(self, self.services, self._table(), prefix="settlements")
