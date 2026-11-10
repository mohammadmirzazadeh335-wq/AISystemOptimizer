"""Payroll: dated settings versions, the monthly run, payslips and the journal.

The chain is deliberately boring and auditable:

1. a **settings version** holds every rate/allowance the engine may read;
2. a **run** is one Jalali month; calculating it reads contracts, attendance,
   approved overtime/leave, loans and the version, and writes one **payslip** per
   employee with itemised lines;
3. approving locks the numbers; posting writes **one balanced journal** for the
   whole run through the configurable ``payroll.salary`` posting pattern;
4. payment happens in :mod:`pars_erp.services.payroll_payment_service`, over the
   phase-4 treasury documents.

Nothing here is a legal rate: an empty version simply produces zero tax/insurance
and says so on the payslip.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Contract,
    Employee,
    Loan,
    LoanInstallment,
    PayRun,
    PaySettingsVersion,
    PaySettingItem,
    PayTaxBracket,
    Payslip,
    PayslipLine,
)
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.hr import constants as H
from pars_erp.payroll import constants as P
from pars_erp.payroll import engine
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.attendance_service import AttendanceService
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import clean_code, clean_text, next_document_number
from pars_erp.services.hr_common import ZERO, month_range, to_money


# ------------------------------------------------------------------ dataclasses
@dataclass(frozen=True)
class TaxBracketInput:
    from_amount: Decimal | int | str = 0
    to_amount: Decimal | int | str | None = None
    rate_percent: Decimal | int | str = 0
    note: str = ""


@dataclass(frozen=True)
class VersionInput:
    code: str
    title_fa: str
    effective_from: _dt.date
    effective_to: _dt.date | None = None
    status: str = P.VERSION_DRAFT
    source_note: str = ""
    notes: str = ""
    items: dict[str, str] = field(default_factory=dict)
    brackets: tuple[TaxBracketInput, ...] = ()


@dataclass(frozen=True)
class VersionRow:
    id: int
    code: str
    title_fa: str
    effective_from: _dt.date
    effective_to: _dt.date | None
    status: str
    status_fa: str
    items: dict[str, str]
    brackets: tuple[tuple[Decimal, Decimal | None, Decimal], ...]
    source_note: str
    notes: str

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class RunRow:
    id: int
    number: str
    period_year: int
    period_month: int
    period_start: _dt.date
    period_end: _dt.date
    status: str
    status_fa: str
    settings_version_id: int | None
    settings_version: str
    employees_count: int
    gross_total: Decimal
    deductions_total: Decimal
    net_total: Decimal
    insurance_total: Decimal
    tax_total: Decimal
    journal_id: int | None
    notes: str

    @property
    def period_label(self) -> str:
        return f"{self.period_year}/{self.period_month:02d}"


@dataclass(frozen=True)
class PayslipLineRow:
    kind: str
    title_fa: str
    side: str
    amount: Decimal
    detail: str


@dataclass(frozen=True)
class PayslipRow:
    id: int
    number: str
    run_id: int
    period_year: int
    period_month: int
    employee_id: int
    employee_code: str
    employee_name: str
    org_unit: str
    job_title: str
    status: str
    status_fa: str
    worked_days: Decimal
    absent_days: Decimal
    paid_leave_days: Decimal
    overtime_hours: Decimal
    base_salary: Decimal
    benefits_total: Decimal
    overtime_amount: Decimal
    bonus: Decimal
    gross: Decimal
    absence_deduction: Decimal
    insurance_employee: Decimal
    insurance_employer: Decimal
    income_tax: Decimal
    loan_installment: Decimal
    advance_deduction: Decimal
    other_deductions: Decimal
    deductions_total: Decimal
    net: Decimal
    payment_id: int | None
    lines: tuple[PayslipLineRow, ...] = ()

    @property
    def period_label(self) -> str:
        return f"{self.period_year}/{self.period_month:02d}"


@dataclass(frozen=True)
class CalculationSummary:
    run: RunRow
    employees: int
    gross: Decimal
    net: Decimal
    skipped: tuple[str, ...]


# --------------------------------------------------------------------- service
class PayrollService:
    def __init__(self, db: Database, audit: AuditService, *,
                 journals=None, posting=None, settings=None,
                 attendance: AttendanceService | None = None) -> None:
        self.db = db
        self.audit = audit
        self.journals = journals
        self.posting = posting
        self.settings = settings
        self.attendance = attendance or AttendanceService(db, audit, settings)

    # ---------------------------------------------------------- settings versions
    def list_versions(self, ctx: SecurityContext | None) -> list[VersionRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(PaySettingsVersion)
                .order_by(PaySettingsVersion.effective_from.desc())).scalars()
            return [self._version_row(row) for row in rows]

    def get_version(self, ctx: SecurityContext | None, version_id: int) -> VersionRow:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            row = session.get(PaySettingsVersion, version_id)
            if row is None:
                raise NotFoundError("نسخهٔ تنظیمات حقوق یافت نشد.")
            return self._version_row(row)

    def create_version(self, ctx: SecurityContext | None, data: VersionInput) -> VersionRow:
        require_permission(ctx, "payroll.settings")
        with self.db.session_scope() as session:
            version = self._build_version(session, data, ctx)
            session.add(version)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_settings_version", entity_id=version.id,
                action="create",
                summary_fa=f"ایجاد نسخهٔ تنظیمات حقوق {version.code}",
                after={"code": version.code, "from": str(version.effective_from),
                       "items": len(version.items), "brackets": len(version.brackets)},
                session=session)
            return self._version_row(version)

    def update_version(self, ctx: SecurityContext | None, version_id: int,
                       data: VersionInput) -> VersionRow:
        """Edit a version that no run has used yet; used versions are immutable."""
        require_permission(ctx, "payroll.settings")
        with self.db.session_scope() as session:
            version = session.get(PaySettingsVersion, version_id)
            if version is None:
                raise NotFoundError("نسخهٔ تنظیمات حقوق یافت نشد.")
            used = session.execute(
                select(func.count(PayRun.id)).where(
                    PayRun.settings_version_id == version.id,
                    PayRun.status.in_((P.RUN_APPROVED, P.RUN_POSTED, P.RUN_PAID)))
            ).scalar() or 0
            if used:
                raise ConflictError(
                    "این نسخهٔ تنظیمات در یک دورهٔ تأییدشده استفاده شده است؛ برای تغییر "
                    "نرخ‌ها یک نسخهٔ جدید با تاریخ اجرا بسازید.")
            before = {"code": version.code, "from": str(version.effective_from)}
            for item in list(version.items):
                session.delete(item)
            for bracket in list(version.brackets):
                session.delete(bracket)
            session.flush()
            version.code = clean_code(data.code, label="کد نسخه")
            version.title_fa = clean_text(data.title_fa, field="title_fa",
                                          label="عنوان نسخه", required=True, max_length=160)
            version.effective_from = data.effective_from
            version.effective_to = data.effective_to
            version.status = data.status
            version.source_note = (data.source_note or "").strip() or None
            version.notes = (data.notes or "").strip() or None
            self._fill_version(session, version, data)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_settings_version", entity_id=version.id,
                action="update",
                summary_fa=f"ویرایش نسخهٔ تنظیمات حقوق {version.code}", before=before,
                after={"code": version.code, "items": len(version.items)}, session=session)
            return self._version_row(version)

    def ensure_default_version(self, ctx: SecurityContext | None, *,
                               effective_from: _dt.date | None = None) -> VersionRow:
        """Seed one version with every key at zero - rates stay for the user to fill."""
        require_permission(ctx, "payroll.settings")
        start = effective_from or _dt.date(2026, 3, 21)
        with self.db.session_scope() as session:
            existing = session.execute(
                select(PaySettingsVersion).order_by(
                    PaySettingsVersion.effective_from)).scalars().first()
            if existing is not None:
                return self._version_row(existing)
            payload = VersionInput(
                code=f"V{start.year}", title_fa="نسخهٔ پایهٔ تنظیمات حقوق",
                effective_from=start, status=P.VERSION_ACTIVE,
                source_note=("نرخ‌ها و مبالغ این نسخه خالی است. پیش از اجرای حقوق، مقادیر "
                             "را از منبع رسمی (قوانین کار و تأمین اجتماعی همان سال) در "
                             "همین صفحه وارد کنید."),
                items={key: "0" for key in P.PAY_SETTING_KEYS})
            version = self._build_version(session, payload, ctx)
            session.add(version)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_settings_version", entity_id=version.id,
                action="create", summary_fa="ایجاد نسخهٔ پایهٔ تنظیمات حقوق",
                after={"keys": len(P.PAY_SETTING_KEYS)}, session=session)
            return self._version_row(version)

    def activate_version(self, ctx: SecurityContext | None, version_id: int) -> VersionRow:
        require_permission(ctx, "payroll.settings")
        with self.db.session_scope() as session:
            version = session.get(PaySettingsVersion, version_id)
            if version is None:
                raise NotFoundError("نسخهٔ تنظیمات حقوق یافت نشد.")
            version.status = P.VERSION_ACTIVE
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_settings_version", entity_id=version.id,
                action="activate",
                summary_fa=f"فعال‌سازی نسخهٔ تنظیمات حقوق {version.code}", session=session)
            return self._version_row(version)

    def version_for(self, session: Session, year: int, month: int) -> PaySettingsVersion:
        start, _end = month_range(year, month)
        version = session.execute(
            select(PaySettingsVersion).where(
                PaySettingsVersion.effective_from <= start,
                or_(PaySettingsVersion.effective_to.is_(None),
                    PaySettingsVersion.effective_to >= start))
            .order_by(PaySettingsVersion.effective_from.desc())).scalars().first()
        if version is None:
            version = session.execute(
                select(PaySettingsVersion).order_by(
                    PaySettingsVersion.effective_from.desc())).scalars().first()
        if version is None:
            raise ValidationError(
                "هیچ نسخهٔ تنظیمات حقوق تعریف نشده است؛ ابتدا در صفحهٔ تنظیمات حقوق یک "
                "نسخه با تاریخ اجرا بسازید.")
        return version

    # ------------------------------------------------------------------- runs
    def list_runs(self, ctx: SecurityContext | None) -> list[RunRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(PayRun).order_by(PayRun.period_year.desc(),
                                        PayRun.period_month.desc())).scalars()
            return [self._run_row(session, row) for row in rows]

    def get_run(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            return self._run_row(session, self._get_run(session, run_id))

    def create_run(self, ctx: SecurityContext | None, *, year: int, month: int,
                   notes: str = "") -> RunRow:
        require_permission(ctx, "payroll.calculate")
        if not 1 <= int(month) <= 12:
            raise ValidationError("ماه دوره باید بین ۱ تا ۱۲ باشد.", field="month")
        start, end = month_range(year, month)
        with self.db.session_scope() as session:
            existing = session.execute(
                select(PayRun).where(PayRun.period_year == year,
                                     PayRun.period_month == month)).scalars().first()
            if existing is not None:
                raise ConflictError(
                    f"دورهٔ حقوق {year}/{month:02d} قبلاً ایجاد شده است ({existing.number}).")
            version = self.version_for(session, year, month)
            number = next_document_number(session, PayRun, prefix="PR", on_date=start)
            run = PayRun(number=number, period_year=int(year), period_month=int(month),
                         period_start=start, period_end=end,
                         settings_version_id=version.id, status=P.RUN_DRAFT,
                         notes=notes or None, created_by_id=getattr(ctx, "user_id", None))
            session.add(run)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_run", entity_id=run.id, action="create",
                summary_fa=f"ایجاد دورهٔ حقوق {run.number} ({year}/{month:02d})",
                after={"version": version.code}, session=session)
            return self._run_row(session, run)

    def calculate(self, ctx: SecurityContext | None, run_id: int) -> CalculationSummary:
        """(Re)calculate every payslip of a run from the documents."""
        require_permission(ctx, "payroll.calculate")
        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status in (P.RUN_APPROVED, P.RUN_POSTED, P.RUN_PAID):
                raise ConflictError("دورهٔ تأییدشده یا ثبت‌شده قابل محاسبهٔ مجدد نیست.")
            version = (session.get(PaySettingsVersion, run.settings_version_id)
                       if run.settings_version_id else
                       self.version_for(session, run.period_year, run.period_month))
            if run.settings_version_id is None:
                run.settings_version_id = version.id
            values = self._version_values(version)
            brackets = [(Decimal(b.from_amount or 0),
                         (Decimal(b.to_amount) if b.to_amount is not None else None),
                         Decimal(b.rate_percent or 0)) for b in version.brackets]
            self._clear_slips(session, run)
            employees = list(session.execute(
                select(Employee).where(Employee.is_active.is_(True),
                                       Employee.collaboration_status == H.COLLAB_ACTIVE)
                .order_by(Employee.code)).scalars())
            skipped: list[str] = []
            totals = {"gross": ZERO, "deductions": ZERO, "net": ZERO,
                      "insurance": ZERO, "tax": ZERO}
            count = 0
            for index, employee in enumerate(employees, start=1):
                contract = session.execute(
                    select(Contract).where(
                        Contract.employee_id == employee.id,
                        Contract.status == H.CONTRACT_ACTIVE,
                        Contract.start_date <= run.period_end,
                        or_(Contract.end_date.is_(None),
                            Contract.end_date >= run.period_start))
                    .order_by(Contract.start_date.desc())).scalars().first()
                base = Decimal((contract.base_salary if contract else employee.base_salary)
                               or 0)
                if base <= 0:
                    skipped.append(f"{employee.code} — بدون قرارداد/حقوق پایه")
                    continue
                slip = self._calculate_employee(
                    session, run, version, values, brackets, employee, contract, base,
                    index)
                count += 1
                totals["gross"] += Decimal(slip.gross)
                totals["deductions"] += Decimal(slip.deductions_total)
                totals["net"] += Decimal(slip.net)
                totals["insurance"] += (Decimal(slip.insurance_employee)
                                        + Decimal(slip.insurance_employer))
                totals["tax"] += Decimal(slip.income_tax)
            run.employees_count = count
            run.gross_total = to_money(totals["gross"])
            run.deductions_total = to_money(totals["deductions"])
            run.net_total = to_money(totals["net"])
            run.insurance_total = to_money(totals["insurance"])
            run.tax_total = to_money(totals["tax"])
            run.status = P.RUN_CALCULATED
            run.calculated_at = utcnow()
            run.calculated_by_id = getattr(ctx, "user_id", None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_run", entity_id=run.id, action="calculate",
                summary_fa=f"محاسبهٔ حقوق {run.number} برای {count} کارمند",
                after={"gross": str(run.gross_total), "net": str(run.net_total),
                       "skipped": len(skipped)}, session=session)
            return CalculationSummary(
                run=self._run_row(session, run), employees=count,
                gross=Decimal(run.gross_total), net=Decimal(run.net_total),
                skipped=tuple(skipped))

    def payslips(self, ctx: SecurityContext | None, run_id: int) -> list[PayslipRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(Payslip).where(Payslip.run_id == run_id)
                .order_by(Payslip.number)).scalars()
            return [self._payslip_row(session, row, with_lines=False) for row in rows]

    def payslip(self, ctx: SecurityContext | None, payslip_id: int) -> PayslipRow:
        require_permission(ctx, "payroll.payslip.view")
        with self.db.session_scope() as session:
            row = session.get(Payslip, payslip_id)
            if row is None:
                raise NotFoundError("فیش حقوقی یافت نشد.")
            return self._payslip_row(session, row, with_lines=True)

    def employee_payslips(self, ctx: SecurityContext | None, employee_id: int,
                          year: int | None = None) -> list[PayslipRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            query = select(Payslip).where(Payslip.employee_id == employee_id)
            if year:
                query = query.join(PayRun, PayRun.id == Payslip.run_id).where(
                    PayRun.period_year == year)
            rows = session.execute(query.order_by(Payslip.number)).scalars()
            return [self._payslip_row(session, row, with_lines=False) for row in rows]

    def approve(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        require_permission(ctx, "payroll.approve")
        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status not in (P.RUN_CALCULATED, P.RUN_DRAFT):
                raise ConflictError("این دوره در وضعیت قابل تأیید نیست.")
            slips = list(session.execute(
                select(Payslip).where(Payslip.run_id == run.id)).scalars())
            if not slips:
                raise ValidationError("دورهٔ حقوق فیشی ندارد؛ ابتدا محاسبه کنید.")
            run.status = P.RUN_APPROVED
            run.approved_at = utcnow()
            run.approved_by_id = getattr(ctx, "user_id", None)
            for slip in slips:
                slip.status = P.SLIP_APPROVED
            self._apply_loan_installments(session, slips)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_run", entity_id=run.id, action="approve",
                summary_fa=f"تأیید حقوق {run.number} ({len(slips)} فیش)",
                after={"net": str(run.net_total)}, session=session)
            return self._run_row(session, run)

    def post(self, ctx: SecurityContext | None, run_id: int) -> RunRow:
        """Post the run's single balanced journal through the posting pattern."""
        require_permission(ctx, "payroll.approve")
        if self.posting is None or self.journals is None:  # pragma: no cover
            raise ValidationError("سرویس حسابداری در دسترس نیست.")
        from pars_erp.services.treasury_common import post_system_journal

        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status == P.RUN_POSTED or run.journal_id:
                raise ConflictError("سند این دوره قبلاً ثبت شده است.")
            if run.status != P.RUN_APPROVED:
                raise ConflictError("برای ثبت سند، ابتدا دوره را تأیید کنید.")
            slips = list(session.execute(
                select(Payslip).where(Payslip.run_id == run.id)).scalars())
            absence_total = sum((Decimal(s.absence_deduction or 0) for s in slips),
                                ZERO)
            rounding_total = sum(
                (Decimal(s.insurance_employee or 0) + Decimal(s.income_tax or 0)
                 + Decimal(s.absence_deduction or 0) + Decimal(s.loan_installment or 0)
                 + Decimal(s.advance_deduction or 0)
                 + Decimal(s.other_deductions or 0)
                 - Decimal(s.deductions_total or 0) for s in slips), ZERO)
            components = {
                P.SRC_GROSS: Decimal(run.gross_total or 0),
                # expense = gross − absence + rounding, which is exactly what makes
                # the pattern balance when the net was rounded to a step
                P.SRC_SALARY_EXPENSE: (Decimal(run.gross_total or 0) - absence_total
                                       + rounding_total),
                P.SRC_EMPLOYER_INSURANCE: sum(
                    (Decimal(s.insurance_employer or 0) for s in slips), ZERO),
                P.SRC_INSURANCE_TOTAL: Decimal(run.insurance_total or 0),
                P.SRC_TAX: Decimal(run.tax_total or 0),
                P.SRC_LOAN: sum((Decimal(s.loan_installment or 0) for s in slips), ZERO),
                P.SRC_ADVANCE: sum((Decimal(s.advance_deduction or 0) for s in slips), ZERO),
                P.SRC_OTHER_DEDUCTION: sum(
                    (Decimal(s.other_deductions or 0) for s in slips), ZERO),
                P.SRC_NET: Decimal(run.net_total or 0),
            }
            draft = self.posting.build_entry(
                session, operation=P.POSTING_SALARY, components=components,
                party_detail_id=None, party_account_hint_id=None,
                description=f"حقوق و دستمزد {run.period_year}/{run.period_month:02d}")
            journal = post_system_journal(
                session, journals=self.journals, ctx=ctx, entry_date=run.period_end,
                title_fa=f"حقوق و دستمزد {run.period_year}/{run.period_month:02d}",
                reference_no=run.number,
                idempotency_key=f"payrun:{run.id}:journal",
                notes=run.notes or "", draft=draft, source_kind="pay_run",
                source_id=run.id)
            run.journal_id = journal.id
            for slip in slips:
                slip.journal_id = journal.id
            run.status = P.RUN_POSTED
            run.posted_at = utcnow()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_run", entity_id=run.id, action="post",
                summary_fa=f"ثبت سند حقوق {run.number}",
                after={"journal_id": journal.id, "amount": str(run.gross_total)},
                session=session)
            return self._run_row(session, run)

    def cancel_run(self, ctx: SecurityContext | None, run_id: int, *, reason: str) -> RunRow:
        require_permission(ctx, "payroll.calculate")
        if not (reason or "").strip():
            raise ValidationError("دلیل لغو دوره را وارد کنید.", field="reason")
        with self.db.session_scope() as session:
            run = self._get_run(session, run_id)
            if run.status in (P.RUN_POSTED, P.RUN_PAID):
                raise ConflictError("دورهٔ ثبت‌شده یا پرداخت‌شده لغو نمی‌شود.")
            run.status = P.RUN_CANCELLED
            run.notes = f"{run.notes or ''}\nلغو: {reason}".strip()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_run", entity_id=run.id, action="cancel",
                summary_fa=f"لغو دورهٔ حقوق {run.number}", after={"reason": reason},
                session=session)
            return self._run_row(session, run)

    # -------------------------------------------------------------- calculation
    def _calculate_employee(self, session: Session, run: PayRun,
                            version: PaySettingsVersion, values: dict[str, Decimal],
                            brackets, employee: Employee, contract: Contract | None,
                            base: Decimal, index: int) -> Payslip:
        summary = self.attendance.attendance_summary(session, employee.id,
                                                     run.period_start, run.period_end)
        normal_hours, holiday_hours = self.attendance.approved_overtime_hours(
            session, employee.id, run.period_start, run.period_end)
        mission_allowance = self.attendance.approved_mission_allowance(
            session, employee.id, run.period_start, run.period_end)
        work_days = values.get(P.SETTING_WORK_DAYS, Decimal("30")) or Decimal("30")
        absent = summary["absent_days"]
        worked = summary["present_days"] if summary["present_days"] else work_days - absent
        loan_amount, advance_amount = self._due_installments(
            session, employee.id, run.period_year, run.period_month)
        years = Decimal("0")
        if employee.hire_date:
            years = Decimal(max(0, (run.period_end - employee.hire_date).days // 365))
        inputs = engine.PayInputs(
            base_salary=base,
            worked_days=worked, absent_days=absent,
            paid_leave_days=summary["leave_days"],
            overtime_hours=normal_hours, holiday_overtime_hours=holiday_hours,
            work_days_per_month=work_days,
            base_hours_per_month=values.get(P.SETTING_BASE_HOURS, Decimal("176")),
            overtime_factor=values.get(P.SETTING_OVERTIME_FACTOR, Decimal("1.4")),
            holiday_overtime_factor=values.get(P.SETTING_HOLIDAY_FACTOR, Decimal("2")),
            housing_allowance=values.get(P.SETTING_HOUSING, ZERO),
            food_allowance=values.get(P.SETTING_FOOD, ZERO),
            child_allowance_per_child=values.get(P.SETTING_CHILD, ZERO),
            children_count=int(employee.children_count or 0),
            marriage_allowance=values.get(P.SETTING_MARRIAGE, ZERO),
            is_married=(employee.marital_status == H.MARITAL_MARRIED),
            seniority_years=years,
            seniority_allowance_per_year=values.get(P.SETTING_SENIORITY, ZERO),
            continuous_benefit=values.get(P.SETTING_CONTINUOUS, ZERO),
            non_continuous_benefit=values.get(P.SETTING_NON_CONTINUOUS, ZERO),
            mission_allowance=mission_allowance,
            insurance_employee_rate=values.get(P.SETTING_INSURANCE_EMPLOYEE, ZERO),
            insurance_employer_rate=values.get(P.SETTING_INSURANCE_EMPLOYER, ZERO),
            insurance_base_cap=values.get(P.SETTING_INSURANCE_BASE_CAP, ZERO),
            tax_exempt_amount=values.get(P.SETTING_TAX_EXEMPT, ZERO),
            tax_brackets=tuple(brackets),
            absence_deduction_per_day=values.get(P.SETTING_ABSENCE, ZERO),
            loan_installment=loan_amount, advance_deduction=advance_amount,
            rounding_step=values.get(P.SETTING_ROUNDING, Decimal("0.01")),
        )
        result = engine.calculate(inputs)
        slip = Payslip(
            number=f"{run.number}/{employee.code}", run_id=run.id,
            employee_id=employee.id, contract_id=contract.id if contract else None,
            settings_version_id=version.id,
            worked_days=worked, absent_days=absent,
            paid_leave_days=summary["leave_days"],
            overtime_hours=normal_hours + holiday_hours,
            base_salary=result.base_salary, benefits_total=result.benefits_total,
            overtime_amount=result.overtime_amount, bonus=result.bonus,
            gross=result.gross, absence_deduction=result.absence_deduction,
            insurance_employee=result.insurance_employee,
            insurance_employer=result.insurance_employer, income_tax=result.income_tax,
            loan_installment=result.loan_installment,
            advance_deduction=result.advance_deduction,
            other_deductions=result.other_deductions,
            deductions_total=result.deductions_total, net=result.net,
            status=P.SLIP_DRAFT, note="؛ ".join(result.notes) or None)
        session.add(slip)
        session.flush()
        for position, line in enumerate(result.lines, start=1):
            session.add(PayslipLine(
                slip_id=slip.id, kind=line.kind, title_fa=line.title_fa,
                side=line.side, amount=line.amount, detail=line.detail or None,
                sort_order=position))
        session.flush()
        return slip

    def _due_installments(self, session: Session, employee_id: int, year: int,
                          month: int) -> tuple[Decimal, Decimal]:
        rows = list(session.execute(
            select(LoanInstallment, Loan).join(Loan, Loan.id == LoanInstallment.loan_id)
            .where(Loan.employee_id == employee_id,
                   LoanInstallment.due_year == year,
                   LoanInstallment.due_month == month,
                   LoanInstallment.status == P.INSTALLMENT_PENDING,
                   Loan.status == P.LOAN_PAID)).all())
        loan_total = sum((Decimal(inst.amount or 0) for inst, loan in rows
                          if loan.kind == P.LOAN_KIND_LOAN), ZERO)
        advance_total = sum((Decimal(inst.amount or 0) for inst, loan in rows
                             if loan.kind == P.LOAN_KIND_ADVANCE), ZERO)
        return to_money(loan_total), to_money(advance_total)

    def _apply_loan_installments(self, session: Session, slips: list[Payslip]) -> None:
        """Mark the installments a payslip deducted, so the next month cannot reuse them."""
        for slip in slips:
            if not slip.loan_installment and not slip.advance_deduction:
                continue
            run = session.get(PayRun, slip.run_id)
            rows = session.execute(
                select(LoanInstallment).join(Loan, Loan.id == LoanInstallment.loan_id)
                .where(Loan.employee_id == slip.employee_id,
                       LoanInstallment.due_year == run.period_year,
                       LoanInstallment.due_month == run.period_month,
                       LoanInstallment.status == P.INSTALLMENT_PENDING)).scalars()
            for installment in rows:
                installment.status = P.INSTALLMENT_DEDUCTED
                installment.paid_amount = Decimal(installment.amount or 0)
                installment.slip_id = slip.id
            session.flush()

    # ------------------------------------------------------------------ helpers
    def _get_run(self, session: Session, run_id: int) -> PayRun:
        run = session.get(PayRun, run_id)
        if run is None:
            raise NotFoundError("دورهٔ حقوق یافت نشد.")
        return run

    def _clear_slips(self, session: Session, run: PayRun) -> None:
        for slip in session.execute(
                select(Payslip).where(Payslip.run_id == run.id)).scalars():
            session.delete(slip)
        session.flush()

    def _build_version(self, session: Session, data: VersionInput,
                       ctx: SecurityContext | None) -> PaySettingsVersion:
        if data.status not in dict(P.VERSION_STATUSES):
            raise ValidationError("وضعیت نسخهٔ تنظیمات معتبر نیست.", field="status")
        if data.effective_to and data.effective_to < data.effective_from:
            raise ValidationError("پایان اعتبار نسخه قبل از شروع آن است.",
                                  field="effective_to")
        version = PaySettingsVersion(
            code=clean_code(data.code, label="کد نسخه"),
            title_fa=clean_text(data.title_fa, field="title_fa", label="عنوان نسخه",
                                required=True, max_length=160),
            effective_from=data.effective_from, effective_to=data.effective_to,
            status=data.status,
            source_note=(data.source_note or "").strip() or None,
            notes=(data.notes or "").strip() or None,
            created_by_id=getattr(ctx, "user_id", None))
        self._fill_version(session, version, data)
        return version

    def _fill_version(self, session: Session, version: PaySettingsVersion,
                      data: VersionInput) -> None:
        for key, value in (data.items or {}).items():
            if key not in P.PAY_SETTING_KEYS:
                raise ValidationError(f"کلید تنظیمات «{key}» شناخته‌شده نیست.",
                                      field="items")
            version.items.append(PaySettingItem(key=key, value=str(value)))
        for index, bracket in enumerate(data.brackets, start=1):
            rate = Decimal(str(bracket.rate_percent or 0))
            if rate < 0 or rate > 100:
                raise ValidationError("نرخ مالیات باید بین ۰ تا ۱۰۰ درصد باشد.",
                                      field="rate_percent")
            version.brackets.append(PayTaxBracket(
                sort_order=index,
                from_amount=to_money(bracket.from_amount, field="from_amount"),
                to_amount=(to_money(bracket.to_amount, field="to_amount")
                           if bracket.to_amount not in (None, "") else None),
                rate_percent=rate, note=(bracket.note or "").strip() or None))

    def _version_values(self, version: PaySettingsVersion) -> dict[str, Decimal]:
        values = {key: ZERO for key in P.PAY_SETTING_KEYS}
        for item in version.items:
            try:
                values[item.key] = Decimal(str(item.value or "0"))
            except Exception:  # pragma: no cover - bad manual data
                values[item.key] = ZERO
        return values

    def _version_row(self, version: PaySettingsVersion) -> VersionRow:
        return VersionRow(
            id=version.id, code=version.code, title_fa=version.title_fa,
            effective_from=version.effective_from, effective_to=version.effective_to,
            status=version.status,
            status_fa=P.VERSION_TITLES_FA.get(version.status, version.status),
            items={item.key: item.value for item in version.items},
            brackets=tuple((Decimal(b.from_amount or 0),
                            (Decimal(b.to_amount) if b.to_amount is not None else None),
                            Decimal(b.rate_percent or 0)) for b in version.brackets),
            source_note=version.source_note or "", notes=version.notes or "")

    def _run_row(self, session: Session, run: PayRun) -> RunRow:
        version = (session.get(PaySettingsVersion, run.settings_version_id)
                   if run.settings_version_id else None)
        return RunRow(
            id=run.id, number=run.number, period_year=run.period_year,
            period_month=run.period_month, period_start=run.period_start,
            period_end=run.period_end, status=run.status,
            status_fa=P.RUN_STATUS_TITLES_FA.get(run.status, run.status),
            settings_version_id=run.settings_version_id,
            settings_version=version.code if version else "",
            employees_count=int(run.employees_count or 0),
            gross_total=Decimal(run.gross_total or 0),
            deductions_total=Decimal(run.deductions_total or 0),
            net_total=Decimal(run.net_total or 0),
            insurance_total=Decimal(run.insurance_total or 0),
            tax_total=Decimal(run.tax_total or 0), journal_id=run.journal_id,
            notes=run.notes or "")

    def _payslip_row(self, session: Session, slip: Payslip,
                     *, with_lines: bool) -> PayslipRow:
        employee = session.get(Employee, slip.employee_id)
        run = session.get(PayRun, slip.run_id)
        unit_title = ""
        if employee is not None and employee.org_unit_id:
            from pars_erp.db.models import OrgUnit
            unit = session.get(OrgUnit, employee.org_unit_id)
            unit_title = unit.title_fa if unit else ""
        lines = tuple(PayslipLineRow(kind=line.kind, title_fa=line.title_fa,
                                     side=line.side, amount=Decimal(line.amount or 0),
                                     detail=line.detail or "")
                      for line in (slip.lines if with_lines else ()))
        return PayslipRow(
            id=slip.id, number=slip.number, run_id=slip.run_id,
            period_year=run.period_year if run else 0,
            period_month=run.period_month if run else 0,
            employee_id=slip.employee_id,
            employee_code=employee.code if employee else "",
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            org_unit=unit_title, job_title=(employee.job_title or "") if employee else "",
            status=slip.status,
            status_fa=P.SLIP_STATUS_TITLES_FA.get(slip.status, slip.status),
            worked_days=Decimal(slip.worked_days or 0),
            absent_days=Decimal(slip.absent_days or 0),
            paid_leave_days=Decimal(slip.paid_leave_days or 0),
            overtime_hours=Decimal(slip.overtime_hours or 0),
            base_salary=Decimal(slip.base_salary or 0),
            benefits_total=Decimal(slip.benefits_total or 0),
            overtime_amount=Decimal(slip.overtime_amount or 0),
            bonus=Decimal(slip.bonus or 0), gross=Decimal(slip.gross or 0),
            absence_deduction=Decimal(slip.absence_deduction or 0),
            insurance_employee=Decimal(slip.insurance_employee or 0),
            insurance_employer=Decimal(slip.insurance_employer or 0),
            income_tax=Decimal(slip.income_tax or 0),
            loan_installment=Decimal(slip.loan_installment or 0),
            advance_deduction=Decimal(slip.advance_deduction or 0),
            other_deductions=Decimal(slip.other_deductions or 0),
            deductions_total=Decimal(slip.deductions_total or 0),
            net=Decimal(slip.net or 0), payment_id=slip.payment_id, lines=lines)
