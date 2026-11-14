"""Phase 7: management alerts - configurable rules and the alerts they raised.

Adds two tables only. Rules are seeded lazily by the service (a missing row is
created on first use), so the migration itself inserts no data and is safe on a
live database. ``dedupe_key`` is unique, which is what stops the same warning
from being stored twice.

Revision ID: 0006_phase7_alerts
Revises: 0005_phase7_reporting
Create Date: 2026-11-10 19:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import pars_erp.db.types

revision = "0006_phase7_alerts"
down_revision = "0005_phase7_reporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rpt_alert_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=48), nullable=False),
        sa.Column("title_fa", sa.String(length=160), nullable=False),
        sa.Column("section", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("threshold", pars_erp.db.types.JsonDocument(), nullable=True),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False),
        sa.Column("last_evaluated_at", pars_erp.db.types.UtcDateTime(), nullable=True),
        sa.Column("created_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rpt_alert_rules")),
        sa.UniqueConstraint("key", name=op.f("uq_rpt_alert_rules_key")),
    )

    op.create_table(
        "rpt_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_key", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=12), nullable=False),
        sa.Column("title_fa", sa.String(length=160), nullable=False),
        sa.Column("message_fa", sa.String(length=600), nullable=False),
        sa.Column("dedupe_key", sa.String(length=180), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=40), nullable=True),
        sa.Column("value_amount", pars_erp.db.types.MoneyAmount(), nullable=True),
        sa.Column("raised_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.Column("raised_by_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", pars_erp.db.types.UtcDateTime(), nullable=True),
        sa.Column("acknowledged_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", pars_erp.db.types.UtcDateTime(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("note_fa", sa.String(length=400), nullable=False),
        sa.Column("created_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rpt_alerts")),
        sa.UniqueConstraint("dedupe_key", name="uq_rpt_alerts_dedupe_key"),
    )
    op.create_index(op.f("ix_rpt_alerts_rule"), "rpt_alerts", ["rule_key"], unique=False)
    op.create_index(op.f("ix_rpt_alerts_open"), "rpt_alerts", ["resolved_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rpt_alerts_open"), table_name="rpt_alerts")
    op.drop_index(op.f("ix_rpt_alerts_rule"), table_name="rpt_alerts")
    op.drop_table("rpt_alerts")
    op.drop_table("rpt_alert_rules")
