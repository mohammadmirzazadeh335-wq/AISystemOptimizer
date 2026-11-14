"""HR reports: staff, contracts, attendance, leave, overtime and missions.

All numbers are computed from stored documents; nothing is sampled or faked.
Each report is a :class:`ReportTable` so the phase-3/4 renderer can print it,
export it to PDF or push it to Excel without a second code path.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import select

from pars_erp.core.jalali import format_gregorian_as_jalali
from pars_erp.db.models import (
    Attendance,
    Contract,
    Employee,
    LeaveRequest,
    LeaveType,
    Mission,
    OrgUnit,
    OvertimeRequest,
)
from pars_erp.db.session import Database
from pars_erp.hr import constants as H
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.commerce_reports_service import ReportPeriod, ReportTable
from pars_erp.services.hr_common import ZERO

MINUTES_PER_HOUR = Decimal("60")


def _d(value: _dt.date | None) -> str:
    return format_gregorian_as_jalali(value) if value else ""


def _hours(minutes: int | None) -> Decimal:
    return (Decimal(int(minutes or 0)) / MINUTES_PER_HOUR).quantize(Decimal("0.01"))


def _name(employee: Employee | None) -> str:
    return employee.full_name if employee is not None else ""


class HRReportService:
    def __init__(self, db: Database, settings=None) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------- staff
    def staff_list(self, ctx: SecurityContext | None, *, status: str | None = None,
                   org_unit_id: int | None = None, search: str = "",
                   include_sensitive: bool = False) -> ReportTable:
        """``include_sensitive`` must be granted separately by the caller."""
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            query = select(Employee).order_by(Employee.code)
            if status:
                query = query.where(Employee.collaboration_status == status)
            if org_unit_id:
                query = query.where(Employee.org_unit_id == org_unit_id)
            employees = list(session.execute(query).scalars())
            units = {unit.id: unit.title_fa
                     for unit in session.execute(select(OrgUnit)).scalars()}
            term = (search or "").strip()
            if term:
                employees = [e for e in employees
                             if term in e.code or term in _name(e)
                             or term in (e.job_title or "") or term in (e.mobile or "")]
            rows = []
            for employee in employees:
                row = (
                    employee.code, _name(employee),
                    units.get(employee.org_unit_id, ""),
                    employee.job_title or "", employee.position or "",
                    H.EMPLOYMENT_TITLES_FA.get(employee.employment_type,
                                               employee.employment_type),
                    _d(employee.hire_date),
                    H.COLLAB_TITLES_FA.get(employee.collaboration_status,
                                           employee.collaboration_status),
                )
                if include_sensitive:
                    row = row + (employee.national_id or "", employee.mobile or "",
                                 employee.iban or employee.bank_account_no or "",
                                 Decimal(employee.base_salary or 0))
                rows.append(row)
            columns = ["کد پرسنلی", "نام", "واحد سازمانی", "عنوان شغلی", "سمت", "نوع همکاری",
                       "تاریخ استخدام", "وضعیت"]
            if include_sensitive:
                columns += ["کد ملی", "موبایل", "شماره حساب/شبا", "حقوق پایه"]
            return ReportTable("hr_staff", "فهرست کارکنان", tuple(columns), tuple(rows),
                               meta_fa=f"{len(rows)} نفر")

    def contracts(self, ctx: SecurityContext | None, *, expiring_within_days: int = 30,
                  today: _dt.date | None = None) -> ReportTable:
        require_permission(ctx, "hr.reports")
        moment = today or _dt.date.today()
        horizon = moment + _dt.timedelta(days=int(expiring_within_days))
        with self.db.session_scope() as session:
            contracts = list(session.execute(
                select(Contract).order_by(Contract.end_date)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = []
            for contract in contracts:
                end = contract.end_date
                if end is None:
                    state_fa, state = "بدون پایان", "open"
                elif end < moment:
                    state_fa, state = "منقضی", "expired"
                elif end <= horizon:
                    state_fa, state = "در آستانهٔ انقضا", "expiring"
                else:
                    state_fa, state = "جاری", "active"
                rows.append((
                    contract.number, _name(employees.get(contract.employee_id)),
                    contract.job_title or "", _d(contract.start_date), _d(end),
                    Decimal(contract.base_salary or 0), state_fa, state,
                    H.CONTRACT_STATUS_TITLES_FA.get(contract.status, contract.status),
                ))
            return ReportTable(
                "hr_contracts", "قراردادهای کارکنان",
                ("شماره قرارداد", "کارمند", "عنوان", "شروع", "پایان", "حقوق پایه",
                 "وضعیت زمانی", "کد وضعیت", "وضعیت سند"), tuple(rows),
                meta_fa=f"در آستانهٔ انقضا تا {expiring_within_days} روز")

    # -------------------------------------------------------------- attendance
    def attendance(self, ctx: SecurityContext | None,
                   period: ReportPeriod) -> ReportTable:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            records = list(session.execute(
                select(Attendance).where(Attendance.work_date >= period.date_from,
                                         Attendance.work_date <= period.date_to)
            ).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            buckets: dict[int, dict] = {}
            for record in records:
                bucket = buckets.setdefault(record.employee_id, {
                    "present_days": 0, "absent_days": 0, "minutes": 0,
                    "late": 0, "early": 0, "overtime": 0})
                if record.status == "absent":
                    bucket["absent_days"] += 1
                else:
                    bucket["present_days"] += 1
                    bucket["minutes"] += int(record.worked_minutes or 0)
                bucket["late"] += int(record.late_minutes or 0)
                bucket["early"] += int(record.early_leave_minutes or 0)
                bucket["overtime"] += int(record.overtime_minutes or 0)
            rows = []
            for employee_id, bucket in sorted(
                    buckets.items(),
                    key=lambda item: employees[item[0]].code
                    if item[0] in employees else ""):
                employee = employees.get(employee_id)
                rows.append((
                    employee.code if employee else str(employee_id), _name(employee),
                    bucket["present_days"], bucket["absent_days"],
                    _hours(bucket["minutes"]), _hours(bucket["late"]),
                    _hours(bucket["early"]), _hours(bucket["overtime"]),
                ))
            return ReportTable(
                "hr_attendance", "گزارش حضور و غیاب",
                ("کد پرسنلی", "نام", "روز حضور", "روز غیبت", "ساعت کارکرد",
                 "تأخیر (ساعت)", "تعجیل در خروج (ساعت)", "اضافه‌کار (ساعت)"),
                tuple(rows),
                meta_fa=f"{_d(period.date_from)} تا {_d(period.date_to)}")

    def lateness(self, ctx: SecurityContext | None,
                 period: ReportPeriod) -> ReportTable:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            records = list(session.execute(
                select(Attendance)
                .where(Attendance.work_date >= period.date_from,
                       Attendance.work_date <= period.date_to,
                       Attendance.late_minutes > 0)
                .order_by(Attendance.work_date)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = tuple(
                (employee.code if (employee := employees.get(record.employee_id)) else "",
                 _name(employee), _d(record.work_date),
                 int(record.late_minutes or 0), int(record.early_leave_minutes or 0),
                 record.note or "")
                for record in records)
            return ReportTable(
                "hr_lateness", "گزارش تأخیر و تعجیل",
                ("کد پرسنلی", "نام", "تاریخ", "تأخیر (دقیقه)",
                 "تعجیل در خروج (دقیقه)", "توضیح"), rows,
                meta_fa=f"{len(rows)} مورد — {_d(period.date_from)} تا {_d(period.date_to)}")

    def leave(self, ctx: SecurityContext | None, period: ReportPeriod) -> ReportTable:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            requests = list(session.execute(
                select(LeaveRequest)
                .where(LeaveRequest.date_from <= period.date_to,
                       LeaveRequest.date_to >= period.date_from)
                .order_by(LeaveRequest.date_from)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            types = {row.id: row for row in
                     session.execute(select(LeaveType)).scalars()}
            rows = []
            for request in requests:
                leave_type = types.get(request.leave_type_id)
                rows.append((
                    request.number,
                    _name(employees.get(request.employee_id)),
                    leave_type.title_fa if leave_type else "",
                    _d(request.date_from), _d(request.date_to),
                    Decimal(request.days or 0), Decimal(request.hours or 0),
                    H.REQUEST_STATUS_TITLES_FA.get(request.status, request.status),
                    request.decided_by_name or "",
                ))
            return ReportTable(
                "hr_leave", "گزارش مرخصی",
                ("شماره", "کارمند", "نوع مرخصی", "از تاریخ", "تا تاریخ", "روز",
                 "ساعت", "وضعیت", "تصمیم‌گیرنده"), tuple(rows),
                meta_fa=f"{_d(period.date_from)} تا {_d(period.date_to)}")

    def overtime(self, ctx: SecurityContext | None,
                 period: ReportPeriod) -> ReportTable:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            items = list(session.execute(
                select(OvertimeRequest)
                .where(OvertimeRequest.work_date >= period.date_from,
                       OvertimeRequest.work_date <= period.date_to)
                .order_by(OvertimeRequest.work_date)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = []
            for item in items:
                rows.append((
                    _name(employees.get(item.employee_id)), _d(item.work_date),
                    _hours(item.minutes),
                    "تعطیل" if item.is_holiday else "روز عادی",
                    H.REQUEST_STATUS_TITLES_FA.get(item.status, item.status),
                    "بله" if item.payroll_applied else "خیر",
                    item.reason or "",
                ))
            return ReportTable(
                "hr_overtime", "گزارش اضافه‌کار",
                ("کارمند", "تاریخ", "ساعت", "نوع روز", "وضعیت", "اعمال در حقوق", "علت"),
                tuple(rows), meta_fa=f"{_d(period.date_from)} تا {_d(period.date_to)}")

    def missions(self, ctx: SecurityContext | None,
                 period: ReportPeriod) -> ReportTable:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            items = list(session.execute(
                select(Mission)
                .where(Mission.date_from <= period.date_to,
                       Mission.date_to >= period.date_from)
                .order_by(Mission.date_from)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = tuple(
                (item.number, _name(employees.get(item.employee_id)), item.destination,
                 _d(item.date_from), _d(item.date_to), Decimal(item.days or 0),
                 Decimal(item.cost or 0), Decimal(item.allowance or 0),
                 H.REQUEST_STATUS_TITLES_FA.get(item.status, item.status))
                for item in items)
            return ReportTable(
                "hr_missions", "گزارش مأموریت‌ها",
                ("شماره", "کارمند", "مقصد", "از تاریخ", "تا تاریخ", "روز", "هزینه",
                 "کمک‌هزینه", "وضعیت"), rows,
                meta_fa=f"{_d(period.date_from)} تا {_d(period.date_to)}")

    # ---------------------------------------------------------------- summary
    def headcount(self, ctx: SecurityContext | None) -> dict[str, int]:
        require_permission(ctx, "hr.reports")
        with self.db.session_scope() as session:
            counts = {key: 0 for key in H.COLLAB_TITLES_FA}
            for employee in session.execute(select(Employee)).scalars():
                counts[employee.collaboration_status] = counts.get(
                    employee.collaboration_status, 0) + 1
            return counts


__all__ = ["HRReportService", "ReportPeriod", "ReportTable", "ZERO"]
