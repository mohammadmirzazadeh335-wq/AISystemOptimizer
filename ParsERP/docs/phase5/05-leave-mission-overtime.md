# مرخصی، مأموریت و اضافه‌کاری

**مجوزها:** `hr.leave.request` (ثبت درخواست) — `hr.leave.approve` (تأیید مرخصی و
تنظیم مانده) — `hr.overtime.approve` (تأیید اضافه‌کاری و مأموریت)

## انواع مرخصی

`attendance.create_leave_type(ctx, LeaveTypeInput(code=..., title_fa=..., kind=...,
is_paid=True, requires_approval=True, annual_quota_days=26, max_hours=None,
counts_in_balance=True))`

انواع: استحقاقی، استعلاجی، بدون حقوق، ساعتی، اضطراری و سفارشی.

## درخواست مرخصی

`attendance.request_leave(ctx, LeaveInput(employee_id=..., leave_type_id=...,
date_from=..., date_to=..., hours=0, reason=...))`

- تعداد روز از **روزهای کاری** بین دو تاریخ (بر اساس `working_days` تنظیمات) محاسبه
  می‌شود، نه تفاضل تقویمی.
- مرخصی ساعتی: روز = ساعت ÷ ۸ و سقف `max_hours` هر نوع رعایت می‌شود.
- درخواست هم‌پوشان با درخواست «ثبت‌شده» یا «تأییدشدهٔ» همان کارمند رد می‌شود.
- شمارهٔ درخواست: `LV-<سال جلالی>-NNNN`؛ وضعیت اولیه «ثبت‌شده».

## تأیید / رد / لغو

- `approve_leave`: ماندهٔ سال (سهمیه + انتقالی + تعدیل − استفاده‌شده) بررسی می‌شود؛
  اگر کافی نباشد خطای `ValidationError` با مانده و درخواست در پیام. با تأیید،
  `used_days` افزایش می‌یابد و برای هر روز کاری، رکورد حضور با وضعیت «مرخصی» ثبت
  یا به‌روز می‌شود.
- `reject_leave`: **دلیل الزامی**؛ مانده دست نمی‌خورد.
- `cancel_leave`: مرخصی تأییدشده، مانده را برمی‌گرداند و رکوردهای حضور مرخصی را پاک می‌کند.
- مانده هر کارمند/نوع/سال یک ردیف یکتاست (`hr_leave_balances`)؛ تغییر مانده فقط از
  مسیر «تنظیم سهمیه» (`set_balance`) با مجوز و ثبت `audit` انجام می‌شود.

## مأموریت

`create_mission(ctx, MissionInput(employee_id=..., destination=..., date_from=...,
date_to=..., purpose=..., transport=..., cost=..., allowance=...))`
سپس `decide_mission(ctx, id, approve=True/False, note=...)`.

با تأیید، روزهای مأموریت در حضور ثبت می‌شود و **کمک‌هزینهٔ مأموریت** به محاسبهٔ
حقوق همان دوره منتقل می‌شود (`approved_mission_allowance`).

## اضافه‌کاری

`request_overtime(ctx, OvertimeInput(employee_id=..., work_date=..., hours=2,
is_holiday=False, reason=...))` → `decide_overtime(ctx, id, approve=...)`

- ساعت باید بزرگ‌تر از صفر باشد؛ برای هر کارمند در هر روز یک درخواست.
- فقط اضافه‌کاری **تأییدشده** وارد حقوق می‌شود و ساعت عادی و تعطیل جدا برمی‌گردد
  (`approved_overtime_hours`) تا با ضرایب مختلف محاسبه شود.

> هیچ‌کدام از این سه جریان بدون تأیید، اثری روی حقوق ندارند؛ این قاعده در آزمون‌ها
> بررسی شده است.
