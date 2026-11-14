"""Typed application settings stored in the database.

The registry below is the single source of truth: it defines every setting's
type, default, allowed range/choices, Persian label and the tab it appears on.
The settings screen is generated from this registry, so a new setting only needs
one entry here to be editable, validated, audited and persisted.

Reading settings never requires a permission (the login window itself needs the
application name, theme and fonts). Changing them requires ``settings.edit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import select

from pars_erp.core.errors import ValidationError
from pars_erp import APP_NAME_DEFAULT
from pars_erp.core.money import CURRENCIES, DEFAULT_CURRENCY_CODE
from pars_erp.db.models import AppSetting
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService, EventType

GROUP_GENERAL = "general"
GROUP_APPEARANCE = "appearance"
GROUP_SECURITY = "security"
GROUP_BACKUP = "backup"
GROUP_ACCOUNTING = "accounting"
GROUP_COMMERCE = "commerce"
GROUP_TREASURY = "treasury"
GROUP_HR = "hr"
GROUP_PAYROLL = "payroll"
GROUP_ASSETS = "assets"
GROUP_REPORTING = "reporting"
GROUP_UPDATE = "update"

SETTING_GROUPS: tuple[tuple[str, str], ...] = (
    (GROUP_GENERAL, "اطلاعات شرکت و عمومی"),
    (GROUP_APPEARANCE, "ظاهر و نمایش"),
    (GROUP_SECURITY, "امنیت و نشست"),
    (GROUP_BACKUP, "پشتیبان‌گیری"),
    (GROUP_ACCOUNTING, "حسابداری"),
    (GROUP_COMMERCE, "بازرگانی و انبار"),
    (GROUP_TREASURY, "خزانه‌داری"),
    (GROUP_HR, "منابع انسانی"),
    (GROUP_PAYROLL, "حقوق و دستمزد"),
    (GROUP_ASSETS, "دارایی‌های ثابت"),
    (GROUP_REPORTING, "گزارش‌ها و داشبورد"),
    (GROUP_UPDATE, "به‌روزرسانی برنامه"),
)

TYPE_STRING = "string"
TYPE_INT = "int"
TYPE_BOOL = "bool"
TYPE_CHOICE = "choice"


@dataclass(frozen=True)
class SettingDef:
    key: str
    label_fa: str
    group: str
    type: str
    default: Any
    choices: tuple[tuple[str, str], ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    max_length: int | None = None
    help_fa: str = ""
    requires_restart: bool = False

    @property
    def group_title_fa(self) -> str:
        return dict(SETTING_GROUPS).get(self.group, self.group)

    def coerce(self, value: Any) -> Any:
        """Validate and normalise a raw value, raising a Persian error."""
        if self.type == TYPE_BOOL:
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
                return value.strip().lower() in ("true", "1")
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            raise ValidationError(f"مقدار «{self.label_fa}» باید بله یا خیر باشد.", field=self.key)

        if self.type == TYPE_INT:
            if isinstance(value, bool):
                raise ValidationError(f"مقدار «{self.label_fa}» باید عدد باشد.", field=self.key)
            if isinstance(value, str):
                from pars_erp.core.digits import to_latin_digits
                text = to_latin_digits(value).strip()
                if not text.lstrip("-").isdigit():
                    raise ValidationError(f"مقدار «{self.label_fa}» باید عدد باشد.", field=self.key)
                value = int(text)
            if not isinstance(value, int):
                raise ValidationError(f"مقدار «{self.label_fa}» باید عدد باشد.", field=self.key)
            if self.min_value is not None and value < self.min_value:
                raise ValidationError(
                    f"«{self.label_fa}» نباید کمتر از {self.min_value} باشد.", field=self.key)
            if self.max_value is not None and value > self.max_value:
                raise ValidationError(
                    f"«{self.label_fa}» نباید بیشتر از {self.max_value} باشد.", field=self.key)
            return value

        if self.type == TYPE_CHOICE:
            text = str(value).strip()
            allowed = {choice[0] for choice in self.choices}
            if text not in allowed:
                raise ValidationError(
                    f"مقدار «{self.label_fa}» باید یکی از گزینه‌های مجاز باشد.", field=self.key)
            return text

        # string
        if value is None:
            text = ""
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            text = str(value)
        else:
            text = str(value).strip()
        if self.max_length is not None and len(text) > self.max_length:
            raise ValidationError(
                f"طول «{self.label_fa}» نباید بیشتر از {self.max_length} نویسه باشد.", field=self.key)
        return text


def _currency_choices() -> tuple[tuple[str, str], ...]:
    return tuple((code, cur.name_fa) for code, cur in CURRENCIES.items())


SETTING_DEFS: tuple[SettingDef, ...] = (
    # -------------------------------------------------------------- general
    SettingDef("app_name", "نام نرم‌افزار", GROUP_GENERAL, TYPE_STRING, APP_NAME_DEFAULT,
               max_length=40, help_fa="نامی که در عنوان پنجره‌ها و گزارش‌ها نمایش داده می‌شود."),
    SettingDef("company_name", "نام شرکت", GROUP_GENERAL, TYPE_STRING, "", max_length=160),
    SettingDef("company_economic_code", "شناسه ملی / کد اقتصادی", GROUP_GENERAL, TYPE_STRING, "",
               max_length=32),
    SettingDef("company_phone", "تلفن شرکت", GROUP_GENERAL, TYPE_STRING, "", max_length=32),
    SettingDef("company_address", "نشانی شرکت", GROUP_GENERAL, TYPE_STRING, "", max_length=300),
    SettingDef("currency_code", "واحد پول پیش‌فرض", GROUP_GENERAL, TYPE_CHOICE,
               DEFAULT_CURRENCY_CODE, choices=_currency_choices(),
               help_fa="واحد پولی که در فرم‌ها و گزارش‌ها به‌کار می‌رود."),
    # ----------------------------------------------------------- appearance
    SettingDef("theme", "پوسته", GROUP_APPEARANCE, TYPE_CHOICE, "light",
               choices=(("light", "روشن"), ("dark", "تاریک"))),
    SettingDef("font_family", "قلم رابط کاربری", GROUP_APPEARANCE, TYPE_CHOICE, "Vazirmatn",
               choices=(("Vazirmatn", "وزیرمتن"), ("Tahoma", "Tahoma"), ("Segoe UI", "Segoe UI"),
                        ("IRANSans", "IRANSans")),
               help_fa="قلم باید روی سیستم نصب باشد یا از قلم همراه برنامه استفاده می‌شود."),
    SettingDef("font_size", "اندازه قلم", GROUP_APPEARANCE, TYPE_INT, 11, min_value=9, max_value=18),
    SettingDef("persian_digits", "نمایش اعداد به فارسی", GROUP_APPEARANCE, TYPE_BOOL, True),
    SettingDef("table_page_size", "تعداد سطر در هر صفحه جدول", GROUP_APPEARANCE, TYPE_INT, 25,
               min_value=10, max_value=100),
    # ------------------------------------------------------------- security
    SettingDef("idle_lock_minutes", "قفل خودکار نشست پس از بی‌کاری (دقیقه)", GROUP_SECURITY,
               TYPE_INT, 10, min_value=1, max_value=120),
    SettingDef("max_failed_attempts", "حداکثر تلاش ناموفق ورود", GROUP_SECURITY, TYPE_INT, 5,
               min_value=3, max_value=10),
    SettingDef("lockout_minutes", "مدت قفل حساب پس از تلاش‌های ناموفق (دقیقه)", GROUP_SECURITY,
               TYPE_INT, 15, min_value=1, max_value=1440),
    SettingDef("password_min_length", "حداقل طول رمز عبور", GROUP_SECURITY, TYPE_INT, 10,
               min_value=8, max_value=64),
    SettingDef("require_password_for_restore", "درخواست رمز عبور برای بازیابی پایگاه داده",
               GROUP_SECURITY, TYPE_BOOL, True,
               help_fa="پیشنهاد می‌شود همیشه فعال بماند؛ بازیابی عملیات پرخطری است."),
    # --------------------------------------------------------------- backup
    SettingDef("auto_backup_on_startup", "پشتیبان‌گیری خودکار در شروع برنامه",
               GROUP_BACKUP, TYPE_BOOL, True),
    SettingDef("backup_interval_hours", "فاصله پشتیبان‌گیری خودکار (ساعت)", GROUP_BACKUP,
               TYPE_INT, 24, min_value=1, max_value=720),
    SettingDef("backup_retention", "تعداد پشتیبان‌های نگهداری‌شده", GROUP_BACKUP, TYPE_INT, 20,
               min_value=1, max_value=365,
               help_fa="پشتیبان‌های قدیمی‌تر از این تعداد به‌صورت خودکار پاک می‌شوند."),
    # ----------------------------------------------------------- accounting
    SettingDef("accounting_code_mask", "الگوی کدینگ حساب‌ها", GROUP_ACCOUNTING, TYPE_STRING,
               "1-2-3", max_length=12,
               help_fa=("سه عدد با خط تیره: رقم‌های افزوده در هر سطح از بالا به پایین. "
                        "مثال 1-2-3 یعنی گروه یک‌رقمی (1)، کل سه‌رقمی (101) و "
                        "معین شش‌رقمی (101001).")),
    SettingDef("accounting_enforce_workflow", "اجرای گردش تأیید سند", GROUP_ACCOUNTING,
               TYPE_BOOL, False,
               help_fa=("اگر فعال باشد سند باید مرحلهٔ «در انتظار تأیید» و «تأییدشده» را "
                        "طی کند؛ در غیر این صورت پیش‌نویس مستقیماً نهایی می‌شود.")),
    SettingDef("accounting_show_currency", "نمایش ستون ارز در فرم سند", GROUP_ACCOUNTING,
               TYPE_BOOL, False),
    # ------------------------------------------------------------- commerce
    SettingDef("commerce_valuation_method", "روش ارزش‌گذاری موجودی", GROUP_COMMERCE,
               TYPE_CHOICE, "average",
               choices=(("average", "میانگین موزون"), ("fifo", "اولین صادره از اولین وارده (FIFO)")),
               help_fa=("روش پیش‌فرض شرکت است؛ هر انبار می‌تواند روش خودش را داشته باشد. "
                        "تغییر روش، اسناد و کاردکس گذشته را بازنویسی نمی‌کند.")),
    SettingDef("commerce_invoice_warn_credit_limit", "هشدار عبور از سقف اعتبار مشتری",
               GROUP_COMMERCE, TYPE_BOOL, True,
               help_fa="در صورت فعال بودن، فروش بیش از سقف اعتبار نیازمند مجوز است."),
    SettingDef("commerce_allow_negative_stock", "اجازه موجودی منفی در انبارهای بدون سیاست خاص",
               GROUP_COMMERCE, TYPE_BOOL, False,
               help_fa=("به‌صورت پیش‌فرض موجودی منفی ممنوع است. برای اجازه در یک انبار، "
                        "گزینهٔ همان انبار و مجوز «اجازه خروج بیش از موجودی» لازم است.")),
    # ------------------------------------------------------------- treasury
    SettingDef("treasury_allow_negative_fund", "اجازه منفی شدن موجودی صندوق/بانک",
               GROUP_TREASURY, TYPE_BOOL, False,
               help_fa=("به‌صورت پیش‌فرض پرداخت بیش از موجودی صندوق یا حساب بانکی ممنوع "
                        "است؛ تغییر این تنظیم باید با اطلاع مدیر مالی باشد.")),
    SettingDef("treasury_cheque_alert_days", "هشدار چند روز قبل از سررسید چک",
               GROUP_TREASURY, TYPE_INT, 7,
               help_fa="تعداد روزهای هشدار برای چک‌ها و بدهی‌های نزدیک سررسید."),
    SettingDef("treasury_stale_cheque_days", "آستانهٔ «چک معوق» (روز)", GROUP_TREASURY,
               TYPE_INT, 30,
               help_fa="چک سررسیدگذشته بیش از این تعداد روز در گزارش معوق شمرده می‌شود."),
    # --------------------------------------------------------------------- hr
    SettingDef("hr_work_start_time", "ساعت شروع کار موظفی", GROUP_HR, TYPE_STRING, "08:00",
               max_length=5,
               help_fa="مبنای محاسبهٔ تأخیر؛ ساعت پایان و استراحت هر شیفت در تعریف شیفت است."),
    SettingDef("hr_work_end_time", "ساعت پایان کار موظفی", GROUP_HR, TYPE_STRING, "17:00",
               max_length=5),
    SettingDef("hr_grace_minutes", "مهلت مجاز تأخیر (دقیقه)", GROUP_HR, TYPE_INT, 10,
               min_value=0, max_value=120,
               help_fa="تأخیر کمتر از این مقدار در گزارش‌ها محاسبه نمی‌شود."),
    SettingDef("hr_work_days_per_week", "تعداد روز کاری هفته", GROUP_HR, TYPE_INT, 6,
               min_value=1, max_value=7),
    SettingDef("hr_work_weekdays", "روزهای کاری هفته (۰=شنبه تا ۶=جمعه)", GROUP_HR,
               TYPE_STRING, "0,1,2,3,4,5", max_length=20,
               help_fa="برای محاسبهٔ روزهای کاری ماه، غیبت و مرخصی استفاده می‌شود."),
    SettingDef("hr_allow_self_service", "امکان ثبت حضور و درخواست توسط کارمند", GROUP_HR,
               TYPE_BOOL, False,
               help_fa="در صورت فعال بودن، کارمند می‌تواند ورود/خروج و درخواست مرخصی ثبت کند."),
    SettingDef("hr_overtime_requires_approval", "اضافه‌کاری نیازمند تأیید است", GROUP_HR,
               TYPE_BOOL, True),
    SettingDef("hr_leave_requires_approval", "مرخصی نیازمند تأیید است", GROUP_HR, TYPE_BOOL,
               True),
    SettingDef("hr_contract_alert_days", "هشدار انقضای قرارداد (روز)", GROUP_HR, TYPE_INT, 30,
               min_value=0, max_value=365),
    SettingDef("hr_employee_code_prefix", "پیشوند کد پرسنلی", GROUP_HR, TYPE_STRING, "EMP",
               max_length=8),
    # ---------------------------------------------------------------- payroll
    SettingDef("payroll_require_approval", "محاسبهٔ حقوق نیازمند تأیید است", GROUP_PAYROLL,
               TYPE_BOOL, True,
               help_fa="پس از محاسبه، ثبت سند حسابداری و پرداخت فقط پس از تأیید ممکن است."),
    SettingDef("payroll_payment_file_format", "قالب فایل بانکی پرداخت حقوق", GROUP_PAYROLL,
               TYPE_CHOICE, "csv",
               choices=(("csv", "CSV"), ("txt", "متن با جداکنندهٔ تب")),
               help_fa="فایل خروجی دستهٔ پرداخت با این قالب ساخته می‌شود."),
    SettingDef("payroll_payment_file_columns", "ستون‌های فایل بانکی (با کاما)", GROUP_PAYROLL,
               TYPE_STRING,
               "employee_code,full_name,iban,amount,tracking_no",
               max_length=200,
               help_fa=("ترتیب ستون‌ها را خودتان تعیین می‌کنید: هر نام باید یکی از "
                        "employee_code/full_name/iban/bank_account_no/amount/tracking_no/"
                        "period باشد.")),
    SettingDef("payroll_allow_multiple_runs", "اجازهٔ چند دورهٔ حقوق هم‌زمان در یک ماه",
               GROUP_PAYROLL, TYPE_BOOL, False),
    # ----------------------------------------------------------------- assets
    SettingDef("assets_default_useful_life_years", "عمر مفید پیش‌فرض دارایی (سال)",
               GROUP_ASSETS, TYPE_INT, 5, min_value=1, max_value=60),
    SettingDef("assets_depreciation_requires_approval", "ثبت استهلاک نیازمند تأیید است",
               GROUP_ASSETS, TYPE_BOOL, True),
    SettingDef("assets_code_prefix", "پیشوند کد دارایی", GROUP_ASSETS, TYPE_STRING, "AST",
               max_length=8),
    # ------------------------------------------------------------- reporting
    SettingDef("report_page_size", "تعداد سطر پیش‌فرض گزارش‌ها", GROUP_REPORTING, TYPE_INT, 100,
               min_value=25, max_value=1000,
               help_fa="هر صفحه از مرکز گزارش‌ها چند سطر داشته باشد."),
    SettingDef("report_default_days", "بازهٔ پیش‌فرض گزارش (روز)", GROUP_REPORTING, TYPE_INT, 30,
               min_value=1, max_value=3650,
               help_fa="اگر کاربر تاریخی انتخاب نکند، گزارش از این تعداد روز پیش تا امروز است."),
    SettingDef("report_export_format", "قالب پیش‌فرض خروجی گزارش", GROUP_REPORTING, TYPE_CHOICE,
               "xlsx", choices=(("xlsx", "Excel (XLSX)"), ("pdf", "PDF"), ("csv", "CSV")),
               help_fa="دکمهٔ خروجی سریع در مرکز گزارش‌ها از این قالب استفاده می‌کند."),
    SettingDef("report_csv_delimiter", "جداکنندهٔ فایل CSV", GROUP_REPORTING, TYPE_CHOICE, ",",
               choices=((',', "کاما (,)"), (';', "نقطه‌ویرگول (;)"), ('\t', "تب")),
               help_fa="برای باز شدن درست فایل در Excel فارسی، معمولاً نقطه‌ویرگول بهتر است."),
    SettingDef("report_show_company_header", "درج نام شرکت در سربرگ گزارش‌ها",
               GROUP_REPORTING, TYPE_BOOL, True),
    SettingDef("report_max_rows", "سقف سطرهای یک گزارش", GROUP_REPORTING, TYPE_INT, 20000,
               min_value=1000, max_value=200000,
               help_fa=("گزارش سنگین‌تر از این تعداد سطر اجرا نمی‌شود تا برنامه کند نشود؛ "
                        "بازه را کوچک‌تر کنید.")),
    SettingDef("dashboard_compare_previous", "مقایسهٔ داشبورد با دورهٔ قبل", GROUP_REPORTING,
               TYPE_BOOL, True),
    SettingDef("dashboard_refresh_seconds", "فاصلهٔ تازه‌سازی خودکار داشبورد (ثانیه)",
               GROUP_REPORTING, TYPE_INT, 300, min_value=0, max_value=3600,
               help_fa="صفر یعنی تازه‌سازی خودکار خاموش است."),
    # ---------------------------------------------------------------- update
    SettingDef("update_source", "منبع بررسی به‌روزرسانی", GROUP_UPDATE, TYPE_STRING, "",
               max_length=400,
               help_fa=("نشانی فایل یا وب‌سرور فهرست نسخه‌ها (مانیفست JSON). خالی یعنی "
                        "کانال به‌روزرسانی تنظیم نشده است و برنامه ادعایی نمی‌کند.")),
    SettingDef("update_channel", "کانال انتشار", GROUP_UPDATE, TYPE_CHOICE, "stable",
               choices=(("stable", "پایدار"), ("beta", "آزمایشی")),
               help_fa="کانال آزمایشی نسخه‌های پیش‌انتشار را هم نشان می‌دهد."),
    SettingDef("update_check_on_startup", "بررسی به‌روزرسانی در شروع برنامه", GROUP_UPDATE,
               TYPE_BOOL, False,
               help_fa="اگر منبع تنظیم نشده باشد، بررسی انجام نمی‌شود."),
    SettingDef("update_require_signature", "الزام امضای دیجیتال بستهٔ به‌روزرسانی",
               GROUP_UPDATE, TYPE_BOOL, True,
               help_fa=("تا وقتی کلید عمومی امضا تنظیم نشده باشد، هیچ بسته‌ای «تأییدشده» "
                        "شمرده نمی‌شود و نصب خودکار انجام نمی‌گیرد.")),
    SettingDef("update_public_key", "کلید عمومی امضای بسته (Ed25519، base64)", GROUP_UPDATE,
               TYPE_STRING, "", max_length=200,
               help_fa=("کلید عمومی که امضای بسته‌های به‌روزرسانی با آن بررسی می‌شود. خالی "
                        "یعنی امضا قابل بررسی نیست؛ این وضعیت به کاربر گزارش می‌شود.")),
    SettingDef("update_last_check_at", "زمان آخرین بررسی به‌روزرسانی", GROUP_UPDATE,
               TYPE_STRING, "", max_length=40),
)

SETTINGS_BY_KEY: dict[str, SettingDef] = {d.key: d for d in SETTING_DEFS}

#: Keys that must never be silently dropped, even when a stored value is invalid.
_STRICT_DEFAULTS = {d.key: d.default for d in SETTING_DEFS}


@dataclass(frozen=True)
class SettingsSnapshot:
    """Immutable view of all current settings (DB overrides over defaults)."""

    values: dict[str, Any]

    def raw(self, key: str) -> Any:
        if key in self.values:
            return self.values[key]
        if key in _STRICT_DEFAULTS:
            return _STRICT_DEFAULTS[key]
        raise KeyError(key)

    def str(self, key: str) -> str:
        value = self.raw(key)
        return "" if value is None else str(value)

    def int(self, key: str) -> int:
        try:
            return int(self.raw(key))
        except (TypeError, ValueError):
            return int(_STRICT_DEFAULTS.get(key, 0))

    def bool(self, key: str) -> bool:
        return bool(self.raw(key))

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)

    # convenience accessors used across the UI
    @property
    def app_name(self) -> str:
        return self.str("app_name") or APP_NAME_DEFAULT

    @property
    def company_name(self) -> str:
        return self.str("company_name")

    @property
    def currency_code(self) -> str:
        return self.str("currency_code") or DEFAULT_CURRENCY_CODE

    @property
    def theme(self) -> str:
        return self.str("theme") or "light"

    @property
    def font_family(self) -> str:
        return self.str("font_family") or "Vazirmatn"

    @property
    def font_size(self) -> int:
        return self.int("font_size")

    @property
    def persian_digits(self) -> bool:
        return self.bool("persian_digits")

    @property
    def idle_lock_minutes(self) -> int:
        return self.int("idle_lock_minutes")

    @property
    def max_failed_attempts(self) -> int:
        return self.int("max_failed_attempts")

    @property
    def lockout_minutes(self) -> int:
        return self.int("lockout_minutes")

    @property
    def password_min_length(self) -> int:
        return self.int("password_min_length")

    @property
    def table_page_size(self) -> int:
        return self.int("table_page_size")

    @property
    def backup_retention(self) -> int:
        return self.int("backup_retention")


class SettingsService:
    def __init__(self, db: Database, audit: AuditService | None = None) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------------ read
    def snapshot(self) -> SettingsSnapshot:
        values = {d.key: d.default for d in SETTING_DEFS}
        with self.db.session_scope() as session:
            for row in session.execute(select(AppSetting)).scalars():
                definition = SETTINGS_BY_KEY.get(row.key)
                if definition is None:
                    continue  # obsolete or unknown key: ignore, never crash the app
                try:
                    values[row.key] = definition.coerce(row.value)
                except ValidationError:
                    # Corrupted/legacy value: fall back to the default rather than
                    # blocking application startup.
                    values[row.key] = definition.default
        return SettingsSnapshot(values)

    def get(self, key: str) -> Any:
        return self.snapshot().raw(key)

    # ----------------------------------------------------------------- write
    def update(self, ctx: SecurityContext | None, updates: dict[str, Any]) -> dict[str, Any]:
        """Validate all values first, then persist them atomically.

        Returns the dict of actually changed ``{key: value}`` pairs.
        """
        require_permission(ctx, "settings.edit")
        if not updates:
            return {}
        validated: dict[str, Any] = {}
        for key, raw_value in updates.items():
            definition = SETTINGS_BY_KEY.get(key)
            if definition is None:
                raise ValidationError(f"تنظیم «{key}» شناخته‌شده نیست.", field=key)
            validated[key] = definition.coerce(raw_value)

        current = self.snapshot()
        changed = {k: v for k, v in validated.items() if current.raw(k) != v}
        if not changed:
            return {}

        with self.db.session_scope() as session:
            for key, value in changed.items():
                row = session.get(AppSetting, key)
                if row is None:
                    row = AppSetting(key=key, value=value, updated_by_id=ctx.user_id if ctx else None)
                    session.add(row)
                else:
                    row.value = value
                    row.updated_by_id = ctx.user_id if ctx else None
            if self.audit is not None:
                before = {k: current.raw(k) for k in changed}
                labels = {SETTINGS_BY_KEY[k].label_fa: v for k, v in changed.items()}
                self.audit.log_audit(
                    ctx=ctx, entity_type="app_setting", entity_id=",".join(sorted(changed)),
                    action="update",
                    summary_fa="تغییر تنظیمات: " + "، ".join(sorted(
                        SETTINGS_BY_KEY[k].label_fa for k in changed)),
                    before=before, after=changed, session=session)
                self.audit.log_security(
                    event_type=EventType.SETTINGS_UPDATED,
                    message_fa=f"تنظیمات تغییر کرد: {'، '.join(sorted(labels))}",
                    ctx=ctx, details=changed, session=session)
        return changed

    def reset_to_defaults(self, ctx: SecurityContext | None, keys: Sequence[str]) -> dict[str, Any]:
        require_permission(ctx, "settings.edit")
        defaults = {k: SETTINGS_BY_KEY[k].default for k in keys if k in SETTINGS_BY_KEY}
        return self.update(ctx, defaults)

    # ------------------------------------------------------------- metadata
    @staticmethod
    def definitions() -> tuple[SettingDef, ...]:
        return SETTING_DEFS

    @staticmethod
    def definitions_by_group() -> dict[str, list[SettingDef]]:
        grouped: dict[str, list[SettingDef]] = {code: [] for code, _ in SETTING_GROUPS}
        for definition in SETTING_DEFS:
            grouped.setdefault(definition.group, []).append(definition)
        return grouped

    @staticmethod
    def group_titles() -> list[tuple[str, str]]:
        return list(SETTING_GROUPS)
