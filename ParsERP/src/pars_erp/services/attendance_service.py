"""Attendance, shifts, leave, missions and overtime (phase 5, part 2).

Rules that the rest of the system relies on:

* one attendance row per employee per day (a database constraint), so importing a
  file twice **updates** instead of doubling the hours;
* late/early/overtime are computed from the employee's shift and the company
  grace period - never typed in by the operator;
* a leave balance moves only when a request is approved (and back when an
  approved request is cancelled); a rejected or draft request changes nothing;
* approved overtime and missions are exactly what the payroll engine reads.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Attendance,
    Employee,
    EmployeeShift,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Mission,
    OvertimeRequest,
    Shift,
)
from pars_erp.db.session import Database
from pars_erp.hr import constants as H
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import clean_code, clean_text, next_document_number
from pars_erp.services.hr_common import (
    ZERO,
    diff_minutes,
    is_working_day,
    jalali_year,
    minutes_of,
    month_range,
    parse_time,
    parse_weekdays,
    working_days_between,
)
from pars_erp.db.types import utcnow


# ------------------------------------------------------------------ dataclasses
@dataclass(frozen=True)
class ShiftInput:
    code: str
    title_fa: str
    kind: str = H.SHIFT_CUSTOM
    start_time: _dt.time | str = "08:00"
    end_time: _dt.time | str = "17:00"
    break_minutes: int = 60
    grace_minutes: int | None = None
    working_days: str = "0,1,2,3,4"
    is_night: bool = False
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class ShiftRow:
    id: int
    code: str
    title_fa: str
    kind: str
    kind_fa: str
    start_time: _dt.time
    end_time: _dt.time
    break_minutes: int
    grace_minutes: int
    working_days: str
    working_days_fa: str
    duration_minutes: int
    is_night: bool
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class AttendanceInput:
    employee_id: int
    work_date: _dt.date
    check_in: _dt.time | str | None = None
    check_out: _dt.time | str | None = None
    shift_id: int | None = None
    status: str | None = None
    note: str = ""
    source: str = H.ATT_SOURCE_MANUAL


@dataclass(frozen=True)
class AttendanceRow:
    id: int
    employee_id: int
    employee_code: str
    employee_name: str
    work_date: _dt.date
    shift_title: str
    check_in: _dt.time | None
    check_out: _dt.time | None
    worked_minutes: int
    late_minutes: int
    early_leave_minutes: int
    overtime_minutes: int
    status: str
    status_fa: str
    source: str
    source_fa: str
    is_approved: bool
    note: str


@dataclass(frozen=True)
class LeaveTypeInput:
    code: str
    title_fa: str
    kind: str = H.LEAVE_PAID
    is_paid: bool = True
    requires_approval: bool = True
    annual_quota_days: Decimal | int | str = 0
    max_hours: Decimal | int | str | None = None
    counts_in_balance: bool = True
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class LeaveTypeRow:
    id: int
    code: str
    title_fa: str
    kind: str
    is_paid: bool
    requires_approval: bool
    annual_quota_days: Decimal
    max_hours: Decimal | None
    counts_in_balance: bool
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class LeaveInput:
    employee_id: int
    leave_type_id: int
    date_from: _dt.date
    date_to: _dt.date | None = None
    hours: Decimal | int | str = 0
    reason: str = ""


@dataclass(frozen=True)
class LeaveRow:
    id: int
    number: str
    employee_id: int
    employee_name: str
    leave_type: str
    date_from: _dt.date
    date_to: _dt.date
    days: Decimal
    hours: Decimal
    status: str
    status_fa: str
    reason: str
    decided_by_name: str
    decision_note: str


@dataclass(frozen=True)
class BalanceRow:
    leave_type_id: int
    leave_type: str
    period_year: int
    entitled_days: Decimal
    carried_days: Decimal
    adjusted_days: Decimal
    used_days: Decimal
    remaining_days: Decimal


@dataclass(frozen=True)
class MissionInput:
    employee_id: int
    destination: str
    date_from: _dt.date
    date_to: _dt.date | None = None
    purpose: str = ""
    transport: str = ""
    cost: Decimal | int | str = 0
    allowance: Decimal | int | str = 0


@dataclass(frozen=True)
class MissionRow:
    id: int
    number: str
    employee_id: int
    employee_name: str
    destination: str
    date_from: _dt.date
    date_to: _dt.date
    days: Decimal
    cost: Decimal
    allowance: Decimal
    status: str
    status_fa: str
    purpose: str


@dataclass(frozen=True)
class OvertimeInput:
    employee_id: int
    work_date: _dt.date
    hours: Decimal | int | str
    is_holiday: bool = False
    reason: str = ""


@dataclass(frozen=True)
class OvertimeRow:
    id: int
    employee_id: int
    employee_name: str
    work_date: _dt.date
    minutes: int
    hours: Decimal
    is_holiday: bool
    status: str
    status_fa: str
    reason: str
    payroll_applied: bool


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


# -------------------------------------------------------------------- service
class AttendanceService:
    def __init__(self, db: Database, audit: AuditService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------- shifts
    def list_shifts(self, ctx: SecurityContext | None, *,
                    active_only: bool = False) -> list[ShiftRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(Shift).order_by(Shift.code)
            if active_only:
                query = query.where(Shift.is_active.is_(True))
            return [self._shift_row(row) for row in session.execute(query).scalars()]

    def shift_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, row.display) for row in self.list_shifts(ctx, active_only=True)]

    def create_shift(self, ctx: SecurityContext | None, data: ShiftInput) -> ShiftRow:
        require_permission(ctx, "hr.org.edit")
        with self.db.session_scope() as session:
            payload = self._validate_shift(data)
            shift = Shift(**payload)
            session.add(shift)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="shift", entity_id=shift.id, action="create",
                summary_fa=f"تعریف شیفت {shift.code} — {shift.title_fa}",
                after=payload, session=session)
            return self._shift_row(shift)

    def update_shift(self, ctx: SecurityContext | None, shift_id: int,
                     data: ShiftInput) -> ShiftRow:
        require_permission(ctx, "hr.org.edit")
        with self.db.session_scope() as session:
            shift = session.get(Shift, shift_id)
            if shift is None:
                raise NotFoundError("شیفت مورد نظر یافت نشد.")
            payload = self._validate_shift(data)
            for key, value in payload.items():
                setattr(shift, key, value)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="shift", entity_id=shift.id, action="update",
                summary_fa=f"ویرایش شیفت {shift.code}", after=payload, session=session)
            return self._shift_row(shift)

    def assign_shift(self, ctx: SecurityContext | None, *, employee_id: int, shift_id: int,
                     from_date: _dt.date, to_date: _dt.date | None = None,
                     note: str = "") -> None:
        require_permission(ctx, "hr.org.edit")
        with self.db.session_scope() as session:
            self._get_employee(session, employee_id)
            if session.get(Shift, shift_id) is None:
                raise ValidationError("شیفت انتخاب‌شده یافت نشد.", field="shift_id")
            if to_date and to_date < from_date:
                raise ValidationError("پایان تخصیص شیفت قبل از شروع آن است.", field="to_date")
            session.add(EmployeeShift(employee_id=employee_id, shift_id=shift_id,
                                      from_date=from_date, to_date=to_date,
                                      note=note or None, created_by_id=self._uid(ctx)))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="employee_shift", entity_id=employee_id,
                action="assign",
                summary_fa=f"تخصیص شیفت به کارمند ({from_date})",
                after={"shift_id": shift_id}, session=session)

    def employee_shift(self, session: Session, employee_id: int,
                       when: _dt.date) -> Shift | None:
        row = session.execute(
            select(EmployeeShift).where(
                EmployeeShift.employee_id == employee_id,
                EmployeeShift.from_date <= when,
                or_(EmployeeShift.to_date.is_(None), EmployeeShift.to_date >= when))
            .order_by(EmployeeShift.from_date.desc())).scalars().first()
        return session.get(Shift, row.shift_id) if row else None

    # --------------------------------------------------------------- attendance
    def record(self, ctx: SecurityContext | None, data: AttendanceInput,
               session: Session | None = None) -> AttendanceRow:
        require_permission(ctx, "hr.attendance.record")
        if session is not None:
            return self._record_in(session, ctx, data)
        with self.db.session_scope() as own:
            return self._record_in(own, ctx, data)

    def _record_in(self, session: Session, ctx: SecurityContext | None,
                   data: AttendanceInput) -> AttendanceRow:
        employee = self._get_employee(session, data.employee_id)
        shift = self._resolve_shift(session, employee, data.shift_id, data.work_date)
        check_in = parse_time(data.check_in)
        check_out = parse_time(data.check_out)
        status = data.status or (H.ATT_PRESENT if (check_in or check_out) else H.ATT_ABSENT)
        if status not in dict(H.ATT_STATUSES):
            raise ValidationError("وضعیت حضور معتبر نیست.", field="status")
        metrics = self._metrics(shift, check_in, check_out, status)
        existing = session.execute(
            select(Attendance).where(Attendance.employee_id == employee.id,
                                     Attendance.work_date == data.work_date)
        ).scalars().first()
        if existing is not None:
            raise ConflictError(
                "برای این کارمند در این تاریخ قبلاً حضور ثبت شده است؛ از «اصلاح حضور» "
                "استفاده کنید.")
        row = Attendance(employee_id=employee.id, work_date=data.work_date,
                         shift_id=shift.id if shift else None, check_in=check_in,
                         check_out=check_out, status=status, note=data.note or None,
                         source=data.source, created_by_id=self._uid(ctx),
                         is_approved=getattr(ctx, "user_id", None) is not None, **metrics)
        session.add(row)
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="attendance", entity_id=row.id, action="create",
            summary_fa=f"ثبت حضور {employee.code} در {data.work_date}",
            after={"status": status, "worked_minutes": row.worked_minutes},
            session=session)
        return self._attendance_row(session, row)

    def amend(self, ctx: SecurityContext | None, attendance_id: int, *,
              check_in: _dt.time | str | None = None,
              check_out: _dt.time | str | None = None,
              status: str | None = None, note: str = "") -> AttendanceRow:
        """Correct an attendance row - requires a separate permission + reason."""
        require_permission(ctx, "hr.attendance.amend")
        if not (note or "").strip():
            raise ValidationError("دلیل اصلاح حضور را وارد کنید.", field="note")
        with self.db.session_scope() as session:
            row = session.get(Attendance, attendance_id)
            if row is None:
                raise NotFoundError("رکورد حضور یافت نشد.")
            before = {"check_in": str(row.check_in), "check_out": str(row.check_out),
                      "status": row.status, "worked": row.worked_minutes}
            shift = session.get(Shift, row.shift_id) if row.shift_id else None
            new_in = parse_time(check_in) if check_in is not None else row.check_in
            new_out = parse_time(check_out) if check_out is not None else row.check_out
            new_status = status or row.status
            if new_status not in dict(H.ATT_STATUSES):
                raise ValidationError("وضعیت حضور معتبر نیست.", field="status")
            metrics = self._metrics(shift, new_in, new_out, new_status)
            for key, value in metrics.items():
                setattr(row, key, value)
            row.check_in, row.check_out, row.status = new_in, new_out, new_status
            row.note = note or row.note
            row.updated_by_id = self._uid(ctx)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="attendance", entity_id=row.id, action="amend",
                summary_fa=f"اصلاح حضور کارمند شمارهٔ {row.employee_id} در {row.work_date}",
                before=before,
                after={"check_in": str(row.check_in), "check_out": str(row.check_out),
                       "status": row.status, "worked": row.worked_minutes,
                       "reason": note}, session=session)
            return self._attendance_row(session, row)

    def list_attendance(self, ctx: SecurityContext | None, *,
                        employee_id: int | None = None,
                        date_from: _dt.date | None = None,
                        date_to: _dt.date | None = None,
                        status: str | None = None) -> list[AttendanceRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(Attendance).order_by(Attendance.work_date.desc(),
                                                Attendance.employee_id)
            if employee_id:
                query = query.where(Attendance.employee_id == employee_id)
            if date_from:
                query = query.where(Attendance.work_date >= date_from)
            if date_to:
                query = query.where(Attendance.work_date <= date_to)
            if status:
                query = query.where(Attendance.status == status)
            return [self._attendance_row(session, row)
                    for row in session.execute(query).scalars()]

    def import_rows(self, ctx: SecurityContext | None, rows: list[dict],
                    *, source: str = H.ATT_SOURCE_IMPORT) -> ImportResult:
        """Import (or re-import) attendance from a parsed spreadsheet/file.

        Each row is ``{"employee_code": ..., "date": date|"1405/08/10",
        "in": "08:05", "out": "17:10", "status": optional}``. Existing rows are
        updated, so importing the same file twice is idempotent.
        """
        require_permission(ctx, "hr.attendance.record")
        created = updated = 0
        errors: list[str] = []
        with self.db.session_scope() as session:
            for index, raw in enumerate(rows, start=1):
                try:
                    code = str(raw.get("employee_code") or raw.get("code") or "").strip()
                    employee = session.execute(
                        select(Employee).where(Employee.code == code)).scalars().first()
                    if employee is None:
                        raise ValidationError(f"کارمند با کد «{code}» یافت نشد.")
                    work_date = self._coerce_date(raw.get("date") or raw.get("work_date"))
                    shift = self._resolve_shift(session, employee,
                                                raw.get("shift_id"), work_date)
                    check_in = parse_time(raw.get("in") or raw.get("check_in"))
                    check_out = parse_time(raw.get("out") or raw.get("check_out"))
                    status = raw.get("status") or (
                        H.ATT_PRESENT if (check_in or check_out) else H.ATT_ABSENT)
                    if status not in dict(H.ATT_STATUSES):
                        # a Persian label from the sheet is accepted too
                        labels = {title: key for key, title in H.ATT_STATUSES}
                        status = labels.get(str(status).strip(), H.ATT_PRESENT)
                    metrics = self._metrics(shift, check_in, check_out, status)
                    existing = session.execute(
                        select(Attendance).where(
                            Attendance.employee_id == employee.id,
                            Attendance.work_date == work_date)).scalars().first()
                    if existing is None:
                        session.add(Attendance(
                            employee_id=employee.id, work_date=work_date,
                            shift_id=shift.id if shift else None, check_in=check_in,
                            check_out=check_out, status=status, source=source,
                            created_by_id=self._uid(ctx), is_approved=True,
                            note=str(raw.get("note") or "") or None, **metrics))
                        created += 1
                    else:
                        for key, value in metrics.items():
                            setattr(existing, key, value)
                        existing.check_in, existing.check_out = check_in, check_out
                        existing.status = status
                        existing.source = source
                        existing.is_approved = True
                        updated += 1
                except Exception as error:  # row-level error is reported, not raised
                    errors.append(f"سطر {index}: {error}")
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="attendance", entity_id=None, action="import",
                summary_fa=f"ورود حضور و غیاب از فایل ({created} جدید، {updated} به‌روز)",
                after={"created": created, "updated": updated, "errors": len(errors)},
                session=session)
        return ImportResult(created=created, updated=updated, errors=tuple(errors))

    # --------------------------------------------------------------------- leave
    def list_leave_types(self, ctx: SecurityContext | None, *,
                         active_only: bool = True) -> list[LeaveTypeRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(LeaveType).order_by(LeaveType.code)
            if active_only:
                query = query.where(LeaveType.is_active.is_(True))
            return [self._leave_type_row(row) for row in session.execute(query).scalars()]

    def leave_type_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, row.display) for row in self.list_leave_types(ctx)]

    def create_leave_type(self, ctx: SecurityContext | None,
                          data: LeaveTypeInput) -> LeaveTypeRow:
        require_permission(ctx, "hr.org.edit")
        if data.kind not in dict(H.LEAVE_KINDS):
            raise ValidationError("نوع مرخصی معتبر نیست.", field="kind")
        with self.db.session_scope() as session:
            row = LeaveType(
                code=clean_code(data.code, label="کد نوع مرخصی"),
                title_fa=clean_text(data.title_fa, field="title_fa",
                                    label="عنوان نوع مرخصی", required=True,
                                    max_length=120),
                kind=data.kind, is_paid=bool(data.is_paid),
                requires_approval=bool(data.requires_approval),
                annual_quota_days=Decimal(str(data.annual_quota_days or 0)),
                max_hours=(Decimal(str(data.max_hours)) if data.max_hours not in (None, "")
                           else None),
                counts_in_balance=bool(data.counts_in_balance),
                is_active=bool(data.is_active),
                description=(data.description or "").strip() or None)
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_type", entity_id=row.id, action="create",
                summary_fa=f"تعریف نوع مرخصی {row.code} — {row.title_fa}",
                after={"quota": str(row.annual_quota_days)}, session=session)
            return self._leave_type_row(row)

    def request_leave(self, ctx: SecurityContext | None, data: LeaveInput) -> LeaveRow:
        require_permission(ctx, "hr.leave.request")
        with self.db.session_scope() as session:
            employee = self._get_employee(session, data.employee_id)
            leave_type = session.get(LeaveType, data.leave_type_id)
            if leave_type is None or not leave_type.is_active:
                raise ValidationError("نوع مرخصی انتخاب‌شده معتبر نیست.",
                                      field="leave_type_id")
            date_from = data.date_from
            date_to = data.date_to or date_from
            if date_to < date_from:
                raise ValidationError("پایان مرخصی قبل از شروع آن است.", field="date_to")
            hours = Decimal(str(data.hours or 0))
            if hours > 0:
                days = (hours / Decimal("8")).quantize(Decimal("0.01"))
                if leave_type.max_hours and hours > Decimal(leave_type.max_hours):
                    raise ValidationError(
                        f"حداکثر مرخصی ساعتی این نوع {leave_type.max_hours} ساعت است.",
                        field="hours")
            else:
                days = Decimal(working_days_between(date_from, date_to,
                                                    self._weekdays()))
            if days <= 0:
                raise ValidationError("بازهٔ انتخاب‌شده روز کاری ندارد.", field="date_from")
            overlapping = session.execute(
                select(LeaveRequest).where(
                    LeaveRequest.employee_id == employee.id,
                    LeaveRequest.status.in_((H.LEAVE_SUBMITTED, H.LEAVE_APPROVED)),
                    LeaveRequest.date_from <= date_to,
                    LeaveRequest.date_to >= date_from)).scalars().first()
            if overlapping is not None:
                raise ConflictError(
                    f"در این بازه درخواست مرخصی شمارهٔ {overlapping.number} ثبت شده است.")
            number = next_document_number(session, LeaveRequest, prefix="LV",
                                          on_date=date_from)
            row = LeaveRequest(
                number=number, employee_id=employee.id, leave_type_id=leave_type.id,
                date_from=date_from, date_to=date_to, days=days, hours=hours,
                reason=(data.reason or "").strip() or None, status=H.LEAVE_SUBMITTED,
                requested_at=utcnow(), created_by_id=self._uid(ctx))
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_request", entity_id=row.id, action="create",
                summary_fa=f"درخواست مرخصی {row.number} برای {employee.code}",
                after={"days": str(row.days), "from": str(date_from)}, session=session)
            return self._leave_row(session, row)

    def approve_leave(self, ctx: SecurityContext | None, request_id: int,
                      *, note: str = "") -> LeaveRow:
        require_permission(ctx, "hr.leave.approve")
        with self.db.session_scope() as session:
            row = self._get_leave(session, request_id)
            if row.status != H.LEAVE_SUBMITTED:
                raise ConflictError("فقط درخواست در انتظار تأیید قابل تأیید است.")
            leave_type = session.get(LeaveType, row.leave_type_id)
            balance = self._balance_for(session, row.employee_id, leave_type, row.date_from)
            if (leave_type.counts_in_balance and leave_type.is_paid
                    and balance is not None):
                if Decimal(balance.remaining_days) < Decimal(row.days):
                    raise ValidationError(
                        f"ماندهٔ مرخصی کافی نیست (مانده {balance.remaining_days}، "
                        f"درخواست {row.days}).", field="days")
            row.status = H.LEAVE_APPROVED
            row.decided_by_id = self._uid(ctx)
            row.decided_by_name = getattr(ctx, "full_name", None)
            row.decided_at = utcnow()
            row.decision_note = note or None
            if leave_type.counts_in_balance and leave_type.is_paid and balance is not None:
                balance.used_days = Decimal(balance.used_days or 0) + Decimal(row.days)
            self._mark_leave_attendance(session, row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_request", entity_id=row.id, action="approve",
                summary_fa=f"تأیید مرخصی {row.number}",
                after={"days": str(row.days), "note": note}, session=session)
            return self._leave_row(session, row)

    def reject_leave(self, ctx: SecurityContext | None, request_id: int,
                     *, note: str = "") -> LeaveRow:
        require_permission(ctx, "hr.leave.approve")
        if not (note or "").strip():
            raise ValidationError("دلیل رد درخواست را وارد کنید.", field="note")
        with self.db.session_scope() as session:
            row = self._get_leave(session, request_id)
            if row.status != H.LEAVE_SUBMITTED:
                raise ConflictError("فقط درخواست در انتظار تأیید قابل رد است.")
            row.status = H.LEAVE_REJECTED
            row.decided_by_id = self._uid(ctx)
            row.decided_by_name = getattr(ctx, "full_name", None)
            row.decided_at = utcnow()
            row.decision_note = note
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_request", entity_id=row.id, action="reject",
                summary_fa=f"رد مرخصی {row.number}", after={"note": note}, session=session)
            return self._leave_row(session, row)

    def cancel_leave(self, ctx: SecurityContext | None, request_id: int,
                     *, note: str = "") -> LeaveRow:
        require_permission(ctx, "hr.leave.request")
        with self.db.session_scope() as session:
            row = self._get_leave(session, request_id)
            if row.status not in (H.LEAVE_SUBMITTED, H.LEAVE_APPROVED):
                raise ConflictError("این درخواست قابل لغو نیست.")
            if row.status == H.LEAVE_APPROVED:
                leave_type = session.get(LeaveType, row.leave_type_id)
                balance = self._balance_for(session, row.employee_id, leave_type,
                                            row.date_from, create=False)
                if balance is not None and leave_type.counts_in_balance \
                        and leave_type.is_paid:
                    balance.used_days = max(
                        ZERO, Decimal(balance.used_days or 0) - Decimal(row.days))
                self._clear_leave_attendance(session, row)
            row.status = H.LEAVE_CANCELLED
            row.decision_note = note or row.decision_note
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_request", entity_id=row.id, action="cancel",
                summary_fa=f"لغو مرخصی {row.number}", after={"note": note}, session=session)
            return self._leave_row(session, row)

    def list_leave(self, ctx: SecurityContext | None, *, employee_id: int | None = None,
                   status: str | None = None, year: int | None = None,
                   date_from: _dt.date | None = None,
                   date_to: _dt.date | None = None) -> list[LeaveRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(LeaveRequest).order_by(LeaveRequest.date_from.desc())
            if employee_id:
                query = query.where(LeaveRequest.employee_id == employee_id)
            if status:
                query = query.where(LeaveRequest.status == status)
            if year:
                start, _end = month_range(year, 1)
                last_start, last_end = month_range(year, 12)
                query = query.where(LeaveRequest.date_from >= start,
                                    LeaveRequest.date_from <= last_end)
            if date_from:
                query = query.where(LeaveRequest.date_to >= date_from)
            if date_to:
                query = query.where(LeaveRequest.date_from <= date_to)
            return [self._leave_row(session, row)
                    for row in session.execute(query).scalars()]

    def balances(self, ctx: SecurityContext | None, employee_id: int,
                 year: int | None = None) -> list[BalanceRow]:
        require_permission(ctx, "hr.employees.view")
        target = year or jalali_year(_dt.date.today())
        with self.db.session_scope() as session:
            types = list(session.execute(
                select(LeaveType).where(LeaveType.is_active.is_(True),
                                        LeaveType.counts_in_balance.is_(True))
                .order_by(LeaveType.code)).scalars())
            rows = []
            for leave_type in types:
                balance = self._balance_for(session, employee_id, leave_type,
                                            _dt.date.today(), year=target, create=False)
                if balance is None:
                    entitled = Decimal(leave_type.annual_quota_days or 0)
                    carried = adjusted = used = ZERO
                else:
                    entitled = Decimal(balance.entitled_days or 0)
                    carried = Decimal(balance.carried_days or 0)
                    adjusted = Decimal(balance.adjusted_days or 0)
                    used = Decimal(balance.used_days or 0)
                rows.append(BalanceRow(
                    leave_type_id=leave_type.id,
                    leave_type=f"{leave_type.code} — {leave_type.title_fa}",
                    period_year=target, entitled_days=entitled, carried_days=carried,
                    adjusted_days=adjusted, used_days=used,
                    remaining_days=(entitled + carried + adjusted - used)))
            return rows

    def set_balance(self, ctx: SecurityContext | None, *, employee_id: int,
                    leave_type_id: int, year: int, entitled_days: Decimal | None = None,
                    carried_days: Decimal | None = None,
                    adjusted_days: Decimal | None = None, note: str = "") -> BalanceRow:
        """Opening/quota adjustment - audited, never used for day-to-day usage."""
        require_permission(ctx, "hr.leave.approve")
        with self.db.session_scope() as session:
            leave_type = session.get(LeaveType, leave_type_id)
            if leave_type is None:
                raise ValidationError("نوع مرخصی یافت نشد.", field="leave_type_id")
            balance = self._balance_for(session, employee_id, leave_type,
                                        _dt.date.today(), year=year, create=True)
            before = {"entitled": str(balance.entitled_days),
                      "carried": str(balance.carried_days),
                      "adjusted": str(balance.adjusted_days)}
            if entitled_days is not None:
                balance.entitled_days = Decimal(str(entitled_days))
            if carried_days is not None:
                balance.carried_days = Decimal(str(carried_days))
            if adjusted_days is not None:
                balance.adjusted_days = Decimal(str(adjusted_days))
            balance.note = note or balance.note
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="leave_balance", entity_id=balance.id,
                action="adjust",
                summary_fa=f"اصلاح ماندهٔ مرخصی کارمند {employee_id} سال {year}",
                before=before,
                after={"entitled": str(balance.entitled_days),
                       "carried": str(balance.carried_days),
                       "adjusted": str(balance.adjusted_days)}, session=session)
            return BalanceRow(
                leave_type_id=leave_type.id,
                leave_type=f"{leave_type.code} — {leave_type.title_fa}",
                period_year=year, entitled_days=Decimal(balance.entitled_days),
                carried_days=Decimal(balance.carried_days),
                adjusted_days=Decimal(balance.adjusted_days),
                used_days=Decimal(balance.used_days),
                remaining_days=Decimal(balance.remaining_days))

    # ------------------------------------------------------------------ missions
    def create_mission(self, ctx: SecurityContext | None, data: MissionInput) -> MissionRow:
        require_permission(ctx, "hr.leave.request")
        with self.db.session_scope() as session:
            employee = self._get_employee(session, data.employee_id)
            date_from = data.date_from
            date_to = data.date_to or date_from
            if date_to < date_from:
                raise ValidationError("پایان مأموریت قبل از شروع آن است.", field="date_to")
            days = Decimal((date_to - date_from).days + 1)
            number = next_document_number(session, Mission, prefix="MSN", on_date=date_from)
            row = Mission(
                number=number, employee_id=employee.id,
                destination=clean_text(data.destination, field="destination",
                                       label="مقصد مأموریت", required=True, max_length=160),
                date_from=date_from, date_to=date_to, days=days,
                purpose=(data.purpose or "").strip() or None,
                transport=(data.transport or "").strip() or None,
                cost=Decimal(str(data.cost or 0)), allowance=Decimal(str(data.allowance or 0)),
                status=H.REQUEST_SUBMITTED, created_by_id=self._uid(ctx))
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="mission", entity_id=row.id, action="create",
                summary_fa=f"درخواست مأموریت {row.number} برای {employee.code}",
                after={"destination": row.destination, "days": str(days)}, session=session)
            return self._mission_row(session, row)

    def decide_mission(self, ctx: SecurityContext | None, mission_id: int, *,
                       approve: bool, note: str = "") -> MissionRow:
        require_permission(ctx, "hr.overtime.approve")
        with self.db.session_scope() as session:
            row = session.get(Mission, mission_id)
            if row is None:
                raise NotFoundError("درخواست مأموریت یافت نشد.")
            if row.status != H.REQUEST_SUBMITTED:
                raise ConflictError("فقط درخواست در انتظار تأیید قابل بررسی است.")
            row.status = H.REQUEST_APPROVED if approve else H.REQUEST_REJECTED
            row.decided_by_id = self._uid(ctx)
            row.decided_by_name = getattr(ctx, "full_name", None)
            row.decided_at = utcnow()
            row.decision_note = note or None
            if approve:
                self._mark_mission_attendance(session, row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="mission", entity_id=row.id,
                action="approve" if approve else "reject",
                summary_fa=f"{'تأیید' if approve else 'رد'} مأموریت {row.number}",
                after={"note": note}, session=session)
            return self._mission_row(session, row)

    def list_missions(self, ctx: SecurityContext | None, *, employee_id: int | None = None,
                      status: str | None = None) -> list[MissionRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(Mission).order_by(Mission.date_from.desc())
            if employee_id:
                query = query.where(Mission.employee_id == employee_id)
            if status:
                query = query.where(Mission.status == status)
            return [self._mission_row(session, row)
                    for row in session.execute(query).scalars()]

    # ------------------------------------------------------------------ overtime
    def request_overtime(self, ctx: SecurityContext | None,
                         data: OvertimeInput) -> OvertimeRow:
        require_permission(ctx, "hr.attendance.record")
        hours = Decimal(str(data.hours or 0))
        if hours <= 0:
            raise ValidationError("ساعت اضافه‌کاری باید بزرگ‌تر از صفر باشد.", field="hours")
        with self.db.session_scope() as session:
            employee = self._get_employee(session, data.employee_id)
            existing = session.execute(
                select(OvertimeRequest).where(
                    OvertimeRequest.employee_id == employee.id,
                    OvertimeRequest.work_date == data.work_date)).scalars().first()
            if existing is not None:
                raise ConflictError("برای این روز قبلاً اضافه‌کاری ثبت شده است.")
            row = OvertimeRequest(
                employee_id=employee.id, work_date=data.work_date,
                minutes=int(hours * 60), is_holiday=bool(data.is_holiday),
                reason=(data.reason or "").strip() or None, status=H.REQUEST_SUBMITTED,
                created_by_id=self._uid(ctx))
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="overtime", entity_id=row.id, action="create",
                summary_fa=f"درخواست اضافه‌کاری {employee.code} در {data.work_date}",
                after={"minutes": row.minutes}, session=session)
            return self._overtime_row(session, row)

    def decide_overtime(self, ctx: SecurityContext | None, overtime_id: int, *,
                        approve: bool, note: str = "") -> OvertimeRow:
        require_permission(ctx, "hr.overtime.approve")
        with self.db.session_scope() as session:
            row = session.get(OvertimeRequest, overtime_id)
            if row is None:
                raise NotFoundError("درخواست اضافه‌کاری یافت نشد.")
            if row.status != H.REQUEST_SUBMITTED:
                raise ConflictError("فقط درخواست در انتظار تأیید قابل بررسی است.")
            row.status = H.REQUEST_APPROVED if approve else H.REQUEST_REJECTED
            row.decided_by_id = self._uid(ctx)
            row.decided_by_name = getattr(ctx, "full_name", None)
            row.decided_at = utcnow()
            row.decision_note = note or None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="overtime", entity_id=row.id,
                action="approve" if approve else "reject",
                summary_fa=f"{'تأیید' if approve else 'رد'} اضافه‌کاری", after={"note": note},
                session=session)
            return self._overtime_row(session, row)

    def list_overtime(self, ctx: SecurityContext | None, *, employee_id: int | None = None,
                      status: str | None = None, date_from: _dt.date | None = None,
                      date_to: _dt.date | None = None) -> list[OvertimeRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(OvertimeRequest).order_by(OvertimeRequest.work_date.desc())
            if employee_id:
                query = query.where(OvertimeRequest.employee_id == employee_id)
            if status:
                query = query.where(OvertimeRequest.status == status)
            if date_from:
                query = query.where(OvertimeRequest.work_date >= date_from)
            if date_to:
                query = query.where(OvertimeRequest.work_date <= date_to)
            return [self._overtime_row(session, row)
                    for row in session.execute(query).scalars()]

    # ---------------------------------------------------------- payroll feed-in
    def approved_overtime_hours(self, session: Session, employee_id: int,
                                start: _dt.date, end: _dt.date) -> tuple[Decimal, Decimal]:
        """``(normal hours, holiday hours)`` approved for the payroll period."""
        rows = session.execute(
            select(OvertimeRequest).where(
                OvertimeRequest.employee_id == employee_id,
                OvertimeRequest.status == H.REQUEST_APPROVED,
                OvertimeRequest.work_date >= start,
                OvertimeRequest.work_date <= end)).scalars()
        normal = holiday = ZERO
        for row in rows:
            hours = Decimal(row.minutes or 0) / Decimal(60)
            if row.is_holiday:
                holiday += hours
            else:
                normal += hours
        return normal, holiday

    def approved_mission_allowance(self, session: Session, employee_id: int,
                                   start: _dt.date, end: _dt.date) -> Decimal:
        rows = session.execute(
            select(Mission).where(
                Mission.employee_id == employee_id,
                Mission.status == H.REQUEST_APPROVED,
                Mission.date_from <= end,
                Mission.date_to >= start)).scalars()
        return sum((Decimal(row.allowance or 0) for row in rows), ZERO)

    def attendance_summary(self, session: Session, employee_id: int, start: _dt.date,
                           end: _dt.date) -> dict[str, Decimal]:
        rows = list(session.execute(
            select(Attendance).where(
                Attendance.employee_id == employee_id,
                Attendance.work_date >= start,
                Attendance.work_date <= end)).scalars())
        worked = sum((row.worked_minutes for row in rows), 0) / 60
        late = sum((row.late_minutes for row in rows), 0) / 60
        overtime = sum((row.overtime_minutes for row in rows), 0) / 60
        present = Decimal(sum(1 for row in rows
                              if row.status in (H.ATT_PRESENT, H.ATT_LATE)))
        absent = Decimal(sum(1 for row in rows if row.status == H.ATT_ABSENT))
        leave = Decimal(sum(1 for row in rows if row.status == H.ATT_LEAVE))
        return {"present_days": present, "absent_days": absent, "leave_days": leave,
                "worked_hours": Decimal(str(round(worked, 2))),
                "late_hours": Decimal(str(round(late, 2))),
                "overtime_hours": Decimal(str(round(overtime, 2)))}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _uid(ctx: SecurityContext | None) -> int | None:
        return getattr(ctx, "user_id", None)

    def _get_employee(self, session: Session, employee_id: int) -> Employee:
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError("کارمند مورد نظر یافت نشد.")
        return employee

    def _get_leave(self, session: Session, request_id: int) -> LeaveRequest:
        row = session.get(LeaveRequest, request_id)
        if row is None:
            raise NotFoundError("درخواست مرخصی یافت نشد.")
        return row

    def _weekdays(self) -> tuple[int, ...]:
        if self.settings is None:
            return H.DEFAULT_WORKING_DAYS + (5,)
        try:
            return parse_weekdays(self.settings.snapshot().get("hr_work_weekdays"))
        except Exception:  # pragma: no cover
            return H.DEFAULT_WORKING_DAYS + (5,)

    def _grace_minutes(self) -> int:
        if self.settings is None:
            return 0
        try:
            return int(self.settings.snapshot().int("hr_grace_minutes"))
        except Exception:  # pragma: no cover
            return 0

    def _validate_shift(self, data: ShiftInput) -> dict:
        if data.kind not in dict(H.SHIFT_KINDS):
            raise ValidationError("نوع شیفت معتبر نیست.", field="kind")
        start = parse_time(data.start_time)
        end = parse_time(data.end_time)
        if start is None or end is None:
            raise ValidationError("ساعت شروع و پایان شیفت را وارد کنید.", field="start_time")
        if start == end:
            raise ValidationError("ساعت شروع و پایان شیفت نمی‌تواند یکسان باشد.",
                                  field="end_time")
        days = parse_weekdays(data.working_days)
        return {
            "code": clean_code(data.code, label="کد شیفت"),
            "title_fa": clean_text(data.title_fa, field="title_fa", label="عنوان شیفت",
                                   required=True, max_length=120),
            "kind": data.kind, "start_time": start, "end_time": end,
            "break_minutes": max(0, int(data.break_minutes or 0)),
            "grace_minutes": (self._grace_minutes() if data.grace_minutes is None
                              else max(0, int(data.grace_minutes))),
            "working_days": ",".join(str(day) for day in days),
            "is_night": bool(data.is_night),
            "is_active": bool(data.is_active),
            "description": (data.description or "").strip() or None,
        }

    def _resolve_shift(self, session: Session, employee: Employee,
                       shift_id: int | None, when: _dt.date) -> Shift | None:
        if shift_id:
            shift = session.get(Shift, shift_id)
            if shift is None:
                raise ValidationError("شیفت انتخاب‌شده یافت نشد.", field="shift_id")
            return shift
        assigned = self.employee_shift(session, employee.id, when)
        if assigned is not None:
            return assigned
        return session.execute(
            select(Shift).where(Shift.is_active.is_(True)).order_by(Shift.code)
        ).scalars().first()

    def _metrics(self, shift: Shift | None, check_in: _dt.time | None,
                 check_out: _dt.time | None, status: str) -> dict:
        if status in (H.ATT_ABSENT, H.ATT_LEAVE, H.ATT_HOLIDAY, H.ATT_MISSION):
            return {"worked_minutes": 0, "late_minutes": 0,
                    "early_leave_minutes": 0, "overtime_minutes": 0}
        worked = diff_minutes(check_in, check_out)
        break_minutes = int(shift.break_minutes or 0) if shift else 0
        worked = max(0, worked - break_minutes)
        late = early = overtime = 0
        if shift is not None and check_in is not None:
            grace = int(shift.grace_minutes or 0)
            # signed difference: arriving early must never look like ~24h of lateness
            late = max(0, minutes_of(check_in) - minutes_of(shift.start_time) - grace)
        if shift is not None and check_out is not None:
            early = max(0, minutes_of(shift.end_time) - minutes_of(check_out))
            shift_minutes = max(0, diff_minutes(shift.start_time, shift.end_time)
                                - int(shift.break_minutes or 0))
            overtime = max(0, worked - shift_minutes)
        if status == H.ATT_LATE and late == 0:
            late = 1
        return {"worked_minutes": worked, "late_minutes": late,
                "early_leave_minutes": early, "overtime_minutes": overtime}

    def _coerce_date(self, value) -> _dt.date:
        if isinstance(value, _dt.datetime):
            return value.date()
        if isinstance(value, _dt.date):
            return value
        text = str(value or "").strip().replace("-", "/").replace(".", "/")
        if not text:
            raise ValidationError("تاریخ حضور خالی است.", field="date")
        parts = [part for part in text.split("/") if part]
        if len(parts) != 3:
            raise ValidationError(f"تاریخ «{value}» معتبر نیست.", field="date")
        year, month, day = (int(part) for part in parts)
        if year < 100:
            year += 1400
        if year > 1700:  # a Gregorian date slipped through
            return _dt.date(year, month, day)
        from pars_erp.core.jalali import jalali_to_gregorian
        return jalali_to_gregorian(year, month, day)

    def _balance_for(self, session: Session, employee_id: int, leave_type: LeaveType,
                     when: _dt.date, *, year: int | None = None,
                     create: bool = True) -> LeaveBalance | None:
        target_year = year or jalali_year(when)
        balance = session.execute(
            select(LeaveBalance).where(
                LeaveBalance.employee_id == employee_id,
                LeaveBalance.leave_type_id == leave_type.id,
                LeaveBalance.period_year == target_year)).scalars().first()
        if balance is None and create and leave_type.counts_in_balance:
            balance = LeaveBalance(
                employee_id=employee_id, leave_type_id=leave_type.id,
                period_year=target_year,
                entitled_days=Decimal(leave_type.annual_quota_days or 0))
            session.add(balance)
            session.flush()
        return balance

    def _mark_leave_attendance(self, session: Session, request: LeaveRequest) -> None:
        cursor = request.date_from
        weekdays = self._weekdays()
        while cursor <= request.date_to:
            if is_working_day(cursor, weekdays):
                row = session.execute(
                    select(Attendance).where(Attendance.employee_id == request.employee_id,
                                             Attendance.work_date == cursor)
                ).scalars().first()
                if row is None:
                    session.add(Attendance(
                        employee_id=request.employee_id, work_date=cursor,
                        status=H.ATT_LEAVE, leave_request_id=request.id,
                        is_approved=True, source=H.ATT_SOURCE_MANUAL,
                        note=f"مرخصی {request.number}"))
                else:
                    row.status = H.ATT_LEAVE
                    row.leave_request_id = request.id
                    row.worked_minutes = row.late_minutes = row.overtime_minutes = 0
            cursor += _dt.timedelta(days=1)

    def _clear_leave_attendance(self, session: Session, request: LeaveRequest) -> None:
        rows = session.execute(
            select(Attendance).where(Attendance.leave_request_id == request.id)).scalars()
        for row in rows:
            session.delete(row)

    def _mark_mission_attendance(self, session: Session, mission: Mission) -> None:
        cursor = mission.date_from
        weekdays = self._weekdays()
        while cursor <= mission.date_to:
            if is_working_day(cursor, weekdays):
                row = session.execute(
                    select(Attendance).where(Attendance.employee_id == mission.employee_id,
                                             Attendance.work_date == cursor)
                ).scalars().first()
                if row is None:
                    session.add(Attendance(
                        employee_id=mission.employee_id, work_date=cursor,
                        status=H.ATT_MISSION, mission_id=mission.id, is_approved=True,
                        note=f"مأموریت {mission.number}"))
                else:
                    row.status = H.ATT_MISSION
                    row.mission_id = mission.id
            cursor += _dt.timedelta(days=1)

    # -------------------------------------------------------------------- rows
    def _shift_row(self, shift: Shift) -> ShiftRow:
        days = shift.working_day_indexes
        duration = max(0, diff_minutes(shift.start_time, shift.end_time)
                       - int(shift.break_minutes or 0))
        return ShiftRow(
            id=shift.id, code=shift.code, title_fa=shift.title_fa, kind=shift.kind,
            kind_fa=H.SHIFT_TITLES_FA.get(shift.kind, shift.kind),
            start_time=shift.start_time, end_time=shift.end_time,
            break_minutes=int(shift.break_minutes or 0),
            grace_minutes=int(shift.grace_minutes or 0),
            working_days=shift.working_days,
            working_days_fa="، ".join(H.WEEKDAY_TITLES_FA[index] for index in days),
            duration_minutes=duration, is_night=shift.is_night, is_active=shift.is_active)

    def _attendance_row(self, session: Session, row: Attendance) -> AttendanceRow:
        employee = session.get(Employee, row.employee_id)
        shift = session.get(Shift, row.shift_id) if row.shift_id else None
        return AttendanceRow(
            id=row.id, employee_id=row.employee_id,
            employee_code=employee.code if employee else "",
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            work_date=row.work_date, shift_title=shift.title_fa if shift else "",
            check_in=row.check_in, check_out=row.check_out,
            worked_minutes=int(row.worked_minutes or 0),
            late_minutes=int(row.late_minutes or 0),
            early_leave_minutes=int(row.early_leave_minutes or 0),
            overtime_minutes=int(row.overtime_minutes or 0),
            status=row.status,
            status_fa=H.ATT_STATUS_TITLES_FA.get(row.status, row.status),
            source=row.source,
            source_fa=H.ATT_SOURCE_TITLES_FA.get(row.source, row.source),
            is_approved=bool(row.is_approved), note=row.note or "")

    @staticmethod
    def _leave_type_row(row: LeaveType) -> LeaveTypeRow:
        return LeaveTypeRow(
            id=row.id, code=row.code, title_fa=row.title_fa, kind=row.kind,
            is_paid=row.is_paid, requires_approval=row.requires_approval,
            annual_quota_days=Decimal(row.annual_quota_days or 0),
            max_hours=(Decimal(row.max_hours) if row.max_hours is not None else None),
            counts_in_balance=row.counts_in_balance, is_active=row.is_active)

    def _leave_row(self, session: Session, row: LeaveRequest) -> LeaveRow:
        employee = session.get(Employee, row.employee_id)
        leave_type = session.get(LeaveType, row.leave_type_id)
        return LeaveRow(
            id=row.id, number=row.number, employee_id=row.employee_id,
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            leave_type=(f"{leave_type.code} — {leave_type.title_fa}"
                        if leave_type else ""),
            date_from=row.date_from, date_to=row.date_to,
            days=Decimal(row.days or 0), hours=Decimal(row.hours or 0),
            status=row.status,
            status_fa=H.LEAVE_STATUS_TITLES_FA.get(row.status, row.status),
            reason=row.reason or "", decided_by_name=row.decided_by_name or "",
            decision_note=row.decision_note or "")

    def _mission_row(self, session: Session, row: Mission) -> MissionRow:
        employee = session.get(Employee, row.employee_id)
        return MissionRow(
            id=row.id, number=row.number, employee_id=row.employee_id,
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            destination=row.destination, date_from=row.date_from, date_to=row.date_to,
            days=Decimal(row.days or 0), cost=Decimal(row.cost or 0),
            allowance=Decimal(row.allowance or 0), status=row.status,
            status_fa=H.REQUEST_STATUS_TITLES_FA.get(row.status, row.status),
            purpose=row.purpose or "")

    def _overtime_row(self, session: Session, row: OvertimeRequest) -> OvertimeRow:
        employee = session.get(Employee, row.employee_id)
        return OvertimeRow(
            id=row.id, employee_id=row.employee_id,
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            work_date=row.work_date, minutes=int(row.minutes or 0),
            hours=Decimal(row.minutes or 0) / Decimal(60), is_holiday=row.is_holiday,
            status=row.status,
            status_fa=H.REQUEST_STATUS_TITLES_FA.get(row.status, row.status),
            reason=row.reason or "", payroll_applied=row.payroll_applied)
