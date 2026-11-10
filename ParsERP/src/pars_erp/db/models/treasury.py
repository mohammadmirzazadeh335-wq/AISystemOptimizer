"""Treasury models (phase 4): bank accounts, cash boxes, cheques and vouchers.

Design notes (mirrored in ``docs/PHASE4_SCHEMA.md``):

* a **fund** is either a cash box or a bank account; both point at a
  subsidiary account of the phase-2 chart, so fund movements are ledger
  movements and no second bookkeeping exists;
* a **voucher** (receipt / payment / transfer) owns its status, its journal
  entry and an idempotency key — posting twice is rejected by the database, not
  only by the service;
* a **cheque** keeps a status *history* table and a link to the voucher that
  produced it, so every status change is auditable;
* settlements are explicit allocation rows (many receipts → one invoice and one
  receipt → many invoices), never an edited balance on the invoice itself.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import MoneyAmount, UtcDateTime
from pars_erp.treasury.constants import (
    CHEQUE_RECEIVED,
    FUND_CASH,
    RECEIPT_CUSTOMER,
    STATUS_DRAFT,
)

ZERO = Decimal("0.0000")


class BankAccount(Base, TimestampMixin):
    """A company bank account, linked to one subsidiary ledger account."""

    __tablename__ = "trs_bank_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_trs_bank_accounts_code"),
        UniqueConstraint("bank_name", "account_number", name="uq_trs_bank_accounts_number"),
        Index("ix_trs_bank_accounts_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_number: Mapped[str] = mapped_column(String(40), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(24), nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    opening_balance: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                    default=ZERO)
    opening_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CashBox(Base, TimestampMixin):
    """A physical till; several tills may exist, each with its own ledger."""

    __tablename__ = "trs_cash_boxes"
    __table_args__ = (UniqueConstraint("code", name="uq_trs_cash_boxes_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    keeper_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                    default=ZERO)
    opening_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CashBoxUser(Base):
    """Which users may operate which till (empty = everybody with the permission)."""

    __tablename__ = "trs_cash_box_users"
    __table_args__ = (UniqueConstraint("cash_box_id", "user_id",
                                       name="uq_trs_cash_box_users"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cash_box_id: Mapped[int] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class ChequeBook(Base, TimestampMixin):
    """A booklet of blank cheques received from a bank."""

    __tablename__ = "trs_cheque_books"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "serial_no", name="uq_trs_cheque_books_serial"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    serial_no: Mapped[str] = mapped_column(String(40), nullable=False)
    first_no: Mapped[int] = mapped_column(Integer, nullable=False)
    last_no: Mapped[int] = mapped_column(Integer, nullable=False)
    received_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    bank_account: Mapped["BankAccount"] = relationship(lazy="joined")
    cheques: Mapped[list["Cheque"]] = relationship(back_populates="book",
                                                   lazy="selectin")


class Cheque(Base, TimestampMixin):
    """A received or issued cheque, with its lifecycle and history."""

    __tablename__ = "trs_cheques"
    __table_args__ = (
        UniqueConstraint("cheque_book_id", "number", name="uq_trs_cheques_book_number"),
        Index("ix_trs_cheques_direction_status", "direction", "status"),
        Index("ix_trs_cheques_due", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction: Mapped[str] = mapped_column(String(12), nullable=False,
                                          default=CHEQUE_RECEIVED)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    cheque_book_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cheque_books.id", ondelete="RESTRICT"), nullable=True)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    holder_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False,
                                                  default=Decimal("1"))
    base_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    issue_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    party_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_invoices.id", ondelete="RESTRICT"), nullable=True)
    cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    receipt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    book: Mapped["ChequeBook | None"] = relationship(back_populates="cheques", lazy="joined")
    events: Mapped[list["ChequeEvent"]] = relationship(
        back_populates="cheque", cascade="all, delete-orphan", lazy="selectin",
        order_by="ChequeEvent.id")


class ChequeEvent(Base):
    __tablename__ = "trs_cheque_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cheque_id: Mapped[int] = mapped_column(
        ForeignKey("trs_cheques.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    event_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)

    cheque: Mapped["Cheque"] = relationship(back_populates="events")


class Receipt(Base, TimestampMixin):
    """Money received into a fund (cash, bank or cheque)."""

    __tablename__ = "trs_receipts"
    __table_args__ = (
        UniqueConstraint("number", name="uq_trs_receipts_number"),
        UniqueConstraint("idempotency_key", name="uq_trs_receipts_idempotency"),
        Index("ix_trs_receipts_date", "receipt_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    receipt_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                             default=RECEIPT_CUSTOMER)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="cash")
    fund_kind: Mapped[str] = mapped_column(String(8), nullable=False, default=FUND_CASH)
    payer_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False,
                                                  default=Decimal("1"))
    base_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    cheque_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cheques.id", ondelete="RESTRICT"), nullable=True)
    counter_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Payment(Base, TimestampMixin):
    """Money paid out of a fund (cash, bank or cheque)."""

    __tablename__ = "trs_payments"
    __table_args__ = (
        UniqueConstraint("number", name="uq_trs_payments_number"),
        UniqueConstraint("idempotency_key", name="uq_trs_payments_idempotency"),
        Index("ix_trs_payments_date", "payment_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    payment_type: Mapped[str] = mapped_column(String(16), nullable=False, default="supplier")
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="cash")
    fund_kind: Mapped[str] = mapped_column(String(8), nullable=False, default=FUND_CASH)
    payee_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    payee_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False,
                                                  default=Decimal("1"))
    base_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    cheque_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cheques.id", ondelete="RESTRICT"), nullable=True)
    counter_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FundTransfer(Base, TimestampMixin):
    """Money moved between two funds (cash ↔ bank), optionally with a fee."""

    __tablename__ = "trs_transfers"
    __table_args__ = (
        UniqueConstraint("number", name="uq_trs_transfers_number"),
        UniqueConstraint("idempotency_key", name="uq_trs_transfers_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    transfer_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    from_cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    from_bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    to_cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    to_bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    fee: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    tracking_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SettlementAllocation(Base):
    """How much of a receipt/payment settles a given invoice."""

    __tablename__ = "trs_allocations"
    __table_args__ = (
        UniqueConstraint("voucher_kind", "voucher_id", "invoice_id",
                         name="uq_trs_allocations_voucher_invoice"),
        Index("ix_trs_allocations_invoice", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_kind: Mapped[str] = mapped_column(String(12), nullable=False)  # receipt/payment
    voucher_id: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("com_invoices.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BankStatement(Base, TimestampMixin):
    """A bank statement period, imported from CSV/Excel, for reconciliation."""

    __tablename__ = "trs_bank_statements"
    __table_args__ = (Index("ix_trs_bank_statements_account", "bank_account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=False)
    statement_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    period_start: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                    default=ZERO)
    closing_balance: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                    default=ZERO)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    bank_account: Mapped["BankAccount"] = relationship(lazy="joined")
    lines: Mapped[list["BankStatementLine"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan", lazy="selectin",
        order_by="BankStatementLine.id")


class BankStatementLine(Base):
    """One row of the bank's own statement."""

    __tablename__ = "trs_bank_statement_lines"
    __table_args__ = (Index("ix_trs_statement_lines_statement", "statement_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("trs_bank_statements.id", ondelete="CASCADE"), nullable=False)
    tx_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount_in: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    amount_out: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unmatched")
    matched_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    matched_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)

    statement: Mapped["BankStatement"] = relationship(back_populates="lines")

    @property
    def signed_amount(self) -> Decimal:
        """Positive for money the bank received, negative for money it paid."""
        return Decimal(self.amount_in) - Decimal(self.amount_out)


class PlannedItem(Base, TimestampMixin):
    """A due-dated item shown on the treasury calendar (cheque, debt, payment)."""

    __tablename__ = "trs_planned_items"
    __table_args__ = (Index("ix_trs_planned_items_due", "due_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    party_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    ref_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
