# مجوزها، نقش‌ها و امنیت فاز ۵

## مجوزهای جدید

کاتالوگ از ۱۱۷ به **۱۳۸** مجوز در **۲۴** بخش رسید. بخش‌های جدید: `hr` (۱۳)،
`payroll` (۹)، `assets` (۹).

| بخش | مجوزها |
|------|---------|
| `hr` | `hr.employees.view`, `hr.employees.create`, `hr.employees.edit`, `hr.employees.sensitive`, `hr.contracts.manage`, `hr.org.edit`, `hr.attendance.record`, `hr.attendance.amend`, `hr.leave.request`, `hr.leave.approve`, `hr.overtime.approve`, `hr.reports`, `hr.print` |
| `payroll` | `payroll.view`, `payroll.settings`, `payroll.calculate`, `payroll.approve`, `payroll.pay`, `payroll.payslip.view`, `payroll.loans.manage`, `payroll.reports`, `payroll.print` |
| `assets` | `assets.view`, `assets.register`, `assets.transfer`, `assets.dispose`, `assets.depreciate`, `assets.post_depreciation`, `assets.maintenance`, `assets.reports`, `assets.print` |

## نقش‌های جدید

- `hr_manager` — کارکنان، قرارداد، حضور و غیاب، مرخصی، اضافه‌کاری و گزارش‌های منابع
  انسانی (بدون تنظیمات حقوق و بدون پرداخت).
- `asset_keeper` — ثبت/انتقال/تعمیر دارایی، محاسبهٔ استهلاک و گزارش‌های دارایی
  (بدون ثبت نهایی استهلاک و بدون فروش، که به `assets.dispose` و
  `assets.post_depreciation` نیاز دارد).

نقش‌های قبلی (admin, chief_accountant, accountant, viewer, treasurer, salesperson,
storekeeper) مجوزهای مرتبط جدید را به‌صورت افزودنی گرفتند؛ هیچ مجوزی از نقش‌ها
حذف نشد (قاعدهٔ `_apply_template_permissions`).

## کنترل دسترسی در کجا اعمال می‌شود

- **لایهٔ سرویس**: هر متد عمومی با `require_permission(...)` شروع می‌شود؛ فراخوانی
  مستقیم سرویس (تست، اسکریپت) هم بدون مجوز رد می‌شود
  (`PermissionDeniedError`).
- **پایگاه‌داده**: قیدهای یکتایی و کلیدهای خارجی، ثبت تکراری/ناسازگار را حتی در
  صورت خطای برنامه رد می‌کنند.
- **رابط کاربری** (در فاز UI): فقط دکمه‌ها را پنهان/غیرفعال می‌کند؛ مبنای امنیت نیست.

## دادهٔ حساس

- کد ملی، حقوق پایه و اطلاعات بانکی فقط با `hr.employees.sensitive` کامل دیده
  می‌شوند؛ در غیر این صورت ماسک می‌شوند (کنترل در `_employee_row`).
- گزارش فهرست کارکنان به‌صورت پیش‌فرض این ستون‌ها را ندارد.
- فیش حقوقی (`payroll.payslip.view`) از فهرست حقوق (`payroll.view`) جدا شده است.

## ثبت رویداد (Audit)

عملیات زیر در `audit` با کاربر، زمان و جزئیات ثبت می‌شوند:
ایجاد/ویرایش کارمند، پایان همکاری، تغییر واحد (گروهی)، ثبت/تمدید/اصلاح/خاتمهٔ
قرارداد، تنظیم شیفت، ثبت/اصلاح/ورود فایل حضور، درخواست/تأیید/رد/لغو مرخصی،
تنظیم مانده، مأموریت و اضافه‌کاری، نسخه‌های تنظیمات حقوق، دورهٔ حقوق
(ایجاد/محاسبه/تأیید/ثبت/لغو)، دستهٔ پرداخت (ایجاد/پرداخت/ناموفق/تلاش مجدد)،
وام (ایجاد/تأیید/رد/پرداخت/تسویه/لغو)، دارایی (ثبت/ویرایش/انتقال/تعمیر/واگذاری/
تغییر سیاست) و دورهٔ استهلاک (محاسبه/تأیید/ثبت/حذف).

## تراکنش و جلوگیری از تکرار

- پرداخت حقوق، پرداخت وام، فروش دارایی و ثبت استهلاک همگی **در یک تراکنش** با سند
  خزانه/دفتر روزنامه انجام می‌شوند؛ شکست هر مرحله، کل عملیات را برمی‌گرداند.
- کلیدهای idempotency: `payrun:<id>:journal`، `paybatch:<id>:payment`،
  `loan:<id>:payment`، `asset:<id>:sale`، `asset:<id>:disposal`،
  `depreciation:<run_id>:journal`.
- قیدهای یکتایی: `pay_runs(year, month)`، `pay_payslips(run_id, employee_id)`،
  `pay_batch_items(payslip_id)`، `pay_loan_installments(loan_id, seq)`،
  `ast_depreciation_lines(asset_id, year, month)`، `ast_disposals(asset_id)`،
  `hr_attendance(employee_id, work_date)`، `hr_leave_balances(employee, type, year)`.
