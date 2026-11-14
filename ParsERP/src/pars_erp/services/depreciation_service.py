"""Depreciation runs: preview → approve → post (phase 5, part 5).

The arithmetic lives in :mod:`pars_erp.assets.depreciation` (pure functions).
This module only feeds it data, persists the result, and books the journal.

Guarantees:

* one run per Jalali month (DB unique constraint) and one line per asset per
  month, so an asset can never be depreciated twice for the same period;
* a posted run is immutable - corrections require the reversal path;
* the expense never takes an asset below its salvage value, and a fully
  depreciated asset contributes ``0`` (and is reported as skipped);
* units-of-production needs a reading per asset; without one nothing is
  invented, the asset is skipped and listed in the report.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pars_erp.assets import constants as A
from pars_erp.assets.depreciation import (
    book_value,
    first_period,
    money,
    monthly_amount,
    period_end_date,
)
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.core.jalali import days_in_month, jalali_to_gregorian
from pars_erp.db.models import (
    Asset,
    AssetCategory,
    DepreciationLine,
    DepreciationRun,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import next_document_number
from pars_erp.services.hr_common import ZERO


@dataclass(frozen=True)
class LineRow:
    asset_id: int
    asset_code: str
    asset_title: str
    category: str
    method: str
    method_fa: str
    opening_value: Decimal
    amount: Decimal
    accumulated_after: Decimal
    book_value_after: Decimal
    expense_account_id: int | None
    accumulated_account_id: int | None
    units_used: Decimal | None
    note: str


@dataclass(frozen=True)
class RunRow:
    id: int
    number: str
    year: int
    month: int
    period_end: _dt.date
    status: str
    status_fa: str
    assets_count: int
    total_amount: Decimal
    journal_id: int | None
    calculated_at: _dt.datetime | None
    approved_at: _dt.datetime | None
    posted_at: _dt.datetime | None
    note: str

    @property
    def title(self) -> str:
        return f"{self.number} — {self.year}/{self.month:02d}"


@dataclass(frozen=True)
class PreviewResult:
    year: int
    month: int
    period_end: _dt.date
    lines: tuple[LineRow, ...]
    skipped: tuple[tuple[str, str], ...]   # (asset code, Persian reason)
    total_amount: Decimal
    run: RunRow | None = None


class DepreciationService:
    def __init__(self, db: Database, audit: AuditService, *, journals=None,
                 settings=None) -> None:
        self.db = db
        self.audit = audit
        self.journals = journals
        self.settings = settings

    # --------------------------------------------------------------------- reads
    def list_runs(self, ctx: SecurityContext | None, *,
                  year: int | None = None) -> list[RunRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            query = select(DepreciationRun).order_by(
                DepreciationRun.period_year.desc(),
                DepreciationRun.period_month.desc())
            if year:
                query = query.where(DepreciationRun.period_year == year)
            return [self._run_row(row) for row in session.execute(query).scalars()]

    def get_run(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            return self._run_row(self._get_run(session, run_id))

    def run_lines(self, ctx: SecurityContext | None, run_id: int) -> list[LineRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            self._get_run(session, run_id)
            rows = session.execute(
                select(DepreciationLine).where(DepreciationLine.run_id == run_id)
                .order_by(DepreciationLine.id)).scalars()
            return [self._line_row(session, row) for row in rows]

    def asset_history(self, ctx: SecurityContext | None,
                      asset_id: int) -> list[LineRow]:
        """Posted + pending depreciation of one asset, newest first."""
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(DepreciationLine).where(DepreciationLine.asset_id == asset_id)
                .order_by(DepreciationLine.period_year.desc(),
                          DepreciationLine.period_month.desc()).limit(120)).scalars()
            return [self._line_row(session, row) for row in rows]

    # ------------------------------------------------------------------ preview
    def preview(self, ctx: SecurityContext | None, year: int, month: int, *,
                unit_readings: dict[int, Decimal] | None = None) -> PreviewResult:
        """Compute a period without writing anything."""
        require_permission(ctx, "assets.depreciate")
        self._validate_period(year, month)
        with self.db.session_scope() as session:
            lines, skipped = self._compute(session, year, month, unit_readings or {})
            existing = session.execute(
                select(DepreciationRun).where(DepreciationRun.period_year == year,
                                             DepreciationRun.period_month == month)
            ).scalars().first()
            return PreviewResult(
                year=year, month=month, period_end=period_end_date(year, month),
                lines=tuple(self._line_row(session, item)
                            for item in self._as_models(lines)),
                skipped=tuple(skipped),
                total_amount=sum((item["amount"] for item in lines), ZERO),
                run=self._run_row(existing) if existing else None)

    def calculate(self, ctx: SecurityContext | None, year: int, month: int, *,
                  unit_readings: dict[int, Decimal] | None = None,
                  note: str = "") -> PreviewResult:
        """Create (or refresh) the draft run of a period."""
        require_permission(ctx, "assets.depreciate")
        self._validate_period(year, month)
        with self.db.session_scope() as session:
            run = session.execute(
                select(DepreciationRun).where(DepreciationRun.period_year == year,
                                             DepreciationRun.period_month == month)
            ).scalars().first()
            if run is not None and run.status != A.DEP_RUN_DRAFT:
                raise ConflictError(
                    "دورهٔ استهلاک تأیید/ثبت شده است و بازمحاسبهٔ آن مجاز نیست؛ "
                    "برای اصلاح از مسیر سند اصلاحی استفاده کنید.")
            if run is None:
                end = period_end_date(year, month)
                run = DepreciationRun(
                    number=next_document_number(session, DepreciationRun, prefix="DEP",
                                                on_date=end),
                    period_year=year, period_month=month, period_end=end,
                    status=A.DEP_RUN_DRAFT, created_by_id=getattr(ctx, "user_id", None))
                session.add(run)
                session.flush()
            else:
                for line in list(session.execute(
                        select(DepreciationLine)
                        .where(DepreciationLine.run_id == run.id)).scalars()):
                    session.delete(line)
                session.flush()
            computed, skipped = self._compute(session, year, month, unit_readings or {})
            total = ZERO
            for item in computed:
                total += item["amount"]
                session.add(DepreciationLine(run_id=run.id, **item))
            run.assets_count = len(computed)
            run.total_amount = money(total)
            run.note = (note or "").strip() or None
            run.calculated_at = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="depreciation_run", entity_id=run.id, action="calculate",
                summary_fa=(f"محاسبهٔ استهلاک دورهٔ {year}/{month:02d} — "
                            f"{len(computed)} دارایی، مبلغ {total}"),
                after={"assets": len(computed), "total": str(total),
                       "skipped": len(skipped)}, session=session)
            rows = session.execute(
                select(DepreciationLine).where(DepreciationLine.run_id == run.id)
                .order_by(DepreciationLine.id)).scalars()
            return PreviewResult(
                year=year, month=month, period_end=run.period_end,
                lines=tuple(self._line_row(session, row) for row in rows),
                skipped=tuple(skipped), total_amount=Decimal(run.total_amount),
                run=self._run_row(run))

    def skip_run(self, ctx: SecurityContext | None, year: int, month: int,
                 note: str = "") -> None:
        """Delete a draft run (nothing has been posted, so nothing to reverse)."""
        require_permission(ctx, "assets.depreciate")
        with self.db.session_scope() as session:
            run = session.execute(
                select(DepreciationRun).where(DepreciationRun.period_year == year,
                                             DepreciationRun.period_month == month)
            ).scalars().first()
            if run is None:
                raise NotFoundError("دورهٔ استهلاک یافت نشد.")
            if run.status != A.DEP_RUN_DRAFT:
                raise ConflictError("تنها پیش‌نویس استهلاک قابل حذف است.")
            session.delete(run)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="depreciation_run", entity_id=run.id, action="delete",
                summary_fa=f"حذف پیش‌نویس استهلاک {year}/{month:02d}", after={"note": note},
                session=session)

    # ------------------------------------------------------------------ approve
    def approve(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        require_permission(ctx, "assets.depreciate")
        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status == A.DEP_RUN_POSTED:
                raise ConflictError("این دوره قبلاً ثبت شده است.")
            if run.status == A.DEP_RUN_APPROVED:
                raise ConflictError("این دوره قبلاً تأیید شده است.")
            if int(run.assets_count or 0) == 0 or Decimal(run.total_amount or 0) <= 0:
                raise ValidationError("دورهٔ استهلاک بدون مبلغ قابل تأیید نیست.")
            run.status = A.DEP_RUN_APPROVED
            run.approved_at = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            run.approved_by_id = getattr(ctx, "user_id", None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="depreciation_run", entity_id=run.id, action="approve",
                summary_fa=f"تأیید استهلاک {run.number}", session=session)
            return self._run_row(run)

    # --------------------------------------------------------------------- post
    def post(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        require_permission(ctx, "assets.post_depreciation")
        if self.journals is None:  # pragma: no cover
            raise ValidationError("سرویس دفتر روزنامه در دسترس نیست.")
        from pars_erp.services.treasury_common import post_system_journal
        from pars_erp.services.journals_service import JournalLineInput

        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status == A.DEP_RUN_POSTED:
                raise ConflictError("این دوره قبلاً در دفاتر ثبت شده است.")
            if run.status != A.DEP_RUN_APPROVED:
                raise ConflictError("پیش از ثبت نهایی، دورهٔ استهلاک را تأیید کنید.")
            lines = list(session.execute(
                select(DepreciationLine).where(DepreciationLine.run_id == run.id)
                .order_by(DepreciationLine.id)).scalars())
            if not lines:
                raise ValidationError("دورهٔ استهلاک سطر قابل ثبت ندارد.")
            grouped: dict[tuple[int | None, int | None], Decimal] = {}
            for line in lines:
                key = (line.expense_account_id, line.accumulated_account_id)
                grouped[key] = grouped.get(key, ZERO) + Decimal(line.amount or 0)
            journal_lines: list[JournalLineInput] = []
            for (expense_id, accumulated_id), amount in grouped.items():
                if amount <= 0:
                    continue
                if not expense_id or not accumulated_id:
                    raise ValidationError(
                        "حساب هزینه یا استهلاک انباشتهٔ یکی از دارایی‌ها تعیین نشده است؛ "
                        "ابتدا حساب‌های دارایی را کامل کنید.")
                journal_lines.append(JournalLineInput(
                    account_id=expense_id, debit=amount, credit=ZERO,
                    description="هزینهٔ استهلاک دوره"))
                journal_lines.append(JournalLineInput(
                    account_id=accumulated_id, debit=ZERO, credit=amount,
                    description="استهلاک انباشتهٔ دوره"))
            if not journal_lines:
                raise ValidationError("مبلغ استهلاک قابل ثبت صفر است.")
            journal = post_system_journal(
                session, journals=self.journals, ctx=ctx, entry_date=run.period_end,
                title_fa=f"استهلاک دارایی ثابت {run.period_year}/{run.period_month:02d}",
                reference_no=run.number,
                idempotency_key=f"depreciation:{run.id}:journal",
                notes=run.note or "", draft=_Draft(tuple(journal_lines)),
                source_kind="depreciation_run", source_id=run.id)
            now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            run.status = A.DEP_RUN_POSTED
            run.journal_id = journal.id
            run.posted_at = now
            if run.approved_at is None:
                run.approved_at = now
                run.approved_by_id = getattr(ctx, "user_id", None)
            for line in lines:
                if line.units_used:
                    asset = session.get(Asset, line.asset_id)
                    if asset is not None:
                        asset.units_depreciated = (
                            Decimal(asset.units_depreciated or 0)
                            + Decimal(line.units_used))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="depreciation_run", entity_id=run.id, action="post",
                summary_fa=f"ثبت استهلاک {run.number} در دفاتر",
                after={"journal_id": journal.id, "total": str(run.total_amount)},
                session=session)
            return self._run_row(run)

    # ------------------------------------------------------------------ helpers
    def _validate_period(self, year: int, month: int) -> None:
        year = int(year or 0)
        month = int(month or 0)
        if year <= 0 or not (1 <= month <= 12):
            raise ValidationError("دورهٔ استهلاک باید سال و ماه معتبر باشد.")

    def _get_run(self, session: Session, run_id: int) -> DepreciationRun:
        run = session.get(DepreciationRun, run_id)
        if run is None:
            raise NotFoundError("دورهٔ استهلاک یافت نشد.")
        return run

    def _company_policy(self) -> tuple[bool, bool]:
        """``(start_next_month, requires_approval)`` from settings, with safe defaults."""
        if self.settings is None:
            return False, True
        try:
            snapshot = self.settings.snapshot()
            return False, bool(snapshot.bool("assets_depreciation_requires_approval"))
        except Exception:  # pragma: no cover
            return False, True

    def _compute(self, session: Session, year: int, month: int,
                 unit_readings: dict[int, Decimal]) -> tuple[list[dict], list[tuple[str, str]]]:
        _, requires_approval = self._company_policy()
        end = period_end_date(year, month)
        target = (year, month)
        computed: list[dict] = []
        skipped: list[tuple[str, str]] = []
        assets = list(session.execute(select(Asset).order_by(Asset.code)).scalars())
        for asset in assets:
            if asset.status in A.DISPOSED_STATUSES:
                skipped.append((asset.code, "واگذار شده است"))
                continue
            start = asset.depreciation_start_override or asset.in_service_date
            if start is None:  # pragma: no cover - schema requires it
                skipped.append((asset.code, "تاریخ بهره‌برداری ندارد"))
                continue
            start_year, start_month = first_period(start)
            if target < (start_year, start_month):
                skipped.append((asset.code, "هنوز به دورهٔ استهلاک نرسیده است"))
                continue
            if end < start:
                skipped.append((asset.code, "تاریخ دوره پیش از بهره‌برداری است"))
                continue
            accumulated = self._accumulated(session, asset.id)
            opening = book_value(asset.initial_value, accumulated)
            units = None
            if asset.method == A.METHOD_UNITS:
                units = Decimal(str(unit_readings.get(asset.id, 0) or 0))
                if units <= 0:
                    skipped.append((asset.code, "کارکرد دوره برای روش کارکردی ثبت نشده است"))
                    continue
            amount = monthly_amount(
                method=asset.method, initial_value=Decimal(asset.initial_value or 0),
                salvage_value=Decimal(asset.salvage_value or 0),
                useful_life_months=int(asset.useful_life_months or 0),
                accumulated=accumulated,
                declining_rate=(Decimal(asset.declining_rate)
                                if asset.declining_rate is not None else None),
                units_period=units,
                total_units=(Decimal(asset.total_units)
                             if asset.total_units is not None else None))
            if amount <= 0:
                skipped.append((asset.code, "استهلاک کامل شده است"))
                continue
            accumulated_after = accumulated + amount
            computed.append({
                "asset_id": asset.id, "period_year": year, "period_month": month,
                "method": asset.method, "opening_value": opening, "amount": amount,
                "accumulated_after": accumulated_after,
                "book_value_after": book_value(asset.initial_value, accumulated_after),
                "expense_account_id": asset.expense_account_id,
                "accumulated_account_id": asset.accumulated_account_id,
                "units_used": units,
                "note": None,
            })
        return computed, skipped

    def _as_models(self, items: list[dict]) -> list[DepreciationLine]:
        """Wrap computed dicts so the preview can reuse :meth:`_line_row`."""
        return [DepreciationLine(**item) for item in items]

    def _accumulated(self, session: Session, asset_id: int) -> Decimal:
        total = session.execute(
            select(func.sum(DepreciationLine.amount))
            .join(DepreciationRun, DepreciationRun.id == DepreciationLine.run_id)
            .where(DepreciationLine.asset_id == asset_id,
                   DepreciationRun.status == A.DEP_RUN_POSTED)).scalar()
        return Decimal(total or 0)

    def _run_row(self, run: DepreciationRun) -> RunRow:
        return RunRow(
            id=run.id, number=run.number, year=run.period_year, month=run.period_month,
            period_end=run.period_end, status=run.status,
            status_fa=A.DEP_RUN_TITLES_FA.get(run.status, run.status),
            assets_count=int(run.assets_count or 0),
            total_amount=Decimal(run.total_amount or 0), journal_id=run.journal_id,
            calculated_at=run.calculated_at, approved_at=run.approved_at,
            posted_at=run.posted_at, note=run.note or "")

    def _line_row(self, session: Session, line: DepreciationLine) -> LineRow:
        asset = session.get(Asset, line.asset_id)
        category = (session.get(AssetCategory, asset.category_id)
                    if asset is not None else None)
        return LineRow(
            asset_id=line.asset_id,
            asset_code=asset.code if asset else "",
            asset_title=asset.title_fa if asset else "",
            category=category.title_fa if category else "",
            method=line.method,
            method_fa=A.METHOD_TITLES_FA.get(line.method, line.method),
            opening_value=Decimal(line.opening_value or 0),
            amount=Decimal(line.amount or 0),
            accumulated_after=Decimal(line.accumulated_after or 0),
            book_value_after=Decimal(line.book_value_after or 0),
            expense_account_id=line.expense_account_id,
            accumulated_account_id=line.accumulated_account_id,
            units_used=(Decimal(line.units_used) if line.units_used is not None else None),
            note=line.note or "")


class _Draft:
    """Minimal journal draft accepted by :func:`post_system_journal`."""

    def __init__(self, lines) -> None:
        self.lines = tuple(lines)


# Re-exported for the UI's period picker (kept here so callers import one place).
def month_bounds(year: int, month: int) -> tuple[_dt.date, _dt.date]:
    return (jalali_to_gregorian(year, month, 1),
            jalali_to_gregorian(year, month, days_in_month(year, month)))


__all__ = [
    "DepreciationService", "LineRow", "PreviewResult", "RunRow", "month_bounds",
]
