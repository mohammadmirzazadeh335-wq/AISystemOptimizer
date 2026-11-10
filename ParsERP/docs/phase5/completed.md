# کارهای انجام‌شده در فاز ۵

## مدل داده و مهاجرت

- ۲۹ جدول جدید (`hr_*` ۱۲، `pay_*` ۱۰، `ast_*` ۷) در `db/models/{hr,payroll,assets}.py`.
- مهاجرت `9c3f5ad21e70_phase_5_hr_payroll_and_fixed_assets.py` (upgrade/downgrade/upgrade
  آزمایش‌شده) و مهاجرت دادهٔ `b7d21f4c9e10_phase_5_chart_accounts.py`.
- پشتیبان پیش از کار: `backups/pars_erp_phase5_pre_work_20261110_1530.tgz`.

## قواعد و کد خالص

- `pars_erp/hr/constants.py`, `pars_erp/payroll/constants.py`,
  `pars_erp/assets/constants.py` (انواع، وضعیت‌ها، گذارهای مجاز، عنوان‌های فارسی).
- `pars_erp/payroll/engine.py` — موتور محاسبهٔ حقوق، بدون دیتابیس و بدون Qt.
- `pars_erp/assets/depreciation.py` — فرمول‌های استهلاک (سه روش) و تقویم دوره.

## لایهٔ سرویس (۱۰ ماژول جدید)

| ماژول | مسئولیت |
|--------|----------|
| `services/hr_common.py` | کمک‌تابع‌های مشترک (پول، روز کاری، بازهٔ ماه جلالی، ساعت، ماسک) |
| `services/hr_service.py` | ساختار سازمانی، پروندهٔ کارکنان، سابقه، قراردادها |
| `services/attendance_service.py` | شیفت، حضور و غیاب، ورود فایل، مرخصی، مأموریت، اضافه‌کاری |
| `services/payroll_service.py` | نسخه‌های تنظیمات، دوره‌ها، محاسبه، فیش، تأیید، سند حقوق |
| `services/loans_service.py` | وام/مساعده، اقساط، پرداخت خزانه، تسویه |
| `services/payroll_payment_service.py` | دستهٔ پرداخت، فایل بانکی، پرداخت، ناموفق، تلاش مجدد |
| `services/assets_service.py` | دسته، دارایی، انتقال، تعمیر، فروش/کنارگذاری |
| `services/depreciation_service.py` | پیش‌نمایش، محاسبه، تأیید، ثبت و حذف دورهٔ استهلاک |
| `services/hr_report_service.py` | هشت گزارش منابع انسانی |
| `services/payroll_report_service.py` | شش گزارش حقوق و بدهی کارکنان |
| `services/asset_report_service.py` | هشت گزارش دارایی ثابت |

## یکپارچه‌سازی

- `services/context.py`: `hr`, `attendance`, `payroll`, `loans`, `payroll_payments`,
  `hr_reports`, `payroll_reports`, `assets`, `depreciation`, `asset_reports` در
  `AppServices` و `build_services` (ساخت موفق در آزمون‌ها تأیید شد).
- `services/voucher_service.py`: افزودن `create_receipt_in_session` /
  `post_receipt_in_session` و اصلاح `post_payment_in_session` (تأیید پیش از ثبت).
- `services/posting_service.py`: الگوی جدید `payroll.salary` و منبع `salary_expense`.
- `services/commerce_common.py`: `next_document_number(..., column="code")`.
- `services/accounting_setup_service.py`: هفت حساب جدید در کدینگ استاندارد.
- `security/permissions.py`: ۲۱ مجوز جدید، دو نقش جدید، به‌روزرسانی نقش‌های قبلی.
- `services/settings_service.py`: ۱۷ تنظیم جدید در سه گروه `hr`, `payroll`, `assets`
  (مجموع ۴۵ تنظیم).

## آزمون

- ۱۱۷ آزمون جدید در هفت فایل؛ کل مجموعه **۵۷۵ موفق** (گزارش کامل در
  [`test-report.md`](test-report.md)).
- ۱۳ باگ واقعی که این آزمون‌ها آشکار کردند، اصلاح شد (همان سند، بخش «باگ‌ها»).

## مستندات

- ۱۵ سند این پوشه (راهنمای کارکنان، ساختار سازمانی، قرارداد، حضور، مرخصی/مأموریت/
  اضافه‌کاری، تنظیمات حقوق، فیش و سند، پرداخت حقوق، وام، دارایی، استهلاک، فروش و
  کنارگذاری، گزارش‌ها، مجوزها/امنیت، ساختار داده، گزارش آزمون، این فهرست و
  [`remaining.md`](remaining.md)).
