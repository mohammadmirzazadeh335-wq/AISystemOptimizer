"""Fiscal periods (دوره‌های مالی) and the closing entry.

Closing a period is a controlled operation:

* every document inside it must already be posted or voided;
* the trial balance of the period must be balanced;
* a closing document (سند اختتامیه) transfers the result of the period to the
  retained-earnings equity account, so no historical row is deleted or rewritten.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, FiscalPeriod, Journal, JournalLine
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService, EventType, SEVERITY_CRITICAL
from pars_erp.services.accounting_common import quantize_money

ZERO = Decimal("0")


@dataclass(frozen=True)
class PeriodInput:
    code: str
    title_fa: str
    start_date: _dt.date
    end_date: _dt.date
    notes: str = ""
    is_active: bool = False


@dataclass(frozen=True)
class PeriodRow:
    id: int
    code: str
    title_fa: str
    start_date: _dt.date
    end_date: _dt.date
    status: str
    status_fa: str
    is_active: bool
    notes: str
    journal_count: int = 0
    posted_count: int = 0
    total_debit: Decimal = ZERO

    @property
    def is_open(self) -> bool:
        return self.status == C.PERIOD_OPEN

    @property
    def label(self) -> str:
        return f"{self.title_fa} ({self.start_date.isoformat()} — {self.end_date.isoformat()})"


class PeriodService:
    def __init__(self, db: Database, audit: AuditService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------ read
    def list_periods(self, ctx: SecurityContext | None) -> list[PeriodRow]:
        require_permission(ctx, "periods.view")
        with self.db.session_scope() as session:
            periods = list(session.execute(
                select(FiscalPeriod).order_by(FiscalPeriod.start_date.desc())).scalars())
            result = []
            for period in periods:
                journal_count = session.execute(
                    select(func.count(Journal.id))
                    .where(Journal.fiscal_period_id == period.id)).scalar() or 0
                posted = session.execute(
                    select(func.count(Journal.id))
                    .where(Journal.fiscal_period_id == period.id,
                           Journal.status == C.STATUS_POSTED)).scalar() or 0
                total_debit = session.execute(
                    select(func.coalesce(func.sum(Journal.total_debit), 0))
                    .where(Journal.fiscal_period_id == period.id,
                           Journal.status == C.STATUS_POSTED)).scalar() or 0
                result.append(PeriodRow(
                    id=period.id, code=period.code, title_fa=period.title_fa,
                    start_date=period.start_date, end_date=period.end_date,
                    status=period.status,
                    status_fa=C.PERIOD_TITLES_FA.get(period.status, period.status),
                    is_active=period.is_active, notes=period.notes or "",
                    journal_count=int(journal_count),
                    posted_count=int(posted), total_debit=Decimal(total_debit)))
            return result

    def get(self, ctx: SecurityContext | None, period_id: int) -> PeriodRow:
        for row in self.list_periods(ctx):
            if row.id == period_id:
                return row
        raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")

    def active_period(self, ctx: SecurityContext | None) -> PeriodRow | None:
        require_permission(ctx, "periods.view")
        for row in self.list_periods(ctx):
            if row.is_active:
                return row
        return None

    def period_for_date(self, ctx: SecurityContext | None, value: _dt.date) -> PeriodRow | None:
        require_permission(ctx, "periods.view")
        for row in self.list_periods(ctx):
            if row.start_date <= value <= row.end_date:
                return row
        return None

    # ----------------------------------------------------------------- write
    def create(self, ctx: SecurityContext | None, data: PeriodInput) -> PeriodRow:
        require_permission(ctx, "periods.create")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            period = FiscalPeriod(**payload)
            session.add(period)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("دوره‌ای با این کد قبلاً تعریف شده است.") from exc
            if period.is_active:
                self._set_active_in(session, period)
            self.audit.log_audit(
                ctx=ctx, entity_type="fiscal_period", entity_id=period.id, action="create",
                summary_fa=f"ایجاد دورهٔ مالی {period.title_fa}",
                after=period.to_dict(), session=session)
        return self.get(ctx, period.id)

    def update(self, ctx: SecurityContext | None, period_id: int,
               data: PeriodInput) -> PeriodRow:
        require_permission(ctx, "periods.create")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            if period.status == C.PERIOD_CLOSED:
                raise ValidationError("دورهٔ بسته‌شده قابل ویرایش نیست؛ ابتدا آن را باز کنید.")
            existing = session.execute(
                select(func.count(Journal.id))
                .where(Journal.fiscal_period_id == period_id)).scalar() or 0
            if existing and (payload["start_date"] != period.start_date
                             or payload["end_date"] != period.end_date):
                raise ValidationError(
                    "این دوره دارای سند است؛ بازهٔ تاریخ آن قابل تغییر نیست.")
            before = period.to_dict()
            for key, value in payload.items():
                setattr(period, key, value)
            if period.is_active:
                self._set_active_in(session, period)
            self.audit.log_audit(
                ctx=ctx, entity_type="fiscal_period", entity_id=period.id, action="update",
                summary_fa=f"ویرایش دورهٔ مالی {period.title_fa}",
                before=before, after=period.to_dict(), session=session)
        return self.get(ctx, period_id)

    def set_active(self, ctx: SecurityContext | None, period_id: int) -> PeriodRow:
        require_permission(ctx, "periods.create")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            self._set_active_in(session, period)
        return self.get(ctx, period_id)

    def close(self, ctx: SecurityContext | None, period_id: int) -> PeriodRow:
        """Close a period after proving it is consistent and fully posted."""
        require_permission(ctx, "periods.close")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            if period.status == C.PERIOD_CLOSED:
                raise ValidationError("این دوره قبلاً بسته شده است.")
            dangling = session.execute(
                select(func.count(Journal.id))
                .where(Journal.fiscal_period_id == period_id,
                       Journal.status.in_((C.STATUS_DRAFT, C.STATUS_PENDING,
                                           C.STATUS_APPROVED)))).scalar() or 0
            if dangling:
                raise ValidationError(
                    f"{dangling} سند در این دوره هنوز نهایی نشده است؛ ابتدا آن‌ها را "
                    "تعیین تکلیف کنید.")
            debit, credit = session.execute(
                select(func.coalesce(func.sum(JournalLine.debit), 0),
                       func.coalesce(func.sum(JournalLine.credit), 0))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .where(Journal.fiscal_period_id == period_id,
                       Journal.status == C.STATUS_POSTED)).first()
            debit, credit = Decimal(debit or 0), Decimal(credit or 0)
            if debit != credit:
                raise ValidationError(
                    "اسناد این دوره تراز نیستند؛ بستن دوره مجاز نیست. "
                    f"(بدهکار {debit} — بستانکار {credit})")
            before = period.to_dict()
            period.status = C.PERIOD_CLOSED
            period.closed_at = utcnow()
            period.closed_by_id = ctx.user_id if ctx else None
            period.is_active = False
            self.audit.log_audit(
                ctx=ctx, entity_type="fiscal_period", entity_id=period.id, action="close",
                summary_fa=f"بستن دورهٔ مالی {period.title_fa}",
                before=before, after=period.to_dict(), session=session)
            self.audit.log_security(
                event_type=EventType.PERIOD_CLOSED,
                message_fa=f"دورهٔ مالی {period.title_fa} بسته شد.",
                severity=SEVERITY_CRITICAL, ctx=ctx,
                details={"period_id": period.id, "debit": str(debit)}, session=session)
        return self.get(ctx, period_id)

    def reopen(self, ctx: SecurityContext | None, period_id: int, reason: str) -> PeriodRow:
        require_permission(ctx, "periods.close")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValidationError("دلیل بازگشایی دوره را (حداقل ۵ نویسه) بنویسید.",
                                  field="reason")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            if period.status != C.PERIOD_CLOSED:
                raise ValidationError("این دوره باز است.")
            before = period.to_dict()
            period.status = C.PERIOD_OPEN
            period.closed_at = None
            period.closed_by_id = None
            self.audit.log_audit(
                ctx=ctx, entity_type="fiscal_period", entity_id=period.id, action="reopen",
                summary_fa=f"بازگشایی دورهٔ مالی {period.title_fa}: {reason}",
                before=before, after=period.to_dict(), session=session)
            self.audit.log_security(
                event_type=EventType.PERIOD_REOPENED,
                message_fa=f"دورهٔ مالی {period.title_fa} بازگشایی شد.",
                severity=SEVERITY_CRITICAL, ctx=ctx,
                details={"period_id": period.id, "reason": reason}, session=session)
        return self.get(ctx, period_id)

    def delete(self, ctx: SecurityContext | None, period_id: int) -> None:
        require_permission(ctx, "periods.create")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            used = session.execute(
                select(func.count(Journal.id))
                .where(Journal.fiscal_period_id == period_id)).scalar() or 0
            if used:
                raise ValidationError("این دوره دارای سند است و قابل حذف نیست.")
            before = period.to_dict()
            session.delete(period)
            self.audit.log_audit(
                ctx=ctx, entity_type="fiscal_period", entity_id=period_id, action="delete",
                summary_fa=f"حذف دورهٔ مالی {before.get('title_fa')}", before=before,
                session=session)

    # -------------------------------------------------------- closing entry
    def create_closing_entry(self, ctx: SecurityContext | None, period_id: int, *,
                             retained_earnings_account_id: int) -> int:
        """Post the closing document that zeroes income/expense accounts.

        Returns the id of the created (posted) journal.
        """
        require_permission(ctx, "periods.close")
        require_permission(ctx, "journals.reverse")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی مورد نظر یافت نشد.")
            if period.status == C.PERIOD_CLOSED:
                raise ValidationError("دوره بسته است؛ پیش از ثبت سند اختتامیه آن را باز کنید.")
            equity = session.get(Account, retained_earnings_account_id)
            if equity is None:
                raise NotFoundError("حساب سود و زیان انباشته یافت نشد.")
            if equity.level != C.LEVEL_SUBSIDIARY or equity.account_type != C.TYPE_EQUITY:
                raise ValidationError(
                    "حساب انتخاب‌شده باید یک حساب معین از نوع سرمایه باشد.",
                    field="retained_earnings_account_id")
            already = session.execute(
                select(Journal).where(Journal.fiscal_period_id == period_id,
                                      Journal.kind == C.KIND_CLOSING)).scalars().first()
            if already is not None:
                raise ConflictError("برای این دوره قبلاً سند اختتامیه ثبت شده است.")

            rows = session.execute(
                select(JournalLine.account_id,
                       func.sum(JournalLine.debit), func.sum(JournalLine.credit))
                .join(Journal, JournalLine.journal_id == Journal.id)
                .join(Account, JournalLine.account_id == Account.id)
                .where(Journal.status == C.STATUS_POSTED,
                       Journal.entry_date <= period.end_date,
                       Account.account_type.in_((C.TYPE_REVENUE, C.TYPE_EXPENSE)),
                       Account.level == C.LEVEL_SUBSIDIARY)
                .group_by(JournalLine.account_id)).all()
            lines: list[JournalLine] = []
            net = ZERO
            index = 1
            for account_id, debit_sum, credit_sum in rows:
                debit_sum, credit_sum = Decimal(debit_sum or 0), Decimal(credit_sum or 0)
                balance = debit_sum - credit_sum      # > 0 => debit balance
                if balance == ZERO:
                    continue
                if balance > 0:      # expense: credit it to zero it out
                    lines.append(JournalLine(
                        line_no=index, account_id=account_id, debit=ZERO,
                        credit=quantize_money(balance, self._base_currency()),
                        description="بستن حساب هزینه"))
                    net -= balance
                else:                # revenue: debit it
                    lines.append(JournalLine(
                        line_no=index, account_id=account_id,
                        debit=quantize_money(-balance, self._base_currency()),
                        credit=ZERO, description="بستن حساب درآمد"))
                    net += -balance
                index += 1
            if not lines:
                raise ValidationError(
                    "در این دوره حساب درآمد یا هزینه‌ای با گردش باقی‌مانده وجود ندارد.")

            if net > 0:
                lines.append(JournalLine(
                    line_no=index, account_id=equity.id, debit=ZERO,
                    credit=quantize_money(net, self._base_currency()),
                    description="انتقال سود دوره به سود و زیان انباشته"))
            elif net < 0:
                lines.append(JournalLine(
                    line_no=index, account_id=equity.id,
                    debit=quantize_money(-net, self._base_currency()), credit=ZERO,
                    description="انتقال زیان دوره به سود و زیان انباشته"))
            else:  # pragma: no cover - defensive; lines always imply a net amount
                raise ValidationError("مانده قابل انتقالی برای اختتامیه وجود ندارد.")

            highest = session.execute(
                select(func.max(Journal.number))
                .where(Journal.fiscal_period_id == period_id)).scalar()
            total_debit = sum((Decimal(line.debit or 0) for line in lines), ZERO)
            total_credit = sum((Decimal(line.credit or 0) for line in lines), ZERO)
            journal = Journal(
                fiscal_period_id=period.id,
                number=int(highest or 0) + 1,
                entry_date=period.end_date,
                registered_at=utcnow(),
                title_fa=f"سند اختتامیه دورهٔ {period.title_fa}",
                status=C.STATUS_POSTED,
                kind=C.KIND_CLOSING,
                currency_code=self._base_currency(),
                exchange_rate=Decimal("1"),
                total_debit=total_debit,
                total_credit=total_credit,
                notes="سند سیستمی اختتامیه؛ نتیجهٔ دوره به سود و زیان انباشته منتقل شد.",
                created_by_id=ctx.user_id if ctx else None,
                posted_by_id=ctx.user_id if ctx else None,
                posted_at=utcnow(),
            )
            journal.lines.extend(lines)
            session.add(journal)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action="closing",
                summary_fa=(f"ثبت سند اختتامیه شماره {journal.number} دورهٔ "
                            f"{period.title_fa}"),
                after={"number": journal.number, "net": str(net)}, session=session)
            return journal.id

    # --------------------------------------------------------------- helpers
    def _validated(self, data: PeriodInput) -> dict:
        code = (data.code or "").strip()
        title = (data.title_fa or "").strip()
        if not code:
            raise ValidationError("کد دوره را وارد کنید.", field="code")
        if len(title) < 2:
            raise ValidationError("عنوان دوره را وارد کنید.", field="title_fa")
        if data.end_date < data.start_date:
            raise ValidationError("تاریخ پایان دوره نباید پیش از تاریخ شروع باشد.",
                                  field="end_date")
        with self.db.session_scope() as session:
            overlap = session.execute(
                select(FiscalPeriod).where(
                    FiscalPeriod.start_date <= data.end_date,
                    FiscalPeriod.end_date >= data.start_date)).scalars().all()
            for period in overlap:
                if period.code != code:
                    raise ValidationError(
                        f"بازهٔ انتخاب‌شده با دورهٔ «{period.title_fa}» هم‌پوشانی دارد.",
                        field="start_date")
        return {
            "code": code,
            "title_fa": title,
            "start_date": data.start_date,
            "end_date": data.end_date,
            "notes": (data.notes or "").strip() or None,
            "is_active": bool(data.is_active),
            "status": C.PERIOD_OPEN,
        }

    @staticmethod
    def _set_active_in(session, period: FiscalPeriod) -> None:
        for other in session.execute(select(FiscalPeriod)).scalars():
            if other.id != period.id and other.is_active:
                other.is_active = False
        period.is_active = True

    def _base_currency(self) -> str:
        if self.settings is None:
            return "IRR"
        try:
            return self.settings.snapshot().currency_code
        except Exception:  # pragma: no cover
            return "IRR"
