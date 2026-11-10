"""Fixed assets: register, move, repair, sell and retire (phase 5, part 5).

Every asset carries its **own** accounts, copied from its category at
registration; a later category change therefore never rewrites history. Book
value is always ``initial_value − accumulated depreciation`` where the
accumulated figure comes from *posted* depreciation lines only.

Disposal is a two-document event for a sale:

* a treasury **receipt** records the money (Dr fund / Cr proceeds account);
* a **disposal journal** clears the accumulated depreciation and the cost, and
  books the gain or loss (``proceeds − book value``).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pars_erp.assets import constants as A
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    Asset,
    AssetCategory,
    AssetDisposal,
    AssetMaintenance,
    AssetMovement,
    DepreciationLine,
    DepreciationRun,
    DetailAccount,
    Employee,
    OrgUnit,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import clean_code, clean_text, next_document_number
from pars_erp.services.hr_common import ZERO, to_money
from pars_erp.treasury import constants as TC


# ------------------------------------------------------------------ dataclasses
@dataclass(frozen=True)
class CategoryInput:
    code: str
    title_fa: str
    kind: str = A.CAT_OTHER
    asset_account_id: int | None = None
    accumulated_account_id: int | None = None
    expense_account_id: int | None = None
    default_useful_life_years: int = 5
    default_method: str = A.METHOD_STRAIGHT_LINE
    default_salvage_percent: Decimal | int | str = 0
    is_active: bool = True
    description: str = ""


@dataclass(frozen=True)
class CategoryRow:
    id: int
    code: str
    title_fa: str
    kind: str
    kind_fa: str
    asset_account_id: int | None
    accumulated_account_id: int | None
    expense_account_id: int | None
    default_useful_life_years: int
    default_method: str
    default_method_fa: str
    assets_count: int
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class AssetInput:
    code: str = ""
    title_fa: str = ""
    category_id: int | None = None
    serial_no: str = ""
    model: str = ""
    manufacturer: str = ""
    purchase_date: _dt.date | None = None
    in_service_date: _dt.date | None = None
    supplier_detail_id: int | None = None
    invoice_id: int | None = None
    location: str = ""
    custodian_employee_id: int | None = None
    org_unit_id: int | None = None
    purchase_price: Decimal | int | str = 0
    related_costs: Decimal | int | str = 0
    initial_value: Decimal | int | str | None = None
    salvage_value: Decimal | int | str = 0
    useful_life_months: int | None = None
    method: str | None = None
    declining_rate: Decimal | int | str | None = None
    total_units: Decimal | int | str | None = None
    asset_account_id: int | None = None
    accumulated_account_id: int | None = None
    expense_account_id: int | None = None
    status: str = A.ASSET_IN_USE
    depreciation_start_override: _dt.date | None = None
    notes: str = ""
    attachment_path: str = ""


@dataclass(frozen=True)
class AssetRow:
    id: int
    code: str
    title_fa: str
    category: str
    category_id: int
    serial_no: str
    model: str
    purchase_date: _dt.date | None
    in_service_date: _dt.date
    supplier_name: str
    location: str
    custodian_employee_id: int | None
    custodian_name: str
    org_unit_title: str
    purchase_price: Decimal
    related_costs: Decimal
    initial_value: Decimal
    salvage_value: Decimal
    useful_life_months: int
    method: str
    method_fa: str
    declining_rate: Decimal | None
    status: str
    status_fa: str
    accumulated: Decimal
    book_value: Decimal
    monthly_depreciation: Decimal
    is_fully_depreciated: bool
    notes: str

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class MovementRow:
    id: int
    kind: str
    kind_fa: str
    movement_date: _dt.date
    from_value: str
    to_value: str
    note: str
    user_name: str


@dataclass(frozen=True)
class MaintenanceInput:
    asset_id: int
    kind: str = A.MAINT_REPAIR
    service_date: _dt.date | None = None
    cost: Decimal | int | str = 0
    contractor: str = ""
    consumables: str = ""
    description: str = ""
    next_service_date: _dt.date | None = None
    attachment_path: str = ""
    is_periodic: bool = False


@dataclass(frozen=True)
class MaintenanceRow:
    id: int
    asset_id: int
    asset_code: str
    asset_title: str
    kind: str
    kind_fa: str
    service_date: _dt.date
    cost: Decimal
    contractor: str
    description: str
    next_service_date: _dt.date | None
    is_periodic: bool


@dataclass(frozen=True)
class DisposalInput:
    asset_id: int
    kind: str
    disposal_date: _dt.date | None = None
    sale_amount: Decimal | int | str = 0
    buyer_name: str = ""
    reason: str = ""
    cash_box_id: int | None = None
    bank_account_id: int | None = None
    method: str = TC.METHOD_CASH


@dataclass(frozen=True)
class DisposalRow:
    id: int
    number: str
    asset_id: int
    asset_code: str
    asset_title: str
    kind: str
    kind_fa: str
    disposal_date: _dt.date
    sale_amount: Decimal
    buyer_name: str
    book_value: Decimal
    accumulated: Decimal
    initial_value: Decimal
    gain_loss: Decimal
    journal_id: int | None
    receipt_id: int | None
    reason: str


# --------------------------------------------------------------------- service
class AssetService:
    def __init__(self, db: Database, audit: AuditService, *, vouchers=None,
                 journals=None, settings=None) -> None:
        self.db = db
        self.audit = audit
        self.vouchers = vouchers
        self.journals = journals
        self.settings = settings

    # ---------------------------------------------------------------- categories
    def list_categories(self, ctx: SecurityContext | None, *,
                        active_only: bool = False) -> list[CategoryRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            query = select(AssetCategory).order_by(AssetCategory.code)
            if active_only:
                query = query.where(AssetCategory.is_active.is_(True))
            counts = dict(session.execute(
                select(Asset.category_id, func.count(Asset.id))
                .group_by(Asset.category_id)).all())
            return [self._category_row(row, counts.get(row.id, 0))
                    for row in session.execute(query).scalars()]

    def category_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, row.display) for row in self.list_categories(ctx,
                                                                      active_only=True)]

    def create_category(self, ctx: SecurityContext | None,
                        data: CategoryInput) -> CategoryRow:
        require_permission(ctx, "assets.register")
        if data.kind not in dict(A.CATEGORY_KINDS):
            raise ValidationError("نوع دستهٔ دارایی معتبر نیست.", field="kind")
        if data.default_method not in dict(A.METHODS):
            raise ValidationError("روش استهلاک معتبر نیست.", field="default_method")
        with self.db.session_scope() as session:
            accounts = self._resolve_accounts(session, data)
            row = AssetCategory(
                code=clean_code(data.code, label="کد دسته"),
                title_fa=clean_text(data.title_fa, field="title_fa", label="عنوان دسته",
                                    required=True, max_length=120),
                kind=data.kind, **accounts,
                default_useful_life_years=max(1, int(data.default_useful_life_years or 5)),
                default_method=data.default_method,
                default_salvage_percent=Decimal(str(data.default_salvage_percent or 0)),
                is_active=bool(data.is_active),
                description=(data.description or "").strip() or None)
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset_category", entity_id=row.id, action="create",
                summary_fa=f"تعریف دستهٔ دارایی {row.code} — {row.title_fa}",
                after={"kind": row.kind}, session=session)
            return self._category_row(row, 0)

    def update_category(self, ctx: SecurityContext | None, category_id: int,
                        data: CategoryInput) -> CategoryRow:
        require_permission(ctx, "assets.register")
        with self.db.session_scope() as session:
            row = session.get(AssetCategory, category_id)
            if row is None:
                raise NotFoundError("دستهٔ دارایی یافت نشد.")
            accounts = self._resolve_accounts(session, data, existing=row)
            row.code = clean_code(data.code, label="کد دسته")
            row.title_fa = clean_text(data.title_fa, field="title_fa", label="عنوان دسته",
                                      required=True, max_length=120)
            row.kind = data.kind
            row.default_useful_life_years = max(1, int(data.default_useful_life_years or 5))
            row.default_method = data.default_method
            row.default_salvage_percent = Decimal(str(data.default_salvage_percent or 0))
            row.is_active = bool(data.is_active)
            row.description = (data.description or "").strip() or None
            for key, value in accounts.items():
                setattr(row, key, value)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset_category", entity_id=row.id, action="update",
                summary_fa=f"ویرایش دستهٔ دارایی {row.code}", session=session)
            count = session.execute(
                select(func.count(Asset.id)).where(Asset.category_id == row.id)
            ).scalar() or 0
            return self._category_row(row, int(count))

    # -------------------------------------------------------------------- assets
    def list_assets(self, ctx: SecurityContext | None, *, search: str = "",
                    category_id: int | None = None, status: str | None = None,
                    location: str = "", org_unit_id: int | None = None,
                    custodian_employee_id: int | None = None) -> list[AssetRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            query = select(Asset).order_by(Asset.code)
            if category_id:
                query = query.where(Asset.category_id == category_id)
            if status:
                query = query.where(Asset.status == status)
            if location:
                query = query.where(Asset.location.ilike(f"%{location}%"))
            if org_unit_id:
                query = query.where(Asset.org_unit_id == org_unit_id)
            if custodian_employee_id:
                query = query.where(Asset.custodian_employee_id == custodian_employee_id)
            term = (search or "").strip()
            if term:
                like = f"%{term}%"
                query = query.where(or_(Asset.code.ilike(like), Asset.title_fa.ilike(like),
                                        Asset.serial_no.ilike(like),
                                        Asset.location.ilike(like)))
            return [self._asset_row(session, row) for row in
                    session.execute(query).scalars()]

    def get_asset(self, ctx: SecurityContext | None, asset_id: int) -> AssetRow:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            return self._asset_row(session, self._get_asset(session, asset_id))

    def asset_choices(self, ctx: SecurityContext | None) -> list[tuple[int, str]]:
        return [(row.id, row.display) for row in self.list_assets(ctx)]

    #: every editable field of an asset, in ``AssetInput`` terms (edit form)
    ASSET_FORM_FIELDS: tuple[str, ...] = (
        "code", "title_fa", "category_id", "serial_no", "model", "manufacturer",
        "purchase_date", "in_service_date", "supplier_detail_id", "invoice_id",
        "location", "custodian_employee_id", "org_unit_id", "purchase_price",
        "related_costs", "initial_value", "salvage_value", "useful_life_months",
        "method", "declining_rate", "total_units", "asset_account_id",
        "accumulated_account_id", "expense_account_id", "status",
        "depreciation_start_override", "notes", "attachment_path",
    )

    def asset_form_data(self, ctx: SecurityContext | None, asset_id: int) -> dict:
        """Raw editable values of one asset (used by the edit form)."""
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            asset = self._get_asset(session, asset_id)
            return {field: getattr(asset, field, None) for field in self.ASSET_FORM_FIELDS}

    def register(self, ctx: SecurityContext | None, data: AssetInput) -> AssetRow:
        require_permission(ctx, "assets.register")
        with self.db.session_scope() as session:
            payload = self._validate_asset(session, data)
            code = payload.pop("code")
            if code:
                clash = session.execute(
                    select(Asset).where(Asset.code == code)).scalars().first()
                if clash is not None:
                    raise ConflictError(f"دارایی با کد «{code}» قبلاً ثبت شده است.")
            if not code:
                prefix = self._setting_text("assets_code_prefix", "AST")
                code = next_document_number(session, Asset, prefix=prefix,
                                            on_date=payload["in_service_date"],
                                            column="code")
            asset = Asset(code=code, created_by_id=getattr(ctx, "user_id", None),
                          **payload)
            session.add(asset)
            session.flush()
            session.add(AssetMovement(
                asset_id=asset.id, kind=A.MOVE_STATUS, movement_date=asset.in_service_date,
                to_value=A.ASSET_STATUS_TITLES_FA[A.ASSET_IN_USE],
                note="ثبت اولیهٔ دارایی", user_id=getattr(ctx, "user_id", None),
                user_name=getattr(ctx, "full_name", None)))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset", entity_id=asset.id, action="create",
                summary_fa=f"ثبت دارایی {asset.code} — {asset.title_fa}",
                after={"value": str(asset.initial_value), "method": asset.method},
                session=session)
            return self._asset_row(session, asset)

    def update(self, ctx: SecurityContext | None, asset_id: int,
               data: AssetInput) -> AssetRow:
        """Edit descriptive fields; value/life/method changes go through policy paths."""
        require_permission(ctx, "assets.register")
        with self.db.session_scope() as session:
            asset = self._get_asset(session, asset_id)
            payload = self._validate_asset(session, data, existing=asset)
            payload.pop("code", None)
            if Decimal(payload["initial_value"]) != Decimal(asset.initial_value) \
                    or int(payload["useful_life_months"]) != int(asset.useful_life_months) \
                    or payload["method"] != asset.method:
                raise ValidationError(
                    "تغییر بهای تمام‌شده، عمر مفید یا روش استهلاک باید از مسیر «تغییر "
                    "سیاست استهلاک» با تاریخ اجرا انجام شود.", field="method")
            if payload["status"] != asset.status:
                self._assert_status_transition(asset.status, payload["status"])
                self._record_movement(session, ctx, asset, A.MOVE_STATUS,
                                      _dt.date.today(),
                                      from_value=A.ASSET_STATUS_TITLES_FA[asset.status],
                                      to_value=A.ASSET_STATUS_TITLES_FA[payload["status"]])
            for key, value in payload.items():
                setattr(asset, key, value)
            asset.updated_by_id = getattr(ctx, "user_id", None)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset", entity_id=asset.id, action="update",
                summary_fa=f"ویرایش دارایی {asset.code}", session=session)
            return self._asset_row(session, asset)

    def change_depreciation_policy(self, ctx: SecurityContext | None, asset_id: int, *,
                                   method: str | None = None,
                                   useful_life_months: int | None = None,
                                   declining_rate: Decimal | None = None,
                                   effective_date: _dt.date | None = None,
                                   note: str = "") -> AssetRow:
        require_permission(ctx, "assets.register")
        if not (note or "").strip():
            raise ValidationError("دلیل تغییر سیاست استهلاک را وارد کنید.", field="note")
        when = effective_date or _dt.date.today()
        with self.db.session_scope() as session:
            asset = self._get_asset(session, asset_id)
            before = {"method": asset.method, "life": asset.useful_life_months,
                      "rate": str(asset.declining_rate)}
            if method:
                if method not in dict(A.METHODS):
                    raise ValidationError("روش استهلاک معتبر نیست.", field="method")
                asset.method = method
            if useful_life_months:
                if int(useful_life_months) <= 0:
                    raise ValidationError("عمر مفید باید بزرگ‌تر از صفر باشد.",
                                          field="useful_life_months")
                asset.useful_life_months = int(useful_life_months)
            if declining_rate is not None:
                asset.declining_rate = Decimal(str(declining_rate))
            self._record_movement(
                session, ctx, asset, A.MOVE_POLICY, when,
                from_value=f"{before['method']} / {before['life']} ماه",
                to_value=f"{asset.method} / {asset.useful_life_months} ماه",
                note=note)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset", entity_id=asset.id, action="policy_change",
                summary_fa=f"تغییر سیاست استهلاک دارایی {asset.code}", before=before,
                after={"method": asset.method, "life": asset.useful_life_months,
                       "note": note}, session=session)
            return self._asset_row(session, asset)

    def transfer(self, ctx: SecurityContext | None, asset_id: int, *,
                 to_org_unit_id: int | None = None,
                 to_employee_id: int | None = None, location: str | None = None,
                 movement_date: _dt.date | None = None, note: str = "") -> AssetRow:
        require_permission(ctx, "assets.transfer")
        when = movement_date or _dt.date.today()
        with self.db.session_scope() as session:
            asset = self._get_asset(session, asset_id)
            if asset.status in A.DISPOSED_STATUSES:
                raise ConflictError("دارایی فروخته/کنارگذاشته‌شده قابل انتقال نیست.")
            if to_org_unit_id:
                unit = session.get(OrgUnit, to_org_unit_id)
                if unit is None:
                    raise ValidationError("واحد مقصد یافت نشد.", field="to_org_unit_id")
                self._record_movement(
                    session, ctx, asset, A.MOVE_TRANSFER, when,
                    from_org_unit_id=asset.org_unit_id, to_org_unit_id=unit.id,
                    from_value=self._unit_title(session, asset.org_unit_id),
                    to_value=unit.title_fa, note=note)
                asset.org_unit_id = unit.id
            if to_employee_id:
                employee = session.get(Employee, to_employee_id)
                if employee is None:
                    raise ValidationError("امانت‌دار انتخاب‌شده یافت نشد.",
                                          field="to_employee_id")
                self._record_movement(
                    session, ctx, asset, A.MOVE_CUSTODIAN, when,
                    from_employee_id=asset.custodian_employee_id,
                    to_employee_id=employee.id,
                    from_value=self._employee_name(session, asset.custodian_employee_id),
                    to_value=f"{employee.first_name} {employee.last_name}".strip(),
                    note=note)
                asset.custodian_employee_id = employee.id
            if location is not None and location.strip() != (asset.location or ""):
                self._record_movement(session, ctx, asset, A.MOVE_LOCATION, when,
                                      from_value=asset.location or "",
                                      to_value=location.strip(), note=note)
                asset.location = location.strip()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset", entity_id=asset.id, action="transfer",
                summary_fa=f"انتقال دارایی {asset.code}",
                after={"unit": asset.org_unit_id, "custodian": asset.custodian_employee_id,
                       "location": asset.location, "date": str(when)}, session=session)
            return self._asset_row(session, asset)

    def history(self, ctx: SecurityContext | None, asset_id: int) -> list[MovementRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(AssetMovement).where(AssetMovement.asset_id == asset_id)
                .order_by(AssetMovement.movement_date.desc(), AssetMovement.id.desc())
            ).scalars()
            return [MovementRow(
                id=row.id, kind=row.kind,
                kind_fa=A.MOVE_TITLES_FA.get(row.kind, row.kind),
                movement_date=row.movement_date, from_value=row.from_value or "",
                to_value=row.to_value or "", note=row.note or "",
                user_name=row.user_name or "") for row in rows]

    # --------------------------------------------------------------- maintenance
    def add_maintenance(self, ctx: SecurityContext | None,
                        data: MaintenanceInput) -> MaintenanceRow:
        require_permission(ctx, "assets.maintenance")
        if data.kind not in dict(A.MAINT_KINDS):
            raise ValidationError("نوع تعمیر/سرویس معتبر نیست.", field="kind")
        when = data.service_date or _dt.date.today()
        with self.db.session_scope() as session:
            asset = self._get_asset(session, data.asset_id)
            if asset.status in A.DISPOSED_STATUSES:
                raise ConflictError("برای دارایی کنارگذاشته‌شده تعمیر ثبت نمی‌شود.")
            row = AssetMaintenance(
                asset_id=asset.id, kind=data.kind, service_date=when,
                cost=to_money(data.cost, field="cost"),
                contractor=(data.contractor or "").strip() or None,
                consumables=(data.consumables or "").strip() or None,
                description=(data.description or "").strip() or None,
                next_service_date=data.next_service_date,
                attachment_path=(data.attachment_path or "").strip() or None,
                is_periodic=bool(data.is_periodic),
                created_by_id=getattr(ctx, "user_id", None))
            session.add(row)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset_maintenance", entity_id=row.id, action="create",
                summary_fa=f"ثبت {A.MAINT_TITLES_FA[data.kind]} برای دارایی {asset.code}",
                after={"cost": str(row.cost), "date": str(when)}, session=session)
            return self._maintenance_row(session, row)

    def list_maintenance(self, ctx: SecurityContext | None, *,
                         asset_id: int | None = None) -> list[MaintenanceRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            query = select(AssetMaintenance).order_by(
                AssetMaintenance.service_date.desc())
            if asset_id:
                query = query.where(AssetMaintenance.asset_id == asset_id)
            return [self._maintenance_row(session, row)
                    for row in session.execute(query).scalars()]

    # ------------------------------------------------------------------ disposal
    def dispose(self, ctx: SecurityContext | None, data: DisposalInput) -> DisposalRow:
        require_permission(ctx, "assets.dispose")
        if data.kind not in dict(A.DISPOSAL_KINDS):
            raise ValidationError("نوع واگذاری معتبر نیست.", field="kind")
        if self.vouchers is None or self.journals is None:  # pragma: no cover
            raise ValidationError("سرویس حسابداری/خزانه در دسترس نیست.")
        from pars_erp.services.treasury_common import post_system_journal
        from pars_erp.services.journals_service import JournalLineInput

        when = data.disposal_date or _dt.date.today()
        with self.db.session_scope() as session:
            asset = self._get_asset(session, data.asset_id)
            if asset.status in A.DISPOSED_STATUSES:
                raise ConflictError("این دارایی قبلاً واگذار شده است.")
            existing = session.execute(
                select(AssetDisposal).where(AssetDisposal.asset_id == asset.id)
            ).scalars().first()
            if existing is not None:  # pragma: no cover - guarded by status too
                raise ConflictError("برای این دارایی سند واگذاری ثبت شده است.")
            accumulated = self._accumulated(session, asset.id)
            book = (Decimal(asset.initial_value or 0) - accumulated).quantize(Decimal("0.01"))
            sale = to_money(data.sale_amount, field="sale_amount")
            if data.kind != A.DISPOSAL_SALE and sale:
                raise ValidationError("برای کنارگذاری/حذف، مبلغ فروش را خالی بگذارید.",
                                      field="sale_amount")
            if data.kind == A.DISPOSAL_SALE and sale <= 0:
                raise ValidationError("برای فروش، مبلغ فروش را وارد کنید.",
                                      field="sale_amount")
            gain_loss = (sale - book) if data.kind == A.DISPOSAL_SALE else (-book)
            gain_account = self._account(session, A.DEFAULT_GAIN_CODE)
            loss_account = self._account(session, A.DEFAULT_LOSS_CODE)

            if asset.asset_account_id is None:
                raise ValidationError("حساب دارایی برای ثبت واگذاری تعیین نشده است.")

            # The sale proceeds enter the books through a treasury receipt whose
            # counter account is the asset cost account itself: Dr fund / Cr cost.
            # The disposal journal then only removes the *remaining* cost and
            # closes accumulated depreciation against the gain/loss, so the cost
            # account always nets to zero and nothing is counted twice.
            receipt_id = None
            if data.kind == A.DISPOSAL_SALE:
                from pars_erp.services.voucher_service import ReceiptInput
                if not (data.cash_box_id or data.bank_account_id):
                    raise ValidationError("برای فروش، صندوق یا حساب بانکی دریافت وجه را "
                                          "انتخاب کنید.", field="cash_box_id")
                receipt = self.vouchers.create_receipt_in_session(
                    session, ctx,
                    ReceiptInput(
                        receipt_date=when, amount=sale,
                        receipt_type=TC.RECEIPT_OTHER, method=data.method,
                        cash_box_id=data.cash_box_id,
                        bank_account_id=data.bank_account_id,
                        payer_name=(data.buyer_name or "").strip(),
                        counter_account_id=asset.asset_account_id,
                        description=f"فروش دارایی {asset.code} — {asset.title_fa}",
                        idempotency_key=f"asset:{asset.id}:sale"))
                self.vouchers.post_receipt_in_session(session, receipt, ctx)
                receipt_id = receipt.id

            cost = Decimal(asset.initial_value or 0)
            remaining_cost = cost - sale
            lines: list[JournalLineInput] = []
            if accumulated > 0:
                lines.append(JournalLineInput(
                    account_id=asset.accumulated_account_id, debit=accumulated,
                    credit=ZERO, description=f"استهلاک انباشتهٔ {asset.code}"))
            if remaining_cost > 0:
                lines.append(JournalLineInput(
                    account_id=asset.asset_account_id, debit=ZERO,
                    credit=remaining_cost,
                    description=f"حذف باقیماندهٔ بهای تمام‌شدهٔ {asset.code}"))
            elif remaining_cost < 0:
                lines.append(JournalLineInput(
                    account_id=asset.asset_account_id, debit=-remaining_cost,
                    credit=ZERO,
                    description=f"مازاد فروش بالای بهای تمام‌شدهٔ {asset.code}"))
            if gain_loss > 0:
                if gain_account is None:
                    raise ValidationError("حساب سود فروش دارایی در کدینگ نیست.")
                lines.append(JournalLineInput(
                    account_id=gain_account.id, debit=ZERO, credit=gain_loss,
                    description=f"سود واگذاری {asset.code}"))
            elif gain_loss < 0:
                if loss_account is None:
                    raise ValidationError("حساب زیان فروش دارایی در کدینگ نیست.")
                lines.append(JournalLineInput(
                    account_id=loss_account.id, debit=-gain_loss, credit=ZERO,
                    description=f"زیان واگذاری {asset.code}"))
            journal = post_system_journal(
                session, journals=self.journals, ctx=ctx, entry_date=when,
                title_fa=f"{A.DISPOSAL_TITLES_FA[data.kind]} دارایی {asset.code}",
                reference_no=asset.code,
                idempotency_key=f"asset:{asset.id}:disposal",
                notes=data.reason or "", draft=_Draft(tuple(lines)),
                source_kind="asset_disposal", source_id=asset.id)

            number = next_document_number(session, AssetDisposal, prefix="DSP", on_date=when)
            row = AssetDisposal(
                number=number, asset_id=asset.id, kind=data.kind, disposal_date=when,
                sale_amount=sale, buyer_name=(data.buyer_name or "").strip() or None,
                book_value=book, accumulated=accumulated,
                initial_value=Decimal(asset.initial_value or 0),
                gain_loss=gain_loss, journal_id=journal.id, receipt_id=receipt_id,
                reason=(data.reason or "").strip() or None,
                created_by_id=getattr(ctx, "user_id", None))
            session.add(row)
            asset.status = (A.ASSET_SOLD if data.kind == A.DISPOSAL_SALE else
                            A.ASSET_RETIRED if data.kind == A.DISPOSAL_RETIRE else
                            A.ASSET_WRITTEN_OFF)
            self._record_movement(session, ctx, asset, A.MOVE_STATUS, when,
                                  to_value=A.ASSET_STATUS_TITLES_FA[asset.status],
                                  note=data.reason or "")
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="asset", entity_id=asset.id, action="dispose",
                summary_fa=f"{A.DISPOSAL_TITLES_FA[data.kind]} دارایی {asset.code}",
                after={"sale": str(sale), "book": str(book), "gain_loss": str(gain_loss),
                       "journal_id": journal.id, "receipt_id": receipt_id},
                session=session)
            return self._disposal_row(session, row, asset)

    def list_disposals(self, ctx: SecurityContext | None) -> list[DisposalRow]:
        require_permission(ctx, "assets.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(AssetDisposal).order_by(AssetDisposal.disposal_date.desc())
            ).scalars()
            return [self._disposal_row(session, row, session.get(Asset, row.asset_id))
                    for row in rows]

    # ------------------------------------------------------------------- helpers
    def _get_asset(self, session: Session, asset_id: int) -> Asset:
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise NotFoundError("دارایی مورد نظر یافت نشد.")
        return asset

    def _account(self, session: Session, code: str) -> Account | None:
        return session.execute(select(Account).where(Account.code == code)).scalars().first()

    def _resolve_accounts(self, session: Session, data: CategoryInput,
                          existing: AssetCategory | None = None) -> dict:
        def pick(explicit: int | None, code: str, fallback: int | None):
            if explicit:
                account = session.get(Account, explicit)
                if account is None:
                    raise ValidationError("حساب انتخاب‌شده یافت نشد.")
                return account.id
            if fallback:
                return fallback
            account = self._account(session, code)
            return account.id if account else None

        return {
            "asset_account_id": pick(
                data.asset_account_id, A.DEFAULT_ASSET_ACCOUNT_CODE,
                existing.asset_account_id if existing else None),
            "accumulated_account_id": pick(
                data.accumulated_account_id, A.DEFAULT_ACCUMULATED_CODE,
                existing.accumulated_account_id if existing else None),
            "expense_account_id": pick(
                data.expense_account_id, A.DEFAULT_DEPRECIATION_EXPENSE_CODE,
                existing.expense_account_id if existing else None),
        }

    def _validate_asset(self, session: Session, data: AssetInput,
                        existing: Asset | None = None) -> dict:
        if data.category_id is None and existing is None:
            raise ValidationError("دستهٔ دارایی را انتخاب کنید.", field="category_id")
        category_id = data.category_id or (existing.category_id if existing else None)
        category = session.get(AssetCategory, category_id)
        if category is None:
            raise ValidationError("دستهٔ دارایی یافت نشد.", field="category_id")
        in_service = data.in_service_date or (existing.in_service_date if existing else None)
        if in_service is None:
            raise ValidationError("تاریخ بهره‌برداری را وارد کنید.", field="in_service_date")
        purchase_price = to_money(data.purchase_price, field="purchase_price")
        related = to_money(data.related_costs, field="related_costs")
        initial = (to_money(data.initial_value, field="initial_value")
                   if data.initial_value not in (None, "") else purchase_price + related)
        if initial <= 0:
            raise ValidationError("بهای تمام‌شده باید بزرگ‌تر از صفر باشد.",
                                  field="initial_value")
        salvage = to_money(data.salvage_value, field="salvage_value")
        if salvage < 0 or salvage >= initial:
            raise ValidationError("ارزش اسقاط باید کوچک‌تر از بهای تمام‌شده باشد.",
                                  field="salvage_value")
        method = data.method or (existing.method if existing else category.default_method)
        if method not in dict(A.METHODS):
            raise ValidationError("روش استهلاک معتبر نیست.", field="method")
        life = data.useful_life_months if data.useful_life_months is not None else (
            existing.useful_life_months if existing
            else category.default_useful_life_years * 12)
        if int(life) <= 0:
            raise ValidationError("عمر مفید باید بزرگ‌تر از صفر باشد.",
                                  field="useful_life_months")
        status = data.status or A.ASSET_IN_USE
        if status not in dict(A.ASSET_STATUSES):
            raise ValidationError("وضعیت دارایی معتبر نیست.", field="status")
        if existing is not None and status != existing.status:
            self._assert_status_transition(existing.status, status)
        custodian = data.custodian_employee_id
        if custodian and session.get(Employee, custodian) is None:
            raise ValidationError("امانت‌دار انتخاب‌شده یافت نشد.",
                                  field="custodian_employee_id")
        if data.org_unit_id and session.get(OrgUnit, data.org_unit_id) is None:
            raise ValidationError("واحد سازمانی انتخاب‌شده یافت نشد.", field="org_unit_id")
        if data.supplier_detail_id and session.get(DetailAccount,
                                                   data.supplier_detail_id) is None:
            raise ValidationError("تأمین‌کنندهٔ انتخاب‌شده یافت نشد.",
                                  field="supplier_detail_id")
        code = (clean_code(data.code, label="کد دارایی")
                if (data.code or "").strip() else "")
        return {
            "code": code,
            "title_fa": clean_text(data.title_fa, field="title_fa", label="نام دارایی",
                                   required=True, max_length=200),
            "category_id": category.id, "serial_no": (data.serial_no or "").strip() or None,
            "model": (data.model or "").strip() or None,
            "manufacturer": (data.manufacturer or "").strip() or None,
            "purchase_date": data.purchase_date, "in_service_date": in_service,
            "supplier_detail_id": data.supplier_detail_id,
            "invoice_id": data.invoice_id, "location": (data.location or "").strip() or None,
            "custodian_employee_id": custodian, "org_unit_id": data.org_unit_id,
            "purchase_price": purchase_price, "related_costs": related,
            "initial_value": initial, "salvage_value": salvage,
            "useful_life_months": int(life), "method": method,
            "declining_rate": (Decimal(str(data.declining_rate))
                               if data.declining_rate not in (None, "") else
                               (existing.declining_rate if existing else None)),
            "total_units": (Decimal(str(data.total_units))
                            if data.total_units not in (None, "")
                            else (existing.total_units if existing else None)),
            "asset_account_id": data.asset_account_id or (
                existing.asset_account_id if existing else category.asset_account_id),
            "accumulated_account_id": data.accumulated_account_id or (
                existing.accumulated_account_id if existing
                else category.accumulated_account_id),
            "expense_account_id": data.expense_account_id or (
                existing.expense_account_id if existing else category.expense_account_id),
            "status": status, "depreciation_start_override": data.depreciation_start_override,
            "notes": (data.notes or "").strip() or None,
            "attachment_path": (data.attachment_path or "").strip() or None,
        }

    def _assert_status_transition(self, current: str, target: str) -> None:
        allowed = A.ASSET_TRANSITIONS.get(current, ())
        if target not in allowed:
            raise ConflictError(
                f"تغییر وضعیت از «{A.ASSET_STATUS_TITLES_FA.get(current, current)}» به "
                f"«{A.ASSET_STATUS_TITLES_FA.get(target, target)}» مجاز نیست.")

    def _record_movement(self, session: Session, ctx: SecurityContext | None,
                         asset: Asset, kind: str, when: _dt.date, *,
                         from_value: str = "", to_value: str = "", note: str = "",
                         from_employee_id: int | None = None,
                         to_employee_id: int | None = None,
                         from_org_unit_id: int | None = None,
                         to_org_unit_id: int | None = None) -> None:
        session.add(AssetMovement(
            asset_id=asset.id, kind=kind, movement_date=when,
            from_value=from_value or None, to_value=to_value or None,
            from_employee_id=from_employee_id, to_employee_id=to_employee_id,
            from_org_unit_id=from_org_unit_id, to_org_unit_id=to_org_unit_id,
            note=note or None, user_id=getattr(ctx, "user_id", None),
            user_name=getattr(ctx, "full_name", None)))

    def _accumulated(self, session: Session, asset_id: int) -> Decimal:
        total = session.execute(
            select(func.sum(DepreciationLine.amount))
            .join(DepreciationRun, DepreciationRun.id == DepreciationLine.run_id)
            .where(DepreciationLine.asset_id == asset_id,
                   DepreciationRun.status == A.DEP_RUN_POSTED)).scalar()
        return Decimal(total or 0)

    def _unit_title(self, session: Session, unit_id: int | None) -> str:
        if not unit_id:
            return ""
        unit = session.get(OrgUnit, unit_id)
        return unit.title_fa if unit else ""

    def _employee_name(self, session: Session, employee_id: int | None) -> str:
        if not employee_id:
            return ""
        employee = session.get(Employee, employee_id)
        return (f"{employee.first_name} {employee.last_name}".strip()
                if employee else "")

    def _setting_text(self, key: str, default: str) -> str:
        if self.settings is None:
            return default
        try:
            return self.settings.snapshot().str(key) or default
        except Exception:  # pragma: no cover
            return default

    # -------------------------------------------------------------------- rows
    def _category_row(self, row: AssetCategory, count: int) -> CategoryRow:
        return CategoryRow(
            id=row.id, code=row.code, title_fa=row.title_fa, kind=row.kind,
            kind_fa=A.CATEGORY_TITLES_FA.get(row.kind, row.kind),
            asset_account_id=row.asset_account_id,
            accumulated_account_id=row.accumulated_account_id,
            expense_account_id=row.expense_account_id,
            default_useful_life_years=int(row.default_useful_life_years or 0),
            default_method=row.default_method,
            default_method_fa=A.METHOD_TITLES_FA.get(row.default_method,
                                                     row.default_method),
            assets_count=count, is_active=row.is_active)

    def _asset_row(self, session: Session, asset: Asset) -> AssetRow:
        category = session.get(AssetCategory, asset.category_id)
        accumulated = self._accumulated(session, asset.id)
        initial = Decimal(asset.initial_value or 0)
        book = (initial - accumulated).quantize(Decimal("0.01"))
        monthly = ZERO
        if asset.method == A.METHOD_STRAIGHT_LINE and asset.useful_life_months:
            monthly = ((initial - Decimal(asset.salvage_value or 0))
                       / Decimal(asset.useful_life_months)).quantize(Decimal("0.01"))
        custodian = self._employee_name(session, asset.custodian_employee_id)
        supplier = ""
        if asset.supplier_detail_id:
            detail = session.get(DetailAccount, asset.supplier_detail_id)
            supplier = detail.name if detail else ""
        return AssetRow(
            id=asset.id, code=asset.code, title_fa=asset.title_fa,
            category=category.title_fa if category else "",
            category_id=asset.category_id, serial_no=asset.serial_no or "",
            model=asset.model or "", purchase_date=asset.purchase_date,
            in_service_date=asset.in_service_date, supplier_name=supplier,
            location=asset.location or "",
            custodian_employee_id=asset.custodian_employee_id,
            custodian_name=custodian,
            org_unit_title=self._unit_title(session, asset.org_unit_id),
            purchase_price=Decimal(asset.purchase_price or 0),
            related_costs=Decimal(asset.related_costs or 0),
            initial_value=initial, salvage_value=Decimal(asset.salvage_value or 0),
            useful_life_months=int(asset.useful_life_months or 0),
            method=asset.method,
            method_fa=A.METHOD_TITLES_FA.get(asset.method, asset.method),
            declining_rate=(Decimal(asset.declining_rate)
                            if asset.declining_rate is not None else None),
            status=asset.status,
            status_fa=A.ASSET_STATUS_TITLES_FA.get(asset.status, asset.status),
            accumulated=accumulated, book_value=book,
            monthly_depreciation=monthly,
            is_fully_depreciated=book <= Decimal(asset.salvage_value or 0),
            notes=asset.notes or "")

    def _maintenance_row(self, session: Session, row: AssetMaintenance) -> MaintenanceRow:
        asset = session.get(Asset, row.asset_id)
        return MaintenanceRow(
            id=row.id, asset_id=row.asset_id, asset_code=asset.code if asset else "",
            asset_title=asset.title_fa if asset else "", kind=row.kind,
            kind_fa=A.MAINT_TITLES_FA.get(row.kind, row.kind),
            service_date=row.service_date, cost=Decimal(row.cost or 0),
            contractor=row.contractor or "", description=row.description or "",
            next_service_date=row.next_service_date, is_periodic=row.is_periodic)

    def _disposal_row(self, session: Session, row: AssetDisposal,
                      asset: Asset | None) -> DisposalRow:
        return DisposalRow(
            id=row.id, number=row.number, asset_id=row.asset_id,
            asset_code=asset.code if asset else "",
            asset_title=asset.title_fa if asset else "", kind=row.kind,
            kind_fa=A.DISPOSAL_TITLES_FA.get(row.kind, row.kind),
            disposal_date=row.disposal_date, sale_amount=Decimal(row.sale_amount or 0),
            buyer_name=row.buyer_name or "", book_value=Decimal(row.book_value or 0),
            accumulated=Decimal(row.accumulated or 0),
            initial_value=Decimal(row.initial_value or 0),
            gain_loss=Decimal(row.gain_loss or 0), journal_id=row.journal_id,
            receipt_id=row.receipt_id, reason=row.reason or "")


class _Draft:
    """Minimal duck-typed journal draft for :func:`post_system_journal`."""

    def __init__(self, lines) -> None:
        self.lines = tuple(lines)
        self.total_debit = sum((Decimal(line.debit or 0) for line in self.lines), ZERO)
        self.total_credit = sum((Decimal(line.credit or 0) for line in self.lines), ZERO)
