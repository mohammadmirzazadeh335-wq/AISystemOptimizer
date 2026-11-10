# گزارش‌های فاز ۵

همهٔ گزارش‌ها از `ReportTable` (فاز ۳) استفاده می‌کنند: ستون‌ها، ردیف‌ها،
`meta_fa` و `totals()`؛ بنابراین چاپ، PDF و Excel با همان `report_render_service`
فازهای قبل انجام می‌شود و مسیر دومی برای خروجی وجود ندارد.

## منابع انسانی — `services.hr_report_service.py`

| متد | گزارش | مجوز |
|-----|--------|------|
| `staff_list(ctx, status=, org_unit_id=, search=, include_sensitive=)` | فهرست کارکنان (+ کد ملی/موبایل/حساب/حقوق در صورت مجوز) | `hr.reports` |
| `contracts(ctx, expiring_within_days=30)` | قراردادها با وضعیت زمانی (جاری/در آستانهٔ انقضا/منقضی) | `hr.reports` |
| `attendance(ctx, ReportPeriod(...))` | روز حضور/غیبت، ساعت کارکرد، تأخیر، تعجیل، اضافه‌کار | `hr.reports` |
| `lateness(ctx, period)` | جزئیات هر مورد تأخیر | `hr.reports` |
| `leave(ctx, period)` | مرخصی‌ها با نوع، روز/ساعت و تصمیم‌گیرنده | `hr.reports` |
| `overtime(ctx, period)` | اضافه‌کار با نوع روز، وضعیت و اعمال در حقوق | `hr.reports` |
| `missions(ctx, period)` | مأموریت‌ها با مقصد، روز، هزینه و کمک‌هزینه | `hr.reports` |
| `headcount(ctx)` | شمار کارکنان به تفکیک وضعیت همکاری | `hr.reports` |

> `include_sensitive` فقط زمانی داده می‌دهد که مجوز `hr.employees.sensitive` هم
> داشته باشید؛ مقدار پیش‌فرض `False` است.

## حقوق و دستمزد — `services.payroll_report_service.py`

| متد | گزارش |
|-----|--------|
| `runs(ctx, year=)` | دوره‌های حقوق با جمع ناخالص/بیمه/مالیات/کسور/خالص |
| `register(ctx, run_id)` | لیست حقوق هر کارمند (۱۷ ستون) |
| `components(ctx, run_id)` | ریز اقلام و جمع هر قلم در دوره |
| `payments(ctx, run_id)` | وضعیت پرداخت هر ردیف + جمع پرداخت‌شده |
| `loan_balances(ctx, only_open=True)` | بدهی و اقساط هر کارمند |
| `advances(ctx, year=)` | مساعده‌ها با بازپرداخت و مانده |

## دارایی ثابت — `services/asset_report_service.py`

| متد | گزارش |
|-----|--------|
| `register(ctx, category_id=, location=, custodian_employee_id=, status=, search=, with_book_value=True)` | فهرست دارایی‌ها (+ استهلاک انباشته و ارزش دفتری) |
| `by_category(ctx)` / `by_location(ctx)` / `by_custodian(ctx)` | تجمیع به تفکیک دسته/محل/امانت‌دار |
| `depreciation(ctx, year=, month=, asset_id=)` | استهلاک دوره‌ها با وضعیت سند |
| `disposals(ctx, kind=)` | فروش/کنارگذاری با سود یا زیان |
| `sold_or_retired(ctx)` | دارایی‌های واگذارشده |
| `maintenance(ctx, asset_id=)` / `maintenance_detail(ctx, asset_id)` | هزینهٔ تعمیر هر دارایی و سوابق آن |

## محدودیت فعلی

گزارش‌ها در لایهٔ سرویس آماده و آزمون‌شده‌اند (جداول بالا)، اما صفحهٔ رابط کاربری
برای فیلتر و دکمهٔ چاپ/Excel در این فاز ساخته نشده است؛ به
[`remaining.md`](remaining.md) مراجعه کنید.
