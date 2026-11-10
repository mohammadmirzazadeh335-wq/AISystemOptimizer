"""Shared helpers for the accounting services.

Nothing here talks to Qt; everything is testable head-lessly.
"""

from __future__ import annotations

import datetime as _dt
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from pars_erp.accounting import constants as C
from pars_erp.core.errors import NotFoundError, ValidationError
from pars_erp.db.models import Account, FiscalPeriod

#: Default digit mask per level (گروه-کل-معین). Configurable through settings.
DEFAULT_CODE_MASK = "1-2-3"
_CODE_MASK_KEY = "accounting_code_mask"


def parse_mask(mask: str | None) -> tuple[int, ...]:
    """Parse ``"1-2-3"`` into ``(1, 2, 3)`` digit lengths per level."""
    text = (mask or DEFAULT_CODE_MASK).strip().replace("٫", "-").replace(",", "-")
    parts = [p.strip() for p in text.split("-") if p.strip()]
    if len(parts) != 3 or not all(p.isdigit() and int(p) > 0 for p in parts):
        raise ValidationError(
            "الگوی کدینگ حساب‌ها باید سه عدد مثبت با جداکنندهٔ خط تیره باشد "
            "(مثال: 1-2-3 برای گروه، کل و معین).",
            field=_CODE_MASK_KEY)
    return tuple(int(p) for p in parts)


def format_mask(mask: Iterable[int]) -> str:
    return "-".join(str(int(part)) for part in mask)


def expected_code_length(level: str, mask: tuple[int, ...]) -> int | None:
    """Total code length of a level: the mask is *cumulative*.

    ``"1-2-3"`` means: group = 1 digit (``1``), total = 1+2 = 3 digits (``101``),
    subsidiary = 1+2+3 = 6 digits (``101001``). Cumulative lengths guarantee that a
    child code always starts with its parent code, which is what makes the tree
    queryable by prefix.
    """
    order = C.ACCOUNT_LEVELS.index(level) if level in C.ACCOUNT_LEVELS else None
    if order is None:
        return None
    return int(sum(mask[: order + 1]))


def validate_account_code(code: str, level: str, mask: tuple[int, ...],
                          parent: Account | None) -> str:
    """Normalise and validate an account code against the level mask."""
    value = (code or "").strip()
    if not value:
        raise ValidationError("کد حساب را وارد کنید.", field="code")
    if not value.isdigit():
        raise ValidationError("کد حساب باید فقط از ارقام تشکیل شده باشد.", field="code")
    length = expected_code_length(level, mask)
    if length is not None and len(value) != length:
        raise ValidationError(
            f"طول کد برای سطح «{C.LEVEL_TITLES_FA[level]}» باید {length} رقم باشد "
            f"(الگوی فعلی: {format_mask(mask)}).", field="code")
    if parent is not None and not value.startswith(parent.code):
        raise ValidationError(
            f"کد حساب باید با کد حساب والد «{parent.code}» آغاز شود.", field="code")
    return value


def to_decimal(value, *, field: str = "amount", allow_zero: bool = True) -> Decimal:
    """Convert user/database input to Decimal without ever going through float."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, float):
        raise ValidationError("استفاده از عدد اعشاری ممیز شناور برای مبلغ مجاز نیست.",
                              field=field)
    try:
        if isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, str):
            amount = Decimal(value.strip().replace(",", "").replace("٬", "")
                             .replace("٫", "."))
        else:
            amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("مبلغ وارد‌شده معتبر نیست.", field=field) from exc
    if not amount.is_finite():
        raise ValidationError("مبلغ وارد‌شده معتبر نیست.", field=field)
    if not allow_zero and amount == 0:
        raise ValidationError("مبلغ باید بزرگ‌تر از صفر باشد.", field=field)
    if amount < 0:
        raise ValidationError("مبلغ نمی‌تواند منفی باشد؛ برای اصلاح از سند معکوس "
                              "استفاده کنید.", field=field)
    return amount


def quantize_money(value: Decimal, currency: str | None = None) -> Decimal:
    """Round a monetary amount to the currency scale (banker-safe HALF_UP)."""
    from pars_erp.core.money import get_currency

    places = get_currency(currency).decimals
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding="ROUND_HALF_UP")


def resolve_period(session: Session, *, period_id: int | None = None,
                   on_date: date | None = None, require_open: bool = True) -> FiscalPeriod:
    """Find the fiscal period for a document date (or by explicit id)."""
    if period_id is not None:
        period = session.get(FiscalPeriod, period_id)
        if period is None:
            raise NotFoundError("دورهٔ مالی انتخاب‌شده یافت نشد.")
    elif on_date is not None:
        period = session.execute(
            select(FiscalPeriod)
            .where(FiscalPeriod.start_date <= on_date, FiscalPeriod.end_date >= on_date)
            .order_by(FiscalPeriod.start_date)
        ).scalars().first()
        if period is None:
            raise ValidationError(
                f"برای تاریخ {on_date.isoformat()} دورهٔ مالی تعریف نشده است.",
                field="entry_date")
    else:
        raise ValidationError("تاریخ سند یا دورهٔ مالی را مشخص کنید.", field="entry_date")
    if not period.contains(on_date) and on_date is not None:
        raise ValidationError(
            f"تاریخ سند باید در بازهٔ دورهٔ «{period.title_fa}» "
            f"({period.start_date} تا {period.end_date}) باشد.", field="entry_date")
    if require_open and period.status == C.PERIOD_CLOSED:
        raise ValidationError(
            f"دورهٔ مالی «{period.title_fa}» بسته شده است و ثبت سند در آن مجاز نیست.",
            field="entry_date")
    return period


def get_account(session: Session, account_id: int, *, level: str | None = None,
                require_active: bool = True) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("حساب انتخاب‌شده یافت نشد.")
    if level is not None and account.level != level:
        raise ValidationError(
            f"حساب «{account.title_fa}» از سطح «{C.LEVEL_TITLES_FA.get(level, level)}» نیست.",
            field="account_id")
    if require_active and not account.is_active:
        raise ValidationError(
            f"حساب «{account.code} - {account.title_fa}» غیرفعال است و قابل استفاده نیست.",
            field="account_id")
    return account


def today() -> date:
    return _dt.date.today()
