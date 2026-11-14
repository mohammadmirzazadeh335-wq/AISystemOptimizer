"""Catalogue: units, categories, brands, products and services.

The catalogue is the backbone of every commercial document: an invoice line
always points at a product row, and stock is kept per product in its **base
unit**. Sub-units (carton, pack, ...) carry a conversion factor against the
base unit, so a line can be entered in a carton while the warehouse stores
counts - the factor is copied onto the line at entry time, which keeps old
documents correct even if the factor is changed later.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Brand,
    Invoice,
    InvoiceLine,
    Product,
    ProductCategory,
    StockBalance,
    StockDocumentLine,
    Unit,
    Warehouse,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import (
    ZERO,
    clean_code,
    clean_text,
    to_money,
    to_quantity,
)

MAX_CATEGORY_DEPTH = CC.CATEGORY_MAX_DEPTH


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class UnitRow:
    id: int
    code: str
    title_fa: str
    kind: str
    kind_fa: str
    factor: Decimal
    base_unit_id: int | None
    base_unit_title: str
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.title_fa} ({self.code})"

    @property
    def is_base(self) -> bool:
        return self.base_unit_id is None

    @property
    def factor_fa(self) -> str:
        if self.is_base:
            return "واحد پایه"
        return f"× {self.factor.normalize():f}"


@dataclass(frozen=True)
class CategoryRow:
    id: int
    code: str
    title_fa: str
    parent_id: int | None
    parent_title: str
    depth: int
    is_active: bool
    description: str
    product_count: int

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class BrandRow:
    id: int
    code: str
    title_fa: str
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


@dataclass(frozen=True)
class ProductRow:
    id: int
    code: str
    name_fa: str
    name_en: str
    barcode: str
    kind: str
    kind_fa: str
    category_id: int | None
    category_title: str
    brand_id: int | None
    brand_title: str
    unit_id: int
    unit_title: str
    description: str
    image_path: str
    min_stock: Decimal
    max_stock: Decimal
    reorder_point: Decimal
    purchase_price: Decimal
    sale_price: Decimal
    is_active: bool
    total_stock: Decimal

    @property
    def display(self) -> str:
        return f"{self.code} — {self.name_fa}"

    @property
    def is_service(self) -> bool:
        return self.kind == CC.PRODUCT_SERVICE

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"

    @property
    def stock_status_fa(self) -> str:
        if self.is_service:
            return "خدمت (بدون موجودی)"
        if self.total_stock <= 0:
            return "ناموجود"
        if self.reorder_point and self.total_stock <= self.reorder_point:
            return "کم‌موجود"
        return "موجود"


@dataclass(frozen=True)
class ProductInput:
    code: str
    name_fa: str
    unit_id: int
    kind: str = CC.PRODUCT_GOODS
    name_en: str = ""
    barcode: str = ""
    category_id: int | None = None
    brand_id: int | None = None
    description: str = ""
    image_path: str = ""
    min_stock: Decimal | str | int = 0
    max_stock: Decimal | str | int = 0
    reorder_point: Decimal | str | int = 0
    purchase_price: Decimal | str | int = 0
    sale_price: Decimal | str | int = 0
    is_active: bool = True


@dataclass(frozen=True)
class ProductFilter:
    search: str = ""
    kind: str | None = None
    category_id: int | None = None
    brand_id: int | None = None
    active: bool | None = None
    low_stock_only: bool = False
    warehouse_id: int | None = None


@dataclass(frozen=True)
class StockAtWarehouse:
    warehouse_id: int
    warehouse_title: str
    quantity: Decimal
    value: Decimal
    average_cost: Decimal


@dataclass(frozen=True)
class HistoryLine:
    document_no: str
    document_date: object
    kind: str
    kind_fa: str
    party_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    status_fa: str


# ------------------------------------------------------------------- service
class CatalogueService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------------ units
    def list_units(self, ctx: SecurityContext | None, *, active: bool | None = None,
                   search: str | None = None) -> list[UnitRow]:
        require_permission(ctx, "products.view")
        query = select(Unit).order_by(Unit.code)
        if active is not None:
            query = query.where(Unit.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Unit.code.like(needle), Unit.title_fa.like(needle)))
        with self.db.session_scope() as session:
            return [self._unit_row(unit) for unit in session.execute(query).scalars()]

    def unit_choices(self, ctx: SecurityContext | None, *, active_only: bool = True,
                     base_only: bool = False) -> list[tuple[int, str]]:
        require_permission(ctx, "products.view")
        query = select(Unit).order_by(Unit.is_active.desc(), Unit.code)
        if active_only:
            query = query.where(Unit.is_active.is_(True))
        if base_only:
            query = query.where(Unit.base_unit_id.is_(None))
        with self.db.session_scope() as session:
            return [(u.id, f"{u.title_fa} ({u.code})")
                    for u in session.execute(query).scalars()]

    def create_unit(self, ctx: SecurityContext | None, *, code: str, title_fa: str,
                    kind: str = "count", factor: Decimal | str | int = 1,
                    base_unit_id: int | None = None, description: str = "") -> UnitRow:
        require_permission(ctx, "products.edit")
        payload = self._validated_unit(code=code, title_fa=title_fa, kind=kind,
                                       factor=factor, base_unit_id=base_unit_id,
                                       description=description)
        with self.db.session_scope() as session:
            unit = Unit(**payload)
            session.add(unit)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("واحدی با این کد قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_unit", entity_id=unit.id, action="create",
                summary_fa=f"تعریف واحد {unit.title_fa} ({unit.code})",
                after={"code": unit.code, "factor": str(unit.factor)}, session=session)
            return self._unit_row(unit)

    def update_unit(self, ctx: SecurityContext | None, unit_id: int, *,
                    title_fa: str | None = None, kind: str | None = None,
                    factor: Decimal | str | int | None = None,
                    base_unit_id: int | None = None, description: str | None = None,
                    is_active: bool | None = None) -> UnitRow:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            unit = session.get(Unit, unit_id)
            if unit is None:
                raise NotFoundError("واحد مورد نظر یافت نشد.")
            if title_fa is not None:
                unit.title_fa = clean_text(title_fa, field="title_fa", label="عنوان واحد",
                                           required=True, max_length=60)
            if kind is not None:
                if kind not in CC.UNIT_KIND_TITLES_FA:
                    raise ValidationError("نوع واحد معتبر نیست.", field="kind")
                unit.kind = kind
            if base_unit_id is not None and base_unit_id != unit.base_unit_id:
                if base_unit_id == unit.id:
                    raise ValidationError("واحد نمی‌تواند پایهٔ خودش باشد.", field="base_unit_id")
                base = session.get(Unit, base_unit_id)
                if base is None:
                    raise NotFoundError("واحد پایه یافت نشد.")
                if base.base_unit_id is not None:
                    raise ValidationError("واحد پایه باید خودش یک واحد پایه باشد، نه زیرواحد.",
                                          field="base_unit_id")
                unit.base_unit_id = base.id
            if factor is not None:
                value = to_quantity(factor, field="factor", allow_zero=False)
                unit.factor = value
            if description is not None:
                unit.description = clean_text(description, field="description",
                                              label="توضیحات", max_length=300)
            if is_active is not None:
                unit.is_active = bool(is_active)
            if unit.base_unit_id is None:
                unit.factor = Decimal("1")
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_unit", entity_id=unit.id, action="update",
                summary_fa=f"ویرایش واحد {unit.title_fa}", session=session)
            return self._unit_row(unit)

    def convert(self, ctx: SecurityContext | None, quantity, *, from_unit_id: int,
                to_unit_id: int) -> Decimal:
        """Convert ``quantity`` between two compatible units.

        Conversion is allowed only inside one unit family (same base unit).
        Incompatible families raise a Persian validation error instead of
        silently producing nonsense.
        """
        require_permission(ctx, "products.view")
        qty = to_quantity(quantity, field="quantity")
        if from_unit_id == to_unit_id:
            return qty
        with self.db.session_scope() as session:
            source = session.get(Unit, from_unit_id)
            target = session.get(Unit, to_unit_id)
            if source is None or target is None:
                raise NotFoundError("واحد مورد نظر یافت نشد.")
            base_source = source.base_unit_id or source.id
            base_target = target.base_unit_id or target.id
            if base_source != base_target:
                raise ValidationError(
                    f"تبدیل «{source.title_fa}» به «{target.title_fa}» مجاز نیست: "
                    "این دو واحد از یک خانواده نیستند.", field="unit_id")
            in_base = qty * (source.factor if source.base_unit_id else Decimal(1))
            result = in_base / (target.factor if target.base_unit_id else Decimal(1))
            return result.quantize(Decimal("0.0001"))

    # ------------------------------------------------------------- categories
    def list_categories(self, ctx: SecurityContext | None, *, active: bool | None = None,
                        search: str | None = None) -> list[CategoryRow]:
        require_permission(ctx, "products.view")
        query = select(ProductCategory).order_by(ProductCategory.code)
        if active is not None:
            query = query.where(ProductCategory.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(ProductCategory.code.like(needle),
                                    ProductCategory.title_fa.like(needle)))
        with self.db.session_scope() as session:
            counts = dict(session.execute(
                select(Product.category_id, func.count(Product.id))
                .group_by(Product.category_id)).all())
            rows = [self._category_row(item, counts.get(item.id, 0))
                    for item in session.execute(query).scalars()]
        return rows

    def category_choices(self, ctx: SecurityContext | None, *,
                         active_only: bool = True) -> list[tuple[int, str]]:
        rows = self.list_categories(ctx, active=True if active_only else None)
        return [(row.id, f"{'— ' * (row.depth - 1)}{row.title_fa}") for row in rows]

    def create_category(self, ctx: SecurityContext | None, *, code: str, title_fa: str,
                        parent_id: int | None = None, description: str = "",
                        is_active: bool = True) -> CategoryRow:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            parent = session.get(ProductCategory, parent_id) if parent_id else None
            if parent_id and parent is None:
                raise NotFoundError("دستهٔ والد یافت نشد.")
            depth = self._category_depth(session, parent)
            if depth > MAX_CATEGORY_DEPTH:
                raise ValidationError(
                    f"حداکثر عمق دسته‌بندی {MAX_CATEGORY_DEPTH} سطح است.", field="parent_id")
            category = ProductCategory(
                code=clean_code(code, label="کد دسته", max_length=24),
                title_fa=clean_text(title_fa, field="title_fa", label="عنوان دسته",
                                    required=True, max_length=120),
                parent_id=parent.id if parent else None,
                description=clean_text(description, field="description", label="توضیحات",
                                       max_length=300),
                is_active=bool(is_active),
            )
            session.add(category)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("دسته‌بندی با این کد قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_category", entity_id=category.id,
                action="create", summary_fa=f"ایجاد دسته‌بندی {category.title_fa}",
                session=session)
            return self._category_row(category, 0)

    def update_category(self, ctx: SecurityContext | None, category_id: int, *,
                        title_fa: str | None = None, parent_id: int | None = None,
                        description: str | None = None,
                        is_active: bool | None = None) -> CategoryRow:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            category = session.get(ProductCategory, category_id)
            if category is None:
                raise NotFoundError("دسته‌بندی مورد نظر یافت نشد.")
            if title_fa is not None:
                category.title_fa = clean_text(title_fa, field="title_fa", label="عنوان دسته",
                                               required=True, max_length=120)
            if parent_id is not None and parent_id != category.parent_id:
                if parent_id == category.id:
                    raise ValidationError("یک دسته نمی‌تواند والد خودش باشد.", field="parent_id")
                parent = session.get(ProductCategory, parent_id) if parent_id else None
                if parent_id and parent is None:
                    raise NotFoundError("دستهٔ والد یافت نشد.")
                if parent is not None and self._is_descendant(session, parent, category.id):
                    raise ValidationError("دستهٔ والد نمی‌تواند زیرمجموعهٔ خود دسته باشد.",
                                          field="parent_id")
                depth = self._category_depth(session, parent)
                if depth > MAX_CATEGORY_DEPTH:
                    raise ValidationError(
                        f"حداکثر عمق دسته‌بندی {MAX_CATEGORY_DEPTH} سطح است.",
                        field="parent_id")
                category.parent_id = parent.id if parent else None
            if description is not None:
                category.description = clean_text(description, field="description",
                                                  label="توضیحات", max_length=300)
            if is_active is not None:
                category.is_active = bool(is_active)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_category", entity_id=category.id,
                action="update", summary_fa=f"ویرایش دسته‌بندی {category.title_fa}",
                session=session)
            return self._category_row(category, 0)

    def delete_category(self, ctx: SecurityContext | None, category_id: int) -> None:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            category = session.get(ProductCategory, category_id)
            if category is None:
                raise NotFoundError("دسته‌بندی مورد نظر یافت نشد.")
            children = session.execute(
                select(func.count(ProductCategory.id))
                .where(ProductCategory.parent_id == category_id)).scalar() or 0
            if children:
                raise ValidationError("این دسته زیرمجموعه دارد؛ ابتدا زیرمجموعه‌ها را جابه‌جا کنید.")
            products = session.execute(
                select(func.count(Product.id))
                .where(Product.category_id == category_id)).scalar() or 0
            if products:
                raise ValidationError(
                    f"این دسته برای {products} کالا استفاده شده است و قابل حذف نیست.")
            session.delete(category)
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_category", entity_id=category_id,
                action="delete", summary_fa=f"حذف دسته‌بندی {category.title_fa}",
                session=session)

    # ----------------------------------------------------------------- brands
    def list_brands(self, ctx: SecurityContext | None, *, active: bool | None = None,
                    search: str | None = None) -> list[BrandRow]:
        require_permission(ctx, "products.view")
        query = select(Brand).order_by(Brand.code)
        if active is not None:
            query = query.where(Brand.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Brand.code.like(needle), Brand.title_fa.like(needle)))
        with self.db.session_scope() as session:
            return [self._brand_row(item) for item in session.execute(query).scalars()]

    def brand_choices(self, ctx: SecurityContext | None, *,
                      active_only: bool = True) -> list[tuple[int, str]]:
        rows = self.list_brands(ctx, active=True if active_only else None)
        return [(row.id, row.title_fa) for row in rows]

    def create_brand(self, ctx: SecurityContext | None, *, code: str,
                     title_fa: str) -> BrandRow:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            brand = Brand(code=clean_code(code, label="کد برند", max_length=24),
                          title_fa=clean_text(title_fa, field="title_fa", label="نام برند",
                                              required=True, max_length=120))
            session.add(brand)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("برند با این کد قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_brand", entity_id=brand.id, action="create",
                summary_fa=f"ایجاد برند {brand.title_fa}", session=session)
            return self._brand_row(brand)

    # --------------------------------------------------------------- products
    def list_products(self, ctx: SecurityContext | None,
                      filters: ProductFilter | None = None) -> list[ProductRow]:
        require_permission(ctx, "products.view")
        filters = filters or ProductFilter()
        query = select(Product).order_by(Product.code)
        if filters.kind:
            query = query.where(Product.kind == filters.kind)
        if filters.category_id:
            query = query.where(Product.category_id == filters.category_id)
        if filters.brand_id:
            query = query.where(Product.brand_id == filters.brand_id)
        if filters.active is not None:
            query = query.where(Product.is_active.is_(bool(filters.active)))
        if filters.search:
            needle = f"%{filters.search.strip()}%"
            query = query.where(or_(Product.code.like(needle), Product.name_fa.like(needle),
                                    Product.name_en.like(needle),
                                    Product.barcode.like(needle)))
        with self.db.session_scope() as session:
            totals = self._stock_totals(session, filters.warehouse_id)
            rows = [self._product_row(item, totals.get(item.id, ZERO))
                    for item in session.execute(query).scalars()]
        if filters.low_stock_only:
            rows = [row for row in rows
                    if not row.is_service and row.reorder_point > 0
                    and row.total_stock <= row.reorder_point]
        return rows

    def get(self, ctx: SecurityContext | None, product_id: int) -> ProductRow:
        require_permission(ctx, "products.view")
        with self.db.session_scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NotFoundError("کالا/خدمت مورد نظر یافت نشد.")
            totals = self._stock_totals(session, None)
            return self._product_row(product, totals.get(product.id, ZERO))

    def find_by_barcode(self, ctx: SecurityContext | None, barcode: str) -> ProductRow:
        """Exact barcode lookup used by the keyboard-wedge scanner."""
        require_permission(ctx, "products.view")
        needle = (barcode or "").strip()
        if not needle:
            raise ValidationError("بارکد خالی است.", field="barcode")
        with self.db.session_scope() as session:
            product = session.execute(
                select(Product).where(Product.barcode == needle)).scalars().first()
            if product is None:
                raise NotFoundError(f"کالایی با بارکد «{needle}» یافت نشد.")
            totals = self._stock_totals(session, None)
            return self._product_row(product, totals.get(product.id, ZERO))

    def product_choices(self, ctx: SecurityContext | None, *, kind: str | None = None,
                        search: str | None = None, active_only: bool = True,
                        limit: int = 50) -> list[tuple[int, str]]:
        require_permission(ctx, "products.view")
        query = select(Product).order_by(Product.code).limit(max(1, min(limit, 500)))
        if active_only:
            query = query.where(Product.is_active.is_(True))
        if kind:
            query = query.where(Product.kind == kind)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Product.code.like(needle), Product.name_fa.like(needle),
                                    Product.name_en.like(needle),
                                    Product.barcode.like(needle)))
        with self.db.session_scope() as session:
            return [(p.id, f"{p.code} — {p.name_fa}")
                    for p in session.execute(query).scalars()]

    def create(self, ctx: SecurityContext | None, data: ProductInput) -> ProductRow:
        require_permission(ctx, "products.create")
        with self.db.session_scope() as session:
            payload = self._validated(session, data)
            product = Product(**payload, created_by_id=ctx.user_id if ctx else None)
            session.add(product)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد کالا یا بارکد وارد شده قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_product", entity_id=product.id,
                action="create", summary_fa=f"ایجاد کالا {product.code} — {product.name_fa}",
                after=self._product_snapshot(product), session=session)
            return self._product_row(product, ZERO)

    def update(self, ctx: SecurityContext | None, product_id: int,
               data: ProductInput) -> ProductRow:
        require_permission(ctx, "products.edit")
        with self.db.session_scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NotFoundError("کالا/خدمت مورد نظر یافت نشد.")
            before = self._product_snapshot(product)
            price_changed = (to_money(data.sale_price) != product.sale_price
                             or to_money(data.purchase_price) != product.purchase_price)
            if price_changed and not (ctx and ctx.has("products.price_change")):
                raise ValidationError(
                    "تغییر بهای خرید/فروش نیازمند مجوز «تغییر بهای فروش و خرید کالا» است.",
                    field="sale_price")
            payload = self._validated(session, data, product_id=product.id)
            for key, value in payload.items():
                setattr(product, key, value)
            product.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            after = self._product_snapshot(product)
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_product", entity_id=product.id,
                action="update", summary_fa=f"ویرایش کالا {product.code} — {product.name_fa}",
                before=before, after=after, session=session)
            return self._product_row(product, ZERO)

    def set_active(self, ctx: SecurityContext | None, product_id: int,
                   active: bool) -> ProductRow:
        require_permission(ctx, "products.deactivate")
        with self.db.session_scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NotFoundError("کالا/خدمت مورد نظر یافت نشد.")
            product.is_active = bool(active)
            product.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_product", entity_id=product.id,
                action="activate" if active else "deactivate",
                summary_fa=("فعال‌سازی" if active else "غیرفعال‌سازی")
                + f" کالا {product.code} — {product.name_fa}", session=session)
            return self._product_row(product, ZERO)

    def delete(self, ctx: SecurityContext | None, product_id: int) -> None:
        """Delete a product **only** when it has no commercial history."""
        require_permission(ctx, "products.delete")
        with self.db.session_scope() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NotFoundError("کالا/خدمت مورد نظر یافت نشد.")
            used = session.execute(
                select(func.count(StockDocumentLine.id))
                .where(StockDocumentLine.product_id == product_id)).scalar() or 0
            invoiced = session.execute(
                select(func.count(InvoiceLine.id))
                .where(InvoiceLine.product_id == product_id)).scalar() or 0
            if used or invoiced:
                raise ValidationError(
                    "این کالا سابقهٔ انبار یا فاکتور دارد و قابل حذف نیست؛ "
                    "به‌جای حذف آن را غیرفعال کنید.")
            session.delete(product)
            self.audit.log_audit(
                ctx=ctx, entity_type="commerce_product", entity_id=product_id,
                action="delete", summary_fa=f"حذف کالا {product.code} — {product.name_fa}",
                session=session)

    def stock_by_warehouse(self, ctx: SecurityContext | None,
                           product_id: int) -> list[StockAtWarehouse]:
        require_permission(ctx, "products.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(StockBalance, Warehouse)
                .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
                .where(StockBalance.product_id == product_id)
                .order_by(Warehouse.code)).all()
            return [StockAtWarehouse(
                warehouse_id=warehouse.id,
                warehouse_title=f"{warehouse.title_fa} ({warehouse.code})",
                quantity=balance.quantity,
                value=balance.value,
                average_cost=balance.average_cost,
            ) for balance, warehouse in rows]

    def purchase_history(self, ctx: SecurityContext | None, product_id: int, *,
                         limit: int = 50) -> list[HistoryLine]:
        require_permission(ctx, "products.view")
        return self._invoice_history(ctx, product_id, (CC.INVOICE_PURCHASE,
                                                       CC.INVOICE_PURCHASE_RETURN), limit)

    def sale_history(self, ctx: SecurityContext | None, product_id: int, *,
                     limit: int = 50) -> list[HistoryLine]:
        require_permission(ctx, "products.view")
        return self._invoice_history(ctx, product_id, (CC.INVOICE_SALE,
                                                       CC.INVOICE_SALE_RETURN), limit)

    # ------------------------------------------------------------- internals
    def _invoice_history(self, ctx, product_id: int, kinds: tuple[str, ...],
                         limit: int) -> list[HistoryLine]:
        from pars_erp.db.models import DetailAccount  # local: avoid a cycle in typing

        with self.db.session_scope() as session:
            rows = session.execute(
                select(InvoiceLine, Invoice, DetailAccount)
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .outerjoin(DetailAccount, DetailAccount.id == Invoice.party_detail_id)
                .where(InvoiceLine.product_id == product_id, Invoice.kind.in_(kinds))
                .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
                .limit(max(1, min(limit, 500)))).all()
            return [HistoryLine(
                document_no=invoice.number,
                document_date=invoice.invoice_date,
                kind=invoice.kind,
                kind_fa=CC.INVOICE_TITLES_FA.get(invoice.kind, invoice.kind),
                party_name=party.name if party else "",
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.line_total,
                status_fa=CC.DOC_STATUS_TITLES_FA.get(invoice.status, invoice.status),
            ) for line, invoice, party in rows]

    @staticmethod
    def _stock_totals(session, warehouse_id: int | None) -> dict[int, Decimal]:
        query = select(StockBalance.product_id, func.sum(StockBalance.quantity))
        if warehouse_id:
            query = query.where(StockBalance.warehouse_id == warehouse_id)
        query = query.group_by(StockBalance.product_id)
        return {pid: Decimal(qty or 0) for pid, qty in session.execute(query).all()}

    def _validated(self, session, data: ProductInput, *, product_id: int | None = None) -> dict:
        code = clean_code(data.code, label="کد کالا", max_length=32)
        name_fa = clean_text(data.name_fa, field="name_fa", label="نام کالا", required=True,
                             max_length=200)
        if data.kind not in CC.PRODUCT_KINDS:
            raise ValidationError("نوع کالا معتبر نیست.", field="kind")
        unit = session.get(Unit, data.unit_id)
        if unit is None:
            raise NotFoundError("واحد پایه انتخاب‌شده یافت نشد.")
        if not unit.is_active:
            raise ValidationError("واحد پایه انتخاب‌شده غیرفعال است.", field="unit_id")
        if unit.base_unit_id is not None:
            raise ValidationError("واحد پایهٔ کالا باید از نوع واحد پایه باشد.", field="unit_id")
        barcode = clean_text(data.barcode, field="barcode", label="بارکد", max_length=64)
        if barcode:
            clash = session.execute(
                select(Product).where(Product.barcode == barcode)).scalars().first()
            if clash is not None and clash.id != product_id:
                raise ConflictError(f"بارکد «{barcode}» قبلاً برای کالای دیگری ثبت شده است.")
        category = None
        if data.category_id:
            category = session.get(ProductCategory, data.category_id)
            if category is None:
                raise NotFoundError("دسته‌بندی انتخاب‌شده یافت نشد.")
        brand = None
        if data.brand_id:
            brand = session.get(Brand, data.brand_id)
            if brand is None:
                raise NotFoundError("برند انتخاب‌شده یافت نشد.")
        min_stock = to_quantity(data.min_stock, field="min_stock")
        max_stock = to_quantity(data.max_stock, field="max_stock")
        if max_stock and min_stock > max_stock:
            raise ValidationError("حداقل موجودی نمی‌تواند بیشتر از حداکثر باشد.",
                                  field="min_stock")
        return {
            "code": code,
            "name_fa": name_fa,
            "name_en": clean_text(data.name_en, field="name_en", label="نام انگلیسی",
                                  max_length=200),
            "barcode": barcode or None,
            "kind": data.kind,
            "category_id": category.id if category else None,
            "brand_id": brand.id if brand else None,
            "unit_id": unit.id,
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=1000),
            "image_path": clean_text(data.image_path, field="image_path", label="تصویر",
                                     max_length=300),
            "min_stock": min_stock,
            "max_stock": max_stock,
            "reorder_point": to_quantity(data.reorder_point, field="reorder_point"),
            "purchase_price": to_money(data.purchase_price, field="purchase_price"),
            "sale_price": to_money(data.sale_price, field="sale_price"),
            "is_active": bool(data.is_active),
        }

    @staticmethod
    def _validated_unit(*, code: str, title_fa: str, kind: str, factor, base_unit_id,
                        description: str) -> dict:
        if kind not in CC.UNIT_KIND_TITLES_FA:
            raise ValidationError("نوع واحد معتبر نیست.", field="kind")
        value = to_quantity(factor, field="factor", allow_zero=False)
        if base_unit_id is None:
            value = Decimal("1")
        return {
            "code": clean_code(code, label="کد واحد", max_length=16),
            "title_fa": clean_text(title_fa, field="title_fa", label="عنوان واحد",
                                   required=True, max_length=60),
            "kind": kind,
            "factor": value,
            "base_unit_id": None if base_unit_id is None else int(base_unit_id),
            "description": clean_text(description, field="description", label="توضیحات",
                                      max_length=300),
        }

    @staticmethod
    def _category_depth(session, parent: ProductCategory | None) -> int:
        depth = 1
        node = parent
        guard = 0
        while node is not None and guard < 20:
            depth += 1
            node = session.get(ProductCategory, node.parent_id) if node.parent_id else None
            guard += 1
        return depth

    @staticmethod
    def _is_descendant(session, candidate: ProductCategory, ancestor_id: int) -> bool:
        node = candidate
        guard = 0
        while node is not None and guard < 20:
            if node.id == ancestor_id:
                return True
            node = session.get(ProductCategory, node.parent_id) if node.parent_id else None
            guard += 1
        return False

    @staticmethod
    def _unit_row(unit: Unit) -> UnitRow:
        return UnitRow(
            id=unit.id, code=unit.code, title_fa=unit.title_fa, kind=unit.kind,
            kind_fa=CC.UNIT_KIND_TITLES_FA.get(unit.kind, unit.kind),
            factor=unit.factor, base_unit_id=unit.base_unit_id,
            base_unit_title=unit.base_unit.title_fa if unit.base_unit else "",
            is_active=unit.is_active,
        )

    @staticmethod
    def _category_row(category: ProductCategory, product_count: int) -> CategoryRow:
        depth = 1
        node = category
        guard = 0
        while getattr(node, "parent", None) is not None and guard < 20:
            depth += 1
            node = node.parent
            guard += 1
        return CategoryRow(
            id=category.id, code=category.code, title_fa=category.title_fa,
            parent_id=category.parent_id,
            parent_title=category.parent.title_fa if category.parent else "",
            depth=depth, is_active=category.is_active,
            description=category.description or "", product_count=product_count,
        )

    @staticmethod
    def _brand_row(brand: Brand) -> BrandRow:
        return BrandRow(id=brand.id, code=brand.code, title_fa=brand.title_fa,
                        is_active=brand.is_active)

    @staticmethod
    def _product_row(product: Product, total_stock: Decimal) -> ProductRow:
        return ProductRow(
            id=product.id, code=product.code, name_fa=product.name_fa,
            name_en=product.name_en or "", barcode=product.barcode or "",
            kind=product.kind, kind_fa=CC.PRODUCT_KIND_TITLES_FA.get(product.kind, product.kind),
            category_id=product.category_id,
            category_title=product.category.title_fa if product.category else "",
            brand_id=product.brand_id,
            brand_title=product.brand.title_fa if product.brand else "",
            unit_id=product.unit_id,
            unit_title=product.unit.title_fa if product.unit else "",
            description=product.description or "", image_path=product.image_path or "",
            min_stock=product.min_stock, max_stock=product.max_stock,
            reorder_point=product.reorder_point, purchase_price=product.purchase_price,
            sale_price=product.sale_price, is_active=product.is_active,
            total_stock=total_stock,
        )

    @staticmethod
    def _product_snapshot(product: Product) -> dict:
        return {
            "code": product.code, "name_fa": product.name_fa,
            "barcode": product.barcode, "kind": product.kind,
            "unit_id": product.unit_id,
            "purchase_price": str(product.purchase_price),
            "sale_price": str(product.sale_price),
            "is_active": product.is_active,
        }
