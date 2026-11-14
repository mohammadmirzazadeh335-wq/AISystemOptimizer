# تنظیمات حقوق و محاسبهٔ دستمزد

**مجوزها:** `payroll.settings` (نسخه‌های تنظیمات) — `payroll.calculate` (محاسبه) —
`payroll.view` (مشاهده)

## نسخه‌های تاریخ‌دار تنظیمات

`payroll.create_version(ctx, VersionInput(code=..., title_fa=..., effective_from=...,
effective_to=None, status=..., source_note=..., items={...},
brackets=(TaxBracketInput(from_amount, to_amount, rate_percent), ...)))`

کلیدهای قابل تنظیم (`PAY_SETTING_KEYS`، همه به‌صورت متن ذخیره می‌شوند و به `Decimal`
تبدیل می‌گردند):

| کلید | معنا |
|------|------|
| `base_hours_per_month` | ساعت کاری موظفی ماه |
| `work_days_per_month` | روز کاری ماه |
| `overtime_factor` / `holiday_overtime_factor` | ضریب اضافه‌کاری عادی/تعطیل |
| `housing_allowance` / `food_allowance` | کمک‌هزینهٔ مسکن و خواربار |
| `child_allowance_per_child` / `marriage_allowance` | حق اولاد و تأهل |
| `seniority_allowance_per_year` | پایهٔ سنوات |
| `continuous_benefit_default` / `non_continuous_benefit_default` | مزایای مستمر/غیرمستمر |
| `insurance_employee_rate` / `insurance_employer_rate` / `insurance_base_cap` | بیمه |
| `income_tax_exempt_amount` | معافیت مالیاتی |
| `absence_deduction_per_day` | کسور هر روز غیبت (خالی = نرخ روزانه) |
| `loan_max_share_of_salary` | سقف قسط نسبت به حقوق |
| `rounding_step` | گام گرد کردن خالص (مثلاً ۱۰۰۰ ریال) |

- هر نسخه یک بازهٔ اعتبار دارد؛ `version_for(session, year, month)` نسخهٔ معتبر همان
  دوره را برمی‌گرداند و دورهٔ حقوق، شناسهٔ نسخه را **قفل** می‌کند.
- نسخه‌ای که در یک دورهٔ تأییدشده/ثبت‌شده/پرداخت‌شده استفاده شده باشد قابل ویرایش
  نیست؛ برای تغییر نرخ باید نسخهٔ جدید با تاریخ اجرا ساخت (`ConflictError` با پیام فارسی).
- `ensure_default_version(ctx)` یک نسخهٔ پایه با **همهٔ مقادیر صفر** و یادداشت
  «از منبع رسمی پر کنید» می‌سازد. هیچ نرخ قانونی در کد نیست.
- پله‌های مالیات (`TaxBracketInput`) هم تاریخ‌دار هستند؛ نرخ باید بین ۰ و ۱۰۰ باشد.

## دورهٔ حقوق

`payroll.create_run(ctx, year=1405, month=2)` → شمارهٔ `PR-<سال>-NNNN`،
`period_start`/`period_end` از تقویم جلالی. برای هر (سال، ماه) فقط یک دوره
(قید یکتایی `pay_runs(year, month)`).

## محاسبه

`payroll.calculate(ctx, run_id)`:

1. دورهٔ تأییدشده/ثبت‌شده قابل محاسبهٔ مجدد نیست.
2. برای هر کارمند فعال با وضعیت «شاغل»: قرارداد معتبر همان دوره مبنای حقوق است؛
   در نبود قرارداد، `employee.base_salary`.
3. کارمند بدون حقوق پایه **حذف نمی‌شود**؛ در `CalculationSummary.skipped` با پیام
   فارسی گزارش می‌شود.
4. ورودی‌ها: خلاصهٔ حضور (روز کارکرد/غیبت/مرخصی)، ساعت اضافه‌کاری تأییدشده (عادی و
   تعطیل)، کمک‌هزینهٔ مأموریت تأییدشده، اقساط وام/مساعدهٔ سررسید همان ماه،
   مزایا و نرخ‌های نسخهٔ تنظیمات.
5. محاسبه در `pars_erp/payroll/engine.py` (توابع خالص، بدون دیتابیس و بدون Qt) انجام
   می‌شود و اقلام فیش در `pay_payslip_lines` ذخیره می‌شوند.
6. جمع‌های دوره (ناخالص، کسور، خالص، بیمه، مالیات) روی `pay_runs` به‌روز می‌شود.

## فرمول‌ها (قابل آزمون مستقل)

- `hourly_rate = base_salary ÷ base_hours_per_month`
- `overtime = hourly_rate × hours × factor` (تعطیل با ضریب جداگانه)
- مزایای مستمر = مسکن + خواربار + حق اولاد (تعداد فرزند × نرخ) + تأهل + سنوات + مستمر
- `gross = base + benefits + overtime + bonus (+ کمک‌هزینهٔ مأموریت)`
- مبنای بیمه = حقوق پایه + مزایای مستمر (سقف‌دار)؛ اضافه‌کاری و پاداش در آن نیست
- `taxable = gross − insurance_employee − tax_exempt`
- مالیات = پله‌ای روی `taxable` با پله‌های نسخهٔ تنظیمات
- کسور غیبت = روز غیبت × نرخ روز (از تنظیمات یا حقوق ÷ روز کاری ماه)
- `net = gross − (insurance + tax + absence + loan + advance + other)` و در پایان
  با `rounding_step` گرد می‌شود.

اگر نرخ بیمه یا پلهٔ مالیات در نسخه تعریف نشده باشد، مقدار **صفر** محاسبه و در
یادداشت فیش ثبت می‌شود («نرخ بیمه … تعریف نشده است») — عدد ساختگی تولید نمی‌شود.
