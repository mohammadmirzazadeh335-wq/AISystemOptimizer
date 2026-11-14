"""Financial reports built exclusively from posted journal lines.

Every figure is derived from the database - nothing is typed in by hand, and the
same aggregation code feeds the screen, the PDF and the Excel export so the three
can never disagree.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from pars_erp.accounting import constants as C
from pars_erp.db.models import Account
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.ledger_service import AccountBalanceRow, LedgerService

ZERO = Decimal("0")


# ---------------------------------------------------------------------- rows
@dataclass(frozen=True)
class TrialBalanceRow:
    code: str
    title: str
    level_fa: str
    opening_debit: Decimal
    opening_credit: Decimal
    period_debit: Decimal
    period_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


@dataclass(frozen=True)
class TrialBalance:
    mode: int
    date_from: _dt.date
    date_to: _dt.date
    rows: tuple[TrialBalanceRow, ...]
    totals: dict[str, Decimal]

    @property
    def is_balanced(self) -> bool:
        return (self.totals["closing_debit"] == self.totals["closing_credit"]
                and self.totals["period_debit"] == self.totals["period_credit"])

    @property
    def difference(self) -> Decimal:
        return self.totals["closing_debit"] - self.totals["closing_credit"]


@dataclass(frozen=True)
class StatementLine:
    code: str
    title: str
    amount: Decimal


@dataclass(frozen=True)
class StatementSection:
    code: str
    title: str
    lines: tuple[StatementLine, ...] = ()
    total: Decimal = ZERO

    @property
    def is_empty(self) -> bool:
        return not self.lines


@dataclass(frozen=True)
class StatementReport:
    title: str
    subtitle: str
    sections: tuple[StatementSection, ...]
    summary: tuple[tuple[str, Decimal], ...] = ()
    warnings: tuple[str, ...] = ()


# ------------------------------------------------------------------- service
class ReportsService:
    def __init__(self, db: Database, ledger: LedgerService) -> None:
        self.db = db
        self.ledger = ledger

    # -------------------------------------------------------- trial balance
    def trial_balance(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                      date_to: _dt.date, mode: int = 2, level: str = C.LEVEL_SUBSIDIARY,
                      only_with_activity: bool = True) -> TrialBalance:
        require_permission(ctx, "reports.trial_balance")
        if mode not in (2, 4, 6):
            raise ValueError("حالت تراز آزمایشی باید ۲، ۴ یا ۶ ستونی باشد.")
        balances = self._rolled_balances(ctx, date_from=date_from, date_to=date_to, level=level)
        rows: list[TrialBalanceRow] = []
        totals = {
            "opening_debit": ZERO, "opening_credit": ZERO,
            "period_debit": ZERO, "period_credit": ZERO,
            "closing_debit": ZERO, "closing_credit": ZERO,
        }
        for balance in balances:
            row = TrialBalanceRow(
                code=balance.code,
                title=balance.title,
                level_fa=balance.level_fa,
                opening_debit=balance.opening_debit,
                opening_credit=balance.opening_credit,
                period_debit=balance.period_debit,
                period_credit=balance.period_credit,
                closing_debit=balance.closing_debit,
                closing_credit=balance.closing_credit,
            )
            if only_with_activity and not balance.has_activity:
                continue
            rows.append(row)
            totals["opening_debit"] += row.opening_debit
            totals["opening_credit"] += row.opening_credit
            totals["period_debit"] += row.period_debit
            totals["period_credit"] += row.period_credit
            totals["closing_debit"] += row.closing_debit
            totals["closing_credit"] += row.closing_credit
        return TrialBalance(mode=mode, date_from=date_from, date_to=date_to,
                            rows=tuple(rows), totals=totals)

    # -------------------------------------------------------- balance sheet
    def balance_sheet(self, ctx: SecurityContext | None, *, as_of: _dt.date) -> StatementReport:
        require_permission(ctx, "reports.statements")
        sections = self._build_sections(ctx, date_from=None, date_to=as_of,
                                        codes=C.BALANCE_SHEET_SECTIONS)
        assets = sum((section.total for section in sections
                      if section.code.endswith("assets")), ZERO)
        liabilities = sum((section.total for section in sections
                           if "liabilities" in section.code), ZERO)
        equity_sections = [section for section in sections if section.code == "equity"]
        equity = sum((section.total for section in equity_sections), ZERO)
        profit = self._net_profit_until(as_of)
        equity_with_profit = equity + profit
        warnings: list[str] = []
        if assets != liabilities + equity_with_profit:
            warnings.append(
                "جمع دارایی‌ها با جمع بدهی‌ها و سرمایه برابر نیست "
                f"(اختلاف: {assets - (liabilities + equity_with_profit)}). "
                "نگاشت سرفصل حساب‌ها و اسناد افتتاحیه را بررسی کنید.")

        profit_section = StatementSection(
            code="retained_result", title="سود (زیان) انباشته دوره‌های قبل و جاری",
            lines=(StatementLine("", "سود (زیان) انباشته محاسبه‌شده", profit),) if profit else (),
            total=profit)
        ordered = list(sections)
        ordered.insert(4 if len(sections) > 4 else len(sections), profit_section)
        summary = (
            ("جمع دارایی‌ها", assets),
            ("جمع بدهی‌ها", liabilities),
            ("جمع سرمایه", equity_with_profit),
            ("بدهی‌ها و سرمایه", liabilities + equity_with_profit),
            ("اختلاف", assets - (liabilities + equity_with_profit)),
        )
        return StatementReport(
            title="ترازنامه",
            subtitle=f"در تاریخ {as_of.isoformat()} — فقط اسناد ثبت نهایی شده",
            sections=tuple(ordered), summary=summary, warnings=tuple(warnings))

    # ----------------------------------------------------- income statement
    def income_statement(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                         date_to: _dt.date) -> StatementReport:
        require_permission(ctx, "reports.statements")
        sections = list(self._build_sections(ctx, date_from=date_from, date_to=date_to,
                                             codes=C.INCOME_SECTIONS))
        by_code = {section.code: section for section in sections}
        revenue = by_code.get("revenue", StatementSection("revenue", C.SECTION_TITLES_FA["revenue"])).total
        cogs = by_code.get("cogs", StatementSection("cogs", C.SECTION_TITLES_FA["cogs"])).total
        operating = by_code.get(
            "operating_expense",
            StatementSection("operating_expense", C.SECTION_TITLES_FA["operating_expense"])).total
        other_income = by_code.get(
            "other_income", StatementSection("other_income", C.SECTION_TITLES_FA["other_income"])).total
        other_expense = by_code.get(
            "other_expense",
            StatementSection("other_expense", C.SECTION_TITLES_FA["other_expense"])).total
        gross_profit = revenue - cogs
        operating_profit = gross_profit - operating
        net_profit = operating_profit + other_income - other_expense
        summary = (
            ("جمع درآمدها", revenue),
            ("بهای تمام‌شده", cogs),
            ("سود ناخالص", gross_profit),
            ("هزینه‌های عملیاتی", operating),
            ("سود عملیاتی", operating_profit),
            ("سایر درآمدها", other_income),
            ("سایر هزینه‌ها", other_expense),
            ("سود (زیان) دوره", net_profit),
        )
        return StatementReport(
            title="صورت سود و زیان",
            subtitle=(f"از {date_from.isoformat()} تا {date_to.isoformat()} — "
                      "فقط اسناد ثبت نهایی شده"),
            sections=tuple(sections), summary=summary)

    # ----------------------------------------------------- helpers / internals
    def _net_profit_until(self, as_of: _dt.date) -> Decimal:
        totals = self.ledger._closing_totals(as_of)
        income = ZERO
        with self.db.session_scope() as session:
            accounts = list(session.execute(
                select(Account).where(Account.level == C.LEVEL_SUBSIDIARY)).scalars())
        for account in accounts:
            if account.statement_section not in C.INCOME_SECTIONS:
                continue
            debit, credit = totals.get(account.id, (ZERO, ZERO))
            income += (credit - debit)
        return income

    def _build_sections(self, ctx, *, date_from: _dt.date | None, date_to: _dt.date,
                        codes: tuple[str, ...],
                        credit_positive: bool = True) -> list[StatementSection]:
        totals = self.ledger._closing_totals(date_to)
        opening = self.ledger._totals_before(date_from) if date_from else {}
        with self.db.session_scope() as session:
            accounts = list(session.execute(
                select(Account).where(Account.level == C.LEVEL_SUBSIDIARY)
                .order_by(Account.code)).scalars())
        buckets: dict[str, list[StatementLine]] = {code: [] for code in codes}
        sums: dict[str, Decimal] = {code: ZERO for code in codes}
        for account in accounts:
            section = account.statement_section
            if section not in buckets:
                continue
            debit, credit = totals.get(account.id, (ZERO, ZERO))
            if date_from is not None:
                open_debit, open_credit = opening.get(account.id, (ZERO, ZERO))
                debit -= open_debit
                credit -= open_credit
            # Statement figures are shown on the account's *normal* side:
            # assets/expenses grow with debit, liabilities/equity/revenue with credit.
            normal_side = C.TYPE_NATURE.get(account.account_type, "debit")
            net = (debit - credit) if normal_side == "debit" else (credit - debit)
            if net == ZERO:
                continue
            buckets[section].append(StatementLine(account.code, account.title_fa, net))
            sums[section] += net
        return [StatementSection(code=code, title=C.SECTION_TITLES_FA[code],
                                 lines=tuple(buckets[code]), total=sums[code])
                for code in codes if buckets[code]]

    def _rolled_balances(self, ctx, *, date_from: _dt.date, date_to: _dt.date,
                         level: str) -> list[AccountBalanceRow]:
        """Balances of ``level`` accounts, rolling leaf activity into ancestors."""
        leaves = self.ledger.account_balances(ctx, date_from=date_from, date_to=date_to,
                                              level=C.LEVEL_SUBSIDIARY)
        with self.db.session_scope() as session:
            accounts = {account.id: account for account in
                        session.execute(select(Account)).scalars()}
        aggregated: dict[int, list[Decimal]] = {}
        for leaf in leaves:
            current = accounts.get(leaf.account_id)
            values = [leaf.opening_debit, leaf.opening_credit, leaf.period_debit,
                      leaf.period_credit, leaf.closing_debit, leaf.closing_credit]
            while current is not None:
                if current.level == level:
                    bucket = aggregated.setdefault(current.id, [ZERO] * 6)
                    for index, value in enumerate(values):
                        bucket[index] += value
                    break
                current = accounts.get(current.parent_id) if current.parent_id else None
        result: list[AccountBalanceRow] = []
        for account_id, values in aggregated.items():
            account = accounts[account_id]
            result.append(AccountBalanceRow(
                account_id=account.id, code=account.code, title=account.title_fa,
                level=account.level, level_fa=C.LEVEL_TITLES_FA.get(account.level, ""),
                type_fa=C.TYPE_TITLES_FA.get(account.account_type, ""),
                nature=account.nature,
                nature_fa=C.NATURE_TITLES_FA.get(account.nature, ""),
                opening_debit=values[0], opening_credit=values[1],
                period_debit=values[2], period_credit=values[3],
                closing_debit=values[4], closing_credit=values[5]))
        result.sort(key=lambda row: row.code)
        return result
