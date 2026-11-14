"""Persons: customers, suppliers and employees on top of the phase-2 details.

A person **is** a phase-2 detail account (``acc_details``), extended with the
commercial fields (person type, mobile, e-mail, tax ids, credit limit and the
customer/supplier flags). Keeping one record means:

* there is exactly one ledger detail per person - no duplicate detail accounts
  for the same legal entity;
* the AR/AP control accounts defined in phase 2 are reused, so an invoice's
  journal entry lands straight on the person's subsidiary ledger;
* the person can be both a customer and a supplier without being created twice.

The trade-off (documented in ``docs/phase3/accounting-integration.md``): the
detail hangs under **one** control account - the one matching the primary role
(AR for customers, AP for suppliers, AR for dual-role records). Commercial
balances and turnover are therefore computed from the invoices themselves,
which is why a dual-used person still shows a correct AR *and* AP balance.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as AC
from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    DetailAccount,
    Invoice,
    Journal,
    JournalLine,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import ZERO, clean_code, clean_text, to_money

#: Default control accounts from the standard phase-2 chart (configurable).
DEFAULT_CUSTOMER_ACCOUNT_CODE = "101002"   # حساب‌های دریافتنی تجاری
DEFAULT_SUPPLIER_ACCOUNT_CODE = "201001"   # حساب‌های پرداختنی تجاری

PERSON_ROLES: dict[str, str] = {
    "customer": "مشتری",
    "supplier": "تأمین‌کننده",
    "both": "مشتری و تأمین‌کننده",
}


@dataclass(frozen=True)
class PersonInput:
    code: str
    name: str
    role: str = "customer"
    person_type: str = CC.PERSON_REAL
    phone: str = ""
    mobile: str = ""
    email: str = ""
    address: str = ""
    economic_code: str = ""
    national_id: str = ""
    registration_no: str = ""
    credit_limit: Decimal | str | int = 0
    description: str = ""
    is_active: bool = True
    account_id: int | None = None


@dataclass(frozen=True)
class PersonRow:
    id: int
    code: str
    name: str
    kind: str
    role: str
    role_fa: str
    person_type: str
    person_type_fa: str
    phone: str
    mobile: str
    email: str
    address: str
    economic_code: str
    national_id: str
    registration_no: str
    credit_limit: Decimal
    description: str
    is_active: bool
    is_customer: bool
    is_supplier: bool
    account_id: int | None
    account_label: str
    balance: Decimal
    balance_fa: str

    @property
    def display(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"

    @property
    def roles_fa(self) -> str:
        if self.is_customer and self.is_supplier:
            return PERSON_ROLES["both"]
        return PERSON_ROLES["customer"] if self.is_customer else PERSON_ROLES["supplier"]


@dataclass(frozen=True)
class PersonFilter:
    search: str = ""
    role: str | None = None
    person_type: str | None = None
    active: bool | None = None
    has_debt: bool = False


@dataclass(frozen=True)
class PersonInvoice:
    invoice_id: int
    number: str
    kind: str
    kind_fa: str
    invoice_date: _dt.date
    net_total: Decimal
    status: str
    status_fa: str


@dataclass(frozen=True)
class PersonTurnover:
    person_id: int
    name: str
    purchase_total: Decimal
    purchase_returns: Decimal
    sale_total: Decimal
    sale_returns: Decimal
    balance: Decimal

    @property
    def net_purchase(self) -> Decimal:
        return self.purchase_total - self.purchase_returns

    @property
    def net_sale(self) -> Decimal:
        return self.sale_total - self.sale_returns


@dataclass(frozen=True)
class PersonLedgerLine:
    entry_date: _dt.date
    number: int
    title: str
    account_label: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    running_fa: str


class PersonService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # -------------------------------------------------------------- queries
    def list_persons(self, ctx: SecurityContext | None,
                     filters: PersonFilter | None = None) -> list[PersonRow]:
        require_permission(ctx, "persons.view")
        filters = filters or PersonFilter()
        query = (select(DetailAccount)
                 .where(DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)))
                 .order_by(DetailAccount.code))
        if filters.person_type:
            query = query.where(DetailAccount.person_type == filters.person_type)
        if filters.active is not None:
            query = query.where(DetailAccount.is_active.is_(bool(filters.active)))
        if filters.role == "customer":
            query = query.where(DetailAccount.is_customer.is_(True))
        elif filters.role == "supplier":
            query = query.where(DetailAccount.is_supplier.is_(True))
        if filters.search:
            needle = f"%{filters.search.strip()}%"
            query = query.where(or_(DetailAccount.code.like(needle),
                                    DetailAccount.name.like(needle),
                                    DetailAccount.phone.like(needle),
                                    DetailAccount.mobile.like(needle),
                                    DetailAccount.national_id.like(needle),
                                    DetailAccount.economic_code.like(needle),
                                    DetailAccount.email.like(needle)))
        with self.db.session_scope() as session:
            details = list(session.execute(query).scalars())
            balances = self._ledger_balances(session, [d.id for d in details])
            accounts = {a.id: a for a in session.execute(select(Account)).scalars()}
            rows = [self._row(d, balances.get(d.id, ZERO), accounts.get(d.account_id))
                    for d in details]
        if filters.has_debt:
            rows = [row for row in rows if row.balance > 0]
        return rows

    def get(self, ctx: SecurityContext | None, person_id: int) -> PersonRow:
        require_permission(ctx, "persons.view")
        with self.db.session_scope() as session:
            detail = session.get(DetailAccount, person_id)
            if detail is None:
                raise NotFoundError("شخص مورد نظر یافت نشد.")
            balances = self._ledger_balances(session, [detail.id])
            account = session.get(Account, detail.account_id) if detail.account_id else None
            return self._row(detail, balances.get(detail.id, ZERO), account)

    def choices(self, ctx: SecurityContext | None, *, role: str | None = None,
                active_only: bool = True) -> list[tuple[int, str]]:
        require_permission(ctx, "persons.view")
        query = (select(DetailAccount)
                 .where(DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)))
                 .order_by(DetailAccount.code))
        if active_only:
            query = query.where(DetailAccount.is_active.is_(True))
        if role == "customer":
            query = query.where(DetailAccount.is_customer.is_(True))
        elif role == "supplier":
            query = query.where(DetailAccount.is_supplier.is_(True))
        with self.db.session_scope() as session:
            return [(d.id, f"{d.code} — {d.name}")
                    for d in session.execute(query).scalars()]

    def find_by_code(self, ctx: SecurityContext | None, code: str) -> PersonRow:
        require_permission(ctx, "persons.view")
        with self.db.session_scope() as session:
            detail = session.execute(
                select(DetailAccount).where(DetailAccount.code == (code or "").strip())
            ).scalars().first()
            if detail is None or detail.kind not in (AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER):
                raise NotFoundError(f"شخصی با کد «{code}» یافت نشد.")
            balances = self._ledger_balances(session, [detail.id])
            account = session.get(Account, detail.account_id) if detail.account_id else None
            return self._row(detail, balances.get(detail.id, ZERO), account)

    def invoices(self, ctx: SecurityContext | None, person_id: int, *,
                 kind: str | None = None, limit: int = 100) -> list[PersonInvoice]:
        require_permission(ctx, "persons.view")
        query = (select(Invoice).where(Invoice.party_detail_id == person_id)
                 .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
                 .limit(max(1, min(limit, 500))))
        if kind:
            query = query.where(Invoice.kind == kind)
        with self.db.session_scope() as session:
            return [PersonInvoice(
                invoice_id=inv.id, number=inv.number, kind=inv.kind,
                kind_fa=CC.INVOICE_TITLES_FA.get(inv.kind, inv.kind),
                invoice_date=inv.invoice_date, net_total=inv.net_total, status=inv.status,
                status_fa=CC.DOC_STATUS_TITLES_FA.get(inv.status, inv.status))
                for inv in session.execute(query).scalars()]

    def turnover(self, ctx: SecurityContext | None, person_id: int, *,
                 date_from: _dt.date | None = None,
                 date_to: _dt.date | None = None) -> PersonTurnover:
        require_permission(ctx, "persons.view")
        with self.db.session_scope() as session:
            detail = session.get(DetailAccount, person_id)
            if detail is None:
                raise NotFoundError("شخص مورد نظر یافت نشد.")
            query = (select(Invoice.kind, func.sum(Invoice.net_total))
                     .where(Invoice.party_detail_id == person_id,
                            Invoice.status == CC.STATUS_POSTED)
                     .group_by(Invoice.kind))
            if date_from:
                query = query.where(Invoice.invoice_date >= date_from)
            if date_to:
                query = query.where(Invoice.invoice_date <= date_to)
            totals = {kind: Decimal(value or 0)
                      for kind, value in session.execute(query).all()}
            balances = self._ledger_balances(session, [detail.id])
            return PersonTurnover(
                person_id=detail.id, name=detail.name,
                purchase_total=totals.get(CC.INVOICE_PURCHASE, ZERO),
                purchase_returns=totals.get(CC.INVOICE_PURCHASE_RETURN, ZERO),
                sale_total=totals.get(CC.INVOICE_SALE, ZERO),
                sale_returns=totals.get(CC.INVOICE_SALE_RETURN, ZERO),
                balance=balances.get(detail.id, ZERO),
            )

    def statement(self, ctx: SecurityContext | None, person_id: int, *,
                  date_from: _dt.date | None = None,
                  date_to: _dt.date | None = None) -> list[PersonLedgerLine]:
        """The person's subsidiary ledger, straight from phase-2 journal lines."""
        require_permission(ctx, "persons.view")
        with self.db.session_scope() as session:
            query = (select(JournalLine, Journal, Account)
                     .join(Journal, Journal.id == JournalLine.journal_id)
                     .join(Account, Account.id == JournalLine.account_id)
                     .where(JournalLine.detail_id == person_id,
                            Journal.status.in_(AC.EFFECTIVE_STATUSES))
                     .order_by(Journal.entry_date, Journal.number, JournalLine.id))
            if date_from:
                query = query.where(Journal.entry_date >= date_from)
            if date_to:
                query = query.where(Journal.entry_date <= date_to)
            running = ZERO
            rows: list[PersonLedgerLine] = []
            for line, journal, account in session.execute(query).all():
                debit = Decimal(line.debit or 0)
                credit = Decimal(line.credit or 0)
                running += debit - credit
                rows.append(PersonLedgerLine(
                    entry_date=journal.entry_date, number=journal.number,
                    title=journal.title_fa,
                    account_label=f"{account.code} — {account.title_fa}",
                    debit=debit, credit=credit, balance=running,
                    running_fa=f"{running:,}"))
            return rows

    # ---------------------------------------------------------------- writes
    def create(self, ctx: SecurityContext | None, data: PersonInput) -> PersonRow:
        require_permission(ctx, "persons.create")
        with self.db.session_scope() as session:
            payload, control = self._validated(session, data)
            detail = DetailAccount(
                **payload,
                account_id=control.id if control else None,
                created_by_id=ctx.user_id if ctx else None,
            )
            session.add(detail)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد شخص قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="person", entity_id=detail.id, action="create",
                summary_fa=f"ایجاد {self._role_title(detail)} {detail.code} — {detail.name}",
                after=self._snapshot(detail), session=session)
            return self._row(detail, ZERO, control)

    def update(self, ctx: SecurityContext | None, person_id: int,
               data: PersonInput) -> PersonRow:
        require_permission(ctx, "persons.edit")
        with self.db.session_scope() as session:
            detail = session.get(DetailAccount, person_id)
            if detail is None:
                raise NotFoundError("شخص مورد نظر یافت نشد.")
            before = self._snapshot(detail)
            payload, control = self._validated(session, data, person_id=detail.id,
                                               existing=detail)
            had_history = self._has_history(session, detail.id)
            if had_history and payload["kind"] != detail.kind:
                raise ValidationError(
                    "این شخص سابقهٔ مالی دارد؛ تغییر نوع مشتری/تأمین‌کننده مجاز نیست. "
                    "برای هر دو نقش، گزینهٔ «مشتری و تأمین‌کننده» را انتخاب کنید.",
                    field="role")
            for key, value in payload.items():
                setattr(detail, key, value)
            if control is not None:
                detail.account_id = control.id
            detail.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="person", entity_id=detail.id, action="update",
                summary_fa=f"ویرایش {self._role_title(detail)} {detail.code} — {detail.name}",
                before=before, after=self._snapshot(detail), session=session)
            return self._row(detail, ZERO, control)

    def set_active(self, ctx: SecurityContext | None, person_id: int,
                   active: bool) -> PersonRow:
        require_permission(ctx, "persons.deactivate")
        with self.db.session_scope() as session:
            detail = session.get(DetailAccount, person_id)
            if detail is None:
                raise NotFoundError("شخص مورد نظر یافت نشد.")
            detail.is_active = bool(active)
            detail.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="person", entity_id=detail.id,
                action="activate" if active else "deactivate",
                summary_fa=("فعال‌سازی" if active else "غیرفعال‌سازی")
                + f" شخص {detail.code} — {detail.name}", session=session)
            account = session.get(Account, detail.account_id) if detail.account_id else None
            return self._row(detail, ZERO, account)

    def delete(self, ctx: SecurityContext | None, person_id: int) -> None:
        require_permission(ctx, "persons.delete")
        with self.db.session_scope() as session:
            detail = session.get(DetailAccount, person_id)
            if detail is None:
                raise NotFoundError("شخص مورد نظر یافت نشد.")
            if self._has_history(session, detail.id):
                raise ValidationError(
                    "این شخص سابقهٔ مالی دارد و قابل حذف نیست؛ به‌جای حذف، آن را غیرفعال کنید.")
            session.delete(detail)
            self.audit.log_audit(
                ctx=ctx, entity_type="person", entity_id=person_id, action="delete",
                summary_fa=f"حذف شخص {detail.code} — {detail.name}", session=session)

    # ------------------------------------------------------------- internals
    @staticmethod
    def _has_history(session, detail_id: int) -> bool:
        lines = session.execute(
            select(func.count(JournalLine.id))
            .where(JournalLine.detail_id == detail_id)).scalar() or 0
        invoices = session.execute(
            select(func.count(Invoice.id))
            .where(Invoice.party_detail_id == detail_id)).scalar() or 0
        return bool(lines or invoices)

    @staticmethod
    def _ledger_balances(session, detail_ids: list[int]) -> dict[int, Decimal]:
        if not detail_ids:
            return {}
        # SUM over two MoneyAmount columns separately: an expression like
        # ``debit - credit`` loses the column type, and SQLite would hand back the
        # raw integer minor units instead of the Decimal money value.
        rows = session.execute(
            select(JournalLine.detail_id, func.sum(JournalLine.debit),
                   func.sum(JournalLine.credit))
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(JournalLine.detail_id.in_(detail_ids),
                   Journal.status.in_(AC.EFFECTIVE_STATUSES))
            .group_by(JournalLine.detail_id)).all()
        return {int(detail_id): Decimal(debit or 0) - Decimal(credit or 0)
                for detail_id, debit, credit in rows}

    def _validated(self, session, data: PersonInput, *, person_id: int | None = None,
                   existing: DetailAccount | None = None) -> tuple[dict, Account | None]:
        code = clean_code(data.code, label="کد شخص", max_length=32)
        name = clean_text(data.name, field="name", label="نام شخص", required=True,
                          max_length=160)
        if data.role not in PERSON_ROLES:
            raise ValidationError("نوع شخص باید مشتری، تأمین‌کننده یا هر دو باشد.",
                                  field="role")
        if data.person_type not in CC.PERSON_TYPES:
            raise ValidationError("نوع حقوقی/حقیقی معتبر نیست.", field="person_type")
        is_customer = data.role in ("customer", "both")
        is_supplier = data.role in ("supplier", "both")
        kind = AC.DETAIL_CUSTOMER if is_customer else AC.DETAIL_SUPPLIER

        clash = session.execute(
            select(DetailAccount).where(DetailAccount.code == code)).scalars().first()
        if clash is not None and clash.id != person_id:
            raise ConflictError(f"کد «{code}» قبلاً برای شخص دیگری ثبت شده است.")
        national_id = clean_text(data.national_id, field="national_id", label="کد ملی",
                                 max_length=32)
        economic_code = clean_text(data.economic_code, field="economic_code",
                                   label="کد اقتصادی", max_length=32)
        if national_id:
            dup = session.execute(
                select(DetailAccount).where(
                    DetailAccount.national_id == national_id,
                    DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)))).scalars().first()
            if dup is not None and dup.id != person_id:
                raise ConflictError(
                    f"کد ملی «{national_id}» قبلاً برای شخص «{dup.name}» ثبت شده است.")
        if economic_code:
            dup = session.execute(
                select(DetailAccount).where(
                    DetailAccount.economic_code == economic_code,
                    DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)))).scalars().first()
            if dup is not None and dup.id != person_id:
                raise ConflictError(
                    f"کد اقتصادی «{economic_code}» قبلاً برای شخص «{dup.name}» ثبت شده است.")
        if not national_id and not economic_code:
            dup = session.execute(
                select(DetailAccount).where(
                    DetailAccount.name == name,
                    DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)))).scalars().first()
            if dup is not None and dup.id != person_id:
                raise ConflictError(
                    f"شخصی با نام «{name}» از قبل ثبت شده است؛ برای جلوگیری از تکرار، "
                    "کد ملی یا کد اقتصادی را وارد کنید یا همان شخص را ویرایش کنید.")

        control: Account | None = None
        if data.account_id:
            control = session.get(Account, data.account_id)
            if control is None:
                raise NotFoundError("حساب معین انتخاب‌شده یافت نشد.")
            if control.level != AC.LEVEL_SUBSIDIARY:
                raise ValidationError("حساب شخص باید یک حساب معین باشد.", field="account_id")
        else:
            code_pref = (DEFAULT_CUSTOMER_ACCOUNT_CODE if is_customer
                         else DEFAULT_SUPPLIER_ACCOUNT_CODE)
            control = session.execute(
                select(Account).where(Account.code == code_pref)).scalars().first()
            if control is None:  # a chart without the standard codes is still usable
                control = None

        payload = {
            "code": code,
            "name": name,
            "kind": kind,
            "person_type": data.person_type,
            "phone": clean_text(data.phone, field="phone", label="تلفن", max_length=32),
            "mobile": clean_text(data.mobile, field="mobile", label="همراه", max_length=32),
            "email": clean_text(data.email, field="email", label="ایمیل", max_length=120),
            "address": clean_text(data.address, field="address", label="نشانی", max_length=300),
            "economic_code": economic_code,
            "national_id": national_id,
            "registration_no": clean_text(data.registration_no, field="registration_no",
                                          label="شماره ثبت", max_length=32),
            "credit_limit": to_money(data.credit_limit, field="credit_limit"),
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=500),
            "is_active": bool(data.is_active),
            "is_customer": is_customer,
            "is_supplier": is_supplier,
        }
        if "email" in payload and payload["email"] and "@" not in payload["email"]:
            raise ValidationError("ایمیل معتبر نیست.", field="email")
        return payload, control

    @staticmethod
    def _role_title(detail: DetailAccount) -> str:
        if detail.is_customer and detail.is_supplier:
            return PERSON_ROLES["both"]
        return PERSON_ROLES["customer"] if detail.is_customer else PERSON_ROLES["supplier"]

    @staticmethod
    def _row(detail: DetailAccount, balance: Decimal, account: Account | None) -> PersonRow:
        role = ("both" if detail.is_customer and detail.is_supplier
                else ("customer" if detail.is_customer else "supplier"))
        return PersonRow(
            id=detail.id, code=detail.code, name=detail.name, kind=detail.kind,
            role=role, role_fa=PERSON_ROLES[role],
            person_type=detail.person_type,
            person_type_fa=CC.PERSON_TYPE_TITLES_FA.get(detail.person_type,
                                                        detail.person_type),
            phone=detail.phone or "", mobile=detail.mobile or "",
            email=detail.email or "", address=detail.address or "",
            economic_code=detail.economic_code or "", national_id=detail.national_id or "",
            registration_no=detail.registration_no or "",
            credit_limit=detail.credit_limit, description=detail.description or "",
            is_active=detail.is_active, is_customer=detail.is_customer,
            is_supplier=detail.is_supplier, account_id=detail.account_id,
            account_label=(f"{account.code} — {account.title_fa}" if account else ""),
            balance=balance, balance_fa=f"{balance:,}",
        )

    @staticmethod
    def _snapshot(detail: DetailAccount) -> dict:
        return {
            "code": detail.code, "name": detail.name, "kind": detail.kind,
            "person_type": detail.person_type, "is_customer": detail.is_customer,
            "is_supplier": detail.is_supplier, "credit_limit": str(detail.credit_limit),
            "account_id": detail.account_id, "is_active": detail.is_active,
        }
