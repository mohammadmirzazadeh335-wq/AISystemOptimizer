"""Bank accounts and cash boxes.

A *fund* is the thing that holds money; each fund owns exactly one subsidiary
account of the phase-2 chart, so every treasury document that touches the fund
also touches the general ledger. Cash boxes may be restricted to specific users
(``trs_cash_box_users``); an empty list means "everybody who has the permission".
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as AC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, BankAccount, CashBox, CashBoxUser, Payment, Receipt
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import ZERO, clean_code, clean_text, get_or_404, to_money
from pars_erp.services.treasury_common import fund_balance, fund_ledger_lines
from pars_erp.treasury import constants as TC


@dataclass(frozen=True)
class BankAccountInput:
    code: str
    bank_name: str
    account_number: str
    #: link to an existing subsidiary account, or leave empty and pass
    #: ``parent_account_id`` so a dedicated subsidiary account is created
    account_id: int | None = None
    parent_account_id: int | None = None
    branch_name: str = ""
    iban: str = ""
    card_number: str = ""
    holder_name: str = ""
    currency_code: str = "IRR"
    opening_balance: Decimal | str | int = 0
    opening_date: _dt.date | None = None
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class CashBoxInput:
    code: str
    title_fa: str
    account_id: int | None = None
    parent_account_id: int | None = None
    keeper_name: str = ""
    opening_balance: Decimal | str | int = 0
    opening_date: _dt.date | None = None
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class BankAccountRow:
    id: int
    code: str
    bank_name: str
    branch_name: str
    account_number: str
    iban: str
    card_number: str
    holder_name: str
    account_id: int
    account_label: str
    currency_code: str
    opening_balance: Decimal
    opening_date: _dt.date | None
    is_active: bool
    description: str
    balance: Decimal

    @property
    def display(self) -> str:
        return f"{self.bank_name} — {self.account_number}"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"

    @property
    def iban_masked(self) -> str:
        """IBAN shown in lists; full value only on the record itself."""
        if not self.iban:
            return ""
        return f"{self.iban[:6]}…{self.iban[-4:]}" if len(self.iban) > 10 else self.iban


@dataclass(frozen=True)
class CashBoxRow:
    id: int
    code: str
    title_fa: str
    keeper_name: str
    account_id: int
    account_label: str
    opening_balance: Decimal
    opening_date: _dt.date | None
    is_active: bool
    description: str
    balance: Decimal
    allowed_users: tuple[int, ...]

    @property
    def display(self) -> str:
        return f"{self.title_fa} ({self.code})"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"


@dataclass(frozen=True)
class FundMovementRow:
    """One row of a fund's ledger, built from posted documents only."""

    id: str
    movement_date: _dt.date
    kind: str
    kind_fa: str
    number: str
    description: str
    amount_in: Decimal
    amount_out: Decimal
    balance: Decimal
    journal_id: int | None


