# 7. شبیه‌سازی حرکت و کنترل با موس

## 7.1 دو قابلیت متفاوت

| قابلیت | نحوه فعال‌سازی | کاربرد |
|--------|---------------|--------|
| **Drag با موس** | انتخاب قطعه متحرک → Drag در جهت مجاز | تست سریع، بررسی Limit، احساس مکانیکی |
| **Motion Study** | Tab Motion Study → Play | انیمیشن خودکار، بررسی مسیر کامل، Collision |

هر دو پیاده‌سازی شده‌اند — یکی جایگزین دیگری نیست.

## 7.2 تست Drag با موس

### پیش‌نیاز

- `Main_Assembly.SLDASM` را در SolidWorks 2025 باز کنید.
- مطمئن شوید `Interference Detection` خاموش نیست (برای حس برخورد).
- از حالت `Assembly → Move Component` یا مستقیم Drag استفاده کنید.

### سناریوهای Drag

| # | قطعه | جهت Drag | محدوده مجاز | انتظار |
|---|------|----------|-------------|--------|
| 1 | `X_Carriage` | چپ↔راست (X) | 0–480mm | حرکت روان روی 2 ریل، توقف نرم در انتها |
| 2 | `Z_Carriage` | بالا↔پایین (Z) | 0–2120mm | حرکت عمودی، همگام دو طرف |
| 3 | `Transfer_Tray` | جلو↔عقب (Y) | 0–450mm | ورود به عمق، بدون گیر |
| 4 | `Pulley_GT2_20T` | چرخش | 360° آزاد | چرخش پولی، تسمه (در صورت Belt Mate) همگام |
| 5 | `Roller_Drive` | چرخش | 360° | غلتک نوار نقاله |
| 6 | X+Z هم‌زمان | X و Z را یکی‌یکی Drag کنید | تمام ترکیب‌ها | سینی با بار فرضی 380×400×350 نباید به سازه بخورد |

> **نکته:** پس از Drag، از `Tools → Mate Controller` می‌توانید مقدار دقیق Distance Mateها را ببینید و تنظیم کنید.

### Mate Controller

برای کنترل دقیق‌تر، **Mate Controller** فعال شده:

```
Mate Controller
├── X_Position (LimitDistance X: 0–480mm)
├── Z_Position (LimitDistance Z: 0–2120mm)
└── Y_Position (LimitDistance Y: 0–450mm)
```

- هر Slider را حرکت دهید → گنتری/سینی به موقعیت دقیق می‌رود.
- دکمه `Add Position` برای ذخیره موقعیت هر خانه استفاده شده (10 Position برای 10 خانه + Home).

## 7.3 Motion Study — سناریوها

### لیست Motion Studyها

| # | نام Study | مدت | محورها | توضیح |
|---|-----------|-----|--------|-------|
| 1 | `Study_X_Sweep` | 4 sec | X: 0→480→0 | جاروی کامل X |
| 2 | `Study_Z_Sweep` | 10 sec | Z: 0→2120→0 | جاروی کامل Z |
| 3 | `Study_XZ_Grid` | 20 sec | X و Z پله‌ای | بازدید تمام 10 خانه |
| 4 | `Study_Deposit_06` | 12 sec | X→601.5, Z→1003, Y→450, Y→0, Home | چرخه دریافت به خانه 06 |
| 5 | `Study_Retrieval_06` | 12 sec | Home→X,Z→Y→450→Y→0→Home→Conveyor | چرخه تحویل از خانه 06 |
| 6 | `Study_Full_Cycle_All` | 60 sec | Sequence تمام 10 خانه | تست پوشش کامل |

### جزئیات Study_Deposit_06

| زمان | عمل | موتور |
|------|-----|-------|
| 0.0–0.5s | آماده‌سازی (سینی Y=0) | — |
| 0.5–3.0s | حرکت X: 0→601.5mm | Linear Motor X, v=300mm/s |
| 0.5–6.0s | حرکت Z: 0→1003mm | Linear Motor Z, v=200mm/s |
| 6.0–8.0s | حرکت Y: 0→450mm | Linear Motor Y, v=150mm/s |
| 8.0–8.5s | مکث (تخلیه) | — |
| 8.5–10.5s | برگشت Y: 450→0 | Linear Motor Y |
| 10.5–12.0s | برگشت X,Z به Home | — |

> موتورها با پروفیل **Trapezoidal** (شتاب 500mm/s²، سرعت ثابت، کاهش سرعت) تعریف شده‌اند تا حرکت واقعی باشد.

### تنظیمات Motion Study

- **Type:** Motion Analysis (برای در نظر گرفتن جرم و برخورد) یا Animation (برای نمایش سریع).
- **Frame Rate:** 30 fps
- **Gravity:** روشن (Z منفی) برای تست سقوط آزاد سینی (اختیاری).
- **Contact:** بین سینی و امانت (Contact Set) برای شبیه‌سازی اصطکاک.
- **Collision:** فعال، با Exclude تماس‌های مجاز.

## 7.4 موتورهای حرکتی

| موتور | نوع SolidWorks | محل | پروفیل |
|-------|---------------|-----|--------|
| `Motor_X` | Linear Motor | X_Carriage ↔ Frame | Distance 0–480mm, v=300mm/s |
| `Motor_Z` | Linear Motor | Z_Carriage ↔ Bottom_Plate | Distance 0–2120mm, v=200mm/s |
| `Motor_Y` | Linear Motor | Transfer_Tray ↔ Z_Carriage | Distance 0–450mm, v=150mm/s |
| `Motor_Pulley_X` | Rotary Motor | Pulley_GT2_20T | 360°/sec (اختیاری، برای نمایش تسمه) |
| `Motor_Roller` | Rotary Motor | Roller_Drive | 60 RPM |

> اگر Linear Motor در نسخه SolidWorks در دسترس نباشد، از **Distance Mate با Key Frame** استفاده شده: در هر Key Frame، مقدار Distance تغییر می‌کند و SolidWorks بین آن‌ها Interpolate می‌کند.

## 7.5 تسمه — محدودیت و راه‌حل

| موضوع | محدودیت SolidWorks | راه‌حل پروژه |
|-------|-------------------|--------------|
| حرکت واقعی تسمه بسته با موس | تسمه به‌صورت Part ثابت است، با موس حرکت نمی‌کند | پولی‌ها Concentric آزادند و با موس می‌چرخند — این حرکت معادل است |
| Belt/Chain Mate | فقط در بعضی نسخه‌ها و با هندسه خاص کار می‌کند | Belt/Chain Mate تعریف شده اما Fallback نیز دارد: مسیر تسمه شماتیک + Limit Mate برای کالسکه |
| نمایش کشیدگی تسمه | SolidWorks کشیدگی را شبیه‌سازی نمی‌کند | Tensioner به‌صورت Distance Mate قابل تنظیم مدل شده |

> این محدودیت در [Validation/MotionValidation.md](../Validation/MotionValidation.md) مستند شده و به‌عنوان نقص پذیرفته نشده — بلکه ویژگی SolidWorks است.

## 7.6 خروجی Motion Study

- هر Study به‌صورت **AVI** قابل Export است (File → Save Animation).
- گراف Position/Velocity/Acceleration برای هر محور قابل نمایش (Results and Plots).
- برای ارائه، Study_Full_Cycle_All به‌صورت ویدیو 60 ثانیه‌ای توصیه می‌شود.
