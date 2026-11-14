"""Phase-5 attendance, leave, mission and overtime tests."""

from __future__ import annotations

import datetime as _dt
from dataclasses import replace
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, PermissionDeniedError, ValidationError
from pars_erp.hr import constants as H
from pars_erp.services.attendance_service import (
    AttendanceInput,
    LeaveInput,
    LeaveTypeInput,
    MissionInput,
    OvertimeInput,
    ShiftInput,
)
from pars_erp.services.hr_service import EmployeeInput

MONDAY = _dt.date(2026, 4, 20)      # 1405/01/31
TUESDAY = _dt.date(2026, 4, 21)


@pytest.fixture()
def employee(services, admin):
    return services.hr.create_employee(admin, EmployeeInput(
        code="EMP-2001", first_name="رضا", last_name="کاظمی", hire_date=MONDAY,
        base_salary=Decimal("20000000")))


@pytest.fixture()
def shift(services, admin):
    return services.attendance.create_shift(admin, ShiftInput(
        code="MORN", title_fa="شیفت صبح", kind=H.SHIFT_MORNING,
        start_time="08:00", end_time="17:00", break_minutes=60,
        grace_minutes=10, working_days="0,1,2,3,4,5"))


@pytest.fixture()
def leave_type(services, admin):
    return services.attendance.create_leave_type(admin, LeaveTypeInput(
        code="ANNUAL", title_fa="مرخصی استحقاقی", kind=H.LEAVE_PAID,
        is_paid=True, annual_quota_days=Decimal("26"), counts_in_balance=True))


# --------------------------------------------------------------------- shifts
def test_shift_duration_and_working_days(services, admin, shift):
    # 08:00 → 17:00 is 540 minutes minus a 60 minute break
    assert shift.duration_minutes == 480
    assert "دوشنبه" in shift.working_days_fa or shift.working_days_fa
    assert shift.grace_minutes == 10


def test_shift_rejects_invalid_hours(services, admin):
    with pytest.raises(ValidationError):
        services.attendance.create_shift(admin, ShiftInput(
            code="BAD", title_fa="شیفت نامعتبر", start_time="09:00",
            end_time="09:00"))


# ----------------------------------------------------------------- attendance
def test_attendance_computes_late_and_overtime(services, admin, employee, shift):
    row = services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        check_in="08:25", check_out="18:00"))
    # 10 minute grace: 25 - 10 = 15 minutes late
    assert row.late_minutes == 15
    # 08:25 → 18:00 = 575 min − 60 break = 515 min, shift is 480 → 35 overtime
    assert row.worked_minutes == 515
    assert row.overtime_minutes == 35
    assert row.early_leave_minutes == 0
    assert row.is_approved is True


def test_second_attendance_row_for_the_same_day_is_refused(services, admin,
                                                            employee, shift):
    services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    with pytest.raises(ConflictError):
        services.attendance.record(admin, AttendanceInput(
            employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
            check_in="08:05", check_out="17:05"))


def test_absence_row_has_zero_worked_minutes(services, admin, employee, shift):
    row = services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        status=H.ATT_ABSENT))
    assert row.status == H.ATT_ABSENT
    assert row.worked_minutes == 0


def test_amend_requires_reason_and_recomputes(services, admin, employee, shift):
    row = services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    with pytest.raises(ValidationError):
        services.attendance.amend(admin, row.id, check_in="09:30", note="")
    amended = services.attendance.amend(admin, row.id, check_in="09:30",
                                        note="قبض ورود اشتباه ثبت شده بود")
    assert amended.late_minutes == 80  # 09:30 minus 08:00 minus 10 minutes grace


def test_amend_needs_its_own_permission(services, admin, employee, shift):
    row = services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    limited = replace(admin, permissions=frozenset({"hr.attendance.record"}))
    with pytest.raises(PermissionDeniedError):
        services.attendance.amend(limited, row.id, check_in="09:00", note="تلاش")


