# حضور و غیاب و شیفت

**مجوزها:** `hr.attendance.record` (ثبت) — `hr.attendance.amend` (اصلاح) —
`hr.employees.view` (مشاهده)

## شیفت‌ها

`attendance.create_shift(ctx, ShiftInput(code=..., title_fa=..., kind=...,
start_time="08:00", end_time="17:00", break_minutes=60, grace_minutes=10,
working_days="0,1,2,3,4", is_night=False))`

- انواع: صبح، عصر، شب، گردشی، سفارشی.
- `working_days` ایندکس روزهای هفته به مبنای شنبه=۰ است و به متن فارسی هم تبدیل می‌شود.
- ساعت شروع و پایان نباید یکسان باشند (شیفت صفر/۲۴ ساعته مبهم است و رد می‌شود).
- اختصاص شیفت به کارمند: `attendance.assign_shift(ctx, employee_id=..., shift_id=...,
  from_date=...)`؛ در نبود اختصاص، شیفت پیش‌فرض/تنظیمات استفاده می‌شود.

## ثبت حضور

`attendance.record(ctx, AttendanceInput(employee_id=..., work_date=...,
check_in="08:05", check_out="17:00", shift_id=..., status=None, note=...))`

مقادیر محاسبه‌شده:

- `worked_minutes` = فاصلهٔ ورود تا خروج منهای استراحت شیفت (پشتیبانی از شیفت شبانه
  که از نیمه‌شب می‌گذرد).
- `late_minutes` = دیرکرد نسبت به شروع شیفت منهای مهلت مجاز (`grace_minutes`).
- `early_leave_minutes` = تعجیل در خروج نسبت به پایان شیفت.
- `overtime_minutes` = کارکرد بیش از مدت استاندارد شیفت.

> ورودِ **زودتر** از شروع شیفت هرگز به‌صورت تأخیر ۲۳ ساعته ثبت نمی‌شود؛ محاسبهٔ
> تأخیر/تعجیل با اختلاف علامت‌دار ساعت انجام می‌شود (این باگ در همین فاز اصلاح و
> آزمون شد).

- برای هر کارمند در هر روز فقط **یک** رکورد وجود دارد (قید یکتایی
  `(employee_id, work_date)`). ثبت دوباره خطای `ConflictError` می‌دهد.
- وضعیت‌ها: حاضر، تأخیر، غیبت، مرخصی، مأموریت، تعطیل.

## اصلاح

`attendance.amend(ctx, attendance_id, check_in=..., check_out=..., status=..., note=...)`

- مجوز جداگانه (`hr.attendance.amend`) و **یادداشت دلیل الزامی**.
- مقادیر قبلی و جدید در `audit` با نوع رویداد `amend` ثبت می‌شود.

## ورود فایل (Excel/CSV)

`attendance.import_rows(ctx, rows, source=...)`

هر سطر: `{"employee_code": "EMP-1001", "date": "1405/02/10", "in": "08:05",
"out": "17:10", "status": "حاضر"}`

- تاریخ شمسی یا میلادی پذیرفته می‌شود.
- ورود مجدد همان فایل، رکورد موجود را به‌روز می‌کند (idempotent) و رکورد تکراری نمی‌سازد.
- سطرهای نامعتبر (کد پرسنلی ناشناس، تاریخ بد) **کل فایل را رد نمی‌کنند**؛
  در `ImportResult.errors` با شمارهٔ سطر گزارش می‌شوند و بقیه ثبت می‌شوند.

## گزارش‌های روزانه/ماهانه

`attendance.attendance_summary(session, employee_id, start, end)` خروجی
`present_days، absent_days، leave_days، worked_hours، late_hours، overtime_hours`
می‌دهد و همان تابع ورودی محاسبهٔ حقوق است.
