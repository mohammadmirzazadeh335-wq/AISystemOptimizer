"""Receipts, payments, fund transfers and invoice settlement.

Every money document follows the same lifecycle:

``draft → approved → posted → (void)``

* **draft** can be edited freely;
* **approved** is frozen for editing but still has no ledger effect;
* **posted** writes exactly one balanced journal (idempotent by key) and, for
  receipts/payments, the settlement allocations that were validated first;
* **void** posts the mirror entry and never edits the original journal.

Balances are checked against the *fund* (cash box / bank account) and against the
open amount of every invoice, so a payment can never spend money the fund does
not hold and a settlement can never exceed what the invoice still owes.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    BankAccount,
    CashBox,
    Cheque,
    DetailAccount,
    FundTransfer,
    Invoice,
    Payment,
    Receipt,
    SettlementAllocation,
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
    allow_negative_funds,
    assert_fund_available,
    fund_account_id,
    fund_label,
    party_hint_account,
    payment_number,
    post_system_journal,
    receipt_number,
    resolve_fund,
    reverse_journal,
    transfer_number,
    validate_status,
)
from pars_erp.treasury import constants as TC

MONEY = Decimal("0.01")
VOUCHER_RECEIPT = "receipt"
VOUCHER_PAYMENT = "payment"


# --------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class AllocationInput:
    invoice_id: int
    amount: Decimal | str | int
    note: str = ""


@dataclass(frozen=True)
class ReceiptInput:
    receipt_date: _dt.date
    amount: Decimal | str | int
    receipt_type: str = TC.RECEIPT_CUSTOMER
    method: str = TC.METHOD_CASH
    cash_box_id: int | None = None
    bank_account_id: int | None = None
    payer_detail_id: int | None = None
    payer_name: str = ""
    counter_account_id: int | None = None
    currency_code: str = "IRR"
    exchange_rate: Decimal | str | int = 1
    tracking_no: str = ""
    reference_no: str = ""
    description: str = ""
    attachment_path: str = ""
    cheque: "ChequeInput | None" = None
    allocations: tuple[AllocationInput, ...] = ()
    idempotency_key: str | None = None


@dataclass(frozen=True)
class PaymentInput:
    payment_date: _dt.date
    amount: Decimal | str | int
    payment_type: str = TC.PAYMENT_SUPPLIER
    method: str = TC.METHOD_CASH
    cash_box_id: int | None = None
    bank_account_id: int | None = None
    payee_detail_id: int | None = None
    payee_name: str = ""
    counter_account_id: int | None = None
    currency_code: str = "IRR"
    exchange_rate: Decimal | str | int = 1
    tracking_no: str = ""
    reference_no: str = ""
    description: str = ""
    attachment_path: str = ""
    cheque: "ChequeInput | None" = None
    allocations: tuple[AllocationInput, ...] = ()
    idempotency_key: str | None = None


@dataclass(frozen=True)
class TransferInput:
    transfer_date: _dt.date
    amount: Decimal | str | int
    from_cash_box_id: int | None = None
    from_bank_account_id: int | None = None
    to_cash_box_id: int | None = None
    to_bank_account_id: int | None = None
    fee: Decimal | str | int = 0
    tracking_no: str = ""
    description: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ChequeInput:
    """A cheque that is born together with its receipt/payment."""

    number: str
    bank_name: str
    amount: Decimal | str | int
    issue_date: _dt.date
    due_date: _dt.date
    branch_name: str = ""
    account_number: str = ""
    holder_name: str = ""
    cheque_book_id: int | None = None
    description: str = ""
    attachment_path: str = ""


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class VoucherRow:
    id: int
    kind: str
    number: str
    voucher_date: _dt.date
    type_code: str
    type_fa: str
    method: str
    method_fa: str
    fund_kind: str
    fund_label: str
    party_name: str
    party_detail_id: int | None
    amount: Decimal
    currency_code: str
    exchange_rate: Decimal
    base_amount: Decimal
    status: str
    status_fa: str
    tracking_no: str
    reference_no: str
    description: str
    attachment_path: str
    journal_id: int | None
    cheque_id: int | None
    settlement_total: Decimal

    @property
    def display(self) -> str:
        return f"{self.number} — {self.party_name or self.type_fa}"

    @property
    def is_editable(self) -> bool:
        return self.status == TC.STATUS_DRAFT

    @property
    def is_posted(self) -> bool:
        return self.status == TC.STATUS_POSTED

    @property
    def outstanding(self) -> Decimal:
        return (self.base_amount - self.settlement_total).quantize(MONEY)


@dataclass(frozen=True)
class TransferRow:
    id: int
    number: str
    transfer_date: _dt.date
    from_label: str
    to_label: str
    amount: Decimal
    fee: Decimal
    tracking_no: str
    description: str
    status: str
    status_fa: str
    journal_id: int | None

    @property
    def display(self) -> str:
        return f"{self.number} — {self.from_label} ← {self.to_label}"

    @property
    def is_posted(self) -> bool:
        return self.status == TC.STATUS_POSTED


@dataclass(frozen=True)
class OpenInvoiceRow:
    """An invoice with the amount that is still open, for the settlement form."""

    id: int
    number: str
    kind: str
    kind_fa: str
    invoice_date: _dt.date
    party_detail_id: int
    party_name: str
    net_total: Decimal
    settled: Decimal
    returned: Decimal

    @property
    def open_amount(self) -> Decimal:
        value = Decimal(self.net_total) - Decimal(self.settled) - Decimal(self.returned)
        return value.quantize(MONEY) if value > 0 else ZERO

    @property
    def is_partial(self) -> bool:
        return ZERO < Decimal(self.settled) < Decimal(self.net_total)

    @property
    def display(self) -> str:
        return f"{self.number} — {self.party_name} — مانده {self.open_amount:,}"


# --------------------------------------------------------------- the service
class VoucherService:
    def __init__(self, db: Database, audit: AuditService, *, journals, inventory=None,
                 cheques=None, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.journals = journals
        self.settings = settings
        self.cheques = cheques

    # ---------------------------------------------------------------- numbering
    def next_receipt_number(self, ctx: SecurityContext | None,
                            on_date: _dt.date | None = None) -> str:
        require_permission(ctx, "receipts.view")
        with self.db.session_scope() as session:
            return receipt_number(session, on_date or _dt.date.today())

    def next_payment_number(self, ctx: SecurityContext | None,
                            on_date: _dt.date | None = None) -> str:
        require_permission(ctx, "payments.view")
        with self.db.session_scope() as session:
            return payment_number(session, on_date or _dt.date.today())

    # ------------------------------------------------------------------ listing
    def list_receipts(self, ctx: SecurityContext | None, *,
                      date_from: _dt.date | None = None, date_to: _dt.date | None = None,
                      status: str | None = None, receipt_type: str | None = None,
                      fund: str | None = None, search: str | None = None,
                      limit: int = 500) -> list[VoucherRow]:
        require_permission(ctx, "receipts.view")
        query = select(Receipt).order_by(Receipt.receipt_date.desc(), Receipt.id.desc())
        query = self._filter_documents(query, Receipt.receipt_date, Receipt.number,
                                      Receipt.status, search, date_from, date_to, status)
        if receipt_type:
            query = query.where(Receipt.receipt_type == receipt_type)
        if fund == TC.FUND_CASH:
            query = query.where(Receipt.cash_box_id.is_not(None))
        elif fund == TC.FUND_BANK:
            query = query.where(Receipt.bank_account_id.is_not(None))
        with self.db.session_scope() as session:
            return [self._receipt_row(session, row)
                    for row in session.execute(query.limit(limit)).scalars()]

    def list_payments(self, ctx: SecurityContext | None, *,
                      date_from: _dt.date | None = None, date_to: _dt.date | None = None,
                      status: str | None = None, payment_type: str | None = None,
                      fund: str | None = None, search: str | None = None,
                      limit: int = 500) -> list[VoucherRow]:
        require_permission(ctx, "payments.view")
        query = select(Payment).order_by(Payment.payment_date.desc(), Payment.id.desc())
        query = self._filter_documents(query, Payment.payment_date, Payment.number,
                                      Payment.status, search, date_from, date_to, status)
        if payment_type:
            query = query.where(Payment.payment_type == payment_type)
        if fund == TC.FUND_CASH:
            query = query.where(Payment.cash_box_id.is_not(None))
        elif fund == TC.FUND_BANK:
            query = query.where(Payment.bank_account_id.is_not(None))
        with self.db.session_scope() as session:
            return [self._payment_row(session, row)
                    for row in session.execute(query.limit(limit)).scalars()]

    def get_receipt(self, ctx: SecurityContext | None, receipt_id: int) -> VoucherRow:
        require_permission(ctx, "receipts.view")
        with self.db.session_scope() as session:
            return self._receipt_row(session, get_or_404(
                session, Receipt, receipt_id, "رسید دریافت یافت نشد."))

    def get_payment(self, ctx: SecurityContext | None, payment_id: int) -> VoucherRow:
        require_permission(ctx, "payments.view")
        with self.db.session_scope() as session:
            return self._payment_row(session, get_or_404(
                session, Payment, payment_id, "سند پرداخت یافت نشد."))

    # ------------------------------------------------------------------ receipts
    def create_receipt(self, ctx: SecurityContext | None, data: ReceiptInput) -> VoucherRow:
        require_permission(ctx, "receipts.create")
        with self.db.session_scope() as session:
            receipt = Receipt(number=receipt_number(session, data.receipt_date))
            self._apply_receipt(session, receipt, data, ctx)
            session.add(receipt)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("ثبت شمارهٔ رسید با خطا مواجه شد؛ دوباره تلاش کنید.") from exc
            self._store_allocations(session, receipt, VOUCHER_RECEIPT, data, ctx)
            if data.cheque is not None:
                receipt.cheque_id = self._create_cheque(
                    session, data.cheque, ctx, direction=TC.CHEQUE_RECEIVED,
                    party_detail_id=receipt.payer_detail_id,
                    amount=Decimal(receipt.amount)).id
                session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="receipt", entity_id=receipt.id, action="create",
                summary_fa=f"ثبت رسید دریافت {receipt.number}",
                after={"amount": str(receipt.amount), "fund": receipt.fund_kind},
                session=session)
            return self._receipt_row(session, receipt)

    def update_receipt(self, ctx: SecurityContext | None, receipt_id: int,
                       data: ReceiptInput) -> VoucherRow:
        require_permission(ctx, "receipts.create")
        with self.db.session_scope() as session:
            receipt = get_or_404(session, Receipt, receipt_id, "رسید دریافت یافت نشد.")
            self._assert_editable(receipt)
            for row in session.execute(select(SettlementAllocation).where(
                    SettlementAllocation.voucher_kind == VOUCHER_RECEIPT,
                    SettlementAllocation.voucher_id == receipt.id)).scalars():
                session.delete(row)
            session.flush()
            self._apply_receipt(session, receipt, data, ctx)
            session.flush()
            self._store_allocations(session, receipt, VOUCHER_RECEIPT, data, ctx)
            self.audit.log_audit(
                ctx=ctx, entity_type="receipt", entity_id=receipt.id, action="update",
                summary_fa=f"ویرایش رسید دریافت {receipt.number}", session=session)
            return self._receipt_row(session, receipt)

    # ------------------------------------------------------------------ payments
    def create_payment(self, ctx: SecurityContext | None, data: PaymentInput) -> VoucherRow:
        require_permission(ctx, "payments.create")
        with self.db.session_scope() as session:
            payment = Payment(number=payment_number(session, data.payment_date))
            self._apply_payment(session, payment, data, ctx)
            session.add(payment)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("ثبت شمارهٔ سند پرداخت با خطا مواجه شد.") from exc
            self._store_allocations(session, payment, VOUCHER_PAYMENT, data, ctx)
            if data.cheque is not None:
                payment.cheque_id = self._create_cheque(
                    session, data.cheque, ctx, direction=TC.CHEQUE_ISSUED,
                    party_detail_id=payment.payee_detail_id,
                    amount=Decimal(payment.amount),
                    bank_account_id=payment.bank_account_id).id
                session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="payment", entity_id=payment.id, action="create",
                summary_fa=f"ثبت سند پرداخت {payment.number}",
                after={"amount": str(payment.amount), "fund": payment.fund_kind},
                session=session)
            return self._payment_row(session, payment)

    def update_payment(self, ctx: SecurityContext | None, payment_id: int,
                       data: PaymentInput) -> VoucherRow:
        require_permission(ctx, "payments.create")
        with self.db.session_scope() as session:
            payment = get_or_404(session, Payment, payment_id, "سند پرداخت یافت نشد.")
            self._assert_editable(payment)
            for row in session.execute(select(SettlementAllocation).where(
                    SettlementAllocation.voucher_kind == VOUCHER_PAYMENT,
                    SettlementAllocation.voucher_id == payment.id)).scalars():
                session.delete(row)
            session.flush()
            self._apply_payment(session, payment, data, ctx)
            session.flush()
            self._store_allocations(session, payment, VOUCHER_PAYMENT, data, ctx)
            self.audit.log_audit(
                ctx=ctx, entity_type="payment", entity_id=payment.id, action="update",
                summary_fa=f"ویرایش سند پرداخت {payment.number}", session=session)
            return self._payment_row(session, payment)

    # ------------------------------------------------------------------ lifecycle
    def approve_receipt(self, ctx: SecurityContext | None, receipt_id: int) -> VoucherRow:
        require_permission(ctx, "vouchers.approve")
        with self.db.session_scope() as session:
            receipt = get_or_404(session, Receipt, receipt_id, "رسید دریافت یافت نشد.")
            validate_status(receipt.status, TC.STATUS_APPROVED)
            receipt.status = TC.STATUS_APPROVED
            receipt.approved_by_id = getattr(ctx, "user_id", None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="receipt", entity_id=receipt.id, action="approve",
                summary_fa=f"تأیید رسید دریافت {receipt.number}", session=session)
            return self._receipt_row(session, receipt)

    def approve_payment(self, ctx: SecurityContext | None, payment_id: int) -> VoucherRow:
        require_permission(ctx, "vouchers.approve")
        with self.db.session_scope() as session:
            payment = get_or_404(session, Payment, payment_id, "سند پرداخت یافت نشد.")
            validate_status(payment.status, TC.STATUS_APPROVED)
            payment.status = TC.STATUS_APPROVED
            payment.approved_by_id = getattr(ctx, "user_id", None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="payment", entity_id=payment.id, action="approve",
                summary_fa=f"تأیید سند پرداخت {payment.number}", session=session)
            return self._payment_row(session, payment)

    def post_receipt(self, ctx: SecurityContext | None, receipt_id: int) -> VoucherRow:
        require_permission(ctx, "vouchers.post")
        with self.db.session_scope() as session:
            receipt = get_or_404(session, Receipt, receipt_id, "رسید دریافت یافت نشد.")
            if receipt.status == TC.STATUS_POSTED:
                return self._receipt_row(session, receipt)  # idempotent
            validate_status(receipt.status, TC.STATUS_POSTED)
            self._post_receipt_in_session(session, receipt, ctx)
            return self._receipt_row(session, receipt)

    def post_payment(self, ctx: SecurityContext | None, payment_id: int) -> VoucherRow:
        require_permission(ctx, "vouchers.post")
        with self.db.session_scope() as session:
            payment = get_or_404(session, Payment, payment_id, "سند پرداخت یافت نشد.")
            if payment.status == TC.STATUS_POSTED:
                return self._payment_row(session, payment)
            validate_status(payment.status, TC.STATUS_POSTED)
            self._post_payment_in_session(session, payment, ctx)
            return self._payment_row(session, payment)

    def void_receipt(self, ctx: SecurityContext | None, receipt_id: int,
                     reason: str) -> VoucherRow:
        require_permission(ctx, "vouchers.post")
        reason = clean_text(reason, field="reason", label="دلیل ابطال", required=True,
                            max_length=300)
        if len(reason) < 5:
            raise ValidationError("دلیل ابطال باید حداقل ۵ نویسه باشد.", field="reason")
        with self.db.session_scope() as session:
            receipt = get_or_404(session, Receipt, receipt_id, "رسید دریافت یافت نشد.")
            validate_status(receipt.status, TC.STATUS_VOID)
            if receipt.status == TC.STATUS_POSTED:
                receipt.journal_id = self._reverse(session, receipt.journal_id, ctx,
                                                  f"ابطال رسید دریافت {receipt.number}",
                                                  receipt.number,
                                                  f"receipt:{receipt.id}:void", reason,
                                                  "receipt_void", receipt.id)
            receipt.status = TC.STATUS_VOID
            receipt.void_reason = reason
            if receipt.cheque_id:
                cheque = session.get(Cheque, receipt.cheque_id)
                if cheque is not None and cheque.status not in (TC.CHQ_BOUNCED,
                                                               TC.CHQ_CANCELLED):
                    cheque.status = TC.CHQ_CANCELLED
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="receipt", entity_id=receipt.id, action="void",
                summary_fa=f"ابطال رسید دریافت {receipt.number}", after={"reason": reason},
                session=session)
            return self._receipt_row(session, receipt)

    def void_payment(self, ctx: SecurityContext | None, payment_id: int,
                     reason: str) -> VoucherRow:
        require_permission(ctx, "vouchers.post")
        reason = clean_text(reason, field="reason", label="دلیل ابطال", required=True,
                            max_length=300)
        if len(reason) < 5:
            raise ValidationError("دلیل ابطال باید حداقل ۵ نویسه باشد.", field="reason")
        with self.db.session_scope() as session:
            payment = get_or_404(session, Payment, payment_id, "سند پرداخت یافت نشد.")
            validate_status(payment.status, TC.STATUS_VOID)
            if payment.status == TC.STATUS_POSTED:
                payment.journal_id = self._reverse(session, payment.journal_id, ctx,
                                                  f"ابطال سند پرداخت {payment.number}",
                                                  payment.number,
                                                  f"payment:{payment.id}:void", reason,
                                                  "payment_void", payment.id)
            payment.status = TC.STATUS_VOID
            payment.void_reason = reason
            if payment.cheque_id:
                cheque = session.get(Cheque, payment.cheque_id)
                if cheque is not None and cheque.status not in (TC.CHQ_PAID,):
                    cheque.status = TC.CHQ_CANCELLED
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="payment", entity_id=payment.id, action="void",
                summary_fa=f"ابطال سند پرداخت {payment.number}", after={"reason": reason},
                session=session)
            return self._payment_row(session, payment)

    # ------------------------------------------------------------------ transfers
    def create_transfer(self, ctx: SecurityContext | None,
                        data: TransferInput) -> TransferRow:
        require_permission(ctx, "transfers.create")
        with self.db.session_scope() as session:
            payload = self._validated_transfer(session, data)
            transfer = FundTransfer(number=transfer_number(session, data.transfer_date),
                                    **payload)
            session.add(transfer)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="fund_transfer", entity_id=transfer.id, action="create",
                summary_fa=f"ثبت انتقال وجه {transfer.number}",
                after={"amount": str(transfer.amount)}, session=session)
            return self._transfer_row(session, transfer)

    def post_transfer(self, ctx: SecurityContext | None, transfer_id: int) -> TransferRow:
        require_permission(ctx, "vouchers.post")
        with self.db.session_scope() as session:
            transfer = get_or_404(session, FundTransfer, transfer_id,
                                  "سند انتقال وجه یافت نشد.")
            if transfer.status == TC.STATUS_POSTED:
                return self._transfer_row(session, transfer)
            validate_status(transfer.status, TC.STATUS_POSTED, TC.TRANSFER_TRANSITIONS)
            from_cash = (session.get(CashBox, transfer.from_cash_box_id)
                         if transfer.from_cash_box_id else None)
            from_bank = (session.get(BankAccount, transfer.from_bank_account_id)
                         if transfer.from_bank_account_id else None)
            to_cash = (session.get(CashBox, transfer.to_cash_box_id)
                       if transfer.to_cash_box_id else None)
            to_bank = (session.get(BankAccount, transfer.to_bank_account_id)
                       if transfer.to_bank_account_id else None)
            components = {
                TC.SRC_FUND_TO: Decimal(transfer.amount),
                TC.SRC_FEE: Decimal(transfer.fee),
                TC.SRC_FUND_FROM: Decimal(transfer.amount) + Decimal(transfer.fee),
            }
            draft = self._posting().build_entry(
                session, operation=TC.POSTING_TRANSFER, components=components,
                party_detail_id=None, party_account_hint_id=None,
                description=f"انتقال وجه {transfer.number}",
                dynamic_accounts={TC.SRC_FUND_FROM: fund_account_id(from_cash, from_bank),
                                  TC.SRC_FUND_TO: fund_account_id(to_cash, to_bank)})
            transfer.journal_id = post_system_journal(
                session, journals=self.journals, ctx=ctx,
                entry_date=transfer.transfer_date,
                title_fa=f"انتقال وجه {transfer.number}", reference_no=transfer.number,
                idempotency_key=f"transfer:{transfer.id}:journal",
                notes=transfer.description or "", draft=draft,
                source_kind="fund_transfer", source_id=transfer.id).id
            transfer.status = TC.STATUS_POSTED
            transfer.posted_at = _dt.datetime.now(_dt.timezone.utc)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="fund_transfer", entity_id=transfer.id, action="post",
                summary_fa=f"ثبت نهایی انتقال وجه {transfer.number}", session=session)
            return self._transfer_row(session, transfer)

    def list_transfers(self, ctx: SecurityContext | None, *,
                       date_from: _dt.date | None = None, date_to: _dt.date | None = None,
                       status: str | None = None, search: str | None = None,
                       limit: int = 500) -> list[TransferRow]:
        require_permission(ctx, "treasury.reports")
        query = select(FundTransfer).order_by(FundTransfer.transfer_date.desc(),
                                              FundTransfer.id.desc())
        query = self._filter_documents(query, FundTransfer.transfer_date,
                                       FundTransfer.number, FundTransfer.status, search,
                                       date_from, date_to, status)
        with self.db.session_scope() as session:
            return [self._transfer_row(session, row)
                    for row in session.execute(query.limit(limit)).scalars()]

    # ---------------------------------------------------------------- settlement
    def open_invoices(self, ctx: SecurityContext | None, *, direction: str,
                      party_detail_id: int | None = None,
                      limit: int = 500) -> list[OpenInvoiceRow]:
        """Invoices of ``direction`` (receipt→sale, payment→purchase) still open."""
        require_permission(ctx, "settlements.manage")
        kinds = ((CC.INVOICE_SALE,) if direction == VOUCHER_RECEIPT
                 else (CC.INVOICE_PURCHASE,))
        require_permission(ctx, "sales.reports" if direction == VOUCHER_RECEIPT
                           else "purchase.reports")
        with self.db.session_scope() as session:
            query = select(Invoice).where(Invoice.kind.in_(kinds),
                                          Invoice.status == CC.STATUS_POSTED)
            if party_detail_id:
                query = query.where(Invoice.party_detail_id == party_detail_id)
            invoices = list(session.execute(
                query.order_by(Invoice.invoice_date, Invoice.id)).scalars())
            rows: list[OpenInvoiceRow] = []
            for invoice in invoices:
                settled = self._settled(session, invoice.id)
                returned = self._returned(session, invoice)
                row = OpenInvoiceRow(
                    id=invoice.id, number=invoice.number, kind=invoice.kind,
                    kind_fa=CC.INVOICE_TITLES_FA.get(invoice.kind, invoice.kind),
                    invoice_date=invoice.invoice_date,
                    party_detail_id=invoice.party_detail_id,
                    party_name=self._party_name(session, invoice.party_detail_id),
                    net_total=Decimal(invoice.net_total), settled=settled,
                    returned=returned)
                if row.open_amount > 0:
                    rows.append(row)
            return rows[:limit]

    def allocations_of(self, ctx: SecurityContext | None, kind: str,
                       voucher_id: int) -> list[dict]:
        require_permission(ctx, "settlements.manage")
        with self.db.session_scope() as session:
            rows = session.execute(select(SettlementAllocation).where(
                SettlementAllocation.voucher_kind == kind,
                SettlementAllocation.voucher_id == voucher_id)).scalars()
            return [{"invoice_id": row.invoice_id,
                     "number": (session.get(Invoice, row.invoice_id).number
                                if session.get(Invoice, row.invoice_id) else ""),
                     "amount": Decimal(row.amount), "note": row.note or ""}
                    for row in rows]

    # ------------------------------------------------------------------ posting
    def _post_receipt_in_session(self, session, receipt: Receipt,
                                 ctx: SecurityContext | None) -> None:
        box = session.get(CashBox, receipt.cash_box_id) if receipt.cash_box_id else None
        bank = (session.get(BankAccount, receipt.bank_account_id)
                if receipt.bank_account_id else None)
        operation = self._receipt_operation(receipt)
        components = {TC.SRC_AMOUNT: Decimal(receipt.base_amount),
                      TC.SRC_FUND: Decimal(receipt.base_amount)}
        hint = party_hint_account(session, operation, receipt.payer_detail_id)
        draft = self._posting().build_entry(
            session, operation=operation, components=components,
            party_detail_id=receipt.payer_detail_id, party_account_hint_id=hint,
            description=f"رسید دریافت {receipt.number}",
            dynamic_accounts={TC.SRC_FUND: fund_account_id(box, bank)},
            counter_account_id=receipt.counter_account_id)
        receipt.journal_id = post_system_journal(
            session, journals=self.journals, ctx=ctx,
            entry_date=receipt.receipt_date,
            title_fa=f"دریافت وجه {receipt.number}"
                     + (f" — {receipt.payer_name}" if receipt.payer_name else ""),
            reference_no=receipt.number,
            idempotency_key=f"receipt:{receipt.id}:journal",
            notes=receipt.description or "", draft=draft,
            source_kind="receipt", source_id=receipt.id).id
        receipt.status = TC.STATUS_POSTED
        receipt.posted_at = _dt.datetime.now(_dt.timezone.utc)
        receipt.posted_by_id = getattr(ctx, "user_id", None)
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="receipt", entity_id=receipt.id, action="post",
            summary_fa=f"ثبت نهایی رسید دریافت {receipt.number}",
            after={"journal_id": receipt.journal_id}, session=session)

    def _post_payment_in_session(self, session, payment: Payment,
                                 ctx: SecurityContext | None) -> None:
        box = session.get(CashBox, payment.cash_box_id) if payment.cash_box_id else None
        bank = (session.get(BankAccount, payment.bank_account_id)
                if payment.bank_account_id else None)
        operation = self._payment_operation(payment)
        components = {TC.SRC_AMOUNT: Decimal(payment.base_amount),
                      TC.SRC_FUND: Decimal(payment.base_amount)}
        hint = party_hint_account(session, operation, payment.payee_detail_id)
        dynamic = {}
        if operation != TC.POSTING_PAYMENT_CHEQUE:
            dynamic[TC.SRC_FUND] = fund_account_id(box, bank)
        draft = self._posting().build_entry(
            session, operation=operation, components=components,
            party_detail_id=payment.payee_detail_id if payment.payment_type
            in (TC.PAYMENT_SUPPLIER, TC.PAYMENT_ADVANCE) else None,
            party_account_hint_id=hint,
            description=f"سند پرداخت {payment.number}",
            dynamic_accounts=dynamic, counter_account_id=payment.counter_account_id)
        payment.journal_id = post_system_journal(
            session, journals=self.journals, ctx=ctx,
            entry_date=payment.payment_date,
            title_fa=f"پرداخت وجه {payment.number}"
                     + (f" — {payment.payee_name}" if payment.payee_name else ""),
            reference_no=payment.number,
            idempotency_key=f"payment:{payment.id}:journal",
            notes=payment.description or "", draft=draft,
            source_kind="payment", source_id=payment.id).id
        payment.status = TC.STATUS_POSTED
        payment.posted_at = _dt.datetime.now(_dt.timezone.utc)
        payment.posted_by_id = getattr(ctx, "user_id", None)
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="payment", entity_id=payment.id, action="post",
            summary_fa=f"ثبت نهایی سند پرداخت {payment.number}",
            after={"journal_id": payment.journal_id}, session=session)

    def _reverse(self, session, journal_id: int | None, ctx, title: str, reference: str,
                 key: str, reason: str, source_kind: str, source_id: int) -> int | None:
        journal = reverse_journal(session, journals=self.journals, journal_id=journal_id,
                                  ctx=ctx, title_fa=title, reference_no=reference,
                                  idempotency_key=key, reason=reason,
                                  source_kind=source_kind, source_id=source_id)
        return journal.id

    # -------------------------------------------------------------- validation
    def _apply_receipt(self, session, receipt: Receipt, data: ReceiptInput,
                       ctx: SecurityContext | None) -> None:
        fund_kind, box, bank = resolve_fund(session, cash_box_id=data.cash_box_id,
                                            bank_account_id=data.bank_account_id)
        amount = to_money(data.amount, field="amount")
        if amount <= 0:
            raise ValidationError("مبلغ دریافت باید بزرگ‌تر از صفر باشد.", field="amount")
        rate = self._rate(data.exchange_rate)
        if data.receipt_type not in dict(TC.RECEIPT_TYPES):
            raise ValidationError("نوع دریافت معتبر نیست.", field="receipt_type")
        if data.method not in dict(TC.RECEIPT_METHODS):
            raise ValidationError("روش دریافت معتبر نیست.", field="method")
        if box is not None:
            self._funds().assert_cash_box_allowed(session, ctx, box)
        payer_detail_id = data.payer_detail_id
        if payer_detail_id:
            get_or_404(session, DetailAccount, payer_detail_id, "شخص دریافت‌کننده یافت نشد.")
        if data.receipt_type == TC.RECEIPT_CUSTOMER and not payer_detail_id:
            raise ValidationError("برای «دریافت از مشتری» شخص را انتخاب کنید.",
                                  field="payer_detail_id")
        counter_account_id = data.counter_account_id
        if counter_account_id:
            self._subsidiary_account(session, counter_account_id)
        if data.method == TC.METHOD_CHEQUE and data.cheque is None:
            raise ValidationError("برای دریافت با چک، اطلاعات چک را وارد کنید.", field="cheque")
        receipt.receipt_date = data.receipt_date
        receipt.receipt_type = data.receipt_type
        receipt.method = data.method
        receipt.fund_kind = TC.FUND_CHEQUE if data.cheque is not None else fund_kind
        receipt.payer_detail_id = payer_detail_id
        receipt.payer_name = clean_text(data.payer_name or self._party_name(session, payer_detail_id),
                                        field="payer_name", label="پرداخت‌کننده", max_length=160)
        receipt.amount = amount
        receipt.currency_code = (data.currency_code or "IRR").strip().upper()[:8]
        receipt.exchange_rate = rate
        receipt.base_amount = (amount * rate).quantize(MONEY)
        receipt.cash_box_id = box.id if box else None
        receipt.bank_account_id = bank.id if bank else None
        receipt.counter_account_id = counter_account_id
        receipt.tracking_no = clean_text(data.tracking_no, field="tracking_no",
                                         label="شماره پیگیری", max_length=60)
        receipt.reference_no = clean_text(data.reference_no, field="reference_no",
                                          label="شماره مرجع", max_length=60)
        receipt.description = clean_text(data.description, field="description",
                                         label="شرح", max_length=500)
        receipt.attachment_path = clean_text(data.attachment_path, field="attachment_path",
                                             label="پیوست", max_length=500)
        receipt.idempotency_key = (data.idempotency_key or "").strip() or None
        receipt.created_by_id = getattr(ctx, "user_id", None)

    def _store_allocations(self, session, voucher, kind: str, data, ctx) -> None:
        self._apply_allocations(session, voucher, kind, data.allocations, ctx,
                                direction=kind, party_detail_id=(
                                    voucher.payer_detail_id if kind == VOUCHER_RECEIPT
                                    else voucher.payee_detail_id))
        # the session is autoflush=False, so flush explicitly: the returned row
        # and every later check read the allocations back from the database
        session.flush()

    def _apply_payment(self, session, payment: Payment, data: PaymentInput,
                       ctx: SecurityContext | None) -> None:
        fund_kind, box, bank = resolve_fund(session, cash_box_id=data.cash_box_id,
                                            bank_account_id=data.bank_account_id)
        amount = to_money(data.amount, field="amount")
        if amount <= 0:
            raise ValidationError("مبلغ پرداخت باید بزرگ‌تر از صفر باشد.", field="amount")
        rate = self._rate(data.exchange_rate)
        if data.payment_type not in dict(TC.PAYMENT_TYPES):
            raise ValidationError("نوع پرداخت معتبر نیست.", field="payment_type")
        if data.method not in dict(TC.PAYMENT_METHODS):
            raise ValidationError("روش پرداخت معتبر نیست.", field="method")
        if box is not None:
            self._funds().assert_cash_box_allowed(session, ctx, box)
        payee_detail_id = data.payee_detail_id
        if payee_detail_id:
            get_or_404(session, DetailAccount, payee_detail_id, "شخص دریافت‌کننده وجه یافت نشد.")
        if data.payment_type == TC.PAYMENT_SUPPLIER and not payee_detail_id:
            raise ValidationError("برای «پرداخت به تأمین‌کننده» تأمین‌کننده را انتخاب کنید.",
                                  field="payee_detail_id")
        counter_account_id = data.counter_account_id
        if data.payment_type in (TC.PAYMENT_EXPENSE, TC.PAYMENT_SALARY) and not counter_account_id:
            raise ValidationError("برای پرداخت هزینه/حقوق، حساب هزینه را انتخاب کنید.",
                                  field="counter_account_id")
        if counter_account_id:
            self._subsidiary_account(session, counter_account_id)
        if data.method == TC.METHOD_CHEQUE:
            if data.cheque is None:
                raise ValidationError("برای پرداخت با چک، اطلاعات چک را وارد کنید.",
                                      field="cheque")
        else:
            assert_fund_available(session, cash_box_id=box.id if box else None,
                                  bank_account_id=bank.id if bank else None,
                                  amount=(amount * rate).quantize(MONEY),
                                  allow_negative=allow_negative_funds(self.settings))
        payment.payment_date = data.payment_date
        payment.payment_type = data.payment_type
        payment.method = data.method
        payment.fund_kind = TC.FUND_CHEQUE if data.cheque is not None else fund_kind
        payment.payee_detail_id = payee_detail_id
        payment.payee_name = clean_text(data.payee_name or self._party_name(session, payee_detail_id),
                                        field="payee_name", label="دریافت‌کننده وجه", max_length=160)
        payment.amount = amount
        payment.currency_code = (data.currency_code or "IRR").strip().upper()[:8]
        payment.exchange_rate = rate
        payment.base_amount = (amount * rate).quantize(MONEY)
        payment.cash_box_id = box.id if box else None
        payment.bank_account_id = bank.id if bank else None
        payment.counter_account_id = counter_account_id
        payment.tracking_no = clean_text(data.tracking_no, field="tracking_no",
                                         label="شماره پیگیری", max_length=60)
        payment.reference_no = clean_text(data.reference_no, field="reference_no",
                                          label="شماره مرجع", max_length=60)
        payment.description = clean_text(data.description, field="description",
                                         label="شرح", max_length=500)
        payment.attachment_path = clean_text(data.attachment_path, field="attachment_path",
                                             label="پیوست", max_length=500)
        payment.idempotency_key = (data.idempotency_key or "").strip() or None
        payment.created_by_id = getattr(ctx, "user_id", None)

    def _apply_allocations(self, session, voucher, kind: str,
                           allocations: tuple[AllocationInput, ...], ctx,
                           *, direction: str, party_detail_id: int | None) -> None:
        cleaned: list[tuple[Invoice, Decimal]] = []
        seen: set[int] = set()
        for entry in allocations:
            amount = to_money(entry.amount, field="allocation")
            if amount <= 0:
                continue
            if entry.invoice_id in seen:
                raise ValidationError("یک فاکتور را نمی‌توان دو بار در یک سند تسویه کرد.",
                                      field="allocations")
            seen.add(entry.invoice_id)
            invoice = get_or_404(session, Invoice, entry.invoice_id, "فاکتور یافت نشد.")
            expected = (CC.INVOICE_SALE if direction == VOUCHER_RECEIPT
                        else CC.INVOICE_PURCHASE)
            if invoice.kind != expected:
                raise ValidationError(
                    f"فاکتور «{invoice.number}» از نوع مناسب برای این سند نیست.",
                    field="allocations")
            if invoice.status != CC.STATUS_POSTED:
                raise ValidationError(
                    f"فقط فاکتور ثبت‌شده قابل تسویه است (فاکتور {invoice.number}).",
                    field="allocations")
            if party_detail_id and invoice.party_detail_id != party_detail_id:
                raise ValidationError(
                    f"فاکتور «{invoice.number}» به این شخص تعلق ندارد.", field="allocations")
            open_amount = (Decimal(invoice.net_total)
                           - self._settled(session, invoice.id)
                           - self._returned(session, invoice))
            if amount > open_amount:
                raise ValidationError(
                    f"مبلغ تسویه فاکتور «{invoice.number}» بیش از ماندهٔ آن است "
                    f"(مانده: {open_amount:,}).", field="allocations")
            cleaned.append((invoice, amount))
        total = sum((amount for _invoice, amount in cleaned), ZERO)
        if total > Decimal(voucher.base_amount or 0):
            raise ValidationError(
                f"جمع تسویه‌ها ({total:,}) از مبلغ سند ({voucher.base_amount:,}) بیشتر است.",
                field="allocations")
        for invoice, amount in cleaned:
            session.add(SettlementAllocation(
                voucher_kind=kind, voucher_id=voucher.id or 0, invoice_id=invoice.id,
                amount=amount,
                note=next((e.note for e in allocations if e.invoice_id == invoice.id), ""),
                created_at=_dt.datetime.now(_dt.timezone.utc),
                created_by_id=getattr(ctx, "user_id", None)))

    def _validated_transfer(self, session, data: TransferInput) -> dict:
        amount = to_money(data.amount, field="amount")
        if amount <= 0:
            raise ValidationError("مبلغ انتقال باید بزرگ‌تر از صفر باشد.", field="amount")
        fee = to_money(data.fee, field="fee")
        from_kind, from_box, from_bank = resolve_fund(
            session, cash_box_id=data.from_cash_box_id,
            bank_account_id=data.from_bank_account_id)
        to_kind, to_box, to_bank = resolve_fund(
            session, cash_box_id=data.to_cash_box_id,
            bank_account_id=data.to_bank_account_id)
        if (from_box is not None and to_box is not None and from_box.id == to_box.id) or \
           (from_bank is not None and to_bank is not None and from_bank.id == to_bank.id):
            raise ValidationError("حساب مبدأ و مقصد نباید یکی باشند.", field="to")
        if fund_account_id(from_box, from_bank) == fund_account_id(to_box, to_bank):
            raise ValidationError("حساب حسابداری مبدأ و مقصد یکسان است؛ انتقال بی‌معناست.",
                                  field="to")
        assert_fund_available(session, cash_box_id=from_box.id if from_box else None,
                              bank_account_id=from_bank.id if from_bank else None,
                              amount=amount + fee,
                              allow_negative=allow_negative_funds(self.settings))
        return {
            "transfer_date": data.transfer_date,
            "from_cash_box_id": from_box.id if from_box else None,
            "from_bank_account_id": from_bank.id if from_bank else None,
            "to_cash_box_id": to_box.id if to_box else None,
            "to_bank_account_id": to_bank.id if to_bank else None,
            "amount": amount,
            "fee": fee,
            "tracking_no": clean_text(data.tracking_no, field="tracking_no",
                                      label="شماره پیگیری", max_length=60),
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=500),
            "idempotency_key": (data.idempotency_key or "").strip() or None,
        }

    # ------------------------------------------------------------------ helpers
    def _posting(self):
        from pars_erp.services.posting_service import PostingService

        return PostingService(self.db, self.audit)

    def _funds(self):
        from pars_erp.services.funds_service import FundsService

        return FundsService(self.db, self.audit)

    def _cheques(self):
        if self.cheques is None:
            from pars_erp.services.cheque_service import ChequeService

            self.cheques = ChequeService(self.db, self.audit, journals=self.journals,
                                         settings=self.settings)
        return self.cheques

    def _create_cheque(self, session, data: ChequeInput, ctx, *, direction: str,
                       party_detail_id: int | None, amount: Decimal,
                       bank_account_id: int | None = None):
        return self._cheques().create_in_session(
            session, ctx, direction=direction, data=data, party_detail_id=party_detail_id,
            amount=amount, bank_account_id=bank_account_id)

    def _receipt_operation(self, receipt: Receipt) -> str:
        if receipt.cheque_id:
            return TC.POSTING_RECEIPT_CHEQUE
        if receipt.cash_box_id:
            return TC.POSTING_RECEIPT_CASH
        return TC.POSTING_RECEIPT_BANK

    def _payment_operation(self, payment: Payment) -> str:
        if payment.cheque_id:
            return TC.POSTING_PAYMENT_CHEQUE
        if payment.cash_box_id:
            return TC.POSTING_PAYMENT_CASH
        return TC.POSTING_PAYMENT_BANK

    def _subsidiary_account(self, session, account_id: int):
        from pars_erp.accounting import constants as AC
        from pars_erp.db.models import Account

        account = get_or_404(session, Account, account_id, "حساب حسابداری یافت نشد.")
        if account.level != AC.LEVEL_SUBSIDIARY:
            raise ValidationError("حساب طرف مقابل باید «معین» باشد.",
                                  field="counter_account_id")
        if not account.is_active:
            raise ValidationError("حساب طرف مقابل غیرفعال است.",
                                  field="counter_account_id")
        return account

    @staticmethod
    def _rate(value) -> Decimal:
        try:
            rate = Decimal(str(value if value not in (None, "") else 1))
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("نرخ تبدیل معتبر نیست.", field="exchange_rate") from exc
        if rate <= 0:
            raise ValidationError("نرخ تبدیل باید بزرگ‌تر از صفر باشد.", field="exchange_rate")
        return rate

    @staticmethod
    def _assert_editable(document) -> None:
        if document.status != TC.STATUS_DRAFT:
            raise ConflictError(
                f"سند در وضعیت «{TC.STATUS_TITLES_FA.get(document.status, document.status)}» "
                "قابل ویرایش نیست؛ برای اصلاح، ابطال و ثبت مجدد انجام دهید.")

    @staticmethod
    def _party_name(session, detail_id: int | None) -> str:
        if not detail_id:
            return ""
        detail = session.get(DetailAccount, detail_id)
        return detail.name if detail else ""

    @staticmethod
    def _settled(session, invoice_id: int) -> Decimal:
        rows = session.execute(select(SettlementAllocation).where(
            SettlementAllocation.invoice_id == invoice_id)).scalars()
        return sum((Decimal(row.amount) for row in rows), ZERO)

    @staticmethod
    def _returned(session, invoice: Invoice) -> Decimal:
        kinds = {CC.INVOICE_SALE: CC.INVOICE_SALE_RETURN,
                 CC.INVOICE_PURCHASE: CC.INVOICE_PURCHASE_RETURN}
        return_kind = kinds.get(invoice.kind)
        if return_kind is None:
            return ZERO
        rows = session.execute(select(Invoice).where(
            Invoice.source_invoice_id == invoice.id,
            Invoice.kind == return_kind,
            Invoice.status == CC.STATUS_POSTED)).scalars()
        return sum((Decimal(row.net_total) for row in rows), ZERO)

    @staticmethod
    def _filter_documents(query, date_column, number_column, status_column,
                          search, date_from, date_to, status):
        if status:
            query = query.where(status_column == status)
        if date_from:
            query = query.where(date_column >= date_from)
        if date_to:
            query = query.where(date_column <= date_to)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(number_column.like(needle)
                                | number_column.like(needle))
        return query

    def _receipt_row(self, session, receipt: Receipt) -> VoucherRow:
        box = session.get(CashBox, receipt.cash_box_id) if receipt.cash_box_id else None
        bank = (session.get(BankAccount, receipt.bank_account_id)
                if receipt.bank_account_id else None)
        return VoucherRow(
            id=receipt.id, kind=VOUCHER_RECEIPT, number=receipt.number,
            voucher_date=receipt.receipt_date, type_code=receipt.receipt_type,
            type_fa=TC.RECEIPT_TYPE_TITLES_FA.get(receipt.receipt_type,
                                                  receipt.receipt_type),
            method=receipt.method,
            method_fa=TC.RECEIPT_METHOD_TITLES_FA.get(receipt.method, receipt.method),
            fund_kind=receipt.fund_kind, fund_label=fund_label(box, bank),
            party_name=receipt.payer_name or self._party_name(session, receipt.payer_detail_id),
            party_detail_id=receipt.payer_detail_id,
            amount=Decimal(receipt.amount), currency_code=receipt.currency_code,
            exchange_rate=Decimal(receipt.exchange_rate),
            base_amount=Decimal(receipt.base_amount), status=receipt.status,
            status_fa=TC.STATUS_TITLES_FA.get(receipt.status, receipt.status),
            tracking_no=receipt.tracking_no or "", reference_no=receipt.reference_no or "",
            description=receipt.description or "",
            attachment_path=receipt.attachment_path or "",
            journal_id=receipt.journal_id, cheque_id=receipt.cheque_id,
            settlement_total=self._voucher_settled(session, VOUCHER_RECEIPT, receipt.id))

    def _payment_row(self, session, payment: Payment) -> VoucherRow:
        box = session.get(CashBox, payment.cash_box_id) if payment.cash_box_id else None
        bank = (session.get(BankAccount, payment.bank_account_id)
                if payment.bank_account_id else None)
        return VoucherRow(
            id=payment.id, kind=VOUCHER_PAYMENT, number=payment.number,
            voucher_date=payment.payment_date, type_code=payment.payment_type,
            type_fa=TC.PAYMENT_TYPE_TITLES_FA.get(payment.payment_type,
                                                  payment.payment_type),
            method=payment.method,
            method_fa=TC.PAYMENT_METHOD_TITLES_FA.get(payment.method, payment.method),
            fund_kind=payment.fund_kind, fund_label=fund_label(box, bank),
            party_name=payment.payee_name or self._party_name(session, payment.payee_detail_id),
            party_detail_id=payment.payee_detail_id,
            amount=Decimal(payment.amount), currency_code=payment.currency_code,
            exchange_rate=Decimal(payment.exchange_rate),
            base_amount=Decimal(payment.base_amount), status=payment.status,
            status_fa=TC.STATUS_TITLES_FA.get(payment.status, payment.status),
            tracking_no=payment.tracking_no or "", reference_no=payment.reference_no or "",
            description=payment.description or "",
            attachment_path=payment.attachment_path or "",
            journal_id=payment.journal_id, cheque_id=payment.cheque_id,
            settlement_total=self._voucher_settled(session, VOUCHER_PAYMENT, payment.id))

    @staticmethod
    def _voucher_settled(session, kind: str, voucher_id: int) -> Decimal:
        rows = session.execute(select(SettlementAllocation).where(
            SettlementAllocation.voucher_kind == kind,
            SettlementAllocation.voucher_id == voucher_id)).scalars()
        return sum((Decimal(row.amount) for row in rows), ZERO)

    def _transfer_row(self, session, transfer: FundTransfer) -> TransferRow:
        def label(box_id, bank_id) -> str:
            if box_id:
                box = session.get(CashBox, box_id)
                return f"صندوق {box.title_fa}" if box else "—"
            if bank_id:
                bank = session.get(BankAccount, bank_id)
                return f"بانک {bank.bank_name}" if bank else "—"
            return "—"

        return TransferRow(
            id=transfer.id, number=transfer.number, transfer_date=transfer.transfer_date,
            from_label=label(transfer.from_cash_box_id, transfer.from_bank_account_id),
            to_label=label(transfer.to_cash_box_id, transfer.to_bank_account_id),
            amount=Decimal(transfer.amount), fee=Decimal(transfer.fee),
            tracking_no=transfer.tracking_no or "",
            description=transfer.description or "", status=transfer.status,
            status_fa=TC.STATUS_TITLES_FA.get(transfer.status, transfer.status),
            journal_id=transfer.journal_id)
