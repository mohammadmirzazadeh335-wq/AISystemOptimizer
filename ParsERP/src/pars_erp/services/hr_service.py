"""Employees, the org structure and contracts (phase 5, part 1).

The service enforces three rules the rest of the phase depends on:

* **the employee IS a person**: creating an employee creates (or links) the
  ``acc_details`` record, so payroll, loans and treasury all address the same id;
* **history is append-only**: a unit/job/salary/status change writes an
  ``hr_employee_history`` row; nothing rewrites yesterday's data;
* **sensitive data is permission-gated**: national id, birth date, bank data and
  base salary are masked unless the caller holds ``hr.employees.sensitive`` -
  enforced here, not in the screen, so a direct service call cannot leak them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    Attendance,
    Contract,
    DetailAccount,
    Employee,
    EmployeeHistory,
    LeaveRequest,
    Loan,
    OrgUnit,
    Payslip,
)
from pars_erp.db.session import Database
from pars_erp.hr import constants as H
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import clean_code, clean_text, next_document_number
from pars_erp.services.hr_common import (
    MONEY,
    ZERO,
    employee_full_name,
    mask,
    org_unit_path,
    to_money,
)

DEFAULT_EMPLOYEE_ACCOUNT_CODE = "101008"


# ------------------------------------------------------------------- dataclasses
@dataclass(frozen=True)
class OrgUnitInput:
    code: str
    title_fa: str
    kind: str = H.UNIT_UNIT
    parent_id: int | None = None
    manager_employee_id: int | None = None
    cost_center_id: int | None = None
    sort_order: int = 0
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class OrgUnitRow:
    id: int
    code: str
    title_fa: str
    kind: str
    kind_fa: str
    parent_id: int | None
    parent_title: str
    manager_employee_id: int | None
    manager_name: str
    path: str
    depth: int
    employees_count: int
    is_active: bool
    description: str

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class EmployeeInput:
    code: str = ""
    first_name: str = ""
    last_name: str = ""
    person_id: int | None = None
    father_name: str = ""
    national_id: str = ""
    birth_date: _dt.date | None = None
    birth_place: str = ""
    gender: str = H.GENDER_MALE
    marital_status: str = H.MARITAL_SINGLE
    children_count: int = 0
    phone: str = ""
    mobile: str = ""
    email: str = ""
    address: str = ""
    emergency_contact: str = ""
    hire_date: _dt.date | None = None
    end_date: _dt.date | None = None
    employment_type: str = H.EMPLOYMENT_FULL_TIME
    collaboration_status: str = H.COLLAB_ACTIVE
    org_unit_id: int | None = None
    job_title: str = ""
    position: str = ""
    manager_id: int | None = None
    base_salary: Decimal | str | int = ZERO
    insurance_no: str = ""
    tax_file_no: str = ""
    bank_name: str = ""
    bank_account_no: str = ""
    iban: str = ""
    user_id: int | None = None
    attachment_path: str = ""
    notes: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class EmployeeRow:
    id: int
    code: str
    full_name: str
    person_id: int
    national_id: str
    birth_date: _dt.date | None
    mobile: str
    phone: str
    address: str
    email: str
    hire_date: _dt.date
    end_date: _dt.date | None
    employment_type: str
    employment_type_fa: str
    collaboration_status: str
    collaboration_status_fa: str
    org_unit_id: int | None
    org_unit_title: str
    org_unit_path: str
    job_title: str
    position: str
    manager_id: int | None
    manager_name: str
    base_salary: Decimal
    bank_name: str
    bank_account_no: str
    iban: str
    insurance_no: str
    children_count: int
    marital_status: str
    is_active: bool
    sensitive_visible: bool
    years_of_service: int
    active_contract: str = ""
    notes: str = ""

    @property
    def display(self) -> str:
        return f"{self.code} — {self.full_name}"


@dataclass(frozen=True)
class EmployeeFilter:
    search: str = ""
    org_unit_id: int | None = None
    collaboration_status: str | None = None
    employment_type: str | None = None
    active_only: bool = False


@dataclass(frozen=True)
class ContractInput:
    employee_id: int
    contract_type: str = H.CONTRACT_FIXED
    start_date: _dt.date | None = None
    end_date: _dt.date | None = None
    base_salary: Decimal | str | int = ZERO
    working_hours_weekly: Decimal | str | int = 44
    working_days_weekly: int = 6
    payment_terms: str = ""
    benefits: str = ""
    deductions: str = ""
    job_title: str = ""
    org_unit_id: int | None = None
    signed_date: _dt.date | None = None
    file_path: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ContractRow:
    id: int
    number: str
    employee_id: int
    employee_name: str
    contract_type: str
    contract_type_fa: str
    start_date: _dt.date
    end_date: _dt.date | None
    base_salary: Decimal
    working_hours_weekly: Decimal
    working_days_weekly: int
    status: str
    status_fa: str
    days_to_expiry: int | None
    previous_contract_id: int | None
    job_title: str
    org_unit_title: str
    notes: str

    @property
    def display(self) -> str:
        return f"{self.number} — {self.employee_name}"


@dataclass(frozen=True)
class HistoryRow:
    id: int
    kind: str
    kind_fa: str
    effective_date: _dt.date
    from_value: str
    to_value: str
    note: str
    user_name: str


@dataclass(frozen=True)
class OrgChartNode:
    unit: OrgUnitRow
    children: tuple["OrgChartNode", ...] = ()
    employees: tuple[tuple[int, str], ...] = ()


# --------------------------------------------------------------------- service
class HRService:
    def __init__(self, db: Database, audit: AuditService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------ org tree
    def list_units(self, ctx: SecurityContext | None, *, kind: str | None = None,
                   active_only: bool = True) -> list[OrgUnitRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(OrgUnit).order_by(OrgUnit.sort_order, OrgUnit.code)
            if kind:
                query = query.where(OrgUnit.kind == kind)
            if active_only:
                query = query.where(OrgUnit.is_active.is_(True))
            units = list(session.execute(query).scalars())
            counts = dict(session.execute(
                select(Employee.org_unit_id, func.count(Employee.id))
                .group_by(Employee.org_unit_id)).all())
            return [self._unit_row(session, unit, counts.get(unit.id, 0))
                    for unit in units]

    def create_unit(self, ctx: SecurityContext | None, data: OrgUnitInput) -> OrgUnitRow:
        require_permission(ctx, "hr.org.edit")
        with self.db.session_scope() as session:
            payload = self._validate_unit(session, data)
            unit = OrgUnit(**payload, created_by_id=self._uid(ctx))
            session.add(unit)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد واحد سازمانی تکراری است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="org_unit", entity_id=unit.id, action="create",
                summary_fa=f"ایجاد واحد سازمانی {unit.code} — {unit.title_fa}",
                after={"code": unit.code, "title": unit.title_fa, "kind": unit.kind},
                session=session)
            return self._unit_row(session, unit, 0)

    def update_unit(self, ctx: SecurityContext | None, unit_id: int,
                    data: OrgUnitInput) -> OrgUnitRow:
        require_permission(ctx, "hr.org.edit")
        with self.db.session_scope() as session:
            unit = self._get_unit(session, unit_id)
            payload = self._validate_unit(session, data, existing=unit)
            before = {"code": unit.code, "title": unit.title_fa, "kind": unit.kind,
                      "parent_id": unit.parent_id}
            for key, value in payload.items():
                setattr(unit, key, value)
            unit.updated_by_id = self._uid(ctx)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="org_unit", entity_id=unit.id, action="update",
                summary_fa=f"ویرایش واحد سازمانی {unit.code} — {unit.title_fa}",
                before=before,
                after={"code": unit.code, "title": unit.title_fa, "kind": unit.kind},
                session=session)
            count = session.execute(
                select(func.count(Employee.id)).where(Employee.org_unit_id == unit.id)
            ).scalar() or 0
            return self._unit_row(session, unit, int(count))

    def unit_choices(self, ctx: SecurityContext | None, *,
                     kinds: tuple[str, ...] | None = None) -> list[tuple[int, str]]:
        rows = self.list_units(ctx, active_only=True)
        if kinds:
            rows = [row for row in rows if row.kind in kinds]
        return [(row.id, row.display) for row in rows]

    def org_chart(self, ctx: SecurityContext | None) -> tuple[OrgChartNode, ...]:
        """Nested tree; employees are attached to their own unit only."""
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            units = list(session.execute(
                select(OrgUnit).order_by(OrgUnit.sort_order, OrgUnit.code)).scalars())
            counts = dict(session.execute(
                select(Employee.org_unit_id, func.count(Employee.id))
                .group_by(Employee.org_unit_id)).all())
            people: dict[int | None, list[tuple[int, str]]] = {}
            for employee in session.execute(
                    select(Employee).where(Employee.is_active.is_(True))
                    .order_by(Employee.code)).scalars():
                people.setdefault(employee.org_unit_id, []).append(
                    (employee.id, employee_full_name(employee)))
            rows = {unit.id: self._unit_row(session, unit, counts.get(unit.id, 0))
                    for unit in units}

            def build(parent_id: int | None) -> list[OrgChartNode]:
                nodes = []
                for unit in units:
                    if unit.parent_id != parent_id:
                        continue
                    nodes.append(OrgChartNode(
                        unit=rows[unit.id], children=tuple(build(unit.id)),
                        employees=tuple(people.get(unit.id, ()))))
                return nodes

            return tuple(build(None))

    def move_employees(self, ctx: SecurityContext | None, *, employee_ids: tuple[int, ...],
                       target_unit_id: int, effective_date: _dt.date | None = None,
                       note: str = "") -> int:
        """Move staff between units; history keeps the old unit for every person."""
        require_permission(ctx, "hr.org.edit")
        if not employee_ids:
            raise ValidationError("کارمندی برای انتقال انتخاب نشده است.", field="employee_ids")
        when = effective_date or _dt.date.today()
        moved = 0
        with self.db.session_scope() as session:
            target = self._get_unit(session, target_unit_id)
            for employee_id in employee_ids:
                employee = self._get_employee(session, employee_id)
                if employee.org_unit_id == target.id:
                    continue
                self._record_history(
                    session, ctx, employee, H.HISTORY_UNIT, when,
                    from_value=self._unit_label(session, employee.org_unit_id),
                    to_value=target.title_fa, note=note or "انتقال سازمانی")
                employee.org_unit_id = target.id
                moved += 1
                self.audit.log_audit(
                    ctx=ctx, entity_type="employee", entity_id=employee.id,
                    action="move_unit",
                    summary_fa=f"انتقال {employee.code} به {target.title_fa}",
                    after={"org_unit_id": target.id, "effective_date": str(when)},
                    session=session)
            session.flush()
        return moved

    # ----------------------------------------------------------------- employees
    def list_employees(self, ctx: SecurityContext | None,
                       filters: EmployeeFilter | None = None) -> list[EmployeeRow]:
        require_permission(ctx, "hr.employees.view")
        filters = filters or EmployeeFilter()
        with self.db.session_scope() as session:
            query = select(Employee).order_by(Employee.code)
            if filters.active_only:
                query = query.where(Employee.is_active.is_(True))
            if filters.org_unit_id:
                query = query.where(Employee.org_unit_id == filters.org_unit_id)
            if filters.collaboration_status:
                query = query.where(
                    Employee.collaboration_status == filters.collaboration_status)
            if filters.employment_type:
                query = query.where(Employee.employment_type == filters.employment_type)
            term = (filters.search or "").strip()
            if term:
                like = f"%{term}%"
                query = query.where(or_(
                    Employee.code.ilike(like), Employee.first_name.ilike(like),
                    Employee.last_name.ilike(like), Employee.national_id.ilike(like),
                    Employee.mobile.ilike(like), Employee.job_title.ilike(like)))
            return [self._employee_row(session, row, ctx)
                    for row in session.execute(query).scalars()]

    def get_employee(self, ctx: SecurityContext | None, employee_id: int) -> EmployeeRow:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            return self._employee_row(session, self._get_employee(session, employee_id),
                                      ctx)

    def employee_choices(self, ctx: SecurityContext | None, *,
                         active_only: bool = True) -> list[tuple[int, str]]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(Employee).order_by(Employee.code)
            if active_only:
                query = query.where(Employee.is_active.is_(True))
            return [(row.id, f"{row.code} — {employee_full_name(row)}")
                    for row in session.execute(query).scalars()]

    def create_employee(self, ctx: SecurityContext | None,
                        data: EmployeeInput) -> EmployeeRow:
        require_permission(ctx, "hr.employees.create")
        with self.db.session_scope() as session:
            payload, person = self._validate_employee(session, data)
            employee = Employee(**payload, created_by_id=self._uid(ctx))
            employee.person_id = person.id
            session.add(employee)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد پرسنلی تکراری است یا این شخص قبلاً کارمند شده است.") from exc
            self._record_history(session, ctx, employee, H.HISTORY_CONTRACT,
                                 employee.hire_date,
                                 to_value=f"استخدام — {data.employment_type}")
            if employee.org_unit_id:
                self._record_history(session, ctx, employee, H.HISTORY_UNIT,
                                     employee.hire_date,
                                     to_value=self._unit_label(session,
                                                               employee.org_unit_id))
            self.audit.log_audit(
                ctx=ctx, entity_type="employee", entity_id=employee.id, action="create",
                summary_fa=f"ایجاد پروندهٔ کارمند {employee.code} — "
                           f"{employee_full_name(employee)}",
                after={"code": employee.code, "hire_date": str(employee.hire_date),
                       "org_unit_id": employee.org_unit_id},
                session=session)
            return self._employee_row(session, employee, ctx)

    def update_employee(self, ctx: SecurityContext | None, employee_id: int,
                        data: EmployeeInput) -> EmployeeRow:
        require_permission(ctx, "hr.employees.edit")
        with self.db.session_scope() as session:
            employee = self._get_employee(session, employee_id)
            payload, _person = self._validate_employee(session, data, existing=employee)
            when = _dt.date.today()
            watched = {
                "org_unit_id": (H.HISTORY_UNIT,
                                lambda value: self._unit_label(session, value)),
                "job_title": (H.HISTORY_JOB, str),
                "position": (H.HISTORY_JOB, str),
                "base_salary": (H.HISTORY_SALARY, str),
                "collaboration_status": (H.HISTORY_STATUS, str),
            }
            for key, (kind, render) in watched.items():
                new_value = payload.get(key)
                old_value = getattr(employee, key)
                if new_value != old_value:
                    self._record_history(
                        session, ctx, employee, kind, when,
                        from_value=render(old_value) if old_value not in (None, "") else "",
                        to_value=render(new_value) if new_value not in (None, "") else "")
            before = {"code": employee.code, "org_unit_id": employee.org_unit_id,
                      "job_title": employee.job_title, "base_salary": str(employee.base_salary),
                      "collaboration_status": employee.collaboration_status}
            for key, value in payload.items():
                setattr(employee, key, value)
            employee.updated_by_id = self._uid(ctx)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="employee", entity_id=employee.id, action="update",
                summary_fa=f"ویرایش پروندهٔ کارمند {employee.code}", before=before,
                after={"code": employee.code, "org_unit_id": employee.org_unit_id,
                       "job_title": employee.job_title,
                       "base_salary": str(employee.base_salary),
                       "collaboration_status": employee.collaboration_status},
                session=session)
            return self._employee_row(session, employee, ctx)

    def deactivate_employee(self, ctx: SecurityContext | None, employee_id: int,
                            *, end_date: _dt.date | None = None,
                            reason: str = "") -> EmployeeRow:
        """Retire/leave an employee - refused when financial history exists."""
        require_permission(ctx, "hr.employees.edit")
        when = end_date or _dt.date.today()
        with self.db.session_scope() as session:
            employee = self._get_employee(session, employee_id)
            payslips = session.execute(
                select(func.count(Payslip.id)).where(Payslip.employee_id == employee.id)
            ).scalar() or 0
            loans = session.execute(
                select(func.count(Loan.id)).where(Loan.employee_id == employee.id,
                                                  Loan.status.in_(("approved", "paid")))
            ).scalar() or 0
            if payslips or loans:
                raise ConflictError(
                    "این کارمند سابقهٔ حقوق یا وام دارد و حذف نمی‌شود؛ با ثبت «تاریخ "
                    "پایان همکاری» غیرفعال کنید. سابقهٔ مالی باید حفظ شود.")
            self._record_history(session, ctx, employee, H.HISTORY_STATUS, when,
                                 from_value=employee.collaboration_status,
                                 to_value=H.COLLAB_LEFT, note=reason)
            employee.collaboration_status = H.COLLAB_LEFT
            employee.end_date = when
            employee.is_active = False
            employee.updated_by_id = self._uid(ctx)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="employee", entity_id=employee.id,
                action="deactivate",
                summary_fa=f"پایان همکاری کارمند {employee.code}",
                after={"end_date": str(when), "reason": reason}, session=session)
            return self._employee_row(session, employee, ctx)

    def history(self, ctx: SecurityContext | None, employee_id: int) -> list[HistoryRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(EmployeeHistory).where(EmployeeHistory.employee_id == employee_id)
                .order_by(EmployeeHistory.effective_date.desc(),
                          EmployeeHistory.id.desc())).scalars()
            return [HistoryRow(
                id=row.id, kind=row.kind,
                kind_fa=H.HISTORY_TITLES_FA.get(row.kind, row.kind),
                effective_date=row.effective_date, from_value=row.from_value or "",
                to_value=row.to_value or "", note=row.note or "",
                user_name=row.user_name or "") for row in rows]

    # ----------------------------------------------------------------- contracts
    def list_contracts(self, ctx: SecurityContext | None, *,
                       employee_id: int | None = None, status: str | None = None) -> list[ContractRow]:
        require_permission(ctx, "hr.employees.view")
        with self.db.session_scope() as session:
            query = select(Contract).order_by(Contract.start_date.desc(), Contract.id.desc())
            if employee_id:
                query = query.where(Contract.employee_id == employee_id)
            if status:
                query = query.where(Contract.status == status)
            return [self._contract_row(session, row) for row in
                    session.execute(query).scalars()]

    def create_contract(self, ctx: SecurityContext | None,
                        data: ContractInput) -> ContractRow:
        require_permission(ctx, "hr.contracts.manage")
        with self.db.session_scope() as session:
            employee = self._get_employee(session, data.employee_id)
            payload = self._validate_contract(session, data)
            number = next_document_number(session, Contract, prefix="CTR",
                                          on_date=payload["start_date"])
            contract = Contract(number=number, employee_id=employee.id, **payload,
                                created_by_id=self._uid(ctx))
            session.add(contract)
            session.flush()
            employee.base_salary = payload["base_salary"]
            if payload["job_title"]:
                employee.job_title = payload["job_title"]
            if payload["org_unit_id"]:
                employee.org_unit_id = payload["org_unit_id"]
            self._record_history(session, ctx, employee, H.HISTORY_CONTRACT,
                                 payload["start_date"], to_value=number,
                                 note=f"قرارداد {H.CONTRACT_TITLES_FA[payload['contract_type']]}")
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="contract", entity_id=contract.id, action="create",
                summary_fa=f"ثبت قرارداد {number} برای {employee.code}",
                after={"number": number, "start": str(contract.start_date),
                       "salary": str(contract.base_salary)}, session=session)
            return self._contract_row(session, contract)

    def renew_contract(self, ctx: SecurityContext | None, contract_id: int,
                       data: ContractInput) -> ContractRow:
        """Close the old contract as *renewed* and create its successor."""
        require_permission(ctx, "hr.contracts.manage")
        with self.db.session_scope() as session:
            old = self._get_contract(session, contract_id)
            if old.status == H.CONTRACT_RENEWED:
                raise ConflictError("این قرارداد قبلاً تمدید شده است.")
            employee = self._get_employee(session, old.employee_id)
            payload = self._validate_contract(session, data, employee=employee,
                                              require_start=True)
            if payload["start_date"] <= old.start_date:
                raise ValidationError("شروع قرارداد جدید باید بعد از قرارداد فعلی باشد.",
                                      field="start_date")
            number = next_document_number(session, Contract, prefix="CTR",
                                          on_date=payload["start_date"])
            new = Contract(number=number, employee_id=employee.id, **payload,
                           previous_contract_id=old.id, created_by_id=self._uid(ctx))
            session.add(new)
            old.status = H.CONTRACT_RENEWED
            old.end_date = old.end_date or (payload["start_date"] - _dt.timedelta(days=1))
            session.flush()
            employee.base_salary = payload["base_salary"]
            self._record_history(session, ctx, employee, H.HISTORY_CONTRACT,
                                 payload["start_date"], from_value=old.number,
                                 to_value=number, note="تمدید قرارداد")
            self.audit.log_audit(
                ctx=ctx, entity_type="contract", entity_id=new.id, action="renew",
                summary_fa=f"تمدید قرارداد {old.number} → {number}",
                after={"previous": old.number, "salary": str(new.base_salary)},
                session=session)
            return self._contract_row(session, new)

    def amend_contract(self, ctx: SecurityContext | None, contract_id: int, *,
                       base_salary: Decimal | None = None, end_date: _dt.date | None = None,
                       working_hours_weekly: Decimal | None = None, note: str = "") -> ContractRow:
        """Amend an active contract; the salary change also lands in the history."""
        require_permission(ctx, "hr.contracts.manage")
        if not note:
            raise ValidationError("دلیل اصلاح قرارداد را وارد کنید.", field="note")
        with self.db.session_scope() as session:
            contract = self._get_contract(session, contract_id)
            if contract.status not in (H.CONTRACT_ACTIVE, H.CONTRACT_DRAFT):
                raise ConflictError("قرارداد خاتمه‌یافته یا تمدیدشده اصلاح نمی‌شود.")
            employee = self._get_employee(session, contract.employee_id)
            before = {"salary": str(contract.base_salary), "end_date": str(contract.end_date),
                      "hours": str(contract.working_hours_weekly)}
            if base_salary is not None:
                new_salary = to_money(base_salary, field="base_salary")
                if new_salary <= 0:
                    raise ValidationError("حقوق پایه باید بزرگ‌تر از صفر باشد.",
                                          field="base_salary")
                contract.base_salary = new_salary
                employee.base_salary = new_salary
                self._record_history(session, ctx, employee, H.HISTORY_SALARY,
                                     _dt.date.today(), from_value=before["salary"],
                                     to_value=str(new_salary), note=note)
            if end_date is not None:
                contract.end_date = end_date
            if working_hours_weekly is not None:
                contract.working_hours_weekly = Decimal(str(working_hours_weekly))
            contract.amendment_note = (contract.amendment_note or "") + f"\n{note}"
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="contract", entity_id=contract.id, action="amend",
                summary_fa=f"اصلاح قرارداد {contract.number}", before=before,
                after={"salary": str(contract.base_salary),
                       "end_date": str(contract.end_date), "note": note},
                session=session)
            return self._contract_row(session, contract)

    def terminate_contract(self, ctx: SecurityContext | None, contract_id: int,
                           *, end_date: _dt.date | None = None, reason: str = "") -> ContractRow:
        require_permission(ctx, "hr.contracts.manage")
        with self.db.session_scope() as session:
            contract = self._get_contract(session, contract_id)
            if contract.status in (H.CONTRACT_TERMINATED, H.CONTRACT_RENEWED):
                raise ConflictError("این قرارداد قبلاً بسته شده است.")
            contract.status = H.CONTRACT_TERMINATED
            contract.end_date = end_date or _dt.date.today()
            contract.notes = f"{contract.notes or ''}\n{reason}".strip()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="contract", entity_id=contract.id,
                action="terminate",
                summary_fa=f"خاتمهٔ قرارداد {contract.number}",
                after={"end_date": str(contract.end_date), "reason": reason},
                session=session)
            return self._contract_row(session, contract)

    def expiring_contracts(self, ctx: SecurityContext | None,
                           days: int | None = None) -> list[ContractRow]:
        require_permission(ctx, "hr.employees.view")
        window = days if days is not None else self._setting_int("hr_contract_alert_days", 30)
        today = _dt.date.today()
        limit = today + _dt.timedelta(days=window)
        with self.db.session_scope() as session:
            rows = session.execute(
                select(Contract).where(Contract.status == H.CONTRACT_ACTIVE,
                                       Contract.end_date.is_not(None),
                                       Contract.end_date <= limit)
                .order_by(Contract.end_date)).scalars()
            return [self._contract_row(session, row) for row in rows]

    def active_contract(self, ctx: SecurityContext | None, employee_id: int,
                        on_date: _dt.date | None = None) -> ContractRow | None:
        require_permission(ctx, "hr.employees.view")
        when = on_date or _dt.date.today()
        with self.db.session_scope() as session:
            row = session.execute(
                select(Contract).where(
                    Contract.employee_id == employee_id,
                    Contract.status == H.CONTRACT_ACTIVE,
                    Contract.start_date <= when,
                    or_(Contract.end_date.is_(None), Contract.end_date >= when))
                .order_by(Contract.start_date.desc())).scalars().first()
            return self._contract_row(session, row) if row else None

    # ------------------------------------------------------------------ helpers
    def _setting_int(self, key: str, default: int) -> int:
        if self.settings is None:
            return default
        try:
            return int(self.settings.snapshot().int(key))
        except Exception:  # pragma: no cover - settings are optional in tools
            return default

    @staticmethod
    def _uid(ctx: SecurityContext | None) -> int | None:
        return getattr(ctx, "user_id", None)

    def _get_employee(self, session: Session, employee_id: int) -> Employee:
        employee = session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError("کارمند مورد نظر یافت نشد.")
        return employee

    def _get_unit(self, session: Session, unit_id: int) -> OrgUnit:
        unit = session.get(OrgUnit, unit_id)
        if unit is None:
            raise NotFoundError("واحد سازمانی مورد نظر یافت نشد.")
        return unit

    def _get_contract(self, session: Session, contract_id: int) -> Contract:
        contract = session.get(Contract, contract_id)
        if contract is None:
            raise NotFoundError("قرارداد مورد نظر یافت نشد.")
        return contract

    def _unit_label(self, session: Session, unit_id: int | None) -> str:
        if not unit_id:
            return ""
        unit = session.get(OrgUnit, unit_id)
        return unit.title_fa if unit else ""

    def _validate_unit(self, session: Session, data: OrgUnitInput,
                       existing: OrgUnit | None = None) -> dict:
        code = clean_code(data.code, label="کد واحد")
        title = clean_text(data.title_fa, field="title_fa", label="عنوان واحد",
                           required=True, max_length=160)
        if data.kind not in dict(H.ORG_UNIT_KINDS):
            raise ValidationError("نوع واحد سازمانی معتبر نیست.", field="kind")
        if data.parent_id:
            parent = self._get_unit(session, data.parent_id)
            if existing is not None and parent.id == existing.id:
                raise ValidationError("واحد نمی‌تواند والد خودش باشد.", field="parent_id")
            if existing is not None and self._is_descendant(session, parent, existing.id):
                raise ValidationError("انتخاب این والد یک حلقه در درخت سازمانی می‌سازد.",
                                      field="parent_id")
        return {"code": code, "title_fa": title, "kind": data.kind,
                "parent_id": data.parent_id, "manager_employee_id": data.manager_employee_id,
                "cost_center_id": data.cost_center_id, "sort_order": int(data.sort_order or 0),
                "is_active": bool(data.is_active),
                "description": (data.description or "").strip()}

    def _is_descendant(self, session: Session, unit: OrgUnit, ancestor_id: int) -> bool:
        current = unit
        seen: set[int] = set()
        while current is not None and current.id not in seen:
            if current.id == ancestor_id:
                return True
            seen.add(current.id)
            current = session.get(OrgUnit, current.parent_id) if current.parent_id else None
        return False

    def _validate_employee(self, session: Session, data: EmployeeInput,
                           existing: Employee | None = None) -> tuple[dict, DetailAccount]:
        first = clean_text(data.first_name, field="first_name", label="نام", required=True,
                           max_length=80)
        last = clean_text(data.last_name, field="last_name", label="نام خانوادگی",
                          required=True, max_length=80)
        if data.employment_type not in dict(H.EMPLOYMENT_TYPES):
            raise ValidationError("نوع استخدام معتبر نیست.", field="employment_type")
        if data.collaboration_status not in dict(H.COLLAB_STATUSES):
            raise ValidationError("وضعیت همکاری معتبر نیست.", field="collaboration_status")
        hire_date = data.hire_date or (existing.hire_date if existing else None)
        if hire_date is None:
            raise ValidationError("تاریخ استخدام را وارد کنید.", field="hire_date")
        if data.end_date and data.end_date < hire_date:
            raise ValidationError("تاریخ پایان همکاری نمی‌تواند قبل از استخدام باشد.",
                                  field="end_date")
        org_unit_id = data.org_unit_id
        if org_unit_id and session.get(OrgUnit, org_unit_id) is None:
            raise ValidationError("واحد سازمانی انتخاب‌شده یافت نشد.", field="org_unit_id")
        if data.manager_id and existing is not None and data.manager_id == existing.id:
            raise ValidationError("کارمند نمی‌تواند مدیر خودش باشد.", field="manager_id")
        base_salary = to_money(data.base_salary, field="base_salary")
        if base_salary < 0:
            raise ValidationError("حقوق پایه نمی‌تواند منفی باشد.", field="base_salary")
        code = clean_code(data.code, label="کد پرسنلی") if data.code.strip() else ""
        if not code:
            prefix = self._setting_text("hr_employee_code_prefix", "EMP")
            code = next_document_number(session, Employee, prefix=prefix,
                                        on_date=hire_date, column="code")
        person = self._person_for(session, data, first, last, existing)
        payload = {
            "code": code, "first_name": first, "last_name": last,
            "father_name": (data.father_name or "").strip() or None,
            "national_id": (data.national_id or "").strip() or None,
            "birth_date": data.birth_date,
            "birth_place": (data.birth_place or "").strip() or None,
            "gender": data.gender or None,
            "marital_status": data.marital_status or None,
            "children_count": max(0, int(data.children_count or 0)),
            "phone": (data.phone or "").strip() or None,
            "mobile": (data.mobile or "").strip() or None,
            "email": (data.email or "").strip() or None,
            "address": (data.address or "").strip() or None,
            "emergency_contact": (data.emergency_contact or "").strip() or None,
            "hire_date": hire_date, "end_date": data.end_date,
            "employment_type": data.employment_type,
            "collaboration_status": data.collaboration_status,
            "org_unit_id": org_unit_id,
            "job_title": (data.job_title or "").strip() or None,
            "position": (data.position or "").strip() or None,
            "manager_id": data.manager_id, "base_salary": base_salary,
            "insurance_no": (data.insurance_no or "").strip() or None,
            "tax_file_no": (data.tax_file_no or "").strip() or None,
            "bank_name": (data.bank_name or "").strip() or None,
            "bank_account_no": (data.bank_account_no or "").strip() or None,
            "iban": (data.iban or "").strip() or None,
            "user_id": data.user_id,
            "attachment_path": (data.attachment_path or "").strip() or None,
            "notes": (data.notes or "").strip() or None,
            "is_active": bool(data.is_active),
        }
        return payload, person

    def _person_for(self, session: Session, data: EmployeeInput, first: str, last: str,
                    existing: Employee | None) -> DetailAccount:
        """Link the person record (phase-3 ``acc_details``) or create one."""
        if existing is not None:
            person = session.get(DetailAccount, existing.person_id)
            if person is None:  # pragma: no cover - data integrity guard
                raise NotFoundError("پروندهٔ شخصی این کارمند یافت نشد.")
            person.name = f"{first} {last}"
            person.mobile = (data.mobile or "").strip() or None
            person.phone = (data.phone or "").strip() or None
            person.national_id = (data.national_id or "").strip() or None
            person.address = (data.address or "").strip() or None
            return person
        if data.person_id:
            person = session.get(DetailAccount, data.person_id)
            if person is None:
                raise ValidationError("شخص انتخاب‌شده یافت نشد.", field="person_id")
            taken = session.execute(
                select(Employee).where(Employee.person_id == person.id)).scalars().first()
            if taken is not None:
                raise ConflictError("این شخص قبلاً به‌عنوان کارمند ثبت شده است.")
            person.kind = "employee"
            return person
        account = session.execute(
            select(Account).where(Account.code == DEFAULT_EMPLOYEE_ACCOUNT_CODE)
        ).scalars().first()
        code = f"EMP-{(_dt.datetime.now().strftime('%f'))}".upper()
        person = DetailAccount(
            code=code, name=f"{first} {last}", kind="employee",
            account_id=account.id if account else None,
            phone=(data.phone or "").strip() or None,
            mobile=(data.mobile or "").strip() or None,
            national_id=(data.national_id or "").strip() or None,
            address=(data.address or "").strip() or None)
        session.add(person)
        session.flush()
        return person

    def _validate_contract(self, session: Session, data: ContractInput,
                           employee: Employee | None = None,
                           require_start: bool = False) -> dict:
        employee = employee or self._get_employee(session, data.employee_id)
        if data.contract_type not in dict(H.CONTRACT_TYPES):
            raise ValidationError("نوع قرارداد معتبر نیست.", field="contract_type")
        start = data.start_date or (_dt.date.today() if not require_start else None)
        if start is None:
            raise ValidationError("تاریخ شروع قرارداد را وارد کنید.", field="start_date")
        if data.end_date and data.end_date <= start:
            raise ValidationError("تاریخ پایان باید بعد از شروع باشد.", field="end_date")
        salary = to_money(data.base_salary, field="base_salary")
        if salary <= 0:
            raise ValidationError("حقوق پایهٔ قرارداد باید بزرگ‌تر از صفر باشد.",
                                  field="base_salary")
        if data.org_unit_id and session.get(OrgUnit, data.org_unit_id) is None:
            raise ValidationError("واحد سازمانی قرارداد یافت نشد.", field="org_unit_id")
        return {
            "contract_type": data.contract_type, "start_date": start,
            "end_date": data.end_date, "base_salary": salary,
            "working_hours_weekly": Decimal(str(data.working_hours_weekly)),
            "working_days_weekly": int(data.working_days_weekly),
            "payment_terms": (data.payment_terms or "").strip() or None,
            "benefits": (data.benefits or "").strip() or None,
            "deductions": (data.deductions or "").strip() or None,
            "job_title": (data.job_title or employee.job_title or "").strip() or None,
            "org_unit_id": data.org_unit_id or employee.org_unit_id,
            "signed_date": data.signed_date,
            "file_path": (data.file_path or "").strip() or None,
            "notes": (data.notes or "").strip() or None,
            "status": H.CONTRACT_ACTIVE,
        }

    def _record_history(self, session: Session, ctx: SecurityContext | None,
                        employee: Employee, kind: str, effective_date: _dt.date,
                        *, from_value: str = "", to_value: str = "", note: str = "") -> None:
        session.add(EmployeeHistory(
            employee_id=employee.id, kind=kind, effective_date=effective_date,
            from_value=from_value or None, to_value=to_value or None,
            note=note or None, user_id=self._uid(ctx),
            user_name=getattr(ctx, "full_name", None)))

    def _setting_text(self, key: str, default: str) -> str:
        if self.settings is None:
            return default
        try:
            return str(self.settings.snapshot().get(key) or default)
        except Exception:  # pragma: no cover
            return default

    def _unit_row(self, session: Session, unit: OrgUnit, count: int) -> OrgUnitRow:
        parent = session.get(OrgUnit, unit.parent_id) if unit.parent_id else None
        manager = session.get(Employee, unit.manager_employee_id) \
            if unit.manager_employee_id else None
        path = org_unit_path(session, unit)
        return OrgUnitRow(
            id=unit.id, code=unit.code, title_fa=unit.title_fa, kind=unit.kind,
            kind_fa=H.ORG_UNIT_TITLES_FA.get(unit.kind, unit.kind),
            parent_id=unit.parent_id, parent_title=parent.title_fa if parent else "",
            manager_employee_id=unit.manager_employee_id,
            manager_name=employee_full_name(manager), path=path,
            depth=max(0, path.count("/")), employees_count=count,
            is_active=unit.is_active, description=unit.description or "")

    def _employee_row(self, session: Session, employee: Employee,
                      ctx: SecurityContext | None) -> EmployeeRow:
        sensitive = bool(ctx and ctx.has("hr.employees.sensitive"))
        unit = session.get(OrgUnit, employee.org_unit_id) if employee.org_unit_id else None
        manager = session.get(Employee, employee.manager_id) if employee.manager_id else None
        contract = session.execute(
            select(Contract).where(Contract.employee_id == employee.id,
                                   Contract.status == H.CONTRACT_ACTIVE)
            .order_by(Contract.start_date.desc())).scalars().first()
        years = 0
        if employee.hire_date:
            years = max(0, (_dt.date.today() - employee.hire_date).days // 365)
        return EmployeeRow(
            id=employee.id, code=employee.code,
            full_name=employee_full_name(employee), person_id=employee.person_id,
            national_id=(employee.national_id or "") if sensitive else
                        mask(employee.national_id),
            birth_date=employee.birth_date if sensitive else None,
            mobile=employee.mobile or "", phone=employee.phone or "",
            address=employee.address or "", email=employee.email or "",
            hire_date=employee.hire_date, end_date=employee.end_date,
            employment_type=employee.employment_type,
            employment_type_fa=H.EMPLOYMENT_TITLES_FA.get(employee.employment_type,
                                                         employee.employment_type),
            collaboration_status=employee.collaboration_status,
            collaboration_status_fa=H.COLLAB_TITLES_FA.get(employee.collaboration_status,
                                                          employee.collaboration_status),
            org_unit_id=employee.org_unit_id, org_unit_title=unit.title_fa if unit else "",
            org_unit_path=org_unit_path(session, unit),
            job_title=employee.job_title or "", position=employee.position or "",
            manager_id=employee.manager_id, manager_name=employee_full_name(manager),
            base_salary=(Decimal(employee.base_salary or 0) if sensitive else ZERO),
            bank_name=(employee.bank_name or "") if sensitive else "",
            bank_account_no=(employee.bank_account_no or "") if sensitive else
                            mask(employee.bank_account_no),
            iban=(employee.iban or "") if sensitive else mask(employee.iban),
            insurance_no=(employee.insurance_no or "") if sensitive else "",
            children_count=int(employee.children_count or 0),
            marital_status=employee.marital_status or "",
            is_active=employee.is_active, sensitive_visible=sensitive,
            years_of_service=years,
            active_contract=contract.number if contract else "",
            notes=employee.notes or "")

    def _contract_row(self, session: Session, contract: Contract) -> ContractRow:
        employee = session.get(Employee, contract.employee_id)
        unit = session.get(OrgUnit, contract.org_unit_id) if contract.org_unit_id else None
        days = None
        if contract.end_date:
            days = (contract.end_date - _dt.date.today()).days
        return ContractRow(
            id=contract.id, number=contract.number, employee_id=contract.employee_id,
            employee_name=employee_full_name(employee),
            contract_type=contract.contract_type,
            contract_type_fa=H.CONTRACT_TITLES_FA.get(contract.contract_type,
                                                      contract.contract_type),
            start_date=contract.start_date, end_date=contract.end_date,
            base_salary=Decimal(contract.base_salary or 0),
            working_hours_weekly=Decimal(contract.working_hours_weekly or 0),
            working_days_weekly=int(contract.working_days_weekly or 0),
            status=contract.status,
            status_fa=H.CONTRACT_STATUS_TITLES_FA.get(contract.status, contract.status),
            days_to_expiry=days, previous_contract_id=contract.previous_contract_id,
            job_title=contract.job_title or "",
            org_unit_title=unit.title_fa if unit else "",
            notes=contract.notes or "")
