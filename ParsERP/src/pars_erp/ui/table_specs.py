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
