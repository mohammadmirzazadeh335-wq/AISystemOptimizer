"""Warehouses, stock movements, valuation and stock counts.

Design notes
------------
* Every movement belongs to a :class:`StockDocument` with a unique number, a
  date, an author and a status. Nothing touches a balance directly: documents
  are created as drafts and applied by :meth:`InventoryService.post_document`,
  which runs inside one database transaction (balances, FIFO layers, the
  document status and the audit trail either all succeed or all roll back).
* Two valuation methods are supported and can be selected per company
  (settings) or per warehouse:

  - **weighted average**: ``com_stock_balances`` keeps quantity *and* value, so
    the average cost is ``value / quantity``. Issues consume at that average.
  - **FIFO**: ``com_stock_layers`` keeps one row per receipt with its remaining
    quantity and cost; issues consume the oldest layers first.

  Both stores are maintained *in the same transaction* as the movement, and
  historical documents/layers are never rewritten - so switching the method
  only changes future issues, never the cardex that has already been printed.
* Negative stock is refused by default. A warehouse may opt in
  (``allow_negative``) and the acting user still needs ``stock.negative_override``;
  every override is written to the security log.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Product,
    ProductCategory,
    StockBalance,
    StockCountLine,
    StockCountSheet,
    StockDocument,
    StockDocumentLine,
    StockLayer,
    Unit,
    Warehouse,
)
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService, EventType
from pars_erp.services.commerce_common import (
    ZERO,
    allow_negative_default,
    clean_code,
    clean_text,
    get_or_404,
    next_document_number,
    require_status,
    to_money,
    to_quantity,
    valuation_method,
)

QTY = Decimal("0.0001")


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class WarehouseInput:
    code: str
    title_fa: str
    keeper: str = ""
    address: str = ""
    is_primary: bool = False
    is_active: bool = True
    allow_negative: bool = False
    valuation_method: str | None = None
    description: str = ""


@dataclass(frozen=True)
class WarehouseRow:
    id: int
    code: str
    title_fa: str
    keeper: str
    address: str
    is_primary: bool
    is_active: bool
    allow_negative: bool
    valuation_method: str
    valuation_fa: str
    item_count: int
    total_value: Decimal

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"


@dataclass(frozen=True)
class StockLineInput:
    product_id: int
    quantity: Decimal | str | int
    unit_id: int | None = None
    unit_cost: Decimal | str | int = 0
    direction: str = "in"
    note: str = ""


@dataclass(frozen=True)
class StockDocInput:
    kind: str
    doc_date: _dt.date
    warehouse_id: int
    lines: tuple[StockLineInput, ...]
    target_warehouse_id: int | None = None
    party_detail_id: int | None = None
    reference_no: str = ""
    note: str = ""
    idempotency_key: str | None = None
    source_kind: str | None = None
    source_id: int | None = None


@dataclass(frozen=True)
class StockDocLineRow:
    line_no: int
    product_id: int
    product_code: str
    product_name: str
    unit_title: str
    factor: Decimal
    quantity: Decimal
    base_quantity: Decimal
    direction: str
    unit_cost: Decimal
    value: Decimal
    balance_after: Decimal | None
    note: str

    @property
    def direction_fa(self) -> str:
        return "ورود" if self.direction == "in" else "خروج"


@dataclass(frozen=True)
class StockDocRow:
    id: int
    number: str
    kind: str
    kind_fa: str
    doc_date: _dt.date
    warehouse_title: str
    target_title: str
    party_name: str
    status: str
    status_fa: str
    total_value: Decimal
    note: str
    line_count: int
    posted_at: _dt.datetime | None
    created_by: str

    @property
    def display(self) -> str:
        return f"{self.number} — {self.kind_fa}"

    @property
    def is_editable(self) -> bool:
        return self.status == CC.STATUS_DRAFT


@dataclass(frozen=True)
class StockDocFilter:
    kind: str | None = None
    warehouse_id: int | None = None
    status: str | None = None
    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    search: str = ""


@dataclass(frozen=True)
class CardexRow:
    doc_date: _dt.date
    number: str
    kind_fa: str
    warehouse_title: str
    quantity_in: Decimal
    quantity_out: Decimal
    balance: Decimal
    unit_cost: Decimal
    value: Decimal
    note: str

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity_in - self.quantity_out


@dataclass(frozen=True)
class BalanceRow:
    product_id: int
    code: str
    name_fa: str
    category_title: str
    unit_title: str
    warehouse_id: int | None
    warehouse_title: str
    quantity: Decimal
    value: Decimal
    average_cost: Decimal
    reorder_point: Decimal
    quantity_fa: str
    value_fa: str

    @property
    def status_fa(self) -> str:
        if self.quantity <= 0:
            return "ناموجود"
        if self.reorder_point and self.quantity <= self.reorder_point:
            return "کم‌موجود"
        return "موجود"


@dataclass(frozen=True)
class CountLineInput:
    product_id: int
    counted_quantity: Decimal | str | int
    note: str = ""


# ------------------------------------------------------------------- service
class InventoryService:
    def __init__(self, db: Database, audit: AuditService, settings) -> None:
        self.db = db
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------ warehouses
    def list_warehouses(self, ctx: SecurityContext | None, *,
                        active: bool | None = None,
                        search: str | None = None) -> list[WarehouseRow]:
        require_permission(ctx, "warehouses.view")
        query = select(Warehouse).order_by(Warehouse.is_primary.desc(), Warehouse.code)
        if active is not None:
            query = query.where(Warehouse.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Warehouse.code.like(needle),
                                    Warehouse.title_fa.like(needle),
                                    Warehouse.keeper.like(needle)))
        with self.db.session_scope() as session:
            stats = {
                wid: (int(count or 0), Decimal(value or 0))
                for wid, count, value in session.execute(
                    select(StockBalance.warehouse_id, func.count(StockBalance.id),
                           func.sum(StockBalance.value))
                    .group_by(StockBalance.warehouse_id)).all()
            }
            return [self._warehouse_row(w, *stats.get(w.id, (0, ZERO)))
                    for w in session.execute(query).scalars()]

    def warehouse_choices(self, ctx: SecurityContext | None, *,
                          active_only: bool = True) -> list[tuple[int, str]]:
        require_permission(ctx, "warehouses.view")
        query = select(Warehouse).order_by(Warehouse.is_primary.desc(), Warehouse.code)
        if active_only:
            query = query.where(Warehouse.is_active.is_(True))
        with self.db.session_scope() as session:
            return [(w.id, f"{w.title_fa} ({w.code})")
                    for w in session.execute(query).scalars()]

    def primary_warehouse_id(self, ctx: SecurityContext | None) -> int | None:
        require_permission(ctx, "warehouses.view")
        with self.db.session_scope() as session:
            warehouse = session.execute(
                select(Warehouse).where(Warehouse.is_primary.is_(True),
                                        Warehouse.is_active.is_(True))).scalars().first()
            if warehouse is None:
                warehouse = session.execute(
                    select(Warehouse).where(Warehouse.is_active.is_(True))
                    .order_by(Warehouse.id)).scalars().first()
            return warehouse.id if warehouse else None

    def create_warehouse(self, ctx: SecurityContext | None,
                         data: WarehouseInput) -> WarehouseRow:
        require_permission(ctx, "warehouses.edit")
        with self.db.session_scope() as session:
            payload = self._validated_warehouse(session, data)
            warehouse = Warehouse(**payload)
            session.add(warehouse)
            if warehouse.is_primary:
                self._clear_primary(session)
                warehouse.is_primary = True
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("انباری با این کد قبلاً ثبت شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="warehouse", entity_id=warehouse.id, action="create",
                summary_fa=f"ایجاد انبار {warehouse.code} — {warehouse.title_fa}",
                session=session)
            return self._warehouse_row(warehouse, 0, ZERO)

    def update_warehouse(self, ctx: SecurityContext | None, warehouse_id: int,
                         data: WarehouseInput) -> WarehouseRow:
        require_permission(ctx, "warehouses.edit")
        with self.db.session_scope() as session:
            warehouse = get_or_404(session, Warehouse, warehouse_id,
                                   "انبار مورد نظر یافت نشد.")
            payload = self._validated_warehouse(session, data, warehouse_id=warehouse.id)
            before = self._warehouse_snapshot(warehouse)
            for key, value in payload.items():
                setattr(warehouse, key, value)
            if warehouse.is_primary:
                self._clear_primary(session, keep=warehouse.id)
                warehouse.is_primary = True
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="warehouse", entity_id=warehouse.id, action="update",
                summary_fa=f"ویرایش انبار {warehouse.code} — {warehouse.title_fa}",
                before=before, after=self._warehouse_snapshot(warehouse), session=session)
            return self._warehouse_row(warehouse, 0, ZERO)

    # ------------------------------------------------------------ documents
    def create_document(self, ctx: SecurityContext | None,
                        data: StockDocInput) -> StockDocRow:
        permission = self._permission_for(data.kind)
        require_permission(ctx, permission)
        with self.db.session_scope() as session:
            doc = self._prepare_document(session, data)
            session.add(doc)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("شمارهٔ سند انبار هم‌زمان ثبت شد؛ دوباره تلاش کنید.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="stock_document", entity_id=doc.id, action="create",
                summary_fa=f"ایجاد سند {doc.number} ({CC.STOCK_MOVE_TITLES_FA.get(doc.kind)})",
                after=self._doc_snapshot(doc), session=session)
            return self._doc_row(session, doc)

    def update_document(self, ctx: SecurityContext | None, document_id: int,
                        data: StockDocInput) -> StockDocRow:
        require_permission(ctx, self._permission_for(data.kind))
        with self.db.session_scope() as session:
            doc = get_or_404(session, StockDocument, document_id,
                             "سند انبار مورد نظر یافت نشد.")
            require_status(doc, CC.STATUS_DRAFT, label="سند انبار")
            rebuilt = self._prepare_document(session, data, existing=doc)
            session.flush()
            return self._doc_row(session, rebuilt)

    def delete_document(self, ctx: SecurityContext | None, document_id: int) -> None:
        require_permission(ctx, "stock.adjust")
        with self.db.session_scope() as session:
            doc = get_or_404(session, StockDocument, document_id,
                             "سند انبار مورد نظر یافت نشد.")
            if doc.status == CC.STATUS_POSTED:
                raise ValidationError(
                    "سند ثبت‌شده قابل حذف نیست؛ برای اصلاح، سند برگشت ثبت کنید.")
            session.delete(doc)
            self.audit.log_audit(
                ctx=ctx, entity_type="stock_document", entity_id=document_id,
                action="delete", summary_fa=f"حذف پیش‌نویس سند {doc.number}",
                session=session)

    def post_document(self, ctx: SecurityContext | None, document_id: int,
                      *, allow_negative: bool | None = None) -> StockDocRow:
        """Apply the document to balances and layers - atomically."""
        with self.db.session_scope() as session:
            doc = get_or_404(session, StockDocument, document_id,
                             "سند انبار مورد نظر یافت نشد.")
            self.post_document_in_session(session, doc, ctx,
                                          allow_negative=allow_negative)
            return self._doc_row(session, doc)

    # -- the same operations on a caller-owned session (invoice posting) -----
    def create_document_in_session(self, session, data: StockDocInput,
                                   ctx: SecurityContext | None) -> StockDocument:
        """Create a draft stock document inside an **existing** transaction."""
        doc = self._prepare_document(session, data)
        session.add(doc)
        session.flush()
        return doc

    def post_document_in_session(self, session, doc: StockDocument,
                                 ctx: SecurityContext | None, *,
                                 allow_negative: bool | None = None) -> StockDocument:
        self._post_in_session(session, doc, ctx, allow_negative=allow_negative)
        return doc

    def reverse_document_in_session(self, session, document_id: int,
                                    ctx: SecurityContext | None,
                                    reason: str) -> StockDocument:
        original = get_or_404(session, StockDocument, document_id,
                              "سند انبار مورد نظر یافت نشد.")
        require_status(original, CC.STATUS_POSTED, label="سند انبار")
        reverse_kind = {CC.MOVE_RECEIPT: CC.MOVE_ISSUE,
                        CC.MOVE_ISSUE: CC.MOVE_RECEIPT,
                        CC.MOVE_TRANSFER: CC.MOVE_TRANSFER,
                        CC.MOVE_ADJUSTMENT: CC.MOVE_ADJUSTMENT}.get(original.kind,
                                                                    CC.MOVE_ADJUSTMENT)
        data = StockDocInput(
            kind=reverse_kind, doc_date=_dt.date.today(),
            warehouse_id=original.warehouse_id,
            target_warehouse_id=original.target_warehouse_id,
            party_detail_id=original.party_detail_id,
            reference_no=original.number,
            note=f"برگشت سند {original.number}: {reason}",
            source_kind="reversal", source_id=original.id,
            lines=tuple(StockLineInput(
                product_id=line.product_id, quantity=line.quantity,
                unit_id=line.unit_id, unit_cost=line.unit_cost,
                direction=("out" if line.direction == "in" else "in")
                if original.kind == CC.MOVE_ADJUSTMENT else "in",
                note=line.note or "",
            ) for line in original.lines),
        )
        doc = self.create_document_in_session(session, data, ctx)
        self.post_document_in_session(session, doc, ctx, allow_negative=True)
        return doc

    def stock_on_hand_in_session(self, session, product_id: int,
                                 warehouse_id: int | None = None) -> Decimal:
        query = select(func.sum(StockBalance.quantity)).where(
            StockBalance.product_id == product_id)
        if warehouse_id:
            query = query.where(StockBalance.warehouse_id == warehouse_id)
        return Decimal(session.execute(query).scalar() or 0)

    def record_receipt(self, ctx: SecurityContext | None, *,
                       warehouse_id: int, lines: tuple[StockLineInput, ...],
                       doc_date: _dt.date | None = None, note: str = "",
                       party_detail_id: int | None = None,
                       reference_no: str = "") -> StockDocRow:
        return self._create_and_post(ctx, StockDocInput(
            kind=CC.MOVE_RECEIPT, doc_date=doc_date or _dt.date.today(),
            warehouse_id=warehouse_id, lines=lines, note=note,
            party_detail_id=party_detail_id, reference_no=reference_no))

    def record_issue(self, ctx: SecurityContext | None, *,
                     warehouse_id: int, lines: tuple[StockLineInput, ...],
                     doc_date: _dt.date | None = None, note: str = "",
                     party_detail_id: int | None = None,
                     reference_no: str = "") -> StockDocRow:
        return self._create_and_post(ctx, StockDocInput(
            kind=CC.MOVE_ISSUE, doc_date=doc_date or _dt.date.today(),
            warehouse_id=warehouse_id, lines=lines, note=note,
            party_detail_id=party_detail_id, reference_no=reference_no))

    def record_transfer(self, ctx: SecurityContext | None, *, warehouse_id: int,
                        target_warehouse_id: int,
                        lines: tuple[StockLineInput, ...],
                        doc_date: _dt.date | None = None, note: str = "") -> StockDocRow:
        return self._create_and_post(ctx, StockDocInput(
            kind=CC.MOVE_TRANSFER, doc_date=doc_date or _dt.date.today(),
            warehouse_id=warehouse_id, lines=lines, target_warehouse_id=target_warehouse_id,
            note=note))

    def record_adjustment(self, ctx: SecurityContext | None, *, warehouse_id: int,
                          lines: tuple[StockLineInput, ...], reason: str,
                          doc_date: _dt.date | None = None) -> StockDocRow:
        if len((reason or "").strip()) < 5:
            raise ValidationError("برای اصلاح موجودی، دلیل اصلاح را بنویسید (حداقل ۵ نویسه).",
                                  field="note")
        return self._create_and_post(ctx, StockDocInput(
            kind=CC.MOVE_ADJUSTMENT, doc_date=doc_date or _dt.date.today(),
            warehouse_id=warehouse_id, lines=lines, note=reason.strip()))

    def reverse_document(self, ctx: SecurityContext | None, document_id: int,
                         reason: str) -> StockDocRow:
        """Post the mirror image of a posted document (corrections are additive)."""
        require_permission(ctx, "stock.adjust")
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValidationError("برای برگشت سند، دلیل را بنویسید (حداقل ۵ نویسه).",
                                  field="note")
        with self.db.session_scope() as session:
            doc = self.reverse_document_in_session(session, document_id, ctx, reason)
            self.audit.log_security(
                event_type=EventType.STOCK_REVERSED,
                message_fa=f"سند {document_id} با سند {doc.number} برگشت داده شد.",
                ctx=ctx, details={"original_id": document_id, "reversal_id": doc.id,
                                  "reason": reason}, session=session)
            return self._doc_row(session, doc)

    def list_documents(self, ctx: SecurityContext | None,
                       filters: StockDocFilter | None = None) -> list[StockDocRow]:
        require_permission(ctx, "stock.view")
        filters = filters or StockDocFilter()
        query = select(StockDocument).order_by(StockDocument.doc_date.desc(),
                                              StockDocument.id.desc()).limit(1000)
        if filters.kind:
            query = query.where(StockDocument.kind == filters.kind)
        if filters.warehouse_id:
            query = query.where(or_(StockDocument.warehouse_id == filters.warehouse_id,
                                    StockDocument.target_warehouse_id == filters.warehouse_id))
        if filters.status:
            query = query.where(StockDocument.status == filters.status)
        if filters.date_from:
            query = query.where(StockDocument.doc_date >= filters.date_from)
        if filters.date_to:
            query = query.where(StockDocument.doc_date <= filters.date_to)
        if filters.search:
            needle = f"%{filters.search.strip()}%"
            query = query.where(or_(StockDocument.number.like(needle),
                                    StockDocument.reference_no.like(needle),
                                    StockDocument.note.like(needle)))
        with self.db.session_scope() as session:
            return [self._doc_row(session, doc)
                    for doc in session.execute(query).scalars()]

    def get_document(self, ctx: SecurityContext | None, document_id: int) -> StockDocRow:
        require_permission(ctx, "stock.view")
        with self.db.session_scope() as session:
            doc = get_or_404(session, StockDocument, document_id,
                             "سند انبار مورد نظر یافت نشد.")
            return self._doc_row(session, doc)

    def document_lines(self, ctx: SecurityContext | None,
                       document_id: int) -> list[StockDocLineRow]:
        require_permission(ctx, "stock.view")
        with self.db.session_scope() as session:
            doc = get_or_404(session, StockDocument, document_id,
                             "سند انبار مورد نظر یافت نشد.")
            return [self._line_row(line) for line in doc.lines]

    # -------------------------------------------------------------- queries
    def balances(self, ctx: SecurityContext | None, *, warehouse_id: int | None = None,
                 category_id: int | None = None, search: str | None = None,
                 include_zero: bool = True, low_only: bool = False,
                 zero_only: bool = False) -> list[BalanceRow]:
        require_permission(ctx, "stock.view")
        query = (select(StockBalance, Product, Warehouse)
                 .join(Product, Product.id == StockBalance.product_id)
                 .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
                 .order_by(Product.code, Warehouse.code))
        if warehouse_id:
            query = query.where(StockBalance.warehouse_id == warehouse_id)
        if category_id:
            query = query.where(Product.category_id == category_id)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(Product.code.like(needle), Product.name_fa.like(needle),
                                    Product.barcode.like(needle)))
        if not include_zero:
            query = query.where(StockBalance.quantity > 0)
        if zero_only:
            query = query.where(StockBalance.quantity <= 0)
        with self.db.session_scope() as session:
            categories = {c.id: c.title_fa
                          for c in session.execute(select(ProductCategory)).scalars()}
            rows = [self._balance_row(balance, product, warehouse, categories)
                    for balance, product, warehouse in session.execute(query).all()]
        if low_only:
            rows = [r for r in rows if r.quantity > 0 and r.reorder_point
                    and r.quantity <= r.reorder_point]
        return rows

    def stock_on_hand(self, ctx: SecurityContext | None, product_id: int, *,
                      warehouse_id: int | None = None) -> Decimal:
        require_permission(ctx, "stock.view")
        with self.db.session_scope() as session:
            query = select(func.sum(StockBalance.quantity)).where(
                StockBalance.product_id == product_id)
            if warehouse_id:
                query = query.where(StockBalance.warehouse_id == warehouse_id)
            return Decimal(session.execute(query).scalar() or 0)

    def cardex(self, ctx: SecurityContext | None, product_id: int, *,
               warehouse_id: int | None = None, date_from: _dt.date | None = None,
               date_to: _dt.date | None = None) -> list[CardexRow]:
        require_permission(ctx, "stock.cardex")
        with self.db.session_scope() as session:
            query = (select(StockDocumentLine, StockDocument)
                     .join(StockDocument, StockDocument.id == StockDocumentLine.document_id)
                     .where(StockDocumentLine.product_id == product_id,
                            StockDocument.status == CC.STATUS_POSTED)
                     .order_by(StockDocument.doc_date, StockDocument.id,
                               StockDocumentLine.id))
            rows: list[CardexRow] = []
            running = ZERO
            for line, doc in session.execute(query).all():
                is_target = (doc.kind == CC.MOVE_TRANSFER
                             and warehouse_id is not None
                             and doc.target_warehouse_id == warehouse_id)
                in_source = warehouse_id is None or doc.warehouse_id == warehouse_id
                if not (in_source or is_target):
                    continue
                if date_from and doc.doc_date < date_from:
                    # still affects the running balance, just not displayed
                    running += self._signed_qty(line, doc, is_target)
                    continue
                if date_to and doc.doc_date > date_to:
                    continue
                signed = self._signed_qty(line, doc, is_target)
                running += signed
                rows.append(CardexRow(
                    doc_date=doc.doc_date, number=doc.number,
                    kind_fa=CC.STOCK_MOVE_TITLES_FA.get(doc.kind, doc.kind),
                    warehouse_title=(doc.target_warehouse.title_fa if is_target
                                     else doc.warehouse.title_fa),
                    quantity_in=signed if signed > 0 else ZERO,
                    quantity_out=(-signed) if signed < 0 else ZERO,
                    balance=running, unit_cost=line.unit_cost, value=line.value,
                    note=line.note or doc.note or ""))
            return rows

    def valuation(self, ctx: SecurityContext | None, *,
                  warehouse_id: int | None = None) -> dict:
        require_permission(ctx, "commerce.reports")
        with self.db.session_scope() as session:
            query = select(func.sum(StockBalance.quantity), func.sum(StockBalance.value))
            if warehouse_id:
                query = query.where(StockBalance.warehouse_id == warehouse_id)
            quantity, value = session.execute(query).one()
            return {
                "quantity": Decimal(quantity or 0),
                "value": Decimal(value or 0),
                "warehouse_id": warehouse_id,
                "method": valuation_method(self.settings),
            }

    # --------------------------------------------------------- stock counts
    def create_count_sheet(self, ctx: SecurityContext | None, *, warehouse_id: int,
                           count_date: _dt.date | None = None, note: str = "",
                           product_ids: list[int] | None = None) -> int:
        require_permission(ctx, "stock.count")
        with self.db.session_scope() as session:
            warehouse = get_or_404(session, Warehouse, warehouse_id,
                                   "انبار مورد نظر یافت نشد.")
            sheet = StockCountSheet(
                number=next_document_number(session, StockCountSheet, prefix="CNT",
                                            on_date=count_date),
                count_date=count_date or _dt.date.today(),
                warehouse_id=warehouse.id, status="draft",
                note=clean_text(note, field="note", label="توضیحات", max_length=500),
                created_by_id=ctx.user_id if ctx else None,
            )
            session.add(sheet)
            session.flush()
            query = select(StockBalance).where(StockBalance.warehouse_id == warehouse.id)
            if product_ids:
                query = query.where(StockBalance.product_id.in_(product_ids))
            for balance in session.execute(query.order_by(StockBalance.product_id)).scalars():
                sheet.lines.append(StockCountLine(
                    product_id=balance.product_id,
                    system_quantity=balance.quantity,
                    counted_quantity=balance.quantity,
                    unit_cost=balance.average_cost,
                ))
            if not sheet.lines:
                raise ValidationError(
                    "برای این انبار هیچ موجودی‌ای ثبت نشده است؛ ابتدا اجناس را وارد انبار کنید.")
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="stock_count", entity_id=sheet.id, action="create",
                summary_fa=f"ایجاد برگهٔ انبارگردانی {sheet.number}",
                session=session)
            return sheet.id

    def count_sheet(self, ctx: SecurityContext | None, sheet_id: int) -> dict:
        require_permission(ctx, "stock.view")
        with self.db.session_scope() as session:
            sheet = get_or_404(session, StockCountSheet, sheet_id,
                               "برگهٔ انبارگردانی یافت نشد.")
            lines = []
            for line in sheet.lines:
                difference = line.counted_quantity - line.system_quantity
                lines.append({
                    "line_id": line.id,
                    "product_id": line.product_id,
                    "code": line.product.code,
                    "name": line.product.name_fa,
                    "system_quantity": line.system_quantity,
                    "counted_quantity": line.counted_quantity,
                    "difference": difference,
                    "unit_cost": line.unit_cost,
                    "difference_value": difference * line.unit_cost,
                    "note": line.note or "",
                })
            return {
                "id": sheet.id, "number": sheet.number, "count_date": sheet.count_date,
                "warehouse_title": sheet.warehouse.title_fa, "status": sheet.status,
                "status_fa": CC.COUNT_STATUS_TITLES_FA.get(sheet.status, sheet.status),
                "note": sheet.note or "", "stock_document_id": sheet.stock_document_id,
                "lines": lines,
            }

    def record_count(self, ctx: SecurityContext | None, sheet_id: int,
                     entries: list[CountLineInput]) -> dict:
        require_permission(ctx, "stock.count")
        with self.db.session_scope() as session:
            sheet = get_or_404(session, StockCountSheet, sheet_id,
                               "برگهٔ انبارگردانی یافت نشد.")
            if sheet.status not in ("draft", "counting"):
                raise ValidationError("این برگه در وضعیت شمارش نیست.")
            by_product = {line.product_id: line for line in sheet.lines}
            for entry in entries:
                line = by_product.get(entry.product_id)
                if line is None:
                    raise ValidationError(
                        "کالای وارد شده در این برگهٔ انبارگردانی وجود ندارد.")
                line.counted_quantity = to_quantity(entry.counted_quantity,
                                                    field="counted_quantity")
                line.note = clean_text(entry.note, field="note", label="توضیح",
                                       max_length=300)
                line.difference_value = ((line.counted_quantity - line.system_quantity)
                                         * line.unit_cost)
            sheet.status = "counting"
            session.flush()
            return self.count_sheet(ctx, sheet_id)

    def approve_count(self, ctx: SecurityContext | None, sheet_id: int,
                      reason: str = "") -> StockDocRow:
        """Approve a count sheet and post the resulting adjustment document."""
        require_permission(ctx, "stock.count_approve")
        with self.db.session_scope() as session:
            sheet = get_or_404(session, StockCountSheet, sheet_id,
                               "برگهٔ انبارگردانی یافت نشد.")
            if sheet.status == "approved":
                raise ValidationError("این برگه قبلاً تأیید شده است.")
            differences = [(line, line.counted_quantity - line.system_quantity)
                           for line in sheet.lines]
            changed = [(line, diff) for line, diff in differences if diff != 0]
            if changed:
                doc = StockDocument(
                    number=next_document_number(session, StockDocument, prefix="ADJ",
                                                on_date=sheet.count_date),
                    kind=CC.MOVE_ADJUSTMENT, doc_date=sheet.count_date,
                    warehouse_id=sheet.warehouse_id, status=CC.STATUS_DRAFT,
                    note=f"اصلاح مغایرت انبارگردانی {sheet.number}"
                         + (f" — {reason.strip()}" if reason.strip() else ""),
                    source_kind="stock_count", source_id=sheet.id,
                    created_by_id=ctx.user_id if ctx else None,
                )
                for line, diff in changed:
                    doc.lines.append(StockDocumentLine(
                        line_no=len(doc.lines) + 1, product_id=line.product_id,
                        quantity=abs(diff), direction="in" if diff > 0 else "out",
                        unit_id=line.product.unit_id, factor=Decimal("1"),
                        unit_cost=line.unit_cost, note=f"مغایرت انبارگردانی {sheet.number}",
                    ))
                session.add(doc)
                session.flush()
                self._post_in_session(session, doc, ctx, allow_negative=True)
                sheet.stock_document_id = doc.id
            sheet.status = "approved"
            sheet.approved_by_id = ctx.user_id if ctx else None
            sheet.approved_at = utcnow()
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="stock_count", entity_id=sheet.id, action="approve",
                summary_fa=f"تأیید انبارگردانی {sheet.number} "
                           f"({len(changed)} ردیف مغایرت)",
                after={"differences": len(changed),
                       "stock_document_id": sheet.stock_document_id}, session=session)
            self.audit.log_security(
                event_type=EventType.STOCK_COUNT_APPROVED,
                message_fa=f"انبارگردانی {sheet.number} تأیید شد.",
                ctx=ctx, details={"sheet_id": sheet.id, "differences": len(changed)},
                session=session)
            if sheet.stock_document_id:
                return self._doc_row(session, session.get(StockDocument,
                                                          sheet.stock_document_id))
            return StockDocRow(
                id=0, number="", kind=CC.MOVE_ADJUSTMENT,
                kind_fa=CC.STOCK_MOVE_TITLES_FA[CC.MOVE_ADJUSTMENT],
                doc_date=sheet.count_date, warehouse_title=sheet.warehouse.title_fa,
                target_title="", party_name="", status=CC.STATUS_POSTED,
                status_fa=CC.DOC_STATUS_TITLES_FA[CC.STATUS_POSTED],
                total_value=ZERO, note="بدون مغایرت", line_count=0, posted_at=None,
                created_by="")

    def count_sheets(self, ctx: SecurityContext | None, *,
                     warehouse_id: int | None = None,
                     status: str | None = None) -> list[dict]:
        require_permission(ctx, "stock.view")
        query = select(StockCountSheet).order_by(StockCountSheet.count_date.desc(),
                                                 StockCountSheet.id.desc()).limit(500)
        if warehouse_id:
            query = query.where(StockCountSheet.warehouse_id == warehouse_id)
        if status:
            query = query.where(StockCountSheet.status == status)
        with self.db.session_scope() as session:
            return [{
                "id": sheet.id, "number": sheet.number, "count_date": sheet.count_date,
                "warehouse": sheet.warehouse.title_fa, "status": sheet.status,
                "status_fa": CC.COUNT_STATUS_TITLES_FA.get(sheet.status, sheet.status),
                "lines": len(sheet.lines),
                "differences": sum(1 for line in sheet.lines
                                   if line.counted_quantity != line.system_quantity),
            } for sheet in session.execute(query).scalars()]

    # ------------------------------------------------------------- internals
    def _create_and_post(self, ctx: SecurityContext | None,
                         data: StockDocInput) -> StockDocRow:
        require_permission(ctx, self._permission_for(data.kind))
        with self.db.session_scope() as session:
            doc = self._prepare_document(session, data)
            session.add(doc)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("شمارهٔ سند انبار هم‌زمان ثبت شد؛ دوباره تلاش کنید.") from exc
            self._post_in_session(session, doc, ctx)
            return self._doc_row(session, doc)

    @staticmethod
    def _permission_for(kind: str) -> str:
        return {
            CC.MOVE_RECEIPT: "stock.receipt",
            CC.MOVE_ISSUE: "stock.issue",
            CC.MOVE_TRANSFER: "stock.transfer",
            CC.MOVE_ADJUSTMENT: "stock.adjust",
            CC.MOVE_COUNT: "stock.adjust",
        }.get(kind, "stock.adjust")

    def _prepare_document(self, session, data: StockDocInput, *,
                          existing: StockDocument | None = None) -> StockDocument:
        if data.kind not in CC.STOCK_MOVE_KINDS:
            raise ValidationError("نوع سند انبار معتبر نیست.", field="kind")
        warehouse = get_or_404(session, Warehouse, data.warehouse_id,
                               "انبار مبدأ یافت نشد.")
        if not warehouse.is_active:
            raise ValidationError("انبار مبدأ غیرفعال است.", field="warehouse_id")
        target = None
        if data.kind == CC.MOVE_TRANSFER:
            if not data.target_warehouse_id:
                raise ValidationError("برای انتقال، انبار مقصد را انتخاب کنید.",
                                      field="target_warehouse_id")
            target = get_or_404(session, Warehouse, data.target_warehouse_id,
                                "انبار مقصد یافت نشد.")
            if target.id == warehouse.id:
                raise ValidationError("انبار مبدأ و مقصد نباید یکی باشند.",
                                      field="target_warehouse_id")
            if not target.is_active:
                raise ValidationError("انبار مقصد غیرفعال است.", field="target_warehouse_id")
        elif data.target_warehouse_id:
            raise ValidationError("انبار مقصد فقط برای سند انتقال مجاز است.",
                                  field="target_warehouse_id")
        if not data.lines:
            raise ValidationError("سند انبار باید حداقل یک ردیف داشته باشد.")
        if data.doc_date is None:
            raise ValidationError("تاریخ سند را وارد کنید.", field="doc_date")

        doc = existing or StockDocument(
            number=next_document_number(session, StockDocument,
                                        prefix={CC.MOVE_RECEIPT: "RCP",
                                                CC.MOVE_ISSUE: "ISS",
                                                CC.MOVE_TRANSFER: "TRF",
                                                CC.MOVE_ADJUSTMENT: "ADJ",
                                                CC.MOVE_COUNT: "CNT"}.get(data.kind, "STK"),
                                        on_date=data.doc_date),
            created_by_id=None,
        )
        doc.kind = data.kind
        doc.doc_date = data.doc_date
        doc.warehouse_id = warehouse.id
        doc.target_warehouse_id = target.id if target else None
        doc.party_detail_id = data.party_detail_id
        doc.reference_no = clean_text(data.reference_no, field="reference_no",
                                      label="شمارهٔ مرجع", max_length=80) or None
        doc.note = clean_text(data.note, field="note", label="توضیحات", max_length=500)
        doc.status = CC.STATUS_DRAFT
        doc.source_kind = data.source_kind
        doc.source_id = data.source_id
        if data.idempotency_key:
            doc.idempotency_key = data.idempotency_key
        doc.lines.clear()
        for index, line in enumerate(data.lines, start=1):
            product = get_or_404(session, Product, line.product_id,
                                 f"ردیف {index}: کالا یافت نشد.")
            if product.kind == CC.PRODUCT_SERVICE:
                raise ValidationError(
                    f"ردیف {index}: «{product.name_fa}» یک خدمت است و سند انبار نمی‌گیرد.")
            if not product.is_active:
                raise ValidationError(
                    f"ردیف {index}: کالای «{product.name_fa}» غیرفعال است.")
            unit_id = line.unit_id or product.unit_id
            unit = get_or_404(session, Unit, unit_id, f"ردیف {index}: واحد یافت نشد.")
            base_unit = product.unit_id
            if unit.id != base_unit and (unit.base_unit_id != base_unit):
                raise ValidationError(
                    f"ردیف {index}: واحد «{unit.title_fa}» با واحد پایهٔ کالا سازگار نیست.",
                    field="unit_id")
            factor = unit.factor if unit.base_unit_id == base_unit else Decimal("1")
            quantity = to_quantity(line.quantity, field="quantity", allow_zero=False)
            direction = line.direction if data.kind in (CC.MOVE_ADJUSTMENT,) else "in"
            if direction not in ("in", "out"):
                raise ValidationError(f"ردیف {index}: جهت حرکت نامعتبر است.")
            cost = to_money(line.unit_cost, field="unit_cost")
            base_quantity = (quantity * factor).quantize(QTY)
            doc.lines.append(StockDocumentLine(
                line_no=index, product_id=product.id, quantity=quantity,
                direction=direction, unit_id=unit.id, factor=factor,
                unit_cost=cost, value=ZERO,
                note=clean_text(line.note, field="note", label="توضیح", max_length=300),
            ))
        session.flush()
        return doc

    def _post_in_session(self, session, doc: StockDocument, ctx: SecurityContext | None,
                         *, allow_negative: bool | None = None) -> None:
        require_status(doc, CC.STATUS_DRAFT, label="سند انبار")
        if not doc.lines:
            raise ValidationError("سند انبار بدون ردیف قابل ثبت نیست.")
        warehouse = session.get(Warehouse, doc.warehouse_id)
        target = (session.get(Warehouse, doc.target_warehouse_id)
                  if doc.target_warehouse_id else None)
        total_value = ZERO
        session.info["stock_document_id"] = doc.id
        for line in doc.lines:
            product = session.get(Product, line.product_id)
            base_quantity = (line.quantity * line.factor).quantize(QTY)
            if doc.kind == CC.MOVE_TRANSFER:
                cost_value, unit_cost = self._apply_move(
                    session, product, warehouse, base_quantity, "out",
                    unit_cost=None, ctx=ctx, allow_negative=allow_negative,
                    doc_date=doc.doc_date)
                self._apply_move(session, product, target, base_quantity, "in",
                                 unit_cost=unit_cost, ctx=ctx, allow_negative=True,
                                 doc_date=doc.doc_date)
                line.unit_cost = unit_cost
                line.value = cost_value
            elif doc.kind == CC.MOVE_RECEIPT:
                cost_value, unit_cost = self._apply_move(
                    session, product, warehouse, base_quantity, "in",
                    unit_cost=line.unit_cost or product.purchase_price, ctx=ctx,
                    allow_negative=True, doc_date=doc.doc_date)
                line.unit_cost = unit_cost
                line.value = cost_value
            elif doc.kind == CC.MOVE_ISSUE:
                cost_value, unit_cost = self._apply_move(
                    session, product, warehouse, base_quantity, "out",
                    unit_cost=None, ctx=ctx, allow_negative=allow_negative,
                    doc_date=doc.doc_date)
                line.unit_cost = unit_cost
                line.value = cost_value
            else:  # adjustment / count: direction is per line
                cost_value, unit_cost = self._apply_move(
                    session, product, warehouse, base_quantity, line.direction,
                    unit_cost=(line.unit_cost or None), ctx=ctx,
                    allow_negative=(allow_negative or line.direction == "in"),
                    doc_date=doc.doc_date)
                line.unit_cost = unit_cost
                line.value = cost_value
            balance = self._balance(session, product.id, warehouse.id)
            line.balance_after = balance.quantity
            total_value += line.value
        doc.total_value = total_value
        doc.status = CC.STATUS_POSTED
        doc.posted_at = utcnow()
        doc.posted_by_id = ctx.user_id if ctx else None
        doc.updated_by_id = ctx.user_id if ctx else None
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="stock_document", entity_id=doc.id, action="post",
            summary_fa=f"ثبت سند {doc.number} "
                       f"({CC.STOCK_MOVE_TITLES_FA.get(doc.kind, doc.kind)})",
            after=self._doc_snapshot(doc), session=session)
        self.audit.log_security(
            event_type=EventType.STOCK_POSTED,
            message_fa=f"سند انبار {doc.number} ثبت شد.",
            ctx=ctx, details={"document_id": doc.id, "number": doc.number,
                              "kind": doc.kind, "value": str(total_value)},
            session=session)

    def _apply_move(self, session, product: Product, warehouse: Warehouse,
                    quantity: Decimal, direction: str, *, unit_cost: Decimal | None,
                    ctx: SecurityContext | None, allow_negative: bool | None,
                    doc_date: _dt.date) -> tuple[Decimal, Decimal]:
        """Apply one movement; returns ``(total_value, unit_cost)``."""
        balance = self._balance(session, product.id, warehouse.id, create=True,
                                lock=True)
        method = valuation_method(self.settings, warehouse)
        if direction == "in":
            cost = to_money(unit_cost if unit_cost is not None else product.purchase_price,
                            field="unit_cost")
            value = (quantity * cost)
            balance.quantity = balance.quantity + quantity
            balance.value = balance.value + value
            session.add(StockLayer(
                product_id=product.id, warehouse_id=warehouse.id,
                document_id=session.info.get("stock_document_id"),
                received_on=doc_date, original_quantity=quantity,
                remaining_quantity=quantity, unit_cost=cost))
            return value, cost

        # outbound
        self._assert_available(session, product, warehouse, balance, quantity, ctx,
                               allow_negative)
        if method == CC.VALUATION_FIFO:
            cost_value, cost = self._consume_fifo(session, product, warehouse, quantity,
                                                  fallback=balance.average_cost)
        else:
            cost = balance.average_cost
            cost_value = (quantity * cost).quantize(Decimal("0.01"))
            if balance.quantity > 0 and cost_value > balance.value:
                cost_value = balance.value
        balance.quantity = balance.quantity - quantity
        balance.value = balance.value - cost_value
        if balance.quantity <= 0:
            balance.value = ZERO
        return cost_value, cost

    def _assert_available(self, session, product, warehouse, balance, quantity,
                          ctx, allow_negative: bool | None) -> None:
        if balance.quantity >= quantity:
            return
        policy_allows = (warehouse.allow_negative
                         or allow_negative_default(self.settings))
        if allow_negative:
            policy_allows = True
        permitted = bool(ctx and ctx.has("stock.negative_override"))
        if policy_allows and permitted:
            self.audit.log_security(
                event_type=EventType.NEGATIVE_STOCK_OVERRIDE,
                message_fa=(f"خروج بیش از موجودی برای «{product.name_fa}» در انبار "
                            f"«{warehouse.title_fa}» مجاز شد."),
                ctx=ctx, details={"product_id": product.id, "warehouse_id": warehouse.id,
                                  "on_hand": str(balance.quantity),
                                  "requested": str(quantity)}, session=session)
            return
        raise ValidationError(
            f"موجودی «{product.name_fa}» در انبار «{warehouse.title_fa}» کافی نیست "
            f"(موجودی: {balance.quantity}، درخواست: {quantity}). "
            "خروج بیش از موجودی به‌صورت پیش‌فرض ممنوع است.")

    def _consume_fifo(self, session, product, warehouse, quantity: Decimal,
                      *, fallback: Decimal) -> tuple[Decimal, Decimal]:
        layers = list(session.execute(
            select(StockLayer)
            .where(StockLayer.product_id == product.id,
                   StockLayer.warehouse_id == warehouse.id,
                   StockLayer.remaining_quantity > 0)
            .order_by(StockLayer.received_on, StockLayer.id)
            .with_for_update()).scalars())
        remaining = quantity
        total = ZERO
        last_cost = fallback
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer.remaining_quantity, remaining)
            total += take * layer.unit_cost
            layer.remaining_quantity = layer.remaining_quantity - take
            last_cost = layer.unit_cost
            remaining -= take
        if remaining > 0:  # negative stock allowed: cost the remainder at last known
            total += remaining * last_cost
        value = total.quantize(Decimal("0.01"))
        unit_cost = (value / quantity).quantize(Decimal("0.01")) if quantity else ZERO
        return value, unit_cost

    @staticmethod
    def _balance(session, product_id: int, warehouse_id: int, *,
                 create: bool = False, lock: bool = False) -> StockBalance:
        query = (select(StockBalance)
                 .where(StockBalance.product_id == product_id,
                        StockBalance.warehouse_id == warehouse_id))
        if lock:
            query = query.with_for_update()
        balance = session.execute(query).scalars().first()
        if balance is None:
            if not create:
                raise NotFoundError("موجودی این کالا در انبار یافت نشد.")
            balance = StockBalance(product_id=product_id, warehouse_id=warehouse_id,
                                   quantity=ZERO, value=ZERO)
            session.add(balance)
            session.flush()
        return balance

    @staticmethod
    def _signed_qty(line: StockDocumentLine, doc: StockDocument,
                    is_target: bool) -> Decimal:
        qty = line.quantity * line.factor
        if doc.kind == CC.MOVE_RECEIPT:
            return qty
        if doc.kind == CC.MOVE_ISSUE:
            return -qty
        if doc.kind == CC.MOVE_TRANSFER:
            return qty if is_target else -qty
        return qty if line.direction == "in" else -qty

    def _validated_warehouse(self, session, data: WarehouseInput, *,
                             warehouse_id: int | None = None) -> dict:
        if data.valuation_method is not None and data.valuation_method not in CC.VALUATION_METHODS:
            raise ValidationError("روش ارزش‌گذاری انبار معتبر نیست.",
                                  field="valuation_method")
        clash = session.execute(
            select(Warehouse).where(Warehouse.code == clean_code(
                data.code, label="کد انبار", max_length=24))).scalars().first()
        if clash is not None and clash.id != warehouse_id:
            raise ConflictError("انباری با این کد قبلاً ثبت شده است.")
        return {
            "code": clean_code(data.code, label="کد انبار", max_length=24),
            "title_fa": clean_text(data.title_fa, field="title_fa", label="نام انبار",
                                   required=True, max_length=120),
            "keeper": clean_text(data.keeper, field="keeper", label="انباردار",
                                 max_length=120),
            "address": clean_text(data.address, field="address", label="نشانی",
                                  max_length=300),
            "is_primary": bool(data.is_primary),
            "is_active": bool(data.is_active),
            "allow_negative": bool(data.allow_negative),
            "valuation_method": data.valuation_method,
            "description": clean_text(data.description, field="description",
                                      label="توضیحات", max_length=300),
        }

    @staticmethod
    def _clear_primary(session, keep: int | None = None) -> None:
        for other in session.execute(
                select(Warehouse).where(Warehouse.is_primary.is_(True))).scalars():
            if keep is None or other.id != keep:
                other.is_primary = False

    @staticmethod
    def _warehouse_row(warehouse: Warehouse, item_count: int,
                       total_value: Decimal) -> WarehouseRow:
        method = warehouse.valuation_method or CC.VALUATION_AVERAGE
        return WarehouseRow(
            id=warehouse.id, code=warehouse.code, title_fa=warehouse.title_fa,
            keeper=warehouse.keeper or "", address=warehouse.address or "",
            is_primary=warehouse.is_primary, is_active=warehouse.is_active,
            allow_negative=warehouse.allow_negative,
            valuation_method=method,
            valuation_fa=CC.VALUATION_TITLES_FA.get(method, method),
            item_count=item_count, total_value=total_value,
        )

    @staticmethod
    def _doc_snapshot(doc: StockDocument) -> dict:
        return {"number": doc.number, "kind": doc.kind, "status": doc.status,
                "doc_date": str(doc.doc_date), "warehouse_id": doc.warehouse_id,
                "target_warehouse_id": doc.target_warehouse_id,
                "total_value": str(doc.total_value), "lines": len(doc.lines)}

    @staticmethod
    def _warehouse_snapshot(warehouse: Warehouse) -> dict:
        return {"code": warehouse.code, "title_fa": warehouse.title_fa,
                "is_primary": warehouse.is_primary, "is_active": warehouse.is_active,
                "allow_negative": warehouse.allow_negative,
                "valuation_method": warehouse.valuation_method}

    def _doc_row(self, session, doc: StockDocument) -> StockDocRow:
        from pars_erp.db.models import DetailAccount

        party = (session.get(DetailAccount, doc.party_detail_id)
                 if doc.party_detail_id else None)
        return StockDocRow(
            id=doc.id, number=doc.number, kind=doc.kind,
            kind_fa=CC.STOCK_MOVE_TITLES_FA.get(doc.kind, doc.kind),
            doc_date=doc.doc_date,
            warehouse_title=(f"{doc.warehouse.title_fa}" if doc.warehouse else ""),
            target_title=(doc.target_warehouse.title_fa if doc.target_warehouse else ""),
            party_name=party.name if party else "",
            status=doc.status,
            status_fa=CC.DOC_STATUS_TITLES_FA.get(doc.status, doc.status),
            total_value=doc.total_value, note=doc.note or "",
            line_count=len(doc.lines), posted_at=doc.posted_at,
            created_by="",
        )

    @staticmethod
    def _line_row(line: StockDocumentLine) -> StockDocLineRow:
        return StockDocLineRow(
            line_no=line.line_no, product_id=line.product_id,
            product_code=line.product.code if line.product else "",
            product_name=line.product.name_fa if line.product else "",
            unit_title=(line.product.unit.title_fa if line.product and line.product.unit
                        else ""),
            factor=line.factor, quantity=line.quantity,
            base_quantity=line.quantity * line.factor,
            direction=line.direction, unit_cost=line.unit_cost, value=line.value,
            balance_after=line.balance_after, note=line.note or "",
        )

    @staticmethod
    def _balance_row(balance: StockBalance, product: Product, warehouse: Warehouse,
                     categories: dict[int, str]) -> BalanceRow:
        quantity = balance.quantity
        return BalanceRow(
            product_id=product.id, code=product.code, name_fa=product.name_fa,
            category_title=categories.get(product.category_id, ""),
            unit_title=product.unit.title_fa if product.unit else "",
            warehouse_id=warehouse.id, warehouse_title=warehouse.title_fa,
            quantity=quantity, value=balance.value, average_cost=balance.average_cost,
            reorder_point=product.reorder_point,
            quantity_fa=f"{quantity:,}", value_fa=f"{balance.value:,}",
        )
