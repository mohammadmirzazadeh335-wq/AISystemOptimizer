"""Phase-5 HR models: org structure, employees, contracts, attendance, leave.

Design notes:

* an **employee is a person**: ``person_id`` points at the phase-3 ``acc_details``
  row (kind ``employee``), so the same human is one record for accounting, HR and
  treasury - no duplicated name/phone/iban fields that would drift apart;
* **history is never overwritten**: a job/unit/salary change writes an
  ``hr_employee_history`` row *and* updates the employee, and a unit move never
  rewrites the unit's past membership;
* **balances move only through documents**: leave balances change from an
  approved request, never from an editable number;
* attendance is unique per employee per day, so an import twice cannot double a
  day's work.
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
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import MoneyAmount
from pars_erp.hr.constants import (
    ATT_SOURCE_MANUAL,
    COLLAB_ACTIVE,
    CONTRACT_DRAFT,
    EMPLOYMENT_FULL_TIME,
    LEAVE_DRAFT,
    REQUEST_DRAFT,
    SHIFT_CUSTOM,
    UNIT_COMPANY,
)

ZERO = Decimal("0.0000")


class OrgUnit(Base, TimestampMixin):
    """One node of the company/branch/unit/section/position tree."""

    __tablename__ = "hr_org_units"
    __table_args__ = (
        UniqueConstraint("code", name="uq_hr_org_units_code"),
        Index("ix_hr_org_units_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=UNIT_COMPANY)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_org_units.id", ondelete="RESTRICT"), nullable=True)
    manager_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_center_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_cost_centers.id", ondelete="SET NULL"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    parent: Mapped["OrgUnit | None"] = relationship(remote_side=[id], lazy="joined")


class Employee(Base, TimestampMixin):
    __tablename__ = "hr_employees"
    __table_args__ = (
        UniqueConstraint("code", name="uq_hr_employees_code"),
        UniqueConstraint("person_id", name="uq_hr_employees_person"),
        Index("ix_hr_employees_status", "collaboration_status"),
        Index("ix_hr_employees_unit", "org_unit_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    father_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    national_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    birth_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    birth_place: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    children_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(160), nullable=True)

    hire_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                                default=EMPLOYMENT_FULL_TIME)
    collaboration_status: Mapped[str] = mapped_column(String(16), nullable=False,
                                                      default=COLLAB_ACTIVE)
    org_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_org_units.id", ondelete="RESTRICT"), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    position: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True)

    base_salary: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    insurance_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tax_file_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_account_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)

    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    org_unit: Mapped["OrgUnit | None"] = relationship(lazy="joined")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class EmployeeHistory(Base, TimestampMixin):
    """Append-only record of every job/unit/salary/status change."""

    __tablename__ = "hr_employee_history"
    __table_args__ = (Index("ix_hr_employee_history_employee", "employee_id", "effective_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Contract(Base, TimestampMixin):
    __tablename__ = "hr_contracts"
    __table_args__ = (
        UniqueConstraint("number", name="uq_hr_contracts_number"),
        Index("ix_hr_contracts_employee", "employee_id"),
        Index("ix_hr_contracts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    base_salary: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    working_hours_weekly: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("44"))
    working_days_weekly: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    payment_terms: Mapped[str | None] = mapped_column(String(300), nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    deductions: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    org_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_org_units.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=CONTRACT_DRAFT)
    previous_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_contracts.id", ondelete="SET NULL"), nullable=True)
    amendment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    signed_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Shift(Base, TimestampMixin):
    __tablename__ = "hr_shifts"
    __table_args__ = (UniqueConstraint("code", name="uq_hr_shifts_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=SHIFT_CUSTOM)
    start_time: Mapped[_dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[_dt.time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Saturday-based indexes 0..6 stored as ``"0,1,2,3,4"``.
    working_days: Mapped[str] = mapped_column(String(20), nullable=False, default="0,1,2,3,4")
    is_night: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @property
    def working_day_indexes(self) -> tuple[int, ...]:
        return tuple(int(part) for part in (self.working_days or "").split(",") if part.strip())


class EmployeeShift(Base, TimestampMixin):
    __tablename__ = "hr_employee_shifts"
    __table_args__ = (Index("ix_hr_employee_shifts_employee", "employee_id", "from_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    shift_id: Mapped[int] = mapped_column(
        ForeignKey("hr_shifts.id", ondelete="RESTRICT"), nullable=False)
    from_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    to_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Attendance(Base, TimestampMixin):
    __tablename__ = "hr_attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_hr_attendance_employee_date"),
        Index("ix_hr_attendance_date", "work_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    work_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_shifts.id", ondelete="SET NULL"), nullable=True)
    check_in: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    check_out: Mapped[_dt.time | None] = mapped_column(Time, nullable=True)
    worked_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="present")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=ATT_SOURCE_MANUAL)
    leave_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mission_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LeaveType(Base, TimestampMixin):
    __tablename__ = "hr_leave_types"
    __table_args__ = (UniqueConstraint("code", name="uq_hr_leave_types_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="paid")
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    annual_quota_days: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=ZERO)
    max_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    counts_in_balance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)


class LeaveRequest(Base, TimestampMixin):
    __tablename__ = "hr_leave_requests"
    __table_args__ = (
        Index("ix_hr_leave_requests_employee", "employee_id", "date_from"),
        Index("ix_hr_leave_requests_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT"), nullable=False)
    date_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    date_to: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=LEAVE_DRAFT)
    requested_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    decided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LeaveBalance(Base, TimestampMixin):
    """One row per employee, leave type and Jalali year."""

    __tablename__ = "hr_leave_balances"
    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "period_year",
                         name="uq_hr_leave_balances_employee_type_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("hr_leave_types.id", ondelete="RESTRICT"), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    entitled_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    carried_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    adjusted_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    used_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @property
    def remaining_days(self) -> Decimal:
        total = (Decimal(self.entitled_days or 0) + Decimal(self.carried_days or 0)
                 + Decimal(self.adjusted_days or 0))
        return (total - Decimal(self.used_days or 0)).quantize(Decimal("0.01"))


class Mission(Base, TimestampMixin):
    __tablename__ = "hr_missions"
    __table_args__ = (Index("ix_hr_missions_employee", "employee_id", "date_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    destination: Mapped[str] = mapped_column(String(160), nullable=False)
    date_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    date_to: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=ZERO)
    purpose: Mapped[str | None] = mapped_column(String(400), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cost: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    allowance: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=REQUEST_DRAFT)
    decided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payroll_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OvertimeRequest(Base, TimestampMixin):
    __tablename__ = "hr_overtime_requests"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_hr_overtime_requests_employee_date"),
        Index("ix_hr_overtime_requests_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="RESTRICT"), nullable=False)
    work_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=REQUEST_DRAFT)
    decided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payroll_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
