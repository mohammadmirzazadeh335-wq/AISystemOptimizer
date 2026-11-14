"""Presentation helpers shared by every screen.

These functions are deliberately Qt-free so they can be unit-tested and reused by
reports in later phases. All of them respect the user's "Persian digits" setting.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any

from pars_erp.core.digits import to_persian_digits
from pars_erp.core.jalali import format_datetime_as_jalali, format_gregorian_as_jalali
from pars_erp.core.money import format_amount, get_currency
from pars_erp.core.timeutil import humanize_delta_fa, to_local

DASH = "—"


class Formatter:
    """Formats values for display according to the current settings snapshot."""

    def __init__(self, *, persian_digits: bool = True, currency_code: str = "IRR",
                 timezone: str = "Asia/Tehran") -> None:
        self.persian_digits = persian_digits
        self.currency_code = currency_code
        self.timezone = timezone

    # ------------------------------------------------------------- numbers
    def number(self, value: int | float | None) -> str:
        if value is None:
            return DASH
        text = f"{int(value):,}"
        return to_persian_digits(text).replace(",", "\u066c") if self.persian_digits else text

    def amount(self, value: Decimal | int | str | None, *, with_symbol: bool = False) -> str:
        return format_amount(value, self.currency_code, persian_digits=self.persian_digits,
                             with_symbol=with_symbol)

    def currency_symbol(self) -> str:
        return get_currency(self.currency_code).symbol_fa

    # --------------------------------------------------------------- dates
    def date(self, value: _dt.date | _dt.datetime | None) -> str:
        if value is None:
            return DASH
        return format_gregorian_as_jalali(value, persian_digits=self.persian_digits)

    def datetime(self, value: _dt.datetime | None) -> str:
        if value is None:
            return DASH
        return format_datetime_as_jalali(value, timezone=None, persian_digits=self.persian_digits)

    def relative(self, value: _dt.datetime | None) -> str:
        if value is None:
            return DASH
        return humanize_delta_fa(value, tz_name=self.timezone)

    def local_time(self, value: _dt.datetime | None) -> str:
        local = to_local(value, self.timezone)
        if local is None:
            return DASH
        text = local.strftime("%H:%M")
        return to_persian_digits(text) if self.persian_digits else text

    # ---------------------------------------------------------------- text
    def yes_no(self, value: bool | None) -> str:
        if value is None:
            return DASH
        return "بله" if value else "خیر"

    def text(self, value: Any, *, fallback: str = DASH) -> str:
        if value is None or value == "":
            return fallback
        return str(value)

    def bytes(self, value: int | None) -> str:
        if value is None:
            return DASH
        if value < 1024:
            return f"{self.number(value)} بایت"
        if value < 1024 * 1024:
            return f"{to_persian_digits(f'{value / 1024:.0f}') if self.persian_digits else f'{value / 1024:.0f}'} کیلوبایت"
        size = f"{value / (1024 * 1024):.1f}"
        return f"{to_persian_digits(size) if self.persian_digits else size} مگابایت"


def digits(text: str, persian: bool = True) -> str:
    return to_persian_digits(text) if persian else text


def to_display_digits(text: str, persian: bool = True) -> str:
    """Convert ASCII digits inside a string for display (no other changes)."""
    return to_persian_digits(text) if persian else text
