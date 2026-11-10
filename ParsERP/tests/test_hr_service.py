"""Phase-5 HR tests: organisational structure, personnel files and contracts."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, PermissionDeniedError, ValidationError
from pars_erp.hr import constants as H
from pars_erp.services.hr_service import (
    ContractInput,
    EmployeeFilter,
    EmployeeInput,
    OrgUnitInput,
)

TODAY = _dt.date(2026, 4, 20)


@pytest.fixture()
def org(services, admin):
    """Company → branch → unit hierarchy."""
    company = services.hr.create_unit(admin, OrgUnitInput(
        code="CO", title_fa="زرین هرمز", kind=H.UNIT_COMPANY))
    branch = services.hr.create_unit(admin, OrgUnitInput(
        code="BR1", title_fa="شعبهٔ مرکزی", kind=H.UNIT_BRANCH,
        parent_id=company.id))
    unit = services.hr.create_unit(admin, OrgUnitInput(
        code="UN1", title_fa="واحد مالی", kind=H.UNIT_UNIT, parent_id=branch.id))
    return company, branch, unit


@pytest.fixture()
def employee(services, admin, org):
    _company, _branch, unit = org
    return services.hr.create_employee(admin, EmployeeInput(
        code="EMP-1001", first_name="سارا", last_name="محمدی",
        national_id="0012345678", mobile="09121112233",
        hire_date=TODAY, org_unit_id=unit.id, job_title="کارشناس حسابداری",
        position="کارشناس", base_salary=Decimal("25000000"),
        bank_name="بانک ملت", iban="IR120170000000123456789012"))


# ------------------------------------------------------------------ structure
def test_org_unit_tree_reports_path_and_depth(services, admin, org):
    company, branch, unit = org
    units = {row.code: row for row in services.hr.list_units(admin)}
    assert units["UN1"].path == "زرین هرمز / شعبهٔ مرکزی / واحد مالی"
    assert units["UN1"].depth == 2  # depth is zero-based: the root is 0
    assert units["BR1"].parent_id == company.id
    assert units["CO"].parent_id is None
    assert branch  # the fixture creates it through the real service


def test_org_unit_cannot_be_its_own_ancestor(services, admin, org):
    company, _branch, unit = org
    with pytest.raises(ValidationError):
        services.hr.update_unit(admin, company.id,
                                OrgUnitInput(code="CO", title_fa="زرین هرمز",
                                             kind=H.UNIT_COMPANY, parent_id=unit.id))


def test_org_chart_nests_children(services, admin, org):
    roots = services.hr.org_chart(admin)
    assert len(roots) == 1
    company = roots[0]
    assert company.unit.code == "CO"
    assert [child.unit.code for child in company.children] == ["BR1"]
    assert [child.unit.code for child in company.children[0].children] == ["UN1"]


# ------------------------------------------------------------------- employees
def test_employee_gets_default_code_and_person(services, admin):
    row = services.hr.create_employee(admin, EmployeeInput(
        first_name="علی", last_name="رضایی", hire_date=TODAY,
        base_salary=Decimal("10000000")))
    assert row.code.startswith("EMP-")
    assert row.person_id
    assert row.full_name == "علی رضایی"
    # the person row is the accounting detail account, so payroll/treasury agree
    with services.db.session_scope() as session:
        from pars_erp.db.models import DetailAccount
        person = session.get(DetailAccount, row.person_id)
        assert person is not None and "علی" in person.name


def test_duplicate_personnel_code_is_refused(services, admin, employee):
    with pytest.raises(ConflictError):
        services.hr.create_employee(admin, EmployeeInput(
            code=employee.code, first_name="دیگری", last_name="همان کد",
            hire_date=TODAY))


def test_sensitive_fields_are_masked_without_permission(services, admin, employee):
    from dataclasses import replace
    context = replace(admin, permissions=frozenset({"hr.employees.view"}))
    row = services.hr.get_employee(context, employee.id)
    assert row.sensitive_visible is False
    assert row.national_id == "••••••5678"  # masked, last four digits only
    full = services.hr.get_employee(admin, employee.id)
    assert full.sensitive_visible is True
    assert full.national_id == "0012345678"


def test_searching_employees_by_code_and_name(services, admin, employee):
    by_code = services.hr.list_employees(admin, EmployeeFilter(search="EMP-1001"))
    by_name = services.hr.list_employees(admin, EmployeeFilter(search="سارا"))
    by_unit = services.hr.list_employees(admin, EmployeeFilter(
        org_unit_id=employee.org_unit_id))
    assert [row.id for row in by_code] == [employee.id]
    assert [row.id for row in by_name] == [employee.id]
    assert [row.id for row in by_unit] == [employee.id]


def test_moving_an_employee_keeps_history(services, admin, org, employee):
    _company, _branch, unit = org
    other = services.hr.create_unit(admin, OrgUnitInput(
        code="UN2", title_fa="واحد فروش", kind=H.UNIT_UNIT))
    services.hr.move_employees(admin, employee_ids=(employee.id,),
                               target_unit_id=other.id, effective_date=TODAY,
                               note="انتقال سازمانی")
    moved = services.hr.get_employee(admin, employee.id)
    assert moved.org_unit_id == other.id
    history = services.hr.history(admin, employee.id)
    assert any(row.kind == H.HISTORY_UNIT and "واحد فروش" in row.to_value
               for row in history)
    assert unit.id != other.id


def test_deactivate_employee_records_status_history(services, admin, employee):
    row = services.hr.deactivate_employee(admin, employee.id, end_date=TODAY,
                                          reason="استعفا")
    assert row.collaboration_status == H.COLLAB_LEFT
    assert row.is_active is False
    history = services.hr.history(admin, employee.id)
    assert history[0].kind == H.HISTORY_STATUS
    assert history[0].to_value == H.COLLAB_LEFT


def test_editing_an_employee_without_permission_is_denied(services, admin, employee):
    from dataclasses import replace
    limited = replace(admin, permissions=frozenset({"hr.employees.view"}))
    with pytest.raises(PermissionDeniedError):
        services.hr.create_employee(limited, EmployeeInput(
            first_name="ناشناس", last_name="بدون مجوز", hire_date=TODAY))


# ------------------------------------------------------------------- contracts
def test_contract_sets_salary_and_is_listed(services, admin, employee):
    contract = services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, contract_type=H.CONTRACT_FIXED,
        start_date=TODAY, end_date=TODAY + _dt.timedelta(days=365),
        base_salary=Decimal("32000000"), job_title="کارشناس ارشد"))
    assert contract.number.startswith("CTR-")
    assert contract.status == H.CONTRACT_ACTIVE
    refreshed = services.hr.get_employee(admin, employee.id)
    assert refreshed.base_salary == Decimal("32000000.00")
    assert refreshed.job_title == "کارشناس ارشد"
    active = services.hr.active_contract(admin, employee.id, on_date=TODAY)
    assert active is not None and active.id == contract.id


def test_contract_requires_end_after_start(services, admin, employee):
    with pytest.raises(ValidationError):
        services.hr.create_contract(admin, ContractInput(
            employee_id=employee.id, start_date=TODAY,
            end_date=TODAY - _dt.timedelta(days=1),
            base_salary=Decimal("1000")))


def test_renewing_a_contract_creates_a_successor(services, admin, employee):
    first = services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=TODAY,
        end_date=TODAY + _dt.timedelta(days=180), base_salary=Decimal("20000000")))
    second = services.hr.renew_contract(admin, first.id, ContractInput(
        employee_id=employee.id, start_date=TODAY + _dt.timedelta(days=181),
        base_salary=Decimal("24000000")))
    assert second.previous_contract_id == first.id
    assert second.base_salary == Decimal("24000000.00")
    assert services.hr.get_employee(admin, employee.id).base_salary == \
        Decimal("24000000.00")
    with pytest.raises(ConflictError):
        services.hr.renew_contract(admin, first.id, ContractInput(
            employee_id=employee.id, start_date=TODAY + _dt.timedelta(days=400),
            base_salary=Decimal("1")))


def test_amending_salary_requires_a_reason_and_logs_history(services, admin,
                                                            employee):
    contract = services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=TODAY,
        base_salary=Decimal("15000000")))
    with pytest.raises(ValidationError):
        services.hr.amend_contract(admin, contract.id,
                                   base_salary=Decimal("16000000"), note="")
    amended = services.hr.amend_contract(admin, contract.id,
                                         base_salary=Decimal("16500000"),
                                         note="افزایش سالانه")
    assert amended.base_salary == Decimal("16500000.00")
    kinds = {row.kind for row in services.hr.history(admin, employee.id)}
    assert H.HISTORY_SALARY in kinds


def test_expiring_contracts_window(services, admin, employee, clock):
    services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=_dt.date.today() - _dt.timedelta(days=300),
        end_date=_dt.date.today() + _dt.timedelta(days=10),
        base_salary=Decimal("12000000")))
    expiring = services.hr.expiring_contracts(admin, days=30)
    assert len(expiring) == 1
    assert expiring[0].days_to_expiry is not None
    assert expiring[0].days_to_expiry <= 30
    assert services.hr.expiring_contracts(admin, days=5) == []


def test_terminating_a_contract_closes_it(services, admin, employee):
    contract = services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=TODAY,
        base_salary=Decimal("9000000")))
    closed = services.hr.terminate_contract(admin, contract.id, end_date=TODAY,
                                            reason="پایان پروژه")
    assert closed.status == H.CONTRACT_TERMINATED
    with pytest.raises(ConflictError):
        services.hr.terminate_contract(admin, contract.id)
