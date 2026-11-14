"""Products and services: list, filters, editor, history, barcode labels."""

from __future__ import annotations

from decimal import Decimal

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.services.catalogue_service import (
    ProductFilter,
    ProductInput,
    ProductRow,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import MoneyEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, confirm
from pars_erp.ui.table_specs import AMOUNT, BADGE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

PRODUCT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 100, "center"),
    ColumnSpec("name_fa", "نام کالا / خدمت", TEXT, None),
    ColumnSpec("kind_fa", "نوع", TEXT, 70, "center"),
    ColumnSpec("category_title", "دسته", TEXT, 120),
    ColumnSpec("brand_title", "برند", TEXT, 100),
    ColumnSpec("unit_title", "واحد", TEXT, 70, "center"),
    ColumnSpec("barcode", "بارکد", TEXT, 130, "center"),
    ColumnSpec("purchase_price", "بهای خرید", AMOUNT, 110),
    ColumnSpec("sale_price", "بهای فروش", AMOUNT, 110),
    ColumnSpec("total_stock", "موجودی", NUMBER, 90, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 120, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)


class ProductDialog(QDialog):
    """Create or edit one product/service."""

    def __init__(self, services, ctx, *, product: ProductRow | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.product = product
        self.saved: ProductRow | None = None
        self.setWindowTitle("ویرایش کالا" if product else "کالا / خدمت جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        tabs = QTabWidget()
        basic = QWidget()
        form = QFormLayout(basic)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.code_edit = QLineEdit()
        form.addRow("کد کالا *", self.code_edit)
        self.name_edit = QLineEdit()
        form.addRow("نام فارسی *", self.name_edit)
        self.name_en_edit = QLineEdit()
        form.addRow("نام انگلیسی", self.name_en_edit)
        self.barcode_edit = QLineEdit()
        self.barcode_edit.setPlaceholderText("اختیاری؛ برای بارکدخوان USB")
        form.addRow("بارکد", self.barcode_edit)

        self.kind_combo = QComboBox()
        for kind in CC.PRODUCT_KINDS:
            self.kind_combo.addItem(CC.PRODUCT_KIND_TITLES_FA[kind], kind)
        form.addRow("نوع", self.kind_combo)

        self.category_combo = PickCombo()
        self.category_combo.load(
            self.services.catalogue.category_choices(self.ctx, active_only=False),
            placeholder="— بدون دسته —")
        form.addRow("دسته‌بندی", self.category_combo)

        self.brand_combo = PickCombo()
        self.brand_combo.load(
            self.services.catalogue.brand_choices(self.ctx, active_only=False),
            placeholder="— بدون برند —")
        form.addRow("برند", self.brand_combo)

        self.unit_combo = PickCombo()
        units = self.services.catalogue.unit_choices(self.ctx, base_only=True)
        self.unit_combo.load(units, placeholder="— واحد پایه —")
        if product is None and units:
            # the common case: a single base unit, so pre-select it for speed
            self.unit_combo.set_value(units[0][0])
        form.addRow("واحد پایه *", self.unit_combo)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(56)
        form.addRow("توضیحات", self.description_edit)

        self.active_check = QCheckBox("کالا فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        tabs.addTab(basic, "مشخصات")

        pricing = QWidget()
        pf = QFormLayout(pricing)
        pf.setSpacing(8)
        pf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.purchase_price = MoneyEdit()
        pf.addRow("بهای خرید", self.purchase_price)
        self.sale_price = MoneyEdit()
        pf.addRow("بهای فروش", self.sale_price)
        self.min_stock = QLineEdit("0")
        pf.addRow("حداقل موجودی", self.min_stock)
        self.max_stock = QLineEdit("0")
        pf.addRow("حداکثر موجودی", self.max_stock)
        self.reorder_point = QLineEdit("0")
        pf.addRow("نقطهٔ سفارش", self.reorder_point)
        note = QLabel("برای خدمات، موجودی و نقطهٔ سفارش معنا ندارد و نادیده گرفته می‌شود.")
        note.setObjectName("HintText")
        note.setWordWrap(True)
        pf.addRow("", note)
        tabs.addTab(pricing, "قیمت و موجودی")
        root.addWidget(tabs)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if product is not None:
            self._load(product)

    def _load(self, product: ProductRow) -> None:
        self.code_edit.setText(product.code)
        self.name_edit.setText(product.name_fa)
        self.name_en_edit.setText(product.name_en)
        self.barcode_edit.setText(product.barcode)
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(product.kind)))
        self.category_combo.set_value(product.category_id)
        self.brand_combo.set_value(product.brand_id)
        self.unit_combo.set_value(product.unit_id)
        self.description_edit.setPlainText(product.description)
        self.active_check.setChecked(product.is_active)
        self.purchase_price.set_amount(product.purchase_price)
        self.sale_price.set_amount(product.sale_price)
        self.min_stock.setText(str(Decimal(product.min_stock).normalize()))
        self.max_stock.setText(str(Decimal(product.max_stock).normalize()))
        self.reorder_point.setText(str(Decimal(product.reorder_point).normalize()))

    def _save(self) -> None:
        if self.unit_combo.value() is None:
            show_info(self, "ثبت کالا",
                      "واحد کالا انتخاب نشده است؛ یا از فهرست انتخاب کنید یا از دکمهٔ "
                      "«واحدها، گروه‌ها و برندها» یک واحد پایه تعریف کنید.")
            return
        data = ProductInput(
            code=self.code_edit.text().strip(),
            name_fa=self.name_edit.text().strip(),
            name_en=self.name_en_edit.text().strip(),
            barcode=self.barcode_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            category_id=self.category_combo.value(),
            brand_id=self.brand_combo.value(),
            unit_id=self.unit_combo.value() or 0,
            description=self.description_edit.toPlainText().strip(),
            min_stock=self.min_stock.text().strip() or 0,
            max_stock=self.max_stock.text().strip() or 0,
            reorder_point=self.reorder_point.text().strip() or 0,
            purchase_price=self.purchase_price.amount,
            sale_price=self.sale_price.amount,
            is_active=self.active_check.isChecked(),
        )
        try:
            if self.product is None:
                self.saved = self.services.catalogue.create(self.ctx, data)
            else:
                self.saved = self.services.catalogue.update(self.ctx, self.product.id, data)
        except AppError as error:
            show_error(self, "ثبت کالا", error)
            return
        self.accept()


class ProductHistoryDialog(QDialog):
    """Purchase/sale history and per-warehouse stock of one product."""

    def __init__(self, services, ctx, product: ProductRow,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"سابقهٔ کالا — {product.name_fa}")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        head = QLabel(f"{product.code} — {product.name_fa} | واحد: {product.unit_title}")
        head.setObjectName("SectionTitle")
        layout.addWidget(head)

        stock_table = DataTable((
            ColumnSpec("warehouse_title", "انبار", TEXT, None),
            ColumnSpec("quantity", "موجودی", NUMBER, 100, "center"),
            ColumnSpec("average_cost", "بهای میانگین", AMOUNT, 130),
            ColumnSpec("value", "ارزش", AMOUNT, 140),
        ))
        stock_table.set_rows(services.catalogue.stock_by_warehouse(ctx, product.id))
        stock_card = CardPanel("موجودی در انبارها")
        stock_card.add(stock_table)
        layout.addWidget(stock_card)

        tabs = QTabWidget()
        purchase = DataTable((
            ColumnSpec("document_no", "شماره سند", TEXT, 130, "center"),
            ColumnSpec("document_date", "تاریخ", TEXT, 100, "center"),
            ColumnSpec("kind_fa", "نوع", TEXT, 110),
            ColumnSpec("party_name", "تأمین‌کننده", TEXT, None),
            ColumnSpec("quantity", "مقدار", NUMBER, 90, "center"),
            ColumnSpec("unit_price", "بهای واحد", AMOUNT, 110),
            ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
        ))
        purchase.set_rows(services.catalogue.purchase_history(ctx, product.id))
        tabs.addTab(purchase, "سابقهٔ خرید")
        sale = DataTable((
            ColumnSpec("document_no", "شماره سند", TEXT, 130, "center"),
            ColumnSpec("document_date", "تاریخ", TEXT, 100, "center"),
            ColumnSpec("kind_fa", "نوع", TEXT, 110),
            ColumnSpec("party_name", "مشتری", TEXT, None),
            ColumnSpec("quantity", "مقدار", NUMBER, 90, "center"),
            ColumnSpec("unit_price", "بهای واحد", AMOUNT, 110),
            ColumnSpec("status_fa", "وضعیت", TEXT, 90, "center"),
        ))
        sale.set_rows(services.catalogue.sale_history(ctx, product.id))
        tabs.addTab(sale, "سابقهٔ فروش")
        layout.addWidget(tabs, 1)

        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignLeft)


