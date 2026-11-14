"""Accounting module setup: standard chart of accounts and dashboard counters.

The standard chart is a *template* the administrator loads on demand (button in the
UI / ``load_standard_chart``). It is real data the user owns afterwards - never
sample transactions - and loading it twice is a no-op.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from pars_erp.accounting import constants as C
from pars_erp.db.models import (
    Account,
    CostCenter,
    DetailAccount,
    FiscalPeriod,
    Journal,
    Project,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.accounts_service import AccountService
from pars_erp.services.audit_service import AuditService
from pars_erp.services.periods_service import PeriodService

ZERO = Decimal("0")

#: ``(code, title, level, type, section, parent_code)`` for the default mask "1-2-3".
STANDARD_CHART: tuple[tuple[str, str, str, str, str | None, str | None], ...] = (
    ("1", "دارایی‌ها", C.LEVEL_GROUP, C.TYPE_ASSET, None, None),
    ("101", "دارایی‌های جاری", C.LEVEL_TOTAL, C.TYPE_ASSET, "current_assets", "1"),
    ("101001", "موجودی نقد و بانک", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET, "current_assets", "101"),
    ("101002", "حساب‌های دریافتنی تجاری", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "current_assets", "101"),
    ("101003", "موجودی کالا", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET, "current_assets", "101"),
    ("101004", "پیش‌پرداخت‌ها", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET, "current_assets", "101"),
    ("101005", "صندوق‌های نقدی", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET, "current_assets", "101"),
    ("101006", "حساب‌های بانکی", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET, "current_assets", "101"),
    ("101007", "چک‌های دریافتی در جریان وصول", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "current_assets", "101"),
    ("101008", "وام و مساعدهٔ کارکنان", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "current_assets", "101"),
    ("102", "دارایی‌های غیرجاری", C.LEVEL_TOTAL, C.TYPE_ASSET, "non_current_assets", "1"),
    ("102001", "دارایی‌های ثابت مشهود", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "non_current_assets", "102"),
    ("102002", "دارایی‌های نامشهود", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "non_current_assets", "102"),
    ("102003", "استهلاک انباشتهٔ دارایی‌های ثابت", C.LEVEL_SUBSIDIARY, C.TYPE_ASSET,
     "non_current_assets", "102"),

    ("2", "بدهی‌ها", C.LEVEL_GROUP, C.TYPE_LIABILITY, None, None),
    ("201", "بدهی‌های جاری", C.LEVEL_TOTAL, C.TYPE_LIABILITY, "current_liabilities", "2"),
    ("201001", "حساب‌های پرداختنی تجاری", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "current_liabilities", "201"),
    ("201002", "مالیات پرداختنی", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "current_liabilities", "201"),
    ("201003", "حقوق و دستمزد پرداختنی", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "current_liabilities", "201"),
    ("201004", "چک‌های پرداختنی", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "current_liabilities", "201"),
    ("201005", "بیمهٔ تأمین اجتماعی پرداختنی", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "current_liabilities", "201"),
    ("202", "بدهی‌های غیرجاری", C.LEVEL_TOTAL, C.TYPE_LIABILITY,
     "non_current_liabilities", "2"),
    ("202001", "تسهیلات مالی بلندمدت", C.LEVEL_SUBSIDIARY, C.TYPE_LIABILITY,
     "non_current_liabilities", "202"),

    ("3", "سرمایه", C.LEVEL_GROUP, C.TYPE_EQUITY, None, None),
    ("301", "حساب‌های سرمایه", C.LEVEL_TOTAL, C.TYPE_EQUITY, "equity", "3"),
    ("301001", "سرمایه شرکا", C.LEVEL_SUBSIDIARY, C.TYPE_EQUITY, "equity", "301"),
    ("301002", "سود و زیان انباشته", C.LEVEL_SUBSIDIARY, C.TYPE_EQUITY, "equity", "301"),

    ("4", "درآمدها", C.LEVEL_GROUP, C.TYPE_REVENUE, None, None),
    ("401", "درآمد فروش", C.LEVEL_TOTAL, C.TYPE_REVENUE, "revenue", "4"),
    ("401001", "فروش کالا", C.LEVEL_SUBSIDIARY, C.TYPE_REVENUE, "revenue", "401"),
    ("401002", "درآمد خدمات", C.LEVEL_SUBSIDIARY, C.TYPE_REVENUE, "revenue", "401"),
    ("402", "سایر درآمدها", C.LEVEL_TOTAL, C.TYPE_REVENUE, "other_income", "4"),
    ("402001", "درآمد متفرقه", C.LEVEL_SUBSIDIARY, C.TYPE_REVENUE, "other_income", "402"),
    ("402002", "سود فروش دارایی ثابت", C.LEVEL_SUBSIDIARY, C.TYPE_REVENUE,
     "other_income", "402"),

    ("5", "هزینه‌ها", C.LEVEL_GROUP, C.TYPE_EXPENSE, None, None),
    ("501", "بهای تمام‌شده", C.LEVEL_TOTAL, C.TYPE_EXPENSE, "cogs", "5"),
    ("501001", "بهای تمام‌شده کالای فروش‌رفته", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "cogs", "501"),
    ("502", "هزینه‌های عملیاتی", C.LEVEL_TOTAL, C.TYPE_EXPENSE, "operating_expense", "5"),
    ("502001", "حقوق و دستمزد", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "operating_expense", "502"),
    ("502002", "اجاره", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE, "operating_expense", "502"),
    ("502003", "هزینه‌های اداری و عمومی", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "operating_expense", "502"),
    ("502004", "کارمزد و هزینه‌های بانکی", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "operating_expense", "502"),
    ("502005", "هزینهٔ استهلاک دارایی‌های ثابت", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "operating_expense", "502"),
    ("502006", "بیمهٔ سهم کارفرما", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "operating_expense", "502"),
    ("503", "سایر هزینه‌ها", C.LEVEL_TOTAL, C.TYPE_EXPENSE, "other_expense", "5"),
    ("503001", "هزینه‌های متفرقه", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE, "other_expense",
     "503"),
    ("503002", "زیان فروش و کنارگذاری دارایی ثابت", C.LEVEL_SUBSIDIARY, C.TYPE_EXPENSE,
     "other_expense", "503"),
)


@dataclass(frozen=True)
class SetupResult:
    created_accounts: int
    skipped_accounts: int
    created_periods: int


@dataclass(frozen=True)
class AccountingDashboard:
    accounts_total: int
    accounts_active: int
    details_total: int
    periods_total: int
    active_period: str
    journals_draft: int
    journals_pending: int
    journals_approved: int
    journals_posted: int
    posted_total: Decimal
    cost_centers: int
    projects: int
    is_ready: bool
    hints: tuple[str, ...] = ()


class AccountingSetupService:
    def __init__(self, db: Database, audit: AuditService, accounts: AccountService,
                 periods: PeriodService, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.accounts = accounts
        self.periods = periods
        self.settings = settings

    # ------------------------------------------------------------- dashboard
    def dashboard(self, ctx: SecurityContext | None) -> AccountingDashboard:
        require_permission(ctx, "journals.view")
        with self.db.session_scope() as session:
            accounts_total = int(session.execute(
                select(func.count(Account.id))).scalar() or 0)
            accounts_active = int(session.execute(
                select(func.count(Account.id))
                .where(Account.is_active.is_(True))).scalar() or 0)
            details_total = int(session.execute(
                select(func.count(DetailAccount.id))).scalar() or 0)
            periods_total = int(session.execute(
                select(func.count(FiscalPeriod.id))).scalar() or 0)
            active = session.execute(
                select(FiscalPeriod).where(FiscalPeriod.is_active.is_(True))).scalars().first()
            def count_status(status: str) -> int:
                return int(session.execute(
                    select(func.count(Journal.id))
                    .where(Journal.status == status)).scalar() or 0)
            posted_total = session.execute(
                select(func.coalesce(func.sum(Journal.total_debit), 0))
                .where(Journal.status == C.STATUS_POSTED)).scalar() or 0
            cost_centers = int(session.execute(
                select(func.count(CostCenter.id))).scalar() or 0)
            projects = int(session.execute(
                select(func.count(Project.id))).scalar() or 0)
        hints: list[str] = []
        if accounts_total == 0:
            hints.append("کدینگ حساب‌ها خالی است؛ از دکمهٔ «بارگذاری کدینگ استاندارد» "
                         "یا تعریف دستی حساب‌ها شروع کنید.")
        if periods_total == 0:
            hints.append("هیچ دورهٔ مالی تعریف نشده است؛ بدون دورهٔ مالی ثبت سند ممکن نیست.")
        elif active is None:
            hints.append("دورهٔ مالی فعال انتخاب نشده است.")
        return AccountingDashboard(
            accounts_total=accounts_total, accounts_active=accounts_active,
            details_total=details_total, periods_total=periods_total,
            active_period=(active.title_fa if active else ""),
            journals_draft=count_status(C.STATUS_DRAFT),
            journals_pending=count_status(C.STATUS_PENDING),
            journals_approved=count_status(C.STATUS_APPROVED),
            journals_posted=count_status(C.STATUS_POSTED),
            posted_total=Decimal(posted_total or 0),
            cost_centers=cost_centers, projects=projects,
            is_ready=accounts_total > 0 and periods_total > 0,
            hints=tuple(hints))

    # ---------------------------------------------------------------- seeding
    def load_standard_chart(self, ctx: SecurityContext | None) -> SetupResult:
        require_permission(ctx, "accounts.create")
        created = 0
        skipped = 0
        with self.db.session_scope() as session:
            existing = {account.code: account for account in
                        session.execute(select(Account)).scalars()}
            for code, title, level, account_type, section, parent_code in STANDARD_CHART:
                if code in existing:
                    skipped += 1
                    continue
                parent = existing.get(parent_code) if parent_code else None
                account = Account(
                    code=code, title_fa=title, level=level, account_type=account_type,
                    nature=C.TYPE_NATURE[account_type],
                    statement_section=section or C.DEFAULT_SECTION_BY_TYPE[account_type],
                    parent_id=parent.id if parent else None,
                    is_active=True, is_system=False,
                    sort_order=int(code), created_by_id=ctx.user_id if ctx else None)
                session.add(account)
                session.flush()
                existing[code] = account
                created += 1
            self.audit.log_audit(
                ctx=ctx, entity_type="chart_of_accounts", entity_id=0, action="seed",
                summary_fa=f"بارگذاری کدینگ استاندارد حساب‌ها ({created} حساب جدید)",
                after={"created": created, "skipped": skipped}, session=session)
        return SetupResult(created_accounts=created, skipped_accounts=skipped,
                           created_periods=0)

    def suggest_period(self, ctx: SecurityContext | None) -> tuple[str, str, _dt.date, _dt.date]:
        """Suggest the next fiscal year (Jalali year) as ``code/title/start/end``."""
        from pars_erp.core.jalali import JalaliDate, jalali_year_range

        today = JalaliDate.today()
        year = today.year
        while True:
            start, end = jalali_year_range(year)
            with self.db.session_scope() as session:
                clash = session.execute(
                    select(FiscalPeriod).where(FiscalPeriod.start_date <= end,
                                               FiscalPeriod.end_date >= start)
                ).scalars().first()
            if clash is None:
                return str(year), f"سال مالی {year}", start, end
            year += 1

    def create_period_from_suggestion(self, ctx: SecurityContext | None):
        require_permission(ctx, "periods.create")
        code, title, start, end = self.suggest_period(ctx)
        from pars_erp.services.periods_service import PeriodInput

        return self.periods.create(ctx, PeriodInput(code=code, title_fa=title,
                                                    start_date=start, end_date=end,
                                                    is_active=True))

    def ensure_basic_setup(self, ctx: SecurityContext | None) -> SetupResult:
        """One-click start: standard chart + current fiscal period."""
        chart = self.load_standard_chart(ctx)
        periods_created = 0
        rows = self.periods.list_periods(ctx)
        if not rows:
            self.create_period_from_suggestion(ctx)
            periods_created = 1
        elif not any(row.is_active for row in rows):
            open_rows = [row for row in rows if row.is_open]
            if open_rows:
                self.periods.set_active(ctx, open_rows[0].id)
        return SetupResult(created_accounts=chart.created_accounts,
                           skipped_accounts=chart.skipped_accounts,
                           created_periods=periods_created)

    # ---------------------------------------------------------------- helpers
    def retained_earnings_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        require_permission(ctx, "accounts.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(Account).where(Account.level == C.LEVEL_SUBSIDIARY,
                                      Account.account_type == C.TYPE_EQUITY,
                                      Account.is_active.is_(True))
                .order_by(Account.code)).scalars()
            return [(item.id, f"{item.code} — {item.title_fa}") for item in rows]
