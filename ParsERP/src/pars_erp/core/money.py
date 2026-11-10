"""Decimal-exact monetary handling.

Rules enforced across the code base:

* money is **never** represented by ``float``; :class:`decimal.Decimal` is used
  everywhere and the database stores the exact decimal string/NUMERIC value;
* every currency declares how many decimals it uses and how values are rounded;
* formatting is presentation-only and never feeds back into storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_DOWN
from typing import Iterable

from pars_erp.core.digits import normalize_text, to_latin_digits, to_persian_digits
from pars_erp.core.errors import ValidationError

#: Storage scale for monetary columns (4 decimals keeps room for unit prices and
#: exchange rates while still being exact for whole-rial amounts).
STORAGE_SCALE = 4

THOUSANDS_SEPARATOR_FA = "\u066c"  # ٬
DECIMAL_SEPARATOR_FA = "\u066b"    # ٫
ZERO = Decimal("0")


@dataclass(frozen=True)
class Currency:
    code: str
    name_fa: str
    symbol_fa: str
    decimals: int
    display_decimals: int | None = None

    @property
    def places(self) -> int:
        """Number of decimals shown to the user."""
        return self.decimals if self.display_decimals is None else self.display_decimals


CURRENCIES: dict[str, Currency] = {
    "IRR": Currency("IRR", "ریال ایران", "ریال", 0),
    "IRT": Currency("IRT", "تومان", "تومان", 0),
    "USD": Currency("USD", "دلار آمریکا", "دلار", 2),
    "EUR": Currency("EUR", "یورو", "یورو", 2),
    "AED": Currency("AED", "درهم امارات", "درهم", 2),
}
DEFAULT_CURRENCY_CODE = "IRR"


def get_currency(code: str | None) -> Currency:
    key = (code or DEFAULT_CURRENCY_CODE).strip().upper()
    if key not in CURRENCIES:
        raise ValidationError(f"واحد پول «{code}» پشتیبانی نمی‌شود.", field="currency")
    return CURRENCIES[key]


def as_decimal(value: Decimal | int | str) -> Decimal:
    """Convert an exact input to Decimal, rejecting binary floats."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; not a valid amount
        raise ValidationError("مقدار مالی نامعتبر است.", field="amount")
    if isinstance(value, float):
        raise ValidationError("برای محاسبات مالی استفاده از float مجاز نیست.", field="amount")
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"مقدار مالی «{value}» قابل تبدیل به عدد نیست.", field="amount") from exc


