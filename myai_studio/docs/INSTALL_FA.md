# راهنمای نصب و اجرا — MyAI Studio Ultimate

نسخهٔ فعلی: **۰٫۱٫۰ (فاز ۱ — پی‌ریزی)**

---

## ۱. نصب روی ویندوز ۱۱ (از سورس)

### پیش‌نیازها
- ویندوز ۱۱ نسخهٔ ۶۴ بیتی
- Python 3.10 تا 3.13 (پیشنهاد: 3.12)
  - هنگام نصب، گزینهٔ **Add python.exe to PATH** را تیک بزنید.

### گام‌ها

ساده‌ترین راه، اجرای فایل راه‌انداز است:

```powershell
cd myai_studio
.\run_windows.bat        # یا:  powershell -ExecutionPolicy Bypass -File .\run_windows.ps1
```

این فایل در اولین اجرا محیط مجازی می‌سازد، وابستگی‌ها را نصب می‌کند و برنامه را باز می‌کند.

اجرای دستی:

```powershell
# ۱) پوشهٔ برنامه
cd myai_studio

# ۲) ساخت محیط مجازی
python -m venv .venv
.venv\Scripts\activate

# ۳) نصب وابستگی‌ها
pip install -r requirements.txt

# ۴) اجرا
python -m myai
```

پس از اجرا، پنجرهٔ برنامه با رابط فارسی و پوستهٔ تیره باز می‌شود.

گزینه‌های اجرا:

```powershell
python -m myai --lang en            # رابط انگلیسی
python -m myai --theme dawn         # پوستهٔ روشن
python -m myai --home D:\MyData     # پوشهٔ دادهٔ دلخواه
python -m myai --smoke              # آزمون سلامت: باز و بسته می‌شود
```

---

## ۲. ساخت فایل EXE

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

این اسکریپت به‌ترتیب:
1. محیط مجازی و وابستگی‌های ساخت را آماده می‌کند،
2. **کل مجموعهٔ آزمون‌ها را اجرا می‌کند** و اگر حتی یک آزمون شکست بخورد، متوقف می‌شود،
3. با PyInstaller خروجی `dist\MyAIStudio\MyAIStudio.exe` را می‌سازد،
4. فایل اجرایی ساخته‌شده را با `--smoke` **واقعاً اجرا و آزمون می‌کند**،
5. فقط در صورت موفقیت پیام نهایی می‌دهد.

برای ساخت نصب‌کننده (نیازمند [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -Installer
```

خروجی: `dist\installer\MyAIStudio-0.1.0-setup.exe`

> اگر این اسکریپت اجرا نشده باشد، فایل EXE وجود ندارد؛ در مخزن هیچ باینری جعلی
> قرار داده نشده است.

---

## ۳. اجرا روی لینوکس یا macOS (برای توسعه)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m myai
```

روی این سیستم‌ها رمزها با Fernet و یک کلید محلی محافظت می‌شوند (نه DPAPI).

---

## ۴. محل نگهداری داده‌ها

پوشهٔ پیش‌فرض: `%APPDATA%\MyAIStudio`

| مسیر | محتوا |
| --- | --- |
| `myai_studio.db` | پایگاه دادهٔ گفتگوها و تنظیمات |
| `logs\` | گزارش‌های ساختاریافته (JSONL) |
| `secrets.bin` | کلیدهای API رمزنگاری‌شده |
| `backups\` | نسخه‌های پشتیبان (بدون کلیدها) |
| `outputs\` | خروجی‌های تولیدشده |
| `projects\` | پروژه‌های فضای کاری |

با `--home` یا متغیر محیطی `MYAI_STUDIO_HOME` قابل تغییر است.

**نکتهٔ امنیتی:** کلیدهای API هرگز در لاگ‌ها، خروجی‌ها یا فایل‌های پشتیبان نوشته نمی‌شوند.

---

## ۵. اجرای آزمون‌ها

```powershell
.venv\Scripts\python -m pytest -q
```

نتیجهٔ مورد انتظار در این نسخه: `148 passed`.

---

## ۶. رفع اشکال

| نشانه | علت احتمالی | راه‌حل |
| --- | --- | --- |
| `ModuleNotFoundError: PySide6` | محیط مجازی فعال نیست | `.venv\Scripts\activate` |
| پنجره باز نمی‌شود | نسخهٔ Python ناسازگار | Python 3.10–3.13 نصب کنید |
| «برنامه از قبل در حال اجراست» | نمونهٔ دیگری باز است | پنجرهٔ قبلی را ببندید یا با `--allow-multi` اجرا کنید |
| متن فارسی جدا افتاده | فونت وزیرمتن بارگذاری نشده | مطمئن شوید پوشهٔ `assets/fonts` کنار برنامه است |
| مسیر داده اشتباه | متغیر محیطی قدیمی | `echo %MYAI_STUDIO_HOME%` و سپس حذف متغیر |

گزارش خطاها در `logs\myai_studio.jsonl` و از داخل برنامه در
**تنظیمات ← عمومی ← بازکردن پوشهٔ گزارش‌ها** قابل دسترسی است.
