"""Phase-5 payroll integration: settings versions, runs, payslips and the journal."""

from __future__ import annotations

import datetime as _dt
from dataclasses import replace
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, PermissionDeniedError, ValidationError
from pars_erp.hr import constants as H
from pars_erp.payroll import constants as P
from pars_erp.services.attendance_service import AttendanceInput, OvertimeInput, ShiftInput
from pars_erp.services.hr_service import ContractInput, EmployeeInput
from pars_erp.services.payroll_service import TaxBracketInput, VersionInput

D = Decimal
# 1405/02 = 2026-04-21 .. 2026-05-21
PERIOD_YEAR, PERIOD_MONTH = 1405, 2
DAY = _dt.date(2026, 5, 5)


def _version(services, admin, **overrides):
    items = {
        P.SETTING_BASE_HOURS: "176",
        P.SETTING_WORK_DAYS: "30",
        P.SETTING_OVERTIME_FACTOR: "1.4",
        P.SETTING_HOLIDAY_FACTOR: "2",
        P.SETTING_HOUSING: "1000000",
        P.SETTING_FOOD: "800000",
        P.SETTING_CHILD: "300000",
        P.SETTING_MARRIAGE: "500000",
        P.SETTING_SENIORITY: "0",
        P.SETTING_CONTINUOUS: "0",
        P.SETTING_NON_CONTINUOUS: "0",
        P.SETTING_INSURANCE_EMPLOYEE: "7",
        P.SETTING_INSURANCE_EMPLOYER: "23",
        P.SETTING_INSURANCE_BASE_CAP: "0",
        P.SETTING_TAX_EXEMPT: "5000000",
        P.SETTING_ABSENCE: "0",
        P.SETTING_LOAN_MAX_RATIO: "30",
        P.SETTING_ROUNDING: "1000",
    }
    items.update({key: str(value) for key, value in overrides.items()})
    return services.payroll.create_version(admin, VersionInput(
        code="V1405-A", title_fa="تنظیمات حقوق ۱۴۰۵", effective_from=_dt.date(2026, 3, 21),
        status=P.VERSION_ACTIVE, source_note="مقادیر آزمون",
        items=items,
        brackets=(TaxBracketInput(from_amount=D("0"), to_amount=D("10000000"),
                                  rate_percent=D("10")),
                  TaxBracketInput(from_amount=D("10000000"), to_amount=None,
                                  rate_percent=D("15"))),
    ))


@pytest.fixture()
def payroll_world(services, admin, chart):
    """One employee with a contract, attendance, overtime and a paid loan."""
    services.posting.ensure_default_rules(admin)
    employee = services.hr.create_employee(admin, EmployeeInput(
        code="EMP-3001", first_name="مریم", last_name="احمدی",
        hire_date=_dt.date(2024, 5, 1), base_salary=D("30000000"),
        children_count=1, marital_status=H.MARITAL_MARRIED))
    services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=_dt.date(2025, 3, 21),
        base_salary=D("30000000")))
    shift = services.attendance.create_shift(admin, ShiftInput(
        code="S1", title_fa="شیفت روز", start_time="08:00", end_time="17:00",
        break_minutes=60, grace_minutes=0, working_days="0,1,2,3,4,5"))
    services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=DAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    overtime = services.attendance.request_overtime(admin, OvertimeInput(
        employee_id=employee.id, work_date=DAY, hours=D("10")))
    services.attendance.decide_overtime(admin, overtime.id, approve=True)
    return employee


# ----------------------------------------------------------------- versions
def test_default_version_is_seeded_with_zeroed_values(services, admin):
    version = services.payroll.ensure_default_version(admin)
    assert set(version.items) == set(P.PAY_SETTING_KEYS)
    assert all(value == "0" for value in version.items.values())
    assert "خالی" in version.source_note
    # running it twice does not create a second base version
    again = services.payroll.ensure_default_version(admin)
    assert again.id == version.id


def test_version_rejects_unknown_setting_key(services, admin):
    with pytest.raises(ValidationError):
        services.payroll.create_version(admin, VersionInput(
            code="BAD", title_fa="نسخهٔ نامعتبر", effective_from=_dt.date(2026, 3, 21),
            items={"not_a_key": "1"}))


def test_version_rejects_an_impossible_tax_rate(services, admin):
    with pytest.raises(ValidationError):
        services.payroll.create_version(admin, VersionInput(
            code="BAD2", title_fa="نرخ نامعتبر", effective_from=_dt.date(2026, 3, 21),
            brackets=(TaxBracketInput(from_amount=D("0"), rate_percent=D("120")),)))


def test_version_used_by_an_approved_run_is_immutable(services, admin, payroll_world):
    version = _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    services.payroll.approve(admin, run.id)
    with pytest.raises(ConflictError):
        services.payroll.update_version(admin, version.id, VersionInput(
            code="V1405-A", title_fa="تلاش برای تغییر", effective_from=_dt.date(2026, 3, 21),
            items={P.SETTING_INSURANCE_EMPLOYEE: "9"}))


