"""Cheque books, received cheques and issued cheques.

Every status change appends a :class:`ChequeEvent` row *and*, where money moves,
posts exactly one journal entry:

=====================  =====================================================
transition             ledger effect
=====================  =====================================================
received cheque born    Dr cheques-in-hand / Cr receivable (party)  [receipt]
collected               Dr bank / Cr cheques-in-hand
bounced                 Dr receivable (party) / Cr cheques-in-hand
issued cheque born      Dr payable (party) / Cr cheques-payable     [payment]
paid (cleared)          Dr cheques-payable / Cr bank
=====================  =====================================================

The service refuses any other transition, so a cheque cannot jump from
"received" to "paid" and history can never be rewritten.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.db.models import (
    BankAccount,
    Cheque,
    ChequeBook,
    ChequeEvent,
    DetailAccount,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import (
    ZERO,
    clean_text,
    get_or_404,
    to_money,
)
from pars_erp.services.treasury_common import (
    fund_account_id,
    party_hint_account,
    post_system_journal,
    resolve_fund,
)
from pars_erp.treasury import constants as TC

MONEY = Decimal("0.01")


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class ChequeBookRow:
    id: int
    bank_account_id: int
    bank_label: str
    serial_no: str
    first_no: int
    last_no: int
    received_date: _dt.date
    status: str
    status_fa: str
    note: str
    total_leaves: int
    used_leaves: int
    void_leaves: int

    @property
    def free_leaves(self) -> int:
        return self.total_leaves - self.used_leaves - self.void_leaves

    @property
    def display(self) -> str:
        return f"{self.serial_no} ({self.first_no}–{self.last_no})"

    @property
    def next_number(self) -> int | None:
        return self.first_no + self.used_leaves + self.void_leaves \
            if self.free_leaves > 0 else None


@dataclass(frozen=True)
class ChequeRow:
    id: int
    direction: str
    direction_fa: str
    number: str
    bank_name: str
    branch_name: str
    account_number: str
    holder_name: str
    party_name: str
    party_detail_id: int | None
    amount: Decimal
    currency_code: str
    base_amount: Decimal
    issue_date: _dt.date
    due_date: _dt.date
    status: str
    status_fa: str
    description: str
    journal_id: int | None
    book_serial: str
    receipt_id: int | None
    payment_id: int | None
    is_open: bool

    @property
    def display(self) -> str:
        return f"{self.number} — {self.bank_name} — {self.base_amount:,}"

    @property
    def is_received(self) -> bool:
        return self.direction == TC.CHEQUE_RECEIVED

    @property
    def days_to_due(self) -> int:
        return (self.due_date - _dt.date.today()).days


@dataclass(frozen=True)
class ChequeEventRow:
    id: int
    from_status_fa: str
    to_status_fa: str
    event_date: _dt.date
    note: str
    user_name: str


@dataclass(frozen=True)
class ChequeBookInput:
    bank_account_id: int
    serial_no: str
    first_no: int
    last_no: int
    received_date: _dt.date
    status: str = TC.BOOK_ACTIVE
    note: str = ""


class ChequeService:
    def __init__(self, db: Database, audit: AuditService, *, journals,
                 settings=None) -> None:
        self.db = db
        self.audit = audit
        self.journals = journals
        self.settings = settings

    # ----------------------------------------------------------- cheque books
    def list_books(self, ctx: SecurityContext | None, *,
                   bank_account_id: int | None = None) -> list[ChequeBookRow]:
        require_permission(ctx, "cheques.view")
        query = select(ChequeBook).order_by(ChequeBook.serial_no)
        if bank_account_id:
            query = query.where(ChequeBook.bank_account_id == bank_account_id)
        with self.db.session_scope() as session:
            return [self._book_row(session, book)
                    for book in session.execute(query).scalars()]

    def book_choices(self, ctx: SecurityContext | None,
                     bank_account_id: int | None = None) -> list[tuple[int, str]]:
        return [(row.id, f"{row.serial_no} — باقی‌مانده {row.free_leaves}")
                for row in self.list_books(ctx, bank_account_id=bank_account_id)
                if row.free_leaves > 0]

    def create_book(self, ctx: SecurityContext | None,
                    data: ChequeBookInput) -> ChequeBookRow:
        require_permission(ctx, "cheque_books.manage")
        with self.db.session_scope() as session:
            get_or_404(session, BankAccount, data.bank_account_id,
                       "حساب بانکی دسته‌چک یافت نشد.")
            serial = clean_text(data.serial_no, field="serial_no", label="شماره سریال",
                                required=True, max_length=40)
            if int(data.last_no) < int(data.first_no):
                raise ValidationError("شمارهٔ آخر نباید کمتر از شمارهٔ اول باشد.",
                                      field="last_no")
            if int(data.first_no) <= 0:
                raise ValidationError("شمارهٔ برگ باید مثبت باشد.", field="first_no")
            if data.status not in dict(TC.BOOK_STATUSES):
                raise ValidationError("وضعیت دسته‌چک معتبر نیست.", field="status")
            book = ChequeBook(
                bank_account_id=data.bank_account_id, serial_no=serial,
                first_no=int(data.first_no), last_no=int(data.last_no),
                received_date=data.received_date, status=data.status,
                note=clean_text(data.note, field="note", label="توضیح", max_length=300))
            session.add(book)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("دسته‌چک با این سریال برای این حساب ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="cheque_book", entity_id=book.id, action="create",
                summary_fa=f"ثبت دسته‌چک {book.serial_no}", session=session)
            return self._book_row(session, book)

    def set_book_status(self, ctx: SecurityContext | None, book_id: int,
                        status: str) -> ChequeBookRow:
        require_permission(ctx, "cheque_books.manage")
        if status not in dict(TC.BOOK_STATUSES):
            raise ValidationError("وضعیت دسته‌چک معتبر نیست.", field="status")
        with self.db.session_scope() as session:
            book = get_or_404(session, ChequeBook, book_id, "دسته‌چک یافت نشد.")
            book.status = status
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cheque_book", entity_id=book.id, action="status",
                summary_fa=f"تغییر وضعیت دسته‌چک {book.serial_no}",
                after={"status": status}, session=session)
            return self._book_row(session, book)

    # ---------------------------------------------------------------- cheques
    def list_cheques(self, ctx: SecurityContext | None, *, direction: str | None = None,
                     status: str | None = None, date_from: _dt.date | None = None,
                     date_to: _dt.date | None = None, party_detail_id: int | None = None,
                     search: str | None = None, limit: int = 500) -> list[ChequeRow]:
        require_permission(ctx, "cheques.view")
        query = select(Cheque).order_by(Cheque.due_date, Cheque.id)
        if direction:
            query = query.where(Cheque.direction == direction)
        if status:
            query = query.where(Cheque.status == status)
        if date_from:
            query = query.where(Cheque.due_date >= date_from)
        if date_to:
            query = query.where(Cheque.due_date <= date_to)
        if party_detail_id:
            query = query.where(Cheque.party_detail_id == party_detail_id)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(Cheque.number.like(needle) | Cheque.bank_name.like(needle)
                                | Cheque.holder_name.like(needle))
        with self.db.session_scope() as session:
            return [self._cheque_row(session, cheque)
                    for cheque in session.execute(query.limit(limit)).scalars()]

    def get_cheque(self, ctx: SecurityContext | None, cheque_id: int) -> ChequeRow:
        require_permission(ctx, "cheques.view")
        with self.db.session_scope() as session:
            return self._cheque_row(session, get_or_404(
                session, Cheque, cheque_id, "چک مورد نظر یافت نشد."))

    def history(self, ctx: SecurityContext | None, cheque_id: int) -> list[ChequeEventRow]:
        require_permission(ctx, "cheques.view")
        with self.db.session_scope() as session:
            cheque = get_or_404(session, Cheque, cheque_id, "چک مورد نظر یافت نشد.")
            return [ChequeEventRow(
                id=event.id,
                from_status_fa=TC.CHEQUE_STATUS_TITLES_FA.get(event.from_status or "",
                                                              "—"),
                to_status_fa=TC.CHEQUE_STATUS_TITLES_FA.get(event.to_status,
                                                            event.to_status),
                event_date=event.event_date, note=event.note or "",
                user_name=event.user_name or "") for event in cheque.events]

    def create_in_session(self, session, ctx: SecurityContext | None, *, direction: str,
                          data, party_detail_id: int | None, amount: Decimal,
                          bank_account_id: int | None = None) -> Cheque:
        """Used by the voucher service: a cheque is born with its receipt/payment."""
        if direction not in dict(TC.CHEQUE_DIRECTIONS):
            raise ValidationError("نوع چک معتبر نیست.", field="direction")
        number = clean_text(data.number, field="number", label="شماره چک",
                            required=True, max_length=40)
        due = data.due_date
        if due < data.issue_date:
            raise ValidationError("تاریخ سررسید نمی‌تواند قبل از تاریخ صدور باشد.",
                                  field="due_date")
        book = None
        if data.cheque_book_id:
            book = get_or_404(session, ChequeBook, data.cheque_book_id,
                              "دسته‌چک یافت نشد.")
            book_status = book.status
            if book_status != TC.BOOK_ACTIVE:
                raise ValidationError("دسته‌چک انتخاب‌شده فعال نیست.", field="cheque_book_id")
            if book.bank_account_id != bank_account_id:
                raise ValidationError("دسته‌چک به حساب بانکی دیگری تعلق دارد.",
                                      field="cheque_book_id")
            try:
                leaf = int(number)
            except ValueError as exc:
                raise ValidationError("شماره چک باید عددی و از برگ‌های دسته‌چک باشد.",
                                      field="number") from exc
            if leaf < book.first_no or leaf > book.last_no:
                raise ValidationError("شماره چک خارج از محدودهٔ دسته‌چک است.",
                                      field="number")
            used = session.execute(select(Cheque).where(
                Cheque.cheque_book_id == book.id,
                Cheque.number == str(leaf))).scalars().first()
            if used is not None:
                raise ConflictError(
                    f"برگ شمارهٔ {leaf} از این دسته‌چک قبلاً استفاده شده است.")
        duplicate = session.execute(select(Cheque).where(
            Cheque.direction == direction,
            Cheque.bank_name == data.bank_name.strip(),
            Cheque.number == number)).scalars().first()
        if duplicate is not None:
            raise ConflictError(
                f"چک شمارهٔ «{number}» از بانک «{data.bank_name}» قبلاً ثبت شده است.")
        rate = Decimal(str(getattr(data, "exchange_rate", 1) or 1))
        cheque = Cheque(
            direction=direction, number=number, cheque_book_id=book.id if book else None,
            bank_name=clean_text(data.bank_name, field="bank_name", label="نام بانک",
                                 required=True, max_length=120),
            branch_name=clean_text(data.branch_name, field="branch_name",
                                   label="نام شعبه", max_length=120),
            account_number=clean_text(data.account_number, field="account_number",
                                      label="شماره حساب", max_length=40),
            holder_name=clean_text(data.holder_name, field="holder_name",
                                   label="صاحب حساب", max_length=120),
            amount=to_money(amount, field="amount"),
            base_amount=(to_money(amount) * rate).quantize(MONEY),
            exchange_rate=rate,
            currency_code=clean_text(getattr(data, "currency_code", "") or "IRR",
                                     field="currency_code", label="ارز", max_length=8).upper(),
            issue_date=data.issue_date, due_date=due,
            party_detail_id=party_detail_id, invoice_id=getattr(data, "invoice_id", None),
            bank_account_id=bank_account_id,
            cash_box_id=getattr(data, "cash_box_id", None),
            description=clean_text(data.description, field="description",
                                   label="توضیحات", max_length=500),
            attachment_path=clean_text(data.attachment_path, field="attachment_path",
                                       label="پیوست", max_length=500),
            status=(TC.CHQ_RECEIVED if direction == TC.CHEQUE_RECEIVED
                    else TC.CHQ_ISSUED),
            created_by_id=getattr(ctx, "user_id", None))
        session.add(cheque)
        session.flush()
        session.add(ChequeEvent(
            cheque_id=cheque.id, from_status=None, to_status=cheque.status,
            event_date=data.issue_date, note="ثبت چک",
            user_id=getattr(ctx, "user_id", None),
            user_name=getattr(ctx, "full_name", "") or getattr(ctx, "username", ""),
            created_at=_dt.datetime.now(_dt.timezone.utc)))
        session.flush()
        return cheque

    # -------------------------------------------------------- status workflow
    def change_status(self, ctx: SecurityContext | None, cheque_id: int, target: str,
                      *, event_date: _dt.date | None = None, note: str = "",
                      bank_account_id: int | None = None,
                      cash_box_id: int | None = None) -> ChequeRow:
        require_permission(ctx, "cheques.change_status")
        with self.db.session_scope() as session:
            cheque = get_or_404(session, Cheque, cheque_id, "چک مورد نظر یافت نشد.")
            table = (TC.RECEIVED_TRANSITIONS if cheque.direction == TC.CHEQUE_RECEIVED
                     else TC.ISSUED_TRANSITIONS)
            allowed = table.get(cheque.status, ())
            if target not in allowed:
                raise ConflictError(
                    f"تغییر وضعیت چک از «{TC.CHEQUE_STATUS_TITLES_FA.get(cheque.status, cheque.status)}» "
                    f"به «{TC.CHEQUE_STATUS_TITLES_FA.get(target, target)}» مجاز نیست.")
            if target in (TC.CHQ_CANCELLED,) and not (
                    ctx is not None and ctx.has("cheques.cancel")):
                raise ValidationError("ابطال چک نیازمند مجوز «ابطال چک» است.")
            event_day = event_date or _dt.date.today()
            journal_id = None
            if cheque.direction == TC.CHEQUE_RECEIVED:
                if target == TC.CHQ_COLLECTED:
                    fund_kind, box, bank = resolve_fund(
                        session, cash_box_id=cash_box_id, bank_account_id=bank_account_id)
                    cheque.bank_account_id = bank.id if bank else None
                    journal_id = self._ledger(session, ctx, cheque, TC.POSTING_CHEQUE_COLLECTED,
                                              event_day, f"وصول چک {cheque.number}",
                                              dynamic={TC.SRC_FUND: fund_account_id(box, bank)})
                elif target == TC.CHQ_BOUNCED:
                    journal_id = self._ledger(session, ctx, cheque, TC.POSTING_CHEQUE_BOUNCED,
                                              event_day, f"برگشت چک {cheque.number}")
            else:
                if target == TC.CHQ_PAID:
                    fund_kind, box, bank = resolve_fund(
                        session, cash_box_id=cash_box_id, bank_account_id=bank_account_id)
                    cheque.bank_account_id = bank.id if bank else None
                    journal_id = self._ledger(session, ctx, cheque, TC.POSTING_CHEQUE_CLEARED,
                                              event_day, f"وصول چک پرداختی {cheque.number}",
                                              dynamic={TC.SRC_FUND: fund_account_id(box, bank)})
            previous = cheque.status
            cheque.status = target
            if journal_id:
                cheque.journal_id = journal_id
            session.add(ChequeEvent(
                cheque_id=cheque.id, from_status=previous, to_status=target,
                event_date=event_day, note=note, journal_id=journal_id,
                user_id=getattr(ctx, "user_id", None),
                user_name=getattr(ctx, "full_name", "") or getattr(ctx, "username", ""),
                created_at=_dt.datetime.now(_dt.timezone.utc)))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cheque", entity_id=cheque.id, action="status",
                summary_fa=(f"تغییر وضعیت چک {cheque.number} به "
                            f"{TC.CHEQUE_STATUS_TITLES_FA.get(target, target)}"),
                after={"status": target, "journal_id": journal_id}, session=session)
            return self._cheque_row(session, cheque)

    def cancel(self, ctx: SecurityContext | None, cheque_id: int, reason: str) -> ChequeRow:
        require_permission(ctx, "cheques.cancel")
        reason = clean_text(reason, field="reason", label="دلیل ابطال", required=True,
                            max_length=300)
        if len(reason) < 5:
            raise ValidationError("دلیل ابطال باید حداقل ۵ نویسه باشد.", field="reason")
        return self.change_status(ctx, cheque_id, TC.CHQ_CANCELLED, note=reason)

    def mark_voiced(self, ctx: SecurityContext | None, book_id: int,
                    number: int, reason: str = "") -> ChequeBookRow:
        """Record a spoiled leaf so the number can never be issued."""
        require_permission(ctx, "cheque_books.manage")
        with self.db.session_scope() as session:
            book = get_or_404(session, ChequeBook, book_id, "دسته‌چک یافت نشد.")
            if number < book.first_no or number > book.last_no:
                raise ValidationError("شماره برگ خارج از محدودهٔ دسته‌چک است.",
                                      field="number")
            existing = session.execute(select(Cheque).where(
                Cheque.cheque_book_id == book.id, Cheque.number == str(number))
            ).scalars().first()
            if existing is not None:
                raise ConflictError("این برگ قبلاً ثبت شده است.")
            bank = session.get(BankAccount, book.bank_account_id)
            cheque = Cheque(
                direction=TC.CHEQUE_ISSUED, number=str(number), cheque_book_id=book.id,
                bank_name=bank.bank_name if bank else book.serial_no,
                amount=ZERO, base_amount=ZERO, issue_date=_dt.date.today(),
                due_date=_dt.date.today(), status=TC.CHQ_CANCELLED,
                bank_account_id=book.bank_account_id,
                description=clean_text(reason, field="reason", label="دلیل باطل‌کردن",
                                       max_length=500) or "برگ باطل‌شده",
                created_by_id=getattr(ctx, "user_id", None))
            session.add(cheque)
            session.flush()
            session.add(ChequeEvent(
                cheque_id=cheque.id, from_status=None, to_status=TC.CHQ_CANCELLED,
                event_date=_dt.date.today(), note="برگ باطل‌شده",
                user_id=getattr(ctx, "user_id", None),
                user_name=getattr(ctx, "full_name", "") or getattr(ctx, "username", ""),
                created_at=_dt.datetime.now(_dt.timezone.utc)))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cheque_book", entity_id=book.id, action="void_leaf",
                summary_fa=f"باطل‌کردن برگ {number} دسته‌چک {book.serial_no}",
                session=session)
            return self._book_row(session, book)

    def due_soon(self, ctx: SecurityContext | None, days: int | None = None) -> list[ChequeRow]:
        require_permission(ctx, "cheques.view")
        horizon = _dt.date.today() + _dt.timedelta(days=days or self._alert_days())
        with self.db.session_scope() as session:
            rows = session.execute(select(Cheque).where(
                Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES + TC.ISSUED_OPEN_STATUSES),
                Cheque.due_date <= horizon).order_by(Cheque.due_date)).scalars()
            return [self._cheque_row(session, cheque) for cheque in rows]

    # ---------------------------------------------------------------- internals
    def _ledger(self, session, ctx, cheque: Cheque, operation: str, event_day: _dt.date,
                title: str, *, dynamic: dict[str, int] | None = None) -> int | None:
        from pars_erp.services.posting_service import PostingService

        components = {TC.SRC_AMOUNT: Decimal(cheque.base_amount)}
        # The fund side of the template is dynamic, so its own source key must
        # carry the same amount or ``build_entry`` would see an unbalanced rule.
        for key in (dynamic or {}):
            components.setdefault(key, Decimal(cheque.base_amount))
        hint = party_hint_account(session, operation, cheque.party_detail_id)
        draft = PostingService(self.db, self.audit).build_entry(
            session, operation=operation, components=components,
            party_detail_id=cheque.party_detail_id, party_account_hint_id=hint,
            description=title, dynamic_accounts=dynamic or {})
        journal = post_system_journal(
            session, journals=self.journals, ctx=ctx, entry_date=event_day,
            title_fa=title, reference_no=cheque.number,
            idempotency_key=f"cheque:{cheque.id}:{operation.split('.')[-1]}",
            notes=cheque.description or "", draft=draft,
            source_kind="cheque", source_id=cheque.id)
        return journal.id

    def _alert_days(self) -> int:
        try:
            return int(self.settings.snapshot().int("treasury_cheque_alert_days"))
        except Exception:  # pragma: no cover
            return 7

    def _book_row(self, session, book: ChequeBook) -> ChequeBookRow:
        total = book.last_no - book.first_no + 1
        cheques = list(session.execute(select(Cheque).where(
            Cheque.cheque_book_id == book.id)).scalars())
        void = sum(1 for cheque in cheques if cheque.status == TC.CHQ_CANCELLED
                   and Decimal(cheque.amount) == 0)
        used = len(cheques) - void
        bank = session.get(BankAccount, book.bank_account_id)
        return ChequeBookRow(
            id=book.id, bank_account_id=book.bank_account_id,
            bank_label=(f"{bank.bank_name} — {bank.account_number}" if bank else ""),
            serial_no=book.serial_no, first_no=book.first_no, last_no=book.last_no,
            received_date=book.received_date, status=book.status,
            status_fa=TC.BOOK_STATUS_TITLES_FA.get(book.status, book.status),
            note=book.note or "", total_leaves=total, used_leaves=used, void_leaves=void)

    def _cheque_row(self, session, cheque: Cheque) -> ChequeRow:
        party = session.get(DetailAccount, cheque.party_detail_id) \
            if cheque.party_detail_id else None
        book = session.get(ChequeBook, cheque.cheque_book_id) \
            if cheque.cheque_book_id else None
        open_statuses = (TC.RECEIVED_OPEN_STATUSES if cheque.direction == TC.CHEQUE_RECEIVED
                         else TC.ISSUED_OPEN_STATUSES)
        return ChequeRow(
            id=cheque.id, direction=cheque.direction,
            direction_fa=TC.CHEQUE_DIRECTION_TITLES_FA.get(cheque.direction,
                                                           cheque.direction),
            number=cheque.number, bank_name=cheque.bank_name,
            branch_name=cheque.branch_name or "", account_number=cheque.account_number or "",
            holder_name=cheque.holder_name or "", party_name=party.name if party else "",
            party_detail_id=cheque.party_detail_id, amount=Decimal(cheque.amount),
            currency_code=cheque.currency_code, base_amount=Decimal(cheque.base_amount),
            issue_date=cheque.issue_date, due_date=cheque.due_date,
            status=cheque.status,
            status_fa=TC.CHEQUE_STATUS_TITLES_FA.get(cheque.status, cheque.status),
            description=cheque.description or "", journal_id=cheque.journal_id,
            book_serial=book.serial_no if book else "", receipt_id=cheque.receipt_id,
            payment_id=cheque.payment_id, is_open=cheque.status in open_statuses)
