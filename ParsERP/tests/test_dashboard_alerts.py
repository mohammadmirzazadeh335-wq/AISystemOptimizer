"""Phase-7 management dashboard and alert rules, on a real (empty then filled) database."""

from __future__ import annotations

import datetime as _dt
from dataclasses import replace
from decimal import Decimal

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.alert_service import (
    ALERT_RULE_DEFS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)


# --------------------------------------------------------------- dashboard
def test_dashboard_shows_no_invented_cards_on_an_empty_company(services, admin):
    dashboard = services.management_dashboard.overview(admin)
    keys = {card.key for card in dashboard.cards}
    # Real data only: an empty company has no sales, but the treasury cards are
    # real zeros because the cash/bank tables exist and are genuinely zero.
    assert "sales_month" in keys
    assert dashboard.card("sales_month").value == Decimal("0")
    assert dashboard.card("sales_today").value == Decimal("0")
    assert dashboard.charts == ()  # no data -> no chart at all


def test_dashboard_respects_permissions(services, admin):
    limited = replace(admin, permissions=frozenset({"dashboard.view"}))
    dashboard = services.management_dashboard.overview(limited)
    assert dashboard.cards == ()
    assert dashboard.charts == ()

    nobody = replace(admin, permissions=frozenset())
    with pytest.raises(PermissionDeniedError):
        services.management_dashboard.overview(nobody)


def test_dashboard_sales_follow_posted_documents(services, admin, commerce):
    _stock_up(services, admin, commerce)
    invoice = _post_sale(services, admin, commerce, amount="1000000")
    assert invoice.status == "posted"
    dashboard = services.management_dashboard.overview(admin)
    sales = dashboard.card("sales_month")
    assert sales is not None
    assert sales.value == Decimal("1000000.0000")
    assert sales.link_page == "sales_invoices"


# ------------------------------------------------------------------ alerts
def test_rules_are_seeded_once_and_readable(services, admin):
    alerts = services.alerts
    first = alerts.rules(admin)
    assert {rule.key for rule in first} == {rule.key for rule in ALERT_RULE_DEFS}
    second = alerts.rules(admin)
    assert len(second) == len(first)
    assert alerts.rules(admin)[0].severity_fa  # translated for the UI


def test_evaluating_twice_does_not_duplicate_alerts(services, admin):
    services.alerts.set_rule(admin, "backup_stale", threshold={"hours": 1})
    first = services.alerts.evaluate(admin)
    second = services.alerts.evaluate(admin)
    assert len(first) == 1  # no backup yet -> one alert
    assert second == ()
    assert services.alerts.open_count(admin) == 1


def test_rule_can_be_disabled(services, admin):
    services.alerts.set_rule(admin, "backup_stale", is_enabled=False)
    assert services.alerts.evaluate(admin) == ()
    services.alerts.set_rule(admin, "backup_stale", is_enabled=True, severity=SEVERITY_CRITICAL,
                             threshold={"hours": 1})
    rule = next(rule for rule in services.alerts.rules(admin) if rule.key == "backup_stale")
    assert rule.is_enabled and rule.severity == SEVERITY_CRITICAL
    assert rule.threshold == {"hours": 1}


def test_unknown_rule_is_refused(services, admin):
    with pytest.raises(ValidationError):
        services.alerts.set_rule(admin, "no_such_rule", is_enabled=True)


def test_alert_lifecycle_acknowledge_and_resolve(services, admin):
    services.alerts.set_rule(admin, "backup_stale", threshold={"hours": 1})
    created = services.alerts.evaluate(admin)
    alert = created[0]
    assert alert.severity_fa in ("بحرانی", "هشدار")
    assert alert.is_open

    acknowledged = services.alerts.acknowledge(admin, alert.id, "بررسی شد")
    assert acknowledged.acknowledged_at is not None
    assert acknowledged.note_fa == "بررسی شد"

    resolved = services.alerts.resolve(admin, alert.id, "پشتیبان گرفته شد")
    assert resolved.resolved_at is not None
    assert services.alerts.open_count(admin) == 0
    assert any(row.id == alert.id for row in services.alerts.history(admin))


def test_alerts_require_permissions(services, admin):
    limited = replace(admin, permissions=frozenset({"dashboard.view"}))
    with pytest.raises(PermissionDeniedError):
        services.alerts.rules(limited)
    with pytest.raises(PermissionDeniedError):
        services.alerts.evaluate(limited)


def test_low_stock_rule_fires_when_stock_is_below_the_reorder_point(services, admin, commerce):
    # `commerce` seeds products with no stock, so the low-stock report has rows.
    services.alerts.set_rule(admin, "low_stock", threshold={"min_items": 1})
    created = services.alerts.evaluate(admin)
    low_stock = [alert for alert in created if alert.rule_key == "low_stock"]
    assert low_stock, "products without stock must raise the low-stock alert"
    assert low_stock[0].severity in (SEVERITY_WARNING, SEVERITY_CRITICAL)


def test_dashboard_counts_open_alerts(services, admin):
    services.alerts.set_rule(admin, "backup_stale", threshold={"hours": 1})
    services.alerts.evaluate(admin)
    dashboard = services.management_dashboard.overview(admin)
    card = dashboard.card("alerts_open")
    assert card is not None and card.value >= 1


# ------------------------------------------------------------------ helpers
def _stock_up(services, admin, commerce, *, quantity: str = "10"):
    """Bring stock in through a posted purchase invoice (no fixture magic)."""
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput

    invoice = services.invoices.create(admin, InvoiceInput(
        kind="purchase", invoice_date=_dt.date.today(),
        party_detail_id=commerce.supplier.id, warehouse_id=commerce.warehouse.id,
        lines=[InvoiceLineInput(product_id=commerce.product.id,
                                quantity=Decimal(quantity), unit_price=Decimal("1000"))]))
    services.invoices.post(admin, invoice.id)


def _post_sale(services, admin, commerce, *, amount: str):
    """Create and post a real sale invoice through the invoice service."""
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput

    invoice = services.invoices.create(admin, InvoiceInput(
        kind="sale", invoice_date=_dt.date.today(),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=[InvoiceLineInput(product_id=commerce.product.id, quantity=Decimal("1"),
                                unit_price=Decimal(amount))]))
    result = services.invoices.post(admin, invoice.id)
    return services.invoices.get(admin, invoice.id)
