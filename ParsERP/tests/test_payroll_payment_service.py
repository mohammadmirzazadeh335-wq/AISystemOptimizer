"""Phase-5 salary payment batches: bank file, treasury payment, failure and retry."""

from __future__ import annotations

import datetime as _dt
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.hr import constants as H
from pars_erp.payroll import constants as P
from pars_erp.services.hr_service import ContractInput, EmployeeInput
from pars_erp.services.payroll_payment_service import BatchInput
from pars_erp.services.payroll_service import VersionInput

D = Decimal
PERIOD_YEAR, PERIOD_MONTH = 1405, 2
DAY = _dt.date(2026, 5, 10)

EMPLOYEES = (
    ("EMP-5001", "نگار", "سلطانی", "IR120170000000000000000001"),
    ("EMP-5002", "بهرام", "کیانی", "IR120170000000000000000002"),
)


@pytest.fixture()
def payroll_run(services, admin, chart, treasury):
    """Two employees with an approved (not yet posted) payroll run."""
    services.posting.ensure_default_rules(admin)
    services.payroll.create_version(admin, VersionInput(
        code="V1", title_fa="تنظیمات تست", effective_from=_dt.date(2026, 3, 21),
        status=P.VERSION_ACTIVE,
        items={P.SETTING_INSURANCE_EMPLOYEE: "7", P.SETTING_WORK_DAYS: "30"}))
    for code, first, last, iban in EMPLOYEES:
        employee = services.hr.create_employee(admin, EmployeeInput(
            code=code, first_name=first, last_name=last, hire_date=_dt.date(2024, 4, 1),
            base_salary=D("20000000"), iban=iban, bank_name="بانک ملت"))
        services.hr.create_contract(admin, ContractInput(
            employee_id=employee.id, start_date=_dt.date(2025, 3, 21),
            base_salary=D("20000000")))
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    services.payroll.calculate(admin, run.id)
    services.payroll.approve(admin, run.id)
    return run


def test_batch_requires_an_approved_run(services, admin, chart, treasury):
    services.payroll.create_version(admin, VersionInput(
        code="V1", title_fa="تنظیمات تست", effective_from=_dt.date(2026, 3, 21),
        status=P.VERSION_ACTIVE, items={P.SETTING_WORK_DAYS: "30"}))
    employee = services.hr.create_employee(admin, EmployeeInput(
        code="EMP-5009", first_name="بی", last_name="تأیید", hire_date=DAY,
        base_salary=D("1000000")))
    services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=_dt.date(2025, 3, 21),
        base_salary=D("1000000")))
    run = services.payroll.create_run(admin, year=PERIOD_YEAR, month=PERIOD_MONTH)
    with pytest.raises(ConflictError):
        services.payroll_payments.create_batch(admin, BatchInput(
            run_id=run.id, bank_account_id=treasury.bank.id))


def test_batch_lists_every_approved_slip(services, admin, payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY,
        bank_account_id=treasury.bank.id))
    assert batch.number.startswith("PB-")
    assert batch.items_count == 2
    assert len(batch.items) == 2
    assert batch.total_amount == sum((item.amount for item in batch.items), D("0"))
    assert batch.status == P.BATCH_DRAFT
    # payroll data are copied into the item, not referenced twice
    assert {item.employee_code for item in batch.items} == {"EMP-5001", "EMP-5002"}