class BarcodeLabelDialog(QDialog):
    """Printable label sheet (code + barcode digits) for shelf labelling."""

    def __init__(self, services, ctx, product: ProductRow, count: int = 6,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("برچسب بارکد")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        label = QLabel(f"{product.name_fa} — {product.code}")
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        barcode = product.barcode or self._internal_barcode(product)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        rows = "\n".join([f"{product.code}   |   {product.name_fa}   |   ||{barcode}||"
                          for _ in range(max(1, count))])
        text.setPlainText(rows)
        text.setFixedHeight(220)
        layout.addWidget(text)
        self.path_hint = QLabel(f"مقدار بارکد: {barcode}")
        self.path_hint.setObjectName("HintText")
        layout.addWidget(self.path_hint)
        buttons = QDialogButtonBox()
        print_button = buttons.addButton("چاپ برچسب",
                                         QDialogButtonBox.ButtonRole.ActionRole)
        print_button.setProperty("variant", "primary")
        print_button.clicked.connect(lambda: self._print(text.toPlainText()))
        buttons.addButton("بستن", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _internal_barcode(product: ProductRow) -> str:
        # a deterministic internal code: 20 + zero-padded id, usable until a
        # printer-specific symbology is chosen
        return f"20{product.id:011d}"

    def _print(self, plain_text: str) -> None:
        try:
            from PySide6.QtGui import QTextDocument
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except Exception:  # pragma: no cover
            show_info(self, "چاپ برچسب",
                      "پشتیبانی چاپ در این نسخهٔ Qt موجود نیست؛ از خروجی متنی استفاده کنید.")
            return
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        document = QTextDocument()
        document.setPlainText(plain_text)
        document.print_(printer)


class ProductsPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header = PageHeader("کالاها و خدمات",
                                 "تعریف کالا، خدمت، دسته‌بندی، بارکد و بهای خرید/فروش")
        self.header.add_action("کالای جدید", slot=self._new,
                               tooltip="افزودن کالا یا خدمت تازه (F2)")
        self.header.add_action("ویرایش", variant="secondary", slot=self._edit)
        self.header.add_action("غیرفعال/فعال", variant="secondary", slot=self._toggle)
        self.header.add_action("سابقه و موجودی", variant="secondary", slot=self._history)
        self.header.add_action("برچسب بارکد", variant="ghost", slot=self._label)
        self.header.add_action("واحدها، گروه‌ها و برندها", variant="ghost",
                               slot=self._setup,
                               tooltip="تعریف واحد پایه و واحدهای بزرگ‌تر با ضریب تبدیل")
        self.root.addWidget(self.header)

        filters = CardPanel("جست‌وجو و فیلتر")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = SearchInput("جست‌وجو با نام، کد یا بارکد…")
        self.search.searchChanged.connect(self.refresh)
        row.addWidget(self.search, 2)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("همهٔ انواع", None)
        for kind in CC.PRODUCT_KINDS:
            self.kind_combo.addItem(CC.PRODUCT_KIND_TITLES_FA[kind], kind)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.kind_combo, 1)
        self.category_combo = PickCombo()
        self.category_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.category_combo, 1)
        self.brand_combo = PickCombo()
        self.brand_combo.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.brand_combo, 1)
        self.low_only = QCheckBox("فقط کم‌موجودها")
        self.low_only.stateChanged.connect(self.refresh)
        row.addWidget(self.low_only)
        filters.add_layout(row)
        self.root.addWidget(filters)

        self.table = DataTable(PRODUCT_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._edit())
        card = CardPanel("فهرست کالاها")
        self.count_label = QLabel("")
        self.count_label.setObjectName("HintText")
        card.add_header_widget(self.count_label)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        self._reload_filter_choices()
        self.refresh()

    def _reload_filter_choices(self) -> None:
        self.category_combo.load(
            self.services.catalogue.category_choices(self.ctx, active_only=False))
        self.brand_combo.load(
            self.services.catalogue.brand_choices(self.ctx, active_only=False))

    def refresh(self) -> None:
        try:
            self._reload_filter_choices()
            rows = self.services.catalogue.list_products(self.ctx, ProductFilter(
                search=self.search.text().strip(),
                kind=self.kind_combo.currentData(),
                category_id=self.category_combo.value(),
                brand_id=self.brand_combo.value(),
                low_stock_only=self.low_only.isChecked()))
        except AppError as error:
            show_error(self, "فهرست کالاها", error)
            return
        self.table.set_rows(rows)
        self.count_label.setText(f"{len(rows):,} کالا")

    def _selected(self) -> ProductRow | None:
        index = self.table.selected_row_index()
        if index is None:
            show_info(self, "انتخاب کالا", "ابتدا یک کالا را از فهرست انتخاب کنید.")
            return None
        return self.table.model.row_at(index)

    def _new(self) -> None:
        dialog = ProductDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"کالا «{dialog.saved.name_fa}» ثبت شد.")

    def _setup(self) -> None:
        dialog = CatalogueSetupDialog(self.services, self.ctx, parent=self)
        dialog.exec()
        if dialog.changed:
            self._reload_filter_choices()
            self.refresh()

    def _edit(self) -> None:
        product = self._selected()
        if product is None:
            return
        dialog = ProductDialog(self.services, self.ctx, product=product, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.notify(f"کالا «{dialog.saved.name_fa}» به‌روزرسانی شد.")

    def _toggle(self) -> None:
        product = self._selected()
        if product is None:
            return
        action = "غیرفعال" if product.is_active else "فعال"
        if not confirm(self, f"{action}سازی کالا",
                       f"کالای «{product.name_fa}» {action} شود؟",
                       danger=product.is_active):
            return
        try:
            self.services.catalogue.set_active(self.ctx, product.id, not product.is_active)
        except AppError as error:
            show_error(self, "تغییر وضعیت کالا", error)
            return
        self.refresh()
        self.notify(f"کالا «{product.name_fa}» {action} شد.")

    def _history(self) -> None:
        product = self._selected()
        if product is None:
            return
        ProductHistoryDialog(self.services, self.ctx, product, parent=self).exec()

    def _label(self) -> None:
        product = self._selected()
        if product is None:
            return
        BarcodeLabelDialog(self.services, self.ctx, product, parent=self).exec()


# --------------------------------------------------------- catalogue master data
UNIT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان واحد", TEXT, None),
    ColumnSpec("kind_fa", "نوع", TEXT, 80, "center"),
    ColumnSpec("factor_fa", "ضریب تبدیل", TEXT, 110, "center"),
    ColumnSpec("base_unit_title", "واحد پایه", TEXT, 130),
    ColumnSpec("status_fa", "وضعیت", BADGE, 90, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)

CATEGORY_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان دسته", TEXT, None),
    ColumnSpec("parent_title", "دستهٔ والد", TEXT, 160),
    ColumnSpec("product_count", "تعداد کالا", NUMBER, 90, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 90, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)

BRAND_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "نام برند", TEXT, None),
    ColumnSpec("status_fa", "وضعیت", BADGE, 90, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)


