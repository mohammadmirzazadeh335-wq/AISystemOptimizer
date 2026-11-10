"""Warehouses, stock movements, valuation methods and stock counts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.inventory_service import (
    CountLineInput,
    StockDocFilter,
    StockLineInput,
    WarehouseInput,
)


def _receive(services, admin, commerce, product, qty, cost, warehouse=None, day=None):
    return services.inventory.record_receipt(
        admin, warehouse_id=(warehouse or commerce.warehouse).id,
        doc_date=day,
        lines=(StockLineInput(product_id=product.id, quantity=qty, unit_cost=cost),))


def test_warehouse_crud_and_primary_flag(services, admin, commerce):
    primary = services.inventory.list_warehouses(admin)
    assert {w.code for w in primary} == {"WH1", "WH2"}
    assert next(w for w in primary if w.code == "WH1").is_primary

    third = services.inventory.create_warehouse(admin, WarehouseInput(
        code="WH3", title_fa="انبار سوم", is_primary=True,
        valuation_method="fifo"))
    rows = services.inventory.list_warehouses(admin)
    assert sum(1 for w in rows if w.is_primary) == 1
    assert next(w for w in rows if w.code == "WH3").valuation_fa.startswith("اولین")


def test_receipt_increases_stock_and_value(services, admin, commerce):
    doc = _receive(services, admin, commerce, commerce.product, 10, 1000)
    assert doc.status == "posted"
    assert doc.number.startswith("RCP-")
    assert doc.total_value == Decimal("10000.0000")
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("10.0000")
    valuation = services.inventory.valuation(admin)
    assert valuation["value"] == Decimal("10000.0000")


def test_issue_decreases_stock_at_average_cost(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 10, 1000)
    _receive(services, admin, commerce, commerce.product, 10, 2000)
    doc = services.inventory.record_issue(
        admin, warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=5),))
    assert doc.total_value == Decimal("7500.0000")   # average of 1500
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("15.0000")
    balance = services.inventory.balances(admin, warehouse_id=commerce.warehouse.id)[0]
    assert balance.average_cost == Decimal("1500.0000")


def test_negative_stock_is_refused_by_default(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 2, 1000)
    with pytest.raises(ValidationError) as exc:
        services.inventory.record_issue(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=5),))
    assert "کافی نیست" in str(exc.value)
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("2.0000")


def test_negative_stock_allowed_by_policy_and_permission(services, admin, commerce):
    warehouse = services.inventory.create_warehouse(admin, WarehouseInput(
        code="WHN", title_fa="انبار مجاز منفی", allow_negative=True))
    doc = services.inventory.record_issue(
        admin, warehouse_id=warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=3),))
    assert doc.status == "posted"
    assert services.inventory.stock_on_hand(admin, commerce.product.id,
                                            warehouse_id=warehouse.id) == Decimal("-3.0000")


def test_negative_stock_override_needs_the_permission(services, admin, commerce):
    from pars_erp.services.user_service import UserCreateData

    services.roles.create_role(
        admin, code="storekeeper2", title_fa="انباردار دوم",
        permissions=("dashboard.view", "products.view", "warehouses.view", "stock.view",
                     "stock.receipt", "stock.issue", "stock.cardex"))
    services.users.create_user(admin, UserCreateData(
        username="anbardar", full_name="انباردار", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("storekeeper2",)))
    keeper = services.auth.authenticate("anbardar", "StoreRoom9931!")
    warehouse = services.inventory.create_warehouse(admin, WarehouseInput(
        code="WHX", title_fa="انبار آزمایشی", allow_negative=True))
    services.inventory.record_receipt(
        admin, warehouse_id=warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=1, unit_cost=10),))
    with pytest.raises(ValidationError):
        services.inventory.record_issue(
            keeper, warehouse_id=warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=5),))


def test_transfer_between_warehouses_moves_quantity_and_value(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 10, 1000)
    doc = services.inventory.record_transfer(
        admin, warehouse_id=commerce.warehouse.id,
        target_warehouse_id=commerce.warehouse2.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=4),))
    assert doc.status == "posted"
    assert services.inventory.stock_on_hand(admin, commerce.product.id,
                                            warehouse_id=commerce.warehouse.id) == \
        Decimal("6.0000")
    assert services.inventory.stock_on_hand(admin, commerce.product.id,
                                            warehouse_id=commerce.warehouse2.id) == \
        Decimal("4.0000")
    assert services.inventory.valuation(admin)["value"] == Decimal("10000.0000")


def test_transfer_to_the_same_warehouse_is_rejected(services, admin, commerce):
    with pytest.raises(ValidationError):
        services.inventory.record_transfer(
            admin, warehouse_id=commerce.warehouse.id,
            target_warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=1),))


def test_fifo_valuation_consumes_oldest_layers_first(services, admin, commerce):
    services.settings.update(admin, {"commerce_valuation_method": "fifo"})
    _receive(services, admin, commerce, commerce.product, 10, 1000)
    _receive(services, admin, commerce, commerce.product, 10, 2000)
    doc = services.inventory.record_issue(
        admin, warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=15),))
    assert doc.total_value == Decimal("20000.0000")   # 10×1000 + 5×2000
    balance = [b for b in services.inventory.balances(admin,
                                                     warehouse_id=commerce.warehouse.id)
               if b.product_id == commerce.product.id][0]
    assert balance.quantity == Decimal("5.0000")
    assert balance.value == Decimal("10000.0000")


def test_weighted_average_is_the_default_method(services, admin, commerce):
    valuation = services.inventory.valuation(admin)
    assert valuation["method"] == "average"


def test_warehouse_can_override_the_company_method(services, admin, commerce):
    warehouse = services.inventory.create_warehouse(admin, WarehouseInput(
        code="WHF", title_fa="انبار فیفو", valuation_method="fifo"))
    _receive(services, admin, commerce, commerce.product, 10, 1000, warehouse=warehouse)
    _receive(services, admin, commerce, commerce.product, 10, 3000, warehouse=warehouse)
    doc = services.inventory.record_issue(
        admin, warehouse_id=warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=10),))
    assert doc.total_value == Decimal("10000.0000")


def test_cardex_shows_running_balance(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 10, 1000)
    services.inventory.record_issue(
        admin, warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=3),))
    rows = services.inventory.cardex(admin, commerce.product.id,
                                     warehouse_id=commerce.warehouse.id)
    assert [r.balance for r in rows] == [Decimal("10.00000000"), Decimal("7.00000000")]
    assert rows[0].quantity_in == Decimal("10")
    assert rows[1].quantity_out == Decimal("3")
    assert rows[1].unit_cost == Decimal("1000.0000")


def test_service_products_never_get_stock_documents(services, admin, commerce):
    with pytest.raises(ValidationError) as exc:
        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.service.id, quantity=1,
                                  unit_cost=100),))
    assert "خدمت" in str(exc.value)


def test_draft_document_can_be_deleted_but_posted_one_cannot(services, admin, commerce):
    from pars_erp.services.inventory_service import StockDocInput

    draft = services.inventory.create_document(admin, StockDocInput(
        kind="receipt", doc_date=None or __import__("datetime").date(2026, 11, 1),
        warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                              unit_cost=100),)))
    services.inventory.delete_document(admin, draft.id)
    assert services.inventory.list_documents(admin) == []

    posted = _receive(services, admin, commerce, commerce.product, 1, 100)
    with pytest.raises(ValidationError):
        services.inventory.delete_document(admin, posted.id)


def test_reversal_posts_the_mirror_image(services, admin, commerce):
    receipt = _receive(services, admin, commerce, commerce.product, 5, 1000)
    reversal = services.inventory.reverse_document(admin, receipt.id,
                                                   "اشتباه در ثبت اولیه")
    assert reversal.kind == "issue"
    assert reversal.total_value == Decimal("5000.0000")
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("0.0000")
    with pytest.raises(ValidationError):
        services.inventory.reverse_document(admin, receipt.id, "کم")  # reason validation


def test_adjustment_requires_a_reason(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 5, 1000)
    with pytest.raises(ValidationError):
        services.inventory.record_adjustment(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                                  direction="out"),), reason="کم")
    doc = services.inventory.record_adjustment(
        admin, warehouse_id=commerce.warehouse.id,
        lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                              direction="out"),), reason="شکستگی در انبار")
    assert doc.kind == "adjustment"
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("4.0000")


def test_stock_count_creates_an_adjustment_document(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 10, 1000)
    _receive(services, admin, commerce, commerce.second, 5, 2000)
    sheet_id = services.inventory.create_count_sheet(
        admin, warehouse_id=commerce.warehouse.id, note="انبارگردانی پایان دوره")
    sheet = services.inventory.count_sheet(admin, sheet_id)
    assert len(sheet["lines"]) == 2
    services.inventory.record_count(admin, sheet_id, [
        CountLineInput(product_id=commerce.product.id, counted_quantity=8,
                       note="دو عدد شکسته"),
        CountLineInput(product_id=commerce.second.id, counted_quantity=5),
    ])
    doc = services.inventory.approve_count(admin, sheet_id, "تأیید مغایرت")
    assert doc.kind == "adjustment"
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("8.0000")
    approved = services.inventory.count_sheet(admin, sheet_id)
    assert approved["status"] == "approved"
    with pytest.raises(ValidationError):
        services.inventory.approve_count(admin, sheet_id, "تکرار")


def test_low_stock_and_zero_stock_reports(services, admin, commerce):
    _receive(services, admin, commerce, commerce.product, 3, 1000)
    low = services.inventory.balances(admin, low_only=True)
    assert [row.product_id for row in low] == [commerce.product.id]
    assert low[0].status_fa == "کم‌موجود"
    zero = services.inventory.balances(admin, zero_only=True)
    assert zero == []


def test_stock_listing_requires_the_view_permission(services, admin, commerce):
    from pars_erp.services.user_service import UserCreateData

    services.users.create_user(admin, UserCreateData(
        username="nobody", full_name="کاربر بدون دسترسی", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("viewer",)))
    viewer = services.auth.authenticate("nobody", "StoreRoom9931!")

    services.roles.create_role(admin, code="blind", title_fa="بدون دسترسی",
                               permissions=("dashboard.view",))
    services.users.create_user(admin, UserCreateData(
        username="blind1", full_name="کاربر کور", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("blind",)))
    blind = services.auth.authenticate("blind1", "StoreRoom9931!")
    with pytest.raises(PermissionDeniedError):
        services.inventory.balances(blind)
    # the viewer may look but not move stock
    assert services.inventory.balances(viewer) == []
    with pytest.raises(PermissionDeniedError):
        services.inventory.record_receipt(
            viewer, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                                  unit_cost=10),))
