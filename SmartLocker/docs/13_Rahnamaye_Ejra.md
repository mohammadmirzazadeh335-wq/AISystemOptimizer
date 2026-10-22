# 13. راهنمای اجرای پروژه — فارسی

## 13.1 پیش‌نیازها

| نیاز | نسخه | توضیح |
|------|------|-------|
| Windows | 10 1809+ یا 11 | SolidWorks فقط روی Windows اجرا می‌شود |
| SolidWorks | 2025 SP0 یا جدیدتر | نسخه هدف پروژه — MMGS |
| Visual Studio | 2022 17.4+ | برای Build کد Generator |
| .NET SDK | 8.0+ | برای Build Generator |
| SolidWorks API SDK | همراه SolidWorks | Interop Assemblies |
| RAM | 16GB+ | برای Assembly با 100+ قطعه |
| فضای دیسک | 5GB برای CAD + 2GB برای SW |

## 13.2 نصب و آماده‌سازی

### گام 1: کلون ریپازیتوری

```powershell
git clone https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer.git
cd AISystemOptimizer/SmartLocker
```

### گام 2: باز کردن Solution Generator

```powershell
cd API_Generator
start SmartLockerGenerator.sln
```

در Visual Studio:
- `Tools → Options → SolidWorks API` — مسیر نصب SW را چک کنید.
- References باید به‌صورت خودکار Resolve شوند:
  - `SolidWorks.Interop.sldworks`
  - `SolidWorks.Interop.swconst`
  - `SolidWorks.Interop.swpublished`

اگر Referenceها یافت نشدند:
```powershell
# مسیر معمول نصب SolidWorks
# C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\
# فایل‌ها: SolidWorks.Interop.sldworks.dll, SolidWorks.Interop.swconst.dll
```

### گام 3: Build

```powershell
dotnet build SmartLockerGenerator.sln -c Release
# یا در Visual Studio: Build → Build Solution (F6)
```

خروجی:
```
API_Generator/src/SmartLockerGenerator/bin/Release/net8.0-windows/SmartLockerGenerator.exe
```

## 13.3 اجرای Generator

### حالت 1: تولید کامل (توصیه‌شده)

```powershell
# SolidWorks باید باز باشد (حتی خالی)
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --output "D:\SmartLocker_CAD" --verbose

# پارامترها:
# --output   مسیر خروجی (پیش‌فرض: .\CAD_Output)
# --verbose  نمایش جزئیات هر Part/Assembly
# --only-parts      فقط قطعات
# --only-assemblies فقط اسمبلی‌ها
# --dry-run         شبیه‌سازی بدون ساخت فایل (برای تست منطق)
```

### خروجی Generator

```
D:\SmartLocker_CAD\
├── Equations.txt
├── Parts\
│   ├── Main_Frame.SLDPRT
│   ├── Side_Panel_Left.SLDPRT
│   ├── ... (25+ Part)
│   ├── Linear_Rail_X.SLDPRT
│   ├── Transfer_Tray.SLDPRT
│   └── ...
├── Assemblies\
│   ├── Frame_Assembly.SLDASM
│   ├── X_Axis_Assembly.SLDASM
│   ├── Z_Axis_Assembly.SLDASM
│   ├── Transfer_Tray_Assembly.SLDASM
│   ├── Conveyor_Assembly.SLDASM
│   ├── Housing_Assembly.SLDASM
│   ├── User_Interface_Assembly.SLDASM
│   ├── Electronics_Assembly.SLDASM
│   ├── Cable_Management_Assembly.SLDASM
│   └── Main_Assembly.SLDASM
├── Drawings\
│   ├── Main_Assembly.SLDDRW
│   └── ...
└── GenerationReport.txt
```

### حالت 2: Dry Run (بدون SolidWorks)

```powershell
.\SmartLockerGenerator.exe --dry-run --output ".\TestOutput"
# منطق تولید، پارامترها و Mateها را بدون نیاز به SolidWorks چک می‌کند
# برای CI/CD یا بررسی روی Linux
```

## 13.4 باز کردن در SolidWorks

1. SolidWorks 2025 را باز کنید.
2. `File → Open → D:\SmartLocker_CAD\Assemblies\Main_Assembly.SLDASM`
3. `Tools → Options → System Options → Assemblies → Mate Controller` را فعال کنید.
4. **Rebuild:** `Ctrl+Q` — باید 0 Error باشد.
5. **Interference Detection:** `Tools → Evaluate → Interference Detection → Calculate` — فقط تماس‌های مجاز.
6. **Motion Study:** Tab پایین `Motion Study 1` → Play.

### تست Drag با موس

- `X_Carriage` را انتخاب → Drag افقی → باید 0–480mm حرکت کند.
- `Z_Carriage` → Drag عمودی → 0–2120mm.
- `Transfer_Tray` → Drag عمقی → 0–450mm.

### Mate Controller

