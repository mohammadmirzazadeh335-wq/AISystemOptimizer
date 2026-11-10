"""Shared helpers for the phase-3 commerce services.

Everything here is Qt-free and Decimal-only: money never passes through
``float`` and quantities are kept at four decimal places, which is what the
``Numeric(18, 4)`` columns store.

The helpers cover four concerns:

* **quantity/money coercion** with Persian-aware error messages;
* **document numbering** (``PUR-1404-0001`` style, per Jalali year, unique
  per prefix - the unique index on the column is the real guard against
  duplicates, this only produces the candidate);
* **valuation policy resolution** - the company default lives in settings and
  a warehouse may override it, without ever rewriting historical documents;
* **status transitions** for commercial documents, so purchase, sale, order
  and stock-count flows all validate against the same table in
  :mod:`pars_erp.commerce.constants`.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.core.jalali import gregorian_to_jalali
from pars_erp.core.money import quantize_amount
from pars_erp.db.models import Warehouse
from pars_erp.db.types import utcnow

ZERO = Decimal("0")
QTY_SCALE = Decimal("0.0001")
MAX_QTY = Decimal("99999999999999.9999")


# ------------------------------------------------------------------ coercion
def to_quantity(value: Any, *, field: str = "quantity", allow_zero: bool = True,
                allow_negative: bool = False) -> Decimal:
    """Convert user input to a 4-decimal ``Decimal`` quantity."""
    if value is None or value == "":
        if allow_zero:
            return ZERO
        raise ValidationError("مقدار را وارد کنید.", field=field)
    if isinstance(value, float):
        raise ValidationError("استفاده از عدد اعشاری ممیز شناور برای مقدار مجاز نیست.",
                              field=field)
    try:
        if isinstance(value, Decimal):
            qty = value
        elif isinstance(value, int):
            qty = Decimal(value)
        else:
            text = str(value).strip().replace(",", "").replace("٬", "")
            text = text.replace("٫", ".").replace("،", "")
            qty = Decimal(text)
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValidationError("مقدار وارد شده عدد معتبر نیست.", field=field) from exc
    if not qty.is_finite():
        raise ValidationError("مقدار وارد شده عدد معتبر نیست.", field=field)
    qty = qty.quantize(QTY_SCALE)
    if not allow_zero and qty == 0:
        raise ValidationError("مقدار باید بزرگ‌تر از صفر باشد.", field=field)
    if qty < 0 and not allow_negative:
        raise ValidationError("مقدار نباید منفی باشد.", field=field)
    if abs(qty) > MAX_QTY:
        raise ValidationError("مقدار وارد شده بیش از حد مجاز بزرگ است.", field=field)
    return qty


def to_money(value: Any, *, field: str = "amount", allow_negative: bool = False) -> Decimal:
    """Convert input to a positive money value rounded to the currency."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, float):
        raise ValidationError("استفاده از عدد اعشاری ممیز شناور برای مبلغ مجاز نیست.",
                              field=field)
    try:
        if isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        else:
            text = str(value).strip().replace(",", "").replace("٬", "").replace("٫", ".")
            amount = Decimal(text)
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValidationError("مبلغ وارد شده عدد معتبر نیست.", field=field) from exc
    if not amount.is_finite():
        raise ValidationError("مبلغ وارد شده عدد معتبر نیست.", field=field)
    if amount < 0 and not allow_negative:
        raise ValidationError("مبلغ نباید منفی باشد.", field=field)
    return quantize_amount(amount)


