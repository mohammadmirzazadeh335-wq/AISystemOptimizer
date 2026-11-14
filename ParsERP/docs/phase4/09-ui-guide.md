# ۹) راهنمای رابط کاربری خزانه (۱۹ صفحه)

همهٔ صفحه‌ها در گروه «خزانه‌داری» منوی کنار قرار دارند، راست‌به‌چپ هستند، تاریخ شمسی
و ارقام فارسی نشان می‌دهند، و در تم روشن و تاریک کار می‌کنند. هر صفحه سرصفحه
(`PageHeader`) با دکمه‌های عملیاتی، جدول قابل جست‌وجو/فیلتر و دکمهٔ «چاپ / PDF» و
«Excel» دارد.

| کلید ناوبری | عنوان | کلاس صفحه | فایل |
|-------------|-------|------------|------|
| `treasury_dashboard` | داشبورد خزانه‌داری | `TreasuryDashboardPage` | `dashboard_page.py` |
| `receipt_cash` | دریافت وجه | `VouchersPage` | `vouchers_page.py` |
| `payment_cash` | پرداخت وجه | `VouchersPage` | `vouchers_page.py` |
| `receipt_customer` | دریافت از مشتری | `VouchersPage` | `vouchers_page.py` |
| `payment_supplier` | پرداخت به تأمین‌کننده | `VouchersPage` | `vouchers_page.py` |
| `cheque_received` | دریافت چک (+صفحهٔ چک دریافتی) | `ReceivedChequesPage` | `cheques_page.py` |
| `cheque_issued` | پرداخت چک (+صفحهٔ چک صادره) | `IssuedChequesPage` | `cheques_page.py` |
| `cash_boxes` | صندوق‌ها | `CashBoxesPage` | `funds_page.py` |
| `bank_accounts` | حساب‌های بانکی | `BankAccountsPage` | `funds_page.py` |
| `treasury_transfer` | انتقال وجه | `TransfersPage` | `transfers_page.py` |
| `cheque_books` | دسته‌چک‌ها | `ChequeBooksPage` | `cheques_page.py` |
| `cheque_manage` | مدیریت چک‌ها | `ChequeManagePage` | `cheques_page.py` |
| `receivables` | اسناد دریافتنی | `ReceivableDocumentsPage` | `cheques_page.py` |
| `payables` | اسناد پرداختنی | `PayableDocumentsPage` | `cheques_page.py` |
| `settlements` | تسویهٔ فاکتورها | `SettlementsPage` | `settlements_page.py` |
| `reconciliation` | مغایرت‌گیری بانکی | `ReconciliationPage` | `reconciliation_page.py` |
| `fund_flow` | گردش وجوه | `FundFlowPage` | `reports_page.py` |
| `treasury_reports` | گزارش‌های خزانه | `TreasuryReportsPage` | `reports_page.py` |
| `treasury_settings` | تنظیمات خزانه | `TreasurySettingsPage` | `settings_page.py` |

## ثبت دریافت/پرداخت

1. صفحهٔ مربوطه را باز کنید؛ فهرست اسناد با فیلتر تاریخ و وضعیت نمایش داده می‌شود.
2. «سند جدید» → دیالوگ `VoucherDialog` با فیلدهای تاریخ، نوع، روش، منبع نقدی،
   طرف حساب، مبلغ/ارز، شمارهٔ پیگیری، شرح و تخصیص فاکتور.
3. دکمهٔ «ثبت» سند را در وضعیت `draft` ذخیره می‌کند؛ «تأیید» و «ثبت نهایی» از نوار
   عملیات صفحه انجام می‌شود (بر اساس مجوز).
4. مبالغ با `MoneyEdit` وارد می‌شوند: جداکنندهٔ هزارگان، دو رقم اعشار و اعتبارسنجی.

## انتقال وجه

صفحهٔ `treasury_transfer` مبدأ و مقصد را از کمبوهای منبع نقدی می‌گیرد، کارمزد را
اختیاری می‌پذیرد و پس از ثبت، سند را با کلید idempotency می‌سازد.

## مغایرت‌گیری

صفحهٔ `reconciliation` دو بخش دارد: فهرست صورت‌حساب‌ها (بالا) و سطرهای صورت‌حساب
انتخاب‌شده (پایین) با دکمه‌های «تطبیق خودکار»، «تطبیق دستی»، «لغو تطبیق»،
«نادیده‌گرفتن»، «سند اصلاحی» و «گزارش مغایرت».

## داشبورد

۸ کارت شاخص (جمع صندوق‌ها، جمع بانک‌ها، دریافت ماه، پرداخت ماه، چک در جریان،
چک نزدیک سرسید، خالص جریان، تعداد اسناد امروز)، جدول اسناد امروز، جدول چک‌های
نیازمند توجه و نمودار روند روزانه.

## نکته‌های پیاده‌سازی برای توسعه‌دهنده

- `DataTable` یک `QTableView` است؛ برای انتخاب برنامه‌ای یک ردیف از `setCurrentIndex`
  استفاده کنید (`selectRow` در چیدمان RTL در Qt 6.12 کار نمی‌کند).
- `MoneyEdit.amount` یک **property** است، نه متد.
- `CurrencyService.currency_choices()` فهرست ارزها را می‌دهد.
- دکمه‌های نوار عملیات با `setProperty("variant", "primary")` استایل می‌گیرند.
