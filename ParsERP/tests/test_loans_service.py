"""Phase-5 employee loans and advances: schedule, treasury payment, settlement."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.payroll import constants as P
from pars_erp.services.hr_service import EmployeeInput
from pars_erp.services.loans_service import LoanInput, LoanPaymentInput

D = Decimal
DAY = _dt.date(2026, 4, 22)


@pytest.fixture()
def employee(services, admin):
    return services.hr.create_employee(admin, EmployeeInput(
        code="EMP-4001", first_name="حمید", last_name="نوری", hire_date=DAY,
        base_salary=D("25000000")))


@pytest.fixture()
def loan(services, admin, employee, treasury):
    return services.loans.create(admin, LoanInput(
        employee_id=employee.id, amount=D("12000000"), installments=4,
        request_date=DAY, repayment_start_year=1405, repayment_start_month=2,
        reason="وام مسکن"))


def test_installment_schedule_splits_evenly(services, admin, loan):
    assert len(loan.installments_rows) == 4
    assert [row.amount for row in loan.installments_rows] == [D("3000000.00")] * 4
    assert [row.due_month for row in loan.installments_rows] == [2, 3, 4, 5]
    assert all(row.status == P.INSTALLMENT_PENDING for row in loan.installments_rows)


def test_rounding_remainder_lands_on_the_last_installment(services, admin, employee,
                                                          treasury):
    odd = services.loans.create(admin, LoanInput(
        employee_id=employee.id, amount=D("10000000"), installments=3,
        request_date=DAY, repayment_start_year=1405, repayment_start_month=1))
    amounts = [row.amount for row in odd.installments_rows]
    assert sum(amounts) == D("10000000.00")
    assert amounts[0] == amounts[1] == D("3333333.33")
    assert amounts[2] == D("3333333.34")


def test_advance_is_forced_to_a_single_installment(services, admin, employee,
                                                   treasury):
    advance = services.loans.create(admin, LoanInput(
        employee_id=employee.id, kind=P.LOAN_KIND_ADVANCE, amount=D("5000000"),
        installments=6, request_date=DAY, repayment_start_year=1405,
        repayment_start_month=2))
    assert advance.installments == 1
    assert len(advance.installments_rows) == 1
    assert advance.kind == P.LOAN_KIND_ADVANCE


def test_zero_or_negative_amount_is_refused(services, admin, employee, treasury):
    with pytest.raises(ValidationError):
        services.loans.create(admin, LoanInput(employee_id=employee.id, amount=0,
                                               request_date=DAY))


def test_only_an_approved_loan_can_be_paid(services, admin, loan, treasury):
    with pytest.raises(ConflictError):
        services.loans.pay(admin, loan.id, LoanPaymentInput(
            payment_date=DAY, bank_account_id=treasury.bank.id))


def test_paying_a_loan_creates_and_posts_the_treasury_payment(services, admin,
                                                              loan, treasury):
    services.loans.approve(admin, loan.id)
    paid = services.loans.pay(admin, loan.id, LoanPaymentInput(
        payment_date=DAY, bank_account_id=treasury.bank.id, tracking_no="TRK-1"))
    assert paid.status == P.LOAN_PAID
    assert paid.payment_id and paid.journal_id
    with services.db.session_scope() as session:
        from pars_erp.db.models import Journal, JournalLine, Payment
        journal = session.get(Journal, paid.journal_id)
        payment = session.get(Payment, paid.payment_id)
        assert payment.status == "posted"
        lines = list(session.execute(
            __import__("sqlalchemy").select(JournalLine)
            .where(JournalLine.journal_id == paid.journal_id)).scalars())
        debit = sum((D(line.debit or 0) for line in lines), D("0"))
        credit = sum((D(line.credit or 0) for line in lines), D("0"))
        assert debit == credit == D("12000000")
        # the receivable is booked against the employee account (101008)
        from sqlalchemy import select as _select
        from pars_erp.db.models import Account
        employee_account = session.execute(
            _select(Account.id).where(Account.code == "101008")).scalar()
        assert employee_account in {line.account_id for line in lines}
        assert journal.status == "posted"


def test_paying_the_same_loan_twice_is_refused(services, admin, loan, treasury):
    services.loans.approve(admin, loan.id)
    services.loans.pay(admin, loan.id, LoanPaymentInput(
        payment_date=DAY, bank_account_id=treasury.bank.id))
    with pytest.raises(ConflictError):
        services.loans.pay(admin, loan.id, LoanPaymentInput(
            payment_date=DAY, bank_account_id=treasury.bank.id))


def test_early_settlement_closes_the_remaining_installments(services, admin, loan,
                                                            treasury):
    services.loans.approve(admin, loan.id)
    services.loans.pay(admin, loan.id, LoanPaymentInput(
        payment_date=DAY, bank_account_id=treasury.bank.id))
    settled = services.loans.settle(admin, loan.id, note="تسویهٔ زودهنگام")
    assert settled.status == P.LOAN_CLOSED
    assert all(row.status == P.INSTALLMENT_PAID for row in settled.installments_rows)
    assert services.loans.employee_debt(admin, settled.employee_id) == D("0.00")


def test_employee_debt_sums_the_open_installments(services, admin, loan, treasury):
    services.loans.approve(admin, loan.id)
    services.loans.pay(admin, loan.id, LoanPaymentInput(
        payment_date=DAY, bank_account_id=treasury.bank.id))
    assert services.loans.employee_debt(admin, loan.employee_id) == D("12000000.00")
    due = services.loans.due_installments(admin, 1405, 2)
    assert len(due) == 1
    assert due[0].amount == D("3000000.00")


def test_reject_requires_a_reason_and_blocks_the_payment(services, admin, loan,
                                                        treasury):
    with pytest.raises(ValidationError):
        services.loans.reject(admin, loan.id, reason="")
    rejected = services.loans.reject(admin, loan.id, reason="سابقهٔ بازپرداخت ندارد")
    assert rejected.status == P.LOAN_REJECTED
    with pytest.raises(ConflictError):
        services.loans.pay(admin, loan.id, LoanPaymentInput(
            payment_date=DAY, bank_account_id=treasury.bank.id))
