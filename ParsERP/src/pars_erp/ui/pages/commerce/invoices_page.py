"""Purchase and sale invoices: fast entry, posting, returns, print and export."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

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
from pars_erp.services.commerce_common import ZERO
from pars_erp.services.invoice_service import (
    InvoiceFilter,
    InvoiceInput,
    InvoiceLineInput,
    InvoiceRow,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm
from pars_erp.ui.table_specs import AMOUNT, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

INVOICE_COLUMNS = (
    ColumnSpec("number", "شماره", TEXT, 130, "center"),
    ColumnSpec("invoice_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 120),
    ColumnSpec("party_name", "شخص", TEXT, None),
    ColumnSpec("subtotal", "جمع ردیف‌ها", AMOUNT, 120),
    ColumnSpec("total_discount", "تخفیف", AMOUNT, 100,
               getter=lambda row: row.total_discount),
    ColumnSpec("tax_total", "مالیات", AMOUNT, 100),
    ColumnSpec("net_total", "مبلغ نهایی", AMOUNT, 130),
    ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
)

LINE_COLUMNS = (
    ColumnSpec("line_no", "ردیف", TEXT, 50, "center"),
    ColumnSpec("product_name", "کالا", TEXT, None),
    ColumnSpec("quantity", "مقدار", TEXT, 80, "center"),
    ColumnSpec("unit_price", "بهای واحد", AMOUNT, 110),
    ColumnSpec("discount", "تخفیف", AMOUNT, 100),
    ColumnSpec("tax_percent", "مالیات %", TEXT, 70, "center"),
    ColumnSpec("line_total", "مبلغ ردیف", AMOUNT, 120),
)


class InvoiceEditor(QDialog):
    """Line-by-line invoice entry with live totals."""

    def __init__(self, services, ctx, kind: str, *,
                 invoice: InvoiceRow | None = None,
                 prefill: dict | None = None,
                 source: InvoiceRow | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.kind = kind
        self.invoice = invoice
        self.source = source
        self.saved: InvoiceRow | None = None
        self.setWindowTitle(CC.INVOICE_TITLES_FA.get(kind, kind))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1000, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.party_combo = PickCombo()
        role = "supplier" if kind in (CC.INVOICE_PURCHASE,
                                      CC.INVOICE_PURCHASE_RETURN) else "customer"
        self.party_combo.load(services.persons.choices(ctx, role=role))
        top.addWidget(form_row("شخص *", self.party_combo), 2)
        self.warehouse_combo = PickCombo()
        warehouses = services.inventory.warehouse_choices(ctx)
        self.warehouse_combo.load(warehouses)
        if warehouses:
            self.warehouse_combo.set_value(warehouses[0][0])  # primary first
        top.addWidget(form_row("انبار", self.warehouse_combo), 1)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        top.addWidget(form_row("تاریخ *", self.date_edit), 1)
        self.reference_edit = QLineEdit()
        top.addWidget(form_row("شمارهٔ مرجع", self.reference_edit), 1)
        root.addLayout(top)

        self.number_hint = QLabel("")
        self.number_hint.setObjectName("HintText")
        root.addWidget(self.number_hint)

        self.lines = QTableWidget(0, 6)
        self.lines.setHorizontalHeaderLabels(
            ["کالا / خدمت", "مقدار", "واحد", "بهای واحد", "تخفیف ردیف", "مالیات %"])
        self.lines.verticalHeader().setVisible(False)
        self.lines.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.lines.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lines.itemChanged.connect(lambda _item: self._recalculate())
        root.addWidget(self.lines, 1)

        row_buttons = QHBoxLayout()
        add = QPushButton("افزودن ردیف")
        add.clicked.connect(self._add_row)
        row_buttons.addWidget(add)
        remove = QPushButton("حذف ردیف")
        remove.setProperty("variant", "ghost")
        remove.clicked.connect(self._remove_row)
        row_buttons.addWidget(remove)
        self.barcode_edit = QLineEdit()
        self.barcode_edit.setPlaceholderText("بارکد را اسکن کنید و Enter بزنید")
        self.barcode_edit.returnPressed.connect(self._scan_barcode)
        row_buttons.addWidget(self.barcode_edit, 2)
        root.addLayout(row_buttons)

        totals_row = QHBoxLayout()
        self.discount_edit = MoneyEdit()
        self.discount_edit.editingFinished.connect(self._recalculate)
        totals_row.addWidget(form_row("تخفیف کل فاکتور", self.discount_edit))
        self.charges_edit = MoneyEdit()
        self.charges_edit.editingFinished.connect(self._recalculate)
        totals_row.addWidget(form_row("هزینه‌های جانبی (حمل/بسته‌بندی)", self.charges_edit))
        totals_row.addStretch(1)
        root.addLayout(totals_row)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("SectionTitle")
        root.addWidget(self.totals_label)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("توضیحات فاکتور")
        root.addWidget(form_row("توضیحات", self.notes_edit))

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیرهٔ پیش‌نویس",
                                 QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._products = services.catalogue.product_choices(ctx, active_only=True, limit=500)
        self._recalc_timer_rows: list[dict] = []
        self._load_invoice(invoice, prefill, source)
        if invoice is None:
            try:
                self.number_hint.setText(
                    "شمارهٔ پیشنهادی: " + services.invoices.next_number_preview(ctx, kind))
            except AppError:
                pass

    # ------------------------------------------------------------------ lines
    def _load_invoice(self, invoice, prefill, source) -> None:
        if invoice is not None:
            self.party_combo.set_value(invoice.party_id)
            self.warehouse_combo.set_value(invoice.warehouse_id)
            self.date_edit.set_date(invoice.invoice_date)
            self.reference_edit.setText(invoice.reference_no)
            self.notes_edit.setText(invoice.notes)
            self.discount_edit.set_amount(invoice.invoice_discount)
            self.charges_edit.set_amount(invoice.charge_total)
            for line in invoice.lines:
                self._add_row(product_id=line.product_id, quantity=line.quantity,
                              price=line.unit_price, discount=line.discount,
                              tax=line.tax_percent)
        elif prefill:
            self.party_combo.set_value(prefill.get("party_detail_id"))
            self.warehouse_combo.set_value(prefill.get("warehouse_id"))
            self.reference_edit.setText(prefill.get("reference_no", ""))
            for line in prefill.get("lines", []):
                self._add_row(product_id=line["product_id"],
                              quantity=line["quantity"],
                              price=line.get("unit_price", 0))
        elif source is not None:
            self.party_combo.set_value(source.party_id)
            self.warehouse_combo.set_value(source.warehouse_id)
            for line in source.lines:
                self._add_row(product_id=line.product_id, quantity=line.quantity,
                              price=line.unit_price, discount=line.discount,
                              tax=line.tax_percent)
        else:
            self._add_row()
        self._recalculate()

    def _add_row(self, *, product_id=None, quantity=1, price=0, discount=0,
                 tax=0) -> None:
        row = self.lines.rowCount()
        self.lines.insertRow(row)
        combo = PickCombo()
        combo.load(self._products)
        combo.set_value(product_id)
        combo.currentIndexChanged.connect(lambda _i, r=row: self._product_changed(r))
        self.lines.setCellWidget(row, 0, combo)
        self.lines.setItem(row, 1, QTableWidgetItem(str(quantity)))
        unit_combo = PickCombo()
        unit_combo.load(self.services.catalogue.unit_choices(self.ctx),
                        placeholder="— واحد —")
        self.lines.setCellWidget(row, 2, unit_combo)
        self.lines.setItem(row, 3, QTableWidgetItem(str(price)))
        self.lines.setItem(row, 4, QTableWidgetItem(str(discount)))
        self.lines.setItem(row, 5, QTableWidgetItem(str(tax)))
        if product_id:
            self._set_unit_for_row(row, product_id)

    def _set_unit_for_row(self, row: int, product_id: int) -> None:
        try:
            product = self.services.catalogue.get(self.ctx, product_id)
        except AppError:
            return
        combo = self.lines.cellWidget(row, 2)
        if combo is not None:
            combo.set_value(product.unit_id)
        if not (self.lines.item(row, 3) and self.lines.item(row, 3).text() not in ("", "0")):
            price = (product.purchase_price if self.kind in (CC.INVOICE_PURCHASE,
                                                             CC.INVOICE_PURCHASE_RETURN)
                     else product.sale_price)
            self.lines.setItem(row, 3, QTableWidgetItem(str(price)))

    def _product_changed(self, row: int) -> None:
        combo = self.lines.cellWidget(row, 0)
        if combo is None or combo.value() is None:
            return
        self._set_unit_for_row(row, combo.value())
        self._recalculate()

    def _remove_row(self) -> None:
        row = self.lines.currentRow()
        if row >= 0 and self.lines.rowCount() > 1:
            self.lines.removeRow(row)
            self._recalculate()

    def _scan_barcode(self) -> None:
        """Keyboard-wedge scanners type the code and press Enter."""
        code = self.barcode_edit.text().strip()
        if not code:
            return
        try:
            product = self.services.catalogue.find_by_barcode(self.ctx, code)
        except AppError as error:
            show_error(self, "بارکد", error)
            self.barcode_edit.selectAll()
            return
        for row in range(self.lines.rowCount()):
            combo = self.lines.cellWidget(row, 0)
            if combo is not None and combo.value() == product.id:
                item = self.lines.item(row, 1)
                current = Decimal(item.text() or "0") if item else ZERO
                self.lines.setItem(row, 1, QTableWidgetItem(str(current + 1)))
                self._recalculate()
                self.barcode_edit.clear()
                return
        self._add_row(product_id=product.id)
        self._recalculate()
        self.barcode_edit.clear()

    def _postal_date(self) -> _dt.date:
        return self.date_edit.date() or _dt.date.today()

    def _lines_data(self) -> tuple[InvoiceLineInput, ...]:
        result = []
        for row in range(self.lines.rowCount()):
            combo = self.lines.cellWidget(row, 0)
            product_id = combo.value() if combo else None
            if product_id is None:
                continue
            quantity_item = self.lines.item(row, 1)
            if quantity_item is None or not quantity_item.text().strip():
                continue
            unit_combo = self.lines.cellWidget(row, 2)
            result.append(InvoiceLineInput(
                product_id=product_id,
                quantity=quantity_item.text().strip(),
                unit_price=(self.lines.item(row, 3).text()
                            if self.lines.item(row, 3) else 0) or 0,
                discount=(self.lines.item(row, 4).text()
                          if self.lines.item(row, 4) else 0) or 0,
                tax_percent=(self.lines.item(row, 5).text()
                             if self.lines.item(row, 5) else 0) or 0,
                unit_id=unit_combo.value() if unit_combo else None,
            ))
        return tuple(result)

    def _recalculate(self) -> None:
        # reuse the service's own allocation logic so the preview can never
        # disagree with what will be stored
        lines = []
        for entry in self._lines_data():
            try:
                quantity = Decimal(str(entry.quantity))
                price = Decimal(str(entry.unit_price or 0))
                discount = Decimal(str(entry.discount or 0))
                tax = Decimal(str(entry.tax_percent or 0))
            except Exception:  # pragma: no cover - typing in progress
                continue
            lines.append({"gross": quantity * price, "discount": discount,
                          "tax_percent": tax})
        if not lines:
            self.totals_label.setText("ردیفی وارد نشده است.")
            return
        try:
            totals = self.services.invoices.preview_totals(
                lines, self.discount_edit.amount, self.charges_edit.amount)
        except AppError as error:
            self.totals_label.setText(str(error))
            return
        self.totals_label.setText(
            f"جمع ردیف‌ها: {totals['subtotal']:,}   |   "
            f"تخفیف ردیف‌ها: {totals['line_discount']:,}   |   "
            f"تخفیف کل: {totals['invoice_discount']:,}   |   "
            f"مالیات: {totals['tax_total']:,}   |   "
            f"هزینه‌ها: {totals['charge_total']:,}   |   "
            f"مبلغ نهایی: {totals['net_total']:,}")

    # ------------------------------------------------------------------- save
    def _save(self) -> None:
        if self.party_combo.value() is None:
            show_info(self, "ثبت فاکتور", "شخص (مشتری/تأمین‌کننده) را انتخاب کنید.")
            return
        lines = self._lines_data()
        if not lines:
            show_info(self, "ثبت فاکتور", "حداقل یک ردیف کامل وارد کنید.")
            return
        data = InvoiceInput(
            kind=self.kind,
            invoice_date=self._postal_date(),
            party_detail_id=self.party_combo.value(),
            warehouse_id=self.warehouse_combo.value(),
            lines=lines,
            invoice_discount=self.discount_edit.amount,
            charges=self.charges_edit.amount,
            reference_no=self.reference_edit.text().strip(),
            notes=self.notes_edit.text().strip(),
            source_invoice_id=self.source.id if self.source is not None else None,
        )
        try:
            if self.invoice is None:
                self.saved = self.services.invoices.create(self.ctx, data)
            else:
                self.saved = self.services.invoices.update(self.ctx, self.invoice.id, data)
        except AppError as error:
            show_error(self, "ثبت فاکتور", error)
            return
        self.accept()


class InvoicePreviewDialog(QDialog):
    """Screen preview + print + PDF/Excel export of one invoice."""

    def __init__(self, services, ctx, invoice: InvoiceRow, formatter,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.invoice = invoice
        self.formatter = formatter
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"پیش‌نمایش {invoice.kind_fa} {invoice.number}")
        self.resize(940, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        head = QLabel(f"{invoice.kind_fa} شماره {invoice.number} — {invoice.party_name}")
        head.setObjectName("SectionTitle")
        layout.addWidget(head)
        meta = QLabel(
            f"تاریخ: {formatter.date(invoice.invoice_date)}   |   "
            f"انبار: {invoice.warehouse_title or '—'}   |   "
            f"وضعیت: {invoice.status_fa}")
        meta.setObjectName("HintText")
        layout.addWidget(meta)

        table = DataTable(LINE_COLUMNS, formatter=formatter)
        table.set_rows(invoice.lines)
        layout.addWidget(table, 1)

        totals = QLabel(
            f"جمع ردیف‌ها: {invoice.subtotal:,}   |   "
            f"تخفیف: {invoice.total_discount:,}   |   "
            f"مالیات: {invoice.tax_total:,}   |   "
            f"هزینه‌ها: {invoice.charge_total:,}   |   "
            f"مبلغ نهایی: {invoice.net_total:,}")
        totals.setObjectName("SectionTitle")
        layout.addWidget(totals)
        links = QLabel(
            f"سند انبار: {invoice.stock_document_id or '—'}   |   "
            f"سند حسابداری: {invoice.journal_id or '—'}")
        links.setObjectName("HintText")
        layout.addWidget(links)

        buttons = QHBoxLayout()
        print_button = QPushButton("چاپ / PDF")
        print_button.setProperty("variant", "primary")
        print_button.clicked.connect(self._print)
        buttons.addWidget(print_button)
        excel = QPushButton("خروجی Excel")
        excel.clicked.connect(self._excel)
        buttons.addWidget(excel)
        buttons.addStretch(1)
        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _report_table(self):
        from pars_erp.services.report_render_service import (
            KIND_AMOUNT, KIND_NUMBER, KIND_TEXT, ReportColumn, ReportTable,
        )

        columns = (
            ReportColumn("line_no", "ردیف", KIND_NUMBER, 0.5),
            ReportColumn("product_name", "کالا / خدمت", KIND_TEXT, 2.6),
            ReportColumn("quantity", "مقدار", KIND_NUMBER, 0.8),
            ReportColumn("unit_price", "بهای واحد", KIND_AMOUNT, 1.1),
            ReportColumn("discount", "تخفیف", KIND_AMOUNT, 0.9),
            ReportColumn("tax_amount", "مالیات", KIND_AMOUNT, 0.9),
            ReportColumn("line_total", "مبلغ ردیف", KIND_AMOUNT, 1.2),
        )
        rows = tuple((line.line_no, line.description or line.product_name, line.quantity,
                      line.unit_price, line.discount, line.tax_amount, line.line_total)
                     for line in self.invoice.lines)
        snapshot = self.services.settings.snapshot()
        return ReportTable(
            title=f"{self.invoice.kind_fa} {self.invoice.number}",
            columns=columns, rows=rows,
            company=snapshot.company_name,
            currency_code=snapshot.currency_code,
            subtitle=f"{self.invoice.party_name} — {self.invoice.warehouse_title}",
            meta=(f"تاریخ: {self.formatter.date(self.invoice.invoice_date)}",
                  f"وضعیت: {self.invoice.status_fa}",
                  f"جمع ردیف‌ها: {self.invoice.subtotal:,}",
                  f"تخفیف: {self.invoice.total_discount:,}",
                  f"مالیات: {self.invoice.tax_total:,}",
                  f"مبلغ نهایی: {self.invoice.net_total:,}"),
            notes=tuple(filter(None, (self.invoice.notes,))))

    def _renderer(self):
        from pars_erp.services.report_render_service import ReportRenderer

        snapshot = self.services.settings.snapshot()
        return ReportRenderer(app_name=snapshot.app_name,
                              persian_digits=snapshot.persian_digits)

    def _print(self) -> None:
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        ReportPreviewDialog(self._report_table(), self._renderer(), parent=self).exec()

    def _excel(self) -> None:
        path = self.services.paths.exports_dir / f"{self.invoice.number}.xlsx"
        try:
            outcome = self._renderer().to_excel(self._report_table(), path)
        except AppError as error:
            show_error(self, "خروجی Excel", error)
            return
        show_info(self, "خروجی Excel", outcome.message_fa, tone="success")


class InvoicesPage(PageBase):
    """One page used for both purchase and sale families (``family`` argument)."""

    def __init__(self, *args, family: str = "purchase", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.family = family
        purchase = family == "purchase"
        title = "فاکتورهای خرید" if purchase else "فاکتورهای فروش"
        subtitle = ("ثبت، تأیید و قطعی‌سازی فاکتور خرید، برگشت از خرید و گزارش‌ها"
                    if purchase else
                    "پیش‌فاکتور/فاکتور فروش، برگشت از فروش و گزارش‌ها")
        self.header = PageHeader(title, subtitle)
        self.header.add_action(
            "فاکتور خرید" if purchase else "فاکتور فروش", slot=self._new)
        self.header.add_action("برگشت", variant="secondary", slot=self._return)
        self.header.add_action("تأیید", variant="secondary", slot=self._approve)
        self.header.add_action("ثبت نهایی", variant="secondary", slot=self._post)
        self.header.add_action("ابطال", variant="ghost", slot=self._void)
        self.header.add_action("پیش‌نمایش/چاپ", variant="ghost", slot=self._preview)
        self.root.addWidget(self.header)

        filters = CardPanel("جست‌وجو و فیلتر")
        row = QHBoxLayout()
        self.search = SearchInput("جست‌وجوی شماره یا مرجع…")
        self.search.searchChanged.connect(self.refresh)
        row.addWidget(self.search, 2)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("همهٔ انواع", None)
        kinds = (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN) if purchase else (
            CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN)
        for kind in kinds:
            self.kind_combo.addItem(CC.INVOICE_TITLES_FA[kind], kind)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.kind_combo, 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همهٔ وضعیت‌ها", None)
        for status in CC.DOC_STATUSES:
            self.status_combo.addItem(CC.DOC_STATUS_TITLES_FA[status], status)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.status_combo, 1)
        filters.add_layout(row)
        self.root.addWidget(filters)

        self.table = DataTable(INVOICE_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._preview())
        card = CardPanel("فهرست فاکتورها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)
        self.refresh()

    def _rows(self) -> list[InvoiceRow]:
        kinds = {CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN} if self.family == "purchase" \
            else {CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN}
        kind = self.kind_combo.currentData()
        filters = InvoiceFilter(search=self.search.text().strip(),
                                status=self.status_combo.currentData(),
                                kind=kind if kind else None, only_returns=False)
        rows = self.services.invoices.list(self.ctx, filters)
        return [row for row in rows if row.kind in kinds]

    def refresh(self) -> None:
        try:
            rows = self._rows()
        except AppError as error:
            show_error(self, "فهرست فاکتورها", error)
            return
        self.table.set_rows(rows)
        total = sum((row.net_total for row in rows if row.status == CC.STATUS_POSTED),
                    ZERO)
        self.summary.setText(f"{len(rows):,} فاکتور | جمع مبالغ ثبت‌شده: {total:,}")

    def _selected(self) -> InvoiceRow | None:
        index = self.table.selected_row_index()
        if index is None:
            show_info(self, "انتخاب فاکتور", "ابتدا یک فاکتور را از فهرست انتخاب کنید.")
            return None
        return self.table.model.row_at(index)

    def _new(self) -> None:
        kind = CC.INVOICE_PURCHASE if self.family == "purchase" else CC.INVOICE_SALE
        dialog = InvoiceEditor(self.services, self.ctx, kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"فاکتور {dialog.saved.number} ذخیره شد.")

    def _return(self) -> None:
        invoice = self._selected()
        if invoice is None:
            return
        if invoice.is_posted is False:
            show_info(self, "برگشت", "برای ثبت برگشت، فاکتور مرجع باید ثبت نهایی شده باشد.")
            return
        kind = (CC.INVOICE_PURCHASE_RETURN if invoice.kind == CC.INVOICE_PURCHASE
                else CC.INVOICE_SALE_RETURN)
        dialog = InvoiceEditor(self.services, self.ctx, kind, source=invoice, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"برگشت {dialog.saved.number} ثبت شد.")

    def _approve(self) -> None:
        invoice = self._selected()
        if invoice is None:
            return
        try:
            self.services.invoices.approve(self.ctx, invoice.id)
        except AppError as error:
            show_error(self, "تأیید فاکتور", error)
            return
        self.refresh()
        self.notify(f"فاکتور {invoice.number} تأیید شد.")

    def _post(self) -> None:
        invoice = self._selected()
        if invoice is None:
            return
        if not confirm(self, "ثبت نهایی فاکتور",
                       f"فاکتور {invoice.number} ثبت نهایی شود؟ با این کار سند انبار و "
                       "سند حسابداری ایجاد می‌شود و فاکتور دیگر قابل ویرایش نیست."):
            return
        try:
            result = self.services.invoices.post(self.ctx, invoice.id)
        except AppError as error:
            show_error(self, "ثبت نهایی فاکتور", error)
            return
        self.refresh()
        self.notify(f"فاکتور {result.invoice.number} ثبت نهایی شد؛ سند حسابداری "
                    f"شماره {result.journal_id} و سند انبار {result.stock_document_id}.")

    def _void(self) -> None:
        invoice = self._selected()
        if invoice is None:
            return
        reason = ask_reason(self, "ابطال فاکتور",
                            "دلیل ابطال را بنویسید (حداقل ۵ نویسه):")
        if reason is None:
            return
        try:
            self.services.invoices.void(self.ctx, invoice.id, reason)
        except AppError as error:
            show_error(self, "ابطال فاکتور", error)
            return
        self.refresh()
        self.notify(f"فاکتور {invoice.number} باطل و آثار آن برگشت داده شد.")

    def _preview(self) -> None:
        invoice = self._selected()
        if invoice is None:
            return
        try:
            fresh = self.services.invoices.get(self.ctx, invoice.id)
        except AppError as error:
            show_error(self, "پیش‌نمایش", error)
            return
        InvoicePreviewDialog(self.services, self.ctx, fresh, self.formatter,
                             parent=self).exec()
