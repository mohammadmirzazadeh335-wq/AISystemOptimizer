"""Qt-free table column definitions and value extraction.

Screens describe their tables declaratively; the Qt model in
:mod:`pars_erp.ui.widgets.table` renders them. Because the column definitions are
plain Python, the formatting rules (Persian digits, Jalali dates, money, status
badges) are unit-testable without a display.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

from pars_erp.ui.formatting import DASH, Formatter

TEXT = "text"
AMOUNT = "amount"
DATE = "date"
DATETIME = "datetime"
BOOL = "bool"
NUMBER = "number"
BADGE = "badge"


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    title_fa: str
    kind: str = TEXT
    width: int | None = None
    align: str = "right"  # RTL default
    getter: Callable[[Any], Any] | None = None
    hint_fa: str = ""

    def value_of(self, row: Any) -> Any:
        if self.getter is not None:
            return self.getter(row)
        if isinstance(row, dict):
            return row.get(self.key)
        return getattr(row, self.key, None)


@dataclass(frozen=True)
class BadgeStyle:
    tone: str  # success | warning | danger | info | neutral
    label_fa: str


BADGE_TONES: dict[str, BadgeStyle] = {
    "active": BadgeStyle("success", "فعال"),
    "inactive": BadgeStyle("neutral", "غیرفعال"),
    "locked": BadgeStyle("danger", "قفل‌شده"),
    "info": BadgeStyle("info", "اطلاع"),
    "warning": BadgeStyle("warning", "هشدار"),
    "critical": BadgeStyle("danger", "بحرانی"),
    "system": BadgeStyle("info", "سیستمی"),
    "custom": BadgeStyle("neutral", "سفارشی"),
    "verified": BadgeStyle("success", "تأییدشده"),
    "created": BadgeStyle("neutral", "ایجادشده"),
    "deleted": BadgeStyle("neutral", "حذف‌شده"),
    # ---------------------------------------------------------------- treasury
    "draft": BadgeStyle("neutral", "پیش‌نویس"),
    "approved": BadgeStyle("info", "تأییدشده"),
    "posted": BadgeStyle("success", "ثبت نهایی"),
    "void": BadgeStyle("danger", "ابطال‌شده"),
    "in_safe": BadgeStyle("info", "نزد صندوق"),
    "deposited": BadgeStyle("info", "واگذارشده به بانک"),
    "collected": BadgeStyle("success", "وصول‌شده"),
    "bounced": BadgeStyle("danger", "برگشت‌خورده"),
    "spent": BadgeStyle("neutral", "خرج‌شده"),
    "transferred": BadgeStyle("neutral", "منتقل‌شده"),
    "issued": BadgeStyle("info", "صادرشده"),
    "delivered": BadgeStyle("info", "تحویل‌شده"),
    "pending": BadgeStyle("warning", "در انتظار وصول"),
    "paid": BadgeStyle("success", "وصول‌شده (پرداخت)"),
    "returned": BadgeStyle("danger", "برگشت‌خورده (پرداخت)"),
    "cancelled": BadgeStyle("neutral", "باطل‌شده"),
    "matched": BadgeStyle("success", "تطبیق‌شده"),
    "unmatched": BadgeStyle("warning", "تطبیق‌نشده"),
    "ignored": BadgeStyle("neutral", "نادیده‌گرفته"),
    # ------------------------------------------------- phase 5: hr / payroll / assets
    "active_contract": BadgeStyle("success", "قرارداد جاری"),
    "expired": BadgeStyle("warning", "منقضی"),
    "terminated": BadgeStyle("neutral", "خاتمه‌یافته"),
    "renewed": BadgeStyle("info", "تمدیدشده"),
    "requested": BadgeStyle("warning", "درخواست‌شده"),
    "rejected": BadgeStyle("danger", "رد‌شده"),
    "submitted": BadgeStyle("warning", "در انتظار تأیید"),
    "present": BadgeStyle("success", "حاضر"),
    "late": BadgeStyle("warning", "تأخیر"),
    "absent": BadgeStyle("danger", "غیبت"),
    "leave": BadgeStyle("info", "مرخصی"),
    "mission": BadgeStyle("info", "مأموریت"),
    "holiday": BadgeStyle("neutral", "تعطیل"),
    "calculated": BadgeStyle("info", "محاسبه‌شده"),
    "closed": BadgeStyle("success", "بسته‌شده"),
    "partial": BadgeStyle("warning", "پرداخت ناقص"),
    "failed": BadgeStyle("danger", "ناموفق"),
    "deducted": BadgeStyle("success", "کسر‌شده"),
    "in_use": BadgeStyle("success", "در بهره‌برداری"),
    "idle": BadgeStyle("warning", "بی‌استفاده"),
    "under_repair": BadgeStyle("warning", "در تعمیر"),
    "sold": BadgeStyle("neutral", "فروخته‌شده"),
    "retired": BadgeStyle("neutral", "کنارگذاشته‌شده"),
    "written_off": BadgeStyle("danger", "اسقاط‌شده"),
    "sensitive": BadgeStyle("warning", "محرمانه"),
    "suspended": BadgeStyle("warning", "تعلیق موقت"),
    "left": BadgeStyle("neutral", "ترک خدمت"),
    "retired_employee": BadgeStyle("neutral", "بازنشسته"),
    "archived": BadgeStyle("neutral", "بایگانی‌شده"),
}


def format_cell(column: ColumnSpec, row: Any, formatter: Formatter) -> str:
    """Render one cell to display text (used by the model and by CSV exports)."""
    raw = column.value_of(row)
    if column.kind == AMOUNT:
        return formatter.amount(raw if raw is not None else None)
    if column.kind == DATE:
        return formatter.date(raw)
    if column.kind == DATETIME:
        return formatter.datetime(raw)
    if column.kind == BOOL:
        return formatter.yes_no(bool(raw) if raw is not None else None)
    if column.kind == NUMBER:
        return formatter.number(raw if isinstance(raw, (int, float)) else None)
    if column.kind == BADGE:
        style = BADGE_TONES.get(str(raw))
        return style.label_fa if style else formatter.text(raw)
    if raw is None or raw == "":
        return DASH
    if isinstance(raw, (list, tuple)):
        return "، ".join(str(item) for item in raw) or DASH
    return str(raw)


def badge_tone(column: ColumnSpec, row: Any) -> str | None:
    if column.kind != BADGE:
        return None
    raw = str(column.value_of(row))
    style = BADGE_TONES.get(raw)
    return style.tone if style else "neutral"


# --------------------------------------------------------------------- specs
USER_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("username", "نام کاربری", TEXT, 130, "right"),
    ColumnSpec("full_name", "نام و نام خانوادگی", TEXT, 190),
    ColumnSpec("roles_fa", "نقش‌ها", TEXT, 170),
    ColumnSpec("status_fa", "وضعیت", BADGE, 90, "center",
               getter=lambda row: "locked" if row.is_locked else
               ("active" if row.is_active else "inactive")),
    ColumnSpec("last_login_at", "آخرین ورود", DATETIME, 158),
    ColumnSpec("created_at", "تاریخ ایجاد", DATETIME, 158),
    ColumnSpec("email", "ایمیل", TEXT, None),
)

ROLE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("title_fa", "عنوان نقش", TEXT, 150),
    ColumnSpec("code", "کد", TEXT, 104),
    ColumnSpec("kind_fa", "نوع", BADGE, 92, "center",
               getter=lambda row: "system" if row.is_system else "custom"),
    ColumnSpec("permissions_count", "تعداد مجوز", NUMBER, 86, "center"),
    ColumnSpec("member_count", "کاربران", NUMBER, 72, "center"),
    # the full description is shown in the details panel next to the table
)

SECURITY_EVENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("occurred_at", "زمان", DATETIME, 158),
    ColumnSpec("event_title_fa", "رویداد", TEXT, 160),
    ColumnSpec("severity", "سطح", BADGE, 80, "center"),
    ColumnSpec("username", "کاربر", TEXT, 110),
    ColumnSpec("message_fa", "شرح", TEXT, None),
    ColumnSpec("hostname", "رایانه", TEXT, 120),
)

AUDIT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("occurred_at", "زمان", DATETIME, 158),
    ColumnSpec("actor_username", "کاربر", TEXT, 110),
    ColumnSpec("entity_type", "نوع موجودیت", TEXT, 110),
    ColumnSpec("entity_id", "شناسه", TEXT, 80, "center"),
    ColumnSpec("action", "عملیات", TEXT, 110),
    ColumnSpec("summary_fa", "شرح", TEXT, None),
)

BACKUP_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("filename", "نام فایل", TEXT, 250),
    ColumnSpec("created_at", "زمان", DATETIME, 158),
    ColumnSpec("kind_fa", "نوع", TEXT, 100, "center"),
    ColumnSpec("size_mb", "حجم (مگابایت)", NUMBER, 110, "center",
               getter=lambda row: int(round(row.size_mb))),
    ColumnSpec("note", "یادداشت", TEXT, None),
)


# ------------------------------------------------------- phase 5: hr / payroll
EMPLOYEE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد پرسنلی", TEXT, 104, "center"),
    ColumnSpec("full_name", "نام و نام خانوادگی", TEXT, 190),
    ColumnSpec("org_unit_title", "واحد سازمانی", TEXT, 160),
    ColumnSpec("job_title", "عنوان شغلی", TEXT, 150),
    ColumnSpec("employment_type_fa", "نوع استخدام", TEXT, 110, "center"),
    ColumnSpec("collaboration_status_fa", "وضعیت", BADGE, 100, "center",
               getter=lambda row: {"active": "active", "suspended": "suspended",
                                   "left": "left", "retired": "retired_employee"}.get(
                                       row.collaboration_status, "info")),
    ColumnSpec("hire_date", "تاریخ استخدام", DATE, 104, "center"),
    ColumnSpec("mobile", "همراه", TEXT, 120, "center"),
    ColumnSpec("base_salary", "حقوق پایه", AMOUNT, 140),
)

CONTRACT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره قرارداد", TEXT, 130, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("contract_type_fa", "نوع قرارداد", TEXT, 110, "center"),
    ColumnSpec("start_date", "شروع", DATE, 100, "center"),
    ColumnSpec("end_date", "پایان", DATE, 100, "center"),
    ColumnSpec("base_salary", "حقوق پایه", AMOUNT, 140),
    ColumnSpec("working_hours_weekly", "ساعت هفتگی", NUMBER, 100, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 110, "center"),
    ColumnSpec("days_to_expiry", "روز تا انقضا", NUMBER, 110, "center"),
)

ATTENDANCE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("work_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("employee_code", "کد", TEXT, 90, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("shift_title", "شیفت", TEXT, 110, "center"),
    ColumnSpec("check_in", "ورود", TEXT, 90, "center"),
    ColumnSpec("check_out", "خروج", TEXT, 90, "center"),
    ColumnSpec("worked_minutes", "کارکرد (دقیقه)", NUMBER, 120, "center"),
    ColumnSpec("late_minutes", "تأخیر", NUMBER, 90, "center"),
    ColumnSpec("overtime_minutes", "اضافه‌کار", NUMBER, 100, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 100, "center"),
)

SHIFT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان شیفت", TEXT, 150),
    ColumnSpec("kind_fa", "نوع", TEXT, 100, "center"),
    ColumnSpec("start_time", "شروع", TEXT, 80, "center"),
    ColumnSpec("end_time", "پایان", TEXT, 80, "center"),
    ColumnSpec("break_minutes", "استراحت (دقیقه)", NUMBER, 120, "center"),
    ColumnSpec("grace_minutes", "مهلت (دقیقه)", NUMBER, 110, "center"),
    ColumnSpec("duration_minutes", "مدت (دقیقه)", NUMBER, 110, "center"),
)

LEAVE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 120, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("leave_type", "نوع مرخصی", TEXT, 130),
    ColumnSpec("date_from", "از", DATE, 100, "center"),
    ColumnSpec("date_to", "تا", DATE, 100, "center"),
    ColumnSpec("days", "روز", NUMBER, 70, "center"),
    ColumnSpec("hours", "ساعت", NUMBER, 80, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
    ColumnSpec("reason", "علت", TEXT, None),
)

MISSION_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 120, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("destination", "مقصد", TEXT, 150),
    ColumnSpec("date_from", "از", DATE, 100, "center"),
    ColumnSpec("date_to", "تا", DATE, 100, "center"),
    ColumnSpec("days", "روز", NUMBER, 70, "center"),
    ColumnSpec("cost", "هزینه", AMOUNT, 130),
    ColumnSpec("allowance", "کمک‌هزینه", AMOUNT, 130),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
)

OVERTIME_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("work_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("hours", "ساعت", NUMBER, 80, "center"),
    ColumnSpec("is_holiday", "تعطیل", BOOL, 80, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
    ColumnSpec("reason", "علت", TEXT, None),
)

BALANCE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("leave_type", "نوع مرخصی", TEXT, 140),
    ColumnSpec("period_year", "سال", NUMBER, 80, "center"),
    ColumnSpec("entitled_days", "سهمیه", NUMBER, 90, "center"),
    ColumnSpec("carried_days", "انتقالی", NUMBER, 90, "center"),
    ColumnSpec("adjusted_days", "تعدیل", NUMBER, 90, "center"),
    ColumnSpec("used_days", "استفاده‌شده", NUMBER, 110, "center"),
    ColumnSpec("remaining_days", "مانده", NUMBER, 90, "center"),
)

# -------------------------------------------------------------------- payroll
PAY_VERSION_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد نسخه", TEXT, 120, "center"),
    ColumnSpec("title_fa", "عنوان", TEXT, None),
    ColumnSpec("effective_from", "از تاریخ", DATE, 100, "center"),
    ColumnSpec("effective_to", "تا تاریخ", DATE, 100, "center"),
    ColumnSpec("status_fa", "وضعیت", BADGE, 100, "center"),
    ColumnSpec("source_note", "منبع/مبنای قانونی", TEXT, 200),
)

PAY_RUN_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره دوره", TEXT, 130, "center"),
    ColumnSpec("period_start", "شروع دوره", DATE, 100, "center"),
    ColumnSpec("period_end", "پایان دوره", DATE, 100, "center"),
    ColumnSpec("settings_version", "نسخه تنظیمات", TEXT, 130, "center"),
    ColumnSpec("employees_count", "تعداد کارمند", NUMBER, 110, "center"),
    ColumnSpec("gross_total", "جمع ناخالص", AMOUNT, 140),
    ColumnSpec("deductions_total", "جمع کسور", AMOUNT, 140),
    ColumnSpec("net_total", "جمع خالص", AMOUNT, 140),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
)

PAYSLIP_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره فیش", TEXT, 130, "center"),
    ColumnSpec("employee_code", "کد", TEXT, 90, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("org_unit", "واحد", TEXT, 140),
    ColumnSpec("worked_days", "روز کارکرد", NUMBER, 100, "center"),
    ColumnSpec("overtime_hours", "اضافه‌کار", NUMBER, 90, "center"),
    ColumnSpec("gross", "جمع حقوق", AMOUNT, 140),
    ColumnSpec("deductions_total", "کسور", AMOUNT, 130),
    ColumnSpec("net", "پرداختی", AMOUNT, 140),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
)

PAYSLIP_LINE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("title_fa", "عنوان", TEXT, None),
    ColumnSpec("side", "نوع", TEXT, 90, "center",
               getter=lambda row: "درآمد" if row.side == "earning" else "کسور"),
    ColumnSpec("amount", "مبلغ", AMOUNT, 150),
    ColumnSpec("detail", "توضیح محاسبه", TEXT, 220),
)

LOAN_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 120, "center"),
    ColumnSpec("employee_code", "کد", TEXT, 90, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("kind_fa", "نوع", TEXT, 100, "center"),
    ColumnSpec("amount", "مبلغ", AMOUNT, 140),
    ColumnSpec("installments", "تعداد قسط", NUMBER, 100, "center"),
    ColumnSpec("installment_amount", "مبلغ قسط", AMOUNT, 140),
    ColumnSpec("remaining_debt", "بدهی باقی‌مانده", AMOUNT, 150),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
)

INSTALLMENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("seq", "قسط", NUMBER, 70, "center"),
    ColumnSpec("due_year", "سال", NUMBER, 80, "center"),
    ColumnSpec("due_month", "ماه", NUMBER, 80, "center"),
    ColumnSpec("amount", "مبلغ", AMOUNT, 140),
    ColumnSpec("paid_amount", "پرداخت‌شده", AMOUNT, 140),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
    ColumnSpec("paid_date", "تاریخ پرداخت", DATE, 110, "center"),
)

BATCH_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره دسته", TEXT, 130, "center"),
    ColumnSpec("run_number", "دوره حقوق", TEXT, 120, "center"),
    ColumnSpec("payment_date", "تاریخ پرداخت", DATE, 110, "center"),
    ColumnSpec("items_count", "تعداد فیش", NUMBER, 100, "center"),
    ColumnSpec("total_amount", "مبلغ کل", AMOUNT, 150),
    ColumnSpec("paid_amount", "پرداخت‌شده", AMOUNT, 150),
    ColumnSpec("status", "وضعیت", BADGE, 120, "center"),
    ColumnSpec("bank_file_name", "فایل بانکی", TEXT, 200),
)

BATCH_ITEM_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("employee_code", "کد", TEXT, 90, "center"),
    ColumnSpec("employee_name", "کارمند", TEXT, 170),
    ColumnSpec("iban", "شبا", TEXT, 200, "center"),
    ColumnSpec("amount", "مبلغ", AMOUNT, 140),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
    ColumnSpec("tracking_no", "شماره پیگیری", TEXT, 140, "center"),
    ColumnSpec("failure_reason", "علت ناموفق", TEXT, None),
)

# --------------------------------------------------------------------- assets
ASSET_CATEGORY_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان دسته", TEXT, None),
    ColumnSpec("kind_fa", "نوع", TEXT, 110, "center"),
    ColumnSpec("default_useful_life_years", "عمر (سال)", NUMBER, 100, "center"),
    ColumnSpec("default_method_fa", "روش استهلاک", TEXT, 140, "center"),
    ColumnSpec("assets_count", "تعداد دارایی", NUMBER, 110, "center"),
)

ASSET_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد دارایی", TEXT, 110, "center"),
    ColumnSpec("title_fa", "عنوان", TEXT, 190),
    ColumnSpec("category", "دسته", TEXT, 130),
    ColumnSpec("location", "محل", TEXT, 130),
    ColumnSpec("custodian_name", "امانت‌دار", TEXT, 150),
    ColumnSpec("in_service_date", "شروع بهره‌برداری", DATE, 130, "center"),
    ColumnSpec("initial_value", "بهای تمام‌شده", AMOUNT, 150),
    ColumnSpec("accumulated", "استهلاک انباشته", AMOUNT, 150),
    ColumnSpec("book_value", "ارزش دفتری", AMOUNT, 150),
    ColumnSpec("status", "وضعیت", BADGE, 120, "center"),
)

ASSET_MOVEMENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("movement_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("kind_fa", "نوع رویداد", TEXT, 130),
    ColumnSpec("from_value", "از", TEXT, 170),
    ColumnSpec("to_value", "به", TEXT, 170),
    ColumnSpec("user_name", "کاربر", TEXT, 120, "center"),
    ColumnSpec("note", "توضیح", TEXT, None),
)

MAINTENANCE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("service_date", "تاریخ سرویس", DATE, 110, "center"),
    ColumnSpec("asset_code", "کد دارایی", TEXT, 110, "center"),
    ColumnSpec("asset_title", "دارایی", TEXT, 170),
    ColumnSpec("kind_fa", "نوع", TEXT, 110, "center"),
    ColumnSpec("cost", "هزینه", AMOUNT, 140),
    ColumnSpec("contractor", "پیمانکار", TEXT, 150),
    ColumnSpec("next_service_date", "سرویس بعدی", DATE, 110, "center"),
    ColumnSpec("description", "شرح", TEXT, None),
)

DEPRECIATION_RUN_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 130, "center"),
    ColumnSpec("year", "سال", NUMBER, 80, "center"),
    ColumnSpec("month", "ماه", NUMBER, 80, "center"),
    ColumnSpec("period_end", "پایان دوره", DATE, 110, "center"),
    ColumnSpec("assets_count", "تعداد دارایی", NUMBER, 110, "center"),
    ColumnSpec("total_amount", "جمع استهلاک", AMOUNT, 150),
    ColumnSpec("status", "وضعیت", BADGE, 110, "center"),
)

DEPRECIATION_LINE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("asset_code", "کد دارایی", TEXT, 110, "center"),
    ColumnSpec("asset_title", "دارایی", TEXT, 180),
    ColumnSpec("category", "دسته", TEXT, 120),
    ColumnSpec("method_fa", "روش", TEXT, 120, "center"),
    ColumnSpec("opening_value", "ارزش آغاز", AMOUNT, 140),
    ColumnSpec("amount", "استهلاک ماه", AMOUNT, 140),
    ColumnSpec("accumulated_after", "استهلاک انباشته", AMOUNT, 150),
    ColumnSpec("book_value_after", "ارزش دفتری", AMOUNT, 140),
)

DISPOSAL_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", TEXT, 120, "center"),
    ColumnSpec("asset_code", "کد دارایی", TEXT, 110, "center"),
    ColumnSpec("asset_title", "دارایی", TEXT, 170),
    ColumnSpec("kind_fa", "نوع", TEXT, 110, "center"),
    ColumnSpec("disposal_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("book_value", "ارزش دفتری", AMOUNT, 140),
    ColumnSpec("sale_amount", "مبلغ فروش", AMOUNT, 140),
    ColumnSpec("gain_loss", "سود/زیان", AMOUNT, 140),
)

HISTORY_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("effective_date", "تاریخ اجرا", DATE, 110, "center"),
    ColumnSpec("kind_fa", "نوع تغییر", TEXT, 140),
    ColumnSpec("from_value", "مقدار قبلی", TEXT, 180),
    ColumnSpec("to_value", "مقدار جدید", TEXT, 180),
    ColumnSpec("user_name", "کاربر", TEXT, 120, "center"),
    ColumnSpec("note", "توضیح", TEXT, None),
)
