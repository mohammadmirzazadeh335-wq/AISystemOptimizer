"""Payroll reports: registers, component totals, payments and staff debt."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import select

from pars_erp.core.errors import NotFoundError
from pars_erp.core.jalali import format_gregorian_as_jalali
from pars_erp.db.models import (
    Employee,
    Loan,
    LoanInstallment,
    PayBatch,
    PayBatchItem,
    PayRun,
    Payslip,
    PayslipLine,
)
from pars_erp.db.session import Database
from pars_erp.payroll import constants as P
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.commerce_reports_service import ReportTable
from pars_erp.services.hr_common import ZERO


def _d(value: _dt.date | None) -> str:
    return format_gregorian_as_jalali(value) if value else ""


def _period(year: int, month: int) -> str:
    return f"{year}/{month:02d}"


class PayrollReportService:
    def __init__(self, db: Database, settings=None) -> None:
        self.db = db
        self.settings = settings

    # -------------------------------------------------------------------- runs
    def runs(self, ctx: SecurityContext | None, *,
             year: int | None = None) -> ReportTable:
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            query = select(PayRun).order_by(PayRun.period_year.desc(),
                                            PayRun.period_month.desc())
            if year:
                query = query.where(PayRun.period_year == int(year))
            runs = list(session.execute(query).scalars())
            rows = tuple(
                (run.number, _period(run.period_year, run.period_month),
                 P.RUN_STATUS_TITLES_FA.get(run.status, run.status),
                 int(run.employees_count or 0), Decimal(run.gross_total or 0),
                 Decimal(run.insurance_total or 0), Decimal(run.tax_total or 0),
                 Decimal(run.deductions_total or 0), Decimal(run.net_total or 0),
                 _d(run.calculated_at.date() if run.calculated_at else None))
                for run in runs)
            return ReportTable(
                "pay_runs", "دوره‌های حقوق",
                ("شماره", "دوره", "وضعیت", "تعداد کارمند", "جمع ناخالص", "بیمه",
                 "مالیات", "کسور", "خالص پرداختی", "تاریخ محاسبه"), rows,
                meta_fa=f"{len(rows)} دوره")

    def register(self, ctx: SecurityContext | None, run_id: int) -> ReportTable:
        """One row per employee of one payroll run."""
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            run = session.get(PayRun, run_id)
            if run is None:
                raise NotFoundError("دورهٔ حقوق یافت نشد.")
            slips = list(session.execute(
                select(Payslip).where(Payslip.run_id == run_id)
                .order_by(Payslip.id)).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = []
            for slip in slips:
                employee = employees.get(slip.employee_id)
                rows.append((
                    employee.code if employee else str(slip.employee_id),
                    employee.full_name if employee else "",
                    slip.number, Decimal(slip.worked_days or 0),
                    Decimal(slip.overtime_hours or 0), Decimal(slip.base_salary or 0),
                    Decimal(slip.benefits_total or 0), Decimal(slip.overtime_amount or 0),
                    Decimal(slip.bonus or 0), Decimal(slip.gross or 0),
                    Decimal(slip.insurance_employee or 0), Decimal(slip.income_tax or 0),
                    Decimal(slip.loan_installment or 0),
                    Decimal(slip.advance_deduction or 0),
                    Decimal(slip.other_deductions or 0), Decimal(slip.net or 0),
                    P.SLIP_STATUS_TITLES_FA.get(slip.status, slip.status),
                ))
            return ReportTable(
                "pay_register", f"لیست حقوق {_period(run.period_year, run.period_month)}",
                ("کد پرسنلی", "نام", "شمارهٔ فیش", "روز کارکرد", "ساعت اضافه‌کار",
                 "حقوق پایه", "مزایا", "اضافه‌کار", "پاداش", "ناخالص",
                 "بیمهٔ سهم کارمند", "مالیات", "قسط وام", "مساعده", "سایر کسور",
                 "خالص", "وضعیت"), tuple(rows),
                meta_fa=(f"{run.number} — {len(rows)} فیش — خالص "
                         f"{Decimal(run.net_total or 0)}"))

    def components(self, ctx: SecurityContext | None, run_id: int) -> ReportTable:
        """Totals of every payslip line kind/type across a run."""
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            run = session.get(PayRun, run_id)
            if run is None:
                raise NotFoundError("دورهٔ حقوق یافت نشد.")
            slip_ids = [row[0] for row in session.execute(
                select(Payslip.id).where(Payslip.run_id == run_id)).all()]
            lines = []
            if slip_ids:
                lines = list(session.execute(
                    select(PayslipLine).where(PayslipLine.slip_id.in_(slip_ids))
                ).scalars())
            buckets: dict[tuple[str, str], dict] = {}
            for line in lines:
                bucket = buckets.setdefault((line.kind, line.title_fa),
                                            {"amount": ZERO, "count": 0})
                bucket["amount"] += Decimal(line.amount or 0)
                bucket["count"] += 1
            rows = tuple(
                (title, "درآمد" if kind in P.EARNING_CODES else "کسور",
                 P.LINE_TITLES_FA.get(kind, kind), values["count"],
                 values["amount"])
                for (kind, title), values in sorted(buckets.items()))
            return ReportTable(
                "pay_components", "ریز اقلام حقوق",
                ("عنوان", "نوع", "کد قلم", "تعداد فیش", "مبلغ"), rows,
                meta_fa=_period(run.period_year, run.period_month))

    def payments(self, ctx: SecurityContext | None, run_id: int) -> ReportTable:
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            run = session.get(PayRun, run_id)
            if run is None:
                raise NotFoundError("دورهٔ حقوق یافت نشد.")
            batches = list(session.execute(
                select(PayBatch).where(PayBatch.run_id == run_id)
                .order_by(PayBatch.id)).scalars())
            batch_ids = [batch.id for batch in batches]
            items = []
            if batch_ids:
                items = list(session.execute(
                    select(PayBatchItem).where(PayBatchItem.batch_id.in_(batch_ids))
                    .order_by(PayBatchItem.id)).scalars())
            batch_by_id = {batch.id: batch for batch in batches}
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = []
            for item in items:
                batch = batch_by_id.get(item.batch_id)
                employee = employees.get(item.employee_id)
                rows.append((
                    batch.number if batch else "",
                    _d(batch.payment_date) if batch else "",
                    employee.code if employee else str(item.employee_id),
                    employee.full_name if employee else "",
                    Decimal(item.amount or 0),
                    P.ITEM_TITLES_FA.get(item.status, item.status),
                    item.tracking_no or "", item.failure_reason or "",
                    _d(item.paid_at.date() if item.paid_at else None),
                ))
            total = sum((Decimal(item.amount or 0) for item in items), ZERO)
            paid = sum((Decimal(item.amount or 0) for item in items
                        if item.status == P.ITEM_PAID), ZERO)
            return ReportTable(
                "pay_payments", "وضعیت پرداخت حقوق",
                ("دسته", "تاریخ پرداخت", "کد پرسنلی", "نام", "مبلغ", "وضعیت",
                 "شمارهٔ پیگیری", "علت ناموفق", "تاریخ واریز"), tuple(rows),
                meta_fa=f"جمع {total} — واریزشده {paid}")

    # ------------------------------------------------------------------- debt
    def loan_balances(self, ctx: SecurityContext | None, *,
                      only_open: bool = True) -> ReportTable:
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            query = select(Loan).order_by(Loan.number)
            if only_open:
                query = query.where(Loan.status.in_(
                    [P.LOAN_APPROVED, P.LOAN_PAID]))
            loans = list(session.execute(query).scalars())
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            installments = list(session.execute(select(LoanInstallment)).scalars())
            by_loan: dict[int, dict] = {}
            for installment in installments:
                bucket = by_loan.setdefault(installment.loan_id,
                                            {"remaining": ZERO, "paid": ZERO,
                                             "open": 0})
                amount = Decimal(installment.amount or 0)
                paid_amount = Decimal(installment.paid_amount or 0)
                bucket["paid"] += paid_amount
                if installment.status in (P.INSTALLMENT_PAID,
                                          P.INSTALLMENT_DEDUCTED):
                    continue
                bucket["open"] += 1
                bucket["remaining"] += amount - paid_amount
            rows = []
            for loan in loans:
                employee = employees.get(loan.employee_id)
                bucket = by_loan.get(loan.id, {"remaining": ZERO, "paid": ZERO,
                                               "open": 0})
                rows.append((
                    loan.number, employee.code if employee else str(loan.employee_id),
                    employee.full_name if employee else "",
                    P.LOAN_KIND_TITLES_FA.get(loan.kind, loan.kind),
                    _d(loan.request_date), Decimal(loan.amount or 0),
                    int(loan.installments or 0), Decimal(loan.installment_amount or 0),
                    bucket["paid"], bucket["remaining"], bucket["open"],
                    P.LOAN_STATUS_TITLES_FA.get(loan.status, loan.status),
                ))
            total_remaining = sum((row[9] for row in rows), ZERO)
            return ReportTable(
                "pay_loans", "بدهی و اقساط کارکنان",
                ("شماره", "کد پرسنلی", "نام", "نوع", "تاریخ درخواست", "مبلغ",
                 "تعداد اقساط", "مبلغ هر قسط", "پرداخت‌شده", "مانده", "اقساط باز",
                 "وضعیت"), tuple(rows),
                meta_fa=f"جمع مانده {total_remaining}")

    def advances(self, ctx: SecurityContext | None, *, year: int | None = None,
                 today: _dt.date | None = None) -> ReportTable:
        require_permission(ctx, "payroll.reports")
        with self.db.session_scope() as session:
            query = select(Loan).where(Loan.kind == P.LOAN_KIND_ADVANCE)
            loans = list(session.execute(query.order_by(Loan.number)).scalars())
            if year:
                loans = [loan for loan in loans
                         if loan.request_date and loan.request_date.year == int(year)]
            employees = {employee.id: employee
                         for employee in session.execute(select(Employee)).scalars()}
            rows = []
            for loan in loans:
                employee = employees.get(loan.employee_id)
                paid = sum((Decimal(item.paid_amount or 0)
                            for item in loan.installments_rows), ZERO)
                rows.append((
                    loan.number, employee.code if employee else str(loan.employee_id),
                    employee.full_name if employee else "", _d(loan.request_date),
                    Decimal(loan.amount or 0), paid,
                    Decimal(loan.amount or 0) - paid,
                    P.LOAN_STATUS_TITLES_FA.get(loan.status, loan.status),
                    loan.reason or "",
                ))
            return ReportTable(
                "pay_advances", "مساعده‌های کارکنان",
                ("شماره", "کد پرسنلی", "نام", "تاریخ", "مبلغ", "بازپرداخت‌شده",
                 "مانده", "وضعیت", "علت"), tuple(rows),
                meta_fa=f"{len(rows)} مورد — سال {year or 'همه'}")


__all__ = ["PayrollReportService"]
