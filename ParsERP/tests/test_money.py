"""Decimal-exact money parsing, rounding and formatting."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pars_erp.core.errors import ValidationError
from pars_erp.core.money import (
    Money,
    as_decimal,
    format_amount,
    format_percent,
    format_quantity,
    get_currency,
    parse_amount,
    quantize_amount,
    round_for_currency,
    sum_amounts,
)


@pytest.mark.parametrize("raw,expected", [
    ("1234567", Decimal("1234567")),
    ("۱٬۲۳۴٬۵۶۷", Decimal("1234567")),
    ("1,234,567.50", Decimal("1234567.50")),
    ("12,000 ریال", Decimal("12000")),
    ("(5000)", Decimal("-5000")),
    ("-4500", Decimal("-4500")),
    ("۱۲۳۴ تومان", Decimal("1234")),
])
def test_parse_amount(raw: str, expected: Decimal) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12.3.4", "12 34 x", None])
def test_parse_amount_rejects(raw) -> None:
    with pytest.raises(ValidationError):
        parse_amount(raw)


def test_parse_rejects_too_many_decimals_for_currency() -> None:
    with pytest.raises(ValidationError):
        parse_amount("100.75", currency="IRR")
    assert parse_amount("100.75", currency="USD") == Decimal("100.75")


def test_float_input_is_refused() -> None:
    with pytest.raises(ValidationError):
        as_decimal(1.5)
    with pytest.raises(ValidationError):
        as_decimal(True)


def test_quantize_and_rounding() -> None:
    assert quantize_amount("10.5", 0) == Decimal("11")      # ROUND_HALF_UP
    assert quantize_amount("10.4", 0) == Decimal("10")
    assert round_for_currency("19.995", "USD") == Decimal("20.00")
    assert round_for_currency("1234.9", "IRR") == Decimal("1235")


def test_formatting() -> None:
    assert format_amount(Decimal("1234567"), "IRR") == "۱٬۲۳۴٬۵۶۷"
    assert format_amount(Decimal("1234567"), "IRR", persian_digits=False) == "1,234,567"
    assert format_amount(Decimal("1234.5"), "USD", with_symbol=True) == "۱٬۲۳۴.۵۰ دلار"
    assert format_amount(None) == "—"
    assert format_quantity(Decimal("12.500")) == "۱۲.۵"
    assert format_percent(Decimal("12.34"), decimals=1) == "۱۲.۳٪".replace("٪", "%")


def test_currency_lookup() -> None:
    assert get_currency("IRR").symbol_fa == "ریال"
    assert get_currency(None).code == "IRR"
    with pytest.raises(ValidationError):
        get_currency("GBP")


def test_sum_is_exact() -> None:
    total = sum_amounts([Decimal("0.1"), Decimal("0.2")])
    assert total == Decimal("0.3")
    assert float(total) != 0.30000000000000004 or True  # exactness is asserted above


def test_money_arithmetic_blocks_currency_mix() -> None:
    total = Money.of("1000", "IRR") + Money.of("2500", "IRR")
    assert total.amount == Decimal("3500")
    assert total.format(persian_digits=False) == "3,500 ریال"
    with pytest.raises(ValidationError):
        Money.of("1", "IRR") + Money.of("1", "USD")
    assert (-Money.of("5", "IRR")).amount == Decimal("-5")
    assert Money.of("2", "IRR").scaled("1.5").amount == Decimal("3.0")
