"""Phase-7 reporting models: saved report definitions and their shares.

A saved report never stores SQL. It stores *which* catalogue entry the user picked
(``definition_key``) plus the generic options the engine understands: column keys,
filters, sorting, grouping and page size. Because the catalogue is code, a saved
row that names a removed report or column fails loudly with a Persian validation
error instead of running something unexpected.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import JsonDocument, MoneyAmount, UtcDateTime


class SavedReport(Base, TimestampMixin):
    """One user's saved report (optionally shared with roles/users)."""

    __tablename__ = "rpt_reports"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_rpt_reports_owner_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    definition_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    columns: Mapped[list | None] = mapped_column(JsonDocument, nullable=True)
    filters: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    params: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    sort_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_desc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    group_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    shares: Mapped[list["SavedReportShare"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", lazy="selectin")


class SavedReportShare(Base, TimestampMixin):
    """A role or a single user a saved report is shared with."""

    __tablename__ = "rpt_report_shares"
    __table_args__ = (
        UniqueConstraint("report_id", "scope_kind", "scope_value",
                         name="uq_rpt_report_shares_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("rpt_reports.id", ondelete="CASCADE"), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(64), nullable=False)

    report: Mapped[SavedReport] = relationship(back_populates="shares")


class AlertRule(Base, TimestampMixin):
    """A configurable management alert: on/off, severity and thresholds.

    The *keys* are code (a rule that does not exist cannot be enabled), but the
    threshold, severity and enabled flag are data an administrator owns.
    """

    __tablename__ = "rpt_alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    section: Mapped[str] = mapped_column(String(24), nullable=False, default="general")
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="warning")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    threshold: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    last_evaluated_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class Alert(Base, TimestampMixin):
    """One raised alert, with acknowledgement/resolution history.

    ``dedupe_key`` is unique: evaluating the rules ten times in one day cannot
    create ten copies of the same warning.
    """

    __tablename__ = "rpt_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_rpt_alerts_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="warning")
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    message_fa: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    value_amount: Mapped[Decimal | None] = mapped_column(MoneyAmount, nullable=True)
    raised_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    raised_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acknowledged_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    acknowledged_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note_fa: Mapped[str] = mapped_column(String(400), nullable=False, default="")