def to_percent(value: Any, *, field: str = "percent") -> Decimal:
    """Convert a percentage (0..100, up to 4 decimals)."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, float):
        raise ValidationError("درصد باید به‌صورت عدد دقیق وارد شود.", field=field)
    try:
        percent = Decimal(str(value).strip().replace("%", "").replace("٫", "."))
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValidationError("درصد وارد شده عدد معتبر نیست.", field=field) from exc
    if percent < 0 or percent > 100:
        raise ValidationError("درصد باید بین ۰ تا ۱۰۰ باشد.", field=field)
    return percent.quantize(Decimal("0.0001"))


def clean_text(value: Any, *, field: str, label: str, required: bool = False,
               max_length: int = 200) -> str:
    text = ("" if value is None else str(value)).strip()
    if required and not text:
        raise ValidationError(f"{label} را وارد کنید.", field=field)
    if len(text) > max_length:
        raise ValidationError(f"{label} نباید بیش از {max_length} نویسه باشد.", field=field)
    return text


def clean_code(value: Any, *, label: str = "کد", max_length: int = 32) -> str:
    code = clean_text(value, field="code", label=label, required=True, max_length=max_length)
    if " " in code:
        raise ValidationError(f"{label} نباید فاصله داشته باشد.", field="code")
    return code.upper()


# ----------------------------------------------------------------- numbering
def jalali_year(value: _dt.date | None = None) -> int:
    return gregorian_to_jalali(value or _dt.date.today())[0]


def next_document_number(session: Session, model: Any, *, prefix: str,
                         on_date: _dt.date | None = None, width: int = 4,
                         column: str = "number") -> str:
    """Return the next free ``PREFIX-JYY-NNNN`` value for ``model``.

    ``JYY`` is the Jalali year (e.g. 1404). ``column`` names the field that holds
    the value - models such as ``hr_employees`` keep theirs in ``code``. The
    unique constraint on that column still guards against a concurrent insert:
    callers catch :class:`IntegrityError` and retry once.
    """
    year = jalali_year(on_date)
    stem = f"{prefix}-{year}-"
    field = getattr(model, column)
    highest = session.execute(
        select(func.max(field)).where(field.like(f"{stem}%"))).scalar()
    sequence = 1
    if highest:
        tail = str(highest).rsplit("-", 1)[-1]
        if tail.isdigit():
            sequence = int(tail) + 1
    return f"{stem}{sequence:0{width}d}"


# ------------------------------------------------------------------ settings
def valuation_method(settings, warehouse: Warehouse | None = None) -> str:
    """The valuation method that applies to ``warehouse`` right now.

    Company setting → warehouse override. Historical stock layers keep their own
    cost, so switching the method only affects *future* issues.
    """
    if warehouse is not None and warehouse.valuation_method in CC.VALUATION_METHODS:
        return warehouse.valuation_method
    try:
        value = settings.snapshot().str("commerce_valuation_method")
    except Exception:  # pragma: no cover - defensive: settings may be absent in tests
        value = CC.VALUATION_AVERAGE
    return value if value in CC.VALUATION_METHODS else CC.VALUATION_AVERAGE


def allow_negative_default(settings) -> bool:
    try:
        return bool(settings.snapshot().bool("commerce_allow_negative_stock"))
    except Exception:  # pragma: no cover
        return False


def base_currency(settings) -> str:
    try:
        return settings.snapshot().str("currency_code") or "IRR"
    except Exception:  # pragma: no cover
        return "IRR"


# ----------------------------------------------------------------- lifecycle
def assert_transition(current: str, target: str,
                      table: dict[str, tuple[str, ...]] | None = None) -> None:
    allowed = (table or CC.ALLOWED_TRANSITIONS).get(current, ())
    if target not in allowed:
        current_title = CC.DOC_STATUS_TITLES_FA.get(current, current)
        target_title = CC.DOC_STATUS_TITLES_FA.get(target, target)
        raise ValidationError(
            f"تغییر وضعیت از «{current_title}» به «{target_title}» مجاز نیست.")


def require_status(doc: Any, status: str, *, label: str = "سند") -> None:
    if doc.status != status:
        raise ValidationError(
            f"{label} در وضعیت «{CC.DOC_STATUS_TITLES_FA.get(doc.status, doc.status)}» است؛ "
            f"این عملیات فقط برای وضعیت «{CC.DOC_STATUS_TITLES_FA.get(status, status)}» "
            "مجاز است.")


def require_not_posted(doc: Any, *, label: str = "سند") -> None:
    if doc.status == CC.STATUS_POSTED:
        raise ValidationError(
            f"{label} قبلاً ثبت نهایی شده است؛ برای اصلاح باید سند برگشت/ابطال ثبت شود.")


# ------------------------------------------------------------------- lookups
def get_or_404(session: Session, model: Any, identifier: int | None,
               message: str = "رکورد مورد نظر یافت نشد."):
    if identifier is None:
        raise ValidationError(message)
    obj = session.get(model, identifier)
    if obj is None:
        raise NotFoundError(message)
    return obj


def active_choices(rows: Iterable[Any], *, label_attr: str = "title_fa") -> list[tuple[int, str]]:
    return [(row.id, f"{row.code} — {getattr(row, label_attr)}") for row in rows
            if getattr(row, "is_active", True)]


def conflict_from_integrity(exc: Exception, message: str) -> ConflictError:
    return ConflictError(message,)


def stamp_update(doc: Any, ctx) -> None:
    if ctx is not None:
        doc.updated_by_id = getattr(ctx, "user_id", None)
    doc.updated_at = utcnow()


def postal_date(value: _dt.date | None) -> _dt.date:
    return value or _dt.date.today()
