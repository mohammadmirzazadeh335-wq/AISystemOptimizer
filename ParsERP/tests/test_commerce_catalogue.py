"""Products, units, categories, brands and persons (phase 3, part 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from pars_erp.services.catalogue_service import ProductFilter, ProductInput
from pars_erp.services.persons_service import PersonFilter, PersonInput


# ------------------------------------------------------------------- products
def test_product_is_created_with_all_commercial_fields(services, admin, commerce):
    row = services.catalogue.get(admin, commerce.product.id)
    assert row.code == "P-100"
    assert row.name_fa == "کالای آزمون"
    assert row.name_en == "Test Product"
    assert row.barcode == "6260000000011"
    assert row.kind == "goods"
    assert row.category_title == "مواد اولیه"
    assert row.brand_title == "برند آزمون"
    assert row.purchase_price == Decimal("1000.0000")
    assert row.sale_price == Decimal("1500.0000")
    assert row.reorder_point == Decimal("5.0000")
    assert row.is_active
    assert row.status_fa == "فعال"


def test_duplicate_barcode_is_rejected(services, admin, commerce):
    with pytest.raises(ConflictError) as exc:
        services.catalogue.create(admin, ProductInput(
            code="P-999", name_fa="کالای تکراری", unit_id=commerce.unit.id,
            barcode="6260000000011"))
    assert "بارکد" in str(exc.value)


def test_duplicate_product_code_is_rejected(services, admin, commerce):
    with pytest.raises(ConflictError):
        services.catalogue.create(admin, ProductInput(
            code="P-100", name_fa="کد تکراری", unit_id=commerce.unit.id))


def test_barcode_search_finds_the_product(services, admin, commerce):
    found = services.catalogue.find_by_barcode(admin, "6260000000011")
    assert found.id == commerce.product.id
    with pytest.raises(NotFoundError):
        services.catalogue.find_by_barcode(admin, "0000000000000")


def test_product_search_and_filters(services, admin, commerce):
    assert [r.code for r in services.catalogue.list_products(
        admin, ProductFilter(search="P-100"))] == ["P-100"]
    assert [r.code for r in services.catalogue.list_products(
        admin, ProductFilter(kind="service"))] == ["S-100"]
    assert [r.code for r in services.catalogue.list_products(
        admin, ProductFilter(category_id=commerce.category.id))] == ["P-100"]
    assert [r.code for r in services.catalogue.list_products(
        admin, ProductFilter(brand_id=commerce.brand.id))] == ["P-100"]
    assert services.catalogue.list_products(admin, ProductFilter(search="ناموجود")) == []


def test_product_deactivate_keeps_history_and_delete_is_guarded(services, admin, commerce):
    from pars_erp.services.inventory_service import StockLineInput

    deactivated = services.catalogue.set_active(admin, commerce.second.id, False)
    assert not deactivated.is_active
    assert deactivated.status_fa == "غیرفعال"
    services.catalogue.set_active(admin, commerce.second.id, True)

    services.inventory.record_receipt(
        admin, warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                              unit_cost=1000),))
    with pytest.raises(ValidationError) as exc:
        services.catalogue.delete(admin, commerce.product.id)
    assert "سابقه" in str(exc.value)

    # a product with no history can be removed
    services.catalogue.delete(admin, commerce.service.id)
    with pytest.raises(NotFoundError):
        services.catalogue.get(admin, commerce.service.id)


def test_price_change_requires_its_own_permission(services, admin, commerce):
    from pars_erp.services.user_service import UserCreateData

    services.roles.create_role(
        admin, code="cataloguer", title_fa="کارشناس کالا",
        permissions=("dashboard.view", "products.view", "products.create",
                     "products.edit", "pricing.view"))
    services.users.create_user(admin, UserCreateData(
        username="kala", full_name="کارشناس کالا", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("cataloguer",)))
    clerk = services.auth.authenticate("kala", "StoreRoom9931!")

    payload = ProductInput(code="P-100", name_fa="کالای آزمون", unit_id=commerce.unit.id,
                           purchase_price=1000, sale_price=1800)
    with pytest.raises(ValidationError) as exc:
        services.catalogue.update(clerk, commerce.product.id, payload)
    assert "مجوز" in str(exc.value)

    # unchanged prices are allowed without the extra permission
    same = ProductInput(code="P-100", name_fa="کالای ویرایش‌شده",
                        unit_id=commerce.unit.id, purchase_price=1000, sale_price=1500)
    assert services.catalogue.update(clerk, commerce.product.id, same).name_fa == \
        "کالای ویرایش‌شده"

    updated = services.catalogue.update(admin, commerce.product.id, payload)
    assert updated.sale_price == Decimal("1800.0000")


# ---------------------------------------------------------------------- units
def test_unit_conversion_between_families(services, admin, commerce):
    assert services.catalogue.convert(admin, 2, from_unit_id=commerce.carton.id,
                                      to_unit_id=commerce.unit.id) == Decimal("24.0000")
    with pytest.raises(NotFoundError):
        services.catalogue.convert(admin, 1, from_unit_id=commerce.carton.id,
                                   to_unit_id=commerce.unit.id + 999)


def test_unit_conversion_rejects_different_families(services, admin, commerce):
    other_base = services.catalogue.create_unit(admin, code="KG", title_fa="کیلوگرم",
                                                kind="kilogram")
    with pytest.raises(ValidationError) as exc:
        services.catalogue.convert(admin, 1, from_unit_id=commerce.carton.id,
                                   to_unit_id=other_base.id)
    assert "خانواده" in str(exc.value)


# ----------------------------------------------------------- categories/brands
def test_category_depth_is_limited(services, admin, commerce):
    level2 = services.catalogue.create_category(admin, code="CAT1-1",
                                                title_fa="سطح دو",
                                                parent_id=commerce.category.id)
    level3 = services.catalogue.create_category(admin, code="CAT1-1-1",
                                                title_fa="سطح سه", parent_id=level2.id)
    level4 = services.catalogue.create_category(admin, code="CAT1-1-1-1",
                                                title_fa="سطح چهار", parent_id=level3.id)
    with pytest.raises(ValidationError) as exc:
        services.catalogue.create_category(admin, code="CAT1-1-1-1-1",
                                           title_fa="سطح پنج", parent_id=level4.id)
    assert "عمق" in str(exc.value)


def test_category_with_products_cannot_be_deleted(services, admin, commerce):
    with pytest.raises(ValidationError):
        services.catalogue.delete_category(admin, commerce.category.id)


# -------------------------------------------------------------------- persons
def test_person_links_to_the_phase2_detail_account(services, admin, commerce):
    from pars_erp.db.models import DetailAccount

    supplier = services.persons.get(admin, commerce.supplier.id)
    assert supplier.account_label.startswith("201001")
    assert supplier.is_supplier and not supplier.is_customer
    assert supplier.role_fa == "تأمین‌کننده"

    with services.db.session_scope() as session:
        detail = session.get(DetailAccount, supplier.id)
        assert detail.account_id is not None
        assert detail.person_type == "real"
        assert detail.credit_limit == Decimal("0.0000")


def test_person_can_be_both_customer_and_supplier(services, admin, commerce):
    both = services.persons.create(admin, PersonInput(
        code="BOTH-1", name="شرکت دو نقشه", role="both", person_type="legal",
        national_id="3333333333", economic_code="411111111111"))
    assert both.is_customer and both.is_supplier
    assert both.role_fa == "مشتری و تأمین‌کننده"
    assert both.person_type_fa == "حقوقی"
    assert both.account_label.startswith("101002")


def test_duplicate_person_is_prevented(services, admin, commerce):
    with pytest.raises(ConflictError) as exc:
        services.persons.create(admin, PersonInput(
            code="CUS-1", name="کد تکراری", role="customer"))
    assert "کد" in str(exc.value)
    with pytest.raises(ConflictError) as exc:
        services.persons.create(admin, PersonInput(
            code="CUS-9", name="کد ملی تکراری", role="customer",
            national_id="2222222222"))
    assert "کد ملی" in str(exc.value)
    with pytest.raises(ConflictError):
        services.persons.create(admin, PersonInput(
            code="CUS-8", name="مشتری آزمون", role="customer"))


def test_person_search_and_role_filter(services, admin, commerce):
    assert [p.code for p in services.persons.list_persons(
        admin, PersonFilter(role="supplier"))] == ["SUP-1"]
    assert [p.code for p in services.persons.list_persons(
        admin, PersonFilter(search="09120000000"))] == ["CUS-1"]
    assert services.persons.list_persons(admin, PersonFilter(search="ناموجود")) == []


def test_person_delete_with_history_is_refused(services, admin, commerce):
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput
    import datetime as _dt

    invoice = services.invoices.create(admin, InvoiceInput(
        kind="purchase", invoice_date=_dt.date(2026, 11, 1),
        party_detail_id=commerce.supplier.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                unit_price=1000),)))
    services.invoices.post(admin, invoice.id)
    with pytest.raises(ValidationError):
        services.persons.delete(admin, commerce.supplier.id)