def test_version_for_picks_the_dated_version(services, admin):
    first = _version(services, admin)
    second = services.payroll.create_version(admin, VersionInput(
        code="V1405-B", title_fa="نسخهٔ دوم", effective_from=_dt.date(2026, 7, 23),
        status=P.VERSION_ACTIVE, items={P.SETTING_INSURANCE_EMPLOYEE: "9"}))
    with services.db.session_scope() as session:
        early = services.payroll.version_for(session, 1405, 2)
        late = services.payroll.version_for(session, 1405, 6)
    assert early.id == first.id
    assert late.id == second.id


# ---------------------------------------------------------------------- runs
def test_run_is_unique_per_month(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    assert run.number.startswith("PR-")
    with pytest.raises(ConflictError):
        services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)


def test_calculation_produces_a_payslip_with_the_expected_totals(services, admin,
                                                                payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    summary = services.payroll.calculate(admin, run.id)
    assert summary.employees == 1
    assert summary.skipped == ()

    slips = services.payroll.payslips(admin, run.id)
    assert len(slips) == 1
    slip = services.payroll.payslip(admin, slips[0].id)
    # base 30,000,000 + housing 1,000,000 + food 800,000 + child 300,000
    # + marriage 500,000 + overtime 10h × (30,000,000/176) × 1.4
    expected_overtime = D("2386363.64")
    assert slip.base_salary == D("30000000.00")
    assert slip.benefits_total == D("2600000.00")
    assert slip.overtime_amount == expected_overtime
    assert slip.gross == D("34986363.64")
    # insurance base = salary + continuous benefits = 32,600,000 → 7%
    assert slip.insurance_employee == D("2282000.00")
    assert slip.net == slip.gross - slip.deductions_total
    assert slip.lines, "a payslip must carry its earning/deduction lines"
    kinds = {line.kind for line in slip.lines}
    assert P.LINE_BASE in kinds and P.LINE_OVERTIME in kinds and P.LINE_INSURANCE in kinds
    assert summary.gross == slip.gross
    assert summary.net == slip.net


def test_employee_without_salary_is_skipped_and_reported(services, admin, payroll_world):
    _version(services, admin)
    services.hr.create_employee(admin, EmployeeInput(
        code="EMP-3002", first_name="بی", last_name="قرارداد", hire_date=DAY))
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    summary = services.payroll.calculate(admin, run.id)
    assert summary.employees == 1
    assert len(summary.skipped) == 1
    assert "EMP-3002" in summary.skipped[0]


def test_approved_run_cannot_be_recalculated(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    services.payroll.approve(admin, run.id)
    with pytest.raises(ConflictError):
        services.payroll.calculate(admin, run.id)


def test_approval_marks_slips_and_requires_calculation(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    with pytest.raises(ValidationError):
        services.payroll.approve(admin, run.id)
    services.payroll.calculate(admin, run.id)
    approved = services.payroll.approve(admin, run.id)
    assert approved.status == P.RUN_APPROVED
    slips = services.payroll.payslips(admin, run.id)
    assert all(slip.status == P.SLIP_APPROVED for slip in slips)


def test_posting_creates_one_balanced_journal_and_refuses_a_second(services, admin,
                                                                   payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    with pytest.raises(ConflictError):
        services.payroll.post(admin, run.id)      # not approved yet
    services.payroll.approve(admin, run.id)
    posted = services.payroll.post(admin, run.id)
    assert posted.status == P.RUN_POSTED
    assert posted.journal_id

    with services.db.session_scope() as session:
        from pars_erp.db.models import Journal, JournalLine
        journal = session.get(Journal, posted.journal_id)
        lines = list(session.execute(
            __import__("sqlalchemy").select(JournalLine)
            .where(JournalLine.journal_id == journal.id)).scalars())
        debit = sum((D(line.debit or 0) for line in lines), D("0"))
        credit = sum((D(line.credit or 0) for line in lines), D("0"))
    assert debit == credit > 0
    assert journal.status == "posted"

    with pytest.raises(ConflictError):
        services.payroll.post(admin, run.id)


def test_posted_run_cannot_be_cancelled(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    services.payroll.approve(admin, run.id)
    services.payroll.post(admin, run.id)
    with pytest.raises(ConflictError):
        services.payroll.cancel_run(admin, run.id, reason="اشتباه")


def test_payroll_needs_its_permissions(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    viewer = replace(admin, permissions=frozenset({"payroll.view"}))
    with pytest.raises(PermissionDeniedError):
        services.payroll.calculate(viewer, run.id)
    services.payroll.calculate(admin, run.id)
    with pytest.raises(PermissionDeniedError):
        services.payroll.approve(viewer, run.id)


def test_reports_read_the_calculated_run(services, admin, payroll_world):
    _version(services, admin)
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    register = services.payroll_reports.register(admin, run.id)
    assert register.row_count == 1
    assert register.rows[0][0] == "EMP-3001"
    components = services.payroll_reports.components(admin, run.id)
    titles = {row[0] for row in components.rows}
    assert "حقوق پایه" in titles
    runs = services.payroll_reports.runs(admin, year=PERIOD_YEAR)
    assert runs.row_count == 1
