"""Employee loans and advances (phase 5, part 3).

A loan is a small contract: a principal, a number of installments, a repayment
start month and a status. The installments are rows, so:

* the payroll engine knows exactly which installment belongs to which month;
* deducting an installment from a payslip marks it ``deducted`` - the next month
  cannot deduct it again;
* ``remaining_debt`` is a sum of pending installments, never a number typed by an
  operator;
* paying the employee goes through the **treasury** (a real payment document with
  its journal), so the loan is a receivable in the books from day one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, Employee, Loan, LoanInstallment, PayRun, Payslip
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.payroll import constants as P
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import clean_text, next_document_number
from pars_erp.services.hr_common import ZERO, to_money
from pars_erp.treasury import constants as TC

DEFAULT_EMPLOYEE_ACCOUNT_CODE = "101008"


@dataclass(frozen=True)
class LoanInput:
    employee_id: int
    amount: Decimal | int | str
    kind: str = P.LOAN_KIND_LOAN
    request_date: _dt.date | None = None
    installments: int = 1
    repayment_start_year: int | None = None
    repayment_start_month: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class LoanPaymentInput:
    payment_date: _dt.date | None = None
    cash_box_id: int | None = None
    bank_account_id: int | None = None
    method: str = TC.METHOD_CASH
    tracking_no: str = ""


@dataclass(frozen=True)
class InstallmentRow:
    id: int
    seq: int
    due_year: int
    due_month: int
    amount: Decimal
    paid_amount: Decimal
    status: str
    status_fa: str
    slip_id: int | None
    paid_date: _dt.date | None

    @property
    def period_label(self) -> str:
        return f"{self.due_year}/{self.due_month:02d}"


@dataclass(frozen=True)
class LoanRow:
    id: int
    number: str
    employee_id: int
    employee_code: str
    employee_name: str
    kind: str
    kind_fa: str
    amount: Decimal
    request_date: _dt.date
    installments: int
    installment_amount: Decimal
    repayment_start_year: int
    repayment_start_month: int
    status: str
    status_fa: str
    paid_date: _dt.date | None
    remaining_debt: Decimal
    paid_amount: Decimal
    payment_id: int | None
    journal_id: int | None
    reason: str
    installments_rows: tuple[InstallmentRow, ...] = ()

    @property
    def display(self) -> str:
        return f"{self.number} — {self.employee_name}"

    @property
    def period_label(self) -> str:
        return f"{self.repayment_start_year}/{self.repayment_start_month:02d}"


class LoanService:
    def __init__(self, db: Database, audit: AuditService, *, vouchers=None,
                 journals=None) -> None:
        self.db = db
        self.audit = audit
        self.vouchers = vouchers
        self.journals = journals

    # ------------------------------------------------------------------- create
    def create(self, ctx: SecurityContext | None, data: LoanInput) -> LoanRow:
        require_permission(ctx, "payroll.loans.manage")
        amount = to_money(data.amount, field="amount")
        if amount <= 0:
            raise ValidationError("مبلغ وام/مساعده باید بزرگ‌تر از صفر باشد.", field="amount")
        if data.kind not in dict(P.LOAN_KINDS):
            raise ValidationError("نوع درخواست معتبر نیست.", field="kind")
        installments = max(1, int(data.installments or 1))
        if data.kind == P.LOAN_KIND_ADVANCE:
            installments = 1
        when = data.request_date or _dt.date.today()
        start_year = int(data.repayment_start_year or _dt.date.today().year)
        start_month = int(data.repayment_start_month or 1)
        if not 1 <= start_month <= 12:
            raise ValidationError("ماه شروع بازپرداخت معتبر نیست.",
                                  field="repayment_start_month")
        with self.db.session_scope() as session:
            employee = session.get(Employee, data.employee_id)
            if employee is None:
                raise NotFoundError("کارمند مورد نظر یافت نشد.")
            number = next_document_number(session, Loan, prefix="LN", on_date=when)
            per_installment = to_money(amount / Decimal(installments))
            loan = Loan(
                number=number, employee_id=employee.id, kind=data.kind, amount=amount,
                request_date=when, installments=installments,
                installment_amount=per_installment,
                repayment_start_year=start_year, repayment_start_month=start_month,
                status=P.LOAN_REQUESTED, reason=(data.reason or "").strip() or None,
                created_by_id=getattr(ctx, "user_id", None))
            session.add(loan)
            session.flush()
            self._build_installments(session, loan)
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="create",
                summary_fa=f"ثبت درخواست {P.LOAN_KIND_TITLES_FA[loan.kind]} {number}",
                after={"amount": str(amount), "installments": installments},
                session=session)
            return self._loan_row(session, loan, with_installments=True)

    # ------------------------------------------------------------------ workflow
    def approve(self, ctx: SecurityContext | None, loan_id: int) -> LoanRow:
        require_permission(ctx, "payroll.loans.manage")
        with self.db.session_scope() as session:
            loan = self._get_loan(session, loan_id)
            if loan.status != P.LOAN_REQUESTED:
                raise ConflictError("فقط درخواست در انتظار قابل تأیید است.")
            loan.status = P.LOAN_APPROVED
            loan.approved_by_id = getattr(ctx, "user_id", None)
            loan.approved_at = utcnow()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="approve",
                summary_fa=f"تأیید {P.LOAN_KIND_TITLES_FA[loan.kind]} {loan.number}",
                session=session)
            return self._loan_row(session, loan, with_installments=True)

    def reject(self, ctx: SecurityContext | None, loan_id: int, *, reason: str) -> LoanRow:
        require_permission(ctx, "payroll.loans.manage")
        if not (reason or "").strip():
            raise ValidationError("دلیل رد درخواست را وارد کنید.", field="reason")
        with self.db.session_scope() as session:
            loan = self._get_loan(session, loan_id)
            if loan.status != P.LOAN_REQUESTED:
                raise ConflictError("این درخواست در وضعیت قابل رد نیست.")
            loan.status = P.LOAN_REJECTED
            loan.note = reason
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="reject",
                summary_fa=f"رد درخواست {loan.number}", after={"reason": reason},
                session=session)
            return self._loan_row(session, loan, with_installments=True)

    def pay(self, ctx: SecurityContext | None, loan_id: int,
            data: LoanPaymentInput) -> LoanRow:
        """Pay the employee through the treasury and book the receivable."""
        require_permission(ctx, "payroll.loans.manage")
        if self.vouchers is None:  # pragma: no cover - composition guard
            raise ValidationError("سرویس خزانه در دسترس نیست.")
        from pars_erp.services.voucher_service import PaymentInput

        when = data.payment_date or _dt.date.today()
        with self.db.session_scope() as session:
            loan = self._get_loan(session, loan_id)
            if loan.status != P.LOAN_APPROVED:
                raise ConflictError("برای پرداخت، ابتدا درخواست را تأیید کنید.")
            employee = session.get(Employee, loan.employee_id)
            account = session.execute(
                select(Account).where(Account.code == DEFAULT_EMPLOYEE_ACCOUNT_CODE)
            ).scalars().first()
            if account is None:
                raise ValidationError("حساب «وام و مساعدهٔ کارکنان» در کدینگ حساب‌ها نیست؛ "
                                      "ابتدا کدینگ استاندارد را تکمیل کنید.")
            payment = self.vouchers.create_payment_in_session(
                session, ctx,
                PaymentInput(
                    payment_date=when, amount=Decimal(loan.amount),
                    payment_type=TC.PAYMENT_OTHER,
                    method=data.method,
                    cash_box_id=data.cash_box_id,
                    bank_account_id=data.bank_account_id,
                    payee_detail_id=employee.person_id if employee else None,
                    payee_name=f"{employee.first_name} {employee.last_name}".strip()
                    if employee else "",
                    counter_account_id=account.id,
                    tracking_no=data.tracking_no or "",
                    description=f"{P.LOAN_KIND_TITLES_FA[loan.kind]} {loan.number} — "
                                f"{employee.code if employee else ''}",
                    idempotency_key=f"loan:{loan.id}:payment"))
            self.vouchers.post_payment_in_session(session, payment, ctx)
            loan.payment_id = payment.id
            loan.journal_id = payment.journal_id
            loan.paid_date = when
            loan.status = P.LOAN_PAID
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="pay",
                summary_fa=f"پرداخت {P.LOAN_KIND_TITLES_FA[loan.kind]} {loan.number}",
                after={"payment_id": payment.id, "journal_id": payment.journal_id},
                session=session)
            return self._loan_row(session, loan, with_installments=True)

    def settle(self, ctx: SecurityContext | None, loan_id: int, *,
               note: str = "") -> LoanRow:
        """Early settlement: close the remaining installments, keep the history."""
        require_permission(ctx, "payroll.loans.manage")
        with self.db.session_scope() as session:
            loan = self._get_loan(session, loan_id)
            if loan.status not in (P.LOAN_PAID, P.LOAN_APPROVED):
                raise ConflictError("این وام قابل تسویه نیست.")
            remaining = Decimal("0")
            today = _dt.date.today()
            for installment in loan.installments_rows:
                if installment.status == P.INSTALLMENT_PENDING:
                    installment.status = P.INSTALLMENT_PAID
                    installment.paid_amount = Decimal(installment.amount or 0)
                    installment.paid_date = today
                    installment.note = note or "تسویهٔ پیش از موعد"
                    remaining += Decimal(installment.amount or 0)
            loan.status = P.LOAN_CLOSED
            loan.settled_at = utcnow()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="settle",
                summary_fa=f"تسویهٔ {loan.number}",
                after={"remaining": str(remaining), "note": note}, session=session)
            return self._loan_row(session, loan, with_installments=True)

    def cancel(self, ctx: SecurityContext | None, loan_id: int, *, reason: str) -> LoanRow:
        require_permission(ctx, "payroll.loans.manage")
        if not (reason or "").strip():
            raise ValidationError("دلیل لغو را وارد کنید.", field="reason")
        with self.db.session_scope() as session:
            loan = self._get_loan(session, loan_id)
            if loan.status not in (P.LOAN_REQUESTED, P.LOAN_APPROVED):
                raise ConflictError("وام پرداخت‌شده لغو نمی‌شود؛ از تسویه استفاده کنید.")
            loan.status = P.LOAN_CANCELLED
            loan.note = reason
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="loan", entity_id=loan.id, action="cancel",
                summary_fa=f"لغو درخواست {loan.number}", after={"reason": reason},
                session=session)
            return self._loan_row(session, loan, with_installments=True)

    # ---------------------------------------------------------------- read-only
    def list_loans(self, ctx: SecurityContext | None, *, employee_id: int | None = None,
                   status: str | None = None) -> list[LoanRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            query = select(Loan).order_by(Loan.request_date.desc(), Loan.id.desc())
            if employee_id:
                query = query.where(Loan.employee_id == employee_id)
            if status:
                query = query.where(Loan.status == status)
            return [self._loan_row(session, row, with_installments=False)
                    for row in session.execute(query).scalars()]

    def get(self, ctx: SecurityContext | None, loan_id: int) -> LoanRow:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            return self._loan_row(session, self._get_loan(session, loan_id),
                                  with_installments=True)

    def employee_debt(self, ctx: SecurityContext | None, employee_id: int) -> Decimal:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(LoanInstallment).join(Loan, Loan.id == LoanInstallment.loan_id)
                .where(Loan.employee_id == employee_id,
                       LoanInstallment.status == P.INSTALLMENT_PENDING)).scalars()
            return to_money(sum((Decimal(row.amount or 0) for row in rows), ZERO))

    def due_installments(self, ctx: SecurityContext | None, year: int,
                         month: int) -> list[InstallmentRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(LoanInstallment).where(LoanInstallment.due_year == year,
                                              LoanInstallment.due_month == month)
                .order_by(LoanInstallment.loan_id, LoanInstallment.seq)).scalars()
            return [self._installment_row(row) for row in rows]

    # ------------------------------------------------------------------ helpers
    def _build_installments(self, session: Session, loan: Loan) -> None:
        amount = Decimal(loan.amount or 0)
        count = max(1, int(loan.installments or 1))
        base = (amount / Decimal(count)).quantize(Decimal("0.01"))
        allocated = Decimal("0")
        year, month = int(loan.repayment_start_year), int(loan.repayment_start_month)
        for seq in range(1, count + 1):
            value = base
            if seq == count:  # the last installment absorbs the rounding remainder
                value = amount - allocated
            allocated += value
            session.add(LoanInstallment(
                loan_id=loan.id, seq=seq, due_year=year, due_month=month,
                amount=to_money(value), status=P.INSTALLMENT_PENDING))
            month += 1
            if month > 12:
                month = 1
                year += 1
        loan.installment_amount = to_money(base)
        session.flush()

    def _get_loan(self, session: Session, loan_id: int) -> Loan:
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise NotFoundError("وام/مساعدهٔ مورد نظر یافت نشد.")
        return loan

    def _installment_row(self, row: LoanInstallment) -> InstallmentRow:
        return InstallmentRow(
            id=row.id, seq=int(row.seq), due_year=int(row.due_year),
            due_month=int(row.due_month), amount=Decimal(row.amount or 0),
            paid_amount=Decimal(row.paid_amount or 0), status=row.status,
            status_fa=P.INSTALLMENT_TITLES_FA.get(row.status, row.status),
            slip_id=row.slip_id, paid_date=row.paid_date)

    def _loan_row(self, session: Session, loan: Loan,
                  *, with_installments: bool) -> LoanRow:
        employee = session.get(Employee, loan.employee_id)
        rows = tuple(self._installment_row(row) for row in loan.installments_rows) \
            if with_installments else ()
        remaining = sum((row.amount for row in loan.installments_rows
                         if row.status == P.INSTALLMENT_PENDING), ZERO)
        paid = sum((Decimal(row.paid_amount or 0) for row in loan.installments_rows),
                   ZERO)
        return LoanRow(
            id=loan.id, number=loan.number, employee_id=loan.employee_id,
            employee_code=employee.code if employee else "",
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            kind=loan.kind, kind_fa=P.LOAN_KIND_TITLES_FA.get(loan.kind, loan.kind),
            amount=Decimal(loan.amount or 0), request_date=loan.request_date,
            installments=int(loan.installments or 1),
            installment_amount=Decimal(loan.installment_amount or 0),
            repayment_start_year=int(loan.repayment_start_year or 0),
            repayment_start_month=int(loan.repayment_start_month or 0),
            status=loan.status,
            status_fa=P.LOAN_STATUS_TITLES_FA.get(loan.status, loan.status),
            paid_date=loan.paid_date, remaining_debt=to_money(remaining),
            paid_amount=to_money(paid), payment_id=loan.payment_id,
            journal_id=loan.journal_id, reason=loan.reason or "",
            installments_rows=rows)
