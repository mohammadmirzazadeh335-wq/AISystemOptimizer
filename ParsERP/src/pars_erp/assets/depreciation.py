"""Depreciation formulas: pure functions, independently testable.

Rules encoded here (and nowhere else):

* an asset is never depreciated below its salvage value;
* an asset that is fully depreciated yields ``0`` - a second run cannot book
  another month's expense for it;
* the three supported methods are straight line, declining balance and
  units-of-production; the method and life are data, not code;
* the first period is derived from the in-service date (the month of use, or the
  following month, depending on the company policy passed in).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

from pars_erp.assets import constants as A
from pars_erp.core.jalali import gregorian_to_jalali

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str | None) -> Decimal:
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def book_value(initial_value: Decimal, accumulated: Decimal) -> Decimal:
    return money(Decimal(initial_value or 0) - Decimal(accumulated or 0))


def depreciable_base(initial_value: Decimal, salvage_value: Decimal) -> Decimal:
    base = Decimal(initial_value or 0) - Decimal(salvage_value or 0)
    return money(base if base > 0 else ZERO)


def monthly_amount(*, method: str, initial_value: Decimal, salvage_value: Decimal,
                   useful_life_months: int, accumulated: Decimal,
                   declining_rate: Decimal | None = None,
                   units_period: Decimal | None = None,
                   total_units: Decimal | None = None) -> Decimal:
    """The depreciation expense of **one period**, never below the salvage floor."""
    initial = Decimal(initial_value or 0)
    salvage = Decimal(salvage_value or 0)
    accumulated = Decimal(accumulated or 0)
    current_book = book_value(initial, accumulated)
    if current_book <= salvage:
        return ZERO
    capacity = current_book - salvage

    if method == A.METHOD_STRAIGHT_LINE:
        life = int(useful_life_months or 0)
        if life <= 0:
            return ZERO
        amount = depreciable_base(initial, salvage) / Decimal(life)
    elif method == A.METHOD_DECLINING:
        rate = Decimal(declining_rate or 0)
        if rate <= 0:
            return ZERO
        amount = current_book * rate / Decimal("100") / Decimal("12")
    elif method == A.METHOD_UNITS:
        total = Decimal(total_units or 0)
        used = Decimal(units_period or 0)
        if total <= 0 or used <= 0:
            return ZERO
        amount = depreciable_base(initial, salvage) * used / total
    else:
        return ZERO

    amount = money(amount)
    if amount > capacity:
        amount = money(capacity)
    return amount if amount > 0 else ZERO


def first_period(in_service_date: _dt.date, *, next_month: bool = False) -> tuple[int, int]:
    """``(Jalali year, month)`` in which depreciation starts for an asset."""
    year, month, _day = gregorian_to_jalali(in_service_date)
    if next_month:
        month += 1
        if month > 12:
            month = 1
            year += 1
    return year, month


def period_end_date(year: int, month: int) -> _dt.date:
    """Last Gregorian day of a Jalali month."""
    from pars_erp.core.jalali import days_in_month, jalali_to_gregorian

    return jalali_to_gregorian(year, month, days_in_month(year, month))


def months_between(start_year: int, start_month: int, end_year: int, end_month: int) -> int:
    return (end_year - start_year) * 12 + (end_month - start_month)


def build_schedule(*, method: str, initial_value: Decimal, salvage_value: Decimal,
                   useful_life_months: int, start_year: int, start_month: int,
                   months: int, declining_rate: Decimal | None = None) -> list[Decimal]:
    """A preview schedule (used by tests and the on-screen projection)."""
    schedule: list[Decimal] = []
    accumulated = ZERO
    year, month = start_year, start_month
    for _ in range(max(0, months)):
        amount = monthly_amount(
            method=method, initial_value=initial_value, salvage_value=salvage_value,
            useful_life_months=useful_life_months, accumulated=accumulated,
            declining_rate=declining_rate)
        schedule.append(amount)
        accumulated += amount
        month += 1
        if month > 12:
            month = 1
            year += 1
    return schedule
