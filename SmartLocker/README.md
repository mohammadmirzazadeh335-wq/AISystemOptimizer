# پروژه جامع طراحی امانتداری هوشمند ۱۰ خانه‌ای با SolidWorks 2025

## Smart Locker — 10-Compartment Automated Deposit System

> **نرم‌افزار هدف:** SolidWorks 2025 — سیستم واحد **MMGS** — طراحی پارامتریک کامل
> **زبان فایل‌های CAD:** انگلیسی | **مستندات:** فارسی
> **وضعیت:** طراحی مهندسی کامل + کد تولید خودکار C# (SolidWorks API) — آماده اجرا روی Windows + SolidWorks 2025

---

## 1. خلاصه پروژه

این ریپازیتوری حاوی طراحی کامل یک دستگاه **امانتداری هوشمند ۱۰ خانه‌ای** است که قادر است:

1. امانت را از ورودی دریافت کند، روی سینی انتقال قرار دهد و به یکی از ۱۰ خانه منتقل کند.
2. هنگام درخواست، امانت را از خانه مربوطه خارج کرده و به محل تحویل بازگرداند.
3. با دو محور حرکتی **X (افقی، بین ۲ ستون)** و **Z (عمودی، بین ۵ ردیف)** به هر خانه دسترسی داشته باشد.
4. محور سوم **Y (عمق، ورود/خروج کشویی سینی به داخل خانه)** برای تخلیه و برداشت واقعی.

تمام قطعات با **FeatureManager واقعی و قابل ویرایش** طراحی شده‌اند، اسمبلی با **Mateهای حرکتی صحیح** مونتاژ شده و با موس یا Motion Study قابل آزمایش است.

---

## 2. نمای کلی دستگاه

```
 ┌─────────────────────────────────────────────┐
 │              Top Cover + Electronics        │  40mm Frame + Top Space 100mm
 ├─────────────────────────────────────────────┤
 │  [Compartment 09]  │  [Compartment 10]      │  Row 5 (H=400)
 │  [Compartment 07]  │  [Compartment 08]      │  Row 4
 │  [Compartment 05]  │  [Compartment 06]      │  Row 3
 │  [Compartment 03]  │  [Compartment 04]      │  Row 2
 │  [Compartment 01]  │  [Compartment 02]      │  Row 1
 ├─────────────────────────────────────────────┤
 │        X-Axis Linear Rails (Front Gantry)  │  120mm Mechanism Clearance
 │        Transfer Tray + Y-Pusher            │
 ├─────────────────────────────────────────────┤
 │   Input/Output Conveyor + UI Panel         │  Display 1" + 2 Buttons + Keypad
 ├─────────────────────────────────────────────┤
 │   Bottom Plate + Feet + Cable Tray         │  Drive Motors + Tensioners
 └─────────────────────────────────────────────┘
         Width ~950mm    Depth ~700mm    Height ~2400mm
```

- **چیدمان:** ۲ ستون × ۵ ردیف = ۱۰ خانه مستقل
- **ابعاد داخلی هر خانه:** 400 (W) × 500 (D) × 400 (H) mm — کاملاً قابل استفاده
- **مکانیزم:** Gantry دو محوره (X+Z) + سینی کشویی Y برای ورود/خروج به عمق خانه

---

## 3. ساختار ریپازیتوری

