"""Shared, Qt-free helpers for the phase-5 HR / payroll / asset services.

Everything that three services would otherwise implement slightly differently
lives here: working-day arithmetic, Jalali month bounds, time parsing for
attendance and the guard that hides salary and national-id data from users who
may see an employee file but not its sensitive fields.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pars_erp.core.errors import ValidationError
from pars_erp.core.jalali import (days_in_month, gregorian_to_jalali,
                                  jalali_to_gregorian)
from pars_erp.db.models import Employee, OrgUnit

ZERO = Decimal("0.00")
MONEY = Decimal("0.01")


# --------------------------------------------------------------------- numbers
def to_money(value, *, field: str = "amount") -> Decimal:
    """Parse a money input; floats are rejected because money is never binary."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, float):
        raise ValidationError("برای مبلغ نمی‌توان از عدد اعشاری ممیز شناور استفاده کرد.",
                              field=field)
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(MONEY)


def to_decimal(value, *, field: str = "value", default: Decimal = ZERO) -> Decimal:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        raise ValidationError("عدد اعشاری ممیز شناور برای این مقدار مجاز نیست.",
                              field=field)
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ------------------------------------------------------------------- calendars
def saturday_index(value: _dt.date) -> int:
    """0 = Saturday … 6 = Friday (the company calendar, not ``date.weekday``)."""
    return (value.weekday() + 2) % 7


def parse_weekdays(text: str | None) -> tuple[int, ...]:
    if not text:
        return (0, 1, 2, 3, 4, 5)
    parts = []
    for chunk in str(text).replace("،", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            index = int(chunk)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValidationError("فهرست روزهای کاری معتبر نیست.", field="workdays") from exc
        if not 0 <= index <= 6:
            raise ValidationError("روز کاری باید بین ۰ (شنبه) تا ۶ (جمعه) باشد.",
                                  field="workdays")
        parts.append(index)
    return tuple(sorted(set(parts))) or (0, 1, 2, 3, 4, 5)


def is_working_day(value: _dt.date, weekdays: tuple[int, ...]) -> bool:
    return saturday_index(value) in weekdays


def working_days_between(start: _dt.date, end: _dt.date,
                         weekdays: tuple[int, ...]) -> int:
    if end < start:
        return 0
    total = 0
    cursor = start
    while cursor <= end:
        if is_working_day(cursor, weekdays):
            total += 1
        cursor += _dt.timedelta(days=1)
    return total


def jalali_year(value: _dt.date) -> int:
    return gregorian_to_jalali(value)[0]


def month_range(year: int, month: int) -> tuple[_dt.date, _dt.date]:
    """Gregorian ``(first, last)`` day of a Jalali month."""
    first = jalali_to_gregorian(int(year), int(month), 1)
    last = jalali_to_gregorian(int(year), int(month), days_in_month(int(year),
                                                                   int(month)))
    return first, last


def month_bounds_from(value: _dt.date) -> tuple[int, int, _dt.date, _dt.date]:
    year, month, _day = gregorian_to_jalali(value)
    start, end = month_range(year, month)
    return year, month, start, end


# ----------------------------------------------------------------------- times
def parse_time(value) -> _dt.time | None:
    """Accept ``datetime.time``, ``"08:30"``/``"8:30"`` or Jalali-free text."""
    if value in (None, ""):
        return None
    if isinstance(value, _dt.time):
        return value
    if isinstance(value, _dt.datetime):
        return value.time()
    text = str(value).strip().replace("٫", ":").replace(".", ":")
    parts = text.split(":")
    if len(parts) < 2:
        raise ValidationError("ساعت باید به شکل ۰۸:۳۰ باشد.", field="time")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValidationError("ساعت باید به شکل ۰۸:۳۰ باشد.", field="time") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValidationError("ساعت واردشده معتبر نیست.", field="time")
    return _dt.time(hour, minute)


def minutes_of(value: _dt.time | None) -> int:
    return 0 if value is None else value.hour * 60 + value.minute


def combine(value: _dt.date, clock: _dt.time) -> _dt.datetime:
    return _dt.datetime.combine(value, clock)


def diff_minutes(start: _dt.time | None, end: _dt.time | None) -> int:
    """Minutes between two clocks, correctly handling a night shift over midnight."""
    if start is None or end is None:
        return 0
    minutes = minutes_of(end) - minutes_of(start)
    if minutes < 0:
        minutes += 24 * 60
    return minutes


# -------------------------------------------------------------------- lookups
def org_unit_path(session: Session, unit: OrgUnit | None) -> str:
    """``شرکت / شعبه / واحد`` for display, walking up the parent chain."""
    if unit is None:
        return ""
    parts: list[str] = []
    seen: set[int] = set()
    current = unit
    while current is not None and current.id not in seen:
        seen.add(current.id)
        parts.append(current.title_fa)
        current = session.get(OrgUnit, current.parent_id) if current.parent_id else None
    return " / ".join(reversed(parts))


def employee_full_name(employee: Employee | None) -> str:
    if employee is None:
        return ""
    return f"{employee.first_name} {employee.last_name}".strip()


def employee_choices(session: Session, *, active_only: bool = True) -> list[tuple[int, str]]:
    query = select(Employee).order_by(Employee.code)
    if active_only:
        query = query.where(Employee.is_active.is_(True))
    return [(row.id, f"{row.code} — {employee_full_name(row)}")
            for row in session.execute(query).scalars()]


def mask(value: str | None, *, keep: int = 4) -> str:
    """Hide all but the last ``keep`` characters (used when permission is missing)."""
    if not value:
        return ""
    text = str(value)
    if len(text) <= keep:
        return "•" * len(text)
    return "•" * (len(text) - keep) + text[-keep:]