def test_bank_file_follows_the_configured_columns(services, admin, payroll_run,
                                                  treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    content = services.payroll_payments.bank_file_content(admin, batch.id)
    lines = [line for line in content.splitlines() if line.strip()]
    assert lines[0].split(",") == ["employee_code", "full_name", "iban", "amount",
                                   "tracking_no"]
    assert len(lines) == 3
    assert "EMP-5001" in lines[1]

    services.settings.update(admin, {"payroll_payment_file_columns":
                                     "full_name,amount"})
    two = services.payroll_payments.bank_file_content(admin, batch.id)
    assert two.splitlines()[0].split(",") == ["full_name", "amount"]


def test_exporting_the_bank_file_writes_a_real_file(services, admin, payroll_run,
                                                    treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "salaries.csv"
        written = services.payroll_payments.export_bank_file(admin, batch.id, target)
        assert written.exists() and written.stat().st_size > 0
        assert "EMP-5002" in written.read_text(encoding="utf-8-sig")
    refreshed = services.payroll_payments.get_batch(admin, batch.id)
    assert refreshed.bank_file_name == "salaries.csv"


def test_paying_a_batch_marks_slips_and_posts_one_payment(services, admin,
                                                          payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    paid = services.payroll_payments.pay(admin, batch.id, tracking_no="TRK-77")
    assert paid.status == P.BATCH_PAID
    assert paid.paid_amount == paid.total_amount
    assert paid.journal_id
    slips = services.payroll.payslips(admin, payroll_run.id)
    assert all(slip.status == P.SLIP_PAID for slip in slips)
    run = services.payroll.get_run(admin, payroll_run.id)
    assert run.status == P.RUN_PAID

    with services.db.session_scope() as session:
        from pars_erp.db.models import Payment
        payment = session.get(Payment, paid.payment_id)
        assert payment.status == "posted"
        assert Decimal(payment.amount) == paid.total_amount


def test_a_batch_cannot_be_paid_twice(services, admin, payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    services.payroll_payments.pay(admin, batch.id)
    with pytest.raises(ConflictError):
        services.payroll_payments.pay(admin, batch.id)


def test_no_slip_can_be_paid_by_two_batches(services, admin, payroll_run, treasury):
    services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    with pytest.raises(ConflictError):
        services.payroll_payments.create_batch(admin, BatchInput(
            run_id=payroll_run.id, payment_date=DAY,
            bank_account_id=treasury.bank.id))


def test_failed_item_is_kept_and_can_be_retried_in_a_new_batch(services, admin,
                                                               payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    failed = services.payroll_payments.fail_item(
        admin, batch.items[0].id, reason="شمارهٔ حساب مسدود است")
    assert failed.status == P.ITEM_FAILED
    assert failed.failure_reason == "شمارهٔ حساب مسدود است"
    refreshed = services.payroll_payments.get_batch(admin, batch.id)
    assert refreshed.status in (P.BATCH_PARTIAL, P.BATCH_CANCELLED)
    assert len(services.payroll_payments.failed_items(admin)) == 1

    retry = services.payroll_payments.retry_batch(admin, batch.id)
    assert retry.id != batch.id
    assert retry.items_count == 1
    assert retry.items[0].employee_code == failed.employee_code
    assert retry.items[0].status == P.ITEM_PENDING
    # the same payslip now lives in exactly one batch
    with services.db.session_scope() as session:
        from sqlalchemy import func, select
        from pars_erp.db.models import PayBatchItem
        count = session.execute(
            select(func.count(PayBatchItem.id))
            .where(PayBatchItem.payslip_id == failed.payslip_id)).scalar()
    assert count == 1


def test_paying_a_partially_failed_batch_only_pays_its_pending_rows(services, admin,
                                                                     payroll_run,
                                                                     treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    failed = services.payroll_payments.fail_item(admin, batch.items[0].id,
                                                 reason="حساب بسته است")
    paid = services.payroll_payments.pay(admin, batch.id)
    assert paid.paid_amount == paid.total_amount - failed.amount
    slips = {slip.employee_code: slip for slip in
             services.payroll.payslips(admin, payroll_run.id)}
    assert slips[failed.employee_code].status == P.SLIP_APPROVED
    other = next(slip for slip in slips.values()
                 if slip.employee_code != failed.employee_code)
    assert other.status == P.SLIP_PAID


def test_failure_requires_a_reason(services, admin, payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    with pytest.raises(ValidationError):
        services.payroll_payments.fail_item(admin, batch.items[0].id, reason="")


def test_payment_reports_show_the_status(services, admin, payroll_run, treasury):
    batch = services.payroll_payments.create_batch(admin, BatchInput(
        run_id=payroll_run.id, payment_date=DAY, bank_account_id=treasury.bank.id))
    services.payroll_payments.pay(admin, batch.id)
    table = services.payroll_reports.payments(admin, payroll_run.id)
    assert table.row_count == 2
    assert all(row[5] == P.ITEM_TITLES_FA[P.ITEM_PAID] for row in table.rows)