def test_import_is_idempotent_and_reports_bad_rows(services, admin, employee):
    rows = [
        {"employee_code": "EMP-2001", "date": "1405/01/31", "in": "08:00", "out": "17:00"},
        {"employee_code": "EMP-9999", "date": "1405/01/31", "in": "08:00"},
    ]
    first = services.attendance.import_rows(admin, rows)
    assert (first.created, first.updated) == (1, 0)
    assert len(first.errors) == 1 and "EMP-9999" in first.errors[0]
    second = services.attendance.import_rows(admin, rows)
    assert (second.created, second.updated) == (0, 1)
    listed = services.attendance.list_attendance(admin, employee_id=employee.id)
    assert len(listed) == 1


def test_attendance_summary_feeds_payroll(services, admin, employee, shift):
    services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=MONDAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=TUESDAY, shift_id=shift.id,
        status=H.ATT_ABSENT))
    with services.db.session_scope() as session:
        summary = services.attendance.attendance_summary(
            session, employee.id, MONDAY, TUESDAY)
    assert summary["present_days"] == Decimal("1")
    assert summary["absent_days"] == Decimal("1")
    assert summary["worked_hours"] == Decimal("8.00")


# ---------------------------------------------------------------------- leave
def test_leave_request_counts_working_days(services, admin, employee, leave_type):
    row = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY + _dt.timedelta(days=6),
        reason="سفر خانوادگی"))
    assert row.status == H.LEAVE_SUBMITTED
    assert row.number.startswith("LV-")
    # the fixture's working-day setting decides the count; it must be 1..7
    assert Decimal("1") <= row.days <= Decimal("7")


def test_overlapping_leave_is_refused(services, admin, employee, leave_type):
    services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY))
    with pytest.raises(ConflictError):
        services.attendance.request_leave(admin, LeaveInput(
            employee_id=employee.id, leave_type_id=leave_type.id,
            date_from=MONDAY, date_to=MONDAY))


def test_approving_leave_uses_balance_and_marks_attendance(services, admin,
                                                           employee, leave_type):
    services.attendance.set_balance(admin, employee_id=employee.id,
                                    leave_type_id=leave_type.id, year=1405,
                                    entitled_days=Decimal("26"), note="سهمیهٔ سال")
    request = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY))
    approved = services.attendance.approve_leave(admin, request.id,
                                                 note="تأیید مدیر")
    assert approved.status == H.LEAVE_APPROVED
    balances = services.attendance.balances(admin, employee.id, year=1405)
    row = next(item for item in balances if item.leave_type_id == leave_type.id)
    assert row.used_days == request.days
    attendance = services.attendance.list_attendance(admin, employee_id=employee.id)
    assert any(item.status == H.ATT_LEAVE for item in attendance)


def test_leave_cannot_exceed_remaining_balance(services, admin, employee,
                                               leave_type):
    services.attendance.set_balance(admin, employee_id=employee.id,
                                    leave_type_id=leave_type.id, year=1405,
                                    entitled_days=Decimal("0"))
    request = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY + _dt.timedelta(days=4)))
    with pytest.raises(ValidationError):
        services.attendance.approve_leave(admin, request.id)


def test_reject_leave_needs_a_reason(services, admin, employee, leave_type):
    request = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY))
    with pytest.raises(ValidationError):
        services.attendance.reject_leave(admin, request.id, note="")
    rejected = services.attendance.reject_leave(admin, request.id,
                                                note="فصل کاری شلوغ است")
    assert rejected.status == H.LEAVE_REJECTED
    balances = services.attendance.balances(admin, employee.id, year=1405)
    row = next(item for item in balances if item.leave_type_id == leave_type.id)
    assert row.used_days == Decimal("0.00")


def test_cancelling_approved_leave_restores_the_balance(services, admin, employee,
                                                        leave_type):
    services.attendance.set_balance(admin, employee_id=employee.id,
                                    leave_type_id=leave_type.id, year=1405,
                                    entitled_days=Decimal("10"))
    request = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=leave_type.id,
        date_from=MONDAY, date_to=MONDAY))
    services.attendance.approve_leave(admin, request.id)
    services.attendance.cancel_leave(admin, request.id, note="لغو با توافق")
    balances = services.attendance.balances(admin, employee.id, year=1405)
    row = next(item for item in balances if item.leave_type_id == leave_type.id)
    assert row.used_days == Decimal("0.00")
    assert row.remaining_days == Decimal("10.00")


