"""Ledgers, trial balance, financial statements, periods and dimensions."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.services.dimensions_service import DimensionInput
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.periods_service import PeriodInput

D = Decimal


def _post(services, ctx, date, title, lines):
    journal = services.journals.create(ctx, JournalInput(
        entry_date=date, title_fa=title, lines=lines))
    services.journals.submit(ctx, journal.id)
    services.journals.approve(ctx, journal.id)
    return services.journals.post(ctx, journal.id)


def _seed_book(services, admin, accounts, date: _dt.date):
    """Capital 1,000,000 / sale 500,000 cash / rent 200,000 → profit 300,000."""
    _post(services, admin, date, "سرمایه اولیه", [
        JournalLineInput(account_id=accounts["101001"].id, debit=D("1000000")),
        JournalLineInput(account_id=accounts["301001"].id, credit=D("1000000"))])
    _post(services, admin, date, "فروش نقدی خدمات", [
        JournalLineInput(account_id=accounts["101001"].id, debit=D("500000")),
        JournalLineInput(account_id=accounts["401001"].id, credit=D("500000"))])
    _post(services, admin, date, "پرداخت اجاره", [
        JournalLineInput(account_id=accounts["502002"].id, debit=D("200000")),
        JournalLineInput(account_id=accounts["101001"].id, credit=D("200000"))])


# -------------------------------------------------------------------- balances
def test_general_ledger_opening_and_closing(services, admin, chart):
    accounts, period = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    balances = services.ledger.account_balances(
        admin, date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31))
    cash = next(row for row in balances if row.code == "101001")
    assert cash.period_debit == D("1500000.0000")
    assert cash.period_credit == D("200000.0000")
    assert cash.closing_debit == D("1300000.0000")

    # the following month opens with the closing balance and no activity
    next_month = services.ledger.account_balances(
        admin, date_from=_dt.date(2026, 6, 1), date_to=_dt.date(2026, 6, 30))
    cash_next = next(row for row in next_month if row.code == "101001")
    assert cash_next.opening_debit == D("1300000.0000")
    assert cash_next.period_debit == D("0")
    assert cash_next.closing_debit == D("1300000.0000")


def test_account_ledger_movements_are_running(services, admin, chart):
    accounts, _ = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    ledger = services.ledger.account_ledger(
        admin, accounts["101001"].id,
        date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31))
    assert len(ledger.movements) == 3
    assert [m.balance for m in ledger.movements] == [
        D("1000000.0000"), D("1500000.0000"), D("1300000.0000")]
    assert ledger.total_debit == D("1500000.0000")
    assert ledger.closing == D("1300000.0000")


def test_journal_book_lists_posted_lines_with_filters(services, admin, chart):
    accounts, _ = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    book = services.ledger.journal_book(admin, date_from=_dt.date(2026, 5, 1),
                                        date_to=_dt.date(2026, 5, 31))
    assert book.total == 6
    assert {row.account_code for row in book.items} >= {"101001", "301001"}
    filtered = services.ledger.journal_book(
        admin, date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31),
        account_id=accounts["502002"].id)
    assert filtered.total == 1
    assert filtered.items[0].debit == D("200000.0000")
    searched = services.ledger.journal_book(
        admin, date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31),
        search="اجاره")
    assert searched.total == 2       # both lines of the matching document


# --------------------------------------------------------------- trial balance
def test_trial_balance_is_balanced_in_all_modes(services, admin, chart):
    accounts, period = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    for mode in (2, 4, 6):
        report = services.reports.trial_balance(
            admin, date_from=period.start_date, date_to=period.end_date, mode=mode)
        assert report.mode == mode
        assert report.is_balanced
        assert report.totals["closing_debit"] == report.totals["closing_credit"]
        assert report.totals["period_debit"] == report.totals["period_credit"]
        assert report.totals["period_debit"] == D("1700000.0000")
        assert report.difference == 0


def test_trial_balance_rolls_up_to_total_accounts(services, admin, chart):
    accounts, period = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    report = services.reports.trial_balance(
        admin, date_from=period.start_date, date_to=period.end_date,
        level=C.LEVEL_TOTAL, only_with_activity=True)
    codes = {row.code for row in report.rows}
    assert "101" in codes          # cash rolls into "دارایی‌های جاری"
    assert "101001" not in codes
    assert report.is_balanced


# ----------------------------------------------------------- financial reports
def test_income_statement_and_balance_sheet(services, admin, chart):
    accounts, period = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    income = services.reports.income_statement(
        admin, date_from=period.start_date, date_to=period.end_date)
    summary = dict(income.summary)
    assert summary["جمع درآمدها"] == D("500000.0000")
    assert summary["هزینه‌های عملیاتی"] == D("200000.0000")
    assert summary["سود ناخالص"] == D("500000.0000")
    assert summary["سود (زیان) دوره"] == D("300000.0000")

    balance = services.reports.balance_sheet(admin, as_of=period.end_date)
    totals = dict(balance.summary)
    assert totals["جمع دارایی‌ها"] == D("1300000.0000")
    assert totals["جمع سرمایه"] == D("1300000.0000")   # 1,000,000 + 300,000 profit
    assert totals["اختلاف"] == 0
    assert balance.warnings == ()


def test_statements_ignore_unposted_documents(services, admin, chart):
    accounts, period = chart
    draft = services.journals.create(admin, JournalInput(
        entry_date=_dt.date(2026, 5, 2), title_fa="پیش‌نویس فروش",
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=D("999")),
               JournalLineInput(account_id=accounts["401001"].id, credit=D("999"))]))
    income = services.reports.income_statement(
        admin, date_from=period.start_date, date_to=period.end_date)
    assert dict(income.summary)["جمع درآمدها"] == D("0")
    services.journals.delete_draft(admin, draft.id)


# ------------------------------------------------------------------- periods
def test_period_crud_and_activation(services, admin, chart):
    _accounts, period = chart
    second = services.periods.create(admin, PeriodInput(
        code="1406", title_fa="سال مالی ۱۴۰۶",
        start_date=_dt.date(2027, 3, 21), end_date=_dt.date(2028, 3, 20)))
    assert second.status == C.PERIOD_OPEN
    services.periods.set_active(admin, second.id)
    active = services.periods.active_period(admin)
    assert active.id == second.id
    with pytest.raises(ValidationError):
        services.periods.create(admin, PeriodInput(
            code="dup", title_fa="هم‌پوشان",
            start_date=_dt.date(2027, 6, 1), end_date=_dt.date(2027, 9, 1)))
    services.periods.delete(admin, second.id)
    assert [row.id for row in services.periods.list_periods(admin)] == [period.id]


def test_closing_a_period_requires_posted_and_balanced_documents(services, admin, chart):
    accounts, period = chart
    draft = services.journals.create(admin, JournalInput(
        entry_date=_dt.date(2026, 5, 3), title_fa="پیش‌نویس باز",
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=D("10")),
               JournalLineInput(account_id=accounts["301001"].id, credit=D("10"))]))
    with pytest.raises(ValidationError) as exc:
        services.periods.close(admin, period.id)
    assert "نهایی نشده" in str(exc.value)
    services.journals.delete_draft(admin, draft.id)
    closed = services.periods.close(admin, period.id)
    assert closed.status == C.PERIOD_CLOSED
    assert closed.is_open is False
    reopened = services.periods.reopen(admin, period.id, "اصلاح سند فراموش‌شده")
    assert reopened.status == C.PERIOD_OPEN


def test_closing_entry_transfers_profit_to_equity(services, admin, chart):
    accounts, period = chart
    _seed_book(services, admin, accounts, _dt.date(2026, 5, 1))
    retained = accounts["301002"].id
    journal_id = services.periods.create_closing_entry(
        admin, period.id, retained_earnings_account_id=retained)
    journal = services.journals.get(admin, journal_id)
    assert journal.status == C.STATUS_POSTED
    assert journal.kind == C.KIND_CLOSING
    assert journal.is_balanced
    # income accounts are zeroed, retained earnings holds the profit
    income = services.reports.income_statement(
        admin, date_from=period.start_date, date_to=period.end_date)
    totals = dict(income.summary)
    assert totals["جمع درآمدها"] == D("0")
    assert totals["سود (زیان) دوره"] == D("0")
    ledger = services.ledger.account_ledger(
        admin, retained, date_from=period.start_date, date_to=period.end_date)
    # retained earnings is a credit-nature (equity) account
    assert ledger.closing == D("-300000.0000")
    assert ledger.account.closing_credit == D("300000.0000")
    with pytest.raises(ConflictError):
        services.periods.create_closing_entry(
            admin, period.id, retained_earnings_account_id=retained)


# ---------------------------------------------------------------- dimensions
def test_cost_centers_and_projects_are_optional_on_entries(services, admin, chart):
    accounts, period = chart
    cost_center = services.dimensions.create_cost_center(admin, DimensionInput(
        code="10", title_fa="مرکز هزینه ستاد"))
    project = services.dimensions.create_project(admin, DimensionInput(
        code="P1", title_fa="پروژه ساختمان"))
    assert {row.code for row in services.dimensions.list_cost_centers(admin)} == {"10"}

    _post(services, admin, _dt.date(2026, 5, 4), "هزینه با ابعاد", [
        JournalLineInput(account_id=accounts["502003"].id, debit=D("1000"),
                         cost_center_id=cost_center.id, project_id=project.id),
        JournalLineInput(account_id=accounts["101001"].id, credit=D("1000"))])
    # a normal entry without dimensions is still perfectly valid
    _post(services, admin, _dt.date(2026, 5, 4), "هزینه بدون ابعاد", [
        JournalLineInput(account_id=accounts["502003"].id, debit=D("500")),
        JournalLineInput(account_id=accounts["101001"].id, credit=D("500"))])

    by_center = services.ledger.dimension_balances(
        admin, "cost_center", date_from=period.start_date, date_to=period.end_date)
    center_row = next(row for row in by_center if row.id == cost_center.id)
    assert center_row.debit == D("1000.0000")
    unassigned = next(row for row in by_center if row.id is None)
    assert unassigned.debit == D("500.0000")

    by_project = services.ledger.dimension_balances(
        admin, "project", date_from=period.start_date, date_to=period.end_date)
    project_row = next(row for row in by_project if row.id == project.id)
    assert project_row.balance == D("1000.0000")


def test_party_balances_come_from_the_ledger(services, admin, chart):
    from pars_erp.services.parties_service import DetailInput

    accounts, period = chart
    customer = services.parties.create(admin, DetailInput(
        code="7001", name="مشتری الف", kind=C.DETAIL_CUSTOMER,
        account_id=accounts["101002"].id))
    _post(services, admin, _dt.date(2026, 5, 5), "فروش نسیه", [
        JournalLineInput(account_id=accounts["101002"].id, debit=D("450000"),
                         detail_id=customer.id),
        JournalLineInput(account_id=accounts["401001"].id, credit=D("450000"))])
    balances = services.ledger.party_balances(admin, date_from=period.start_date,
                                              date_to=period.end_date)
    row = next(item for item in balances if item.detail_id == customer.id)
    assert row.debit == D("450000.0000")
    assert row.balance == D("450000.0000")
    assert row.kind_fa == "مشتری"


# -------------------------------------------------------------- foreign currency
def test_foreign_currency_entry_keeps_the_rate_snapshot(services, admin, chart):
    accounts, _ = chart
    journal = services.journals.create(admin, JournalInput(
        entry_date=_dt.date(2026, 5, 6), title_fa="خرید ارز",
        currency_code="USD", exchange_rate=D("600000"),
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=D("1000")),
               JournalLineInput(account_id=accounts["301001"].id, credit=D("1000"))]))
    assert journal.currency_code == "USD"
    assert journal.exchange_rate == D("600000")
    assert journal.total_debit == D("600000000.0000")
    assert journal.is_balanced


def test_currency_rates_are_recorded_per_day(services, admin):
    rate = services.currency.set_rate(admin, "USD", _dt.date(2026, 5, 6), D("610000"),
                                      note="نرخ بانک مرکزی")
    assert rate.rate == D("610000")
    found = services.currency.rate_for(admin, "USD", _dt.date(2026, 5, 8))
    assert found == D("610000")
    with pytest.raises(ValidationError):
        services.currency.set_rate(admin, "IRR", _dt.date(2026, 5, 6), D("1"))
