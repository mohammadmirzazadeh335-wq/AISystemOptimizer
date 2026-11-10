"""Phase-5 fixed-asset models: categories, assets, depreciation, disposal.

Design notes:

* every asset stores **its own** accounts (cost, accumulated, expense) copied from
  its category at registration; changing a category later never rewrites history;
* ``ast_depreciation_lines`` has a unique ``(asset_id, period_year, period_month)``
  so the same month can never be depreciated twice, even if two runs overlap;
* book value is always ``initial_value - accumulated`` computed from posted lines,
  never a column a user can type over.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.assets.constants import (
    ASSET_IN_USE,
    DEP_RUN_DRAFT,
    METHOD_STRAIGHT_LINE,
)
from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import MoneyAmount

ZERO = Decimal("0.0000")


class AssetCategory(Base, TimestampMixin):
    __tablename__ = "ast_categories"
    __table_args__ = (UniqueConstraint("code", name="uq_ast_categories_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    asset_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    accumulated_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    expense_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    default_useful_life_years: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    default_method: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default=METHOD_STRAIGHT_LINE)
    default_salvage_percent: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Asset(Base, TimestampMixin):
    __tablename__ = "ast_assets"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ast_assets_code"),
        Index("ix_ast_assets_status", "status"),
        Index("ix_ast_assets_category", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("ast_categories.id", ondelete="RESTRICT"), nullable=False)
    serial_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    purchase_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    in_service_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    supplier_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_invoices.id", ondelete="SET NULL"), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    custodian_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True)
    org_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_org_units.id", ondelete="SET NULL"), nullable=True)

    purchase_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    related_costs: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    initial_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    salvage_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    method: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default=METHOD_STRAIGHT_LINE)
    declining_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    total_units: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    units_depreciated: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False,
                                                       default=ZERO)

    asset_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    accumulated_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)
    expense_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ASSET_IN_USE)
    depreciation_start_override: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped[AssetCategory] = relationship(lazy="joined")


class AssetMovement(Base, TimestampMixin):
    __tablename__ = "ast_movements"
    __table_args__ = (Index("ix_ast_movements_asset", "asset_id", "movement_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("ast_assets.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    movement_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    from_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_org_unit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_org_unit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class DepreciationRun(Base, TimestampMixin):
    __tablename__ = "ast_depreciation_runs"
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", name="uq_ast_depreciation_runs_period"),
        Index("ix_ast_depreciation_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_end: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DEP_RUN_DRAFT)
    assets_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculated_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lines: Mapped[list["DepreciationLine"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin")


class DepreciationLine(Base, TimestampMixin):
    __tablename__ = "ast_depreciation_lines"
    __table_args__ = (
        UniqueConstraint("asset_id", "period_year", "period_month",
                         name="uq_ast_depreciation_lines_asset_period"),
        Index("ix_ast_depreciation_lines_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ast_depreciation_runs.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("ast_assets.id", ondelete="RESTRICT"), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    opening_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    accumulated_after: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                       default=ZERO)
    book_value_after: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                      default=ZERO)
    expense_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accumulated_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_used: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    run: Mapped[DepreciationRun] = relationship(back_populates="lines")


class AssetDisposal(Base, TimestampMixin):
    __tablename__ = "ast_disposals"
    __table_args__ = (UniqueConstraint("asset_id", name="uq_ast_disposals_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("ast_assets.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    disposal_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    sale_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    buyer_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    book_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    accumulated: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    initial_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    gain_loss: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    journal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AssetMaintenance(Base, TimestampMixin):
    __tablename__ = "ast_maintenance"
    __table_args__ = (Index("ix_ast_maintenance_asset", "asset_id", "service_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("ast_assets.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="repair")
    service_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    cost: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    contractor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    consumables: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    next_service_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    attachment_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_periodic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