- `Tools → Mate Controller` → Slider `X_Position`, `Z_Position`, `Y_Position` را حرکت دهید.
- 10 Position ذخیره‌شده برای هر خانه: `Position_01` تا `Position_10`.

## 13.5 عیب‌یابی

| مشکل | علت | راه‌حل |
|------|-----|--------|
| `Failed to connect to SolidWorks` | SW باز نیست | SW را باز کنید، سپس Generator را اجرا کنید |
| `Interop not found` | API SDK نصب نیست | SW را با گزینه API نصب کنید |
| `Mate Over-defined` | نسخه SW متفاوت | Mateها را در SW چک کنید، Limit را تنظیم کنید |
| `Part not found` | مسیر خروجی اشتباه | `--output` را با مسیر Absolute بدهید |
| `Rebuild Error` | پارامتر خارج از محدوده | Equations.txt را چک کنید |
| تسمه حرکت نمی‌کند | Belt Mate پشتیبانی نمی‌شود | از Fallback (Limit Mate) استفاده کنید — در مستندات توضیح داده شده |

## 13.6 ساختار کد Generator

```
SmartLockerGenerator/
├── Program.cs                    نقطه ورود، CLI parsing، اتصال به SW
├── Config/
│   └── LockerParameters.cs       تمام Global Variables + Equations
├── Parts/
│   ├── FrameParts.cs             Main_Frame, Beams, Supports
│   ├── HousingParts.cs           Panels, Dividers, Floors, Doors
│   ├── MechanismParts.cs         Rails, Blocks, Rollers, Shafts, Pulleys
│   ├── TransferParts.cs          Carriage, Tray, Rack, Pinion
│   ├── ConveyorParts.cs          Belt, Rollers, Frame
│   ├── UiParts.cs                Display, Button, Keypad, Front Panel
│   └── ElectronicsParts.cs       Placeholders, Mounting Plate, Cable Tray
├── Assemblies/
│   ├── FrameAssembly.cs
│   ├── HousingAssembly.cs
│   ├── XAxisAssembly.cs
│   ├── ZAxisAssembly.cs
│   ├── TransferTrayAssembly.cs
│   ├── ConveyorAssembly.cs
│   ├── UiAssembly.cs
│   ├── ElectronicsAssembly.cs
│   └── MainAssembly.cs
├── Mates/
│   └── MateDefinitions.cs        تمام Mateها با پارامتر Limit
├── Motion/
│   └── MotionStudyBuilder.cs     ساخت Motion Study + Motors
└── Utils/
    ├── SolidWorksHelper.cs       اتصال COM، مدیریت اسناد
    └── GeometryHelper.cs         کمک‌های Sketch/Extrude
```

## 13.7 توسعه و سفارشی‌سازی

### تغییر ابعاد خانه

```csharp
// در LockerParameters.cs
public static double CompartmentWidth = 400; // → 500 برای خانه بزرگ‌تر
public static double CompartmentHeight = 400; // → 350

// سپس Rebuild Generator و اجرای مجدد
```

### افزودن خانه

```csharp
// NumberOfRows = 5 → 6 → 12 خانه
// Generator به‌صورت خودکار Pattern را گسترش می‌دهد
```

### افزودن سنسور جدید

```csharp
// در ElectronicsParts.cs
CreateSensorPlaceholder("Sensor_NewType", 20, 15, 10);
// در MainAssembly.cs — Mate جدید
AddSensorMate("Sensor_NewType", targetFace, distance: 5);
```

## 13.8 گزارش تولید

پس از هر اجرای Generator، فایل `GenerationReport.txt` تولید می‌شود:

```
SmartLocker Generator Report
===========================
Date: 2026-10-22
SolidWorks Version: 2025 SP2
Output: D:\SmartLocker_CAD

Parts Created: 28/28 ✅
Assemblies Created: 10/10 ✅
Mates Created: 45/45 ✅
Motion Studies: 6/6 ✅
Drawings: 4/9 (5 need manual adjustment) ⚠️

Errors: 0
Warnings: 1 (Belt/Chain Mate fallback used)

Global Variables:
  Compartment_Width = 400mm
  X_Travel = 480mm
  Z_Travel = 2120mm
  ...

Next Steps:
  1. Open Main_Assembly.SLDASM in SolidWorks
  2. Run Interference Detection
  3. Test Motion Study
```

## 13.9 ویدیوی آموزشی (پیشنهادی)

برای ارائه، این مراحل را ضبط کنید:
1. اجرای Generator (30 ثانیه)
2. باز کردن Main_Assembly در SW (15 ثانیه)
3. Drag X/Z/Y با موس (30 ثانیه)
4. اجرای Motion Study Deposit_06 (15 ثانیه)
5. Interference Detection (15 ثانیه)

> این ویدیو معیار پذیرش نهایی پروژه است: "من باید بتوانم پروژه را باز کنم، درخت را ببینم، قطعات را با موس حرکت دهم و رفت‌وبرگشت به هر خانه را آزمایش کنم."
