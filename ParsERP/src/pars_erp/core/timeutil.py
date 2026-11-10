"""Time zone helpers.

All timestamps are stored in UTC. The UI and "today" calculations use the
configured local time zone (default ``Asia/Tehran``), with a fixed-offset
fallback so the application still works on machines without a tz database.
"""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache

DEFAULT_TIMEZONE = "Asia/Tehran"
_IRAN_FALLBACK = _dt.timezone(_dt.timedelta(hours=3, minutes=30), "IRST")


@lru_cache(maxsize=8)
def get_timezone(name: str | None = None) -> _dt.tzinfo:
    candidate = name or DEFAULT_TIMEZONE
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(candidate)
    except Exception:  # missing tzdata (Windows) or unknown name
        return _IRAN_FALLBACK


def now_local(tz_name: str | None = None) -> _dt.datetime:
    return _dt.datetime.now(get_timezone(tz_name))


def to_local(value: _dt.datetime | None, tz_name: str | None = None) -> _dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(get_timezone(tz_name))


def day_bounds_utc(day: _dt.date | None = None, tz_name: str | None = None) -> tuple[_dt.datetime, _dt.datetime]:
    """UTC start/end of a local calendar day (start inclusive, end exclusive)."""
    tz = get_timezone(tz_name)
    local_day = day or _dt.datetime.now(tz).date()
    start_local = _dt.datetime.combine(local_day, _dt.time.min, tzinfo=tz)
    end_local = start_local + _dt.timedelta(days=1)
    return start_local.astimezone(_dt.timezone.utc), end_local.astimezone(_dt.timezone.utc)


def days_ago_utc(days: int, tz_name: str | None = None) -> _dt.datetime:
    """UTC instant at the start of the local day ``days`` days ago."""
    tz = get_timezone(tz_name)
    today = _dt.datetime.now(tz).date()
    return day_bounds_utc(today - _dt.timedelta(days=days), tz_name)[0]


def humanize_delta_fa(value: _dt.datetime | None, *, now: _dt.datetime | None = None,
                      tz_name: str | None = None) -> str:
    """Persian 'x minutes ago' rendering for dashboard cards."""
    if value is None:
        return "—"
    reference = now or _dt.datetime.now(_dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    seconds = int((reference - value).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "لحظه‌ای پیش"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقیقه پیش"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ساعت پیش"
    days = hours // 24
    if days < 30:
        return f"{days} روز پیش"
    months = days // 30
    if months < 12:
        return f"{months} ماه پیش"
    return f"{days // 365} سال پیش"
