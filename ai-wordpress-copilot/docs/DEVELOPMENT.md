# معماری افزونه AI WordPress Copilot

## نمای کلی

این افزونه یک **AI Agent واقعی** است، نه یک رابط چت ساده. مدل زبانی از طریق **Function Calling / Tool Calling**
با ابزارهای اجرایی وردپرس ارتباط برقرار می‌کند و عملیات واقعی (ایجاد صفحه، سئو، طراحی، حافظه و…) را انجام می‌دهد.

```
┌─────────────────────────────────────────────────────────────────┐
│  Admin SPA (RTL fa/en, dark/light)  assets/js/app.js + chat.js  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST  /wp-json/ai-copilot/v1/*
┌──────────────────────────────▼──────────────────────────────────┐
│  Api\* Controllers (chat, settings, tools, content, log, ...)   │
└───────┬──────────────────────────────────┬──────────────────────┘
        │                                  │
┌───────▼───────────┐            ┌─────────▼──────────────────────┐
│  Ai\Agent         │◄─ tools ──►│  Ai\Tool_Registry              │
│  (حلقه tool call) │            │  └─ Ai\Tools\* (6 گروه، ۳۰+    │
│                   │            │     ابزار با schema و ریسک)     │
└───┬───────┬───────┘            └─────────┬──────────────────────┘
    │       │                              │
┌───▼───┐ ┌─▼────────────┐   ┌─────────────▼──────────────┐
│OpenAI │ │Site Context  │   │ ابزارهای امن اجرا:          │
│Client │ │Engine (کش+   │   │ • Snapshot_Manager (بازگردانی)│
│(Base  │ │ صفحه‌بندی)   │   │ • Activity_Log (گزارش)       │
│URL    │ └──────────────┘   │ • Permissions (capability)   │
│قابل  │ ┌──────────────┐   │ • Job_Queue (WP-Cron)        │
│تغییر)│ │Memory_Store  │   └──────────────────────────────┘
└───────┘ └──────────────┘
```

## ساختار پوشه‌ها

```
ai-wordpress-copilot/
├── ai-wordpress-copilot.php      # بوت‌استرپ، هوک‌های فعال‌سازی
├── uninstall.php                 # حذف کامل داده‌ها هنگام Uninstall
├── readme.txt                    # استاندارد مخزن وردپرس
├── includes/
│   ├── class-autoloader.php      # نگاشت AIWC\* → includes/**/class-*.php
│   ├── class-plugin.php          # DI ساده + سیم‌کشی سرویس‌ها و هوک‌ها
│   ├── class-activator.php       # جداول دیتابیس (dbDelta)، نقش‌ها، Cron
│   ├── class-deactivator.php
│   ├── class-settings.php        # تنظیمات با اعتبارسنجی + نمایش Masked
│   ├── class-i18n.php            # رشته‌های fa/en برای UI
│   ├── Admin/class-admin.php     # ۱۰ صفحه منو + بارگذاری Asset ها
│   ├── Api/                      # ۷ کنترلر REST (namespace ai-copilot/v1)
│   ├── Ai/
│   │   ├── class-openai-client.php    # کلاینت OpenAI-compatible (retry/timeout)
│   │   ├── class-agent.php            # حلقه plan → tool call → result → answer
│   │   ├── class-tool-registry.php    # ثبت/فعال‌سازی ابزارها + اجرای امن
│   │   ├── class-tool-group-interface.php
│   │   ├── class-abstract-tool-group.php
│   │   └── Tools/                     # ۶ گروه ابزار:
│   │       ├── class-core-tools.php        (site_overview, list/get/search, users,
│   │       │                                plugins, theme, settings, menus)
│   │       ├── class-content-tools.php     (صفحات، نوشته‌ها، رسانه)
│   │       ├── class-design-tools.php      (سکشن، هدر/فوتر، CSS، منو، Elementor)
│   │       ├── class-seo-tools.php         (تحلیل، متا، گزارش سایتی، پیشنهاد)
│   │       ├── class-woo-tools.php         (محصولات و گزارش فروشگاه — شرطی)
│   │       └── class-system-tools.php      (rollback، حافظه، صف)
│   ├── Context/class-site-context-engine.php
│   ├── Seo/class-seo-analyzer.php          # موتور امتیازدهی واقعی سئو
│   ├── Chat/class-conversation-store.php
│   ├── Memory/class-memory-store.php
│   ├── Log/class-activity-log.php
│   ├── Backup/class-snapshot-manager.php
│   ├── Queue/class-job-queue.php
│   └── Security/class-permissions.php
├── assets/
│   ├── css/admin.css             # RTL-first، تم تاریک/روشن
│   └── js/                       # بدون نیاز به Build (vanilla JS)
│       ├── markdown.js           # رندر امن Markdown (escape + transform)
│       ├── api.js                # کلاینت REST + helper ها
│       ├── chat.js               # UI گفت‌وگو، مراحل ابزار، تأییدها
│       └── app.js                # روتر + صفحات داشبورد/ابزارها/سئو/...
└── docs/                         # این مستندات
```

