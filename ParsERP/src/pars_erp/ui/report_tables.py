"""Qt-free builders that turn service results into printable report tables.

Keeping this mapping out of the widgets means:

* the same numbers feed the grid, the PDF, the Excel file and the tests;
* report layout can be unit-tested without a display;
* no accounting rule lives in a GUI class - these functions only *format* what
  the services already computed from posted documents.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.core.money import format_amount
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_NUMBER,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)

POSTED_ONLY_NOTE = "مبنای گزارش: فقط اسناد ثبت‌نهایی‌شده"


def report_meta(services, formatter, start: _dt.date, end: _dt.date) -> tuple[str, ...]:
    company = ""
    try:
        company = services.settings.snapshot().company_name
    except AppError:
        company = ""
    return (
        f"شرکت: {company}" if company else "شرکت: —",
        f"از {formatter.date(start)} تا {formatter.date(end)}",
        POSTED_ONLY_NOTE,
    )


def journal_book_table(services, ctx, formatter, *, start: _dt.date, end: _dt.date,
                       account_id: int | None = None, search: str | None = None,
                       page: int = 1, page_size: int = 200):
    """``(ReportTable, Page)`` for the daybook (روزنامه)."""
    result = services.ledger.journal_book(
        ctx, date_from=start, date_to=end, account_id=account_id, search=search,
        page=page, page_size=page_size)
    rows = tuple(
        (row.number, row.entry_date, row.title, row.account_code, row.account_title,
         row.detail_name or "—", row.description or "", row.debit, row.credit)
        for row in result.items)
    total_debit = sum((row.debit for row in result.items), Decimal(0))
    total_credit = sum((row.credit for row in result.items), Decimal(0))
    table = ReportTable(
        title="دفتر روزنامه",
        columns=(
            ReportColumn("number", "شماره سند", KIND_NUMBER, 0.8),
            ReportColumn("date", "تاریخ", KIND_DATE, 0.9),
            ReportColumn("title", "شرح سند", KIND_TEXT, 2.2),
            ReportColumn("account_code", "کد حساب", KIND_TEXT, 0.9),
            ReportColumn("account_title", "عنوان حساب", KIND_TEXT, 1.8),
            ReportColumn("detail", "تفصیلی", KIND_TEXT, 1.2),
            ReportColumn("description", "شرح سطر", KIND_TEXT, 1.6),
            ReportColumn("debit", "بدهکار", KIND_AMOUNT, 1.2),
            ReportColumn("credit", "بستانکار", KIND_AMOUNT, 1.2),
        ),
        rows=rows, meta=report_meta(services, formatter, start, end),
        totals=("", "", "جمع", "", "", "", "", total_debit, total_credit),
        currency_code=formatter.currency_code)
    return table, result


def general_ledger_table(services, ctx, formatter, *, start: _dt.date, end: _dt.date,
                         level: str = C.LEVEL_SUBSIDIARY) -> ReportTable:
    balances = services.ledger.account_balances(
        ctx, date_from=start, date_to=end, level=level, only_with_activity=True)
    rows = tuple((b.code, b.title, b.opening_debit, b.opening_credit, b.period_debit,
                  b.period_credit, b.closing_debit, b.closing_credit) for b in balances)
    totals = tuple(sum((getattr(b, name) for b in balances), Decimal(0))
                   for name in ("opening_debit", "opening_credit", "period_debit",
                                "period_credit", "closing_debit", "closing_credit"))
    return ReportTable(
        title="دفتر کل",
        columns=(
            ReportColumn("code", "کد حساب", KIND_TEXT, 0.9),
            ReportColumn("title", "عنوان حساب", KIND_TEXT, 2.6),
            ReportColumn("od", "مانده اول بدهکار", KIND_AMOUNT, 1.3),
            ReportColumn("oc", "مانده اول بستانکار", KIND_AMOUNT, 1.3),
            ReportColumn("pd", "گردش بدهکار", KIND_AMOUNT, 1.3),
            ReportColumn("pc", "گردش بستانکار", KIND_AMOUNT, 1.3),
            ReportColumn("cd", "مانده آخر بدهکار", KIND_AMOUNT, 1.3),
            ReportColumn("cc", "مانده آخر بستانکار", KIND_AMOUNT, 1.3),
        ),
        rows=rows, meta=report_meta(services, formatter, start, end),
        totals=("", "جمع کل") + totals,
        currency_code=formatter.currency_code)


def subsidiary_ledger_table(services, ctx, formatter, *, account_id: int | None,
                            start: _dt.date, end: _dt.date,
                            detail_id: int | None = None) -> ReportTable:
    """Account ledger with a running balance; empty note when no account chosen."""
    if account_id is None:
        return ReportTable(
            title="دفتر معین",
            columns=(ReportColumn("code", "کد"),),
            rows=(), meta=report_meta(services, formatter, start, end),
            notes=("برای نمایش دفتر معین، یک حساب انتخاب کنید.",))
    result = services.ledger.account_ledger(
        ctx, account_id, date_from=start, date_to=end, detail_id=detail_id)
    rows = [(None, None, "مانده ابتدای دوره", "", "", "", Decimal(0), Decimal(0),
             result.opening)]
    rows += [(movement.number, movement.entry_date, movement.title,
              movement.description or "", movement.detail_name or "",
              movement.cost_center or "", movement.debit, movement.credit,
              movement.balance) for movement in result.movements]
    rows.append((None, None, "جمع گردش", "", "", "", result.total_debit,
                 result.total_credit, result.closing))
    return ReportTable(
        title=f"دفتر معین — {result.account.code} {result.account.title}",
        columns=(
            ReportColumn("number", "شماره سند", KIND_NUMBER, 0.8),
            ReportColumn("date", "تاریخ", KIND_DATE, 0.9),
            ReportColumn("title", "شرح سند", KIND_TEXT, 2.0),
            ReportColumn("description", "شرح سطر", KIND_TEXT, 1.8),
            ReportColumn("detail", "تفصیلی", KIND_TEXT, 1.2),
            ReportColumn("cost_center", "مرکز هزینه", KIND_TEXT, 1.1),
            ReportColumn("debit", "بدهکار", KIND_AMOUNT, 1.2),
            ReportColumn("credit", "بستانکار", KIND_AMOUNT, 1.2),
            ReportColumn("balance", "مانده", KIND_AMOUNT, 1.3),
        ),
        rows=tuple(rows), meta=report_meta(services, formatter, start, end),
        totals=("", "جمع", "", "", "", "", result.total_debit, result.total_credit,
                result.closing),
        currency_code=formatter.currency_code)


def turnover_table(services, ctx, formatter, *, start: _dt.date, end: _dt.date,
                   level: str = C.LEVEL_SUBSIDIARY) -> ReportTable:
    balances = services.ledger.account_balances(
        ctx, date_from=start, date_to=end, level=level, only_with_activity=True)
    rows = tuple((b.code, b.title, b.type_fa, b.period_debit, b.period_credit,
                  b.closing_debit, b.closing_credit) for b in balances)
    totals = tuple(sum((getattr(b, name) for b in balances), Decimal(0))
                   for name in ("period_debit", "period_credit",
                                "closing_debit", "closing_credit"))
    return ReportTable(
        title="گردش حساب‌ها",
        columns=(
            ReportColumn("code", "کد حساب", KIND_TEXT, 0.9),
            ReportColumn("title", "عنوان حساب", KIND_TEXT, 2.8),
            ReportColumn("type", "نوع", KIND_TEXT, 1.0),
            ReportColumn("period_debit", "گردش بدهکار", KIND_AMOUNT, 1.4),
            ReportColumn("period_credit", "گردش بستانکار", KIND_AMOUNT, 1.4),
            ReportColumn("closing_debit", "مانده بدهکار", KIND_AMOUNT, 1.4),
            ReportColumn("closing_credit", "مانده بستانکار", KIND_AMOUNT, 1.4),
        ),
        rows=rows, meta=report_meta(services, formatter, start, end),
        totals=("", "جمع", "") + totals,
        currency_code=formatter.currency_code)


def trial_balance_table(services, ctx, formatter, *, start: _dt.date, end: _dt.date,
                        mode: int = 2, level: str = C.LEVEL_SUBSIDIARY) -> ReportTable:
    balance = services.reports.trial_balance(
        ctx, date_from=start, date_to=end, mode=mode, level=level)
    columns = [ReportColumn("code", "کد حساب", KIND_TEXT, 0.9),
               ReportColumn("title", "عنوان حساب", KIND_TEXT, 2.6)]
    rows: list[tuple] = []
    for row in balance.rows:
        values: list = [row.code, row.title]
        if mode >= 4:
            values += [row.period_debit, row.period_credit]
        if mode >= 6:
            values += [row.opening_debit, row.opening_credit]
        values += [row.closing_debit, row.closing_credit]
        rows.append(tuple(values))
    if mode >= 4:
        columns += [ReportColumn("period_debit", "گردش بدهکار", KIND_AMOUNT, 1.3),
                    ReportColumn("period_credit", "گردش بستانکار", KIND_AMOUNT, 1.3)]
    if mode >= 6:
        columns += [ReportColumn("opening_debit", "مانده اول بدهکار", KIND_AMOUNT, 1.4),
                    ReportColumn("opening_credit", "مانده اول بستانکار", KIND_AMOUNT, 1.4)]
    columns += [ReportColumn("closing_debit", "مانده آخر بدهکار", KIND_AMOUNT, 1.4),
                ReportColumn("closing_credit", "مانده آخر بستانکار", KIND_AMOUNT, 1.4)]

    totals: list = ["", "جمع کل"]
    if mode >= 4:
        totals += [balance.totals["period_debit"], balance.totals["period_credit"]]
    if mode >= 6:
        totals += [balance.totals["opening_debit"], balance.totals["opening_credit"]]
    totals += [balance.totals["closing_debit"], balance.totals["closing_credit"]]

    notes = []
    if not balance.is_balanced:
        notes.append("هشدار: تراز متوازن نیست؛ اختلاف مانده: "
                     + format_amount(balance.difference, formatter.currency_code,
                                     persian_digits=formatter.persian_digits))
    return ReportTable(
        title=f"تراز آزمایشی ({mode} ستونی)",
        columns=tuple(columns), rows=tuple(rows),
        meta=report_meta(services, formatter, start, end),
        totals=tuple(totals), notes=tuple(notes),
        currency_code=formatter.currency_code)


def statement_table(services, ctx, formatter, report, *, start: _dt.date,
                    end: _dt.date) -> ReportTable:
    """Flatten a :class:`StatementReport` into printable rows."""
    rows: list[tuple] = []
    for section in report.sections:
        if section.is_empty:
            continue
        rows.append((None, f"▸ {section.title}", None))
        for line in section.lines:
            rows.append((line.code, line.title, line.amount))
        rows.append((None, f"جمع {section.title}", section.total))
    for label, value in report.summary:
        rows.append((None, label, value))
    return ReportTable(
        title=report.title,
        columns=(
            ReportColumn("code", "کد حساب", KIND_TEXT, 1.0),
            ReportColumn("title", "عنوان", KIND_TEXT, 5.0),
            ReportColumn("amount", "مبلغ", KIND_AMOUNT, 1.8),
        ),
        rows=tuple(rows), subtitle=report.subtitle,
        meta=report_meta(services, formatter, start, end),
        notes=tuple(report.warnings),
        currency_code=formatter.currency_code)


def balance_sheet_table(services, ctx, formatter, *, as_of: _dt.date) -> ReportTable:
    report = services.reports.balance_sheet(ctx, as_of=as_of)
    return statement_table(services, ctx, formatter, report,
                           start=as_of.replace(month=1, day=1), end=as_of)


def income_statement_table(services, ctx, formatter, *, start: _dt.date,
                           end: _dt.date) -> ReportTable:
    report = services.reports.income_statement(ctx, date_from=start, date_to=end)
    return statement_table(services, ctx, formatter, report, start=start, end=end)
