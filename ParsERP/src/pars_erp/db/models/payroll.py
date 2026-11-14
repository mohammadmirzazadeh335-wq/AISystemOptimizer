"""Phase-5 payroll models: settings versions, runs, payslips, loans, payment batches.

Design notes:

* **settings are dated and versioned**: a run stores ``settings_version_id``, so a
  later rate change never silently recalculates an approved month;
* **a payslip is unique per run and employee**, and a payslip can be paid once -
  ``payment_item_id`` is unique, which is what makes a retried payment batch safe;
* **loan installments are rows**, not a running balance typed by a user: the
  remaining debt is always ``sum(installments not yet deducted)``.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import (
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
from pars_erp.db.types import MoneyAmount
from pars_erp.payroll.constants import (
    BATCH_DRAFT,
    ITEM_PENDING,
    LOAN_REQUESTED,
    RUN_DRAFT,
    SLIP_DRAFT,
    VERSION_DRAFT,
)

ZERO = Decimal("0.0000")


class PaySettingsVersion(Base, TimestampMixin):
    """A dated snapshot of every payroll rate/allowance."""

    __tablename__ = "pay_settings_versions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_pay_settings_versions_code"),
        Index("ix_pay_settings_versions_dates", "effective_from", "effective_to"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=VERSION_DRAFT)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    items: Mapped[list["PaySettingItem"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", lazy="selectin")
    brackets: Mapped[list["PayTaxBracket"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", lazy="selectin")


class PaySettingItem(Base, TimestampMixin):
    __tablename__ = "pay_settings_items"
    __table_args__ = (
        UniqueConstraint("version_id", "key", name="uq_pay_settings_items_version_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("pay_settings_versions.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[str] = mapped_column(String(120), nullable=False, default="0")
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    version: Mapped[PaySettingsVersion] = relationship(back_populates="items")


class PayTaxBracket(Base, TimestampMixin):
    """Progressive income-tax bracket; empty means 'not configured' (tax = 0)."""

    __tablename__ = "pay_tax_brackets"
    __table_args__ = (
        UniqueConstraint("version_id", "sort_order", name="uq_pay_tax_brackets_version_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("pay_settings_versions.id", ondelete="CASCADE"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    from_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    to_amount: Mapped[Decimal | None] = mapped_column(MoneyAmount, nullable=True)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False,
                                                  default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    version: Mapped[PaySettingsVersion] = relationship(back_populates="brackets")


class PayRun(Base, TimestampMixin):
    __tablename__ = "pay_runs"
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", name="uq_pay_runs_year_month"),
        Index("ix_pay_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    settings_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("pay_settings_versions.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RUN_DRAFT)
    employees_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    deductions_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                     default=ZERO)
    net_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    insurance_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                    default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculated_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    calculated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Payslip(Base, TimestampMixin):
    __tablename__ = "pay_payslips"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_id", name="uq_pay_payslips_run_employee"),
        Index("ix_pay_payslips_employee", "employee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_contracts.id", ondelete="RESTRICT"), nullable=True)
    settings_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    worked_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=ZERO)
    absent_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=ZERO)
    paid_leave_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False,
                                                    default=ZERO)
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False,
                                                   default=ZERO)

    base_salary: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    benefits_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    overtime_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    bonus: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    gross: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    absence_deduction: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                      default=ZERO)
    insurance_employee: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                       default=ZERO)
    insurance_employer: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                       default=ZERO)
    income_tax: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    loan_installment: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    advance_deduction: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                      default=ZERO)
    other_deductions: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    deductions_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    net: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SLIP_DRAFT)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)

    lines: Mapped[list["PayslipLine"]] = relationship(
        back_populates="slip", cascade="all, delete-orphan", lazy="selectin")
    employee: Mapped["object"] = relationship("Employee", lazy="joined")


class PayslipLine(Base):
    __tablename__ = "pay_payslip_lines"
    __table_args__ = (Index("ix_pay_payslip_lines_slip", "slip_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slip_id: Mapped[int] = mapped_column(
        ForeignKey("pay_payslips.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # earning | deduction
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    slip: Mapped[Payslip] = relationship(back_populates="lines")


class Loan(Base, TimestampMixin):
    __tablename__ = "pay_loans"
    __table_args__ = (Index("ix_pay_loans_employee", "employee_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="loan")
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    request_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    installments: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    installment_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                        default=ZERO)
    repayment_start_year: Mapped[int] = mapped_column(Integer, nullable=False, default=1405)
    repayment_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=LOAN_REQUESTED)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    paid_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settled_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    installments_rows: Mapped[list["LoanInstallment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", lazy="selectin")


class LoanInstallment(Base, TimestampMixin):
    __tablename__ = "pay_loan_installments"
    __table_args__ = (
        UniqueConstraint("loan_id", "seq", name="uq_pay_loan_installments_loan_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_id: Mapped[int] = mapped_column(
        ForeignKey("pay_loans.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    due_year: Mapped[int] = mapped_column(Integer, nullable=False)
    due_month: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    paid_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ITEM_PENDING)
    slip_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    loan: Mapped[Loan] = relationship(back_populates="installments_rows")


class PayBatch(Base, TimestampMixin):
    __tablename__ = "pay_batches"
    __table_args__ = (Index("ix_pay_batches_run", "run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pay_runs.id", ondelete="RESTRICT"), nullable=False)
    payment_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    fund_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="bank")
    cash_box_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_cash_boxes.id", ondelete="RESTRICT"), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("trs_bank_accounts.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BATCH_DRAFT)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    paid_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    bank_file_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)

    items: Mapped[list["PayBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", lazy="selectin")


class PayBatchItem(Base, TimestampMixin):
    __tablename__ = "pay_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "payslip_id", name="uq_pay_batch_items_batch_slip"),
        UniqueConstraint("payslip_id", name="uq_pay_batch_items_payslip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("pay_batches.id", ondelete="CASCADE"), nullable=False)
    payslip_id: Mapped[int] = mapped_column(
        ForeignKey("pay_payslips.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ITEM_PENDING)
    tracking_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    paid_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)

    batch: Mapped[PayBatch] = relationship(back_populates="items")