class CatalogueSetupDialog(QDialog):
    """Master data a product needs: units (+ conversions), categories, brands."""

    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.changed = False
        self._unit_editing: int | None = None
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("واحدها، دسته‌بندی‌ها و برندها")
        self.resize(880, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel("کالا بدون واحد قابل ثبت نیست؛ ابتدا واحد پایه (مثل عدد) را تعریف کنید و "
                      "سپس واحدهای بزرگ‌تر (مثل کارتن) را با ضریب تبدیل به آن وصل کنید.")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_units_tab(), "واحدها")
        self.tabs.addTab(self._build_categories_tab(), "دسته‌بندی‌ها")
        self.tabs.addTab(self._build_brands_tab(), "برندها")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("بستن", QDialogButtonBox.ButtonRole.AcceptRole)
        close.setProperty("variant", "primary")
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.refresh()

    # ----------------------------------------------------------------- units
    def _build_units_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        self.unit_table = DataTable(UNIT_COLUMNS)
        self.unit_table.rowActivated.connect(lambda _row: self._load_unit())
        layout.addWidget(self.unit_table, 1)

        form = QHBoxLayout()
        form.setSpacing(8)
        self.unit_code = QLineEdit()
        form.addWidget(form_row("کد *", self.unit_code), 1)
        self.unit_title = QLineEdit()
        form.addWidget(form_row("عنوان *", self.unit_title), 2)
        self.unit_kind = QComboBox()
        for kind, label in CC.UNIT_KINDS:
            self.unit_kind.addItem(label, kind)
        form.addWidget(form_row("نوع", self.unit_kind), 1)
        self.unit_factor = QLineEdit("1")
        form.addWidget(form_row("ضریب تبدیل", self.unit_factor), 1)
        self.unit_base = PickCombo()
        form.addWidget(form_row("واحد پایه", self.unit_base), 2)
        layout.addLayout(form)

        actions = QHBoxLayout()
        save = QPushButton("ثبت واحد")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_unit)
        actions.addWidget(save)
        edit = QPushButton("ویرایش واحد انتخابی")
        edit.clicked.connect(self._load_unit)
        actions.addWidget(edit)
        toggle = QPushButton("فعال/غیرفعال")
        toggle.clicked.connect(self._toggle_unit)
        actions.addWidget(toggle)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def _load_units(self) -> None:
        try:
            rows = self.services.catalogue.list_units(self.ctx, active=None)
        except AppError as error:
            show_error(self, "واحدها", error)
            return
        self.unit_table.set_rows(rows)
        self.unit_base.load([(row.id, f"{row.title_fa} ({row.code})") for row in rows
                             if row.is_base], placeholder="— بدون واحد پایه —")

    def _load_unit(self) -> None:
        index = self.unit_table.selected_row_index()
        if index is None:
            show_info(self, "ویرایش واحد", "ابتدا یک واحد را انتخاب کنید.")
            return
        unit = self.unit_table.model.row_at(index)
        self._unit_editing = unit.id
        self.unit_code.setText(unit.code)
        self.unit_code.setReadOnly(True)
        self.unit_title.setText(unit.title_fa)
        self.unit_kind.setCurrentIndex(max(0, self.unit_kind.findData(unit.kind)))
        self.unit_factor.setText(str(Decimal(unit.factor).normalize()))
        self.unit_base.set_value(unit.base_unit_id)

    def _save_unit(self) -> None:
        code = self.unit_code.text().strip()
        title = self.unit_title.text().strip()
        if not title or (not code and self._unit_editing is None):
            show_info(self, "ثبت واحد", "کد و عنوان واحد را وارد کنید.")
            return
        try:
            if self._unit_editing is None:
                self.services.catalogue.create_unit(
                    self.ctx, code=code, title_fa=title,
                    kind=str(self.unit_kind.currentData()),
                    factor=self.unit_factor.text().strip() or 1,
                    base_unit_id=self.unit_base.value())
            else:
                self.services.catalogue.update_unit(
                    self.ctx, self._unit_editing, title_fa=title,
                    kind=str(self.unit_kind.currentData()),
                    factor=self.unit_factor.text().strip() or 1,
                    base_unit_id=self.unit_base.value())
        except AppError as error:
            show_error(self, "ثبت واحد", error)
            return
        self.changed = True
        self._unit_editing = None
        self.unit_code.setReadOnly(False)
        self.unit_code.clear()
        self.unit_title.clear()
        self.unit_factor.setText("1")
        self.unit_base.set_value(None)
        self._load_units()
        show_info(self, "ثبت واحد", "واحد ذخیره شد.", tone="success")

    def _toggle_unit(self) -> None:
        index = self.unit_table.selected_row_index()
        if index is None:
            show_info(self, "وضعیت واحد", "ابتدا یک واحد را انتخاب کنید.")
            return
        unit = self.unit_table.model.row_at(index)
        try:
            self.services.catalogue.update_unit(self.ctx, unit.id, is_active=not unit.is_active)
        except AppError as error:
            show_error(self, "وضعیت واحد", error)
            return
        self.changed = True
        self._load_units()

    # ------------------------------------------------------------ categories
    def _build_categories_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        self.category_table = DataTable(CATEGORY_COLUMNS)
        layout.addWidget(self.category_table, 1)
        form = QHBoxLayout()
        form.setSpacing(8)
        self.category_code = QLineEdit()
        form.addWidget(form_row("کد *", self.category_code), 1)
        self.category_title = QLineEdit()
        form.addWidget(form_row("عنوان *", self.category_title), 2)
        self.category_parent = PickCombo()
        form.addWidget(form_row("دستهٔ والد", self.category_parent), 2)
        layout.addLayout(form)
        actions = QHBoxLayout()
        save = QPushButton("ثبت دسته")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_category)
        actions.addWidget(save)
        toggle = QPushButton("فعال/غیرفعال")
        toggle.clicked.connect(self._toggle_category)
        actions.addWidget(toggle)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def _load_categories(self) -> None:
        try:
            rows = self.services.catalogue.list_categories(self.ctx, active=None)
        except AppError as error:
            show_error(self, "دسته‌بندی‌ها", error)
            return
        self.category_table.set_rows(rows)
        self.category_parent.load(
            self.services.catalogue.category_choices(self.ctx, active_only=False),
            placeholder="— دستهٔ اصلی —")

    def _save_category(self) -> None:
        code = self.category_code.text().strip()
        title = self.category_title.text().strip()
        if not code or not title:
            show_info(self, "ثبت دسته", "کد و عنوان دسته را وارد کنید.")
            return
        try:
            self.services.catalogue.create_category(
                self.ctx, code=code, title_fa=title,
                parent_id=self.category_parent.value())
        except AppError as error:
            show_error(self, "ثبت دسته", error)
            return
        self.changed = True
        self.category_code.clear()
        self.category_title.clear()
        self._load_categories()
        show_info(self, "ثبت دسته", "دسته‌بندی ذخیره شد.", tone="success")

    def _toggle_category(self) -> None:
        index = self.category_table.selected_row_index()
        if index is None:
            show_info(self, "وضعیت دسته", "ابتدا یک دسته را انتخاب کنید.")
            return
        row = self.category_table.model.row_at(index)
        try:
            self.services.catalogue.update_category(self.ctx, row.id,
                                                    is_active=not row.is_active)
        except AppError as error:
            show_error(self, "وضعیت دسته", error)
            return
        self.changed = True
        self._load_categories()

    # ---------------------------------------------------------------- brands
    def _build_brands_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        self.brand_table = DataTable(BRAND_COLUMNS)
        layout.addWidget(self.brand_table, 1)
        form = QHBoxLayout()
        form.setSpacing(8)
        self.brand_code = QLineEdit()
        form.addWidget(form_row("کد *", self.brand_code), 1)
        self.brand_title = QLineEdit()
        form.addWidget(form_row("نام برند *", self.brand_title), 2)
        layout.addLayout(form)
        actions = QHBoxLayout()
        save = QPushButton("ثبت برند")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_brand)
        actions.addWidget(save)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def _load_brands(self) -> None:
        try:
            self.brand_table.set_rows(
                self.services.catalogue.list_brands(self.ctx, active=None))
        except AppError as error:
            show_error(self, "برندها", error)

    def _save_brand(self) -> None:
        code = self.brand_code.text().strip()
        title = self.brand_title.text().strip()
        if not code or not title:
            show_info(self, "ثبت برند", "کد و نام برند را وارد کنید.")
            return
        try:
            self.services.catalogue.create_brand(self.ctx, code=code, title_fa=title)
        except AppError as error:
            show_error(self, "ثبت برند", error)
            return
        self.changed = True
        self.brand_code.clear()
        self.brand_title.clear()
        self._load_brands()
        show_info(self, "ثبت برند", "برند ذخیره شد.", tone="success")

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._load_units()
        self._load_categories()
        self._load_brands()
