"""Financial accounting models (phase 2).

Vocabulary and invariants live in :mod:`pars_erp.accounting.constants`; this
module only maps them to tables. Design notes:

* chart of accounts is a *tree*: group → total account (کل) → subsidiary
  account (معین). Journal lines may only reference a subsidiary account, which is
  what keeps every balance reportable at a well defined level;
* subsidiary details (تفصیلی: customer, supplier, ...) hang under a subsidiary
  account and are optional on a journal line;
* journal documents follow an explicit state machine and store an immutable
  snapshot of who submitted/approved/posted them;
* amounts use :class:`pars_erp.db.types.MoneyAmount` (exact decimal, integer
  storage) - never floating point;
* a posted document can only be voided/reversed. Nothing in the accounting tables
  is ever cascaded away from financial history.
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.accounting.constants import (
    LEVEL_GROUP,
    LEVEL_SUBSIDIARY,
    LEVEL_TOTAL,
    PROJECT_ACTIVE,
    STATUS_DRAFT,
    TYPE_ASSET,
)
from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import MoneyAmount, UtcDateTime

ZERO = Decimal("0.0000")


class FiscalPeriod(Base, TimestampMixin):
    """A fiscal year/period the documents belong to."""

    __tablename__ = "acc_fiscal_periods"
    __table_args__ = (
        UniqueConstraint("code", name="uq_acc_fiscal_periods_code"),
        Index("ix_acc_fiscal_periods_range", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closed_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def contains(self, value: _dt.date) -> bool:
        return self.start_date <= value <= self.end_date

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FiscalPeriod {self.code} {self.start_date}..{self.end_date}>"


class Account(Base, TimestampMixin):
    """A node of the chart of accounts (گروه / کل / معین)."""

    __tablename__ = "acc_accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_acc_accounts_code"),
        Index("ix_acc_accounts_parent", "parent_id"),
        Index("ix_acc_accounts_level", "level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default=LEVEL_SUBSIDIARY)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False, default=TYPE_ASSET)
    nature: Mapped[str] = mapped_column(String(8), nullable=False, default="debit")
    statement_section: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    parent: Mapped["Account | None"] = relationship(remote_side="Account.id", lazy="joined")
    children: Mapped[list["Account"]] = relationship(
        back_populates="parent", lazy="selectin", order_by="Account.code")

    @property
    def is_group(self) -> bool:
        return self.level == LEVEL_GROUP

    @property
    def is_total(self) -> bool:
        return self.level == LEVEL_TOTAL

    @property
    def is_subsidiary(self) -> bool:
        return self.level == LEVEL_SUBSIDIARY

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Account {self.code} {self.title_fa}>"


class DetailAccount(Base, TimestampMixin):
    """Subsidiary detail (حساب تفصیلی) - a person or entity tied to an account."""

    __tablename__ = "acc_details"
    __table_args__ = (
        UniqueConstraint("code", name="uq_acc_details_code"),
        Index("ix_acc_details_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # --- phase 3: full person record (customer / supplier / employee / bank) ---
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    person_type: Mapped[str] = mapped_column(String(12), nullable=False, default="real")
    economic_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registration_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    is_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    account: Mapped["Account | None"] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DetailAccount {self.code} {self.name}>"


class CostCenter(Base, TimestampMixin):
    __tablename__ = "acc_cost_centers"
    __table_args__ = (UniqueConstraint("code", name="uq_acc_cost_centers_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Project(Base, TimestampMixin):
    __tablename__ = "acc_projects"
    __table_args__ = (UniqueConstraint("code", name="uq_acc_projects_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PROJECT_ACTIVE)
    start_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CurrencyRate(Base, TimestampMixin):
    """Exchange rate snapshot per currency and day."""

    __tablename__ = "acc_currency_rates"
    __table_args__ = (
        UniqueConstraint("currency_code", "rate_date", name="uq_acc_currency_rates_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False)
    rate_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Journal(Base, TimestampMixin):
    """Accounting document (سند حسابداری)."""

    __tablename__ = "acc_journals"
    __table_args__ = (
        UniqueConstraint("fiscal_period_id", "number", name="uq_acc_journals_period_number"),
        UniqueConstraint("idempotency_key", name="uq_acc_journals_idempotency_key"),
        Index("ix_acc_journals_date_status", "entry_date", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fiscal_period_id: Mapped[int] = mapped_column(
        ForeignKey("acc_fiscal_periods.id", ondelete="RESTRICT"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    #: Gregorian application date of registration (distinct from the document date).
    registered_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    title_fa: Mapped[str] = mapped_column(String(300), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    #: normal | opening | closing (see accounting.constants.JOURNAL_KINDS)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False,
                                                   default=Decimal("1"))
    total_debit: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    total_credit: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    foreign_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # --- phase 3: which commercial document produced this journal entry ---
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    voided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voided_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reverses_journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)

    fiscal_period: Mapped[FiscalPeriod] = relationship(lazy="joined")
    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="journal", lazy="selectin",
        cascade="all, delete-orphan",
        order_by="JournalLine.line_no")

    @property
    def is_posted(self) -> bool:
        return self.status == "posted"

    @property
    def is_editable(self) -> bool:
        return self.status == STATUS_DRAFT

    @property
    def is_balanced(self) -> bool:
        return Decimal(self.total_debit or 0) == Decimal(self.total_credit or 0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Journal {self.number} {self.entry_date} {self.status}>"


class JournalLine(Base):
    """One debit/credit row of a document."""

    __tablename__ = "acc_journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_id", "line_no", name="uq_acc_journal_lines_journal_line"),
        Index("ix_acc_journal_lines_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=False)
    detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_cost_centers.id", ondelete="RESTRICT"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_projects.id", ondelete="RESTRICT"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    debit: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    credit: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    #: Amount in the document currency (debit - credit in foreign units).
    foreign_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)

    journal: Mapped[Journal] = relationship(back_populates="lines")
    account: Mapped[Account] = relationship(lazy="joined")
    detail: Mapped[DetailAccount | None] = relationship(lazy="joined")
    cost_center: Mapped[CostCenter | None] = relationship(lazy="joined")
    project: Mapped[Project | None] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JournalLine {self.line_no} {self.debit}/{self.credit}>"


__all__ = [
    "Account",
    "CostCenter",
    "CurrencyRate",
    "DetailAccount",
    "FiscalPeriod",
    "Journal",
    "JournalLine",
    "Project",
]