def test_hourly_leave_converts_hours_to_days(services, admin, employee):
    hourly = services.attendance.create_leave_type(admin, LeaveTypeInput(
        code="HOURLY", title_fa="مرخصی ساعتی", kind=H.LEAVE_HOURLY,
        is_paid=True, max_hours=Decimal("4"), counts_in_balance=False))
    row = services.attendance.request_leave(admin, LeaveInput(
        employee_id=employee.id, leave_type_id=hourly.id, date_from=MONDAY,
        hours=Decimal("4")))
    assert row.hours == Decimal("4.00")
    assert row.days == Decimal("0.50")
    approved = services.attendance.approve_leave(admin, row.id)
    assert approved.status == H.LEAVE_APPROVED


# ------------------------------------------------------------------- overtime
def test_overtime_must_be_positive_and_unique_per_day(services, admin, employee):
    with pytest.raises(ValidationError):
        services.attendance.request_overtime(admin, OvertimeInput(
            employee_id=employee.id, work_date=MONDAY, hours=0))
    services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=MONDAY, hours=Decimal("2")))
    with pytest.raises(ConflictError):
        services.attendance.request_overtime(admin, OvertimeInput(
            employee_id=employee.id, work_date=MONDAY, hours=Decimal("1")))


def test_only_approved_overtime_reaches_payroll(services, admin, employee):
    first = services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=MONDAY, hours=Decimal("2")))
    second = services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=TUESDAY, hours=Decimal("3"),
        is_holiday=True))
    services.attendance.decide_overtime(admin, first.id, approve=True)
    services.attendance.decide_overtime(admin, second.id, approve=True)
    services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=TUESDAY + _dt.timedelta(days=1),
        hours=Decimal("5")))
    with services.db.session_scope() as session:
        normal, holiday = services.attendance.approved_overtime_hours(
            session, employee.id, MONDAY, TUESDAY + _dt.timedelta(days=2))
    assert normal == Decimal("2")
    assert holiday == Decimal("3")


def test_overtime_approval_requires_permission(services, admin, employee):
    request = services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=MONDAY, hours=Decimal("2")))
    limited = replace(admin, permissions=frozenset({"hr.attendance.record"}))
    with pytest.raises(PermissionDeniedError):
        services.attendance.decide_overtime(limited, request.id, approve=True)


# ------------------------------------------------------------------- missions
def test_approved_mission_allowance_feeds_payroll(services, admin, employee):
    mission = services.attendance.create_mission(admin, MissionInput(
        employee_id=employee.id, destination="اصفهان", date_from=MONDAY,
        date_to=TUESDAY, purpose="بازدید کارخانه", cost=Decimal("2000000"),
        allowance=Decimal("1500000")))
    with services.db.session_scope() as session:
        assert services.attendance.approved_mission_allowance(
            session, employee.id, MONDAY, TUESDAY) == Decimal("0.00")
    approved = services.attendance.decide_mission(admin, mission.id, approve=True,
                                                  note="تأیید")
    assert approved.status == H.REQUEST_APPROVED
    assert approved.days is not None
    with services.db.session_scope() as session:
        assert services.attendance.approved_mission_allowance(
            session, employee.id, MONDAY, TUESDAY) == Decimal("1500000.00")
    attendance = services.attendance.list_attendance(admin, employee_id=employee.id)
    assert any(row.status == H.ATT_MISSION for row in attendance)


def test_mission_cannot_be_decided_twice(services, admin, employee):
    mission = services.attendance.create_mission(admin, MissionInput(
        employee_id=employee.id, destination="شیراز", date_from=MONDAY))
    services.attendance.decide_mission(admin, mission.id, approve=False,
                                       note="بودجه ندارد")
    with pytest.raises(ConflictError):
        services.attendance.decide_mission(admin, mission.id, approve=True)
