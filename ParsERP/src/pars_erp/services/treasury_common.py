"""Shared, Qt-free helpers for the phase-4 treasury services.

The important rule of this module: **a fund balance is always derived from
posted documents**, never from a number somebody typed. That keeps the cash box
ledger, the bank ledger and the general ledger explainable line by line.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    BankAccount,
    CashBox,
    FundTransfer,
    Journal,
    Payment,
    Receipt,
)
from pars_erp.services.commerce_common import (  # noqa: F401  (re-exported helpers)
    ZERO,
    clean_code,
    clean_text,
    get_or_404,
    next_document_number,
    to_money,
)
from pars_erp.treasury import constants as TC

MONEY = Decimal("0.01")


# --------------------------------------------------------------- fund lookup
def resolve_fund(session: Session, *, cash_box_id: int | None,
                 bank_account_id: int | None) -> tuple[str, CashBox | None, BankAccount | None]:
    """Exactly one of a cash box or a bank account must be given."""
    if bool(cash_box_id) == bool(bank_account_id):
        raise ValidationError("یکی از «صندوق» یا «حساب بانکی» را انتخاب کنید.", field="fund")
    if cash_box_id:
        box = get_or_404(session, CashBox, cash_box_id, "صندوق مورد نظر یافت نشد.")
        if not box.is_active:
            raise ValidationError("صندوق انتخاب‌شده غیرفعال است.", field="cash_box_id")
        return TC.FUND_CASH, box, None
    account = get_or_404(session, BankAccount, bank_account_id,
                         "حساب بانکی مورد نظر یافت نشد.")
    if not account.is_active:
        raise ValidationError("حساب بانکی انتخاب‌شده غیرفعال است.", field="bank_account_id")
    return TC.FUND_BANK, None, account


def fund_account_id(cash_box: CashBox | None, bank: BankAccount | None) -> int:
    fund = cash_box or bank
    if fund is None:  # pragma: no cover - guarded by resolve_fund
        raise ValidationError("صندوق یا حساب بانکی سند مشخص نیست.", field="fund")
    return fund.account_id


def fund_label(cash_box: CashBox | None, bank: BankAccount | None) -> str:
    if cash_box is not None:
        return f"صندوق {cash_box.title_fa}"
    if bank is not None:
        return f"بانک {bank.bank_name} — {bank.account_number}"
    return ""


def fund_ledger_lines(session: Session, *, cash_box_id: int | None = None,
                      bank_account_id: int | None = None,
                      date_from: _dt.date | None = None,
                      date_to: _dt.date | None = None) -> list[dict]:
    """Every posted journal line that moved one fund, oldest first.

    The fund's own subsidiary account is the single source of truth: receipts,
    payments, transfers (including the fee), collected cheques, corrections and
    voids all reach it through the general ledger, so a statement built from these
    lines always ties to the balance and to the trial balance.
    """
    from pars_erp.accounting import constants as AC
    from pars_erp.db.models import Journal, JournalLine

    box = session.get(CashBox, cash_box_id) if cash_box_id else None
    bank = session.get(BankAccount, bank_account_id) if bank_account_id else None
    fund = box or bank
    if fund is None:
        raise NotFoundError("صندوق یا حساب بانکی مورد نظر یافت نشد.")
    query = (select(JournalLine, Journal)
             .join(Journal, Journal.id == JournalLine.journal_id)
             .where(JournalLine.account_id == fund.account_id,
                    Journal.status == AC.STATUS_POSTED)
             .order_by(Journal.entry_date, Journal.number, JournalLine.line_no))
    if date_from:
        query = query.where(Journal.entry_date >= date_from)
    if date_to:
        query = query.where(Journal.entry_date <= date_to)
    rows: list[dict] = []
    for line, journal in session.execute(query).all():
        rows.append({
            "journal_id": journal.id,
            "number": str(journal.number),
            "date": journal.entry_date,
            "title": journal.title_fa,
            "description": line.description or journal.title_fa,
            "in": Decimal(line.debit or 0),
            "out": Decimal(line.credit or 0),
        })
    return rows


def fund_balance(session: Session, *, cash_box_id: int | None = None,
                 bank_account_id: int | None = None) -> Decimal:
    """Opening balance of the fund plus every posted movement on its account.

    The opening balance is *not* posted to the ledger automatically (that would
    invent an entry the accountant never approved), so it is added here; a fund
    whose opening position was already entered as an opening journal must carry an
    opening balance of zero. ``fund_ledger_lines`` returns the movement side only.
    """
    box = session.get(CashBox, cash_box_id) if cash_box_id else None
    bank = session.get(BankAccount, bank_account_id) if bank_account_id else None
    fund = box or bank
    if fund is None:
        raise ValidationError("صندوق یا حساب بانکی را مشخص کنید.", field="fund")
    movement = sum((row["in"] - row["out"] for row in
                    fund_ledger_lines(session, cash_box_id=cash_box_id,
                                      bank_account_id=bank_account_id)), ZERO)
    return (Decimal(fund.opening_balance or 0) + movement).quantize(MONEY)


def assert_fund_available(session: Session, *, cash_box_id: int | None,
                          bank_account_id: int | None, amount: Decimal,
                          allow_negative: bool) -> None:
    """Refuse a payment/transfer that would push a fund below zero."""
    if allow_negative:
        return
    available = fund_balance(session, cash_box_id=cash_box_id,
                             bank_account_id=bank_account_id)
    if amount > available:
        raise ValidationError(
            f"موجودی قابل استفاده {available:,} است و پرداخت {amount:,} بیش از آن است. "
            "برای عبور از موجودی، سیاست «اجازه منفی شدن» و مجوز مربوط لازم است.",
            field="amount")


def allow_negative_funds(settings) -> bool:
    try:
        return bool(settings.snapshot().bool("treasury_allow_negative_fund"))
    except Exception:  # pragma: no cover - settings may be absent in tests
        return False


def alert_days(settings) -> int:
    try:
        return int(settings.snapshot().int("treasury_cheque_alert_days"))
    except Exception:  # pragma: no cover
        return 7


# ------------------------------------------------------------------ journal
def party_hint_account(session: Session, operation: str,
                       party_detail_id: int | None = None) -> int | None:
    """The account a party detail should attach to, read from the stored rule.

    ``build_entry`` attaches the detail account to the rule line whose account is
    the hint. When the document names a party we therefore return the *same*
    subsidiary account that party already belongs to - that is the only account a
    detail may legally carry, so a party can never be forced onto a fund line.
    Without a party we fall back to the rule's document-amount line.
    """
    from pars_erp.db.models import DetailAccount, PostingRule

    rule = session.execute(
        select(PostingRule).where(PostingRule.operation == operation,
                                  PostingRule.is_active.is_(True))).scalars().first()
    if rule is None:
        return None
    if party_detail_id:
        detail = session.get(DetailAccount, party_detail_id)
        if detail is None:
            return None
        for line in rule.lines:
            if line.amount_source in TC.DYNAMIC_SOURCES:
                continue
            if line.account_id == detail.account_id:
                return line.account_id
        return None
    for line in rule.lines:
        if line.amount_source == TC.SRC_AMOUNT:
            return line.account_id
    return None


def post_system_journal(session: Session, *, journals, ctx, entry_date: _dt.date,
                        title_fa: str, reference_no: str, idempotency_key: str,
                        notes: str, draft, source_kind: str,
                        source_id: int) -> Journal:
    """Create + post one journal from a posting-service draft, idempotently."""
    from pars_erp.services.journals_service import JournalInput, JournalLineInput

    data = JournalInput(
        entry_date=entry_date,
        title_fa=title_fa[:200],
        reference_no=reference_no,
        notes=notes or "",
        idempotency_key=idempotency_key,
        lines=tuple(JournalLineInput(account_id=line.account_id, debit=line.debit,
                                     credit=line.credit, description=line.description,
                                     detail_id=line.detail_id)
                    for line in draft.lines),
    )
    return journals.create_posted_system_entry(
        session, ctx=ctx, data=data, source_kind=source_kind, source_id=source_id)


def reverse_journal(session: Session, *, journals, journal_id: int | None, ctx,
                    title_fa: str, reference_no: str, idempotency_key: str,
                    reason: str, source_kind: str, source_id: int) -> Journal:
    """Post the mirror entry of an existing journal (the only allowed correction)."""
    if not journal_id:
        raise NotFoundError("سند حسابداری برای ابطال یافت نشد.")
    original = session.get(Journal, journal_id)
    if original is None:
        raise NotFoundError("سند حسابداری برای ابطال یافت نشد.")
    from pars_erp.services.journals_service import JournalInput, JournalLineInput

    lines = tuple(JournalLineInput(
        account_id=line.account_id, debit=line.credit, credit=line.debit,
        description=(f"برگشت: {line.description or ''}")[:300],
        detail_id=line.detail_id) for line in original.lines)
    return journals.create_posted_system_entry(
        session, ctx=ctx,
        data=JournalInput(entry_date=_dt.date.today(), title_fa=title_fa[:200],
                          reference_no=reference_no, idempotency_key=idempotency_key,
                          notes=reason, lines=lines),
        source_kind=source_kind, source_id=source_id)


# ---------------------------------------------------------------- sequencing
def receipt_number(session: Session, on_date: _dt.date) -> str:
    return next_document_number(session, Receipt, prefix="RCV", on_date=on_date)


def payment_number(session: Session, on_date: _dt.date) -> str:
    return next_document_number(session, Payment, prefix="PAY", on_date=on_date)


def transfer_number(session: Session, on_date: _dt.date) -> str:
    return next_document_number(session, FundTransfer, prefix="TRF", on_date=on_date)


def validate_status(current: str, target: str,
                    table: dict[str, tuple[str, ...]] | None = None) -> None:
    allowed = (table or TC.ALLOWED_TRANSITIONS).get(current, ())
    if target not in allowed:
        raise ConflictError(
            f"تغییر وضعیت از «{TC.STATUS_TITLES_FA.get(current, current)}» به "
            f"«{TC.STATUS_TITLES_FA.get(target, target)}» مجاز نیست.")
