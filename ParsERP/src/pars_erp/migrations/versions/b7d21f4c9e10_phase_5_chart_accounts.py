"""phase 5: append the payroll / fixed-asset accounts to existing charts

Fresh installations get these rows from ``STANDARD_CHART``; installations that
were set up in an earlier phase already have a chart and would otherwise never
see them. This data migration appends **only** the seven missing leaves, and
only when a chart exists (a database with an empty chart stays empty so the
user's own chart import is not pre-empted).

Nothing is renamed, moved or deleted: this migration is append-only, and its
downgrade removes the seven rows only when no journal line references them.

Revision ID: b7d21f4c9e10
Revises: 9c3f5ad21e70
"""

from __future__ import annotations

import datetime as _dt

import sqlalchemy as sa
from alembic import op

revision = "b7d21f4c9e10"
down_revision = "9c3f5ad21e70"
branch_labels = None
depends_on = None

# (code, title_fa, level, account_type, nature, statement_section, parent_code)
NEW_ACCOUNTS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("101008", "وام و مساعدهٔ کارکنان", "subsidiary", "asset", "debit",
     "current_assets", "101"),
    ("102003", "استهلاک انباشتهٔ دارایی‌های ثابت", "subsidiary", "asset", "debit",
     "non_current_assets", "102"),
    ("201005", "بیمهٔ تأمین اجتماعی پرداختنی", "subsidiary", "liability", "credit",
     "current_liabilities", "201"),
    ("402002", "سود فروش دارایی ثابت", "subsidiary", "revenue", "credit",
     "other_income", "402"),
    ("502005", "هزینهٔ استهلاک دارایی‌های ثابت", "subsidiary", "expense", "debit",
     "operating_expense", "502"),
    ("502006", "بیمهٔ سهم کارفرما", "subsidiary", "expense", "debit",
     "operating_expense", "502"),
    ("503002", "زیان فروش و کنارگذاری دارایی ثابت", "subsidiary", "expense", "debit",
     "other_expense", "503"),
)


def _table_exists(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "acc_accounts"):
        return
    existing = {row[0] for row in bind.execute(
        sa.text("SELECT code FROM acc_accounts")).fetchall()}
    if not existing:
        return  # no chart yet: the user's own import will include these rows
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    for code, title, level, account_type, nature, section, parent_code in NEW_ACCOUNTS:
        if code in existing:
            continue
        parent_id = bind.execute(
            sa.text("SELECT id FROM acc_accounts WHERE code = :code"),
            {"code": parent_code}).scalar()
        bind.execute(
            sa.text(
                "INSERT INTO acc_accounts (code, title_fa, level, account_type, nature, "
                "statement_section, parent_id, is_active, is_system, sort_order, "
                "created_at, updated_at) VALUES (:code, :title, :level, :type, :nature, "
                ":section, :parent_id, :is_active, :is_system, :sort_order, :now, :now)"
            ),
            {"code": code, "title": title, "level": level, "type": account_type,
             "nature": nature, "section": section, "parent_id": parent_id,
             "is_active": True, "is_system": False, "sort_order": int(code), "now": now})
        existing.add(code)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "acc_accounts"):
        return
    referenced_table = _table_exists(bind, "acc_journal_lines")
    for code, *_rest in NEW_ACCOUNTS:
        if referenced_table:
            used = bind.execute(
                sa.text("SELECT COUNT(*) FROM acc_journal_lines WHERE account_id = "
                        "(SELECT id FROM acc_accounts WHERE code = :code)"),
                {"code": code}).scalar() or 0
            if used:
                continue  # never orphan a posted financial line
        bind.execute(sa.text("DELETE FROM acc_accounts WHERE code = :code AND "
                             "is_system = :flag"), {"code": code, "flag": False})
