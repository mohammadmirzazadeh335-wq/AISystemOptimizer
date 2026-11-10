"""Dashboard aggregates for the treasury landing page.

The page needs figures, a receipts-vs-payments series, a cash-flow trend, today's
documents and the cheque watch list. Everything is read from posted documents;
there is no cached or mock number anywhere.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from pars_erp.core.errors import ValidationError
from pars_erp.db.models import Cheque, DetailAccount, Payment, Receipt
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_any, require_permission
from pars_erp.services.commerce_common import ZERO
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.services.treasury_common import fund_balance
from pars_erp.treasury import constants as TC


@dataclass(frozen=True)
class SeriesPoint:
    day: _dt.date
    inflow: Decimal
    outflow: Decimal

    @property
    def net(self) -> Decimal:
        return self.inflow - self.outflow


@dataclass(frozen=True)
class TodayVoucher:
    number: str
    kind: str
    kind_fa: str
    party_name: str
    amount: Decimal
    status: str
    status_fa: str
    document_id: int


@dataclass(frozen=True)
class WatchCheque:
    cheque_id: int
    number: str
    direction_fa: str
    bank_name: str
    party_name: str
    due_date: _dt.date
    days_left: int
    amount: Decimal
    status: str
    status_fa: str


class TreasuryDashboardService:
    def __init__(self, db: Database, reports=None) -> None:
        self.db = db
        self.reports = reports

    # ------------------------------------------------------------------ figures
    def figures(self, ctx: SecurityContext | None, period: ReportPeriod | None = None):
        require_permission(ctx, "treasury.reports")
        today = _dt.date.today()
        period = period or ReportPeriod(today.replace(day=1), today)
        return self.reports.dashboard(ctx, period=period)

    def balances(self, ctx: SecurityContext | None) -> dict[str, Decimal]:
        require_permission(ctx, "treasury.reports")
        with self.db.session_scope() as session:
            from pars_erp.db.models import BankAccount, CashBox

            cash = sum((fund_balance(session, cash_box_id=box.id) for box in
                        session.execute(select(CashBox)).scalars()), ZERO)
            bank = sum((fund_balance(session, bank_account_id=bank.id) for bank in
                        session.execute(select(BankAccount)).scalars()), ZERO)
        return {"cash": cash, "bank": bank, "total": cash + bank}

    # ------------------------------------------------------------------- charts
    def receipts_vs_payments(self, ctx: SecurityContext | None,
                             period: ReportPeriod) -> tuple[SeriesPoint, ...]:
        require_any(ctx, "treasury.reports", "receipts.view", "payments.view")
        if period.date_to < period.date_from:
            raise ValidationError("بازه تاریخ معتبر نیست.", field="date_to")
        buckets: dict[_dt.date, list[Decimal]] = {}
        with self.db.session_scope() as session:
            for row in session.execute(select(Receipt).where(
                    Receipt.status == TC.STATUS_POSTED,
                    Receipt.receipt_date >= period.date_from,
                    Receipt.receipt_date <= period.date_to)).scalars():
                buckets.setdefault(row.receipt_date, [ZERO, ZERO])[0] += Decimal(row.base_amount)
            for row in session.execute(select(Payment).where(
                    Payment.status == TC.STATUS_POSTED,
                    Payment.payment_date >= period.date_from,
                    Payment.payment_date <= period.date_to)).scalars():
                buckets.setdefault(row.payment_date, [ZERO, ZERO])[1] += Decimal(row.base_amount)
        return tuple(SeriesPoint(day, values[0], values[1])
                     for day, values in sorted(buckets.items()))

    def cash_flow_trend(self, ctx: SecurityContext | None, period: ReportPeriod,
                        *, weeks: int = 8) -> tuple[SeriesPoint, ...]:
        """Weekly inflow/outflow over the trailing window that ends at date_to."""
        require_any(ctx, "treasury.reports", "receipts.view", "payments.view")
        end = period.date_to
        start = max(period.date_from, end - _dt.timedelta(days=7 * max(weeks, 1) - 1))
        daily = self.receipts_vs_payments(ctx, ReportPeriod(start, end))
        buckets: dict[_dt.date, list[Decimal]] = {}
        for point in daily:
            week_start = point.day - _dt.timedelta(days=point.day.weekday())
            bucket = buckets.setdefault(week_start, [ZERO, ZERO])
            bucket[0] += point.inflow
            bucket[1] += point.outflow
        return tuple(SeriesPoint(day, values[0], values[1])
                     for day, values in sorted(buckets.items()))

    # -------------------------------------------------------------------- today
    def today_documents(self, ctx: SecurityContext | None,
                        day: _dt.date | None = None) -> tuple[TodayVoucher, ...]:
        require_any(ctx, "treasury.reports", "receipts.view", "payments.view")
        day = day or _dt.date.today()
        rows: list[TodayVoucher] = []
        with self.db.session_scope() as session:
            for receipt in session.execute(select(Receipt).where(
                    Receipt.receipt_date == day).order_by(Receipt.number)).scalars():
                party = (session.get(DetailAccount, receipt.payer_detail_id)
                         if receipt.payer_detail_id else None)
                rows.append(TodayVoucher(
                    number=receipt.number, kind="receipt", kind_fa="دریافت",
                    party_name=party.name if party else (receipt.payer_name or "—"),
                    amount=Decimal(receipt.base_amount), status=receipt.status,
                    status_fa=TC.STATUS_TITLES_FA.get(receipt.status, receipt.status),
                    document_id=receipt.id))
            for payment in session.execute(select(Payment).where(
                    Payment.payment_date == day).order_by(Payment.number)).scalars():
                party = (session.get(DetailAccount, payment.payee_detail_id)
                         if payment.payee_detail_id else None)
                rows.append(TodayVoucher(
                    number=payment.number, kind="payment", kind_fa="پرداخت",
                    party_name=party.name if party else (payment.payee_name or "—"),
                    amount=Decimal(payment.base_amount), status=payment.status,
                    status_fa=TC.STATUS_TITLES_FA.get(payment.status, payment.status),
                    document_id=payment.id))
        rows.sort(key=lambda item: (item.kind, item.number))
        return tuple(rows)

    # -------------------------------------------------------------------- watch
    def watch_cheques(self, ctx: SecurityContext | None, *,
                      days: int = 14) -> tuple[WatchCheque, ...]:
        require_any(ctx, "treasury.reports", "cheques.view")
        today = _dt.date.today()
        horizon = today + _dt.timedelta(days=max(days, 0))
        result: list[WatchCheque] = []
        with self.db.session_scope() as session:
            for cheque in session.execute(select(Cheque).where(
                    Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES + TC.ISSUED_OPEN_STATUSES),
                    Cheque.due_date <= horizon).order_by(Cheque.due_date)).scalars():
                party = (session.get(DetailAccount, cheque.party_detail_id)
                         if cheque.party_detail_id else None)
                result.append(WatchCheque(
                    cheque_id=cheque.id, number=cheque.number,
                    direction_fa=TC.CHEQUE_DIRECTION_TITLES_FA.get(cheque.direction,
                                                                  cheque.direction),
                    bank_name=cheque.bank_name,
                    party_name=party.name if party else "—",
                    due_date=cheque.due_date, days_left=(cheque.due_date - today).days,
                    amount=Decimal(cheque.base_amount), status=cheque.status,
                    status_fa=TC.CHEQUE_STATUS_TITLES_FA.get(cheque.status, cheque.status)))
        return tuple(result)
