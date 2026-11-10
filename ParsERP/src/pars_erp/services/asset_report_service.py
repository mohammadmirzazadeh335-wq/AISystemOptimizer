"""Fixed-asset reports: register, book value, depreciation, disposals, repairs."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from sqlalchemy import func, select

from pars_erp.assets import constants as A
from pars_erp.core.jalali import format_gregorian_as_jalali
from pars_erp.db.models import (
    Asset,
    AssetCategory,
    AssetDisposal,
    AssetMaintenance,
    DepreciationLine,
    DepreciationRun,
    Employee,
    OrgUnit,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.commerce_reports_service import ReportTable
from pars_erp.services.hr_common import ZERO


def _d(value: _dt.date | None) -> str:
    return format_gregorian_as_jalali(value) if value else ""


class AssetReportService:
    def __init__(self, db: Database, settings=None) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------ helpers
    def _accumulated_map(self, session) -> dict[int, Decimal]:
        rows = session.execute(
            select(DepreciationLine.asset_id, func.sum(DepreciationLine.amount))
            .join(DepreciationRun, DepreciationRun.id == DepreciationLine.run_id)
            .where(DepreciationRun.status == A.DEP_RUN_POSTED)
            .group_by(DepreciationLine.asset_id)).all()
        return {asset_id: Decimal(total or 0) for asset_id, total in rows}

    def _lookups(self, session):
        categories = {row.id: row for row in
                      session.execute(select(AssetCategory)).scalars()}
        employees = {row.id: row for row in
                     session.execute(select(Employee)).scalars()}
        units = {row.id: row for row in session.execute(select(OrgUnit)).scalars()}
        return categories, employees, units

    # ---------------------------------------------------------------- register
    def register(self, ctx: SecurityContext | None, *, category_id: int | None = None,
                 location: str = "", custodian_employee_id: int | None = None,
                 status: str | None = None, search: str = "",
                 with_book_value: bool = False) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            query = select(Asset).order_by(Asset.code)
            if category_id:
                query = query.where(Asset.category_id == category_id)
            if status:
                query = query.where(Asset.status == status)
            if location:
                query = query.where(Asset.location.ilike(f"%{location}%"))
            if custodian_employee_id:
                query = query.where(Asset.custodian_employee_id == custodian_employee_id)
            assets = list(session.execute(query).scalars())
            term = (search or "").strip()
            if term:
                assets = [asset for asset in assets
                          if term in asset.code or term in asset.title_fa
                          or term in (asset.serial_no or "")]
            categories, employees, units = self._lookups(session)
            accumulated = self._accumulated_map(session) if with_book_value else {}
            rows = []
            for asset in assets:
                category = categories.get(asset.category_id)
                custodian = employees.get(asset.custodian_employee_id)
                unit = units.get(asset.org_unit_id)
                row = (
                    asset.code, asset.title_fa,
                    category.title_fa if category else "",
                    asset.serial_no or "",
                    _d(asset.in_service_date),
                    unit.title_fa if unit else "",
                    asset.location or "",
                    custodian.full_name if custodian else "",
                    Decimal(asset.initial_value or 0),
                    A.ASSET_STATUS_TITLES_FA.get(asset.status, asset.status),
                )
                if with_book_value:
                    acc = accumulated.get(asset.id, ZERO)
                    row = row + (acc, (Decimal(asset.initial_value or 0) - acc))
                rows.append(row)
            columns = ["کد", "نام دارایی", "دسته", "شماره سری", "تاریخ بهره‌برداری",
                       "واحد", "محل", "امانت‌دار", "بهای تمام‌شده", "وضعیت"]
            if with_book_value:
                columns += ["استهلاک انباشته", "ارزش دفتری"]
            total = sum((row[8] for row in rows), ZERO)
            return ReportTable("ast_register", "فهرست دارایی‌های ثابت",
                               tuple(columns), tuple(rows),
                               meta_fa=f"{len(rows)} دارایی — جمع بهای تمام‌شده {total}")

    def by_category(self, ctx: SecurityContext | None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            assets = list(session.execute(select(Asset)).scalars())
            categories, _employees, _units = self._lookups(session)
            accumulated = self._accumulated_map(session)
            buckets: dict[int, dict] = {}
            for asset in assets:
                bucket = buckets.setdefault(asset.category_id, {
                    "count": 0, "cost": ZERO, "accumulated": ZERO})
                bucket["count"] += 1
                bucket["cost"] += Decimal(asset.initial_value or 0)
                bucket["accumulated"] += accumulated.get(asset.id, ZERO)
            rows = []
            for category_id, bucket in sorted(
                    buckets.items(),
                    key=lambda item: categories[item[0]].code
                    if item[0] in categories else ""):
                category = categories.get(category_id)
                rows.append((
                    category.code if category else "", category.title_fa if category else "",
                    bucket["count"], bucket["cost"], bucket["accumulated"],
                    bucket["cost"] - bucket["accumulated"],
                ))
            return ReportTable(
                "ast_by_category", "دارایی‌ها به تفکیک دسته",
                ("کد دسته", "دسته", "تعداد", "بهای تمام‌شده", "استهلاک انباشته",
                 "ارزش دفتری"), tuple(rows), meta_fa=f"{len(rows)} دسته")

    def by_location(self, ctx: SecurityContext | None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            assets = list(session.execute(select(Asset)).scalars())
            accumulated = self._accumulated_map(session)
            buckets: dict[str, dict] = {}
            for asset in assets:
                key = (asset.location or "بدون محل").strip() or "بدون محل"
                bucket = buckets.setdefault(key, {"count": 0, "cost": ZERO,
                                                  "accumulated": ZERO})
                bucket["count"] += 1
                bucket["cost"] += Decimal(asset.initial_value or 0)
                bucket["accumulated"] += accumulated.get(asset.id, ZERO)
            rows = tuple(
                (key, values["count"], values["cost"], values["accumulated"],
                 values["cost"] - values["accumulated"])
                for key, values in sorted(buckets.items()))
            return ReportTable(
                "ast_by_location", "دارایی‌ها به تفکیک محل",
                ("محل", "تعداد", "بهای تمام‌شده", "استهلاک انباشته", "ارزش دفتری"),
                rows, meta_fa=f"{len(rows)} محل")

    def by_custodian(self, ctx: SecurityContext | None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            assets = list(session.execute(select(Asset)).scalars())
            _categories, employees, _units = self._lookups(session)
            accumulated = self._accumulated_map(session)
            buckets: dict[int | None, dict] = {}
            for asset in assets:
                bucket = buckets.setdefault(asset.custodian_employee_id, {
                    "count": 0, "cost": ZERO, "accumulated": ZERO})
                bucket["count"] += 1
                bucket["cost"] += Decimal(asset.initial_value or 0)
                bucket["accumulated"] += accumulated.get(asset.id, ZERO)
            rows = []
            for employee_id, values in sorted(
                    buckets.items(),
                    key=lambda item: employees[item[0]].code
                    if item[0] in employees else "zzz"):
                employee = employees.get(employee_id)
                rows.append((
                    employee.code if employee else "—",
                    employee.full_name if employee else "بدون امانت‌دار",
                    values["count"], values["cost"], values["accumulated"],
                    values["cost"] - values["accumulated"],
                ))
            return ReportTable(
                "ast_by_custodian", "دارایی‌ها به تفکیک امانت‌دار",
                ("کد پرسنلی", "امانت‌دار", "تعداد", "بهای تمام‌شده",
                 "استهلاک انباشته", "ارزش دفتری"), tuple(rows),
                meta_fa=f"{len(rows)} امانت‌دار")

    # ------------------------------------------------------------ depreciation
    def depreciation(self, ctx: SecurityContext | None, *,
                     year: int | None = None, month: int | None = None,
                     asset_id: int | None = None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            query = (select(DepreciationLine, DepreciationRun)
                     .join(DepreciationRun, DepreciationRun.id == DepreciationLine.run_id)
                     .order_by(DepreciationLine.period_year,
                               DepreciationLine.period_month, DepreciationLine.asset_id))
            if year:
                query = query.where(DepreciationLine.period_year == int(year))
            if month:
                query = query.where(DepreciationLine.period_month == int(month))
            if asset_id:
                query = query.where(DepreciationLine.asset_id == asset_id)
            records = list(session.execute(query).all())
            assets = {asset.id: asset for asset in session.execute(select(Asset)).scalars()}
            rows = []
            for line, run in records:
                asset = assets.get(line.asset_id)
                rows.append((
                    f"{line.period_year}/{line.period_month:02d}",
                    asset.code if asset else "", asset.title_fa if asset else "",
                    A.METHOD_TITLES_FA.get(line.method, line.method),
                    Decimal(line.opening_value or 0), Decimal(line.amount or 0),
                    Decimal(line.accumulated_after or 0),
                    Decimal(line.book_value_after or 0),
                    A.DEP_RUN_TITLES_FA.get(run.status, run.status), run.number,
                ))
            total = sum((row[5] for row in rows), ZERO)
            return ReportTable(
                "ast_depreciation", "استهلاک دارایی‌ها",
                ("دوره", "کد دارایی", "نام", "روش", "ارزش آغاز دوره", "استهلاک دوره",
                 "استهلاک انباشته", "ارزش دفتری", "وضعیت سند", "شمارهٔ سند"),
                tuple(rows), meta_fa=f"جمع استهلاک دوره {total}")

    # --------------------------------------------------------------- disposals
    def disposals(self, ctx: SecurityContext | None, *,
                  kind: str | None = None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            query = select(AssetDisposal).order_by(AssetDisposal.disposal_date.desc())
            if kind:
                query = query.where(AssetDisposal.kind == kind)
            records = list(session.execute(query).scalars())
            assets = {asset.id: asset for asset in session.execute(select(Asset)).scalars()}
            rows = []
            for record in records:
                asset = assets.get(record.asset_id)
                rows.append((
                    record.number, _d(record.disposal_date),
                    asset.code if asset else "", asset.title_fa if asset else "",
                    A.DISPOSAL_TITLES_FA.get(record.kind, record.kind),
                    Decimal(record.initial_value or 0), Decimal(record.accumulated or 0),
                    Decimal(record.book_value or 0), Decimal(record.sale_amount or 0),
                    Decimal(record.gain_loss or 0), record.buyer_name or "",
                ))
            gain = sum((row[9] for row in rows), ZERO)
            return ReportTable(
                "ast_disposals", "فروش و کنارگذاری دارایی‌ها",
                ("شماره", "تاریخ", "کد دارایی", "نام", "نوع", "بهای تمام‌شده",
                 "استهلاک انباشته", "ارزش دفتری", "مبلغ فروش", "سود/زیان", "خریدار"),
                tuple(rows), meta_fa=f"{len(rows)} مورد — جمع سود/زیان {gain}")

    def sold_or_retired(self, ctx: SecurityContext | None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            assets = list(session.execute(
                select(Asset).where(Asset.status.in_(tuple(A.DISPOSED_STATUSES)))
                .order_by(Asset.code)).scalars())
            categories, employees, units = self._lookups(session)
            accumulated = self._accumulated_map(session)
            rows = []
            for asset in assets:
                category = categories.get(asset.category_id)
                custodian = employees.get(asset.custodian_employee_id)
                acc = accumulated.get(asset.id, ZERO)
                rows.append((
                    asset.code, asset.title_fa,
                    category.title_fa if category else "",
                    A.ASSET_STATUS_TITLES_FA.get(asset.status, asset.status),
                    _d(asset.in_service_date),
                    units.get(asset.org_unit_id).title_fa if asset.org_unit_id in units
                    else "",
                    custodian.full_name if custodian else "",
                    Decimal(asset.initial_value or 0), acc,
                    Decimal(asset.initial_value or 0) - acc,
                ))
            return ReportTable(
                "ast_disposed", "دارایی‌های فروخته/کنارگذاشته‌شده",
                ("کد", "نام", "دسته", "وضعیت", "تاریخ بهره‌برداری", "واحد", "امانت‌دار",
                 "بهای تمام‌شده", "استهلاک انباشته", "ارزش دفتری"), tuple(rows),
                meta_fa=f"{len(rows)} دارایی")

    # ------------------------------------------------------------- maintenance
    def maintenance(self, ctx: SecurityContext | None, *,
                    asset_id: int | None = None) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            query = select(AssetMaintenance).order_by(
                AssetMaintenance.service_date.desc())
            if asset_id:
                query = query.where(AssetMaintenance.asset_id == asset_id)
            records = list(session.execute(query).scalars())
            assets = {asset.id: asset for asset in session.execute(select(Asset)).scalars()}
            buckets: dict[int, dict] = {}
            for record in records:
                bucket = buckets.setdefault(record.asset_id, {"count": 0, "cost": ZERO,
                                                              "next": None})
                bucket["count"] += 1
                bucket["cost"] += Decimal(record.cost or 0)
                if record.next_service_date and (
                        bucket["next"] is None or record.next_service_date > bucket["next"]):
                    bucket["next"] = record.next_service_date
            rows = []
            for asset_key, values in sorted(
                    buckets.items(),
                    key=lambda item: assets[item[0]].code if item[0] in assets else ""):
                asset = assets.get(asset_key)
                rows.append((
                    asset.code if asset else "", asset.title_fa if asset else "",
                    values["count"], values["cost"], _d(values["next"]),
                ))
            total = sum((row[3] for row in rows), ZERO)
            return ReportTable(
                "ast_maintenance", "هزینهٔ تعمیر و نگهداری",
                ("کد دارایی", "نام", "تعداد خدمت", "جمع هزینه", "سرویس بعدی"),
                tuple(rows), meta_fa=f"جمع هزینه {total}")

    def maintenance_detail(self, ctx: SecurityContext | None,
                           asset_id: int) -> ReportTable:
        require_permission(ctx, "assets.reports")
        with self.db.session_scope() as session:
            asset = session.get(Asset, asset_id)
            records = list(session.execute(
                select(AssetMaintenance).where(AssetMaintenance.asset_id == asset_id)
                .order_by(AssetMaintenance.service_date.desc())).scalars())
            rows = tuple(
                (_d(record.service_date),
                 A.MAINT_TITLES_FA.get(record.kind, record.kind),
                 Decimal(record.cost or 0), record.contractor or "",
                 record.consumables or "", record.description or "",
                 _d(record.next_service_date))
                for record in records)
            total = sum((row[2] for row in rows), ZERO)
            return ReportTable(
                "ast_maintenance_detail",
                f"سوابق تعمیر {asset.code if asset else ''}", 
                ("تاریخ", "نوع", "هزینه", "پیمانکار", "مصرفی", "شرح", "سرویس بعدی"),
                rows, meta_fa=f"جمع هزینه {total}")


__all__ = ["AssetReportService"]
