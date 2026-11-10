"""Application-level configuration, backup and metadata models."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import JsonDocument, UtcDateTime


class AppSetting(Base, TimestampMixin):
    """Typed key/value store for application settings edited by administrators.

    Values are JSON so a setting can hold a bool, int, string or list without
    schema changes; the registry in :mod:`pars_erp.services.settings_service`
    is the only place that knows what each key means.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JsonDocument, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class BackupRecord(Base):
    """History of database backups and restores."""

    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="created", nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    schema_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AppMetadata(Base):
    """Single-row table with installation identity (created once)."""

    __tablename__ = "app_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    schema_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_startup_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    startup_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
