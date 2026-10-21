"""Time and formatting helpers shared by services and widgets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite friendly, always comparable).

    Microseconds are preserved so that two messages written in the same second
    still sort deterministically.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    aware = as_utc(value)
    return aware.astimezone() if aware else None


def format_bytes(size: float) -> str:
    size = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.1f} s"


def format_clock(value: datetime | None, language: str = "en") -> str:
    local = to_local(value)
    if not local:
        return ""
    if language == "fa":
        return f"{local.hour:02d}:{local.minute:02d}"
    return local.strftime("%H:%M")


PERSIAN_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to the Solar Hijri calendar (no dependencies)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    for i in range(11):
        if j_day_no < (31 if i < 6 else 30):
            return jy, i + 1, j_day_no + 1
        j_day_no -= 31 if i < 6 else 30
    return jy, 12, j_day_no + 1


def format_date(value: datetime | None, language: str = "en") -> str:
    local = to_local(value)
    if not local:
        return ""
    if language == "fa":
        jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
        return f"{jd} {PERSIAN_MONTHS[jm - 1]} {jy}"
    return local.strftime("%b %d, %Y")


def format_datetime(value: datetime | None, language: str = "en") -> str:
    local = to_local(value)
    if not local:
        return ""
    return f"{format_date(value, language)} · {local:%H:%M}"


def relative_time(value: datetime | None, language: str = "en") -> str:
    local = to_local(value)
    if not local:
        return ""
    now = datetime.now().astimezone()
    diff = now - local
    seconds = max(0, diff.total_seconds())
    fa = language == "fa"
    if seconds < 60:
        return "همین حالا" if fa else "just now"
    if seconds < 3600:
        n = int(seconds // 60)
        return f"{n} دقیقه پیش" if fa else f"{n}m ago"
    if seconds < 86400:
        n = int(seconds // 3600)
        return f"{n} ساعت پیش" if fa else f"{n}h ago"
    if seconds < 172800:
        return "دیروز" if fa else "yesterday"
    days = int(seconds // 86400)
    if days < 7:
        return f"{days} روز پیش" if fa else f"{days}d ago"
    return format_date(value, language)


def group_label(value: datetime | None, language: str = "en") -> str:
    local = to_local(value)
    if not local:
        return ""
    today = datetime.now().astimezone().date()
    day = local.date()
    if day == today:
        return "امروز" if language == "fa" else "Today"
    if day == today - timedelta(days=1):
        return "دیروز" if language == "fa" else "Yesterday"
    if (today - day).days < 30:
        return "پیش‌تر" if language == "fa" else "Earlier"
    return format_date(value, language)
