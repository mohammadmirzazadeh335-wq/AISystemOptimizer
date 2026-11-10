"""Purchase requests/orders and sales orders with an explicit status history.

The flow is deliberately simple and auditable:

* purchase: ``draft → submitted → pending_approval → approved → in_progress →
  completed`` (or ``cancelled`` at any open step),
* sales: the same chain, where ``in_progress`` means "goods being prepared".

Every transition is written to ``com_order_status_history`` with the acting user
and the timestamp, and each transition checks the permission that belongs to it
(submit vs. approve vs. cancel), so the workflow cannot be bypassed from the UI.
Orders never move stock or write to the ledger - that only happens when the
invoice is posted, which keeps a single source of truth for stock and money.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import DetailAccount, OrderDocument, OrderLine, Product
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_any, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import (
    ZERO,
    clean_text,
    get_or_404,
    next_document_number,
    to_money,
    to_quantity,
)

#: Which permission each target status needs, per order family.
TRANSITION_PERMISSIONS: dict[str, dict[str, str]] = {
    CC.ORDER_PURCHASE_REQUEST: {
        CC.ORDER_STATUS_SUBMITTED: "purchase.order",
        CC.ORDER_STATUS_PENDING_APPROVAL: "purchase.order",
        CC.ORDER_STATUS_APPROVED: "purchase.approve",
        CC.ORDER_STATUS_IN_PROGRESS: "purchase.order",
        CC.ORDER_STATUS_COMPLETED: "purchase.order",
        CC.ORDER_STATUS_CANCELLED: "purchase.order",
    },
    CC.ORDER_PURCHASE: {
        CC.ORDER_STATUS_SUBMITTED: "purchase.order",
        CC.ORDER_STATUS_PENDING_APPROVAL: "purchase.order",
        CC.ORDER_STATUS_APPROVED: "purchase.approve",
        CC.ORDER_STATUS_IN_PROGRESS: "purchase.order",
        CC.ORDER_STATUS_COMPLETED: "purchase.order",
        CC.ORDER_STATUS_CANCELLED: "purchase.order",
    },
    CC.ORDER_SALES: {
        CC.ORDER_STATUS_SUBMITTED: "sales.order",
        CC.ORDER_STATUS_PENDING_APPROVAL: "sales.order",
        CC.ORDER_STATUS_APPROVED: "sales.approve",
        CC.ORDER_STATUS_IN_PROGRESS: "sales.order",
        CC.ORDER_STATUS_COMPLETED: "sales.order",
        CC.ORDER_STATUS_CANCELLED: "sales.order",
    },
}


@dataclass(frozen=True)
class OrderLineInput:
    product_id: int
    quantity: Decimal | str | int
    unit_price: Decimal | str | int | None = None
    note: str = ""


@dataclass(frozen=True)
class OrderInput:
    kind: str
    doc_date: _dt.date
    party_detail_id: int | None
    warehouse_id: int | None
    lines: tuple[OrderLineInput, ...]
    notes: str = ""


@dataclass(frozen=True)
class OrderLineRow:
    line_no: int
    product_id: int
    product_code: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    note: str


@dataclass(frozen=True)
class OrderHistoryRow:
    from_status: str
    from_status_fa: str
    to_status: str
    to_status_fa: str
    changed_at: _dt.datetime
    changed_by: str
    note: str


@dataclass(frozen=True)
class OrderRow:
    id: int
    number: str
    kind: str
    kind_fa: str
    doc_date: _dt.date
    party_name: str
    warehouse_title: str
    status: str
    status_fa: str
    total: Decimal
    notes: str
    lines: tuple[OrderLineRow, ...]
    history: tuple[OrderHistoryRow, ...]

    @property
    def display(self) -> str:
        return f"{self.number} — {self.kind_fa}"

    @property
    def can_be_invoiced(self) -> bool:
        return self.status in (CC.ORDER_STATUS_APPROVED, CC.ORDER_STATUS_IN_PROGRESS)


class OrderService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ---------------------------------------------------------------- create
    def create(self, ctx: SecurityContext | None, data: OrderInput) -> OrderRow:
        require_permission(ctx, self._create_permission(data.kind))
        if data.kind not in CC.ORDER_KINDS:
            raise ValidationError("نوع سفارش معتبر نیست.", field="kind")
        if not data.lines:
            raise ValidationError("سفارش باید حداقل یک ردیف داشته باشد.")
        with self.db.session_scope() as session:
            party = (get_or_404(session, DetailAccount, data.party_detail_id,
                                "شخص مورد نظر یافت نشد.")
                     if data.party_detail_id else None)
            order = OrderDocument(
                number=next_document_number(session, OrderDocument,
                                            prefix=CC.ORDER_PREFIX[data.kind],
                                            on_date=data.doc_date),
                kind=data.kind, doc_date=data.doc_date,
                party_detail_id=party.id if party else None,
                warehouse_id=data.warehouse_id,
                status=CC.ORDER_STATUS_DRAFT,
                notes=clean_text(data.notes, field="notes", label="توضیحات",
                                 max_length=1000),
                created_by_id=ctx.user_id if ctx else None,
            )
            for index, line in enumerate(data.lines, start=1):
                product = get_or_404(session, Product, line.product_id,
                                     f"ردیف {index}: کالا یافت نشد.")
                quantity = to_quantity(line.quantity, field="quantity", allow_zero=False)
                price = line.unit_price
                if price in (None, ""):
                    price = (product.purchase_price
                             if data.kind != CC.ORDER_SALES else product.sale_price)
                order.lines.append(OrderLine(
                    line_no=index, product_id=product.id, quantity=quantity,
                    unit_price=to_money(price, field="unit_price"),
                    note=clean_text(line.note, field="note", label="توضیح",
                                    max_length=300),
                ))
            order.history.append(_history(None, CC.ORDER_STATUS_DRAFT, ctx,
                                          "ایجاد سند"))
            session.add(order)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("شمارهٔ سفارش هم‌زمان ثبت شد؛ دوباره تلاش کنید.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="order", entity_id=order.id, action="create",
                summary_fa=f"ایجاد {CC.ORDER_TITLES_FA[data.kind]} {order.number}",
                after={"number": order.number, "lines": len(order.lines)},
                session=session)
            return self._row(session, order)

    # ------------------------------------------------------------- lifecycle
    def transition(self, ctx: SecurityContext | None, order_id: int, target: str,
                   note: str = "") -> OrderRow:
        if target not in CC.ORDER_STATUSES:
            raise ValidationError("وضعیت مقصد معتبر نیست.", field="target")
        with self.db.session_scope() as session:
            order = get_or_404(session, OrderDocument, order_id,
                               "سفارش مورد نظر یافت نشد.")
            permission = TRANSITION_PERMISSIONS.get(order.kind, {}).get(target)
            if permission is None:
                raise ValidationError("تغییر این وضعیت برای این سند مجاز نیست.")
            require_permission(ctx, permission)
            allowed = CC.ORDER_ALLOWED_TRANSITIONS.get(order.status, ())
            if target not in allowed:
                raise ValidationError(
                    f"تغییر وضعیت از «{CC.ORDER_STATUS_TITLES_FA[order.status]}» به "
                    f"«{CC.ORDER_STATUS_TITLES_FA[target]}» مجاز نیست.")
            previous = order.status
            order.status = target
            order.updated_by_id = ctx.user_id if ctx else None
            order.history.append(_history(previous, target, ctx, note))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="order", entity_id=order.id, action="status",
                summary_fa=(f"{CC.ORDER_TITLES_FA[order.kind]} {order.number}: "
                            f"{CC.ORDER_STATUS_TITLES_FA[previous]} ← "
                            f"{CC.ORDER_STATUS_TITLES_FA[target]}"),
                after={"status": target, "note": note}, session=session)
            return self._row(session, order)

    # ---------------------------------------------------------------- query
    def get(self, ctx: SecurityContext | None, order_id: int) -> OrderRow:
        require_any(ctx, "purchase.order", "sales.order", "commerce.reports")
        with self.db.session_scope() as session:
            order = get_or_404(session, OrderDocument, order_id,
                               "سفارش مورد نظر یافت نشد.")
            return self._row(session, order)

    def list(self, ctx: SecurityContext | None, *, kind: str | None = None,
             status: str | None = None, search: str = "") -> list[OrderRow]:
        require_any(ctx, "purchase.order", "sales.order", "commerce.reports")
        query = select(OrderDocument).order_by(OrderDocument.doc_date.desc(),
                                               OrderDocument.id.desc()).limit(500)
        if kind:
            query = query.where(OrderDocument.kind == kind)
        if status:
            query = query.where(OrderDocument.status == status)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(OrderDocument.number.like(needle))
        with self.db.session_scope() as session:
            return [self._row(session, order) for order in
                    session.execute(query).scalars()]

    def invoice_prefill(self, ctx: SecurityContext | None, order_id: int) -> dict:
        """Data the invoice form needs to start from an approved order."""
        require_any(ctx, "purchase.order", "sales.order")
        with self.db.session_scope() as session:
            order = get_or_404(session, OrderDocument, order_id,
                               "سفارش مورد نظر یافت نشد.")
            if not order.status in (CC.ORDER_STATUS_APPROVED,
                                    CC.ORDER_STATUS_IN_PROGRESS):
                raise ValidationError(
                    "فقط سفارش تأییدشده یا در حال انجام قابل تبدیل به فاکتور است.")
            return {
                "kind": (CC.INVOICE_PURCHASE if order.kind != CC.ORDER_SALES
                         else CC.INVOICE_SALE),
                "party_detail_id": order.party_detail_id,
                "warehouse_id": order.warehouse_id,
                "reference_no": order.number,
                "lines": [{"product_id": line.product_id,
                           "quantity": line.quantity,
                           "unit_price": line.unit_price,
                           "description": line.note or ""}
                          for line in order.lines],
            }

    # ------------------------------------------------------------- internals
    @staticmethod
    def _create_permission(kind: str) -> str:
        return "sales.order" if kind == CC.ORDER_SALES else "purchase.order"

    @staticmethod
    def _row(session, order: OrderDocument) -> OrderRow:
        party = (session.get(DetailAccount, order.party_detail_id)
                 if order.party_detail_id else None)
        lines = tuple(OrderLineRow(
            line_no=line.line_no, product_id=line.product_id,
            product_code=line.product.code if line.product else "",
            product_name=line.product.name_fa if line.product else "",
            quantity=line.quantity, unit_price=line.unit_price,
            total=(line.quantity * line.unit_price).quantize(Decimal("0.01")),
            note=line.note or "") for line in order.lines)
        history = tuple(OrderHistoryRow(
            from_status=item.from_status or "",
            from_status_fa=CC.ORDER_STATUS_TITLES_FA.get(item.from_status or "", "—"),
            to_status=item.to_status,
            to_status_fa=CC.ORDER_STATUS_TITLES_FA.get(item.to_status, item.to_status),
            changed_at=item.changed_at, changed_by=str(item.changed_by_id or ""),
            note=item.note or "") for item in
            sorted(order.history, key=lambda h: (h.changed_at, h.id)))
        return OrderRow(
            id=order.id, number=order.number, kind=order.kind,
            kind_fa=CC.ORDER_TITLES_FA.get(order.kind, order.kind),
            doc_date=order.doc_date, party_name=party.name if party else "",
            warehouse_title=order.warehouse.title_fa if order.warehouse else "",
            status=order.status,
            status_fa=CC.ORDER_STATUS_TITLES_FA.get(order.status, order.status),
            total=sum((line.total for line in lines), ZERO), notes=order.notes or "",
            lines=lines, history=history,
        )


def _history(previous: str | None, current: str, ctx: SecurityContext | None,
             note: str):
    from pars_erp.db.models import OrderStatusHistory

    return OrderStatusHistory(
        from_status=previous, to_status=current, changed_at=utcnow(),
        changed_by_id=ctx.user_id if ctx else None,
        note=clean_text(note, field="note", label="توضیح", max_length=300),
    )