## جریان یک دستور (مثلاً «صفحه اصلی را بازسازی کن»)

1. `POST /chat` → نرخ‌سنجی (۱۵ درخواست/دقیقه، فیلتر `aiwc_chat_rate_limit`) → `Agent::run()`
2. ساخت **System Prompt**: نقش + سیاست اجرا (حالت ۱..۴) + Site Context + Memory
3. فراخوانی `chat/completions` با آرایه `tools` (schema های JSON ابزارهای فعال)
4. اگر مدل `tool_calls` برگرداند:
   - ابزار **فقط‌خواندنی** → اجرای فوری
   - ابزار **تغییردهنده** → بر اساس حالت اجرا:
     - حالت ۱: اصلاً در لیست ابزارها نیست
     - حالت ۲ و ۴: ساخت رکورد `pending` در Activity Log + نتیجه مصنوعی "در انتظار تأیید"
     - حالت ۳: اجرای خودکار read/write؛ destructive/critical → تأیید
5. هر اجرای موفق: **Snapshot** (قبل/بعد) + **Activity Log** + نتیجه به مدل
6. حلقه تا `max_steps` یا پاسخ نهایی؛ ذخیره پیام‌ها + مصرف توکن
7. تأیید مدیر (`POST /approvals/{id}/approve`) → اجرای ابزار با آرایه ذخیره‌شده + به‌روزرسانی پیام tool در مکالمه (رونوشت معتبر برای ادامه گفت‌وگو)

### لغو عملیات (Stop)
دکمه «توقف» در چت، `POST /chat/cancel` را می‌فرستد که یک پرچم زمان‌دار (`time()`) در
transient می‌نویسد. حلقه Agent در مرز هر گام و هر فراخوان ابزار، پرچم را **با خواندن مستقیم
دیتابیس** بررسی می‌کند (کش منفی options وردپرس، نوشته‌های موازی را از `get_transient` پنهان
می‌کند) و در صورت فعال بودن، با پیام «عملیات لغو شد» و ثبت مراحل انجام‌شده، متوقف می‌شود.
پرچم‌های قدیمی‌تر از ۳۰ ثانیه در شروع run نادیده گرفته و پاک می‌شوند.

### بازگردانی مستقیم Snapshot
`GET /snapshots` (فهرست) و `POST /snapshots/{id}/restore` (بازگردانی) — علاوه بر
`POST /logs/{id}/restore`. در UI چت، هر گام موفق دارای snapshot دکمه «بازگردانی» و در صورت
وجود URL، لینک «پیش‌نمایش» دارد.

## امنیت

| لایه | پیاده‌سازی |
|------|-----------|
| Authentication | Cookie auth وردپرس + nonce (`X-WP-Nonce`) یا Application Password |
| Authorization | `manage_aiwc` / `manage_options` در همه مسیرهای REST |
| ورودی | `sanitize_text_field` / `wp_kses_post` / `absint` / اعتبارسنجی schema هر ابزار |
| SQL | فقط `$wpdb->prepare` + `dbDelta` |
| XSS | خروجی UI با escape؛ Markdown renderer ابتدا HTML را escape می‌کند |
| اجرای کد | هیچ `eval`/PHP دلخواه/دسترسی فایل وجود ندارد؛ فقط ابزارهای ثبت‌شده |
| کلید API | فقط سمت سرور؛ همیشه Masked در پاسخ‌ها (`sk-****abcd`) |
| عملیات پرخطر | سطح ریسک per-tool + تأیید صریح + Snapshot قابل بازگردانی |
| CSS | رد `expression(` ، `@import`، `javascript:`، `behavior:` |

## چرخه عمر داده‌ها

- **۶ جدول اختصاصی** (`aiwc_*`) با `dbDelta` ساخته و در Uninstall حذف می‌شوند.
- **Site Context**: transient کش ۵ دقیقه‌ای + نامعتبرسازی روی `save_post`، `switch_theme`، تغییر منو و…
- **صف عملیات**: جدول `aiwc_jobs` + WP-Cron پنج‌دقیقه‌ای + زنجیره‌کردن دسته‌های طولانی (مثلاً تحلیل سئوی کل سایت).

## توسعه ابزار جدید

یک کلاس که `Abstract_Tool_Group` را ارث‌بری می‌کند بسازید، `tools()` را با
نام/توضیح/parameters (JSON Schema)/سطح ریسک (`read|write|destructive|critical`)/capability/handler
پر کنید و در `Plugin::boot()` با `register_group()` ثبت کنید. بقیه کارها (نمایش در UI،
افزودن به Function Calling، لاگ، اعتبارسنجی) خودکار است.
