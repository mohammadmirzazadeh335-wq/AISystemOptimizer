# ساختار پایگاه‌دادهٔ فاز ۴ (۱۳ جدول `trs_*`)

مهاجرت: `src/pars_erp/migrations/versions/0004_phase4_treasury_core.py`
شناسهٔ مهاجرت: `4b7d1e5a9c30` (والد: `eedc1b9fc765`)

| جدول | نقش | کلیدهای یکتا / نکته |
|-------|-----|----------------------|
| `trs_bank_accounts` | حساب بانکی و حساب معین متناظر | `code` یکتا |
| `trs_cash_boxes` | صندوق نقدی | `code` یکتا |
| `trs_cash_box_users` | کاربران مجاز هر صندوق | `(cash_box_id, user_id)` |
| `trs_receipts` | اسناد دریافت | `number`، `idempotency_key` یکتا |
| `trs_payments` | اسناد پرداخت | `number`، `idempotency_key` یکتا |
| `trs_transfers` | انتقال بین منابع نقدی | `number`، `idempotency_key` یکتا |
| `trs_allocations` | تخصیص دریافت/پرداخت به فاکتور | `(voucher_kind, voucher_id, invoice_id)` |
| `trs_cheques` | چک دریافتی/صادره | `journal_id`، وضعیت |
| `trs_cheque_books` | دسته‌چک | `(bank_account_id, serial_no)` یکتا |
| `trs_cheque_events` | تاریخچهٔ تغییر وضعیت چک | کاربر، زمان، از/به |
| `trs_bank_statements` | سربرگ صورت‌حساب بانکی | وضعیت، دوره |
| `trs_bank_statement_lines` | سطرهای صورت‌حساب | وضعیت تطبیق، `journal_id` |
| `trs_planned_items` | تعهدات/اقلام برنامه‌ریزی‌شده | نوع، سرسید، انجام‌شده |

## ستون‌های مشترک

- `created_at` / `updated_at` (UTC، `datetime`)
- `created_by_id` / `updated_by_id` → `users.id`
- مبالغ: `Numeric(18, 2)` با `Decimal`. ارز خارجی: `currency_code`، `exchange_rate`،
  `base_amount`.
- ارجاع به سند حسابداری: `journal_id` → `journals.id` (**شناسه**، نه آبجکت).

## نمایه‌ها و محدودیت‌ها

- `status` در همهٔ اسناد نمایه‌گذاری شده تا گزارش‌ها و لیست‌های روزانه سریع بمانند.
- `(voucher_kind, voucher_id)` روی `trs_allocations` برای بازیابی سریع تخصیص‌ها.
- `trs_bank_statement_lines.statement_id` کلید خارجی با حذف آبشاری از سربرگ.
- حذف فیزیکی اسناد مالی ممنوع است؛ `void` با دلیل.

## یکپارچگی

| رابطه | قاعده |
|-------|-------|
| صندوق/بانک → حساب معین | هر حساب معین فقط برای یک منبع نقدی (`ConflictError` در سرویس) |
| چک → سند دریافت/پرداخت | `receipt_id` / `payment_id` |
| صورت‌حساب → سطرها | حذف سربرگ، سطرها را حذف می‌کند |
| سند خزانه → ژورنال | در همان تراکنش ساخته می‌شود |

## تغییرات در جداول فازهای قبل

- `posting_rules` با ۱۱ الگوی خزانه مقدار اولیه گرفت.
- `chart_of_accounts` کدهای `101007` و `201004` را اضافه کرد.
- `permissions` ۲۱ کلید جدید خزانه گرفت.

هیچ ستون یا جدول فازهای ۱–۳ حذف یا تغییر معنایی نشد.