class FundsService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------ bank accounts
    def list_bank_accounts(self, ctx: SecurityContext | None, *, active: bool | None = None,
                           search: str | None = None) -> list[BankAccountRow]:
        require_permission(ctx, "bank_accounts.view")
        query = select(BankAccount).order_by(BankAccount.bank_name, BankAccount.code)
        if active is not None:
            query = query.where(BankAccount.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(BankAccount.bank_name.like(needle)
                                | BankAccount.account_number.like(needle)
                                | BankAccount.code.like(needle))
        with self.db.session_scope() as session:
            rows = []
            for account in session.execute(query).scalars():
                rows.append(self._bank_row(session, account))
            return rows

    def bank_account_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, f"{row.bank_name} — {row.account_number}")
                for row in self.list_bank_accounts(ctx, active=True)]

    def get_bank_account(self, ctx: SecurityContext | None, account_id: int) -> BankAccountRow:
        require_permission(ctx, "bank_accounts.view")
        with self.db.session_scope() as session:
            account = get_or_404(session, BankAccount, account_id,
                                 "حساب بانکی مورد نظر یافت نشد.")
            return self._bank_row(session, account)

    def create_bank_account(self, ctx: SecurityContext | None,
                            data: BankAccountInput) -> BankAccountRow:
        require_permission(ctx, "bank_accounts.edit")
        with self.db.session_scope() as session:
            payload = self._validated_bank(session, data)
            account = BankAccount(**payload)
            session.add(account)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("ثبت حساب بانکی با کد یا شمارهٔ تکراری ممکن نیست.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_account", entity_id=account.id, action="create",
                summary_fa=f"تعریف حساب بانکی {account.bank_name} — {account.account_number}",
                after={"code": account.code, "account_id": account.account_id},
                session=session)
            return self._bank_row(session, account)

    def update_bank_account(self, ctx: SecurityContext | None, account_id: int,
                            data: BankAccountInput) -> BankAccountRow:
        require_permission(ctx, "bank_accounts.edit")
        with self.db.session_scope() as session:
            account = get_or_404(session, BankAccount, account_id,
                                 "حساب بانکی مورد نظر یافت نشد.")
            payload = self._validated_bank(session, data, current=account)
            for key, value in payload.items():
                setattr(account, key, value)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_account", entity_id=account.id, action="update",
                summary_fa=f"ویرایش حساب بانکی {account.bank_name}", session=session)
            return self._bank_row(session, account)

    def set_bank_account_active(self, ctx: SecurityContext | None, account_id: int,
                                active: bool) -> BankAccountRow:
        require_permission(ctx, "bank_accounts.edit")
        with self.db.session_scope() as session:
            account = get_or_404(session, BankAccount, account_id,
                                 "حساب بانکی مورد نظر یافت نشد.")
            account.is_active = bool(active)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_account", entity_id=account.id, action="toggle",
                summary_fa=("فعال‌سازی" if active else "غیرفعال‌سازی")
                + f" حساب بانکی {account.bank_name}", session=session)
            return self._bank_row(session, account)

    # --------------------------------------------------------------- cash boxes
    def list_cash_boxes(self, ctx: SecurityContext | None, *, active: bool | None = None,
                        search: str | None = None) -> list[CashBoxRow]:
        require_permission(ctx, "cash_boxes.view")
        query = select(CashBox).order_by(CashBox.code)
        if active is not None:
            query = query.where(CashBox.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(CashBox.title_fa.like(needle) | CashBox.code.like(needle))
        with self.db.session_scope() as session:
            rows = [self._cash_row(session, box) for box in session.execute(query).scalars()]
        if ctx is not None and not getattr(ctx, "is_admin", False):
            # a box with an explicit access list is invisible to everybody else
            rows = [row for row in rows
                    if not row.allowed_users or ctx.user_id in row.allowed_users]
        return rows

    def cash_box_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, f"{row.title_fa} ({row.code})")
                for row in self.list_cash_boxes(ctx, active=True)]

    def get_cash_box(self, ctx: SecurityContext | None, box_id: int) -> CashBoxRow:
        require_permission(ctx, "cash_boxes.view")
        with self.db.session_scope() as session:
            box = get_or_404(session, CashBox, box_id, "صندوق مورد نظر یافت نشد.")
            self.assert_cash_box_allowed(session, ctx, box)
            return self._cash_row(session, box)

    def create_cash_box(self, ctx: SecurityContext | None,
                        data: CashBoxInput) -> CashBoxRow:
        require_permission(ctx, "cash_boxes.edit")
        with self.db.session_scope() as session:
            payload = self._validated_cash(session, data)
            box = CashBox(**payload)
            session.add(box)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cash_box", entity_id=box.id, action="create",
                summary_fa=f"تعریف صندوق {box.title_fa} ({box.code})",
                after={"account_id": box.account_id}, session=session)
            return self._cash_row(session, box)

    def update_cash_box(self, ctx: SecurityContext | None, box_id: int,
                        data: CashBoxInput) -> CashBoxRow:
        require_permission(ctx, "cash_boxes.edit")
        with self.db.session_scope() as session:
            box = get_or_404(session, CashBox, box_id, "صندوق مورد نظر یافت نشد.")
            payload = self._validated_cash(session, data, current=box)
            for key, value in payload.items():
                setattr(box, key, value)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cash_box", entity_id=box.id, action="update",
                summary_fa=f"ویرایش صندوق {box.title_fa}", session=session)
            return self._cash_row(session, box)

    def set_cash_box_users(self, ctx: SecurityContext | None, box_id: int,
                           user_ids: tuple[int, ...]) -> CashBoxRow:
        require_permission(ctx, "cash_boxes.edit")
        with self.db.session_scope() as session:
            box = get_or_404(session, CashBox, box_id, "صندوق مورد نظر یافت نشد.")
            for row in session.execute(
                    select(CashBoxUser).where(CashBoxUser.cash_box_id == box.id)).scalars():
                session.delete(row)
            for user_id in dict.fromkeys(user_ids):
                session.add(CashBoxUser(cash_box_id=box.id, user_id=user_id))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="cash_box", entity_id=box.id, action="access",
                summary_fa=f"تعیین دسترسی کاربران صندوق {box.title_fa}",
                after={"users": list(dict.fromkeys(user_ids))}, session=session)
            return self._cash_row(session, box)

    def assert_cash_box_allowed(self, session, ctx: SecurityContext | None,
                                cash_box: CashBox) -> None:
        """User-level restriction on top of the permission check."""
        if ctx is None or ctx.is_admin:
            return
        allowed = {row.user_id for row in session.execute(
            select(CashBoxUser).where(CashBoxUser.cash_box_id == cash_box.id)).scalars()}
        if allowed and ctx.user_id not in allowed:
            raise ValidationError(
                f"شما به صندوق «{cash_box.title_fa}» دسترسی ندارید؛ "
                "دسترسی صندوق‌ها را مدیر سیستم تعیین می‌کند.", field="cash_box_id")

    # ------------------------------------------------------------------ balance
    def balances(self, ctx: SecurityContext | None) -> dict:
        require_permission(ctx, "bank_accounts.view")
        boxes = self.list_cash_boxes(ctx)
        banks = self.list_bank_accounts(ctx)
        return {
            "cash_total": sum((row.balance for row in boxes), ZERO),
            "bank_total": sum((row.balance for row in banks), ZERO),
            "boxes": boxes,
            "banks": banks,
        }

    def fund_movements(self, ctx: SecurityContext | None, *, cash_box_id: int | None = None,
                       bank_account_id: int | None = None, date_from: _dt.date | None = None,
                       date_to: _dt.date | None = None) -> list[FundMovementRow]:
        """A fund's booked statement: opening balance plus posted ledger lines."""
        require_permission(ctx, "treasury.reports")
        with self.db.session_scope() as session:
            box = session.get(CashBox, cash_box_id) if cash_box_id else None
            account = session.get(BankAccount, bank_account_id) if bank_account_id else None
            fund = box or account
            if fund is None:
                raise ValidationError("صندوق یا حساب بانکی را مشخص کنید.", field="fund")
            opening = Decimal(fund.opening_balance or 0)
            opening_date = fund.opening_date
            rows: list[FundMovementRow] = []
            running = ZERO
            if opening:
                running = opening
                rows.append(FundMovementRow(
                    id="opening", movement_date=opening_date or _dt.date.today(),
                    kind="opening", kind_fa="موجودی اولیه", number="—",
                    description="موجودی ابتدای دوره", amount_in=opening,
                    amount_out=ZERO, balance=running, journal_id=None))
            for index, line in enumerate(fund_ledger_lines(
                    session, cash_box_id=cash_box_id, bank_account_id=bank_account_id,
                    date_from=date_from, date_to=date_to)):
                running = running + line["in"] - line["out"]
                rows.append(FundMovementRow(
                    id=f"journal-{index}", movement_date=line["date"], kind="journal",
                    kind_fa="سند حسابداری", number=line["number"],
                    description=line["description"], amount_in=line["in"],
                    amount_out=line["out"], balance=running,
                    journal_id=line["journal_id"]))
            return rows

    # ---------------------------------------------------------------- internals
    def _account(self, session, account_id: int) -> Account:
        account = get_or_404(session, Account, account_id, "حساب حسابداری یافت نشد.")
        if account.level != AC.LEVEL_SUBSIDIARY:
            raise ValidationError("حساب حسابداری باید «معین» باشد.", field="account_id")
        if not account.is_active:
            raise ValidationError("حساب حسابداری انتخاب‌شده غیرفعال است.", field="account_id")
        return account

    def _fund_account(self, session, *, account_id: int | None,
                      parent_account_id: int | None, default_parent_code: str,
                      code: str, title: str, current_id: int | None = None,
                      current_kind: str | None = None) -> Account:
        """Resolve - or create - the subsidiary account that backs one fund.

        Two funds may never share one ledger account, otherwise their balances,
        statements and reconciliation would be indistinguishable. When the caller
        does not pick an existing account, a dedicated subsidiary account is
        created under the fund's parent account (the chart stays the source of
        truth: the parent may be chosen explicitly with ``parent_account_id``).
        """
        if account_id:
            account = self._account(session, account_id)
        else:
            parent = (session.get(Account, parent_account_id) if parent_account_id
                      else session.execute(select(Account).where(
                          Account.code == default_parent_code)).scalars().first())
            if parent is None:
                raise ValidationError(
                    "حساب کل «صندوق‌ها/بانک‌ها» در دفتر حساب‌ها یافت نشد؛ ابتدا حساب‌ها را "
                    "تعریف کنید یا حساب معین صندوق را انتخاب کنید.", field="account_id")
            base_code = f"{parent.code}.{code}"
            new_code, suffix = base_code, 1
            while session.execute(select(Account).where(
                    Account.code == new_code)).scalars().first() is not None:
                suffix += 1
                new_code = f"{base_code}-{suffix}"
            account = Account(
                code=new_code[:32], title_fa=f"{title} ({code})"[:160],
                level=AC.LEVEL_SUBSIDIARY, account_type=parent.account_type,
                nature=parent.nature, parent_id=parent.id,
                statement_section=parent.statement_section, is_active=True,
                description="حساب معین صندوق/بانک خزانه‌داری")
            session.add(account)
            session.flush()
        taken = session.execute(select(BankAccount.id).where(
            BankAccount.account_id == account.id)).scalars().first()
        if taken is not None and not (current_kind == "bank" and current_id == taken):
            raise ConflictError("این حساب حسابداری قبلاً به یک حساب بانکی وصل شده است.")
        taken_cash = session.execute(select(CashBox.id).where(
            CashBox.account_id == account.id)).scalars().first()
        if taken_cash is not None and not (current_kind == "cash" and current_id == taken_cash):
            raise ConflictError("این حساب حسابداری قبلاً به یک صندوق وصل شده است.")
        return account

    @staticmethod
    def _normalize_iban(value) -> str:
        """Validate the *shape* of an Iranian IBAN (IR + 24 digits), nothing else.

        The format is an international ISO-13616 convention, not a rate: the check
        is purely structural so a mistyped account can be caught early.
        """
        text = clean_text(value, field="iban", label="شماره شبا", max_length=34)
        text = text.replace(" ", "").replace("-", "").upper()
        if text and (not text.startswith("IR") or not text[2:].isdigit()
                     or len(text) != 26):
            raise ValidationError(
                "شماره شبا باید با IR شروع شود و ۲۶ نویسه باشد.", field="iban")
        return text

    @staticmethod
    def _normalize_card(value) -> str:
        text = clean_text(value, field="card_number", label="شماره کارت", max_length=24)
        text = text.replace(" ", "").replace("-", "")
        if text and (not text.isdigit() or len(text) != 16):
            raise ValidationError("شماره کارت باید ۱۶ رقم باشد.", field="card_number")
        return text

    def _validated_bank(self, session, data: BankAccountInput,
                        current: BankAccount | None = None) -> dict:
        code = clean_code(data.code, label="کد حساب", max_length=24)
        account = self._fund_account(
            session, account_id=data.account_id, parent_account_id=data.parent_account_id,
            default_parent_code=TC.DEFAULT_BANK_PARENT_CODE, code=code,
            title=f"بانک {data.bank_name}",
            current_id=current.id if current else None,
            current_kind="bank" if current else None)
        bank_name = clean_text(data.bank_name, field="bank_name", label="نام بانک",
                               required=True, max_length=120)
        number = clean_text(data.account_number, field="account_number",
                            label="شماره حساب", required=True, max_length=40)
        existing = session.execute(
            select(BankAccount).where(BankAccount.bank_name == bank_name,
                                      BankAccount.account_number == number)).scalars().first()
        if existing is not None and (current is None or existing.id != current.id):
            raise ConflictError(
                f"حساب «{number}» در بانک «{bank_name}» قبلاً ثبت شده است.")
        duplicate = session.execute(
            select(BankAccount).where(BankAccount.code == code)).scalars().first()
        if duplicate is not None and (current is None or duplicate.id != current.id):
            raise ConflictError("کد حساب بانکی تکراری است.")
        return {
            "code": code,
            "bank_name": bank_name,
            "branch_name": clean_text(data.branch_name, field="branch_name",
                                      label="نام شعبه", max_length=120),
            "account_number": number,
            "iban": self._normalize_iban(data.iban),
            "card_number": self._normalize_card(data.card_number),
            "holder_name": clean_text(data.holder_name, field="holder_name",
                                      label="نام صاحب حساب", max_length=120),
            "account_id": account.id,
            "currency_code": (data.currency_code or "IRR").strip().upper()[:8],
            "opening_balance": to_money(data.opening_balance, field="opening_balance"),
            "opening_date": data.opening_date,
            "is_active": bool(data.is_active),
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=300),
        }

    def _validated_cash(self, session, data: CashBoxInput,
                        current: CashBox | None = None) -> dict:
        code = clean_code(data.code, label="کد صندوق", max_length=24)
        account = self._fund_account(
            session, account_id=data.account_id, parent_account_id=data.parent_account_id,
            default_parent_code=TC.DEFAULT_CASH_PARENT_CODE, code=code,
            title=f"صندوق {data.title_fa}",
            current_id=current.id if current else None,
            current_kind="cash" if current else None)
        duplicate = session.execute(
            select(CashBox).where(CashBox.code == code)).scalars().first()
        if duplicate is not None and (current is None or duplicate.id != current.id):
            raise ConflictError("کد صندوق تکراری است.")
        return {
            "code": code,
            "title_fa": clean_text(data.title_fa, field="title_fa", label="نام صندوق",
                                   required=True, max_length=120),
            "keeper_name": clean_text(data.keeper_name, field="keeper_name",
                                      label="مسئول صندوق", max_length=120),
            "account_id": account.id,
            "opening_balance": to_money(data.opening_balance, field="opening_balance"),
            "opening_date": data.opening_date,
            "is_active": bool(data.is_active),
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=300),
        }

    def _bank_row(self, session, account: BankAccount) -> BankAccountRow:
        ledger = session.get(Account, account.account_id)
        return BankAccountRow(
            id=account.id, code=account.code, bank_name=account.bank_name,
            branch_name=account.branch_name or "", account_number=account.account_number,
            iban=account.iban or "", card_number=account.card_number or "",
            holder_name=account.holder_name or "", account_id=account.account_id,
            account_label=(f"{ledger.code} — {ledger.title_fa}" if ledger else ""),
            currency_code=account.currency_code,
            opening_balance=Decimal(account.opening_balance or 0),
            opening_date=account.opening_date, is_active=account.is_active,
            description=account.description or "",
            balance=fund_balance(session, bank_account_id=account.id))

    def _cash_row(self, session, box: CashBox) -> CashBoxRow:
        ledger = session.get(Account, box.account_id)
        allowed = tuple(row.user_id for row in session.execute(
            select(CashBoxUser).where(CashBoxUser.cash_box_id == box.id)).scalars())
        return CashBoxRow(
            id=box.id, code=box.code, title_fa=box.title_fa,
            keeper_name=box.keeper_name or "", account_id=box.account_id,
            account_label=(f"{ledger.code} — {ledger.title_fa}" if ledger else ""),
            opening_balance=Decimal(box.opening_balance or 0),
            opening_date=box.opening_date, is_active=box.is_active,
            description=box.description or "",
            balance=fund_balance(session, cash_box_id=box.id), allowed_users=allowed)
