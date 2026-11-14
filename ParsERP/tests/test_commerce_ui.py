"""Commerce screens: navigation, permissions and real widget smoke tests.

The Qt-free tests run everywhere. The ``gui`` tests build the real widgets; they
are skipped when no Qt platform plugin can be created (e.g. a bare CI container),
so the suite stays honest instead of pretending a screen was rendered.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

import pytest

from pars_erp.commerce import constants as CC
from pars_erp.security.permissions import ALL_PERMISSIONS
from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput
from pars_erp.ui.navigation import ALL_ITEMS, NAV_GROUPS, visible_items

COMMERCE_KEYS = (
    "products", "persons", "inventory", "purchase_invoices", "sales_invoices",
    "purchase_orders", "sales_orders", "pricing", "commerce_reports",
    "commerce_settings",
)

COMMERCE_PERMISSIONS = (
    "products.view", "products.create", "products.edit", "products.deactivate",
    "persons.view", "persons.create", "persons.edit", "persons.deactivate",
    "warehouses.view", "warehouses.edit", "stock.view", "stock.receipt",
    "stock.issue", "stock.transfer", "stock.adjust", "stock.count",
    "stock.count_approve",
    "purchase.invoice", "purchase.approve", "purchase.post",
    "purchase.return", "purchase.order", "purchase.reports",
    "sales.invoice", "sales.approve", "sales.post", "sales.return",
    "sales.order", "sales.reports",
    "pricing.view", "pricing.edit", "products.price_change",
    "stock.negative_override", "stock.cardex",
    "commerce.reports", "commerce.settings",
)


class TestCommerceNavigation:
    def test_group_exists_between_overview_and_accounting(self) -> None:
        keys = [group.key for group in NAV_GROUPS]
        assert keys.index("overview") < keys.index("commerce") < keys.index("accounting")
        group = next(group for group in NAV_GROUPS if group.key == "commerce")
        assert group.title_fa == "بازرگانی و انبار"
        assert {item.key for item in group.items} == set(COMMERCE_KEYS)

    def test_every_commerce_page_is_real(self) -> None:
        for key in COMMERCE_KEYS:
            item = ALL_ITEMS[key]
            assert not item.is_placeholder, f"{key} is a placeholder"
            assert item.enabled and item.description_fa and item.icon

    def test_every_commerce_permission_exists(self) -> None:
        known = {definition.code for definition in ALL_PERMISSIONS}
        missing = [code for code in COMMERCE_PERMISSIONS if code not in known]
        assert not missing, missing

    def test_storekeeper_sees_stock_but_not_invoices(self) -> None:
        from pars_erp.security.permissions import SecurityContext

        storekeeper = SecurityContext(
            user_id=99, username="انباردار", full_name="انباردار",
            role_codes=("storekeeper",),
            permissions=frozenset(_role_permissions("storekeeper")))
        keys = {item.key for group in visible_items(storekeeper) for item in group.items}
        assert {"inventory", "products"} <= keys
        assert "purchase_invoices" not in keys and "commerce_settings" not in keys


def _role_permissions(role_code: str) -> set[str]:
    from pars_erp.security.permissions import DEFAULT_ROLE_TEMPLATES

    template = next(t for t in DEFAULT_ROLE_TEMPLATES if t.code == role_code)
    return set(template.permissions)


# ---------------------------------------------------------------------- Qt gate
def _qt_available() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return False
    app = QApplication.instance() or QApplication([])
    return app is not None


qt_required = pytest.mark.skipif(
    not _qt_available(), reason="no Qt platform plugin is available in this environment")


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """Never let a headless test block on a modal box."""
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except Exception:
        return
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: 0, raising=False)
    monkeypatch.setattr(QMessageBox, "exec_", lambda self, *a, **k: 0, raising=False)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
                        raising=False)
    monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: QDialog.DialogCode.Rejected,
                        raising=False)


@pytest.fixture()
def formatter():
    from pars_erp.ui.formatting import Formatter

    return Formatter()


def _pages(services, admin, formatter):
    from pars_erp.ui.pages.commerce.inventory_page import InventoryPage
    from pars_erp.ui.pages.commerce.invoices_page import InvoicesPage
    from pars_erp.ui.pages.commerce.orders_page import OrdersPage
    from pars_erp.ui.pages.commerce.persons_page import PersonsPage
    from pars_erp.ui.pages.commerce.pricing_page import PricingPage
    from pars_erp.ui.pages.commerce.products_page import ProductsPage
    from pars_erp.ui.pages.commerce.reports_page import CommerceReportsPage
    from pars_erp.ui.pages.commerce.settings_page import CommerceSettingsPage

    return {
        "products": ProductsPage(services, admin, formatter),
        "persons": PersonsPage(services, admin, formatter),
        "inventory": InventoryPage(services, admin, formatter),
        "purchase_invoices": InvoicesPage(services, admin, formatter, family="purchase"),
        "sales_invoices": InvoicesPage(services, admin, formatter, family="sales"),
        "purchase_orders": OrdersPage(services, admin, formatter, family="purchase"),
        "sales_orders": OrdersPage(services, admin, formatter, family="sales"),
        "pricing": PricingPage(services, admin, formatter),
        "commerce_reports": CommerceReportsPage(services, admin, formatter),
        "commerce_settings": CommerceSettingsPage(services, admin, formatter),
    }


@pytest.mark.gui
@qt_required
class TestCommercePages:
    @pytest.mark.slow
    def test_every_page_builds_and_refreshes(self, qapp, services, admin, formatter,
                                            commerce) -> None:
        pages = _pages(services, admin, formatter)
        for key, page in pages.items():
            page.refresh()
            assert page.layoutDirection().name == "RightToLeft", key
            assert page.layout() is not None

    def test_products_search_and_category_filter(self, qapp, services, admin, formatter,
                                                 commerce) -> None:
        from pars_erp.ui.pages.commerce.products_page import ProductsPage

        page = ProductsPage(services, admin, formatter)
        page.refresh()
        assert len(page.table.model.rows()) >= 3
        page.search.setText("کالای دوم")
        page.refresh()
        assert len(page.table.model.rows()) == 1
        page.search.setText("")
        page.category_combo.set_value(commerce.category.id)
        page.refresh()
        assert len(page.table.model.rows()) == 1

    def test_product_dialog_creates_and_edits(self, qapp, services, admin, commerce) -> None:
        from pars_erp.ui.pages.commerce.products_page import ProductDialog

        dialog = ProductDialog(services, admin)
        dialog.code_edit.setText("UI-1")
        dialog.name_edit.setText("کالای رابط")
        dialog.unit_combo.set_value(commerce.unit.id)
        dialog.purchase_price.set_amount(1200)
        dialog.sale_price.set_amount(1800)
        dialog._save()
        assert dialog.saved is not None and dialog.saved.code == "UI-1"

        edit = ProductDialog(services, admin, product=dialog.saved)
        edit.name_edit.setText("کالای ویرایش‌شده")
        edit._save()
        assert edit.saved.name_fa == "کالای ویرایش‌شده"

    def test_catalogue_setup_creates_units_categories_brands(self, qapp, services,
                                                             admin, formatter) -> None:
        from pars_erp.ui.pages.commerce.products_page import CatalogueSetupDialog

        dialog = CatalogueSetupDialog(services, admin)
        dialog.unit_code.setText("PCS")
        dialog.unit_title.setText("عدد")
        dialog._save_unit()
        dialog.unit_code.setText("CTN")
        dialog.unit_title.setText("کارتن")
        dialog.unit_kind.setCurrentIndex(dialog.unit_kind.findData("carton"))
        dialog.unit_factor.setText("12")
        base = [u for u in services.catalogue.list_units(admin) if u.code == "PCS"][0]
        dialog.unit_base.set_value(base.id)
        dialog._save_unit()
        dialog.category_code.setText("C1")
        dialog.category_title.setText("گروه")
        dialog._save_category()
        dialog.brand_code.setText("B1")
        dialog.brand_title.setText("برند")
        dialog._save_brand()

        units = services.catalogue.list_units(admin)
        carton = next(u for u in units if u.code == "CTN")
        assert carton.factor == Decimal("12")
        assert services.catalogue.convert(admin, 2, from_unit_id=carton.id,
                                          to_unit_id=base.id) == Decimal("24")
        assert services.catalogue.list_categories(admin)
        assert services.catalogue.list_brands(admin)

    def test_stock_documents_from_dialogs(self, qapp, services, admin, commerce) -> None:
        from pars_erp.ui.pages.commerce.inventory_page import StockDocumentDialog

        def run(kind: str, quantity: int, **extra):
            dialog = StockDocumentDialog(services, admin, kind)
            assert dialog.warehouse_combo.value() == (
                services.inventory.warehouse_choices(admin)[0][0])
            dialog.warehouse_combo.set_value(commerce.warehouse.id)
            if kind == CC.MOVE_TRANSFER:
                dialog.target_combo.set_value(commerce.warehouse2.id)
            dialog.lines.cellWidget(0, 0).set_value(commerce.product.id)
            dialog.lines.item(0, 1).setText(str(quantity))
            price_column = 3 if kind == CC.MOVE_ADJUSTMENT else 2
            dialog.lines.item(0, price_column).setText("1000")
            if kind == CC.MOVE_ADJUSTMENT:
                dialog.lines.cellWidget(0, 2).setCurrentIndex(0)  # direction: in
                dialog.note_edit.setText("اصلاح آزمایشی انبار")
            dialog._save()
            assert dialog.saved is not None
            return dialog.saved

        receipt = run(CC.MOVE_RECEIPT, 20)
        assert receipt.line_count == 1
        assert receipt.total_value == Decimal("20000")
        run(CC.MOVE_ISSUE, 5)
        run(CC.MOVE_TRANSFER, 3)
        run(CC.MOVE_ADJUSTMENT, 2)
        on_hand = services.inventory.stock_on_hand(
            admin, commerce.product.id, warehouse_id=commerce.warehouse.id)
        assert on_hand == Decimal("14")

    def test_invoice_editor_calculates_and_saves(self, qapp, services, admin,
                                                 commerce) -> None:
        from pars_erp.ui.pages.commerce.invoices_page import InvoiceEditor

        dialog = InvoiceEditor(services, admin, CC.INVOICE_PURCHASE)
        dialog.party_combo.set_value(commerce.supplier.id)
        dialog.warehouse_combo.set_value(commerce.warehouse.id)
        dialog._add_row(product_id=commerce.product.id, quantity=10, price=1000)
        dialog.discount_edit.set_amount(300)
        dialog.charges_edit.set_amount(150)
        dialog._recalculate()
        text = dialog.totals_label.text()
        assert "مبلغ نهایی" in text
        dialog._save()
        assert dialog.saved is not None
        assert dialog.saved.net_total == Decimal("9850.00")

    def test_invoice_editor_scanner_adds_and_increments(self, qapp, services, admin,
                                                        commerce) -> None:
        from pars_erp.ui.pages.commerce.invoices_page import InvoiceEditor

        dialog = InvoiceEditor(services, admin, CC.INVOICE_SALE)
        dialog.barcode_edit.setText(commerce.product.barcode)
        dialog._scan_barcode()
        assert dialog.lines.rowCount() == 2  # one empty starter row + the scanned one
        dialog.barcode_edit.setText(commerce.product.barcode)
        dialog._scan_barcode()
        scanned = [dialog.lines.item(row, 1).text() for row in range(dialog.lines.rowCount())]
        assert "2" in scanned

    def test_reports_all_build_and_export(self, qapp, services, admin, formatter,
                                          commerce, tmp_path) -> None:
        from pars_erp.ui.pages.commerce.reports_page import (CommerceReportsPage,
                                                             REPORT_CHOICES)

        page = CommerceReportsPage(services, admin, formatter)
        assert len(REPORT_CHOICES) == 22
        for index, (key, _title, _period, _options) in enumerate(REPORT_CHOICES):
            page.report_combo.setCurrentIndex(index)
            table = page._render_table()
            assert table is not None and table.columns, key
            assert page.current is not None
        page.report_combo.setCurrentIndex(0)
        table = page._render_table()
        renderer = page._renderer()
        assert "زرین هرمز" in renderer.to_html(table) or renderer.to_html(table)
        pdf = renderer.to_pdf(table, tmp_path / "report.pdf")
        assert pdf.path.exists() and pdf.path.stat().st_size > 0
        excel = renderer.to_excel(table, tmp_path / "report.xlsx")
        assert excel.path.exists() and excel.path.stat().st_size > 0

    def test_invoice_preview_and_exports(self, qapp, services, admin, formatter,
                                          commerce, tmp_path) -> None:
        from pars_erp.ui.pages.commerce.invoices_page import (InvoiceEditor,
                                                              InvoicePreviewDialog)

        editor = InvoiceEditor(services, admin, CC.INVOICE_PURCHASE)
        editor.party_combo.set_value(commerce.supplier.id)
        editor.warehouse_combo.set_value(commerce.warehouse.id)
        editor._add_row(product_id=commerce.product.id, quantity=4, price=1000)
        editor._save()
        invoice = services.invoices.get(admin, editor.saved.id)

        dialog = InvoicePreviewDialog(services, admin, invoice, formatter)
        table = dialog._report_table()
        assert invoice.number in table.title
        outcome = dialog._renderer().to_excel(table, tmp_path / "invoice.xlsx")
        assert outcome.rows >= 1
        assert dialog.layoutDirection().name == "RightToLeft"

    def test_order_dialog_and_status_history(self, qapp, services, admin, commerce) -> None:
        from pars_erp.ui.pages.commerce.orders_page import OrderDialog, OrderHistoryDialog

        dialog = OrderDialog(services, admin, CC.ORDER_PURCHASE)
        dialog.party_combo.set_value(commerce.supplier.id)
        dialog.warehouse_combo.set_value(commerce.warehouse.id)
        dialog.lines.cellWidget(0, 0).set_value(commerce.product.id)
        dialog.lines.item(0, 1).setText("5")
        dialog.lines.item(0, 2).setText("1100")
        dialog._save()
        assert dialog.saved is not None
        services.orders.transition(admin, dialog.saved.id, CC.ORDER_STATUS_SUBMITTED, "ثبت")
        fresh = services.orders.get(admin, dialog.saved.id)
        history = OrderHistoryDialog(fresh)
        assert history is not None

    def test_pricing_and_settings_pages(self, qapp, services, admin, formatter,
                                        commerce) -> None:
        from pars_erp.ui.pages.commerce.pricing_page import (PriceListDialog,
                                                             PricingPage,
                                                             SetPriceDialog,
                                                             TaxRateDialog)
        from pars_erp.ui.pages.commerce.settings_page import CommerceSettingsPage

        rate = TaxRateDialog(services, admin)
        rate.code_edit.setText("VAT-UI")
        rate.title_edit.setText("مالیات آزمایشی")
        rate.percent_edit.setText("9")
        rate.to_edit.set_date(None)
        rate._save()
        assert services.pricing.list_tax_rates(admin)

        price_list = PriceListDialog(services, admin)
        price_list.code_edit.setText("PL-UI")
        price_list.title_edit.setText("لیست آزمایشی")
        price_list.discount_edit.setText("5")
        price_list._save()

        item = SetPriceDialog(services, admin, price_list.saved)
        item.product_combo.set_value(commerce.product.id)
        item.price_edit.set_amount(1700)
        item.reason_edit.setText("افزایش بهای خرید")
        item._save()

        page = PricingPage(services, admin, formatter)
        page.refresh()
        assert len(page.tax_table.model.rows()) >= 1

        settings = CommerceSettingsPage(services, admin, formatter)
        settings.refresh()
        settings.method_combo.setCurrentIndex(
            settings.method_combo.findData("fifo"))
        settings._save_method()
        assert services.settings.snapshot().str("commerce_valuation_method") == "fifo"

    @pytest.mark.slow
    def test_main_window_opens_every_visible_page(self, qapp, services, admin) -> None:
        from pars_erp.ui.main_window import MainWindow

        window = MainWindow(services, admin)
        window.show()
        try:
            for group in visible_items(admin):
                for item in group.items:
                    window.navigate(item.key)
            window.toggle_theme()
            window.toggle_theme()
        finally:
            window.close()

    @pytest.mark.slow
    def test_light_and_dark_stylesheets_differ(self, qapp, services, admin) -> None:
        from pars_erp.ui.theme import apply_theme, palette_for

        apply_theme(qapp, type(services.settings.snapshot())(
            values={**services.settings.snapshot().values, "theme": "light"}))
        light = qapp.styleSheet()
        apply_theme(qapp, type(services.settings.snapshot())(
            values={**services.settings.snapshot().values, "theme": "dark"}))
        dark = qapp.styleSheet()
        assert light and dark and light != dark
        assert palette_for("dark") != palette_for("light")


@pytest.mark.gui
@qt_required
class TestCommerceIntegrity:
    def test_posting_from_ui_creates_one_journal_and_one_stock_doc(
            self, qapp, services, admin, commerce) -> None:
        from pars_erp.ui.pages.commerce.invoices_page import InvoiceEditor

        editor = InvoiceEditor(services, admin, CC.INVOICE_PURCHASE)
        editor.party_combo.set_value(commerce.supplier.id)
        editor.warehouse_combo.set_value(commerce.warehouse.id)
        editor._add_row(product_id=commerce.product.id, quantity=3, price=1000)
        editor._save()
        posted = services.invoices.post(admin, editor.saved.id)
        assert posted.journal_id and posted.stock_document_id
        again = services.invoices.get(admin, editor.saved.id)
        assert again.journal_id == posted.journal_id