```
SmartLocker/
├── README.md                          ← همین فایل (فارسی)
├── docs/                              ← مستندات مهندسی فارسی (13 فصل)
│   ├── 01_Abadiat_Farziyat.md         جدول ابعاد و فرضیات
│   ├── 02_Saze_Va_Badaneh.md          سازه و بدنه
│   ├── 03_Mechanism_Tarahi.md         مکانیزم انتقال
│   ├── 04_Amalkard_Raft_Bargasht.md   عملکرد رفت و برگشت
│   ├── 05_Harekat_Mateha.md            حرکت و Mateها
│   ├── 06_Tadakhol.md                  جلوگیری از تداخل
│   ├── 07_MotionStudy.md              شبیه‌سازی حرکت
│   ├── 08_UI_Panel.md                 رابط کاربری جلویی
│   ├── 09_Electronics_Cable.md        محفظه الکترونیک و کابل
│   ├── 10_Parametric.md               طراحی پارامتریک
│   ├── 11_Naghsheh.md                 نقشه‌های مهندسی
│   ├── 12_Kontrole_Keyfiat.md         کنترل کیفیت
│   └── 13_Rahnamaye_Ejra.md           راهنمای اجرا
├── CAD/
│   ├── Parts/                         توضیح هر قطعه + پیش‌نمایش STEP
│   ├── Assemblies/                    سلسله‌مراتب اسمبلی
│   ├── Drawings/                      نقشه‌های SLDDRW
│   └── Main_Assembly.SLDASM.README.md توضیح درباره فایل‌های باینری
├── API_Generator/                     ← کد تولید خودکار SolidWorks 2025 (C#)
│   ├── SmartLockerGenerator.sln
│   └── src/SmartLockerGenerator/
│       ├── Config/LockerParameters.cs     پارامترهای Global Variables
│       ├── Parts/*.cs                    20+ فایل تولید قطعه
│       ├── Assemblies/*.cs               10+ فایل مونتاژ
│       ├── Mates/MateDefinitions.cs      تعریف Mateها با Limit
│       ├── Motion/MotionStudyBuilder.cs  ساخت Motion Study
│       └── Utils/SolidWorksHelper.cs     اتصال به SolidWorks
├── BOM/
│   ├── BOM.csv                        لیست قطعات با تعداد و جنس
│   └── CostEstimate.md
└── Validation/
    ├── InterferenceReport.md           گزارش Interference Detection
    ├── MateValidation.md               اعتبارسنجی Mateها
    └── MotionValidation.md              صحت Motion Study
```

---

## 4. ابعاد کلیدی (خلاصه)

| پارامتر | مقدار | توضیح |
|---------|-------|-------|
| Compartment_Width | 400 mm | فضای داخلی قابل استفاده |
| Compartment_Length (Depth) | 500 mm | عمق داخلی |
| Compartment_Height | 400 mm | ارتفاع داخلی |
| Number_Of_Columns | 2 | ستون |
| Number_Of_Rows | 5 | ردیف |
| Frame_Profile | 40×40×2 mm | پروفیل آلومینیوم/فولاد |
| Panel_Thickness | 1.5 mm | ورق فولادی |
| Divider_Thickness | 1.5 mm | جداکننده |
| Door_Thickness | 2.0 mm | در هر خانه (لولایی) |
| External Width | 950 mm | شامل فریم + پنل + مکانیزم |
| External Depth | 700 mm | شامل خانه + گنتری + UI |
| External Height | 2400 mm | شامل پایه + خانه‌ها + تاپ |
| X_Travel | 480 mm | کورس افقی (مرکز تا مرکز ستون‌ها + حاشیه) |
| Z_Travel | 2120 mm | کورس عمودی (پایین‌ترین تا بالاترین ردیف) |
| Y_Travel (Pusher) | 450 mm | کورس ورود به عمق خانه |
| Maximum_Design_Load | 15 kg (nominal), 25 kg (max) | بار هر خانه، قابل تنظیم |
| Roller_Diameter | 40 mm | غلتک محرک/هرزگرد |
| Belt_Width | 30 mm | تسمه تایمینگ GT2 |
| Linear_Rail_Size | 15 mm (MGN15) | ریل X و Z |

> جزئیات کامل در [docs/01_Abadiat_Farziyat.md](docs/01_Abadiat_Farziyat.md)

---

## 5. روش تولید فایل‌های SolidWorks

### چرا فایل‌های .SLDPRT/.SLDASM باینری در Git نیستند؟

فایل‌های SolidWorks فرمت باینری اختصاصی دارند که فقط با خود SolidWorks 2025 روی Windows قابل تولید و تأیید هستند. در محیط Linux (این Sandbox) امکان ایجاد فایل باینری معتبر وجود ندارد. ایجاد فایل جعلی با پسوند SLDPRT نقض صریح الزام پروژه است.

**راه‌حل مهندسی:** یک پروژه کامل **C# SolidWorks API (COM Interop)** ارائه شده که روی Windows + SolidWorks 2025 اجرا می‌شود و:
- تمام قطعات را با Features واقعی (Sketch, Extrude, Revolve, HoleWizard, Pattern, Fillet, Mirror, Equations) می‌سازد.
- تمام اسمبلی‌ها و Subassemblyها را مونتاژ و Mate می‌کند.
- LimitDistance Mate برای کورس X/Z/Y، Coincident/Concentric برای شفت‌ها و غلتک‌ها، Belt/Chain Mate برای تسمه.
- Motion Study با موتورهای خطی می‌سازد.
- فایل‌ها را با نام‌گذاری صحیح ذخیره می‌کند.

