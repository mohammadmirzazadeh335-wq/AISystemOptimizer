"""Phase 7: the reporting engine - saved report definitions and their shares.

Two new tables and nothing else: no phase 1-6 table is altered, no row is
rewritten. A saved report stores only *which* catalogue entry the user picked and
the generic options (columns, filters, sorting, grouping, page size) - never SQL -
so the table is inert data that cannot be used to read anything the user is not
allowed to see.

Revision ID: 0005_phase7_reporting
Revises: b7d21f4c9e10
Create Date: 2026-11-10 18:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

import pars_erp.db.types

revision = "0005_phase7_reporting"
down_revision = "b7d21f4c9e10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rpt_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("definition_key", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("columns", pars_erp.db.types.JsonDocument(), nullable=True),
        sa.Column("filters", pars_erp.db.types.JsonDocument(), nullable=True),
        sa.Column("params", pars_erp.db.types.JsonDocument(), nullable=True),
        sa.Column("sort_key", sa.String(length=64), nullable=True),
        sa.Column("sort_desc", sa.Boolean(), nullable=False),
        sa.Column("group_by", sa.String(length=64), nullable=True),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("last_run_at", pars_erp.db.types.UtcDateTime(), nullable=True),
        sa.Column("created_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"],
                                name=op.f("fk_rpt_reports_owner_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rpt_reports")),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_rpt_reports_owner_name"),
    )
    op.create_index(op.f("ix_rpt_reports_definition"), "rpt_reports",
                    ["definition_key"], unique=False)

    op.create_table(
        "rpt_report_shares",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("scope_kind", sa.String(length=10), nullable=False),
        sa.Column("scope_value", sa.String(length=64), nullable=False),
        sa.Column("created_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.Column("updated_at", pars_erp.db.types.UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["rpt_reports.id"],
                                name=op.f("fk_rpt_report_shares_report_id_rpt_reports"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rpt_report_shares")),
        sa.UniqueConstraint("report_id", "scope_kind", "scope_value",
                            name="uq_rpt_report_shares_scope"),
    )
    op.create_index(op.f("ix_rpt_report_shares_report"), "rpt_report_shares",
                    ["report_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rpt_report_shares_report"), table_name="rpt_report_shares")
    op.drop_table("rpt_report_shares")
    op.drop_index(op.f("ix_rpt_reports_definition"), table_name="rpt_reports")
    op.drop_table("rpt_reports")