def quantize_amount(value: Decimal | int | str, decimals: int = 0, *, rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round an amount to ``decimals`` places using the configured rule."""
    amount = as_decimal(value)
    exponent = Decimal(1).scaleb(-int(decimals))
    return amount.quantize(exponent, rounding=rounding)


def round_for_currency(value: Decimal | int | str, currency: Currency | str | None = None,
                       *, rounding: str = ROUND_HALF_UP) -> Decimal:
    cur = get_currency(currency) if isinstance(currency, str) or currency is None else currency
    return quantize_amount(value, cur.decimals, rounding=rounding)


def truncate_for_currency(value: Decimal | int | str, currency: Currency | str | None = None) -> Decimal:
    cur = get_currency(currency) if isinstance(currency, str) or currency is None else currency
    return quantize_amount(value, cur.decimals, rounding=ROUND_DOWN)


_PERSIAN_CURRENCY_WORDS = ("ریال", "ريال", "تومان", "تومن", "دلار", "یورو", "درهم", "Rial", "Toman")


def parse_amount(text: str | int | Decimal | None, *, decimals: int | None = None,
                 currency: Currency | str | None = None) -> Decimal:
    """Parse user input such as ``۱٬۲۳۴٬۵۶۷``, ``1,234,567.50`` or ``(5000)``.

    Raises :class:`ValidationError` with a Persian message when the value is not
    a well-formed amount. Negative amounts are only produced by an explicit
    leading ``-`` or by accounting parentheses.
    """
    if text is None or (isinstance(text, str) and not text.strip()):
        raise ValidationError("مبلغ را وارد کنید.", field="amount")
    if isinstance(text, (int, Decimal)):
        return as_decimal(text)
    if not isinstance(text, str):
        raise ValidationError("مبلغ وارد شده معتبر نیست.", field="amount")

    raw = to_latin_digits(normalize_text(text))
    for word in _PERSIAN_CURRENCY_WORDS:
        raw = raw.replace(word, "")
    raw = raw.strip().replace(THOUSANDS_SEPARATOR_FA, "").replace(DECIMAL_SEPARATOR_FA, ".")
    raw = raw.replace(",", "").replace(" ", "").replace("\u200c", "")

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    if raw.startswith("-"):
        negative, raw = not negative, raw[1:]
    elif raw.startswith("+"):
        raw = raw[1:]
    if raw.count(".") > 1:
        raise ValidationError(f"مبلغ «{text}» معتبر نیست.", field="amount")
    if not raw or not any(ch.isdigit() for ch in raw):
        raise ValidationError(f"مبلغ «{text}» معتبر نیست.", field="amount")
    if any(not (ch.isdigit() or ch == ".") for ch in raw):
        raise ValidationError(f"مبلغ «{text}» شامل نویسه‌های غیرمجاز است.", field="amount")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValidationError(f"مبلغ «{text}» معتبر نیست.", field="amount") from exc
    value = -value if negative else value
    if decimals is not None:
        if value != value.quantize(Decimal(1).scaleb(-int(decimals))):
            raise ValidationError(
                f"مبلغ «{text}» بیش از {decimals} رقم اعشار مجاز نیست.", field="amount")
    elif currency is not None:
        cur = get_currency(currency) if isinstance(currency, str) else currency
        if value != value.quantize(Decimal(1).scaleb(-cur.decimals)):
            raise ValidationError(
                f"مبلغ «{text}» بیش از {cur.decimals} رقم اعشار مجاز نیست.", field="amount")
    return value


def format_amount(value: Decimal | int | str | None, currency: Currency | str | None = None, *,
                  persian_digits: bool = True, with_symbol: bool = False,
                  places: int | None = None, grouping: bool = True) -> str:
    """Render an amount for the UI/report in Persian-friendly form."""
    if value is None:
        return "—"
    amount = as_decimal(value)
    cur = get_currency(currency) if isinstance(currency, str) or currency is None else currency
    shown_places = cur.places if places is None else places
    quantized = amount.quantize(Decimal(1).scaleb(-shown_places), rounding=ROUND_HALF_UP)
    spec = f",.{shown_places}f" if grouping else f".{shown_places}f"
    text = format(quantized, spec)
    if persian_digits:
        text = to_persian_digits(text).replace(",", THOUSANDS_SEPARATOR_FA)
    if with_symbol:
        text = f"{text} {cur.symbol_fa}"
    return text


def format_quantity(value: Decimal | int | str | None, *, decimals: int = 3,
                    persian_digits: bool = True) -> str:
    """Format a non-monetary quantity (stock counts, hours, ...)."""
    if value is None:
        return "—"
    amount = as_decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = f"{amount:,.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{amount:,.0f}"
    return to_persian_digits(text).replace(",", THOUSANDS_SEPARATOR_FA) if persian_digits else text


def format_percent(value: Decimal | int | str | None, *, decimals: int = 1,
                   persian_digits: bool = True) -> str:
    if value is None:
        return "—"
    amount = as_decimal(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    text = f"{amount}%"
    return to_persian_digits(text) if persian_digits else text


def sum_amounts(values: Iterable[Decimal | int | str], *, start: Decimal = ZERO) -> Decimal:
    """Exact sum; rejects floats so callers cannot silently lose precision."""
    total = start
    for value in values:
        total += as_decimal(value)
    return total


@dataclass(frozen=True)
class Money:
    """An amount bound to a currency, with exact arithmetic."""

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", as_decimal(self.amount))

    @classmethod
    def of(cls, value: Decimal | int | str, currency_code: str | None = None) -> "Money":
        return cls(as_decimal(value), get_currency(currency_code))

    def _check(self, other: "Money") -> None:
        if other.currency.code != self.currency.code:
            raise ValidationError(
                f"جمع مبالغ با واحدهای پول متفاوت ({self.currency.code} و {other.currency.code}) مجاز نیست.",
                field="currency")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def scaled(self, factor: Decimal | int | str) -> "Money":
        return Money(self.amount * as_decimal(factor), self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == ZERO

    def format(self, **kwargs) -> str:
        kwargs.setdefault("with_symbol", True)
        return format_amount(self.amount, self.currency, **kwargs)
