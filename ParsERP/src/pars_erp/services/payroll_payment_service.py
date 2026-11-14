"""Paying a payroll run: batches, bank file and the treasury link (phase 5, part 4).

Why a batch at all? Because a salary payment is *one* bank movement for many
employees. The batch records the list, then:

* **pay** creates a single treasury payment document (type «پرداخت حقوق») whose
  counter account is the salary-payable account, posts its journal and marks the
  run paid - all in one transaction;
* every payslip keeps ``payment_item_id`` / ``payment_id``; the unique constraint
  on ``pay_batch_items.payslip_id`` plus the payslip status is what makes a retry
  safe - a paid payslip can never enter a second batch;
* **fail_item** marks an employee's transfer as failed (with a reason) so the
  failed list is explicit, and a retry batch can be created for those people only.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    Employee,
    PayBatch,
    PayBatchItem,
    PayRun,
    Payslip,
)
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.payroll import constants as P
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import next_document_number
from pars_erp.services.hr_common import ZERO, to_money
from pars_erp.treasury import constants as TC

DEFAULT_SALARY_PAYABLE_CODE = "201003"


@dataclass(frozen=True)
class BatchInput:
    run_id: int
    payment_date: _dt.date | None = None
    cash_box_id: int | None = None
    bank_account_id: int | None = None
    method: str = TC.METHOD_CASH
    note: str = ""


@dataclass(frozen=True)
class BatchItemRow:
    id: int
    payslip_id: int
    employee_id: int
    employee_code: str
    employee_name: str
    iban: str
    bank_account_no: str
    amount: Decimal
    status: str
    status_fa: str
    tracking_no: str
    failure_reason: str
    payment_id: int | None


@dataclass(frozen=True)
class BatchRow:
    id: int
    number: str
    run_id: int
    run_number: str
    payment_date: _dt.date
    fund_kind: str
    status: str
    status_fa: str
    items_count: int
    total_amount: Decimal
    paid_amount: Decimal
    bank_file_name: str
    payment_id: int | None
    journal_id: int | None
    note: str
    items: tuple[BatchItemRow, ...] = ()

    @property
    def display(self) -> str:
        return f"{self.number} — {self.run_number}"


class PayrollPaymentService:
    def __init__(self, db: Database, audit: AuditService, *, vouchers=None,
                 settings=None) -> None:
        self.db = db
        self.audit = audit
        self.vouchers = vouchers
        self.settings = settings

    # ------------------------------------------------------------------- create
    def create_batch(self, ctx: SecurityContext | None, data: BatchInput) -> BatchRow:
        require_permission(ctx, "payroll.pay")
        when = data.payment_date or _dt.date.today()
        with self.db.session_scope() as session:
            run = session.get(PayRun, data.run_id)
            if run is None:
                raise NotFoundError("دورهٔ حقوق یافت نشد.")
            if run.status not in (P.RUN_APPROVED, P.RUN_POSTED, P.RUN_PAID):
                raise ConflictError("برای پرداخت، ابتدا دوره را تأیید کنید.")
            taken = select(PayBatchItem.payslip_id).where(
                PayBatchItem.payslip_id.is_not(None))
            slips = list(session.execute(
                select(Payslip).where(Payslip.run_id == run.id,
                                      Payslip.status == P.SLIP_APPROVED,
                                      Payslip.id.not_in(taken))
                .order_by(Payslip.number)).scalars())
            if not slips:
                raise ConflictError(
                    "فیش تأییدشدهٔ بدون پرداخت در این دوره وجود ندارد؛ هر فیش فقط در "
                    "یک دستهٔ پرداخت قرار می‌گیرد.")
            number = next_document_number(session, PayBatch, prefix="PB", on_date=when)
            batch = PayBatch(
                number=number, run_id=run.id, payment_date=when,
                fund_kind=TC.FUND_CASH if data.cash_box_id else TC.FUND_BANK,
                cash_box_id=data.cash_box_id, bank_account_id=data.bank_account_id,
                status=P.BATCH_DRAFT, items_count=len(slips),
                total_amount=to_money(sum((Decimal(s.net or 0) for s in slips), ZERO)),
                note=(data.note or "").strip() or None,
                created_by_id=getattr(ctx, "user_id", None))
            session.add(batch)
            session.flush()
            for slip in slips:
                employee = session.get(Employee, slip.employee_id)
                session.add(PayBatchItem(
                    batch_id=batch.id, payslip_id=slip.id, employee_id=slip.employee_id,
                    amount=Decimal(slip.net or 0), status=P.ITEM_PENDING,
                    tracking_no=shib_or_account(employee)))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_batch", entity_id=batch.id, action="create",
                summary_fa=f"ایجاد دستهٔ پرداخت حقوق {number} ({len(slips)} نفر)",
                after={"total": str(batch.total_amount)}, session=session)
            return self._batch_row(session, batch, with_items=True)

    # --------------------------------------------------------------------- file
    def bank_file_content(self, ctx: SecurityContext | None, batch_id: int) -> str:
        """Configurable bank file: the column order comes from the settings."""
        require_permission(ctx, "payroll.pay")
        columns = self._file_columns()
        with self.db.session_scope() as session:
            batch = session.get(PayBatch, batch_id)
            if batch is None:
                raise NotFoundError("دستهٔ پرداخت یافت نشد.")
            run = session.get(PayRun, batch.run_id)
            period = f"{run.period_year}/{run.period_month:02d}" if run else ""
            rows = []
            for item in batch.items:
                employee = session.get(Employee, item.employee_id)
                values = {
                    "employee_code": employee.code if employee else "",
                    "full_name": (f"{employee.first_name} {employee.last_name}".strip()
                                  if employee else ""),
                    "iban": (employee.iban or "") if employee else "",
                    "bank_account_no": (employee.bank_account_no or "") if employee else "",
                    "amount": str(Decimal(item.amount or 0)),
                    "tracking_no": item.tracking_no or "",
                    "period": period,
                }
                rows.append(tuple(values.get(column, "") for column in columns))
        delimiter = "\t" if self._file_format() == "txt" else ","
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow(columns)
        writer.writerows(rows)
        return buffer.getvalue()

    def export_bank_file(self, ctx: SecurityContext | None, batch_id: int,
                         path: str | Path | None = None) -> Path:
        content = self.bank_file_content(ctx, batch_id)
        target = Path(path) if path else Path(f"pay_batch_{batch_id}.csv")
        target.write_text(content, encoding="utf-8-sig")
        with self.db.session_scope() as session:
            batch = session.get(PayBatch, batch_id)
            if batch is not None:
                batch.bank_file_name = target.name
            session.flush()
        return target

    # ---------------------------------------------------------------------- pay
    def pay(self, ctx: SecurityContext | None, batch_id: int, *,
            tracking_no: str = "") -> BatchRow:
        """Create + post the treasury payment and mark the run/paidslips paid."""
        require_permission(ctx, "payroll.pay")
        if self.vouchers is None:  # pragma: no cover - composition guard
            raise ValidationError("سرویس خزانه در دسترس نیست.")
        from pars_erp.services.voucher_service import PaymentInput

        with self.db.session_scope() as session:
            batch = session.get(PayBatch, batch_id)
            if batch is None:
                raise NotFoundError("دستهٔ پرداخت یافت نشد.")
            if batch.status == P.BATCH_PAID:
                raise ConflictError("این دسته قبلاً پرداخت شده است.")
            pending = [item for item in batch.items if item.status == P.ITEM_PENDING]
            if not pending:
                raise ConflictError("این دسته ردیف قابل پرداختی ندارد.")
            account = session.execute(
                select(Account).where(Account.code == DEFAULT_SALARY_PAYABLE_CODE)
            ).scalars().first()
            if account is None:
                raise ValidationError("حساب «حقوق و دستمزد پرداختنی» در کدینگ حساب‌ها "
                                      "وجود ندارد.")
            amount = to_money(sum((Decimal(item.amount or 0) for item in pending), ZERO))
            run = session.get(PayRun, batch.run_id)
            payment = self.vouchers.create_payment_in_session(
                session, ctx,
                PaymentInput(
                    payment_date=batch.payment_date, amount=amount,
                    payment_type=TC.PAYMENT_SALARY,
                    method=TC.METHOD_CASH if batch.cash_box_id else TC.METHOD_TRANSFER,
                    cash_box_id=batch.cash_box_id, bank_account_id=batch.bank_account_id,
                    counter_account_id=account.id, tracking_no=tracking_no,
                    description=f"پرداخت حقوق {run.period_year}/{run.period_month:02d} "
                                f"— دستهٔ {batch.number}",
                    idempotency_key=f"paybatch:{batch.id}:payment"))
            self.vouchers.post_payment_in_session(session, payment, ctx)
            for item in pending:
                item.status = P.ITEM_PAID
                item.payment_id = payment.id
                item.paid_at = utcnow()
                slip = session.get(Payslip, item.payslip_id)
                if slip is not None:
                    slip.status = P.SLIP_PAID
                    slip.payment_id = payment.id
                    slip.payment_item_id = item.id
                    slip.paid_at = utcnow()
            batch.status = P.BATCH_PAID
            batch.paid_amount = amount
            batch.journal_id = payment.journal_id
            batch.paid_at = utcnow()
            session.flush()   # the slip statuses above must be visible to the count
            if run is not None:
                paid = session.execute(
                    select(func.count(Payslip.id)).where(
                        Payslip.run_id == run.id, Payslip.status != P.SLIP_PAID)
                ).scalar() or 0
                run.status = P.RUN_PAID if paid == 0 else P.RUN_POSTED
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_batch", entity_id=batch.id, action="pay",
                summary_fa=f"پرداخت حقوق دستهٔ {batch.number} ({len(pending)} نفر)",
                after={"amount": str(amount), "payment_id": payment.id,
                       "journal_id": payment.journal_id}, session=session)
            return self._batch_row(session, batch, with_items=True)

    def fail_item(self, ctx: SecurityContext | None, item_id: int, *, reason: str) -> BatchItemRow:
        """Mark one employee's transfer as failed (kept for the failed list)."""
        require_permission(ctx, "payroll.pay")
        if not (reason or "").strip():
            raise ValidationError("دلیل ناموفق بودن پرداخت را وارد کنید.", field="reason")
        with self.db.session_scope() as session:
            item = session.get(PayBatchItem, item_id)
            if item is None:
                raise NotFoundError("ردیف پرداخت یافت نشد.")
            if item.status == P.ITEM_PAID:
                raise ConflictError("این ردیف قبلاً پرداخت شده است.")
            item.status = P.ITEM_FAILED
            item.failure_reason = reason
            batch = session.get(PayBatch, item.batch_id)
            if batch is not None:
                remaining = [row for row in batch.items if row.status == P.ITEM_PENDING]
                batch.status = P.BATCH_PARTIAL if remaining else P.BATCH_CANCELLED
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_batch_item", entity_id=item.id, action="fail",
                summary_fa="ثبت ناموفق بودن پرداخت حقوق",
                after={"reason": reason}, session=session)
            return self._item_row(session, item)

    def retry_batch(self, ctx: SecurityContext | None, batch_id: int, *,
                    payment_date: _dt.date | None = None,
                    cash_box_id: int | None = None,
                    bank_account_id: int | None = None,
                    method: str = TC.METHOD_CASH) -> BatchRow:
        """A new batch containing only the failed items of an earlier one."""
        require_permission(ctx, "payroll.pay")
        with self.db.session_scope() as session:
            source = session.get(PayBatch, batch_id)
            if source is None:
                raise NotFoundError("دستهٔ پرداخت یافت نشد.")
            failed = [item for item in source.items if item.status == P.ITEM_FAILED]
            if not failed:
                raise ConflictError("ردیف ناموفقی برای تلاش مجدد وجود ندارد.")
            when = payment_date or _dt.date.today()
            number = next_document_number(session, PayBatch, prefix="PB", on_date=when)
            batch = PayBatch(
                number=number, run_id=source.run_id, payment_date=when,
                fund_kind=source.fund_kind,
                cash_box_id=cash_box_id or source.cash_box_id,
                bank_account_id=bank_account_id or source.bank_account_id,
                status=P.BATCH_DRAFT, items_count=len(failed),
                total_amount=to_money(sum((Decimal(i.amount or 0) for i in failed), ZERO)),
                note=f"تلاش مجدد دستهٔ {source.number}",
                created_by_id=getattr(ctx, "user_id", None))
            session.add(batch)
            session.flush()
            # The failed rows are *moved* into the new batch (a payslip may appear in
            # exactly one batch - the unique index on payslip_id enforces that), so a
            # retry can never pay the same slip twice.
            for item in failed:
                item.batch_id = batch.id
                item.status = P.ITEM_PENDING
                item.failure_reason = None
                item.payment_id = None
                item.paid_at = None
            source.items_count = max(0, int(source.items_count or 0) - len(failed))
            source.total_amount = to_money(sum(
                (Decimal(i.amount or 0) for i in source.items), ZERO))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="pay_batch", entity_id=batch.id, action="retry",
                summary_fa=f"تلاش مجدد پرداخت حقوق {number}",
                after={"source": source.number, "items": len(failed)}, session=session)
            return self._batch_row(session, batch, with_items=True)

    # -------------------------------------------------------------------- reads
    def list_batches(self, ctx: SecurityContext | None, *,
                     run_id: int | None = None) -> list[BatchRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            query = select(PayBatch).order_by(PayBatch.payment_date.desc(),
                                              PayBatch.id.desc())
            if run_id:
                query = query.where(PayBatch.run_id == run_id)
            return [self._batch_row(session, row, with_items=False)
                    for row in session.execute(query).scalars()]

    def get_batch(self, ctx: SecurityContext | None, batch_id: int) -> BatchRow:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            batch = session.get(PayBatch, batch_id)
            if batch is None:
                raise NotFoundError("دستهٔ پرداخت یافت نشد.")
            return self._batch_row(session, batch, with_items=True)

    def failed_items(self, ctx: SecurityContext | None) -> list[BatchItemRow]:
        require_permission(ctx, "payroll.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(PayBatchItem).where(PayBatchItem.status == P.ITEM_FAILED)
                .order_by(PayBatchItem.id.desc())).scalars()
            return [self._item_row(session, row) for row in rows]

    # ------------------------------------------------------------------ helpers
    def _file_format(self) -> str:
        if self.settings is None:
            return "csv"
        try:
            return self.settings.snapshot().str("payroll_payment_file_format") or "csv"
        except Exception:  # pragma: no cover
            return "csv"

    def _file_columns(self) -> list[str]:
        default = ["employee_code", "full_name", "iban", "amount", "tracking_no"]
        if self.settings is None:
            return default
        try:
            raw = self.settings.snapshot().str("payroll_payment_file_columns")
        except Exception:  # pragma: no cover
            return default
        allowed = {"employee_code", "full_name", "iban", "bank_account_no", "amount",
                   "tracking_no", "period"}
        columns = [part.strip() for part in raw.split(",") if part.strip()]
        columns = [column for column in columns if column in allowed]
        return columns or default

    def _batch_row(self, session: Session, batch: PayBatch,
                   *, with_items: bool) -> BatchRow:
        run = session.get(PayRun, batch.run_id)
        items = tuple(self._item_row(session, item) for item in batch.items) \
            if with_items else ()
        return BatchRow(
            id=batch.id, number=batch.number, run_id=batch.run_id,
            run_number=run.number if run else "", payment_date=batch.payment_date,
            fund_kind=batch.fund_kind, status=batch.status,
            status_fa=P.BATCH_TITLES_FA.get(batch.status, batch.status),
            items_count=int(batch.items_count or 0),
            total_amount=Decimal(batch.total_amount or 0),
            paid_amount=Decimal(batch.paid_amount or 0),
            bank_file_name=batch.bank_file_name or "", payment_id=self._payment_id(session, batch),
            journal_id=batch.journal_id, note=batch.note or "",
            items=items)

    @staticmethod
    def _payment_id(session: Session, batch: PayBatch) -> int | None:
        paid = next((item.payment_id for item in batch.items
                     if item.payment_id is not None), None)
        return paid

    def _item_row(self, session: Session, item: PayBatchItem) -> BatchItemRow:
        employee = session.get(Employee, item.employee_id)
        return BatchItemRow(
            id=item.id, payslip_id=item.payslip_id, employee_id=item.employee_id,
            employee_code=employee.code if employee else "",
            employee_name=(f"{employee.first_name} {employee.last_name}".strip()
                           if employee else ""),
            iban=(employee.iban or "") if employee else "",
            bank_account_no=(employee.bank_account_no or "") if employee else "",
            amount=Decimal(item.amount or 0), status=item.status,
            status_fa=P.ITEM_TITLES_FA.get(item.status, item.status),
            tracking_no=item.tracking_no or "",
            failure_reason=item.failure_reason or "", payment_id=item.payment_id)


def shib_or_account(employee: Employee | None) -> str:
    """Bank reference stored on the batch item (iban, else account number)."""
    if employee is None:
        return ""
    return (employee.iban or employee.bank_account_no or "").strip()
