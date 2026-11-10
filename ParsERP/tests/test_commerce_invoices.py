"""Purchase/sale invoices, returns, stock + ledger effects and posting rules."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.commerce_reports_service import CommerceReportService, ReportPeriod
from pars_erp.services.inventory_service import StockLineInput
from pars_erp.services.invoice_service import InvoiceFilter, InvoiceInput, InvoiceLineInput
from pars_erp.services.order_service import OrderInput, OrderLineInput
from pars_erp.services.persons_service import PersonInput
from pars_erp.services.posting_service import PostingService
from pars_erp.services.pricing_service import PricingService

DAY = _dt.date(2026, 11, 1)


def _invoice(services, ctx, commerce, kind, party, lines, **kwargs):
    warehouse = kwargs.pop("warehouse", kwargs.pop("warehouse_id", None)) \
        if "warehouse" in kwargs or "warehouse_id" in kwargs else commerce.warehouse
    if warehouse is None:
        warehouse_id = None
    else:
        warehouse_id = getattr(warehouse, "id", warehouse)
    return services.invoices.create(ctx, InvoiceInput(
        kind=kind, invoice_date=kwargs.pop("day", DAY),
        party_detail_id=kwargs.pop("party", party),
        warehouse_id=warehouse_id,
        lines=tuple(lines), **kwargs))


def _purchase(services, admin, commerce, lines, **kwargs):
    return _invoice(services, admin, commerce, "purchase", commerce.supplier.id, lines,
                    **kwargs)


def _sale(services, admin, commerce, lines, **kwargs):
    return _invoice(services, admin, commerce, "sale", commerce.customer.id, lines,
                    **kwargs)


def _stock(services, admin, commerce, product=None, qty=10, cost=1000):
    return services.inventory.record_receipt(
        admin, warehouse_id=commerce.warehouse.id, doc_date=DAY,
        lines=(StockLineInput(product_id=(product or commerce.product).id,
                              quantity=qty, unit_cost=cost),))


# --------------------------------------------------------------- invoice math
def test_purchase_totals_are_auditable(services, admin, commerce):
    invoice = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=10, unit_price=1000,
                         discount=200, tax_percent=10),
    ], invoice_discount=300, charges=150)
    assert invoice.subtotal == Decimal("10000.0000")
    assert invoice.line_discount == Decimal("200.0000")
    assert invoice.invoice_discount == Decimal("300.0000")
    assert invoice.tax_total == Decimal("950.0000")       # 10% of 9500
    assert invoice.charge_total == Decimal("150.0000")
    assert invoice.net_total == Decimal("10600.0000")


def test_sale_totals_with_invoice_discount_tax_and_charges(services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=4, unit_price=1500,
                         discount=500, tax_percent=10),
    ], invoice_discount=100, charges=200)
    assert invoice.subtotal == Decimal("6000.0000")
    assert invoice.tax_total == Decimal("540.0000")       # 10% of 5400
    assert invoice.net_total == Decimal("6140.0000")


def test_negative_discount_is_rejected(services, admin, commerce):
    with pytest.raises(ValidationError):
        _sale(services, admin, commerce, [
            InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                             unit_price=1500, discount=-10),
        ])


def test_tax_rate_table_is_dated_and_configurable(services, admin, commerce):
    pricing = services.pricing
    _stock(services, admin, commerce, qty=10, cost=1000)
    rate = pricing.create_tax_rate(admin, code="VAT10", title_fa="مالیات بر ارزش افزوده",
                                   percent=10, applies_to="sale",
                                   valid_from=_dt.date(2026, 1, 1),
                                   valid_to=_dt.date(2026, 12, 31))
    assert pricing.resolve_tax_percent(admin, rate_id=rate.id, on_date=DAY,
                                       kind="sale") == Decimal("10.0000")
    choosable = pricing.tax_rate_choices(admin, on_date=DAY, kind="sale")
    assert [row[0] for row in choosable] == [rate.id]

    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=2, unit_price=1000,
                         tax_rate_id=rate.id),
    ])
    assert invoice.tax_total == Decimal("200.0000")
    with pytest.raises(ValidationError):
        pricing.resolve_tax_percent(admin, rate_id=rate.id, on_date=DAY,
                                    kind="purchase")


def test_price_list_applies_to_the_customer_and_never_rewrites_past_invoices(
        services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    pricing = services.pricing
    special = pricing.create_price_list(
        admin, code="PL-S", title_fa="قیمت ویژه", kind="special",
        party_detail_id=commerce.customer.id,
        items=((commerce.product.id, Decimal("1300"), Decimal("0"), Decimal("0"), ""),))
    resolved = pricing.resolve_price(admin, commerce.product.id,
                                     party_detail_id=commerce.customer.id, on_date=DAY)
    assert resolved.price == Decimal("1300.0000")
    assert resolved.price_list_id == special.id

    first = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1),
    ])
    assert first.lines[0].unit_price == Decimal("1300.0000")

    pricing.set_item_price(admin, special.id, product_id=commerce.product.id,
                           price=Decimal("1900"), reason="افزایش بهای تمام‌شده")
    past = services.invoices.get(admin, first.id)
    assert past.lines[0].unit_price == Decimal("1300.0000")
    new = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1),
    ])
    assert new.lines[0].unit_price == Decimal("1900.0000")


# ------------------------------------------------------- purchase posting flow
def test_purchase_posting_creates_stock_and_balanced_journal(services, admin, commerce):
    invoice = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=10, unit_price=1000,
                         discount=200, tax_percent=10),
    ], invoice_discount=300, charges=150)
    result = services.invoices.post(admin, invoice.id)
    posted = result.invoice
    assert posted.status == "posted" and posted.status_fa == "ثبت نهایی"
    assert posted.stock_document_id and posted.journal_id

    # stock receipt at the net purchase cost
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("10.0000")
    stock_doc = services.inventory.get_document(admin, posted.stock_document_id)
    assert stock_doc.kind == "receipt"
    assert stock_doc.total_value == Decimal("9500.0000")

    from pars_erp.db.models import Journal
    with services.db.session_scope() as session:
        journal = session.get(Journal, posted.journal_id)
        debit = sum(line.debit for line in journal.lines)
        credit = sum(line.credit for line in journal.lines)
        assert debit == credit == Decimal("10600.0000")
        assert journal.status == "posted"
        assert journal.reference_no == posted.number
        assert journal.source_kind == "invoice"
        assert journal.source_id == invoice.id
        # the payable line carries the supplier's detail account
        payable = [l for l in journal.lines if l.credit > 0][0]
        assert payable.detail_id == commerce.supplier.id


def test_posting_twice_is_refused(services, admin, commerce):
    invoice = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1000)])
    services.invoices.post(admin, invoice.id)
    with pytest.raises(ValidationError) as exc:
        services.invoices.post(admin, invoice.id)
    assert "قبلاً" in str(exc.value)
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("1.0000")


def test_posted_invoice_cannot_be_edited(services, admin, commerce):
    invoice = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1000)])
    services.invoices.post(admin, invoice.id)
    with pytest.raises(ValidationError):
        services.invoices.update(admin, invoice.id, InvoiceInput(
            kind="purchase", invoice_date=DAY, party_detail_id=commerce.supplier.id,
            warehouse_id=commerce.warehouse.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=2,
                                    unit_price=1000),)))


# ------------------------------------------------------------ sale posting flow
def test_sale_posting_issues_stock_and_books_cogs(services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=4, unit_price=1500,
                         discount=500, tax_percent=10),
    ], invoice_discount=100, charges=200)
    result = services.invoices.post(admin, invoice.id)
    posted = result.invoice
    assert posted.status == "posted"
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("6.0000")
    assert posted.cogs_total == Decimal("4000.0000")   # 4 × 1000 average cost

    from pars_erp.db.models import Journal
    with services.db.session_scope() as session:
        journal = session.get(Journal, posted.journal_id)
        debit = sum(line.debit for line in journal.lines)
        credit = sum(line.credit for line in journal.lines)
        assert debit == credit
        assert debit == posted.net_total + posted.total_discount + posted.cogs_total
        receivable = [l for l in journal.lines if l.account.code == "101002"][0]
        assert receivable.debit == posted.net_total
        assert receivable.detail_id == commerce.customer.id


def test_overselling_is_refused_before_and_at_posting(services, admin, commerce):
    _stock(services, admin, commerce, qty=2, cost=1000)
    with pytest.raises(ValidationError) as exc:
        _sale(services, admin, commerce, [
            InvoiceLineInput(product_id=commerce.product.id, quantity=5,
                             unit_price=1500)])
    assert "کافی نیست" in str(exc.value)


def test_service_lines_do_not_create_stock_documents(services, admin, commerce):
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.service.id, quantity=2, unit_price=5000,
                         tax_percent=10),
    ], warehouse_id=None)
    result = services.invoices.post(admin, invoice.id)
    assert result.stock_document_id is None
    assert result.journal_id is not None
    assert result.invoice.net_total == Decimal("11000.0000")


def test_sale_return_is_linked_to_the_original_invoice(services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    sale = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=4, unit_price=1500,
                         tax_percent=10)])
    services.invoices.post(admin, sale.id)
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("6.0000")

    ret = services.invoices.create(admin, InvoiceInput(
        kind="sale_return", invoice_date=DAY, party_detail_id=commerce.customer.id,
        warehouse_id=commerce.warehouse.id, source_invoice_id=sale.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                unit_price=1500, tax_percent=10),)))
    result = services.invoices.post(admin, ret.id)
    assert result.invoice.status == "posted"
    assert result.invoice.source_number == sale.number
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("7.0000")

    from pars_erp.db.models import Journal
    with services.db.session_scope() as session:
        journal = session.get(Journal, result.journal_id)
        assert sum(l.debit for l in journal.lines) == sum(l.credit for l in journal.lines)

    with pytest.raises(ValidationError) as exc:
        services.invoices.create(admin, InvoiceInput(
            kind="sale_return", invoice_date=DAY,
            party_detail_id=commerce.customer.id,
            warehouse_id=commerce.warehouse.id, source_invoice_id=sale.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=9,
                                    unit_price=1500),)))
    assert "بیش از مقدار قابل برگشت" in str(exc.value)


def test_purchase_return_reduces_stock(services, admin, commerce):
    purchase = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=10, unit_price=1000)])
    services.invoices.post(admin, purchase.id)
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("10.0000")

    ret = services.invoices.create(admin, InvoiceInput(
        kind="purchase_return", invoice_date=DAY,
        party_detail_id=commerce.supplier.id,
        warehouse_id=commerce.warehouse.id, source_invoice_id=purchase.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=3,
                                unit_price=1000),)))
    result = services.invoices.post(admin, ret.id)
    assert result.invoice.status == "posted"
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("7.0000")


def test_return_requires_a_posted_source_invoice(services, admin, commerce):
    draft = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1000)])
    with pytest.raises(ValidationError) as exc:
        services.invoices.create(admin, InvoiceInput(
            kind="purchase_return", invoice_date=DAY,
            party_detail_id=commerce.supplier.id,
            warehouse_id=commerce.warehouse.id, source_invoice_id=draft.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                    unit_price=1000),)))
    assert "ثبت‌شده" in str(exc.value)


def test_voiding_an_invoice_posts_reversal_and_keeps_history(services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    sale = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=2, unit_price=1500)])
    posted = services.invoices.post(admin, sale.id).invoice
    voided = services.invoices.void(admin, sale.id, "اشتباه در انتخاب مشتری")
    assert voided.status == "void"
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("10.0000")

    from pars_erp.db.models import Journal
    with services.db.session_scope() as session:
        original = session.get(Journal, posted.journal_id)
        assert original.status == "posted"        # posted journals stay immutable
        reversals = session.query(Journal).filter(
            Journal.source_kind == "invoice_void",
            Journal.source_id == sale.id).all()
        assert len(reversals) == 1
        assert sum(l.debit for l in reversals[0].lines) == \
            sum(l.credit for l in reversals[0].lines)
    with pytest.raises(ValidationError):
        services.invoices.void(admin, sale.id, "تکرار ابطال")


def test_unbalanced_posting_pattern_aborts_the_whole_transaction(services, admin,
                                                                 commerce, chart):
    accounts, _period = chart
    _stock(services, admin, commerce, qty=10, cost=1000)
    posting = PostingService(services.db, services.audit)
    posting.save_rule(admin, "sale", lines=(
        ("debit", accounts["101002"].id, "net", "بدهکاران"),
        ("credit", accounts["201002"].id, "tax", "مالیات"),
    ))
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=2, unit_price=1500,
                         tax_percent=10)])
    with pytest.raises(ValidationError) as exc:
        services.invoices.post(admin, invoice.id)
    assert "تراز نیست" in str(exc.value)
    # nothing was applied: no stock issue, no journal, invoice still a draft
    assert services.inventory.stock_on_hand(admin, commerce.product.id) == Decimal("10.0000")
    refreshed = services.invoices.get(admin, invoice.id)
    assert refreshed.status == "draft"
    assert refreshed.journal_id is None and refreshed.stock_document_id is None


def test_posting_pattern_accounts_are_configurable(services, admin, commerce, chart):
    accounts, _ = chart
    posting = PostingService(services.db, services.audit)
    posting.save_rule(admin, "sale", lines=(
        ("debit", accounts["101002"].id, "net", "بدهکاران تجاری"),
        ("debit", accounts["401001"].id, "discount", "تخفیف"),
        ("credit", accounts["401001"].id, "subtotal", "درآمد"),
        ("credit", accounts["201002"].id, "tax", "مالیات"),
        ("credit", accounts["402001"].id, "charges", "هزینه‌های جانبی"),
        ("debit", accounts["501001"].id, "cogs", "بهای تمام‌شده"),
        ("credit", accounts["101003"].id, "cogs", "موجودی"),
    ))
    _stock(services, admin, commerce, qty=5, cost=1000)
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1500)])
    posted = services.invoices.post(admin, invoice.id).invoice
    from pars_erp.db.models import Journal
    with services.db.session_scope() as session:
        journal = session.get(Journal, posted.journal_id)
        assert {l.account.code for l in journal.lines} >= {"101002", "401001",
                                                           "501001", "101003"}


# ------------------------------------------------------------------- lifecycle
def test_invoice_lifecycle_draft_approve_post(services, admin, commerce):
    invoice = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1000)])
    assert invoice.status == "draft"
    approved = services.invoices.approve(admin, invoice.id)
    assert approved.status == "approved"
    posted = services.invoices.post(admin, invoice.id).invoice
    assert posted.status == "posted"
    with pytest.raises(ValidationError):
        services.invoices.approve(admin, invoice.id)


# ------------------------------------------------------------------ permissions
def test_commerce_permissions_are_enforced_in_the_service_layer(services, admin,
                                                                commerce):
    from pars_erp.services.user_service import UserCreateData

    services.users.create_user(admin, UserCreateData(
        username="forush", full_name="فروشنده", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("salesperson",)))
    seller = services.auth.authenticate("forush", "StoreRoom9931!")
    _stock(services, admin, commerce, qty=10, cost=1000)
    invoice = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1500)])
    # the salesperson may create but not post
    with pytest.raises(PermissionDeniedError):
        services.invoices.post(seller, invoice.id)
    assert services.invoices.post(admin, invoice.id).invoice.status == "posted"

    services.users.create_user(admin, UserCreateData(
        username="anbar", full_name="انباردار", password="StoreRoom9931!",
        confirm_password="StoreRoom9931!", role_codes=("storekeeper",)))
    keeper = services.auth.authenticate("anbar", "StoreRoom9931!")
    with pytest.raises(PermissionDeniedError):
        services.invoices.create(keeper, InvoiceInput(
            kind="sale", invoice_date=DAY, party_detail_id=commerce.customer.id,
            warehouse_id=commerce.warehouse.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                    unit_price=1500),)))
    with pytest.raises(PermissionDeniedError):
        services.invoices.post(keeper, invoice.id)


# --------------------------------------------------------------------- orders
def test_order_lifecycle_and_status_history(services, admin, commerce):
    order = services.orders.create(admin, OrderInput(
        kind="purchase_order", doc_date=DAY, party_detail_id=commerce.supplier.id,
        warehouse_id=commerce.warehouse.id,
        lines=(OrderLineInput(product_id=commerce.product.id, quantity=5,
                              unit_price=1000),)))
    assert order.status == "draft" and order.number.startswith("PO-")
    assert services.orders.transition(admin, order.id, "submitted").status == "submitted"
    assert services.orders.transition(admin, order.id, "pending_approval").status == \
        "pending_approval"
    assert services.orders.transition(admin, order.id, "approved").status == "approved"
    assert services.orders.transition(admin, order.id, "in_progress").status == "in_progress"
    final = services.orders.transition(admin, order.id, "completed", "تحویل شد")
    assert final.status == "completed"
    assert [h.to_status for h in final.history] == [
        "draft", "submitted", "pending_approval", "approved", "in_progress", "completed"]
    with pytest.raises(ValidationError):
        services.orders.transition(admin, order.id, "in_progress")


def test_order_conversion_needs_an_approved_order(services, admin, commerce):
    order = services.orders.create(admin, OrderInput(
        kind="sales_order", doc_date=DAY, party_detail_id=commerce.customer.id,
        warehouse_id=commerce.warehouse.id,
        lines=(OrderLineInput(product_id=commerce.product.id, quantity=2,
                              unit_price=1500),)))
    with pytest.raises(ValidationError):
        services.orders.invoice_prefill(admin, order.id)
    for status in ("submitted", "pending_approval", "approved"):
        services.orders.transition(admin, order.id, status)
    data = services.orders.invoice_prefill(admin, order.id)
    assert data["kind"] == "sale"
    assert data["lines"][0]["quantity"] == Decimal("2.0000")


# -------------------------------------------------------------------- reports
def test_management_reports(services, admin, commerce):
    _stock(services, admin, commerce, qty=20, cost=1000)
    purchase = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=5, unit_price=1000)])
    services.invoices.post(admin, purchase.id)
    sale = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=3, unit_price=1500,
                         discount=300)])
    services.invoices.post(admin, sale.id)

    reports = services.commerce_reports
    period = ReportPeriod(_dt.date(2026, 11, 1), _dt.date(2026, 11, 30))
    purch = reports.purchase_summary(admin, period, group_by="supplier")
    assert purch.title_fa == "خرید به تفکیک تأمین‌کننده"
    assert purch.rows[0][1] == purchase.net_total

    sales = reports.sales_summary(admin, period, group_by="customer")
    assert sales.rows[0][0] == "مشتری آزمون"
    assert sales.rows[0][4] == sale.net_total

    best = reports.best_sellers(admin, period)
    assert best.rows[0][0].startswith("P-100")
    assert best.rows[0][1] == Decimal("3.0000")

    value = reports.stock_value(admin)
    assert value.rows[-1][0] == "جمع کل"

    turnover = reports.person_turnover(admin, period)
    assert {row[0] for row in turnover.rows} == {"SUP-1 — تأمین‌کننده آزمون",
                                                 "CUS-1 — مشتری آزمون"}

    balances = reports.person_balances(admin, role="customer")
    assert balances.rows[0][3] == sale.net_total

    assert reports.low_stock(admin).column_count == 4
    assert reports.count_discrepancies(admin, period).rows == ()


def test_invoice_list_filters(services, admin, commerce):
    _stock(services, admin, commerce, qty=10, cost=1000)
    purchase = _purchase(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1000)])
    services.invoices.post(admin, purchase.id)
    sale = _sale(services, admin, commerce, [
        InvoiceLineInput(product_id=commerce.product.id, quantity=1, unit_price=1500)])
    services.invoices.post(admin, sale.id)

    assert len(services.invoices.list(admin, InvoiceFilter(kind="purchase"))) == 1
    assert len(services.invoices.list(admin, InvoiceFilter(kind="sale"))) == 1
    assert services.invoices.list(admin, InvoiceFilter(search="ناموجود")) == []
    assert services.invoices.list(
        admin, InvoiceFilter(date_from=_dt.date(2026, 12, 1))) == []
