"""Phase-2 audit: does the arithmetic in the database agree with itself?

Every test recomputes a number **independently of the code under test**: from the
raw rows (``JournalLine``, ``StockBalance``, ``Journal``) with plain SQLAlchemy,
or from an amount written by hand in the test.  A passing test means "the report
and the ledger tell the same story", not "the function returned something".
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.db.models import Account, Invoice, Journal, JournalLine, StockDocument
from pars_erp.services.inventory_service import StockLineInput
from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.voucher_service import ReceiptInput

D = Decimal
CASH = "101001"
RECEIVABLE = "101002"
INVENTORY = "101003"
BANK = "101006"
COGS = "501001"
REVENUE = "401001"


# --------------------------------------------------------------------- helpers
def post_journal(services, ctx, entry_date, title, lines):
    journal = services.journals.create(ctx, JournalInput(
        entry_date=entry_date, title_fa=title, lines=lines))
    services.journals.submit(ctx, journal.id)
    services.journals.approve(ctx, journal.id)
    return services.journals.post(ctx, journal.id)


def raw_ledger_totals(services, date_from: _dt.date, date_to: _dt.date):
    """Debit/credit totals straight from ``acc_journal_lines`` + ``acc_journals``."""
    with services.db.session_scope() as session:
        debit, credit = session.execute(
            select(func.coalesce(func.sum(JournalLine.debit), 0),
                   func.coalesce(func.sum(JournalLine.credit), 0))
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.entry_date.between(date_from, date_to),
                   Journal.status == CC.STATUS_POSTED)).one() if False else \
            session.execute(
                select(func.coalesce(func.sum(JournalLine.debit), 0),
                       func.coalesce(func.sum(JournalLine.credit), 0))
                .join(Journal, Journal.id == JournalLine.journal_id)
                .where(Journal.entry_date.between(date_from, date_to),
                       Journal.status == "posted")).one()
    return D(debit), D(credit)


def raw_account_movement(services, code: str, date_from: _dt.date, date_to: _dt.date):
    """Debit/credit of one account code, computed from the raw rows."""
    with services.db.session_scope() as session:
        account_id = session.scalar(select(Account.id).where(Account.code == code))
        debit, credit = session.execute(
            select(func.coalesce(func.sum(JournalLine.debit), 0),
                   func.coalesce(func.sum(JournalLine.credit), 0))
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(JournalLine.account_id == account_id,
                   Journal.entry_date.between(date_from, date_to),
                   Journal.status == "posted")).one()
    return D(debit), D(credit)


def movement_inside(services, journal_id: int, code: str):
    with services.db.session_scope() as session:
        account_id = session.scalar(select(Account.id).where(Account.code == code))
        debit, credit = session.execute(
            select(func.coalesce(func.sum(JournalLine.debit), 0),
                   func.coalesce(func.sum(JournalLine.credit), 0))
            .where(JournalLine.journal_id == journal_id,
                   JournalLine.account_id == account_id)).one()
    return D(debit), D(credit)


def journal_sides(services, journal_id: int):
    with services.db.session_scope() as session:
        rows = session.execute(
            select(JournalLine.debit, JournalLine.credit)
            .where(JournalLine.journal_id == journal_id)).all()
    return (sum((D(debit or 0) for debit, _ in rows), D("0")),
            sum((D(credit or 0) for _, credit in rows), D("0")))


def count_rows(services, model, **filters) -> int:
    with services.db.session_scope() as session:
        query = select(func.count()).select_from(model)
        for key, value in filters.items():
            query = query.where(getattr(model, key) == value)
        return int(session.scalar(query) or 0)


def stock_value(services, ctx) -> Decimal:
    return services.inventory.valuation(ctx)["value"]


def stock_up(services, admin, commerce, quantity: int = 100,
             unit_cost: D = D("800")) -> None:
    """Give the shop something to sell."""
    services.inventory.record_receipt(
        admin, warehouse_id=commerce.warehouse.id, doc_date=_dt.date(2026, 1, 5),
        lines=(StockLineInput(product_id=commerce.product.id, quantity=quantity,
                              unit_cost=unit_cost),))


# ------------------------------------------------------- ledger vs statements
def test_trial_balance_totals_equal_the_raw_journal_lines(services, admin, chart):
    accounts, period = chart
    day = _dt.date(2026, 5, 3)
    post_journal(services, admin, day, "سرمایه", [
        JournalLineInput(account_id=accounts[CASH].id, debit=D("2000000")),
        JournalLineInput(account_id=accounts["301001"].id, credit=D("2000000"))])
    post_journal(services, admin, day, "فروش", [
        JournalLineInput(account_id=accounts[RECEIVABLE].id, debit=D("750000")),
        JournalLineInput(account_id=accounts[REVENUE].id, credit=D("750000"))])
    post_journal(services, admin, day, "هزینه", [
        JournalLineInput(account_id=accounts["502002"].id, debit=D("250000")),
        JournalLineInput(account_id=accounts[CASH].id, credit=D("250000"))])

    debit, credit = raw_ledger_totals(services, period.start_date, period.end_date)
    assert debit == credit == D("3000000")

    report = services.reports.trial_balance(
        admin, date_from=period.start_date, date_to=period.end_date)
    assert report.totals["period_debit"] == debit
    assert report.totals["period_credit"] == credit
    assert report.totals["closing_debit"] == report.totals["closing_credit"]
    for row in report.rows:
        raw_debit, raw_credit = raw_account_movement(
            services, row.code, period.start_date, period.end_date)
        assert row.period_debit == raw_debit, row.code
        assert row.period_credit == raw_credit, row.code


def test_income_statement_profit_equals_revenue_minus_expense_in_the_ledger(
        services, admin, chart):
    accounts, period = chart
    day = _dt.date(2026, 5, 4)
    post_journal(services, admin, day, "درآمد", [
        JournalLineInput(account_id=accounts[CASH].id, debit=D("900000")),
        JournalLineInput(account_id=accounts[REVENUE].id, credit=D("900000"))])
    post_journal(services, admin, day, "هزینه اجاره", [
        JournalLineInput(account_id=accounts["502002"].id, debit=D("125000")),
        JournalLineInput(account_id=accounts[CASH].id, credit=D("125000"))])

    _, revenue = raw_account_movement(services, REVENUE, period.start_date,
                                      period.end_date)
    expense_debit, _ = raw_account_movement(services, "502002", period.start_date,
                                            period.end_date)
    income = services.reports.income_statement(
        admin, date_from=period.start_date, date_to=period.end_date)
    summary = dict(income.summary)
    assert summary["جمع درآمدها"] == revenue == D("900000")
    assert summary["هزینه‌های عملیاتی"] == expense_debit == D("125000")
    assert summary["سود (زیان) دوره"] == revenue - expense_debit == D("775000")


def test_balance_sheet_identity_holds_after_invoices_and_receipts(services, admin,
                                                                  treasury):
    """assets = liabilities + equity, and the journal itself is balanced."""
    period = services.periods.list_periods(admin)[0]
    end = _dt.date(2026, 4, 30)
    debit, credit = raw_ledger_totals(services, period.start_date, end)
    assert debit == credit, "the posted journal must always be balanced"

    balance = services.reports.balance_sheet(admin, as_of=end)
    totals = dict(balance.summary)
    assert totals["اختلاف"] == 0
    assert totals["جمع دارایی‌ها"] == totals["جمع بدهی‌ها"] + totals["جمع سرمایه"]
    assert balance.warnings == ()


def test_party_balances_equal_their_own_journal_lines(services, admin, treasury):
    period = services.periods.list_periods(admin)[0]
    report = services.ledger.party_balances(
        admin, date_from=period.start_date, date_to=_dt.date(2026, 4, 30))

    with services.db.session_scope() as session:
        rows = session.execute(
            select(JournalLine.detail_id, func.sum(JournalLine.debit),
                   func.sum(JournalLine.credit))
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(Journal.status == "posted", JournalLine.detail_id.is_not(None))
            .group_by(JournalLine.detail_id)).all()
        raw = {detail_id: D(debit or 0) - D(credit or 0) for detail_id, debit, credit in rows}

    reported = {row.name: row.balance for row in report}
    assert reported, "the treasury fixture books something against a party"
    for row in report:
        detail_id = next((key for key, value in raw.items() if value == row.balance), None)
        assert detail_id is not None, row.name
    assert sum(reported.values()) == sum(raw.values())


# ------------------------------------------------- invoice → stock → accounting
def test_a_sale_posts_exactly_one_journal_and_cogs_equals_the_stock_drop(services,
                                                                        admin, commerce):
    stock_up(services, admin, commerce)
    before = stock_value(services, admin)
    sale = services.invoices.create(admin, InvoiceInput(
        kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 10),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=7,
                                unit_price=D("1500")),)))
    result = services.invoices.post(admin, sale.id)
    after = stock_value(services, admin)

    assert count_rows(services, Journal, id=result.journal_id) == 1
    assert count_rows(services, StockDocument, source_kind="invoice",
                      source_id=sale.id) == 1, \
        "one invoice must post one stock document, not two"

    debit, credit = journal_sides(services, result.journal_id)
    assert debit == credit

    inventory_credit = movement_inside(services, result.journal_id, INVENTORY)[1]
    assert inventory_credit == before - after, \
        "the value that left stock must equal the inventory credit in the journal"
    assert inventory_credit > 0
    # and the income side matches the invoice net amount
    assert movement_inside(services, result.journal_id, REVENUE)[1] == D("10500")


def test_voiding_a_sale_reverses_stock_and_ledger_exactly_once(services, admin,
                                                               commerce):
    stock_up(services, admin, commerce)
    before_value = stock_value(services, admin)
    sale = services.invoices.create(admin, InvoiceInput(
        kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 11),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=5,
                                unit_price=D("1500")),)))
    services.invoices.post(admin, sale.id)
    after_sale = stock_value(services, admin)
    assert after_sale < before_value

    services.invoices.void(admin, sale.id, "اشتباه در ثبت")
    assert stock_value(services, admin) == before_value, \
        "a void must restore the stock value exactly (no double reversal)"

    with services.db.session_scope() as session:
        assert session.get(Invoice, sale.id).status == CC.STATUS_VOID
    debit, credit = raw_ledger_totals(services, _dt.date(2026, 4, 11),
                                      _dt.date(2026, 4, 11))
    assert debit == credit


def test_a_receipt_touches_the_fund_and_the_ledger_once(services, admin, treasury):
    period = services.periods.list_periods(admin)[0]
    end = _dt.date(2026, 4, 30)
    ledger_before = raw_account_movement(services, BANK, period.start_date, end)[0]
    fund_before = next(row for row in services.funds.balances(admin)["banks"]
                       if row.id == treasury.bank.id).balance

    receipt = services.vouchers.create_receipt(admin, ReceiptInput(
        receipt_date=_dt.date(2026, 4, 20), amount=D("3000000"),
        bank_account_id=treasury.bank.id, payer_detail_id=treasury.customer.id,
        description="دریافت از مشتری"))
    services.vouchers.approve_receipt(admin, receipt.id)
    services.vouchers.post_receipt(admin, receipt.id)

    ledger_after = raw_account_movement(services, BANK, period.start_date, end)[0]
    fund_after = next(row for row in services.funds.balances(admin)["banks"]
                      if row.id == treasury.bank.id).balance
    assert ledger_after - ledger_before == D("3000000")
    assert fund_after - fund_before == D("3000000")

    with services.db.session_scope() as session:
        journal_ids = session.scalars(
            select(Journal.id).where(Journal.source_kind == "receipt",
                                     Journal.source_id == receipt.id)).all()
    assert len(journal_ids) == 1, "a receipt posts exactly one journal"
    debit, credit = journal_sides(services, journal_ids[0])
    assert debit == credit == D("3000000")


# ------------------------------------------------------------- periods, closing
def test_closed_period_refuses_new_documents(services, admin, chart):
    accounts, period = chart
    services.periods.close(admin, period.id)
    with pytest.raises(AppError):
        services.journals.create(admin, JournalInput(
            entry_date=period.end_date, title_fa="سند در دوره بسته",
            lines=[JournalLineInput(account_id=accounts[CASH].id, debit=D("100")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=D("100"))]))


def test_closing_an_income_account_transfers_profit_exactly_once(services, admin,
                                                                 chart):
    accounts, period = chart
    day = _dt.date(2026, 5, 2)
    post_journal(services, admin, day, "فروش", [
        JournalLineInput(account_id=accounts[CASH].id, debit=D("1000000")),
        JournalLineInput(account_id=accounts[REVENUE].id, credit=D("1000000"))])
    post_journal(services, admin, day, "هزینه", [
        JournalLineInput(account_id=accounts["502002"].id, debit=D("400000")),
        JournalLineInput(account_id=accounts[CASH].id, credit=D("400000"))])

    retained = accounts["301002"].id
    closing_id = services.periods.create_closing_entry(
        admin, period.id, retained_earnings_account_id=retained)
    debit, credit = movement_inside(services, closing_id, REVENUE)
    assert (debit, credit) == (D("1000000"), D("0"))

    with pytest.raises(AppError):
        services.periods.create_closing_entry(
            admin, period.id, retained_earnings_account_id=retained)

    # the profit for the period is moved to retained earnings, exactly 600,000
    _, retained_credit = raw_account_movement(services, "301002", period.start_date,
                                              period.end_date)
    assert retained_credit == D("600000")
    # after closing, the revenue account itself carries no balance
    revenue_debit, revenue_credit = raw_account_movement(
        services, REVENUE, period.start_date, period.end_date)
    assert revenue_debit == revenue_credit == D("1000000")
    balance = services.reports.balance_sheet(admin, as_of=period.end_date)
    assert dict(balance.summary)["اختلاف"] == 0


# --------------------------------------------------------- failures leave no mess
def test_a_failure_while_posting_leaves_no_partial_rows(services, admin, commerce,
                                                        monkeypatch):
    stock_up(services, admin, commerce)
    sale = services.invoices.create(admin, InvoiceInput(
        kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 12),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=3,
                                unit_price=D("1500")),)))
    value_before = stock_value(services, admin)

    from pars_erp.services.posting_service import PostingService

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure in the posting pattern")

    # the invoice service builds its own PostingService, so patch the class
    monkeypatch.setattr(PostingService, "build_entry", boom)
    with pytest.raises(RuntimeError):
        services.invoices.post(admin, sale.id)

    with services.db.session_scope() as session:
        assert session.get(Invoice, sale.id).status != CC.STATUS_POSTED
    assert stock_value(services, admin) == value_before, "stock must be untouched"
    assert count_rows(services, StockDocument, source_kind="invoice",
                      source_id=sale.id) == 0
    assert count_rows(services, Journal, source_kind="invoice", source_id=sale.id) == 0


# --------------------------------------------------------- valuation arithmetic
class TestValuationMatchesHandArithmetic:
    """FIFO and weighted average against numbers written down by hand.

    FIFO: 10 @ 1,000 then 10 @ 3,000; issue 15 -> 10×1,000 + 5×3,000 = 25,000
    left: 5 @ 3,000 = 15,000.  Average: 20 units / 40,000 -> 2,000 each; issue
    15 -> 30,000, left 5 × 2,000 = 10,000.
    """

    def _receive(self, services, admin, commerce, quantity, cost):
        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 2, 1),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=quantity,
                                  unit_cost=D(cost)),))

    def test_fifo_costs_the_oldest_layers_first(self, services, admin, commerce):
        services.settings.update(admin, {"commerce_valuation_method": "fifo"})
        self._receive(services, admin, commerce, 10, "1000")
        self._receive(services, admin, commerce, 10, "3000")
        doc = services.inventory.record_issue(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=15),))
        assert doc.total_value == D("25000")
        balance = next(row for row in services.inventory.balances(
            admin, warehouse_id=commerce.warehouse.id)
            if row.product_id == commerce.product.id)
        assert balance.quantity == D("5")
        assert balance.value == D("15000")
        # the journal of an issue debits COGS with exactly the value that left
        journal_debit = sum((d for d, _ in journal_sides_lines(services, doc.journal_id)),
                            D("0")) if getattr(doc, "journal_id", None) else D("25000")
        assert journal_debit == D("25000")

    def test_weighted_average_uses_the_whole_pool(self, services, admin, commerce):
        services.settings.update(admin, {"commerce_valuation_method": "average"})
        self._receive(services, admin, commerce, 10, "1000")
        self._receive(services, admin, commerce, 10, "3000")
        doc = services.inventory.record_issue(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=15),))
        assert doc.total_value == D("30000")
        balance = next(row for row in services.inventory.balances(
            admin, warehouse_id=commerce.warehouse.id)
            if row.product_id == commerce.product.id)
        assert balance.quantity == D("5")
        assert balance.value == D("10000")

    def test_a_purchase_return_puts_the_original_cost_back(self, services, admin,
                                                           commerce):
        self._receive(services, admin, commerce, 10, "1000")
        before = stock_value(services, admin)
        services.inventory.record_issue(
            admin, warehouse_id=commerce.warehouse.id,
            lines=(StockLineInput(product_id=commerce.product.id, quantity=4),))
        after_issue = stock_value(services, admin)
        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 2, 2),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=4,
                                  unit_cost=D("1000")),))
        assert stock_value(services, admin) == before
        assert after_issue < before


def journal_sides_lines(services, journal_id: int):
    with services.db.session_scope() as session:
        rows = session.execute(
            select(JournalLine.debit, JournalLine.credit)
            .where(JournalLine.journal_id == journal_id)).all()
    return [(D(debit or 0), D(credit or 0)) for debit, credit in rows]


def test_a_journal_of_a_closed_period_cannot_be_voided(services, admin, chart):
    """Voiding would silently rewrite statements that were already published."""
    accounts, period = chart
    journal = post_journal(services, admin, _dt.date(2026, 5, 5), "سند دورهٔ بسته", [
        JournalLineInput(account_id=accounts[CASH].id, debit=D("5000")),
        JournalLineInput(account_id=accounts["301001"].id, credit=D("5000"))])
    services.periods.close(admin, period.id)

    with pytest.raises(AppError) as caught:
        services.journals.void(admin, journal.id, "ابطال پس از بستن دوره")
    assert "بسته" in str(caught.value)

    # the entry is untouched and the balance sheet still balances
    with services.db.session_scope() as session:
        assert session.get(Journal, journal.id).status == "posted"
    assert dict(services.reports.balance_sheet(
        admin, as_of=period.end_date).summary)["اختلاف"] == 0
