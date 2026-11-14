"""Solar Hijri calendar conversion, parsing and formatting."""

from __future__ import annotations

import datetime as dt

import pytest

from pars_erp.core.errors import ValidationError
from pars_erp.core.jalali import (
    JalaliDate,
    days_in_month,
    format_datetime_as_jalali,
    format_gregorian_as_jalali,
    gregorian_to_jalali,
    is_leap_year,
    jalali_to_gregorian,
    parse_jalali,
)

KNOWN_DATES = [
    (dt.date(2024, 3, 20), (1403, 1, 1)),
    (dt.date(2025, 3, 21), (1404, 1, 1)),
    (dt.date(2026, 3, 21), (1405, 1, 1)),
    (dt.date(2023, 3, 21), (1402, 1, 1)),
    (dt.date(2021, 3, 21), (1400, 1, 1)),
    (dt.date(2022, 3, 21), (1401, 1, 1)),
    (dt.date(1979, 2, 11), (1357, 11, 22)),
    (dt.date(2000, 1, 1), (1378, 10, 11)),
    (dt.date(2026, 10, 30), (1405, 8, 8)),
    (dt.date(1983, 9, 1), (1362, 6, 10)),
]


@pytest.mark.parametrize("gregorian,expected", KNOWN_DATES)
def test_known_conversions(gregorian: dt.date, expected: tuple[int, int, int]) -> None:
    assert gregorian_to_jalali(gregorian) == expected
    assert jalali_to_gregorian(*expected) == gregorian


def test_roundtrip_every_day_for_two_years() -> None:
    day = dt.date(2024, 1, 1)
    end = dt.date(2026, 12, 31)
    while day <= end:
        jy, jm, jd = gregorian_to_jalali(day)
        assert jalali_to_gregorian(jy, jm, jd) == day
        day += dt.timedelta(days=1)


def test_leap_years() -> None:
    assert is_leap_year(1403) is True          # 366-day year
    assert is_leap_year(1404) is False
    assert days_in_month(1403, 12) == 30
    assert days_in_month(1404, 12) == 29
    assert days_in_month(1405, 1) == 31
    assert days_in_month(1405, 7) == 30


def test_invalid_dates_rejected() -> None:
    with pytest.raises(ValidationError):
        jalali_to_gregorian(1404, 12, 30)   # 1404 is not a leap year
    with pytest.raises(ValidationError):
        jalali_to_gregorian(1404, 13, 1)
    with pytest.raises(ValidationError):
        jalali_to_gregorian(1404, 0, 1)
    with pytest.raises(ValidationError):
        JalaliDate(1404, 7, 31)


def test_formatting_and_persian_digits() -> None:
    value = JalaliDate(1405, 8, 8)
    assert value.format() == "۱۴۰۵/۰۸/۰۸"
    assert value.format(persian_digits=False) == "1405/08/08"
    assert value.format(month_names=True, persian_digits=False) == "8 آبان 1405"
    assert value.month_name == "آبان"
    assert value.weekday_name == "جمعه"  # 2026-10-30 is a Friday
    assert format_gregorian_as_jalali(dt.date(2026, 10, 30), persian_digits=False) == "1405/08/08"
    assert format_gregorian_as_jalali(None) == "—"


def test_datetime_formatting_uses_local_timezone() -> None:
    # 2026-10-30 20:35 UTC == 2026-10-31 00:05 in Tehran (UTC+3:30)
    value = dt.datetime(2026, 10, 30, 20, 35, tzinfo=dt.timezone.utc)
    text = format_datetime_as_jalali(value, persian_digits=False)
    assert text == "1405/08/09 00:05"


@pytest.mark.parametrize("raw", ["1403/05/12", "۱۴۰۳/۰۵/۱۲", "1403-05-12", "1403.05.12", " 1403/5/12 "])
def test_parse_accepts_common_formats(raw: str) -> None:
    parsed = parse_jalali(raw)
    assert (parsed.year, parsed.month, parsed.day) == (1403, 5, 12)


@pytest.mark.parametrize("raw", ["", "1403/13/01", "1404/12/30", "abc", "1403/05", "03/05/12", "1403/05/12/1"])
def test_parse_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValidationError):
        parse_jalali(raw)


def test_date_ordering() -> None:
    assert JalaliDate(1405, 1, 1) < JalaliDate(1405, 1, 2)
    assert sorted([JalaliDate(1405, 2, 1), JalaliDate(1404, 12, 1)])[0] == JalaliDate(1404, 12, 1)
