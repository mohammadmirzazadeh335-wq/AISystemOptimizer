# راهنمای تست

## محیط تست

تست‌ها روی **یک نصب واقعی WordPress** (نسخه trunk از میراث رسمی `WordPress/WordPress` روی GitHub)
از طریق [WordPress Playground CLI](https://www.npmjs.com/package/@wp-playground/cli) اجرا می‌شوند —
یعنی همان هسته وردپرس، با PHP 8.3 و دیتابیس SQLite، در یک سرور HTTP واقعی.

زیرساخت تست در `tools/wp-test/` مخزن اصلی قرار دارد:

| فایل | نقش |
|------|-----|
| `mock-openai.js` | سرور Mock سازگار با OpenAI (`/v1/chat/completions` با tool calls + `/v1/models`) |
| `fetch-shim.js` | هدایت درخواست‌های مسدودشده `wordpress.org` به میراث GitHub (فقط محیط تست) |
| `mu-plugins/aiwc-test.php` | فقط تست: فعال‌سازی Application Password روی HTTP + صدور credential + fallback موقت HTTP |
| `blueprint.json` | فعال‌سازی افزونه هنگام بوت سایت |
| `smoke_test.py` | مجموعه تست E2E (۶۴ سنجه) |
| `lint-php.js` | lint سینتکس همه فایل‌های PHP با `php-parser` |

## اجرای تست‌ها

```bash
cd tools/wp-test
npm install @wp-playground/cli

# ۱) سرور Mock API
node mock-openai.js &

# ۲) سایت وردپرس (پلاگین به‌صورت زنده mount می‌شود)
NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
node -r ./fetch-shim.js node_modules/@wp-playground/cli/cli.js server \
  --wp=trunk --php=8.3 --port=9400 --login \
  --mount ../../ai-wordpress-copilot:/wordpress/wp-content/plugins/ai-wordpress-copilot \
  --mount ./mu-plugins:/wordpress/wp-content/mu-plugins \
  --blueprint ./blueprint.json

# ۳) تست‌ها (صبر برای بوت + دریافت credential خودکار)
python3 smoke_test.py

# ۴) lint سینتکس PHP
node lint-php.js
```

نکته: چون افزونه به‌صورت `--mount` سوار می‌شود، هر تغییر کد بلافاصله در سایت تست اعمال می‌شود
(نیازی به نصب مجدد نیست).

## پوشش تست‌های E2E (smoke_test.py)

- ✅ بوت وردپرس + فعال‌سازی افزونه بدون Fatal
- ✅ ذخیره/بازیابی تنظیمات؛ **مخفی‌ماندن کلید API** در تمام پاسخ‌ها
- ✅ تست اتصال API با **انتقال HTTP واقعی** به سرور Mock (fallback نیز تست شده)
- ✅ لیست مدل‌ها (`GET /models`)
- ✅ Site Context Engine (نمای کلی + ساختار)
- ✅ **رد درخواست بدون احراز هویت (401/403)**
- ✅ چت + Tool Calling: `create_page` → **ایجاد صفحه واقعی** در وردپرس (تأیید با WP REST API)
- ✅ ثبت در Activity Log + شمارش توکن + ساخت مکالمه
- ✅ ابزار فقط‌خواندنی (`site_overview`)
- ✅ **جریان تأیید (حالت ۲)**: صف تأیید → عدم ایجاد صفحه قبل از تأیید → اجرا پس از `approve`
- ✅ **جریان رد** (`reject`)
- ✅ حافظه: ذخیره از طریق چت + افزودن/حذف دستی
- ✅ تحلیل سئوی تک‌صفحه (امتیاز ۰–۱۰۰، مشکلات، checks)
- ✅ تحلیل سئوی سایتی: صف → زنجیره دسته‌ها → گزارش با میانگین امتیاز
- ✅ لیست محتوا + **Rollback واقعی صفحه** (تغییر → snapshot → بازگردانی → تطابق محتوا)
- ✅ تغییر CSS اختصاصی + **Rollback واقعی CSS**
- ✅ رجیستری ابزارها + فعال/غیرفعال‌سازی
- ✅ رندر صفحه داشبورد ادمین + بارگذاری Asset ها + عدم وجود Fatal
- ✅ lint سینتکس ۳۷ فایل PHP و ۴ فایل JS

## یادداشت‌های محیطی

- در شبکه این sandbox دسترسی مستقیم به `wordpress.org` مسدود است؛ `fetch-shim.js`
  درخواست‌های هسته را به میراث رسمی GitHub هدایت می‌کند (فقط در محیط تست، خارج از افزونه).
- احراز هویت تست‌ها با Application Password (مسیر REST) و `admin/password` (مسیر wp-admin HTML) است.
