"""Treasury reports, dashboard figures and the due-date calendar.

Every number is computed from posted documents; the report tables use the same
:class:`pars_erp.services.commerce_reports_service.ReportTable` shape as the
phase-3 reports so printing, PDF and Excel go through one renderer.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ValidationError
from pars_erp.db.models import (
    BankAccount,
    CashBox,
    Cheque,
    DetailAccount,
    Invoice,
    Payment,
    PlannedItem,
    Receipt,
    SettlementAllocation,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_any, require_permission
from pars_erp.services.commerce_common import ZERO
from pars_erp.services.commerce_reports_service import ReportPeriod, ReportTable
from pars_erp.services.treasury_common import fund_balance
from pars_erp.treasury import constants as TC

MONEY = Decimal("0.01")


@dataclass(frozen=True)
class DashboardFigures:
    cash_total: Decimal
    bank_total: Decimal
    receipts_today: Decimal
    payments_today: Decimal
    receipts_period: Decimal
    payments_period: Decimal
    receipts_open_cheques: Decimal
    issued_open_cheques: Decimal
    cheques_due_soon: int
    overdue_receivables: Decimal
    overdue_payables: Decimal
    net_flow: Decimal


@dataclass(frozen=True)
class CalendarItem:
    id: str
    kind: str
    kind_fa: str
    title: str
    due_date: _dt.date
    amount: Decimal
    party_name: str
    is_done: bool
    days_left: int
    source_kind: str
    source_id: int | None

    @property
    def is_overdue(self) -> bool:
        return self.days_left < 0 and not self.is_done


CALENDAR_KIND_TITLES_FA = {
    TC.PLAN_CHEQUE_RECEIVED: "چک دریافتی",
    TC.PLAN_CHEQUE_ISSUED: "چک پرداختی",
    TC.PLAN_INVOICE_DUE: "فاکتور سررسیدشده",
    TC.PLAN_PAYMENT: "پرداخت برنامه‌ریزی‌شده",
}


class TreasuryReportService:
    def __init__(self, db: Database, settings=None) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------ ledger
    def _fund_statement(self, session, *, cash_box_id: int | None = None,
                        bank_account_id: int | None = None,
                        period: ReportPeriod) -> list[dict]:
        """Opening row plus the posted ledger lines of one fund in the period."""
        from pars_erp.services.treasury_common import fund_ledger_lines

        box = session.get(CashBox, cash_box_id) if cash_box_id else None
        bank = session.get(BankAccount, bank_account_id) if bank_account_id else None
        fund = box or bank
        if fund is None:
            return []
        rows: list[dict] = []
        running = Decimal(fund.opening_balance or 0)
        rows.append({"date": fund.opening_date or period.date_from, "number": "—",
                     "kind_fa": "موجودی اولیه", "description": "مانده ابتدای دوره",
                     "in": ZERO, "out": ZERO, "balance": running})
        for line in fund_ledger_lines(session, cash_box_id=cash_box_id,
                                      bank_account_id=bank_account_id,
                                      date_from=period.date_from,
                                      date_to=period.date_to):
            running = running + line["in"] - line["out"]
            rows.append({"date": line["date"], "number": line["number"],
                         "kind_fa": "سند", "description": line["description"],
                         "in": line["in"], "out": line["out"], "balance": running})
        return rows

    def bank_ledger(self, ctx: SecurityContext | None, period: ReportPeriod,
                    bank_account_id: int | None = None) -> ReportTable:
        require_any(ctx, "treasury.reports", "bank_accounts.view")
        rows: list[tuple] = []
        with self.db.session_scope() as session:
            banks = ([session.get(BankAccount, bank_account_id)] if bank_account_id
                     else list(session.execute(select(BankAccount)
                                               .order_by(BankAccount.bank_name)).scalars()))
            for bank in banks:
                if bank is None:
                    continue
                for line in self._fund_statement(session, bank_account_id=bank.id,
                                                 period=period):
                    rows.append((line["date"], bank.bank_name, line["number"],
                                 line["kind_fa"], line["description"], line["in"],
                                 line["out"], line["balance"]))
        return ReportTable(
            key="bank_ledger", title_fa="گردش حساب‌های بانکی",
            columns=("تاریخ", "بانک", "شماره سند", "نوع", "شرح", "واریز",
                     "برداشت", "مانده"),
            rows=tuple(rows),
            meta_fa=f"از {period.date_from} تا {period.date_to} — {len(rows)} ردیف")

    def cash_ledger(self, ctx: SecurityContext | None, period: ReportPeriod,
                    cash_box_id: int | None = None) -> ReportTable:
        require_any(ctx, "treasury.reports", "cash_boxes.view")
        rows: list[tuple] = []
        with self.db.session_scope() as session:
            boxes = ([session.get(CashBox, cash_box_id)] if cash_box_id
                     else list(session.execute(select(CashBox)
                                               .order_by(CashBox.code)).scalars()))
            for box in boxes:
                if box is None:
                    continue
                for line in self._fund_statement(session, cash_box_id=box.id, period=period):
                    rows.append((line["date"], box.title_fa, line["number"],
                                 line["kind_fa"], line["description"], line["in"],
                                 line["out"], line["balance"]))
        return ReportTable(
            key="cash_ledger", title_fa="گردش صندوق‌ها",
            columns=("تاریخ", "صندوق", "شماره سند", "نوع", "شرح", "دریافت",
                     "پرداخت", "مانده"),
            rows=tuple(rows),
            meta_fa=f"از {period.date_from} تا {period.date_to} — {len(rows)} ردیف")

    def bank_balances(self, ctx: SecurityContext | None) -> ReportTable:
        require_any(ctx, "treasury.reports", "bank_accounts.view")
        rows: list[tuple] = []
        with self.db.session_scope() as session:
            for bank in session.execute(select(BankAccount)
                                        .order_by(BankAccount.bank_name)).scalars():
                rows.append((bank.bank_name, bank.account_number, bank.currency_code,
                             Decimal(bank.opening_balance),
                             fund_balance(session, bank_account_id=bank.id)))
        return ReportTable("bank_balances", "مانده حساب‌های بانکی",
                           ("بانک", "شماره حساب", "ارز", "موجودی اولیه", "مانده"),
                           tuple(rows), f"{len(rows)} حساب")

    def cash_balances(self, ctx: SecurityContext | None) -> ReportTable:
        require_any(ctx, "treasury.reports", "cash_boxes.view")
        rows: list[tuple] = []
        with self.db.session_scope() as session:
            for box in session.execute(select(CashBox).order_by(CashBox.code)).scalars():
                rows.append((box.title_fa, box.keeper_name or "—",
                             Decimal(box.opening_balance),
                             fund_balance(session, cash_box_id=box.id)))
        return ReportTable("cash_balances", "مانده صندوق‌ها",
                           ("صندوق", "مسئول", "موجودی اولیه", "مانده"), tuple(rows),
                           f"{len(rows)} صندوق")

    # ----------------------------------------------------------------- cheques
    def cheques(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                direction: str, statuses: tuple[str, ...] | None = None) -> ReportTable:
        require_any(ctx, "treasury.reports", "cheques.view")
        if direction not in dict(TC.CHEQUE_DIRECTIONS):
            raise ValidationError("نوع چک معتبر نیست.", field="direction")
        with self.db.session_scope() as session:
            # the period filters on the cheque's own date (issue date); the
            # near-due / overdue view is ``cheques_due`` below
            query = select(Cheque).where(Cheque.direction == direction,
                                         Cheque.issue_date >= period.date_from,
                                         Cheque.issue_date <= period.date_to)
            if statuses:
                query = query.where(Cheque.status.in_(statuses))
            rows = []
            for cheque in session.execute(query.order_by(Cheque.due_date)).scalars():
                party = (session.get(DetailAccount, cheque.party_detail_id)
                         if cheque.party_detail_id else None)
                rows.append((cheque.number, cheque.bank_name, party.name if party else "—",
                             cheque.issue_date, cheque.due_date,
                             Decimal(cheque.base_amount),
                             TC.CHEQUE_STATUS_TITLES_FA.get(cheque.status, cheque.status)))
        title = ("چک‌های دریافتی" if direction == TC.CHEQUE_RECEIVED else "چک‌های پرداختی")
        return ReportTable(f"cheques_{direction}", title,
                           ("شماره چک", "بانک", "شخص", "تاریخ صدور", "سررسید",
                            "مبلغ", "وضعیت"), tuple(rows),
                           f"از {period.date_from} تا {period.date_to} — {len(rows)} چک")

    def cheques_due(self, ctx: SecurityContext | None, *, days: int = 30) -> ReportTable:
        require_any(ctx, "treasury.reports", "cheques.view")
        horizon = _dt.date.today() + _dt.timedelta(days=days)
        with self.db.session_scope() as session:
            rows = []
            for cheque in session.execute(select(Cheque).where(
                    Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES + TC.ISSUED_OPEN_STATUSES),
                    Cheque.due_date <= horizon).order_by(Cheque.due_date)).scalars():
                party = (session.get(DetailAccount, cheque.party_detail_id)
                         if cheque.party_detail_id else None)
                rows.append((cheque.due_date, cheque.number,
                             TC.CHEQUE_DIRECTION_TITLES_FA.get(cheque.direction,
                                                               cheque.direction),
                             cheque.bank_name, party.name if party else "—",
                             Decimal(cheque.base_amount),
                             (cheque.due_date - _dt.date.today()).days))
        return ReportTable("cheques_due", f"چک‌های نزدیک سررسید ({days} روز)",
                           ("سررسید", "شماره چک", "نوع", "بانک", "شخص", "مبلغ",
                            "روز باقی‌مانده"), tuple(rows), f"{len(rows)} چک")

    # ----------------------------------------------------------------- persons
    def person_flows(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                     kind: str) -> ReportTable:
        require_any(ctx, "treasury.reports", "persons.view")
        model = Receipt if kind == "receipt" else Payment
        date_column = model.receipt_date if kind == "receipt" else model.payment_date
        with self.db.session_scope() as session:
            query = select(model).where(model.status == TC.STATUS_POSTED,
                                        date_column >= period.date_from,
                                        date_column <= period.date_to)
            rows = []
            for document in session.execute(query.order_by(date_column)).scalars():
                party_id = (document.payer_detail_id if kind == "receipt"
                            else document.payee_detail_id)
                party = session.get(DetailAccount, party_id) if party_id else None
                doc_date = (document.receipt_date if kind == "receipt"
                            else document.payment_date)
                rows.append((document.number, doc_date,
                             party.name if party else "—",
                             Decimal(document.base_amount), document.fund_kind,
                             document.tracking_no or "—"))
        title = "دریافت از اشخاص" if kind == "receipt" else "پرداخت به اشخاص"
        return ReportTable(f"person_{kind}", title,
                           ("شماره سند", "تاریخ", "شخص", "مبلغ", "نوع صندوق",
                            "پیگیری"), tuple(rows),
                           f"از {period.date_from} تا {period.date_to} — {len(rows)} سند")

    def open_invoices(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                      direction: str) -> ReportTable:
        require_any(ctx, "treasury.reports", "settlements.manage")
        kinds = (CC.INVOICE_SALE,) if direction == "receipt" else (CC.INVOICE_PURCHASE,)
        with self.db.session_scope() as session:
            rows = []
            invoices = session.execute(select(Invoice).where(
                Invoice.kind.in_(kinds), Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= period.date_from,
                Invoice.invoice_date <= period.date_to).order_by(Invoice.invoice_date)
            ).scalars()
            for invoice in invoices:
                settled = sum((Decimal(row.amount) for row in session.execute(
                    select(SettlementAllocation).where(
                        SettlementAllocation.invoice_id == invoice.id)).scalars()), ZERO)
                party = session.get(DetailAccount, invoice.party_detail_id)
                outstanding = Decimal(invoice.net_total) - settled
                if outstanding <= 0:
                    continue
                rows.append((invoice.number, invoice.invoice_date,
                             party.name if party else "—", Decimal(invoice.net_total),
                             settled, outstanding))
        return ReportTable(
            f"open_{direction}", "فاکتورهای تسویه‌نشده",
            ("شماره فاکتور", "تاریخ", "شخص", "مبلغ فاکتور", "تسویه‌شده", "مانده"),
            tuple(rows), f"از {period.date_from} تا {period.date_to} — {len(rows)} فاکتور")

    # --------------------------------------------------------------- cash flow
    def cash_flow(self, ctx: SecurityContext | None, period: ReportPeriod) -> ReportTable:
        require_any(ctx, "treasury.reports", "receipts.view", "payments.view")
        with self.db.session_scope() as session:
            receipts = session.execute(select(Receipt).where(
                Receipt.status == TC.STATUS_POSTED,
                Receipt.receipt_date >= period.date_from,
                Receipt.receipt_date <= period.date_to)).scalars()
            payments = session.execute(select(Payment).where(
                Payment.status == TC.STATUS_POSTED,
                Payment.payment_date >= period.date_from,
                Payment.payment_date <= period.date_to)).scalars()
            daily: dict[_dt.date, list[Decimal]] = {}
            for row in receipts:
                bucket = daily.setdefault(row.receipt_date, [ZERO, ZERO])
                bucket[0] += Decimal(row.base_amount)
            for row in payments:
                bucket = daily.setdefault(row.payment_date, [ZERO, ZERO])
                bucket[1] += Decimal(row.base_amount)
            rows = []
            for day in sorted(daily):
                inflow, outflow = daily[day]
                rows.append((day, inflow, outflow, inflow - outflow))
        return ReportTable("cash_flow", "جریان نقدی",
                           ("تاریخ", "ورودی", "خروجی", "خالص"), tuple(rows),
                           f"از {period.date_from} تا {period.date_to}")

    def forecast(self, ctx: SecurityContext | None, *, days: int = 30) -> ReportTable:
        require_any(ctx, "treasury.reports", "treasury.calendar")
        horizon = _dt.date.today() + _dt.timedelta(days=days)
        with self.db.session_scope() as session:
            rows = []
            for cheque in session.execute(select(Cheque).where(
                    Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES),
                    Cheque.due_date >= _dt.date.today(),
                    Cheque.due_date <= horizon).order_by(Cheque.due_date)).scalars():
                rows.append((cheque.due_date, "چک دریافتی", cheque.number,
                             Decimal(cheque.base_amount)))
            for cheque in session.execute(select(Cheque).where(
                    Cheque.status.in_(TC.ISSUED_OPEN_STATUSES),
                    Cheque.due_date >= _dt.date.today(),
                    Cheque.due_date <= horizon).order_by(Cheque.due_date)).scalars():
                rows.append((cheque.due_date, "چک پرداختی", cheque.number,
                             -Decimal(cheque.base_amount)))
            for item in session.execute(select(PlannedItem).where(
                    PlannedItem.is_done.is_(False),
                    PlannedItem.due_date <= horizon)).scalars():
                rows.append((item.due_date, CALENDAR_KIND_TITLES_FA.get(
                    item.kind, item.kind), item.title, Decimal(item.amount)))
        rows.sort(key=lambda row: row[0])
        return ReportTable("forecast", f"پیش‌بینی جریان نقدی ({days} روز)",
                           ("تاریخ", "نوع", "شرح", "مبلغ"), tuple(rows),
                           f"{len(rows)} مورد سررسید")

    # --------------------------------------------------------------- dashboard
    def dashboard(self, ctx: SecurityContext | None, *,
                  period: ReportPeriod | None = None) -> DashboardFigures:
        require_permission(ctx, "treasury.reports")
        today = _dt.date.today()
        period = period or ReportPeriod(today.replace(day=1), today)
        horizon = today + _dt.timedelta(days=self._alert_days())
        with self.db.session_scope() as session:
            cash_total = sum((fund_balance(session, cash_box_id=box.id) for box in
                              session.execute(select(CashBox)).scalars()), ZERO)
            bank_total = sum((fund_balance(session, bank_account_id=bank.id) for bank in
                              session.execute(select(BankAccount)).scalars()), ZERO)
            receipts_today = sum((Decimal(row.base_amount) for row in session.execute(
                select(Receipt).where(Receipt.status == TC.STATUS_POSTED,
                                      Receipt.receipt_date == today)).scalars()), ZERO)
            payments_today = sum((Decimal(row.base_amount) for row in session.execute(
                select(Payment).where(Payment.status == TC.STATUS_POSTED,
                                      Payment.payment_date == today)).scalars()), ZERO)
            receipts_period = sum((Decimal(row.base_amount) for row in session.execute(
                select(Receipt).where(Receipt.status == TC.STATUS_POSTED,
                                      Receipt.receipt_date >= period.date_from,
                                      Receipt.receipt_date <= period.date_to)).scalars()),
                ZERO)
            payments_period = sum((Decimal(row.base_amount) for row in session.execute(
                select(Payment).where(Payment.status == TC.STATUS_POSTED,
                                      Payment.payment_date >= period.date_from,
                                      Payment.payment_date <= period.date_to)).scalars()),
                ZERO)
            received_open = sum((Decimal(row.base_amount) for row in session.execute(
                select(Cheque).where(Cheque.direction == TC.CHEQUE_RECEIVED,
                                     Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES))
            ).scalars()), ZERO)
            issued_open = sum((Decimal(row.base_amount) for row in session.execute(
                select(Cheque).where(Cheque.direction == TC.CHEQUE_ISSUED,
                                     Cheque.status.in_(TC.ISSUED_OPEN_STATUSES))
            ).scalars()), ZERO)
            due_soon = len(list(session.execute(select(Cheque).where(
                Cheque.due_date <= horizon,
                Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES + TC.ISSUED_OPEN_STATUSES))
            ).scalars()))
            overdue_receivables = self._overdue_invoices(session, CC.INVOICE_SALE)
            overdue_payables = self._overdue_invoices(session, CC.INVOICE_PURCHASE)
        return DashboardFigures(
            cash_total=cash_total, bank_total=bank_total,
            receipts_today=receipts_today, payments_today=payments_today,
            receipts_period=receipts_period, payments_period=payments_period,
            receipts_open_cheques=received_open, issued_open_cheques=issued_open,
            cheques_due_soon=due_soon, overdue_receivables=overdue_receivables,
            overdue_payables=overdue_payables,
            net_flow=(receipts_period - payments_period))

    def _overdue_invoices(self, session, kind: str) -> Decimal:
        """Open amount of posted invoices older than 30 days without settlement."""
        cutoff = _dt.date.today() - _dt.timedelta(days=30)
        total = ZERO
        for invoice in session.execute(select(Invoice).where(
                Invoice.kind == kind, Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date <= cutoff)).scalars():
            settled = sum((Decimal(row.amount) for row in session.execute(
                select(SettlementAllocation).where(
                    SettlementAllocation.invoice_id == invoice.id)).scalars()), ZERO)
            outstanding = Decimal(invoice.net_total) - settled
            if outstanding > 0:
                total += outstanding
        return total

    # ---------------------------------------------------------------- calendar
    def calendar(self, ctx: SecurityContext | None, *, date_from: _dt.date,
                 date_to: _dt.date, party_detail_id: int | None = None) -> list[CalendarItem]:
        require_permission(ctx, "treasury.calendar")
        today = _dt.date.today()
        items: list[CalendarItem] = []
        with self.db.session_scope() as session:
            query = select(Cheque).where(
                Cheque.status.in_(TC.RECEIVED_OPEN_STATUSES + TC.ISSUED_OPEN_STATUSES),
                Cheque.due_date >= date_from, Cheque.due_date <= date_to)
            if party_detail_id:
                query = query.where(Cheque.party_detail_id == party_detail_id)
            for cheque in session.execute(query.order_by(Cheque.due_date)).scalars():
                party = (session.get(DetailAccount, cheque.party_detail_id)
                         if cheque.party_detail_id else None)
                kind = (TC.PLAN_CHEQUE_RECEIVED if cheque.direction == TC.CHEQUE_RECEIVED
                        else TC.PLAN_CHEQUE_ISSUED)
                items.append(CalendarItem(
                    id=f"cheque-{cheque.id}", kind=kind,
                    kind_fa=CALENDAR_KIND_TITLES_FA[kind],
                    title=f"چک {cheque.number} — {cheque.bank_name}",
                    due_date=cheque.due_date, amount=Decimal(cheque.base_amount),
                    party_name=party.name if party else "",
                    is_done=False, days_left=(cheque.due_date - today).days,
                    source_kind="cheque", source_id=cheque.id))
            planned = session.execute(select(PlannedItem).where(
                PlannedItem.due_date >= date_from,
                PlannedItem.due_date <= date_to)).scalars()
            for item in planned:
                if party_detail_id and item.party_detail_id != party_detail_id:
                    continue
                party = (session.get(DetailAccount, item.party_detail_id)
                         if item.party_detail_id else None)
                items.append(CalendarItem(
                    id=f"plan-{item.id}", kind=item.kind,
                    kind_fa=CALENDAR_KIND_TITLES_FA.get(item.kind, item.kind),
                    title=item.title, due_date=item.due_date,
                    amount=Decimal(item.amount), party_name=party.name if party else "",
                    is_done=item.is_done, days_left=(item.due_date - today).days,
                    source_kind="planned", source_id=item.id))
        items.sort(key=lambda entry: (entry.due_date, entry.title))
        return items

    def add_planned_item(self, ctx: SecurityContext | None, *, kind: str, title: str,
                         due_date: _dt.date, amount, party_detail_id: int | None = None,
                         note: str = "") -> int:
        require_permission(ctx, "treasury.calendar")
        from pars_erp.services.commerce_common import clean_text, to_money

        if kind not in CALENDAR_KIND_TITLES_FA:
            raise ValidationError("نوع مورد تقویم معتبر نیست.", field="kind")
        with self.db.session_scope() as session:
            item = PlannedItem(
                kind=kind,
                title=clean_text(title, field="title", label="عنوان", required=True,
                                 max_length=200),
                due_date=due_date, amount=to_money(amount, field="amount"),
                party_detail_id=party_detail_id,
                note=clean_text(note, field="note", label="توضیح", max_length=300),
                created_by_id=getattr(ctx, "user_id", None))
            session.add(item)
            session.flush()
            return item.id

    def mark_planned_done(self, ctx: SecurityContext | None, item_id: int,
                          done: bool = True) -> None:
        require_permission(ctx, "treasury.calendar")
        with self.db.session_scope() as session:
            item = session.get(PlannedItem, item_id)
            if item is None:
                raise ValidationError("مورد تقویم یافت نشد.", field="item_id")
            item.is_done = bool(done)
            item.done_at = (_dt.datetime.now(_dt.timezone.utc) if done else None)

    def _alert_days(self) -> int:
        from pars_erp.services.treasury_common import alert_days

        if self.settings is None:
            return 7
        return alert_days(self.settings)