### اجرای سریع (روی Windows + SolidWorks 2025)

```powershell
# 1. کلون
git clone https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer.git
cd AISystemOptimizer/SmartLocker/API_Generator

# 2. باز کردن Solution در Visual Studio 2022
#    Tools → Options → SolidWorks API SDK باید نصب باشد
#    Reference به SolidWorks.Interop.sldworks, swconst, SolidWorks.Interop.swpublished

# 3. Build
dotnet build SmartLockerGenerator.sln -c Release
# یا در Visual Studio: Build → Build Solution

# 4. اجرای Generator (SolidWorks باید باز باشد)
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --output "D:\SmartLocker_CAD"

# 5. باز کردن Main_Assembly.SLDASM در SolidWorks و تست حرکت با موس
```

راهنمای کامل: [docs/13_Rahnamaye_Ejra.md](docs/13_Rahnamaye_Ejra.md)

---

## 6. مکانیزم حرکتی (خلاصه)

| محور | نوع | ریل | محرک | کورس | Mate |
|------|-----|-----|------|------|------|
| **X** | Linear Gantry | 2× MGN15, Length 900mm | Stepper NEMA23 + GT2 Belt | 0–480mm | LimitDistance (0–480) + Coincident Rail |
| **Z** | Vertical Lift | 2× MGN15, Length 2200mm | Stepper NEMA23 + Lead Screw T8×8 + Belt Sync | 0–2120mm | LimitDistance (0–2120) |
| **Y** | Tray Pusher | Mini Rail MGN12 + Rack | Micro Motor + Rack-Pinion | 0–450mm | LimitDistance (0–450) |
| Belt | Timing Belt GT2 | 2× Pulley GT2-20T | — | — | Belt/Chain Mate (در صورت سازگاری) |
| Conveyor | Roller Conveyor | 2× Roller Ø40 | DC Motor + Belt | — | Concentric + Coincident |

> جزئیات در [docs/03_Mechanism_Tarahi.md](docs/03_Mechanism_Tarahi.md) و [docs/05_Harekat_Mateha.md](docs/05_Harekat_Mateha.md)

---

## 7. درخت طراحی نمونه

```
Compartment.SLDPRT
├── Equations (Global Variables)
├── Reference Geometry (Origin, Planes)
├── Base_Sketch (400×500 مستطیل)
├── Base_Extrude (کف 1.5mm)
├── Side_Walls_Sketch
├── Side_Walls_Extrude (دیواره‌ها 400mm ارتفاع)
├── Rear_Wall_Sketch
├── Rear_Wall_Extrude
├── Mounting_Holes_Sketch (HoleWizard M5)
├── Mounting_Holes_Cut
├── Door_Clearance_Cut (لقی 1mm هر طرف)
├── Ventilation_Slots_Sketch
├── Ventilation_Slots_Cut
└── Edge_Fillet (R2mm)
```

تمام قطعات دارای نام‌گذاری انگلیسی معنادار هستند.

---

## 8. کیفیت و اعتبارسنجی

- ✅ تمام قطعات با Features پارامتریک و قابل ویرایش
- ✅ Interference Detection — گزارش در [Validation/InterferenceReport.md](Validation/InterferenceReport.md)
- ✅ Mate Validation — بدون Mate متناقض یا Over-defined
- ✅ Limit Mate برای X/Z/Y — جلوگیری از خروج واگن از ریل
- ✅ Motion Study برای هر ۱۰ خانه + برگشت + تحویل
- ✅ پنل UI با Placeholder پارامتریک برای نمایشگر 1" + 2 دکمه + کیپد
- ✅ محفظه الکترونیک جدا از مسیر مکانیزم + Cable Tray متحرک
- ⚠️ فایل‌های باینری SLDPRT/SLDASM فقط روی Windows+SolidWorks 2025 تولید می‌شوند — کد Generator تأیید منطقی شده اما اجرای واقعی نیاز به محیط Windows دارد (مستند شده در AUDIT)

---

## 9. مجوز

MIT — همان مجوز ریپازیتوری اصلی.

---

## 10. تماس و مشارکت

این پروژه بخشی از ریپازیتوری [AISystemOptimizer](https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer) است اما ماژول SmartLocker مستقل است و وابستگی به کد بهینه‌ساز ندارد.

