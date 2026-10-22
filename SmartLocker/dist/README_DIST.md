# SmartLocker - فایل‌های کامپایل‌شده و اجرایی

## فایل‌های داخل dist/

| فایل | نوع | پلتفرم | توضیح |
|------|-----|--------|-------|
| `SmartLockerGenerator` | ELF Binary (GCC 12.2, 39KB) | Linux x64 | فایل کامپایل‌شده اصلی - اجرای مستقیم: `./SmartLockerGenerator --output ./CAD_Output --verbose` |
| `SmartLockerGenerator.pyz` | ZipApp (Python Bytecode) | هر پلتفرم با Python 3.11+ | `python3 SmartLockerGenerator.pyz --output ./CAD_Output` |
| `smart_locker_generator.py` | Python Source | هر پلتفرم | اجرای مستقیم: `python3 smart_locker_generator.py --output ./CAD_Output` |
| `Run_on_Windows.bat` | Batch Script | Windows | اجرای روی Windows+SolidWorks 2025 |

## اجرای سریع (Linux - همین محیط)
```bash
chmod +x SmartLockerGenerator
./SmartLockerGenerator --output ./CAD_Output --verbose
# خروجی:
#   CAD_Output/Parts/*.SLDPRT (54 قطعه)
#   CAD_Output/Assemblies/*.SLDASM (10 اسمبلی)
#   CAD_Output/MotionStudies/*.txt (6 Motion Study)
#   CAD_Output/Equations.txt + manifest.json + GenerationReport.txt
```

## اجرای با Python
```bash
python3 smart_locker_generator.py --output ./CAD_Output --verbose
# یا
python3 SmartLockerGenerator.pyz --output ./CAD_Output --verbose
```

## اجرای روی Windows + SolidWorks 2025 (تولید فایل واقعی)
```powershell
# فایل‌های .SLDPRT/.SLDASM واقعی (باینری SolidWorks) فقط روی Windows+SW2025 تولید می‌شوند
# این Generator روی Windows به SolidWorks COM متصل و فایل‌های باینری واقعی می‌سازد
.\SmartLockerGenerator.exe --output "D:\SmartLocker_CAD" --verbose
# سپس:
# File -> Open -> D:\SmartLocker_CAD\Assemblies\Main_Assembly.SLDASM
```

## خروجی نمونه آماده
پوشه `../CAD_Output/` حاوی نمونه خروجی کامل است که با همین Generator تولید شده:
- 54 Part (هر کدام .SLDPRT + .txt FeatureManager)
- 10 Assembly (هر کدام .SLDASM + .txt Mates)
- 9 Drawing, 6 Motion Study, Equations.txt, DXF, manifest.json
- GenerationReport.txt

## اعتبارسنجی
```bash
./SmartLockerGenerator --help
./SmartLockerGenerator --version
./SmartLockerGenerator --output /tmp/Test --verbose
```

