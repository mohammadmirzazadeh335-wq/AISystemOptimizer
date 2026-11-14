"""Ledgers: journal book, general ledger, subsidiary ledger and turnovers.

Only **posted** documents are taken into account (``EFFECTIVE_STATUSES``): drafts,
pending, approved and voided documents never influence a balance. All arithmetic
uses :class:`decimal.Decimal`; nothing is rounded except for display.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select

from pars_erp.accounting import constants as C
from pars_erp.core.errors import NotFoundError
from pars_erp.db.models import (
    Account,
    CostCenter,
    DetailAccount,
    Journal,
    JournalLine,
    Project,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.common import Page, normalize_page

ZERO = Decimal("0")


# ---------------------------------------------------------------------- rows
@dataclass(frozen=True)
class JournalBookRow:
    journal_id: int
    number: int
    entry_date: _dt.date
    status_fa: str
    kind_fa: str
    title: str
    reference_no: str
    account_code: str
    account_title: str
    detail_name: str
    description: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class AccountBalanceRow:
    account_id: int
    code: str
    title: str
    level: str
    level_fa: str
    type_fa: str
    nature: str
    nature_fa: str
    opening_debit: Decimal = ZERO
    opening_credit: Decimal = ZERO
    period_debit: Decimal = ZERO
    period_credit: Decimal = ZERO
    closing_debit: Decimal = ZERO
    closing_credit: Decimal = ZERO

    @property
    def opening_net(self) -> Decimal:
        return self.opening_debit - self.opening_credit

    @property
    def period_net(self) -> Decimal:
        return self.period_debit - self.period_credit

    @property
    def closing_net(self) -> Decimal:
        return self.closing_debit - self.closing_credit

    @property
    def has_activity(self) -> bool:
        return any(value != ZERO for value in (
            self.opening_debit, self.opening_credit, self.period_debit,
            self.period_credit, self.closing_debit, self.closing_credit))


@dataclass(frozen=True)
class MovementRow:
    journal_id: int
    number: int
    entry_date: _dt.date
    title: str
    description: str
    detail_name: str
    cost_center: str
    project: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(frozen=True)
class LedgerResult:
    account: AccountBalanceRow
    opening: Decimal
    movements: tuple[MovementRow, ...]
    total_debit: Decimal
    total_credit: Decimal
    closing: Decimal


@dataclass(frozen=True)
class PartyBalanceRow:
    detail_id: int | None
    code: str
    name: str
    kind_fa: str
    account_code: str
    account_title: str
    debit: Decimal
    credit: Decimal

    @property
    def balance(self) -> Decimal:
        return self.debit - self.credit


@dataclass(frozen=True)
class DimensionBalanceRow:
    id: int | None
    code: str
    title: str
    debit: Decimal
    credit: Decimal

    @property
    def balance(self) -> Decimal:
        return self.debit - self.credit


class LedgerService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -------------------------------------------------------- journal book
    def journal_book(self, ctx: SecurityContext | None, *, date_from: _dt.date | None = None,
                     date_to: _dt.date | None = None, fiscal_period_id: int | None = None,
                     account_id: int | None = None, detail_id: int | None = None,
                     search: str | None = None, statuses: tuple[str, ...] = (C.STATUS_POSTED,),
                     page: int = 1, page_size: int = 50) -> Page[JournalBookRow]:
        require_permission(ctx, "reports.journal_book")
        page, page_size = normalize_page(page, page_size)
        with self.db.session_scope() as session:
            query = (select(JournalLine, Journal, Account, DetailAccount)
                     .join(Journal, JournalLine.journal_id == Journal.id)
                     .join(Account, JournalLine.account_id == Account.id)
                     .outerjoin(DetailAccount, JournalLine.detail_id == DetailAccount.id))
            if statuses:
                query = query.where(Journal.status.in_(statuses))
            if date_from:
                query = query.where(Journal.entry_date >= date_from)
            if date_to:
                query = query.where(Journal.entry_date <= date_to)
            if fiscal_period_id:
                query = query.where(Journal.fiscal_period_id == fiscal_period_id)
            if account_id:
                query = query.where(JournalLine.account_id == account_id)
            if detail_id:
                query = query.where(JournalLine.detail_id == detail_id)
            if search:
                needle = f"%{search.strip()}%"
                query = query.where(or_(Journal.title_fa.like(needle),
                                        Journal.reference_no.like(needle),
                                        Account.title_fa.like(needle),
                                        JournalLine.description.like(needle)))
            total = int(session.execute(
                select(func.count()).select_from(query.subquery())).scalar() or 0)
            rows = session.execute(
                query.order_by(Journal.entry_date, Journal.number, JournalLine.line_no)
                .limit(page_size).offset((page - 1) * page_size)).all()
            items = [
                JournalBookRow(
                    journal_id=journal.id,
                    number=journal.number,
                    entry_date=journal.entry_date,
                    status_fa=C.STATUS_TITLES_FA.get(journal.status, journal.status),
                    kind_fa=C.KIND_TITLES_FA.get(journal.kind, journal.kind),
                    title=journal.title_fa,
                    reference_no=journal.reference_no or "",
                    account_code=account.code,
                    account_title=account.title_fa,
                    detail_name=detail.name if detail else "",
                    description=line.description or "",
                    debit=Decimal(line.debit or 0),
                    credit=Decimal(line.credit or 0),
                )
                for line, journal, account, detail in rows
            ]
            return Page(items=items, total=total, page=page, page_size=page_size)

    # ------------------------------------------------------- account balances
    def account_balances(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                         date_to: _dt.date, level: str = C.LEVEL_SUBSIDIARY,
                         only_with_activity: bool = False,
                         active_only: bool = False) -> list[AccountBalanceRow]:
        """Opening / period / closing totals per account for ``date_from..date_to``."""
        require_permission(ctx, "reports.general_ledger")
        opening = self._totals_before(date_from)
        period = self._totals_between(date_from, date_to)
        with self.db.session_scope() as session:
            query = select(Account).order_by(Account.code)
            if level:
                query = query.where(Account.level == level)
            if active_only:
                query = query.where(Account.is_active.is_(True))
            accounts = list(session.execute(query).scalars())
        rows: list[AccountBalanceRow] = []
        for account in accounts:
            open_debit, open_credit = opening.get(account.id, (ZERO, ZERO))
            period_debit, period_credit = period.get(account.id, (ZERO, ZERO))
            # Opening balances are reported on their net side, exactly like closing
            # balances, so a trial balance never shows a negative column value.
            opening_net = open_debit - open_credit
            closing_net = opening_net + period_debit - period_credit
            row = AccountBalanceRow(
                account_id=account.id,
                code=account.code,
                title=account.title_fa,
                level=account.level,
                level_fa=C.LEVEL_TITLES_FA.get(account.level, account.level),
                type_fa=C.TYPE_TITLES_FA.get(account.account_type, account.account_type),
                nature=account.nature,
                nature_fa=C.NATURE_TITLES_FA.get(account.nature, account.nature),
                opening_debit=opening_net if opening_net > 0 else ZERO,
                opening_credit=-opening_net if opening_net < 0 else ZERO,
                period_debit=period_debit,
                period_credit=period_credit,
                closing_debit=closing_net if closing_net > 0 else ZERO,
                closing_credit=-closing_net if closing_net < 0 else ZERO,
            )
            if only_with_activity and not row.has_activity:
                continue
            rows.append(row)
        return rows

    def balances_by_section(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                            date_to: _dt.date) -> dict[str, list[tuple[Account, Decimal]]]:
        """Closing net per account grouped by its financial-statement section."""
        require_permission(ctx, "reports.statements")
        totals = self._closing_totals(date_to)
        result: dict[str, list[tuple[Account, Decimal]]] = {}
        with self.db.session_scope() as session:
            accounts = list(session.execute(
                select(Account).where(Account.level == C.LEVEL_SUBSIDIARY)
                .order_by(Account.code)).scalars())
            for account in accounts:
                if account.statement_section not in C.SECTION_TITLES_FA:
                    continue
                debit, credit = totals.get(account.id, (ZERO, ZERO))
                net = debit - credit
                if net == ZERO:
                    continue
                result.setdefault(account.statement_section, []).append((account, net))
        return result

    # ------------------------------------------------------ subsidiary ledger
    def account_ledger(self, ctx: SecurityContext | None, account_id: int, *,
                       date_from: _dt.date, date_to: _dt.date,
                       detail_id: int | None = None) -> LedgerResult:
        require_permission(ctx, "reports.subsidiary_ledger")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            opening_rows = session.execute(
                select(JournalLine.debit, JournalLine.credit)
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(JournalLine.account_id == account_id,
                       Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date < date_from,
                       *( [JournalLine.detail_id == detail_id] if detail_id else [] ))
            ).all()
            opening = sum((Decimal(d or 0) - Decimal(c or 0) for d, c in opening_rows), ZERO)

            query = (select(JournalLine, Journal, DetailAccount, CostCenter, Project)
                     .join(Journal, JournalLine.journal_id == Journal.id)
                     .outerjoin(DetailAccount, JournalLine.detail_id == DetailAccount.id)
                     .outerjoin(CostCenter, JournalLine.cost_center_id == CostCenter.id)
                     .outerjoin(Project, JournalLine.project_id == Project.id)
                     .where(JournalLine.account_id == account_id,
                            Journal.status.in_(C.EFFECTIVE_STATUSES),
                            Journal.entry_date >= date_from,
                            Journal.entry_date <= date_to))
            if detail_id:
                query = query.where(JournalLine.detail_id == detail_id)
            rows = session.execute(
                query.order_by(Journal.entry_date, Journal.number, JournalLine.line_no)).all()

            balance = opening
            movements: list[MovementRow] = []
            total_debit = ZERO
            total_credit = ZERO
            for line, journal, detail, cost_center, project in rows:
                debit = Decimal(line.debit or 0)
                credit = Decimal(line.credit or 0)
                total_debit += debit
                total_credit += credit
                balance += debit - credit
                movements.append(MovementRow(
                    journal_id=journal.id, number=journal.number,
                    entry_date=journal.entry_date, title=journal.title_fa,
                    description=line.description or "",
                    detail_name=detail.name if detail else "",
                    cost_center=cost_center.title_fa if cost_center else "",
                    project=project.title_fa if project else "",
                    debit=debit, credit=credit, balance=balance))

            summary = AccountBalanceRow(
                account_id=account.id, code=account.code, title=account.title_fa,
                level=account.level, level_fa=C.LEVEL_TITLES_FA.get(account.level, ""),
                type_fa=C.TYPE_TITLES_FA.get(account.account_type, ""),
                nature=account.nature,
                nature_fa=C.NATURE_TITLES_FA.get(account.nature, ""),
                opening_debit=opening if opening > 0 else ZERO,
                opening_credit=-opening if opening < 0 else ZERO,
                period_debit=total_debit, period_credit=total_credit,
                closing_debit=balance if balance > 0 else ZERO,
                closing_credit=-balance if balance < 0 else ZERO,
            )
            return LedgerResult(account=summary, opening=opening,
                                movements=tuple(movements), total_debit=total_debit,
                                total_credit=total_credit, closing=balance)

    # ---------------------------------------------------------- party balances
    def party_balances(self, ctx: SecurityContext | None, *,
                       date_from: _dt.date | None = None,
                       date_to: _dt.date | None = None,
                       kind: str | None = None,
                       search: str | None = None) -> list[PartyBalanceRow]:
        require_permission(ctx, "reports.subsidiary_ledger")
        with self.db.session_scope() as session:
            query = (select(JournalLine, Journal, DetailAccount, Account)
                     .join(Journal, JournalLine.journal_id == Journal.id)
                     .join(DetailAccount, JournalLine.detail_id == DetailAccount.id)
                     .join(Account, JournalLine.account_id == Account.id)
                     .where(Journal.status.in_(C.EFFECTIVE_STATUSES)))
            if date_from:
                query = query.where(Journal.entry_date >= date_from)
            if date_to:
                query = query.where(Journal.entry_date <= date_to)
            if kind:
                query = query.where(DetailAccount.kind == kind)
            if search:
                needle = f"%{search.strip()}%"
                query = query.where(or_(DetailAccount.name.like(needle),
                                        DetailAccount.code.like(needle)))
            rows = session.execute(query).all()
            buckets: dict[int, dict] = {}
            for line, journal, detail, account in rows:
                bucket = buckets.setdefault(detail.id, {
                    "detail": detail, "account": account, "debit": ZERO, "credit": ZERO})
                bucket["debit"] += Decimal(line.debit or 0)
                bucket["credit"] += Decimal(line.credit or 0)
            result = [
                PartyBalanceRow(
                    detail_id=item["detail"].id,
                    code=item["detail"].code,
                    name=item["detail"].name,
                    kind_fa=C.DETAIL_KIND_TITLES_FA.get(item["detail"].kind, ""),
                    account_code=item["account"].code,
                    account_title=item["account"].title_fa,
                    debit=item["debit"], credit=item["credit"])
                for item in buckets.values()
            ]
        result.sort(key=lambda row: row.code)
        return result

    # ------------------------------------------------------ dimension reports
    def dimension_balances(self, ctx: SecurityContext | None, dimension: str, *,
                           date_from: _dt.date, date_to: _dt.date) -> list[DimensionBalanceRow]:
        require_permission(ctx, "reports.general_ledger")
        if dimension not in ("cost_center", "project"):
            raise NotFoundError("گزارش ابعاد حسابداری انتخاب‌شده وجود ندارد.")
        column = JournalLine.cost_center_id if dimension == "cost_center" else JournalLine.project_id
        model = CostCenter if dimension == "cost_center" else Project
        with self.db.session_scope() as session:
            rows = session.execute(
                select(column, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date >= date_from,
                       Journal.entry_date <= date_to,
                       column.is_not(None))
                .group_by(column)).all()
            totals = {row[0]: (Decimal(row[1] or 0), Decimal(row[2] or 0)) for row in rows}
            records = list(session.execute(select(model).order_by(model.code)).scalars())
            result = []
            for record in records:
                debit, credit = totals.get(record.id, (ZERO, ZERO))
                result.append(DimensionBalanceRow(
                    id=record.id, code=record.code, title=record.title_fa,
                    debit=debit, credit=credit))
            unassigned = session.execute(
                select(func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date >= date_from,
                       Journal.entry_date <= date_to,
                       column.is_(None))).first()
            if unassigned and (unassigned[0] or unassigned[1]):
                result.append(DimensionBalanceRow(
                    id=None, code="—", title="بدون تخصیص",
                    debit=Decimal(unassigned[0] or 0), credit=Decimal(unassigned[1] or 0)))
        return result

    # --------------------------------------------------------------- internals
    def _totals_before(self, date_from: _dt.date) -> dict[int, tuple[Decimal, Decimal]]:
        with self.db.session_scope() as session:
            rows = session.execute(
                select(JournalLine.account_id,
                       func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date < date_from)
                .group_by(JournalLine.account_id)).all()
            return {row[0]: (Decimal(row[1] or 0), Decimal(row[2] or 0)) for row in rows}

    def _totals_between(self, date_from: _dt.date,
                        date_to: _dt.date) -> dict[int, tuple[Decimal, Decimal]]:
        with self.db.session_scope() as session:
            rows = session.execute(
                select(JournalLine.account_id,
                       func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date >= date_from,
                       Journal.entry_date <= date_to)
                .group_by(JournalLine.account_id)).all()
            return {row[0]: (Decimal(row[1] or 0), Decimal(row[2] or 0)) for row in rows}

    def _closing_totals(self, date_to: _dt.date) -> dict[int, tuple[Decimal, Decimal]]:
        """Cumulative debit/credit per account up to ``date_to`` (for statements)."""
        with self.db.session_scope() as session:
            rows = session.execute(
                select(JournalLine.account_id,
                       func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date <= date_to)
                .group_by(JournalLine.account_id)).all()
            return {row[0]: (Decimal(row[1] or 0), Decimal(row[2] or 0)) for row in rows}

    def period_activity(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                        date_to: _dt.date) -> tuple[Decimal, Decimal]:
        """Total debit/credit of posted documents in a range (balance proof)."""
        require_permission(ctx, "reports.trial_balance")
        with self.db.session_scope() as session:
            row = session.execute(
                select(func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.status.in_(C.EFFECTIVE_STATUSES),
                       Journal.entry_date >= date_from,
                       Journal.entry_date <= date_to)).first()
            return Decimal(row[0] or 0) if row else ZERO, Decimal(row[1] or 0) if row else ZERO
