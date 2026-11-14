"""The report catalogue: every report the engine may run, and nothing else.

Each entry names

* a **permission** the caller must hold (checked by the engine *and* re-checked by
  the service that produces the rows);
* the **filters** it honours (the UI only offers those);
* a **fetcher** - a plain Python callable. No SQL, no table names, no column names
  from the user ever reach the database: the fetcher calls an existing, tested,
  permission-aware service method.

Reports are grouped the way the product is grouped (accounting, purchasing and
sales, inventory, treasury, HR, payroll, fixed assets). Production, contracting,
imports, distribution and the tax-system (مؤدیان) reports are **not** here because
those modules do not exist yet - see ``docs/phase7/remaining.md``.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from pars_erp.core.timeutil import now_local
from pars_erp.reporting import accounting_tables as A
from pars_erp.reporting.engine import (
    FILTER_DATE_RANGE,
    DrillTarget,
    FilterSpec,
    ReportCatalogue,
    ReportDefinition,
    ReportQuery,
)
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_NUMBER,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)

SECTION_ACCOUNTING = "accounting"
SECTION_COMMERCE = "commerce"
SECTION_INVENTORY = "inventory"
SECTION_TREASURY = "treasury"
SECTION_HR = "hr"
SECTION_PAYROLL = "payroll"
SECTION_ASSETS = "assets"

SECTION_TITLES_FA = {
    SECTION_ACCOUNTING: "حسابداری",
    SECTION_COMMERCE: "خرید و فروش",
    SECTION_INVENTORY: "انبار و موجودی",
    SECTION_TREASURY: "خزانه‌داری",
    SECTION_HR: "منابع انسانی",
    SECTION_PAYROLL: "حقوق و دستمزد",
    SECTION_ASSETS: "دارایی ثابت",
}

DATE_FILTER = FilterSpec("date_range", "بازهٔ تاریخ", FILTER_DATE_RANGE, required=True)


def default_period() -> tuple[_dt.date, _dt.date]:
    """The default range: from the first day of the current local month."""
    today = now_local().date()
    return today.replace(day=1), today


def _period(query: ReportQuery) -> ReportPeriod:
    start, end = query.date_from, query.date_to
    if not start or not end:
        default_start, default_end = default_period()
        start = start or default_start
        end = end or default_end
    return ReportPeriod(start, end)


def _as_of(query: ReportQuery) -> _dt.date:
    return query.date_to or query.date_from or now_local().date()


# --------------------------------------------------------------- conversions
def _kind_for(value, current: str) -> str:
    if current != KIND_TEXT:
        return current
    if isinstance(value, Decimal):
        return KIND_AMOUNT
    if isinstance(value, _dt.datetime):
        return KIND_DATE
    if isinstance(value, _dt.date):
        return KIND_DATE
    if isinstance(value, int) and not isinstance(value, bool):
        return KIND_NUMBER
    return KIND_TEXT


#: safety cap for a single report fetch (the setting ``report_max_rows`` is the
#: user-facing limit; this keeps a runaway query from exhausting memory)
MAX_REPORT_ROWS = 20_000


def _sum_totals(columns, rows):
    """Recompute the totals of a merged multi-page table."""
    numeric = [index for index, column in enumerate(columns)
               if column.kind in (KIND_AMOUNT, KIND_NUMBER)]
    if not numeric:
        return None
    totals = []
    for index, column in enumerate(columns):
        if index in numeric:
            totals.append(sum((row[index] for row in rows
                               if index < len(row) and isinstance(row[index], Decimal)),
                              Decimal("0")))
        else:
            totals.append("جمع" if index == 0 else None)
    return tuple(totals)


def render_table(service_table, *, title: str | None = None) -> ReportTable:
    """Convert a service-level report table into a render (printable) table.

    Service tables carry only column *titles*; the display kind of each column is
    inferred from the values it actually contains, so the same number is formatted
    the same way on screen, in the PDF and in the spreadsheet.
    """
    titles = tuple(service_table.columns)
    kinds = [KIND_TEXT] * len(titles)
    for row in service_table.rows:
        for index, value in enumerate(row[:len(titles)]):
            kinds[index] = _kind_for(value, kinds[index])
    columns = tuple(
        ReportColumn(key=f"c{index}", title_fa=titles[index], kind=kinds[index],
                     width=1.0 if kinds[index] == KIND_TEXT else 1.2, align="right")
        for index in range(len(titles)))
    rows = tuple(tuple(row) for row in service_table.rows)
    totals = None
    if rows and any(kind in (KIND_AMOUNT, KIND_NUMBER) for kind in kinds):
        total_row = []
        for index, kind in enumerate(kinds):
            if kind in (KIND_AMOUNT, KIND_NUMBER):
                numbers = [row[index] for row in rows
                           if index < len(row) and isinstance(row[index], (Decimal, int))
                           and not isinstance(row[index], bool)]
                total_row.append(sum(numbers, Decimal("0") if kind == KIND_AMOUNT else 0))
            else:
                total_row.append("جمع" if index == 0 else None)
        totals = tuple(total_row)
    meta = tuple(text for text in (service_table.meta_fa,) if text)
    return ReportTable(title=title or service_table.title_fa, columns=columns, rows=rows,
                       meta=meta, totals=totals)


def _formatter(services):
    from pars_erp.ui.formatting import Formatter

    snapshot = services.settings.snapshot()
    return Formatter(persian_digits=snapshot.bool("persian_digits"),
                     currency_code=snapshot.currency_code)


# ---------------------------------------------------------------------- build
def build_catalogue(services, *, formatter=None) -> ReportCatalogue:
    """Build the catalogue for one application instance."""
    try:
        fmt = formatter or _formatter(services)
    except Exception:  # pragma: no cover - a database without settings yet
        from pars_erp.ui.formatting import Formatter
        fmt = formatter or Formatter()

    definitions: list[ReportDefinition] = []
    add = definitions.append

    # ---------------------------------------------------------- accounting
    def journal_book(ctx, query):
        """Every posted line of the range - read page by page.

        The ledger service caps a page at 200 rows, so a single "give me 5 000"
        call returned 200 and the report then paginated, summed and exported a
        fifth of the daybook without any warning.
        """
        period = _period(query)
        collected: list = []
        first_table = None
        page_no = 1
        while True:
            table, page = A.journal_book_table(
                services, ctx, fmt, start=period.date_from, end=period.date_to,
                account_id=query.account_id, search=query.search or None,
                page=page_no, page_size=200)
            first_table = first_table or table
            collected.extend(table.rows)
            total = int(getattr(page, "total", 0))
            if (not table.rows or len(collected) >= total
                    or len(collected) >= MAX_REPORT_ROWS):
                break
            page_no += 1
        return type(first_table)(
            title=first_table.title, columns=first_table.columns,
            rows=tuple(collected), company=first_table.company,
            subtitle=first_table.subtitle, meta=first_table.meta,
            totals=_sum_totals(first_table.columns, collected),
            notes=first_table.notes, currency_code=first_table.currency_code)

    add(ReportDefinition(
        key="acc_journal_book", title_fa="دفتر روزنامه", section=SECTION_ACCOUNTING,
        section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.journal_book",
        description_fa="همهٔ سطرهای اسناد ثبت‌نهایی‌شده در بازهٔ انتخابی.",
        fetcher=journal_book, filters=(DATE_FILTER,),
        drill=lambda row: DrillTarget("journals", search=str(row[0])),
        sort_order=10))

    add(ReportDefinition(
        key="acc_general_ledger", title_fa="دفتر کل", section=SECTION_ACCOUNTING,
        section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.general_ledger",
        description_fa="مانده و گردش حساب‌های کل در بازهٔ انتخابی.",
        fetcher=lambda ctx, query: A.general_ledger_table(
            services, ctx, fmt, start=_period(query).date_from,
            end=_period(query).date_to),
        filters=(DATE_FILTER,), sort_order=20))

    add(ReportDefinition(
        key="acc_subsidiary_ledger", title_fa="دفتر معین", section=SECTION_ACCOUNTING,
        section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.subsidiary_ledger",
        description_fa="گردش حساب معین انتخاب‌شده (یا همهٔ معین‌ها).",
        fetcher=lambda ctx, query: A.subsidiary_ledger_table(
            services, ctx, fmt, account_id=query.account_id,
            start=_period(query).date_from, end=_period(query).date_to),
        filters=(DATE_FILTER,), sort_order=30))

    add(ReportDefinition(
        key="acc_turnover", title_fa="گردش حساب", section=SECTION_ACCOUNTING,
        section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.trial_balance",
        description_fa="گردش بدهکار/بستانکار و ماندهٔ هر حساب.",
        fetcher=lambda ctx, query: A.turnover_table(
            services, ctx, fmt, start=_period(query).date_from,
            end=_period(query).date_to),
        filters=(DATE_FILTER,), sort_order=40))

    add(ReportDefinition(
        key="acc_trial_balance", title_fa="تراز آزمایشی دو ستونی",
        section=SECTION_ACCOUNTING, section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.trial_balance",
        description_fa="تراز آزمایشی دو ستونی از اسناد ثبت‌شده.",
        fetcher=lambda ctx, query: A.trial_balance_table(
            services, ctx, fmt, start=_period(query).date_from,
            end=_period(query).date_to),
        filters=(DATE_FILTER,), sort_order=50))

    add(ReportDefinition(
        key="acc_balance_sheet", title_fa="ترازنامه", section=SECTION_ACCOUNTING,
        section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.statements",
        description_fa="ترازنامهٔ تاریخ پایان بازه.",
        fetcher=lambda ctx, query: A.balance_sheet_table(
            services, ctx, fmt, as_of=_as_of(query)),
        filters=(DATE_FILTER,), sort_order=60))

    add(ReportDefinition(
        key="acc_income_statement", title_fa="صورت سود و زیان",
        section=SECTION_ACCOUNTING, section_title_fa=SECTION_TITLES_FA[SECTION_ACCOUNTING],
        permission="reports.statements",
        description_fa="درآمدها و هزینه‌های بازهٔ انتخابی.",
        fetcher=lambda ctx, query: A.income_statement_table(
            services, ctx, fmt, start=_period(query).date_from,
            end=_period(query).date_to),
        filters=(DATE_FILTER,), sort_order=70))

    # ------------------------------------------------------ purchasing/sales
    commerce = services.commerce_reports

    def commerce_report(method: str, *, extra=None):
        def fetch(ctx, query):
            table = getattr(commerce, method)(ctx, _period(query), **(extra or {}))
            return render_table(table)
        return fetch

    for key, title, method, order, description in (
        ("com_purchase_summary", "خرید به تفکیک دوره", "purchase_summary", 100,
         "جمع خرید و برگشت خرید در هر دوره."),
        ("com_sales_summary", "فروش به تفکیک دوره", "sales_summary", 110,
         "جمع فروش و برگشت فروش در هر دوره."),
        ("com_purchase_by_product", "خرید به تفکیک کالا", "purchase_by_product", 120,
         "مقدار و مبلغ خرید هر کالا."),
        ("com_sales_by_product", "فروش به تفکیک کالا", "sales_by_product", 130,
         "مقدار و مبلغ فروش هر کالا."),
        ("com_best_sellers", "پرفروش‌ترین کالاها", "best_sellers", 140,
         "کالاهایی با بیشترین مبلغ فروش."),
        ("com_slow_movers", "کم‌فروش‌ترین کالاها", "slow_movers", 150,
         "کالاهایی با کمترین گردش فروش."),
        ("com_discounts", "تخفیف‌های ارائه‌شده", "discount_report", 160,
         "تخفیف ثبت‌شده در فاکتورهای فروش."),
        ("com_transfers", "انتقال بین انبارها", "transfers", 170,
         "اسناد انتقال کالا بین انبارها."),
        ("com_count_discrepancies", "مغایرت انبارگردانی", "count_discrepancies", 180,
         "اختلاف شمارش انبار با موجودی دفتری."),
    ):
        add(ReportDefinition(
            key=key, title_fa=title, section=SECTION_COMMERCE,
            section_title_fa=SECTION_TITLES_FA[SECTION_COMMERCE],
            permission="commerce.reports",
            description_fa=description,
            fetcher=commerce_report(method),
            filters=(DATE_FILTER,), sort_order=order))

    add(ReportDefinition(
        key="com_person_balances", title_fa="ماندهٔ مشتریان و تأمین‌کنندگان",
        section=SECTION_COMMERCE, section_title_fa=SECTION_TITLES_FA[SECTION_COMMERCE],
        permission="commerce.reports",
        description_fa="ماندهٔ حساب اشخاص از اسناد بازرگانی.",
        fetcher=lambda ctx, query: render_table(
            commerce.person_balances(ctx, role="customer")),
        sort_order=190))

    # -------------------------------------------------------------- inventory
    add(ReportDefinition(
        key="inv_stock_value", title_fa="ارزش ریالی موجودی", section=SECTION_INVENTORY,
        section_title_fa=SECTION_TITLES_FA[SECTION_INVENTORY], permission="stock.view",
        description_fa="ارزش موجودی هر انبار بر پایهٔ لایهٔ بهای تمام‌شده.",
        fetcher=lambda ctx, query: render_table(
            commerce.stock_value(ctx, warehouse_id=query.warehouse_id)),
        sort_order=200))

    add(ReportDefinition(
        key="inv_low_stock", title_fa="کالاهای کم‌موجودی", section=SECTION_INVENTORY,
        section_title_fa=SECTION_TITLES_FA[SECTION_INVENTORY], permission="stock.view",
        description_fa="کالاهایی که موجودی آن‌ها به حد سفارش رسیده است.",
        fetcher=lambda ctx, query: render_table(commerce.low_stock(ctx)),
        sort_order=210))

    add(ReportDefinition(
        key="inv_idle_stock", title_fa="کالاهای بدون گردش", section=SECTION_INVENTORY,
        section_title_fa=SECTION_TITLES_FA[SECTION_INVENTORY], permission="stock.view",
        description_fa="کالاهایی که در بازهٔ انتخابی هیچ حرکتی نداشته‌اند.",
        fetcher=lambda ctx, query: render_table(
            commerce.idle_stock(ctx, days=_days_between(query))),
        sort_order=220))

    # --------------------------------------------------------------- treasury
    treasury = services.treasury_reports

    for key, title, fetcher, order, description in (
        ("tre_bank_ledger", "گردش حساب بانکی",
         lambda ctx, query: treasury.bank_ledger(
             ctx, _period(query),
             bank_account_id=query.params.get("bank_account_id")),
         300, "دریافت و پرداخت هر حساب بانکی در بازه."),
        ("tre_cash_ledger", "گردش صندوق",
         lambda ctx, query: treasury.cash_ledger(
             ctx, _period(query), cash_box_id=query.params.get("cash_box_id")),
         310, "دریافت و پرداخت هر صندوق در بازه."),
        ("tre_open_invoices", "فاکتورهای تسویه‌نشده",
         lambda ctx, query: treasury.open_invoices(ctx, _period(query),
                                                   direction="receivable"),
         320, "مطالبات باز با ماندهٔ باقی‌مانده."),
        ("tre_cash_flow", "جریان نقدی", lambda ctx, query: treasury.cash_flow(
            ctx, _period(query)), 330, "ورود و خروج نقد در بازه."),
        ("tre_receipts", "دریافت‌ها", lambda ctx, query: treasury.person_flows(
            ctx, _period(query), kind="receipt"), 340, "دریافت‌های ثبت‌شده."),
        ("tre_payments", "پرداخت‌ها", lambda ctx, query: treasury.person_flows(
            ctx, _period(query), kind="payment"), 350, "پرداخت‌های ثبت‌شده."),
        ("tre_cheques_due", "چک‌های نزدیک سررسید",
         lambda ctx, query: treasury.cheques_due(ctx, days=_days_between(query)),
         360, "چک‌هایی که در بازهٔ انتخابی سررسید می‌شوند."),
        ("tre_forecast", "پیش‌بینی جریان نقدی",
         lambda ctx, query: treasury.forecast(ctx, days=_days_between(query)),
         370, "پیش‌بینی بر پایهٔ اقلام ثبت‌شده و سررسیدها."),
    ):
        add(ReportDefinition(
            key=key, title_fa=title, section=SECTION_TREASURY,
            section_title_fa=SECTION_TITLES_FA[SECTION_TREASURY],
            permission="treasury.reports", description_fa=description,
            fetcher=lambda ctx, query, fetcher=fetcher: render_table(fetcher(ctx, query)),
            filters=(DATE_FILTER,), sort_order=order))

    # -------------------------------------------------------- hr and payroll
    hr = services.hr_reports

    for key, title, method, order, filter_kinds, description in (
        ("hr_staff_list", "فهرست کارکنان", "staff_list", 400, (),
         "کارکنان با واحد، سمت و وضعیت شغلی."),
        ("hr_contracts", "وضعیت قراردادها", "contracts", 410, (),
         "قراردادهای فعال و نزدیک انقضا."),
        ("hr_attendance", "حضور و غیاب", "attendance", 420, (DATE_FILTER,),
         "ساعت کار، تأخیر و اضافه‌کار در بازه."),
        ("hr_leave", "مرخصی‌ها", "leave", 430, (DATE_FILTER,), "درخواست‌های مرخصی."),
        ("hr_overtime", "اضافه‌کاری", "overtime", 440, (DATE_FILTER,),
         "ساعت اضافه‌کاری تأییدشده."),
        ("hr_missions", "مأموریت‌ها", "missions", 450, (DATE_FILTER,),
         "مأموریت‌های ثبت‌شده."),
    ):
        add(ReportDefinition(
            key=key, title_fa=title, section=SECTION_HR,
            section_title_fa=SECTION_TITLES_FA[SECTION_HR],
            permission="hr.reports", description_fa=description,
            fetcher=(lambda method: lambda ctx, query: render_table(
                getattr(hr, method)(ctx, **(
                    {"period": _period(query), "org_unit_id": query.org_unit_id,
                     "search": query.search}
                    if method == "staff_list" else
                    {"period": _period(query)} if method in
                    ("attendance", "leave", "overtime", "missions") else {}))))(method),
            filters=filter_kinds, sort_order=order))

    payroll = services.payroll_reports

    add(ReportDefinition(
        key="pay_runs", title_fa="فهرست دوره‌های حقوق", section=SECTION_PAYROLL,
        section_title_fa=SECTION_TITLES_FA[SECTION_PAYROLL], permission="payroll.reports",
        description_fa="دوره‌های حقوق با جمع‌ها و وضعیت.",
        fetcher=lambda ctx, query: render_table(
            payroll.runs(ctx, year=query.params.get("year"))),
        sort_order=460))

    add(ReportDefinition(
        key="pay_loan_balances", title_fa="ماندهٔ وام کارکنان", section=SECTION_PAYROLL,
        section_title_fa=SECTION_TITLES_FA[SECTION_PAYROLL], permission="payroll.reports",
        description_fa="وام‌های باز و اقساط باقی‌مانده.",
        fetcher=lambda ctx, query: render_table(payroll.loan_balances(ctx)),
        sort_order=470))

    add(ReportDefinition(
        key="pay_advances", title_fa="مساعده‌ها", section=SECTION_PAYROLL,
        section_title_fa=SECTION_TITLES_FA[SECTION_PAYROLL], permission="payroll.reports",
        description_fa="مساعده‌های پرداخت‌شده در سال انتخابی.",
        fetcher=lambda ctx, query: render_table(
            payroll.advances(ctx, year=query.params.get("year"))),
        sort_order=480))

    # ---------------------------------------------------------------- assets
    assets = services.asset_reports

    for key, title, method, order, description in (
        ("ast_register", "فهرست دارایی‌ها", "register", 500,
         "دارایی‌ها با ارزش دفتری و وضعیت."),
        ("ast_by_category", "دارایی به تفکیک دسته", "by_category", 510,
         "تعداد و بهای تمام‌شدهٔ هر دسته."),
        ("ast_by_location", "دارایی به تفکیک محل", "by_location", 520,
         "پراکندگی دارایی‌ها بر اساس محل استقرار."),
        ("ast_by_custodian", "دارایی به تفکیک امانت‌دار", "by_custodian", 530,
         "دارایی‌های در اختیار هر کارمند."),
        ("ast_depreciation", "استهلاک دوره", "depreciation", 540,
         "استهلاک محاسبه‌شدهٔ هر دارایی."),
        ("ast_disposals", "فروش و کنارگذاری", "disposals", 550,
         "واگذاری‌ها با سود یا زیان."),
        ("ast_maintenance", "هزینهٔ تعمیر و نگهداری", "maintenance", 560,
         "تعمیرهای ثبت‌شده و هزینهٔ آن‌ها."),
    ):
        add(ReportDefinition(
            key=key, title_fa=title, section=SECTION_ASSETS,
            section_title_fa=SECTION_TITLES_FA[SECTION_ASSETS],
            permission="assets.reports", description_fa=description,
            fetcher=(lambda method: lambda ctx, query: render_table(
                getattr(assets, method)(ctx)))(method),
            filters=(), sort_order=order))

    return ReportCatalogue(definitions)


def _days_between(query: ReportQuery) -> int:
    if query.params.get("days"):
        try:
            return max(1, int(query.params["days"]))
        except (TypeError, ValueError):
            return 30
    start, end = _period(query).date_from, _period(query).date_to
    return max(1, (end - start).days)


__all__ = [
    "SECTION_ACCOUNTING",
    "SECTION_ASSETS",
    "SECTION_COMMERCE",
    "SECTION_HR",
    "SECTION_INVENTORY",
    "SECTION_PAYROLL",
    "SECTION_TREASURY",
    "SECTION_TITLES_FA",
    "build_catalogue",
    "default_period",
    "render_table",
]
