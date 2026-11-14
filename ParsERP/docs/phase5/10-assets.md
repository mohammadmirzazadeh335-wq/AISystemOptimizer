# دارایی ثابت: ثبت، انتقال، امانت و تعمیر

**مجوزها:** `assets.view` — `assets.register` (ثبت/ویرایش) — `assets.transfer`
(انتقال و امانت‌دار) — `assets.maintenance` (تعمیر)

## دسته‌های دارایی

`assets.create_category(ctx, CategoryInput(code=..., title_fa=..., kind=...,
asset_account_id=None, accumulated_account_id=None, expense_account_id=None,
default_useful_life_years=5, default_method="straight_line",
default_salvage_percent=0))`

- انواع استاندارد: زمین، ساختمان، ماشین‌آلات، تجهیزات، وسایل نقلیه، تجهیزات اداری،
  تجهیزات رایانه‌ای، اثاثیه، سایر.
- سه حساب (دارایی، استهلاک انباشته، هزینهٔ استهلاک) هر دسته قابل تعیین است؛ اگر خالی
  بماند از کدینگ استاندارد خوانده می‌شود (۱۰۲۰۰۱، ۱۰۲۰۰۳، ۵۰۲۰۰۵).
- این سه حساب در زمان **ثبت دارایی** روی خود دارایی کپی می‌شوند؛ تغییر بعدی دسته
  سابقهٔ استهلاک قبلی را بازنویسی نمی‌کند.

## ثبت دارایی

`assets.register(ctx, AssetInput(title_fa=..., category_id=..., serial_no=...,
purchase_date=..., in_service_date=..., supplier_detail_id=..., location=...,
custodian_employee_id=..., org_unit_id=..., purchase_price=..., related_costs=...,
initial_value=None, salvage_value=..., useful_life_months=..., method=...,
declining_rate=..., total_units=..., status=...))`

- `initial_value` اگر داده نشود = بهای خرید + هزینه‌های جانبی.
- قواعد: بهای تمام‌شده > ۰، ارزش اسقاط < بهای تمام‌شده، عمر مفید > ۰، روش معتبر.
- کد دارایی خودکار `AST-<سال>-NNNN` (پیشوند از تنظیمات `assets_code_prefix`)؛ کد
  دستی تکراری `ConflictError` می‌دهد.
- با ثبت، یک ردیف سابقه (`kind = status`) با وضعیت اولیه نوشته می‌شود.

## ویرایش و تغییر سیاست استهلاک

- `assets.update(...)` فقط فیلدهای توصیفی و وضعیت را تغییر می‌دهد. اگر بهای
  تمام‌شده/عمر مفید/روش عوض شود، خطای `ValidationError` هدایت می‌کند به مسیر زیر.
- گذار وضعیت محدود است (`ASSET_TRANSITIONS`): از «فروخته‌شده/کنارگذاشته/حذف» به
  هیچ وضعیت دیگری نمی‌شود.
- `assets.change_depreciation_policy(ctx, asset_id, method=..., useful_life_months=...,
  declining_rate=..., effective_date=..., note=...)` — **یادداشت دلیل الزامی**؛ یک
  ردیف سابقه (`kind = policy`) با مقدار قبلی/جدید و تاریخ اجرا ثبت می‌شود و رویداد
  `policy_change` در `audit` می‌نشیند.

## انتقال، امانت‌دار و محل

`assets.transfer(ctx, asset_id, to_org_unit_id=..., to_employee_id=..., location=...,
movement_date=..., note=...)`

- برای هر تغییر، یک ردیف `ast_movements` با نوع (`transfer`، `custodian`، `location`)،
  مقدار قبلی/جدید، کاربر و تاریخ ثبت می‌شود.
- دارایی واگذارشده قابل انتقال نیست (`ConflictError`).
- `assets.history(ctx, asset_id)` همهٔ جابه‌جایی‌ها را از نو به قدیم برمی‌گرداند.

## تعمیر و نگهداری

`assets.add_maintenance(ctx, MaintenanceInput(asset_id=..., kind="repair"|"service",
service_date=..., cost=..., contractor=..., consumables=..., description=...,
next_service_date=..., attachment_path=..., is_periodic=...))`

- برای دارایی واگذارشده ثبت نمی‌شود.
- گزارش هزینهٔ هر دارایی: `asset_reports.maintenance(ctx)` (تعداد خدمت، جمع هزینه،
  سرویس بعدی) و `asset_reports.maintenance_detail(ctx, asset_id)`.

## ارزش دفتری

`accumulated` و `book_value` هر دارایی از **سطرهای استهلاک ثبت‌شده** محاسبه می‌شود
(`ast_depreciation_lines` با دورهٔ `posted`)، نه از یک عدد ذخیره‌شده؛ بنابراین ویرایش
دستی نمی‌تواند ارزش دفتری را جعل کند.
