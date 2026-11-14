"""Dialect-portable column types.

See docs/ARCHITECTURE.md section "Data types" for the reasoning. In short:

* ``MoneyAmount`` stores exact amounts as *minor units* (integer) so that no
  binary floating point ever touches financial data, ordering and SQL
  aggregation stay exact on every backend, and PostgreSQL/SQLite behave the same.
* ``UtcDateTime`` always stores/returns timezone-aware UTC datetimes in an
  unambiguous ISO-8601 form.
"""

from __future__ import annotations

import datetime as _dt
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from pars_erp.core.money import STORAGE_SCALE

MONEY_FACTOR = 10 ** STORAGE_SCALE
UTC = _dt.timezone.utc


def utcnow() -> _dt.datetime:
    """Timezone-aware 'now' in UTC - the only clock the application trusts."""
    return _dt.datetime.now(UTC)


class MoneyAmount(TypeDecorator):
    """Exact decimal money stored as integer minor units (scale = 4)."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("float is not allowed for monetary values")
        if isinstance(value, Decimal):
            scaled = value.scaleb(STORAGE_SCALE)
            if scaled != scaled.to_integral_value():
                # More precision than the storage scale: refuse instead of silently rounding.
                from pars_erp.core.errors import ValidationError
                raise ValidationError(
                    f"مبلغ {value} دقت بیشتری از {STORAGE_SCALE} رقم اعشار دارد.")
            return int(scaled)
        if isinstance(value, int):
            return value * MONEY_FACTOR
        if isinstance(value, str):
            return self.process_bind_param(Decimal(value), dialect)
        raise TypeError(f"unsupported money value: {type(value)!r}")

    def process_result_value(self, value: Any, dialect) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(int(value)) / MONEY_FACTOR).quantize(Decimal(1).scaleb(-STORAGE_SCALE))


class UtcDateTime(TypeDecorator):
    """Timezone-aware UTC datetime with a portable, sortable representation."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(DateTime(timezone=True))
        return dialect.type_descriptor(String(32))

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, _dt.datetime):
            raise TypeError(f"expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            # Naive datetimes are ambiguous; the application is required to pass UTC.
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if dialect.name == "postgresql":
            return value
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def process_result_value(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class JsonDocument(TypeDecorator):
    """JSON document stored as JSONB on PostgreSQL and TEXT elsewhere."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    def process_result_value(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return {"_raw": value}
