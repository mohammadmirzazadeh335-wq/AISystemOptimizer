"""Declarative base and shared model mixins."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pars_erp.db.types import UtcDateTime, utcnow

# Deterministic constraint names keep Alembic migrations stable across backends.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            if isinstance(value, _dt.datetime):
                value = value.isoformat()
            elif isinstance(value, _dt.date):
                value = value.isoformat()
            data[column.name] = value
        return data


class TimestampMixin:
    """Created/updated bookkeeping for every mutable record."""

    created_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ActorColumnsMixin:
    """Who created/last touched a row (kept as plain ids to avoid FK cycles)."""

    created_by_id: Mapped[int | None] = mapped_column(nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(nullable=True)


class VersionMixin:
    """Optimistic concurrency guard against lost updates."""

    version: Mapped[int] = mapped_column(default=1, nullable=False)

    def bump_version(self) -> None:
        self.version = int(self.version or 0) + 1


class NotesMixin:
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
