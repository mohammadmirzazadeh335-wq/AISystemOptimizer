"""Accounting documents (اسناد حسابداری): lifecycle, validation and traceability.

Invariants enforced here - not in the UI:

* a document always has at least two lines and each line has exactly one of
  debit/credit with a strictly positive amount;
* lines may only reference *active subsidiary* accounts (معین) and details that
  belong to that account;
* the document date must fall inside an **open** fiscal period, both when it is
  saved *and* when it is posted (a period may be closed in between);
* a document can only be posted when debit total == credit total (exact Decimal);
* posted documents are immutable: corrections happen through a reversal document
  that keeps a link (``reverses_journal_id``) to the original;
* every state change is written to the business audit trail with the actor.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.core.money import get_currency
from pars_erp.db.models import (
    Account,
    CostCenter,
    DetailAccount,
    FiscalPeriod,
    Journal,
    JournalLine,
    Project,
)
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.accounting_common import (
    quantize_money,
    resolve_period,
    to_decimal,
)
from pars_erp.services.audit_service import AuditService, EventType, SEVERITY_INFO
from pars_erp.services.common import Page, normalize_page

ZERO = Decimal("0")


# --------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class JournalLineInput:
    account_id: int
    description: str = ""
    debit: Decimal | str | int = 0
    credit: Decimal | str | int = 0
    detail_id: int | None = None
    cost_center_id: int | None = None
    project_id: int | None = None


@dataclass(frozen=True)
class JournalInput:
    entry_date: _dt.date
    title_fa: str
    lines: Sequence[JournalLineInput]
    fiscal_period_id: int | None = None
    reference_no: str = ""
    currency_code: str = "IRR"
    exchange_rate: Decimal | str | None = None
    notes: str = ""
    idempotency_key: str | None = None
    kind: str = C.KIND_NORMAL


# ---------------------------------------------------------------------- rows
@dataclass(frozen=True)
class JournalLineRow:
    line_no: int
    account_id: int
    account_code: str
    account_title: str
    detail_id: int | None
    detail_name: str
    description: str
    debit: Decimal
    credit: Decimal
    cost_center: str
    project: str


@dataclass(frozen=True)
class JournalRow:
    id: int
    number: int
    entry_date: _dt.date
    title_fa: str
    reference_no: str
    status: str
    status_fa: str
    fiscal_period_id: int
    fiscal_period_title: str
    currency_code: str
    exchange_rate: Decimal
    total_debit: Decimal
    total_credit: Decimal
    foreign_total: Decimal
    line_count: int
    created_by_id: int | None
    posted_at: _dt.datetime | None
    void_reason: str
    kind: str
    kind_fa: str
    reverses_journal_id: int | None
    notes: str
    lines: tuple[JournalLineRow, ...] = field(default_factory=tuple)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit

    @property
    def number_fa(self) -> str:
        return f"{self.number:,}"

    @property
    def is_editable(self) -> bool:
        return self.status in C.EDITABLE_STATUSES

    @property
    def can_be_posted(self) -> bool:
        return self.status == C.STATUS_APPROVED and self.is_balanced


@dataclass(frozen=True)
class JournalFilter:
    fiscal_period_id: int | None = None
    status: str | None = None
    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    number: int | None = None
    account_id: int | None = None
    search: str | None = None


#: how often a colliding document number is retried before the user hears about it
_NUMBER_ATTEMPTS = 6


class JournalService:
    def __init__(self, db: Database, audit: AuditService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------ read
    def get(self, ctx: SecurityContext | None, journal_id: int) -> JournalRow:
        require_permission(ctx, "journals.view")
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            return self._row(journal, with_lines=True)

    def list(self, ctx: SecurityContext | None, filters: JournalFilter | None = None,
             *, page: int = 1, page_size: int = 25) -> Page[JournalRow]:
        require_permission(ctx, "journals.view")
        filters = filters or JournalFilter()
        page, page_size = normalize_page(page, page_size)
        with self.db.session_scope() as session:
            query = select(Journal)
            query = self._apply_filters(query, filters)
            total = int(session.execute(
                select(func.count()).select_from(query.subquery())).scalar() or 0)
            rows = session.execute(
                query.order_by(Journal.entry_date.desc(), Journal.number.desc())
                .limit(page_size).offset((page - 1) * page_size)).scalars().all()
            return Page(items=[self._row(j) for j in rows], total=total,
                        page=page, page_size=page_size)

    def next_number(self, ctx: SecurityContext | None, fiscal_period_id: int) -> int:
        require_permission(ctx, "journals.view")
        with self.db.session_scope() as session:
            period = session.get(FiscalPeriod, fiscal_period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی یافت نشد.")
            highest = session.execute(
                select(func.max(Journal.number))
                .where(Journal.fiscal_period_id == fiscal_period_id)).scalar()
            return int(highest or 0) + 1

    def summary(self, ctx: SecurityContext | None) -> dict:
        """Small set of real counters used by the accounting dashboard."""
        require_permission(ctx, "journals.view")
        with self.db.session_scope() as session:
            def count(*conditions) -> int:
                query = select(func.count(Journal.id))
                for condition in conditions:
                    query = query.where(condition)
                return int(session.execute(query).scalar() or 0)

            totals = session.execute(
                select(func.coalesce(func.sum(Journal.total_debit), 0))
                .where(Journal.status == C.STATUS_POSTED)).scalar()
            return {
                "draft": count(Journal.status == C.STATUS_DRAFT),
                "pending": count(Journal.status == C.STATUS_PENDING),
                "approved": count(Journal.status == C.STATUS_APPROVED),
                "posted": count(Journal.status == C.STATUS_POSTED),
                "void": count(Journal.status == C.STATUS_VOID),
                "posted_total": Decimal(totals or 0),
            }

    # ----------------------------------------------------------------- write
    def create(self, ctx: SecurityContext | None, data: JournalInput) -> JournalRow:
        require_permission(ctx, "journals.create")
        key = (data.idempotency_key or "").strip() or None
        if key:
            existing = self._by_idempotency_key(key)
            if existing is not None:
                return existing
        # Two bookkeepers saving at the same moment both read the same "next
        # number"; the unique constraint rejects the loser. Allocating the
        # number again (a few times) turns that into an invisible retry instead
        # of an error the user has to understand.
        last_error: Exception | None = None
        for _attempt in range(_NUMBER_ATTEMPTS):
            try:
                return self._create_once(ctx, data, key)
            except ConflictError as exc:
                last_error = exc
                continue
        raise ConflictError(
            "شمارهٔ سند هم‌زمان توسط کاربر دیگری ثبت شد؛ دوباره تلاش کنید."
        ) from last_error

    def _create_once(self, ctx: SecurityContext | None, data: JournalInput,
                     key: str | None) -> JournalRow:
        with self.db.session_scope() as session:
            period = resolve_period(session, period_id=data.fiscal_period_id,
                                    on_date=data.entry_date)
            prepared = self._prepare(session, data, period)
            journal = Journal(
                fiscal_period_id=period.id,
                number=self._next_number_in(session, period.id),
                entry_date=data.entry_date,
                registered_at=utcnow(),
                title_fa=prepared["title"],
                reference_no=prepared["reference_no"],
                status=C.STATUS_DRAFT,
                kind=data.kind if data.kind in C.JOURNAL_KINDS else C.KIND_NORMAL,
                currency_code=prepared["currency"],
                exchange_rate=prepared["rate"],
                total_debit=prepared["total_debit"],
                total_credit=prepared["total_credit"],
                foreign_total=prepared["foreign_total"],
                notes=prepared["notes"],
                idempotency_key=key,
                created_by_id=ctx.user_id if ctx else None,
            )
            for line in prepared["lines"]:
                journal.lines.append(JournalLine(**line))
            session.add(journal)
            try:
                session.flush()
            except IntegrityError as exc:  # concurrent number clash or duplicate key
                session.rollback()
                current = session.execute(
                    select(Journal).where(Journal.idempotency_key == key)
                ).scalars().first() if key else None
                if current is not None:
                    return self._row(current, with_lines=True)
                raise ConflictError("شمارهٔ سند هم‌زمان رزرو شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action="create",
                summary_fa=f"ایجاد سند شماره {journal.number} — {journal.title_fa}",
                after=self._audit_snapshot(journal), session=session)
            return self._row(journal, with_lines=True)

    def create_posted_system_entry(self, session: Session, *, ctx: SecurityContext | None,
                                   data: JournalInput, source_kind: str,
                                   source_id: int) -> Journal:
        """Create and post a journal entry generated by another module.

        This is the **only** path that bypasses ``journals.create``/``journals.post``:
        it is called from inside the transaction of a commercial document whose own
        permission (e.g. ``sales.post``) was already checked. The entry is created
        and posted in one step so the caller keeps a single atomic transaction and
        an invoice can never exist without its accounting entry (or vice versa).
        The caller must have an open ``session``; the row is flushed, not committed.
        """
        key = (data.idempotency_key or "").strip() or None
        if key:
            existing = session.execute(
                select(Journal).where(Journal.idempotency_key == key)).scalars().first()
            if existing is not None:
                return existing
        period = resolve_period(session, period_id=data.fiscal_period_id,
                                on_date=data.entry_date)
        if period.status == C.PERIOD_CLOSED:
            raise ValidationError(
                f"دورهٔ «{period.title_fa}» بسته است؛ ثبت خودکار سند مجاز نیست.")
        prepared = self._prepare(session, data, period)
        journal = Journal(
            fiscal_period_id=period.id,
            number=self._next_number_in(session, period.id),
            entry_date=data.entry_date,
            registered_at=utcnow(),
            title_fa=prepared["title"],
            reference_no=prepared["reference_no"],
            status=C.STATUS_POSTED,
            kind=C.KIND_NORMAL,
            currency_code=prepared["currency"],
            exchange_rate=prepared["rate"],
            total_debit=prepared["total_debit"],
            total_credit=prepared["total_credit"],
            foreign_total=prepared["foreign_total"],
            notes=prepared["notes"],
            idempotency_key=key,
            source_kind=source_kind,
            source_id=source_id,
            posted_at=utcnow(),
            posted_by_id=ctx.user_id if ctx else None,
            created_by_id=ctx.user_id if ctx else None,
        )
        for line in prepared["lines"]:
            journal.lines.append(JournalLine(**line))
        session.add(journal)
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="journal", entity_id=journal.id, action="post",
            summary_fa=(f"ثبت خودکار سند شماره {journal.number} از {source_kind} "
                        f"#{source_id} — {journal.title_fa}"),
            after={"number": journal.number, "total_debit": str(journal.total_debit),
                   "source_kind": source_kind, "source_id": source_id},
            session=session)
        return journal

    def update_draft(self, ctx: SecurityContext | None, journal_id: int,
                     data: JournalInput) -> JournalRow:
        require_permission(ctx, "journals.edit_draft")
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            if journal.status not in C.EDITABLE_STATUSES:
                raise ValidationError(
                    f"سند در وضعیت «{C.STATUS_TITLES_FA[journal.status]}» قابل ویرایش نیست.")
            before = self._audit_snapshot(journal)
            period = resolve_period(session, period_id=data.fiscal_period_id,
                                    on_date=data.entry_date)
            prepared = self._prepare(session, data, period)
            journal.fiscal_period_id = period.id
            journal.entry_date = data.entry_date
            journal.title_fa = prepared["title"]
            journal.reference_no = prepared["reference_no"]
            journal.currency_code = prepared["currency"]
            journal.exchange_rate = prepared["rate"]
            journal.total_debit = prepared["total_debit"]
            journal.total_credit = prepared["total_credit"]
            journal.foreign_total = prepared["foreign_total"]
            if prepared["notes"]:
                journal.notes = prepared["notes"]
            journal.updated_by_id = ctx.user_id if ctx else None
            journal.lines.clear()
            session.flush()
            for line_no, line in enumerate(prepared["lines"]):
                line["line_no"] = line_no + 1
                journal.lines.append(JournalLine(**line))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action="update",
                summary_fa=f"ویرایش پیش‌نویس سند شماره {journal.number}",
                before=before, after=self._audit_snapshot(journal), session=session)
            return self._row(journal, with_lines=True)

    def delete_draft(self, ctx: SecurityContext | None, journal_id: int) -> None:
        require_permission(ctx, "journals.delete_draft")
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            if journal.status != C.STATUS_DRAFT:
                raise ValidationError(
                    "فقط پیش‌نویس قابل حذف است؛ برای سند ثبت‌شده از ابطال استفاده کنید.")
            snapshot = self._audit_snapshot(journal)
            number = journal.number
            journal.lines.clear()
            session.delete(journal)
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal_id, action="delete",
                summary_fa=f"حذف پیش‌نویس سند شماره {number}", before=snapshot,
                session=session)

    def duplicate(self, ctx: SecurityContext | None, journal_id: int,
                  *, entry_date: _dt.date | None = None) -> JournalRow:
        require_permission(ctx, "journals.create")
        source = self.get(ctx, journal_id)
        target_date = entry_date or source.entry_date
        return self.create(ctx, JournalInput(
            entry_date=target_date,
            title_fa=f"{source.title_fa} (کپی)",
            lines=[JournalLineInput(
                account_id=line.account_id, description=line.description,
                debit=line.debit, credit=line.credit, detail_id=line.detail_id,
                cost_center_id=None, project_id=None) for line in source.lines],
            reference_no=source.reference_no, currency_code=source.currency_code,
            exchange_rate=source.exchange_rate, notes=source.notes,
        ))

    # ------------------------------------------------------------ transitions
    def submit(self, ctx: SecurityContext | None, journal_id: int) -> JournalRow:
        require_permission(ctx, "journals.submit")
        return self._transition(ctx, journal_id, C.STATUS_PENDING, "submit",
                                "ارسال سند برای تأیید")

    def approve(self, ctx: SecurityContext | None, journal_id: int) -> JournalRow:
        require_permission(ctx, "journals.approve")
        return self._transition(ctx, journal_id, C.STATUS_APPROVED, "approve", "تأیید سند")

    def return_to_draft(self, ctx: SecurityContext | None, journal_id: int,
                        *, reason: str = "") -> JournalRow:
        require_permission(ctx, "journals.edit_draft")
        return self._transition(ctx, journal_id, C.STATUS_DRAFT, "return",
                                "بازگرداندن سند به پیش‌نویس", reason=reason)

    def post(self, ctx: SecurityContext | None, journal_id: int) -> JournalRow:
        require_permission(ctx, "journals.post")
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            if journal.status == C.STATUS_POSTED:
                raise ValidationError("این سند قبلاً ثبت نهایی شده است.")
            if journal.status == C.STATUS_VOID:
                raise ValidationError("سند باطل‌شده قابل ثبت نهایی نیست.")
            self._assert_transition(journal.status, C.STATUS_POSTED)
            if len(journal.lines) < 2:
                raise ValidationError("سند باید حداقل دو ردیف داشته باشد.")
            total_debit = sum((Decimal(line.debit or 0) for line in journal.lines), ZERO)
            total_credit = sum((Decimal(line.credit or 0) for line in journal.lines), ZERO)
            if total_debit != total_credit:
                raise ValidationError(
                    "جمع بدهکار و بستانکار سند برابر نیست؛ ثبت نهایی مجاز نیست. "
                    f"(اختلاف: {total_debit - total_credit})")
            period = session.get(FiscalPeriod, journal.fiscal_period_id)
            if period is None:
                raise NotFoundError("دورهٔ مالی سند یافت نشد.")
            if period.status == C.PERIOD_CLOSED:
                raise ValidationError(
                    f"دورهٔ «{period.title_fa}» بسته است؛ ثبت نهایی سند مجاز نیست.")
            if not period.contains(journal.entry_date):
                raise ValidationError("تاریخ سند خارج از دورهٔ مالی است.")
            journal.total_debit = quantize_money(total_debit, self._base_currency())
            journal.total_credit = quantize_money(total_credit, self._base_currency())
            journal.status = C.STATUS_POSTED
            journal.posted_by_id = ctx.user_id if ctx else None
            journal.posted_at = utcnow()
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action="post",
                summary_fa=f"ثبت نهایی سند شماره {journal.number} — {journal.title_fa}",
                after=self._audit_snapshot(journal), session=session)
            self.audit.log_security(
                event_type=EventType.JOURNAL_POSTED,
                message_fa=f"سند شماره {journal.number} ثبت نهایی شد.",
                ctx=ctx, details={"journal_id": journal.id, "number": journal.number,
                                  "total": str(journal.total_debit)},
                session=session)
            return self._row(journal, with_lines=True)

    def void(self, ctx: SecurityContext | None, journal_id: int, reason: str) -> JournalRow:
        require_permission(ctx, "journals.void")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValidationError("برای ابطال سند، دلیل ابطال را (حداقل ۵ نویسه) بنویسید.",
                                  field="void_reason")
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            if journal.status == C.STATUS_VOID:
                raise ValidationError("این سند قبلاً باطل شده است.")
            if journal.status != C.STATUS_POSTED:
                raise ValidationError(
                    "فقط سند ثبت‌نهایی‌شده باطل می‌شود؛ برای پیش‌نویس از حذف استفاده کنید.")
            period = session.get(FiscalPeriod, journal.fiscal_period_id)
            if period is not None and period.status == C.PERIOD_CLOSED:
                # voiding a posted entry removes it from the ledger; doing that to a
                # closed period would silently rewrite statements that were already
                # reported. The correction belongs in an open period instead.
                raise ValidationError(
                    f"دورهٔ مالی «{period.title_fa}» بسته شده است؛ ابطال سند آن مجاز نیست. "
                    "برای اصلاح، سند معکوس در دورهٔ جاری ثبت کنید.")
            before = self._audit_snapshot(journal)
            journal.status = C.STATUS_VOID
            journal.voided_by_id = ctx.user_id if ctx else None
            journal.voided_at = utcnow()
            journal.void_reason = reason
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action="void",
                summary_fa=f"ابطال سند شماره {journal.number}: {reason}",
                before=before, after=self._audit_snapshot(journal), session=session)
            self.audit.log_security(
                event_type=EventType.JOURNAL_VOIDED,
                message_fa=f"سند شماره {journal.number} باطل شد.",
                severity=SEVERITY_INFO, ctx=ctx,
                details={"journal_id": journal.id, "reason": reason}, session=session)
            return self._row(journal, with_lines=True)

    def reverse(self, ctx: SecurityContext | None, journal_id: int, *,
                entry_date: _dt.date | None = None, reason: str = "") -> JournalRow:
        """Create the mirror document of a posted entry (سند معکوس)."""
        require_permission(ctx, "journals.reverse")
        with self.db.session_scope() as session:
            source = session.get(Journal, journal_id)
            if source is None:
                raise NotFoundError("سند مبدأ یافت نشد.")
            if source.status != C.STATUS_POSTED:
                raise ValidationError("فقط سند ثبت‌نهایی‌شده قابل معکوس‌سازی است.")
            existing = session.execute(
                select(Journal).where(Journal.reverses_journal_id == source.id,
                                      Journal.status == C.STATUS_POSTED)).scalars().first()
            if existing is not None:
                raise ConflictError(
                    f"برای این سند قبلاً سند معکوس شماره {existing.number} ثبت شده است.")
            target_date = entry_date or source.entry_date
            period = resolve_period(session, on_date=target_date)
            lines = [JournalLine(
                line_no=index + 1,
                account_id=line.account_id,
                detail_id=line.detail_id,
                cost_center_id=line.cost_center_id,
                project_id=line.project_id,
                description=line.description,
                debit=line.credit,
                credit=line.debit,
                foreign_amount=-Decimal(line.foreign_amount or 0),
            ) for index, line in enumerate(source.lines)]
            mirror = Journal(
                fiscal_period_id=period.id,
                number=self._next_number_in(session, period.id),
                entry_date=target_date,
                registered_at=utcnow(),
                title_fa=f"سند معکوس شماره {source.number}"
                         + (f" — {reason.strip()}" if reason.strip() else ""),
                reference_no=str(source.number),
                status=C.STATUS_POSTED,
                currency_code=source.currency_code,
                exchange_rate=source.exchange_rate,
                total_debit=source.total_credit,
                total_credit=source.total_debit,
                foreign_total=-Decimal(source.foreign_total or 0),
                notes=reason.strip() or None,
                reverses_journal_id=source.id,
                created_by_id=ctx.user_id if ctx else None,
                posted_by_id=ctx.user_id if ctx else None,
                posted_at=utcnow(),
            )
            mirror.lines.extend(lines)
            session.add(mirror)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=mirror.id, action="reverse",
                summary_fa=(f"ثبت سند معکوس شماره {mirror.number} برای سند "
                            f"شماره {source.number}"),
                after=self._audit_snapshot(mirror), session=session)
            return self._row(mirror, with_lines=True)

    # --------------------------------------------------------------- internals
    def _transition(self, ctx, journal_id: int, target: str, action: str,
                    label: str, *, reason: str = "") -> JournalRow:
        with self.db.session_scope() as session:
            journal = session.get(Journal, journal_id)
            if journal is None:
                raise NotFoundError("سند حسابداری مورد نظر یافت نشد.")
            self._assert_transition(journal.status, target)
            if target in (C.STATUS_PENDING, C.STATUS_APPROVED):
                debit = sum((Decimal(line.debit or 0) for line in journal.lines), ZERO)
                credit = sum((Decimal(line.credit or 0) for line in journal.lines), ZERO)
                if debit != credit:
                    raise ValidationError(
                        "سند نامتوازن است و نمی‌تواند به مرحلهٔ بعد برود.")
                if len(journal.lines) < 2:
                    raise ValidationError("سند باید حداقل دو ردیف داشته باشد.")
            before = self._audit_snapshot(journal)
            journal.status = target
            now = utcnow()
            if target == C.STATUS_PENDING:
                journal.submitted_by_id = ctx.user_id if ctx else None
                journal.submitted_at = now
            elif target == C.STATUS_APPROVED:
                journal.approved_by_id = ctx.user_id if ctx else None
                journal.approved_at = now
            elif target == C.STATUS_DRAFT:
                journal.submitted_by_id = None
                journal.submitted_at = None
                journal.approved_by_id = None
                journal.approved_at = None
                if reason.strip():
                    journal.notes = ((journal.notes or "") + f"\nبازگشت: {reason.strip()}").strip()
            self.audit.log_audit(
                ctx=ctx, entity_type="journal", entity_id=journal.id, action=action,
                summary_fa=f"{label} — سند شماره {journal.number}",
                before=before, after=self._audit_snapshot(journal), session=session)
            return self._row(journal, with_lines=True)

    @staticmethod
    def _assert_transition(current: str, target: str) -> None:
        allowed = C.ALLOWED_TRANSITIONS.get(current, ())
        if target not in allowed:
            raise ValidationError(
                f"تغییر وضعیت از «{C.STATUS_TITLES_FA.get(current, current)}» به "
                f"«{C.STATUS_TITLES_FA.get(target, target)}» مجاز نیست.")

    def _prepare(self, session: Session, data: JournalInput,
                 period: FiscalPeriod) -> dict:
        title = (data.title_fa or "").strip()
        if len(title) < 3:
            raise ValidationError("شرح سند باید حداقل سه نویسه باشد.", field="title_fa")
        if len(title) > 300:
            raise ValidationError("شرح سند بیش از حد مجاز طولانی است.", field="title_fa")
        lines = list(data.lines or ())
        if len(lines) < 2:
            raise ValidationError("سند حسابداری باید حداقل دو ردیف داشته باشد.")

        base_currency = self._base_currency()
        currency = (data.currency_code or base_currency).strip().upper()
        get_currency(currency)  # validates the code
        rate = to_decimal(data.exchange_rate if data.exchange_rate not in (None, "") else "1",
                          field="exchange_rate")
        if rate <= 0:
            raise ValidationError("نرخ تبدیل ارز باید بزرگ‌تر از صفر باشد.",
                                  field="exchange_rate")
        foreign_mode = currency != base_currency

        prepared_lines: list[dict] = []
        total_debit = ZERO
        total_credit = ZERO
        foreign_total = ZERO
        for index, line in enumerate(lines, start=1):
            account = session.get(Account, line.account_id)
            if account is None:
                raise ValidationError(f"ردیف {index}: حساب انتخاب نشده است.",
                                      field="account_id")
            if account.level != C.LEVEL_SUBSIDIARY:
                raise ValidationError(
                    f"ردیف {index}: تنها حساب معین قابل استفاده در سند است "
                    f"(«{account.title_fa}» از سطح {C.LEVEL_TITLES_FA[account.level]} است).",
                    field="account_id")
            if not account.is_active:
                raise ValidationError(
                    f"ردیف {index}: حساب «{account.code} - {account.title_fa}» غیرفعال است.",
                    field="account_id")
            debit = to_decimal(line.debit, field="debit")
            credit = to_decimal(line.credit, field="credit")
            if (debit > 0) == (credit > 0):
                raise ValidationError(
                    f"ردیف {index}: هر ردیف باید فقط یکی از مبلغ بدهکار یا بستانکار "
                    "را داشته باشد.", field="debit")
            amount = debit if debit > 0 else credit
            if foreign_mode:
                base_amount = quantize_money(amount * rate, base_currency)
                foreign_amount = quantize_money(amount, currency)
                if debit > 0:
                    debit, credit = base_amount, ZERO
                else:
                    debit, credit = ZERO, base_amount
            else:
                base_amount = quantize_money(amount, currency)
                foreign_amount = base_amount
                if debit > 0:
                    debit, credit = base_amount, ZERO
                else:
                    debit, credit = ZERO, base_amount

            detail = None
            if line.detail_id is not None:
                detail = session.get(DetailAccount, line.detail_id)
                if detail is None:
                    raise ValidationError(f"ردیف {index}: حساب تفصیلی یافت نشد.",
                                          field="detail_id")
                if not detail.is_active:
                    raise ValidationError(
                        f"ردیف {index}: حساب تفصیلی «{detail.name}» غیرفعال است.",
                        field="detail_id")
                if detail.account_id and detail.account_id != account.id:
                    raise ValidationError(
                        f"ردیف {index}: حساب تفصیلی «{detail.name}» به حساب "
                        f"«{account.title_fa}» تعلق ندارد.", field="detail_id")
            cost_center_id = self._optional_id(session, CostCenter, line.cost_center_id,
                                               "مرکز هزینه", index)
            project_id = self._optional_id(session, Project, line.project_id, "پروژه", index)

            description = (line.description or "").strip()
            if len(description) > 300:
                raise ValidationError(f"ردیف {index}: شرح ردیف بیش از حد طولانی است.",
                                      field="description")
            total_debit += debit
            total_credit += credit
            foreign_total += (foreign_amount if debit > 0 else -foreign_amount)
            prepared_lines.append({
                "line_no": index,
                "account_id": account.id,
                "detail_id": detail.id if detail else None,
                "cost_center_id": cost_center_id,
                "project_id": project_id,
                "description": description or None,
                "debit": debit,
                "credit": credit,
                "foreign_amount": (foreign_amount if debit > 0 else -foreign_amount),
            })

        totals_note = ""
        if total_debit != total_credit:
            difference = total_debit - total_credit
            if foreign_mode and abs(difference) <= Decimal("0.05") * max(1, len(prepared_lines)):
                # rounding of the rate conversion: settle on the largest line
                adjust = self._largest_line(prepared_lines, total_debit > total_credit)
                if adjust is not None:
                    if total_debit > total_credit:
                        adjust["credit"] = quantize_money(
                            Decimal(adjust["credit"]) + difference, base_currency)
                    else:
                        adjust["debit"] = quantize_money(
                            Decimal(adjust["debit"]) - difference, base_currency)
                    total_debit = sum((Decimal(item["debit"]) for item in prepared_lines), ZERO)
                    total_credit = sum((Decimal(item["credit"]) for item in prepared_lines), ZERO)
                    totals_note = ("اختلاف گرد کردن ناشی از تبدیل ارز روی بزرگ‌ترین ردیف "
                                   "اعمال شد.")
            if total_debit != total_credit:
                raise ValidationError(
                    "جمع بدهکار و بستانکار سند برابر نیست؛ سند متوازن لازم است. "
                    f"(بدهکار: {total_debit} — بستانکار: {total_credit})")

        notes = (data.notes or "").strip()
        if totals_note:
            notes = (notes + "\n" + totals_note).strip()
        return {
            "title": title,
            "reference_no": (data.reference_no or "").strip() or None,
            "currency": currency,
            "rate": rate,
            "lines": prepared_lines,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "foreign_total": foreign_total,
            "notes": notes or None,
            "period": period,
        }

    @staticmethod
    def _largest_line(lines: list[dict], debit_side: bool) -> dict | None:
        candidates = [line for line in lines if Decimal(line["debit" if debit_side else "credit"]) > 0]
        if not candidates:
            return None
        key = "debit" if debit_side else "credit"
        return max(candidates, key=lambda line: Decimal(line[key]))

    @staticmethod
    def _optional_id(session: Session, model, value: int | None, label: str,
                     index: int) -> int | None:
        if value in (None, 0, ""):
            return None
        record = session.get(model, int(value))
        if record is None:
            raise ValidationError(f"ردیف {index}: {label} یافت نشد.")
        if hasattr(record, "is_active") and not record.is_active:
            raise ValidationError(f"ردیف {index}: {label} غیرفعال است.")
        return record.id

    @staticmethod
    def _next_number_in(session: Session, period_id: int) -> int:
        highest = session.execute(
            select(func.max(Journal.number))
            .where(Journal.fiscal_period_id == period_id)).scalar()
        return int(highest or 0) + 1

    def _by_idempotency_key(self, key: str) -> JournalRow | None:
        with self.db.session_scope() as session:
            journal = session.execute(
                select(Journal).where(Journal.idempotency_key == key)).scalars().first()
            return self._row(journal, with_lines=True) if journal else None

    def _base_currency(self) -> str:
        if self.settings is None:
            return "IRR"
        try:
            return self.settings.snapshot().currency_code
        except Exception:  # pragma: no cover - defensive
            return "IRR"

    @staticmethod
    def _apply_filters(query: Select, filters: JournalFilter) -> Select:
        if filters.fiscal_period_id:
            query = query.where(Journal.fiscal_period_id == filters.fiscal_period_id)
        if filters.status:
            query = query.where(Journal.status == filters.status)
        if filters.date_from:
            query = query.where(Journal.entry_date >= filters.date_from)
        if filters.date_to:
            query = query.where(Journal.entry_date <= filters.date_to)
        if filters.number:
            query = query.where(Journal.number == int(filters.number))
        if filters.account_id:
            query = query.where(Journal.id.in_(
                select(JournalLine.journal_id)
                .where(JournalLine.account_id == int(filters.account_id))))
        if filters.search:
            needle = f"%{filters.search.strip()}%"
            query = query.where(or_(Journal.title_fa.like(needle),
                                    Journal.reference_no.like(needle)))
        return query

    @staticmethod
    def _row(journal: Journal, *, with_lines: bool = False) -> JournalRow:
        lines: tuple[JournalLineRow, ...] = ()
        if with_lines:
            lines = tuple(
                JournalLineRow(
                    line_no=line.line_no,
                    account_id=line.account_id,
                    account_code=line.account.code if line.account else "",
                    account_title=line.account.title_fa if line.account else "",
                    detail_id=line.detail_id,
                    detail_name=line.detail.name if line.detail else "",
                    description=line.description or "",
                    debit=Decimal(line.debit or 0),
                    credit=Decimal(line.credit or 0),
                    cost_center=line.cost_center.title_fa if line.cost_center else "",
                    project=line.project.title_fa if line.project else "",
                )
                for line in sorted(journal.lines, key=lambda item: item.line_no))
        return JournalRow(
            id=journal.id,
            number=journal.number,
            entry_date=journal.entry_date,
            title_fa=journal.title_fa,
            reference_no=journal.reference_no or "",
            status=journal.status,
            status_fa=C.STATUS_TITLES_FA.get(journal.status, journal.status),
            fiscal_period_id=journal.fiscal_period_id,
            fiscal_period_title=(journal.fiscal_period.title_fa
                                 if journal.fiscal_period else ""),
            currency_code=journal.currency_code,
            exchange_rate=Decimal(journal.exchange_rate or 1),
            total_debit=Decimal(journal.total_debit or 0),
            total_credit=Decimal(journal.total_credit or 0),
            foreign_total=Decimal(journal.foreign_total or 0),
            line_count=len(journal.lines),
            created_by_id=journal.created_by_id,
            posted_at=journal.posted_at,
            void_reason=journal.void_reason or "",
            kind=journal.kind,
            kind_fa=C.KIND_TITLES_FA.get(journal.kind, journal.kind),
            reverses_journal_id=journal.reverses_journal_id,
            notes=journal.notes or "",
            lines=lines,
        )

    @staticmethod
    def _audit_snapshot(journal: Journal) -> dict:
        return {
            "id": journal.id,
            "number": journal.number,
            "entry_date": journal.entry_date.isoformat(),
            "title_fa": journal.title_fa,
            "status": journal.status,
            "total_debit": str(journal.total_debit or 0),
            "total_credit": str(journal.total_credit or 0),
            "lines": [
                {"account_id": line.account_id, "debit": str(line.debit or 0),
                 "credit": str(line.credit or 0),
                 "detail_id": line.detail_id}
                for line in sorted(journal.lines, key=lambda item: item.line_no)
            ],
        }

    @staticmethod
    def new_idempotency_key() -> str:
        """Convenience for callers that want a stable per-submission key."""
        return uuid.uuid4().hex
