# ۶) گزارش‌ها و داشبورد خزانه

## سرویس گزارش (`TreasuryReportService`)

| متد | خروجی |
|-----|-------|
| `bank_ledger(ctx, bank_account_id, period)` | گردش حساب بانکی (۸ ستون) |
| `cash_ledger(ctx, cash_box_id, period)` | گردش صندوق (۸ ستون) |
| `bank_balances(ctx)` | مانده حساب‌ها (۵ ستون) |
| `cash_balances(ctx)` | مانده صندوق‌ها (۴ ستون) |
| `cheques(ctx, direction=..., period=...)` | چک‌های دریافتی/پرداختی (۷ ستون) |
| `cheques_due(ctx, days)` | چک‌های نزدیک سرسید (۷ ستون) |
| `person_flows(ctx, role="customer"\|"supplier")` | دریافت/پرداخت به اشخاص (۶ ستون) |
| `open_invoices(ctx, kind)` | فاکتورهای باز (۶ ستون) |
| `cash_flow(ctx, period)` | جریان نقدی روزانه (۴ ستون) |
| `forecast(ctx, days)` | پیش‌بینی جریان نقدی (۴ ستون) |
| `calendar(ctx, period)` | تقویم تعهدات: چک، اقساط، اقلام برنامه‌ریزی‌شده |
| `dashboard(ctx)` | ارقام خلاصه برای داشبورد |

نکته: `cheques(...)` بر اساس **تاریخ صدور** فیلتر می‌کند، نه سرسید؛ برای سرسید از
`cheques_due` استفاده کنید.

همهٔ گزارش‌ها `ReportTable` برمی‌گردانند: `title`، `headers`، `rows`، `totals()`،
`meta` و آمادهٔ چاپ/PDF/Excel از طریق `report_render_service`.

## داشبورد (`TreasuryDashboardService`)

- `balances(ctx)` — جمع صندوق‌ها و بانک‌ها
- `figures(ctx)` — ۸ شاخص کلیدی (مانده‌ها، دریافت/پرداخت ماه، چک‌های در جریان، …)
- `today_documents(ctx)` — اسناد امروز
- `watch_cheques(ctx)` — چک‌های نیازمند توجه
- `cash_flow_trend(ctx, days)` — روند روزانه
- `receipts_vs_payments(ctx, period)` — مقایسهٔ دریافت و پرداخت برای نمودار

## اقلام برنامه‌ریزی‌شده (`trs_planned_items`)

`add_planned_item` / `mark_planned_done` برای تعهدات آیندهٔ بدون سند
(مثلاً اجارهٔ ماه بعد) که در تقویم و پیش‌بینی ظاهر می‌شوند.

## صفحه‌ها

- `treasury_dashboard` → ۸ کارت شاخص + جدول امروز + چک‌های نیازمند توجه + روند روزانه
- `treasury_reports` → ۱۴ گزارش با فیلتر دوره، چاپ/PDF و خروجی Excel
- `fund_flow` → ۵ نمای گردش وجوه (ورودی/خروجی/خالص/مانده)
- `receivables` / `payables` → فهرست اسناد تسویه‌نشده برای اقدام

## قواعد

- گزارش‌ها فقط خواندنی‌اند و هیچ تغییری در داده ایجاد نمی‌کنند.
- مبالغ با `Decimal` و قالب فارسی (`Formatter`) نمایش داده می‌شوند.
- خروجی Excel از `export_service` و قالب چاپ از `report_render_service` استفاده می‌کند.
