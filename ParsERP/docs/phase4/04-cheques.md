# ۴) چک‌ها و دسته‌چک

## دسته‌چک (`trs_cheque_books`)

`ChequeService.create_book` / `set_book_status` — سریال دسته، شمارهٔ اولین و آخرین برگ،
بانک، تاریخ دریافت و وضعیت. یکتایی `(bank_account_id, serial_no)` تضمین می‌شود.

وضعیت دسته‌ها: `BOOK_OPEN`، `BOOK_FINISHED`، `BOOK_CANCELLED`
(به‌کاررفته/باطل/آزاد از `ChequeBookRow` خوانده می‌شود).

## چک (`trs_cheques`)

جهت چک (`direction`): **دریافتی** از مشتری یا **صادره** به تأمین‌کننده.

فیلدها: شماره، دسته‌چک، بانک/شعبه/حساب، صاحب چک، مبلغ، ارز، نرخ، مبلغ پایه،
تاریخ صدور، تاریخ سرسید، طرف حساب، فاکتور مرتبط، صندوق/حساب، توضیحات، پیوست،
وضعیت، سند حسابداری.

## چرخهٔ وضعیت چک دریافتی

```
received ──> in_safe ──> deposited ──> collected
   │            │            │
   ├──> spent ──┴──> transferred
   └──> cancelled        (bounced از deposited/collected)
```

## چرخهٔ وضعیت چک صادره

```
draft ──> issued ──> delivered ──> paid
                        │
                        └──> returned
```

گذارهای مجاز در `CHEQUE_TRANSITIONS` (`treasury/constants.py`) تعریف شده‌اند؛
هر گذار نامعتبر `ValidationError` می‌دهد. `validate_status` در `treasury_common.py`
این کنترل را انجام می‌دهد.

## قواعد مهم

1. `change_status(ctx, cheque_id, new_status, ...)` برای وصول چک دریافتی، صندوق یا
   حساب بانکی مقصد را الزامی می‌کند (`cash_box_id` یا `bank_account_id`).
2. هر تغییر وضعیت یک ردیف در `trs_cheque_events` ثبت می‌کند
   (وضعیت مبدأ، مقصد، تاریخ، کاربر، توضیح)؛ `history(ctx, cheque_id)` آن را برمی‌گرداند.
3. تغییر وضعیت‌هایی که پول واقعی جابه‌جا می‌کنند سند حسابداری می‌سازند با کلید
   `cheque:{id}:{action}` — ثبت دوباره ممکن نیست.
4. `due_soon(ctx, days)` چک‌های نزدیک سرسید را برمی‌گرداند؛ تعداد روز هشدار از
   تنظیمات `treasury_cheque_alert_days` (پیش‌فرض ۷) خوانده می‌شود.
5. چک‌های کهنه (گذشته از سرسید و بی‌حرکت) با `treasury_stale_cheque_days`
   (پیش‌فرض ۳۰) شناسایی می‌شوند.
6. `cancel(ctx, cheque_id, reason)` نیازمند `cheques.cancel` و دلیل است.
7. `mark_voiced` ثبت «اطلاع به صاحب چک» را نگه می‌دارد.

## صفحه‌های مرتبط

- `cheque_received` / `cheque_issued` → `cheques_page.py`
- `cheque_books` → دسته‌چک‌ها
- `cheque_manage` → تغییر وضعیت، ابطال و تاریخچهٔ چک
