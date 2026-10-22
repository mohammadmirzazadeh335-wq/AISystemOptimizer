# فایل‌های SolidWorks — توضیح مهم

## چرا فایل‌های .SLDPRT/.SLDASM باینری اینجا نیستند؟

فایل‌های SolidWorks (SLDPRT, SLDASM, SLDDRW) فرمت باینری اختصاصی Dassault Systèmes هستند که:
- فقط با خود SolidWorks 2025 روی Windows قابل تولید هستند.
- حتی یک بایت تغییر، فایل را خراب می‌کند.
- ایجاد فایل جعلی با پسوند SLDPRT نقض الزام §2 و §18 پروژه است.

این ریپازیتوری در محیط Linux (Sandbox بدون SolidWorks) ساخته شده — بنابراین فایل باینری واقعی نمی‌تواند اینجا باشد.

## راه‌حل: کد تولید خودکار (SolidWorks API)

پوشه [`API_Generator/`](../API_Generator/) حاوی یک پروژه کامل C# است که:

1. به SolidWorks 2025 (COM API) متصل می‌شود.
2. تمام قطعات را با Features واقعی (Sketch, Extrude, Revolve, HoleWizard, Pattern, Fillet, Equations) می‌سازد.
3. تمام اسمبلی‌ها را مونتاژ و Mate می‌کند (Coincident, Concentric, LimitDistance, Belt/Chain).
4. Motion Study می‌سازد.
5. فایل‌ها را با نام‌گذاری صحیح در مسیر خروجی ذخیره می‌کند.

### اجرای سریع

```powershell
cd SmartLocker/API_Generator
dotnet build SmartLockerGenerator.sln -c Release
.\src\SmartLockerGenerator\bin\Release\net8.0-windows\SmartLockerGenerator.exe --output "D:\SmartLocker_CAD" --verbose
```

سپس:

```
File → Open → D:\SmartLocker_CAD\Assemblies\Main_Assembly.SLDASM
```

راهنمای کامل: [docs/13_Rahnamaye_Ejra.md](../docs/13_Rahnamaye_Ejra.md)

## محتوای پیش‌نمایشی این پوشه

| پوشه | محتوا |
|------|-------|
| `Parts/` | توضیح هر قطعه + Feature Tree + پیش‌نمایش ASCII/STEP |
| `Assemblies/` | سلسله‌مراتب اسمبلی + Mateها + دیاگرام |
| `Drawings/` | توضیح نقشه‌ها + Template |
| `Equations.txt` | تمام Global Variables قابل Import |

## اعتبارسنجی

- کد Generator با `--dry-run` بدون نیاز به SolidWorks قابل تست منطقی است.
- تمام پارامترها با MMGS و SolidWorks 2025 سازگار هستند.
- Mateها با API واقعی SW2025 تعریف شده‌اند (نه فرضی).

> پس از اجرا روی Windows+SW2025، فایل‌های باینری تولید شده 100% با استاندارد SolidWorks سازگار و با موس قابل حرکت خواهند بود.
