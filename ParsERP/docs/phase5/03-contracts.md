# قرارداد کارکنان

**مجوز:** `hr.contracts.manage`

## ثبت قرارداد

`hr.create_contract(ctx, ContractInput(employee_id=..., contract_type=..., start_date=...,
end_date=..., base_salary=..., working_hours_weekly=44, working_days_weekly=6,
payment_terms=..., benefits=..., deductions=..., job_title=..., org_unit_id=...,
signed_date=..., file_path=..., notes=...))`

- شمارهٔ قرارداد خودکار: `CTR-<سال جلالی>-NNNN`.
- نوع قرارداد: ثابت، موقت، پیمانی، ساعتی، کارآموزی (فهرست در `hr/constants.py`).
- تاریخ پایان باید بعد از شروع باشد.
- پس از ثبت، `base_salary` و `job_title`/`org_unit_id` کارمند به‌روز می‌شود و
  یک ردیف سابقه (`kind = contract`) با شمارهٔ قرارداد ثبت می‌شود.
- قرارداد با تاریخ شروع ثبت می‌شود؛ وضعیت اولیه «فعال» است.

## تمدید

`hr.renew_contract(ctx, contract_id, ContractInput(...))`

- قرارداد قبلی «تمدیدشده» می‌شود و قرارداد جدید با `previous_contract_id` ساخته می‌شود.
- شروع قرارداد جدید باید بعد از شروع قبلی باشد؛ تمدید دوباره خطای `ConflictError` است.
- حقوق پایهٔ جدید روی کارمند اعمال می‌شود و سابقه ثبت می‌گردد.

## اصلاح

`hr.amend_contract(ctx, contract_id, base_salary=..., end_date=...,
working_hours_weekly=..., note=...)`

- **یادداشت دلیل الزامی است.**
- فقط قرارداد «فعال» یا «پیش‌نویس» اصلاح می‌شود؛ قرارداد خاتمه‌یافته/تمدیدشده نه.
- تغییر حقوق در سابقهٔ کارمند (`kind = salary`) با مقدار قبلی و جدید ثبت می‌شود و
  `amendment_note` قرارداد متن دلیل را نگه می‌دارد.
- تغییر خاتمه‌یافته‌ها فقط از مسیر قرارداد جدید (تمدید) انجام می‌شود.

## خاتمه

`hr.terminate_contract(ctx, contract_id, end_date=..., reason=...)` — وضعیت
«خاتمه‌یافته»؛ پایان دوباره خطا می‌دهد.

## فهرست‌ها و هشدار انقضا

- `list_contracts(ctx, employee_id=..., status=...)`
- `expiring_contracts(ctx, days=...)` — قراردادهای فعالی که تا `days` روز آینده
  (پیش‌فرض از تنظیمات `hr_contract_alert_days`) تمام می‌شوند؛ `days_to_expiry`
  در هر ردیف محاسبه شده است.
- `active_contract(ctx, employee_id, on_date=...)` — قراردادی که در آن تاریخ معتبر است
  (مبنای محاسبهٔ حقوق).
