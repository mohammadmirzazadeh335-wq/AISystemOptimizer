# ۲) دریافت و پرداخت

## انواع سند خزانه

| سند | جدول | سرویس | شماره‌گذاری |
|-----|------|-------|--------------|
| دریافت | `trs_receipts` | `VoucherService.create_receipt` | `RCV-{سال}-{شماره}` |
| پرداخت | `trs_payments` | `VoucherService.create_payment` | `PAY-{سال}-{شماره}` |
| انتقال | `trs_transfers` | `VoucherService.create_transfer` | `TRF-{سال}-{شماره}` |

شماره‌ها با `next_receipt_number` / `next_payment_number` بر اساس سال سند تولید می‌شوند.

## روش‌های پرداخت (`method`)

- `METHOD_CASH` — نقد (نیازمند صندوق)
- `METHOD_TRANSFER` — حواله/انتقال بانکی (نیازمند حساب بانکی)
- `METHOD_CHEQUE` — چک (نیازمند چک ثبت‌شده در `trs_cheques`)
- روش‌های دیگر در `pars_erp/treasury/constants.py` تعریف شده‌اند (کارت‌خوان، پایا، ساتنا و…).

## نوع طرف حساب (`receipt_type` / `payment_type`)

دریافت از مشتری (`RECEIPT_CUSTOMER`)، دریافت متفرقه (`RECEIPT_CUSTOM`)،
پرداخت به تأمین‌کننده (`PAYMENT_SUPPLIER`)، پرداخت متفرقه (`PAYMENT_CUSTOM`) و
انواع حقوق/هزینه. برای طرف‌های مشخص، `payer_detail_id` / `payee_detail_id` باید
به حساب معین همان شخص اشاره کند؛ در غیر این صورت `ValidationError` صادر می‌شود.

## چرخهٔ وضعیت

```
draft ──approve──> approved ──post──> posted
   │                   │                 │
   └────void───────────┴────void─────────┘  (void_reason الزامی)
```

- `approve_receipt` / `approve_payment`: نیازمند `vouchers.approve`.
- `post_receipt` / `post_payment`: نیازمند `vouchers.post`؛ سند حسابداری را می‌سازد،
  ماندهٔ صندوق و اسناد مرتبط را به‌روزرسانی می‌کند و `posted_at/posted_by_id` را می‌نویسد.
- `void_receipt` / `void_payment`: نیازمند دلیل؛ سند حسابداری با `reverse_journal` برگشت
  می‌خورد (ابطال، حذف نیست).
- سند `posted` قابل ویرایش نیست؛ `_assert_editable` در `voucher_service.py`.

## تسویه با فاکتور

`trs_allocations` تخصیص مبلغ دریافت/پرداخت به یک یا چند فاکتور است:

- ورودی‌ها: `invoice_id` و `amount` برای هر سطر.
- `open_invoices(ctx, kind)` فاکتورهای تسویه‌نشده را با مانده برمی‌گرداند.
- `allocations_of(ctx, kind, voucher_id)` تخصیص‌های ثبت‌شده را نشان می‌دهد.
- جمع تخصیص‌ها نمی‌تواند از مبلغ سند بیشتر شود.

## کنترل تکرار (idempotency)

هر دریافت/پرداخت/انتقال یک `idempotency_key` یکتا دارد؛ مثلاً
`receipt:{id}:journal` برای سند حسابداری. ثبت دوبارهٔ همان کلید
`ConflictError` می‌دهد؛ بنابراین دوبار کلیک یا تلاش مجدد شبکه سند دوم نمی‌سازد.

## پیوست و ارجاع

`reference_no`، `tracking_no` (شمارهٔ پیگیری بانکی) و `attachment_path` برای
نگه‌داری مستندات پشتیبان در دسترس‌اند.

## صفحه‌های مرتبط

`receipt_cash`، `receipt_customer`، `payment_cash`، `payment_supplier`
در `src/pars_erp/ui/pages/treasury/vouchers_page.py`.
