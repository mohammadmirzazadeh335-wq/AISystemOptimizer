# API Generator — راهنمای فنی

## چیست؟

پروژه `SmartLockerGenerator` یک کنسول اپلیکیشن **.NET 8 (net8.0-windows)** است که با **SolidWorks 2025 COM API** تمام فایل‌های CAD را تولید می‌کند.

## پیش‌نیازها

| نیاز | نسخه |
|------|------|
| Windows 10 1809+ یا 11 | - |
| SolidWorks 2025 SP0+ | برای حالت LIVE |
| Visual Studio 2022 17.4+ | با SolidWorks API SDK |
| .NET SDK 8.0+ | `dotnet --version` |

## نصب SolidWorks API References

SolidWorks نصب معمولاً این فایل‌ها را دارد:

```
C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\
  ├── SolidWorks.Interop.sldworks.dll
  ├── SolidWorks.Interop.swconst.dll
  └── SolidWorks.Interop.swpublished.dll
```

در Visual Studio:
1. Solution Explorer → References → Add Reference → Browse → انتخاب 3 فایل فوق
2. `Copy Local: False`, `Embed Interop Types: False`

## Build

```powershell
cd SmartLocker/API_Generator
dotnet build SmartLockerGenerator.sln -c Release
```

خروجی: `src/SmartLockerGenerator/bin/Release/net8.0-windows/SmartLockerGenerator.exe`

## اجرا

```powershell
# 1. حالت کامل (SolidWorks باید باز باشد)
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --output "D:\SmartLocker_CAD" --verbose

# 2. فقط منطق (بدون SolidWorks - روی هر سیستمی)
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --dry-run --output "./TestOutput" --verbose

# 3. فقط قطعات
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --dry-run --only-parts
```

## پارامترها

| گزینه | توضیح |
|-------|-------|
| `--output <path>` | مسیر خروجی (پیش‌فرض: ./CAD_Output) |
| `--dry-run` | شبیه‌سازی بدون SolidWorks - اعتبارسنجی منطق |
| `--verbose` | نمایش تمام Features و Mates |
| `--only-parts` | فقط قطعات |
| `--only-assemblies` | فقط اسمبلی‌ها |
| `--help` | راهنما |

## معماری کد

```
Program.cs                  CLI, ترتیب اجرا, اعتبارسنجی
Config/LockerParameters.cs  تمام Global Variables + فرمول‌ها + GetCompartmentPosition() + Validate()
Utils/SolidWorksHelper.cs   اتصال COM, PartBuilder, AssemblyBuilder
Parts/FrameParts.cs         Main_Frame, Vertical_Support, Horizontal_Beam, Bottom_Plate, Brackets, Feet
Parts/HousingParts.cs       Side/Front/Rear/Top Panels, Dividers, Floors, Doors, Hinges, Service Panel
Parts/MechanismParts.cs     Rails(X/Z/Y), Guide Blocks, Shafts, Lead Screws, Pulleys, Belts, Bearings, Motors, Sensors
Parts/TransferParts.cs      X/Z Carriage, Transfer Tray, Rack/Pinion, Tray Guide, Conveyor
Parts/UiParts.cs            Front Panel, Display/Button/Keypad Placeholders+Mouths
Parts/ElectronicsParts.cs   Electronics Plate, Arduino, Motor Drivers, PSU, Terminal Block, Cable Trays, Energy Chain
Assemblies/AllAssemblies.cs 10 Sub-Assemblies + Main_Assembly با تمام Mateها (LimitDistance X/Z/Y)
Mates/MateDefinitions.cs    لیست متمرکز تمام Mateها با اعتبارسنجی Over-defined
Motion/MotionStudyBuilder.cs 6 Motion Study (X_Sweep, Z_Sweep, XZ_Grid, Deposit_06, Retrieval_06, Full_Cycle)
```

## خروجی

```
D:\SmartLocker_CAD\
├── Equations.txt                    Global Variables قابل Import در SW
├── Parts\
│   ├── Main_Frame.SLDPRT (+ .desc.txt)
│   ├── Side_Panel_Left.SLDPRT
│   ├── Linear_Rail_X.SLDPRT
│   ├── X_Carriage.SLDPRT
│   ├── Transfer_Tray.SLDPRT
│   ├── ... (28 Parts مجموعاً)
│   └── Pulley_GT2_20T.SLDPRT
├── Assemblies\
│   ├── Frame_Assembly.SLDASM
│   ├── X_Axis_Assembly.SLDASM      (Limit X 0-480mm)
│   ├── Z_Axis_Assembly.SLDASM      (Limit Z 0-2120mm)
│   ├── Transfer_Tray_Assembly.SLDASM (Limit Y 0-450mm)
│   ├── ... (10 Assemblies)
│   └── Main_Assembly.SLDASM        (مونتاژ نهایی)
├── Drawings\
│   ├── Main_Assembly.SLDDRW
│   └── ... (9 Drawings)
└── GenerationReport.txt            گزارش کامل تولید
```

## تست پس از تولید

```
1. باز کردن Main_Assembly.SLDASM در SolidWorks 2025
2. Ctrl+Q (Force Rebuild) - باید 0 Error
3. Tools -> Evaluate -> Interference Detection -> Calculate (باید فقط تماس‌های مجاز)
4. Mate Controller (Tools -> Mate Controller) - Slider X/Z/Y را حرکت دهید
5. Drag قطعات با موس - X_Carriage, Z_Carriage, Transfer_Tray
6. Motion Study tab -> Play هر Study
```

## عیب‌یابی

| خطا | راه‌حل |
|-----|--------|
| `SolidWorks not found` | SW را نصب و باز کنید |
| `Interop not found` | API SDK را نصب کنید یا مسیر Reference را چک کنید |
| `Mate Over-defined` | نسخه SW را چک کنید - Limit Mateها را بررسی کنید |
| `Parameter validation failed` | LockerParameters.cs - محدوده را چک کنید |

## Linux/CI (--dry-run)

روی Linux (این Sandbox) یا CI بدون Windows:
- SolidWorks در دسترس نیست، اما `--dry-run` تمام منطق را اعتبارسنجی می‌کند.
- تمام PartBuilders و AssemblyBuilders اجرا می‌شوند و FeatureCount/MateCount را چک می‌کنند.
- فایل‌های `.desc.txt` با توضیح کامل هر Feature/Mate تولید می‌شوند.
- `GenerationReport.txt` خلاصه نهایی است.
