"""Optional reporting dimensions (مراکز هزینه، پروژه‌ها) and currency rates.

Dimensions never block normal bookkeeping: a journal line may carry none of them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.core.money import CURRENCIES
from pars_erp.db.models import CostCenter, CurrencyRate, JournalLine, Project
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.accounting_common import to_decimal


@dataclass(frozen=True)
class DimensionInput:
    code: str
    title_fa: str
    kind: str = ""
    description: str = ""
    is_active: bool = True
    status: str = C.PROJECT_ACTIVE
    start_date: _dt.date | None = None
    end_date: _dt.date | None = None


@dataclass(frozen=True)
class DimensionRow:
    id: int
    code: str
    title_fa: str
    kind: str
    description: str
    is_active: bool
    status: str = C.PROJECT_ACTIVE
    start_date: _dt.date | None = None
    end_date: _dt.date | None = None

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"

    @property
    def status_fa(self) -> str:
        if not self.is_active:
            return "غیرفعال"
        return C.PROJECT_STATUS_TITLES_FA.get(self.status, "فعال")


@dataclass(frozen=True)
class CurrencyRateRow:
    id: int
    currency_code: str
    rate_date: _dt.date
    rate: Decimal
    note: str


class DimensionService:
    """Cost centers and projects share the same shape, so they share this service."""

    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------ cost centers
    def list_cost_centers(self, ctx: SecurityContext | None, *, active: bool | None = None,
                          search: str | None = None) -> list[DimensionRow]:
        require_permission(ctx, "dimensions.view")
        query = select(CostCenter).order_by(CostCenter.code)
        if active is not None:
            query = query.where(CostCenter.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(CostCenter.code.like(needle),
                                    CostCenter.title_fa.like(needle)))
        with self.db.session_scope() as session:
            return [self._row(item) for item in session.execute(query).scalars()]

    def create_cost_center(self, ctx: SecurityContext | None,
                           data: DimensionInput) -> DimensionRow:
        require_permission(ctx, "dimensions.edit")
        with self.db.session_scope() as session:
            item = CostCenter(code=data.code.strip(), title_fa=data.title_fa.strip(),
                              kind=(data.kind or "").strip() or None,
                              description=(data.description or "").strip() or None,
                              is_active=bool(data.is_active))
            session.add(item)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("مرکز هزینه‌ای با این کد وجود دارد.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="cost_center", entity_id=item.id, action="create",
                summary_fa=f"ایجاد مرکز هزینه {item.code} — {item.title_fa}",
                after=item.to_dict(), session=session)
            return self._row(item)

    def update_cost_center(self, ctx: SecurityContext | None, item_id: int,
                           data: DimensionInput) -> DimensionRow:
        require_permission(ctx, "dimensions.edit")
        with self.db.session_scope() as session:
            item = session.get(CostCenter, item_id)
            if item is None:
                raise NotFoundError("مرکز هزینه یافت نشد.")
            before = item.to_dict()
            item.code = data.code.strip()
            item.title_fa = data.title_fa.strip()
            item.kind = (data.kind or "").strip() or None
            item.description = (data.description or "").strip() or None
            item.is_active = bool(data.is_active)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("مرکز هزینه‌ای با این کد وجود دارد.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="cost_center", entity_id=item.id, action="update",
                summary_fa=f"ویرایش مرکز هزینه {item.code}", before=before,
                after=item.to_dict(), session=session)
            return self._row(item)

    # ---------------------------------------------------------------- projects
    def list_projects(self, ctx: SecurityContext | None, *, active: bool | None = None,
                      search: str | None = None) -> list[DimensionRow]:
        require_permission(ctx, "dimensions.view")
        query = select(Project).order_by(Project.code)
        if active is not None:
            query = query.where(Project.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Project.code.like(needle), Project.title_fa.like(needle)))
        with self.db.session_scope() as session:
            return [self._row(item) for item in session.execute(query).scalars()]

    def create_project(self, ctx: SecurityContext | None, data: DimensionInput) -> DimensionRow:
        require_permission(ctx, "dimensions.edit")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            item = Project(**payload)
            session.add(item)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("پروژه‌ای با این کد وجود دارد.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="project", entity_id=item.id, action="create",
                summary_fa=f"ایجاد پروژه {item.code} — {item.title_fa}",
                after=item.to_dict(), session=session)
            return self._row(item)

    def update_project(self, ctx: SecurityContext | None, item_id: int,
                       data: DimensionInput) -> DimensionRow:
        require_permission(ctx, "dimensions.edit")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            item = session.get(Project, item_id)
            if item is None:
                raise NotFoundError("پروژه یافت نشد.")
            before = item.to_dict()
            for key, value in payload.items():
                setattr(item, key, value)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("پروژه‌ای با این کد وجود دارد.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="project", entity_id=item.id, action="update",
                summary_fa=f"ویرایش پروژه {item.code}", before=before,
                after=item.to_dict(), session=session)
            return self._row(item)

    # ------------------------------------------------------------------ usage
    def usage(self, ctx: SecurityContext | None, dimension: str, item_id: int) -> int:
        require_permission(ctx, "dimensions.view")
        column = (JournalLine.cost_center_id if dimension == "cost_center"
                  else JournalLine.project_id)
        with self.db.session_scope() as session:
            return int(session.execute(
                select(func.count(JournalLine.id)).where(column == item_id)).scalar() or 0)

    def choices(self, ctx: SecurityContext | None, dimension: str) -> list[tuple[int, str]]:
        require_permission(ctx, "dimensions.view")
        rows = (self.list_cost_centers(ctx, active=True) if dimension == "cost_center"
                else self.list_projects(ctx, active=True))
        return [(row.id, row.display) for row in rows]

    # --------------------------------------------------------------- helpers
    def _validated(self, data: DimensionInput) -> dict:
        code = (data.code or "").strip()
        title = (data.title_fa or "").strip()
        if not code:
            raise ValidationError("کد را وارد کنید.", field="code")
        if len(title) < 2:
            raise ValidationError("عنوان را کامل وارد کنید.", field="title_fa")
        if data.status not in C.PROJECT_STATUS_TITLES_FA:
            raise ValidationError("وضعیت پروژه نامعتبر است.", field="status")
        if data.start_date and data.end_date and data.end_date < data.start_date:
            raise ValidationError("تاریخ پایان نباید پیش از شروع باشد.", field="end_date")
        return {
            "code": code, "title_fa": title, "status": data.status,
            "start_date": data.start_date, "end_date": data.end_date,
            "description": (data.description or "").strip() or None,
            "is_active": bool(data.is_active),
        }

    @staticmethod
    def _row(item) -> DimensionRow:
        return DimensionRow(
            id=item.id, code=item.code, title_fa=item.title_fa,
            kind=getattr(item, "kind", "") or "",
            description=item.description or "",
            is_active=item.is_active,
            status=getattr(item, "status", C.PROJECT_ACTIVE),
            start_date=getattr(item, "start_date", None),
            end_date=getattr(item, "end_date", None))


class CurrencyService:
    """Exchange-rate snapshots; documents keep the rate they were saved with."""

    def __init__(self, db: Database, audit: AuditService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    def base_currency(self) -> str:
        if self.settings is None:
            return "IRR"
        try:
            return self.settings.snapshot().currency_code
        except Exception:  # pragma: no cover
            return "IRR"

    def rates(self, ctx: SecurityContext | None,
              currency_code: str | None = None) -> list[CurrencyRateRow]:
        require_permission(ctx, "accounts.view")
        query = select(CurrencyRate).order_by(CurrencyRate.rate_date.desc())
        if currency_code:
            query = query.where(CurrencyRate.currency_code == currency_code)
        with self.db.session_scope() as session:
            return [CurrencyRateRow(id=item.id, currency_code=item.currency_code,
                                    rate_date=item.rate_date, rate=Decimal(item.rate),
                                    note=item.note or "")
                    for item in session.execute(query).scalars()]

    def set_rate(self, ctx: SecurityContext | None, currency_code: str, rate_date: _dt.date,
                 rate, note: str = "") -> CurrencyRateRow:
        require_permission(ctx, "accounting.settings")
        code = (currency_code or "").strip().upper()
        if code not in CURRENCIES:
            raise ValidationError("ارز انتخاب‌شده پشتیبانی نمی‌شود.", field="currency_code")
        if code == self.base_currency():
            raise ValidationError("برای ارز پایه نیازی به ثبت نرخ نیست.",
                                  field="currency_code")
        value = to_decimal(rate, field="rate", allow_zero=False)
        with self.db.session_scope() as session:
            item = session.execute(
                select(CurrencyRate).where(CurrencyRate.currency_code == code,
                                           CurrencyRate.rate_date == rate_date)).scalars().first()
            if item is None:
                item = CurrencyRate(currency_code=code, rate_date=rate_date, rate=value,
                                    note=(note or "").strip() or None)
                session.add(item)
            else:
                item.rate = value
                item.note = (note or "").strip() or None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="currency_rate", entity_id=item.id, action="update",
                summary_fa=f"ثبت نرخ {code} برای {rate_date.isoformat()}: {value}",
                after={"currency": code, "date": rate_date.isoformat(), "rate": str(value)},
                session=session)
            return CurrencyRateRow(id=item.id, currency_code=item.currency_code,
                                   rate_date=item.rate_date, rate=Decimal(item.rate),
                                   note=item.note or "")

    def rate_for(self, ctx: SecurityContext | None, currency_code: str,
                 on_date: _dt.date) -> Decimal | None:
        require_permission(ctx, "accounts.view")
        with self.db.session_scope() as session:
            item = session.execute(
                select(CurrencyRate)
                .where(CurrencyRate.currency_code == currency_code.upper(),
                       CurrencyRate.rate_date <= on_date)
                .order_by(CurrencyRate.rate_date.desc())).scalars().first()
            return Decimal(item.rate) if item else None

    def currency_choices(self) -> list[tuple[str, str]]:
        base = self.base_currency()
        return [(code, f"{cur.name_fa}{' (پایه)' if code == base else ''}")
                for code, cur in CURRENCIES.items()]
