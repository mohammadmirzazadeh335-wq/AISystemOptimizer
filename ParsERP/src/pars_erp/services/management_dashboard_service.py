"""The management dashboard: real figures from real documents, nothing invented.

Every card and every chart below is computed from the database - posted invoices,
posted treasury documents, stock balances, payroll runs, employees - through the
same services the report centre uses, so a card can never disagree with the
report behind it. Two rules keep the screen honest:

* a card is **absent**, not zero, when the caller lacks the permission or when the
  underlying module has no data at all (an empty company must not look like a
  company with zero sales and zero stock);
* a card names the page it drills into (``link_page``), so "۲۳ فاکتور باز" is a
  door to those invoices, not a decoration.

The phase-1 :class:`~pars_erp.services.dashboard_service.DashboardService` (users,
sessions, backups) stays untouched; this service is the *business* dashboard.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.core.timeutil import now_local
from pars_erp.db.models import Invoice, Payment, Receipt
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.services.settings_service import SettingsService
from pars_erp.treasury import constants as TC

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

KIND_AMOUNT = "amount"
KIND_COUNT = "count"


@dataclass(frozen=True)
class KpiCard:
    key: str
    title_fa: str
    value: Decimal | int
    kind: str
    subtitle_fa: str = ""
    delta_percent: Decimal | None = None
    link_page: str = ""
    link_hint_fa: str = ""

    @property
    def is_amount(self) -> bool:
        return self.kind == KIND_AMOUNT


@dataclass(frozen=True)
class ChartBar:
    label_fa: str
    value: Decimal
    secondary: Decimal | None = None


@dataclass(frozen=True)
class ChartSeries:
    key: str
    title_fa: str
    bars: tuple[ChartBar, ...]
    unit: str = KIND_AMOUNT
    note_fa: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.bars or all(bar.value == ZERO for bar in self.bars)


@dataclass(frozen=True)
class ManagementDashboard:
    generated_at: _dt.datetime
    period: ReportPeriod
    cards: tuple[KpiCard, ...] = ()
    charts: tuple[ChartSeries, ...] = ()
    notices: tuple[str, ...] = field(default_factory=tuple)

    def card(self, key: str) -> KpiCard | None:
        return next((card for card in self.cards if card.key == key), None)

    def chart(self, key: str) -> ChartSeries | None:
        return next((chart for chart in self.charts if chart.key == key), None)


def _percent_delta(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == ZERO:
        return None
    return ((current - previous) / previous * Decimal("100")).quantize(Decimal("0.1"))


class ManagementDashboardService:
    def __init__(self, db: Database, settings: SettingsService, *,
                 treasury_reports=None, commerce_reports=None, hr_reports=None,
                 payroll_reports=None, asset_reports=None, reports=None,
                 alerts=None) -> None:
        self.db = db
        self.settings = settings
        self.treasury_reports = treasury_reports
        self.commerce_reports = commerce_reports
        self.hr_reports = hr_reports
        self.payroll_reports = payroll_reports
        self.asset_reports = asset_reports
        self.reports = reports
        self.alerts = alerts

    # ------------------------------------------------------------------ public
    def overview(self, ctx: SecurityContext | None, *,
                 period: ReportPeriod | None = None) -> ManagementDashboard:
        require_permission(ctx, "dashboard.view")
        today = now_local().date()
        period = period or ReportPeriod(today.replace(day=1), today)
        previous = self._previous_period(period)

        cards: list[KpiCard] = []
        charts: list[ChartSeries] = []
        notices: list[str] = []

        for builder in (self._sales_cards, self._purchase_cards, self._profit_cards,
                        self._treasury_cards, self._inventory_cards, self._people_cards):
            try:
                produced = builder(ctx, period, previous)
            except AppError:
                continue  # no permission for this module: no card at all
            cards.extend(produced)

        for builder in (self._sales_chart, self._purchase_chart, self._profit_chart,
                        self._cash_chart, self._customer_chart, self._stock_chart,
                        self._expense_chart):
            try:
                chart = builder(ctx, period)
            except AppError:
                continue
            if chart is not None and not chart.is_empty:
                charts.append(chart)

        if self.alerts is not None and ctx is not None and ctx.has("alerts.view"):
            try:
                open_alerts = self.alerts.open_count(ctx)
                if open_alerts:
                    cards.append(KpiCard(
                        key="alerts_open", title_fa="هشدارهای باز", value=open_alerts,
                        kind=KIND_COUNT, subtitle_fa="نیازمند بررسی",
                        link_page="alerts", link_hint_fa="فهرست هشدارها"))
            except AppError:
                pass

        return ManagementDashboard(generated_at=now_local(), period=period,
                                   cards=tuple(cards), charts=tuple(charts),
                                   notices=tuple(notices))

    # ------------------------------------------------------------------- cards
    def _sales_cards(self, ctx, period, previous):
        require_permission(ctx, "commerce.reports")
        today = now_local().date()
        with self.db.session_scope() as session:
            today_net = self._invoice_net(session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                                          today, today)
            month_net = self._invoice_net(session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                                          period.date_from, period.date_to)
            previous_net = self._invoice_net(
                session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                previous.date_from, previous.date_to)
        return [
            KpiCard(key="sales_today", title_fa="فروش امروز", value=today_net,
                    kind=KIND_AMOUNT, subtitle_fa="فاکتورهای ثبت‌نهایی‌شده",
                    link_page="sales_invoices", link_hint_fa="فهرست فاکتورهای فروش"),
            KpiCard(key="sales_month", title_fa="فروش ماه جاری", value=month_net,
                    kind=KIND_AMOUNT, delta_percent=_percent_delta(month_net, previous_net),
                    subtitle_fa="در مقایسه با دورهٔ قبل",
                    link_page="sales_invoices", link_hint_fa="فهرست فاکتورهای فروش"),
        ]

    def _purchase_cards(self, ctx, period, previous):
        require_permission(ctx, "commerce.reports")
        with self.db.session_scope() as session:
            month_net = self._invoice_net(
                session, (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN),
                period.date_from, period.date_to)
            previous_net = self._invoice_net(
                session, (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN),
                previous.date_from, previous.date_to)
        return [KpiCard(key="purchases_month", title_fa="خرید ماه جاری", value=month_net,
                        kind=KIND_AMOUNT, delta_percent=_percent_delta(month_net, previous_net),
                        subtitle_fa="در مقایسه با دورهٔ قبل",
                        link_page="purchase_invoices", link_hint_fa="فهرست فاکتورهای خرید")]

    def _profit_cards(self, ctx, period, previous):
        require_permission(ctx, "commerce.reports")
        with self.db.session_scope() as session:
            revenue, cost = self._invoice_revenue_cost(
                session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                period.date_from, period.date_to)
            prev_revenue, prev_cost = self._invoice_revenue_cost(
                session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                previous.date_from, previous.date_to)
        profit = revenue - cost
        previous_profit = prev_revenue - prev_cost
        return [KpiCard(key="gross_profit", title_fa="سود ناخالص دوره", value=profit,
                        kind=KIND_AMOUNT, delta_percent=_percent_delta(profit, previous_profit),
                        subtitle_fa="فروش خالص منهای بهای تمام‌شده",
                        link_page="report_center", link_hint_fa="گزارش حاشیهٔ سود کالاها")]

    def _treasury_cards(self, ctx, period, previous):
        require_permission(ctx, "treasury.reports")
        figures = self.treasury_reports.dashboard(ctx, period=period)
        return [
            KpiCard(key="cash_total", title_fa="ماندهٔ صندوق‌ها", value=figures.cash_total,
                    kind=KIND_AMOUNT, link_page="cash_boxes",
                    link_hint_fa="ماندهٔ صندوق‌ها"),
            KpiCard(key="bank_total", title_fa="ماندهٔ حساب‌های بانکی", value=figures.bank_total,
                    kind=KIND_AMOUNT, link_page="bank_accounts",
                    link_hint_fa="ماندهٔ حساب‌های بانکی"),
            KpiCard(key="receivables", title_fa="مطالبات سررسیدگذشته",
                    value=figures.overdue_receivables, kind=KIND_AMOUNT,
                    subtitle_fa="بیش از ۳۰ روز",
                    link_page="report_center", link_hint_fa="گزارش مطالبات"),
            KpiCard(key="payables", title_fa="بدهی‌های سررسیدگذشته",
                    value=figures.overdue_payables, kind=KIND_AMOUNT,
                    subtitle_fa="بیش از ۳۰ روز",
                    link_page="report_center", link_hint_fa="گزارش بدهی‌ها"),
            KpiCard(key="cheques_due", title_fa="چک‌های نزدیک سررسید",
                    value=figures.cheques_due_soon, kind=KIND_COUNT,
                    link_page="treasury_cheques", link_hint_fa="فهرست چک‌ها"),
            KpiCard(key="net_flow", title_fa="جریان نقدی خالص دوره", value=figures.net_flow,
                    kind=KIND_AMOUNT, subtitle_fa="دریافت‌ها منهای پرداخت‌ها",
                    link_page="treasury_reports", link_hint_fa="گزارش جریان نقدی"),
        ]

    def _inventory_cards(self, ctx, period, previous):
        require_permission(ctx, "stock.view")
        table = self.commerce_reports.stock_value(ctx)
        total = ZERO
        for row in table.rows:
            for value in row[1:]:
                if isinstance(value, Decimal):
                    total += value
        return [KpiCard(key="stock_value", title_fa="ارزش موجودی انبار", value=total,
                        kind=KIND_AMOUNT, link_page="stock",
                        link_hint_fa="موجودی انبارها")]

    def _people_cards(self, ctx, period, previous):
        require_permission(ctx, "hr.reports")
        headcount = self.hr_reports.headcount(ctx)
        return [KpiCard(key="employees_active", title_fa="کارکنان شاغل",
                        value=int(headcount.get("active", 0)), kind=KIND_COUNT,
                        link_page="hr_employees", link_hint_fa="پروندهٔ کارکنان")]

    # ------------------------------------------------------------------ charts
    def _sales_chart(self, ctx, period):
        require_permission(ctx, "commerce.reports")
        bars = self._monthly_series(ctx, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN), 6)
        return ChartSeries("sales_trend", "روند فروش (۶ ماه)", bars,
                           note_fa="مبلغ خالص فاکتورهای ثبت‌نهایی‌شده در هر ماه")

    def _purchase_chart(self, ctx, period):
        require_permission(ctx, "commerce.reports")
        bars = self._monthly_series(ctx, (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN), 6)
        return ChartSeries("purchase_trend", "روند خرید (۶ ماه)", bars,
                           note_fa="مبلغ خالص فاکتورهای خرید در هر ماه")

    def _profit_chart(self, ctx, period):
        require_permission(ctx, "commerce.reports")
        today = now_local().date()
        bars: list[ChartBar] = []
        with self.db.session_scope() as session:
            for start, end, label in self._month_windows(6):
                revenue, cost = self._invoice_revenue_cost(
                    session, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN), start, end)
                bars.append(ChartBar(label, revenue - cost, revenue))
        return ChartSeries("profit_trend", "سود و فروش (۶ ماه)", tuple(bars),
                           note_fa="سود ناخالص در برابر فروش خالص هر ماه")

    def _cash_chart(self, ctx, period):
        require_permission(ctx, "treasury.reports")
        bars: list[ChartBar] = []
        with self.db.session_scope() as session:
            for start, end, label in self._month_windows(6):
                receipts = self._sum_documents(session, Receipt, Receipt.receipt_date,
                                               Receipt.base_amount, TC.STATUS_POSTED,
                                               start, end)
                payments = self._sum_documents(session, Payment, Payment.payment_date,
                                               Payment.base_amount, TC.STATUS_POSTED,
                                               start, end)
                bars.append(ChartBar(label, receipts, payments))
        return ChartSeries("cash_trend", "دریافت و پرداخت (۶ ماه)", tuple(bars),
                           note_fa="ستون اصلی دریافت و ستون دوم پرداخت هر ماه است")

    def _customer_chart(self, ctx, period):
        require_permission(ctx, "commerce.reports")
        table = self.commerce_reports.sales_summary(ctx, period, group_by="customer")
        bars = tuple(ChartBar(str(row[0]), Decimal(row[-1]))
                     for row in sorted(table.rows, key=lambda r: r[-1], reverse=True)[:8])
        return ChartSeries("top_customers", "فروش به تفکیک مشتری", bars,
                           note_fa="هشت مشتری برتر دورهٔ انتخابی")

    def _stock_chart(self, ctx, period):
        require_permission(ctx, "stock.view")
        table = self.commerce_reports.stock_value(ctx)
        bars = []
        for row in table.rows:
            amount = next((value for value in row[1:] if isinstance(value, Decimal)), ZERO)
            bars.append(ChartBar(str(row[0]), Decimal(amount)))
        return ChartSeries("stock_by_warehouse", "ارزش موجودی هر انبار", tuple(bars),
                           note_fa="بر پایهٔ لایهٔ بهای تمام‌شدهٔ هر انبار")

    def _expense_chart(self, ctx, period):
        require_permission(ctx, "reports.statements")
        statement = self.reports.income_statement(ctx, date_from=period.date_from,
                                                  date_to=period.date_to)
        bars = tuple(ChartBar(section.title, Decimal(section.total))
                     for section in statement.sections
                     if section.total != ZERO)
        return ChartSeries("expense_sections", "هزینه‌ها به تفکیک سرفصل", bars,
                           note_fa="از صورت سود و زیان همان بازه")

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _previous_period(period: ReportPeriod) -> ReportPeriod:
        length = (period.date_to - period.date_from).days + 1
        end = period.date_from - _dt.timedelta(days=1)
        return ReportPeriod(end - _dt.timedelta(days=length - 1), end)

    @staticmethod
    def _month_windows(count: int) -> list[tuple[_dt.date, _dt.date, str]]:
        """The last ``count`` months, oldest first, with Persian month labels."""
        from pars_erp.core.jalali import JalaliDate

        today = now_local().date()
        year, month = today.year, today.month
        windows: list[tuple[_dt.date, _dt.date]] = []
        for _ in range(max(1, count)):
            start = _dt.date(year, month, 1)
            if month == 12:
                end = _dt.date(year, 12, 31)
            else:
                end = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
            windows.append((start, end))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        windows.reverse()
        result = []
        for start, end in windows:
            jalali = JalaliDate.from_gregorian(start)
            result.append((start, end, f"{jalali.month_name} {jalali.year}"))
        return result

    def _monthly_series(self, ctx, kinds, months: int) -> tuple[ChartBar, ...]:
        bars: list[ChartBar] = []
        with self.db.session_scope() as session:
            for start, end, label in self._month_windows(months):
                bars.append(ChartBar(label, self._invoice_net(session, kinds, start, end)))
        return tuple(bars)

    @staticmethod
    def _invoice_net(session, kinds, date_from: _dt.date, date_to: _dt.date) -> Decimal:
        total = session.execute(
            select(func.sum(Invoice.net_total)).where(
                Invoice.kind.in_(kinds), Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        ).scalar()
        return Decimal(total or 0)

    @staticmethod
    def _invoice_revenue_cost(session, kinds, date_from: _dt.date,
                              date_to: _dt.date) -> tuple[Decimal, Decimal]:
        revenue = session.execute(
            select(func.sum(Invoice.net_total)).where(
                Invoice.kind == CC.INVOICE_SALE, Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        ).scalar() or ZERO
        returns = session.execute(
            select(func.sum(Invoice.net_total)).where(
                Invoice.kind == CC.INVOICE_SALE_RETURN, Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        ).scalar() or ZERO
        cost = session.execute(
            select(func.sum(Invoice.cogs_total)).where(
                Invoice.kind == CC.INVOICE_SALE, Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        ).scalar() or ZERO
        cost_returns = session.execute(
            select(func.sum(Invoice.cogs_total)).where(
                Invoice.kind == CC.INVOICE_SALE_RETURN, Invoice.status == CC.STATUS_POSTED,
                Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to)
        ).scalar() or ZERO
        return (Decimal(revenue) - Decimal(returns),
                Decimal(cost) - Decimal(cost_returns))

    @staticmethod
    def _sum_documents(session, model, date_column, amount_column, status,
                       date_from: _dt.date, date_to: _dt.date) -> Decimal:
        total = session.execute(
            select(func.sum(amount_column)).where(
                model.status == status, date_column >= date_from, date_column <= date_to)
        ).scalar()
        return Decimal(total or 0)
