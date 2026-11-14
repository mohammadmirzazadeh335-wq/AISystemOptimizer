"""Solar Hijri (Jalali/Shamsi) calendar support.

Storage policy (see docs/ARCHITECTURE.md):
  * every timestamp is stored as an unambiguous UTC datetime (ISO-8601);
  * business *dates* are stored as ISO ``date`` values;
  * the Jalali calendar is a presentation/input concern only.

The conversion algorithm is the well-known arithmetic conversion (Borkowski /
jalaali) which is exact for 1178-1633 Jalali years (1799-2256 CE); we narrow the
accepted range further and validate it.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from pars_erp.core.digits import normalize_text, to_latin_digits
from pars_erp.core.errors import ValidationError

MONTH_NAMES = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)
WEEKDAY_NAMES = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")

MIN_YEAR = 1200
MAX_YEAR = 1600

_BREAKS = (-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178)


def _div(a: int, b: int) -> int:
    """Integer division truncated toward zero (the reference algorithm's ``~~``)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _mod(a: int, b: int) -> int:
    """Remainder with the sign of the dividend (JavaScript ``%`` semantics)."""
    return a - b * _div(a, b)


def _jalali_year_meta(jy: int) -> tuple[int, int, int]:
    """Return ``(leap, gregorian_year_of_nowruz, march_day_of_nowruz)``.

    ``leap`` is 0 for a leap year and 1..4 for the year's position in the
    four-year cycle (identical to the reference jalaali algorithm).
    """
    bl = len(_BREAKS)
    if jy < _BREAKS[0] or jy >= _BREAKS[bl - 1]:
        raise ValidationError(f"سال شمسی خارج از محدوده مجاز است: {jy}", field="year")
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j = leap_j + _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j = leap_j + _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def _gregorian_to_jdn(gy: int, gm: int, gd: int) -> int:
    """Gregorian date -> Julian day number (reference ``g2d``)."""
    d = (_div((gy + _div(gm - 8, 6) + 100100) * 1461, 4)
         + _div(153 * _mod(gm + 9, 12) + 2, 5)
         + gd - 34840408)
    d = d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752
    return d


def _jdn_to_gregorian(jdn: int) -> tuple[int, int, int]:
    """Julian day number -> Gregorian date (reference ``d2g``)."""
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def is_leap_year(jy: int) -> bool:
    """True when the Jalali year has 366 days (Esfand has 30 days)."""
    return _jalali_year_meta(int(jy))[0] == 0


def days_in_month(jy: int, jm: int) -> int:
    if not 1 <= int(jm) <= 12:
        raise ValidationError("ماه شمسی باید بین ۱ تا ۱۲ باشد.", field="month")
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap_year(int(jy)) else 29


def jalali_year_range(jy: int) -> tuple[_dt.date, _dt.date]:
    """Gregorian ``(start, end)`` of a Jalali year (1 Farvardin .. end of Esfand)."""
    jy = int(jy)
    start = jalali_to_gregorian(jy, 1, 1)
    end = jalali_to_gregorian(jy, 12, days_in_month(jy, 12))
    return start, end


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> _dt.date:
    """Convert a Jalali date to a :class:`datetime.date`."""
    jy, jm, jd = int(jy), int(jm), int(jd)
    if not MIN_YEAR <= jy <= MAX_YEAR:
        raise ValidationError(f"سال شمسی باید بین {MIN_YEAR} تا {MAX_YEAR} باشد.", field="year")
    if not 1 <= jm <= 12:
        raise ValidationError("ماه شمسی باید بین ۱ تا ۱۲ باشد.", field="month")
    if not 1 <= jd <= days_in_month(jy, jm):
        raise ValidationError(f"روز {jd} برای {MONTH_NAMES[jm - 1]} {jy} معتبر نیست.", field="day")
    _, gy, march = _jalali_year_meta(jy)
    day_of_year = ((jm - 1) * 31 if jm <= 7 else 186 + (jm - 7) * 30) + jd - 1
    gy2, gm2, gd2 = _jdn_to_gregorian(_gregorian_to_jdn(gy, 3, march) + day_of_year)
    return _dt.date(gy2, gm2, gd2)


def gregorian_to_jalali(value: _dt.date) -> tuple[int, int, int]:
    """Convert a Gregorian date to ``(year, month, day)`` in the Jalali calendar."""
    if isinstance(value, _dt.datetime):
        value = value.date()
    gy, gm, gd = value.year, value.month, value.day
    if not 1799 <= gy <= 2256:
        raise ValidationError("تاریخ خارج از محدوده پشتیبانی‌شده است.", field="date")
    jdn = _gregorian_to_jdn(gy, gm, gd)
    jy = gy - 621
    leap, _, march = _jalali_year_meta(jy)
    jdn_nowruz = _gregorian_to_jdn(gy, 3, march)
    k = jdn - jdn_nowruz
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


@dataclass(frozen=True, order=True)
class JalaliDate:
    """An immutable Jalali calendar date."""

    year: int
    month: int
    day: int

    def __post_init__(self) -> None:
        gy, gm, gd = jalali_to_gregorian(self.year, self.month, self.day).timetuple()[:3]
        # validation already happened inside jalali_to_gregorian

    @classmethod
    def from_gregorian(cls, value: _dt.date | _dt.datetime) -> "JalaliDate":
        if isinstance(value, _dt.datetime):
            value = value.date()
        y, m, d = gregorian_to_jalali(value)
        return cls(y, m, d)

    @classmethod
    def today(cls) -> "JalaliDate":
        return cls.from_gregorian(_dt.date.today())

    def to_gregorian(self) -> _dt.date:
        return jalali_to_gregorian(self.year, self.month, self.day)

    @property
    def month_name(self) -> str:
        return MONTH_NAMES[self.month - 1]

    @property
    def weekday_name(self) -> str:
        return WEEKDAY_NAMES[self.to_gregorian().weekday()]

    def format(self, *, pattern: str = "{y}/{m:02d}/{d:02d}", persian_digits: bool = True,
               month_names: bool = False, long: bool = False) -> str:
        if month_names:
            base = f"{self.day} {self.month_name} {self.year}"
        else:
            base = pattern.format(y=self.year, m=self.month, d=self.day)
        if long:
            base = f"{self.weekday_name} {base}"
        if persian_digits:
            from pars_erp.core.digits import to_persian_digits
            return to_persian_digits(base)
        return base

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.format()


_SEPARATORS = ("/", "-", ".", " ")


def parse_jalali(text: str | None, *, field: str = "date") -> JalaliDate:
    """Parse ``1403/05/12`` (Persian digits and any of ``/ - .`` allowed)."""
    value = to_latin_digits(normalize_text(text))
    if not value:
        raise ValidationError("تاریخ را وارد کنید.", field=field)
    parts = []
    buffer = ""
    for ch in value:
        if ch.isdigit():
            buffer += ch
        elif ch in _SEPARATORS:
            parts.append(buffer)
            buffer = ""
        else:
            raise ValidationError(f"تاریخ «{text}» قابل خواندن نیست. قالب صحیح: ۱۴۰۳/۰۵/۱۲", field=field)
    parts.append(buffer)
    parts = [p for p in parts if p != ""]
    if len(parts) != 3:
        raise ValidationError(f"تاریخ «{text}» باید شامل سال، ماه و روز باشد. مثال: ۱۴۰۳/۰۵/۱۲", field=field)
    year, month, day = (int(p) for p in parts)
    if year < 100:  # two-digit entry is ambiguous - reject rather than guess
        raise ValidationError("سال را چهار رقمی وارد کنید.", field=field)
    return JalaliDate(year, month, day)


def format_gregorian_as_jalali(value: _dt.date | _dt.datetime | None, *,
                               persian_digits: bool = True, long: bool = False) -> str:
    if value is None:
        return "—"
    return JalaliDate.from_gregorian(value).format(persian_digits=persian_digits, long=long)


def format_datetime_as_jalali(value: _dt.datetime | None, *, timezone: _dt.tzinfo | None = None,
                              persian_digits: bool = True, with_time: bool = True) -> str:
    """Format an (ideally UTC) datetime in local time using the Jalali calendar."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    if timezone is None:
        from pars_erp.core.timeutil import get_timezone
        timezone = get_timezone(None)
    local = value.astimezone(timezone)
    text = JalaliDate.from_gregorian(local.date()).format(persian_digits=False)
    if with_time:
        text += f" {local.hour:02d}:{local.minute:02d}"
    if persian_digits:
        from pars_erp.core.digits import to_persian_digits
        return to_persian_digits(text)
    return text


def to_iso(value: _dt.date) -> str:
    """Unambiguous storage representation for a business date."""
    if isinstance(value, _dt.datetime):
        value = value.date()
    return value.isoformat()


def today_jalali() -> JalaliDate:
    return JalaliDate.today()
