"""Purchase and sale invoices, returns, and their stock + ledger effects.

The lifecycle is draft → (approved) → posted, and posting is **one**
transaction that:

1. creates and posts a linked :class:`StockDocument` (receipt for purchases and
   sale returns, issue for sales and purchase returns),
2. builds the accounting entry from the configurable posting pattern,
3. writes the journal *and* stores ``stock_document_id`` / ``journal_id`` on
   the invoice.

Because those links and the ``idempotency_key`` unique constraints live in the
database, a crash between the steps rolls everything back, and a retry can never
apply stock or ledger effects twice. Corrections are only possible through the
authorised reversal path (:meth:`InvoiceService.void`), which posts the mirror
image instead of editing history.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as AC
from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    DetailAccount,
    JournalLine,
    Invoice,
    InvoiceLine,
    Journal,
    Product,
    StockDocument,
    Unit,
    Warehouse,
)
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import (
    SecurityContext,
    require_any,
    require_permission,
)
from pars_erp.services.audit_service import AuditService, EventType
from pars_erp.services.commerce_common import (
    ZERO,
    assert_transition,
    clean_text,
    get_or_404,
    next_document_number,
    require_status,
    to_money,
    to_percent,
    to_quantity,
)
from pars_erp.services.inventory_service import (
    InventoryService,
    StockDocInput,
    StockLineInput,
)

MONEY = Decimal("0.01")


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class InvoiceLineInput:
    product_id: int
    quantity: Decimal | str | int
    unit_price: Decimal | str | int | None = None
    unit_id: int | None = None
    discount: Decimal | str | int = 0
    tax_rate_id: int | None = None
    tax_percent: Decimal | str | int | None = None
    description: str = ""


@dataclass(frozen=True)
class InvoiceInput:
    kind: str
    invoice_date: _dt.date
    party_detail_id: int
    warehouse_id: int | None
    lines: tuple[InvoiceLineInput, ...]
    invoice_discount: Decimal | str | int = 0
    charges: Decimal | str | int = 0
    reference_no: str = ""
    notes: str = ""
    currency_code: str = "IRR"
    exchange_rate: Decimal | str | int = 1
    source_invoice_id: int | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class InvoiceLineRow:
    id: int
    line_no: int
    product_id: int
    product_code: str
    product_name: str
    unit_title: str
    quantity: Decimal
    unit_price: Decimal
    gross: Decimal
    discount: Decimal
    tax_percent: Decimal
    tax_amount: Decimal
    line_total: Decimal
    cost_amount: Decimal
    description: str

    @property
    def net_amount(self) -> Decimal:
        return self.gross - self.discount


@dataclass(frozen=True)
class InvoiceRow:
    id: int
    number: str
    kind: str
    kind_fa: str
    invoice_date: _dt.date
    party_id: int
    party_name: str
    warehouse_id: int | None
    warehouse_title: str
    status: str
    status_fa: str
    subtotal: Decimal
    line_discount: Decimal
    invoice_discount: Decimal
    tax_total: Decimal
    charge_total: Decimal
    net_total: Decimal
    cogs_total: Decimal
    reference_no: str
    notes: str
    source_invoice_id: int | None
    source_number: str
    stock_document_id: int | None
    journal_id: int | None
    posted_at: _dt.datetime | None
    lines: tuple[InvoiceLineRow, ...]

    @property
    def display(self) -> str:
        return f"{self.number} — {self.kind_fa}"

    @property
    def is_return(self) -> bool:
        return CC.invoice_is_return(self.kind)

    @property
    def is_posted(self) -> bool:
        return self.status == CC.STATUS_POSTED

    @property
    def is_editable(self) -> bool:
        return self.status in CC.EDITABLE_STATUSES

    @property
    def total_discount(self) -> Decimal:
        return self.line_discount + self.invoice_discount


@dataclass(frozen=True)
class InvoiceFilter:
    kind: str | None = None
    party_detail_id: int | None = None
    warehouse_id: int | None = None
    status: str | None = None
    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    search: str = ""
    only_returns: bool = False


@dataclass(frozen=True)
class PostingResult:
    invoice: InvoiceRow
    journal_id: int | None
    stock_document_id: int | None


class InvoiceService:
    def __init__(self, db: Database, audit: AuditService, *, inventory: InventoryService,
                 journals, settings, pricing) -> None:
        self.db = db
        self.audit = audit
        self.inventory = inventory
        self.journals = journals
        self.settings = settings
        self.pricing = pricing

    # ---------------------------------------------------------------- create
    def create(self, ctx: SecurityContext | None, data: InvoiceInput) -> InvoiceRow:
        require_permission(ctx, self._create_permission(data.kind))
        with self.db.session_scope() as session:
            invoice = self._prepare(session, data, ctx=ctx)
            session.add(invoice)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "شمارهٔ فاکتور هم‌زمان ثبت شد؛ دوباره تلاش کنید.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="invoice", entity_id=invoice.id, action="create",
                summary_fa=f"ایجاد {CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}",
                after=self._snapshot(invoice), session=session)
            return self._row(session, invoice)

    def update(self, ctx: SecurityContext | None, invoice_id: int,
               data: InvoiceInput) -> InvoiceRow:
        require_permission(ctx, self._create_permission(data.kind))
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            if invoice.status == CC.STATUS_POSTED:
                raise ValidationError(
                    "فاکتور ثبت‌شده قابل ویرایش نیست؛ برای اصلاح، فاکتور برگشت ثبت کنید.")
            if invoice.kind != data.kind:
                raise ValidationError("نوع فاکتور قابل تغییر نیست.", field="kind")
            before = self._snapshot(invoice)
            self._prepare(session, data, existing=invoice, ctx=ctx)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="invoice", entity_id=invoice.id, action="update",
                summary_fa=f"ویرایش فاکتور {invoice.number}", before=before,
                after=self._snapshot(invoice), session=session)
            return self._row(session, invoice)

    def delete(self, ctx: SecurityContext | None, invoice_id: int) -> None:
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            require_permission(ctx, self._create_permission(invoice.kind))
            if invoice.status != CC.STATUS_DRAFT:
                raise ValidationError("فقط پیش‌نویس فاکتور قابل حذف است.")
            session.delete(invoice)
            self.audit.log_audit(
                ctx=ctx, entity_type="invoice", entity_id=invoice_id, action="delete",
                summary_fa=f"حذف پیش‌نویس فاکتور {invoice.number}", session=session)

    # ------------------------------------------------------------- lifecycle
    def approve(self, ctx: SecurityContext | None, invoice_id: int) -> InvoiceRow:
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            require_permission(ctx, self._approve_permission(invoice.kind))
            assert_transition(invoice.status, CC.STATUS_APPROVED)
            invoice.status = CC.STATUS_APPROVED
            invoice.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="invoice", entity_id=invoice.id,
                action="approve", summary_fa=f"تأیید فاکتور {invoice.number}",
                session=session)
            return self._row(session, invoice)

    def post(self, ctx: SecurityContext | None, invoice_id: int) -> PostingResult:
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            require_permission(ctx, self._post_permission(invoice.kind))
            if invoice.journal_id or invoice.stock_document_id:
                raise ValidationError(
                    "این فاکتور قبلاً آثار انبار/حسابداری را ایجاد کرده است؛ "
                    "ثبت دوبارهٔ آن مجاز نیست.")
            assert_transition(invoice.status, CC.STATUS_POSTED)
            result = self._post_in_session(session, invoice, ctx)
            return result

    def void(self, ctx: SecurityContext | None, invoice_id: int, reason: str) -> InvoiceRow:
        """Authorised reversal: post the mirror stock document and journal entry."""
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValidationError("برای ابطال فاکتور، دلیل را بنویسید (حداقل ۵ نویسه).",
                                  field="void_reason")
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            require_permission(ctx, self._post_permission(invoice.kind))
            if invoice.status != CC.STATUS_POSTED:
                raise ValidationError("فقط فاکتور ثبت‌شده قابل ابطال است.")
            if invoice.stock_document_id:
                self.inventory.reverse_document_in_session(
                    session, invoice.stock_document_id, ctx,
                    f"ابطال فاکتور {invoice.number}: {reason}")
            if invoice.journal_id:
                self._reverse_journal(session, invoice, ctx, reason)
            invoice.status = CC.STATUS_VOID
            invoice.void_reason = reason
            invoice.updated_by_id = ctx.user_id if ctx else None
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="invoice", entity_id=invoice.id, action="void",
                summary_fa=f"ابطال فاکتور {invoice.number}: {reason}", session=session)
            self.audit.log_security(
                event_type=EventType.INVOICE_VOIDED,
                message_fa=f"فاکتور {invoice.number} باطل شد.",
                ctx=ctx, details={"invoice_id": invoice.id, "reason": reason},
                session=session)
            return self._row(session, invoice)

    # ---------------------------------------------------------------- queries
    def get(self, ctx: SecurityContext | None, invoice_id: int) -> InvoiceRow:
        require_any(ctx, "purchase.reports", "sales.reports", "commerce.reports",
                    "stock.view")
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            return self._row(session, invoice)

    def list(self, ctx: SecurityContext | None,
             filters: InvoiceFilter | None = None) -> list[InvoiceRow]:
        require_any(ctx, "purchase.reports", "sales.reports", "commerce.reports",
                    "stock.view")
        filters = filters or InvoiceFilter()
        query = select(Invoice).order_by(Invoice.invoice_date.desc(),
                                        Invoice.id.desc()).limit(1000)
        if filters.kind:
            query = query.where(Invoice.kind == filters.kind)
        elif filters.only_returns:
            query = query.where(Invoice.kind.in_((CC.INVOICE_PURCHASE_RETURN,
                                                  CC.INVOICE_SALE_RETURN)))
        if filters.party_detail_id:
            query = query.where(Invoice.party_detail_id == filters.party_detail_id)
        if filters.warehouse_id:
            query = query.where(Invoice.warehouse_id == filters.warehouse_id)
        if filters.status:
            query = query.where(Invoice.status == filters.status)
        if filters.date_from:
            query = query.where(Invoice.invoice_date >= filters.date_from)
        if filters.date_to:
            query = query.where(Invoice.invoice_date <= filters.date_to)
        if filters.search:
            needle = f"%{filters.search.strip()}%"
            query = query.where(or_(Invoice.number.like(needle),
                                    Invoice.reference_no.like(needle),
                                    Invoice.notes.like(needle)))
        with self.db.session_scope() as session:
            return [self._row(session, invoice) for invoice in
                    session.execute(query).scalars()]

    def next_number_preview(self, ctx: SecurityContext | None, kind: str) -> str:
        require_any(ctx, "purchase.reports", "sales.reports", "commerce.reports")
        if kind not in CC.INVOICE_PREFIX:
            raise ValidationError("نوع فاکتور معتبر نیست.", field="kind")
        with self.db.session_scope() as session:
            return next_document_number(session, Invoice, prefix=CC.INVOICE_PREFIX[kind],
                                        on_date=_dt.date.today())

    def returnable_lines(self, ctx: SecurityContext | None, invoice_id: int) -> list[dict]:
        """Quantities of an invoice that can still be returned."""
        require_any(ctx, "purchase.reports", "sales.reports", "commerce.reports")
        with self.db.session_scope() as session:
            invoice = get_or_404(session, Invoice, invoice_id, "فاکتور مورد نظر یافت نشد.")
            if invoice.kind not in (CC.INVOICE_PURCHASE, CC.INVOICE_SALE):
                raise ValidationError("برای این سند امکان ثبت برگشت وجود ندارد.")
            returned: dict[int, Decimal] = {}
            for ret in session.execute(
                    select(Invoice).where(Invoice.source_invoice_id == invoice.id,
                                          Invoice.status != CC.STATUS_VOID)).scalars():
                for line in ret.lines:
                    returned[line.product_id] = (returned.get(line.product_id, ZERO)
                                                 + line.quantity)
            return [{
                "product_id": line.product_id,
                "product_name": (line.product.name_fa if line.product else ""),
                "quantity": line.quantity,
                "returned": returned.get(line.product_id, ZERO),
                "remaining": max(ZERO, line.quantity - returned.get(line.product_id, ZERO)),
                "unit_price": line.unit_price,
                "tax_percent": line.tax_percent,
                "cost_amount": line.cost_amount,
            } for line in invoice.lines]

    # ------------------------------------------------------------- internals
    def _prepare(self, session, data: InvoiceInput, *,
                 existing: Invoice | None = None,
                 ctx: SecurityContext | None = None) -> Invoice:
        if data.kind not in CC.INVOICE_KINDS:
            raise ValidationError("نوع فاکتور معتبر نیست.", field="kind")
        if not data.lines:
            raise ValidationError("فاکتور باید حداقل یک ردیف داشته باشد.")
        party = get_or_404(session, DetailAccount, data.party_detail_id,
                           "مشتری/تأمین‌کننده یافت نشد.")
        if not party.is_active:
            raise ValidationError("شخص انتخاب‌شده غیرفعال است.", field="party_detail_id")
        is_purchase = data.kind in (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN)
        if is_purchase and party.is_supplier is False and party.is_customer:
            raise ValidationError(
                "این شخص به‌عنوان تأمین‌کننده ثبت نشده است.", field="party_detail_id")
        if not is_purchase and party.is_customer is False and party.is_supplier:
            raise ValidationError(
                "این شخص به‌عنوان مشتری ثبت نشده است.", field="party_detail_id")
        warehouse = None
        if data.warehouse_id:
            warehouse = get_or_404(session, Warehouse, data.warehouse_id,
                                   "انبار مورد نظر یافت نشد.")
            if not warehouse.is_active:
                raise ValidationError("انبار انتخاب‌شده غیرفعال است.", field="warehouse_id")

        source = None
        if CC.invoice_is_return(data.kind):
            if not data.source_invoice_id:
                raise ValidationError(
                    "برای ثبت برگشت، فاکتور مرجع را انتخاب کنید.", field="source_invoice_id")
            source = get_or_404(session, Invoice, data.source_invoice_id,
                                "فاکتور مرجع یافت نشد.")
            expected = (CC.INVOICE_PURCHASE if data.kind == CC.INVOICE_PURCHASE_RETURN
                        else CC.INVOICE_SALE)
            if source.kind != expected:
                raise ValidationError("فاکتور مرجع با نوع برگشت هم‌خوانی ندارد.",
                                      field="source_invoice_id")
            if source.status != CC.STATUS_POSTED:
                raise ValidationError("فقط فاکتور ثبت‌شده قابل برگشت است.",
                                      field="source_invoice_id")
        elif data.source_invoice_id:
            raise ValidationError("فاکتور مرجع فقط برای اسناد برگشت مجاز است.",
                                  field="source_invoice_id")

        invoice = existing or Invoice(
            number=next_document_number(session, Invoice,
                                        prefix=CC.INVOICE_PREFIX[data.kind],
                                        on_date=data.invoice_date),
            created_by_id=None,
        )
        invoice.kind = data.kind
        invoice.invoice_date = data.invoice_date
        invoice.party_detail_id = party.id
        invoice.warehouse_id = warehouse.id if warehouse else None
        invoice.reference_no = clean_text(data.reference_no, field="reference_no",
                                          label="شمارهٔ مرجع", max_length=80) or None
        invoice.notes = clean_text(data.notes, field="notes", label="توضیحات",
                                   max_length=1000)
        invoice.currency_code = (data.currency_code or "IRR").strip().upper()[:8]
        rate = to_quantity(data.exchange_rate, field="exchange_rate", allow_zero=False)
        invoice.exchange_rate = rate
        invoice.source_invoice_id = source.id if source else None
        invoice.status = CC.STATUS_DRAFT
        if data.idempotency_key:
            invoice.idempotency_key = data.idempotency_key
        invoice.lines.clear()

        prepared: list[dict] = []
        for index, line in enumerate(data.lines, start=1):
            product = get_or_404(session, Product, line.product_id,
                                 f"ردیف {index}: کالا یافت نشد.")
            if not product.is_active:
                raise ValidationError(f"ردیف {index}: کالای «{product.name_fa}» غیرفعال است.")
            unit_id = line.unit_id or product.unit_id
            unit = get_or_404(session, Unit, unit_id, f"ردیف {index}: واحد یافت نشد.")
            if unit.id != product.unit_id and unit.base_unit_id != product.unit_id:
                raise ValidationError(
                    f"ردیف {index}: واحد «{unit.title_fa}» با واحد پایهٔ کالا سازگار نیست.",
                    field="unit_id")
            factor = unit.factor if unit.base_unit_id == product.unit_id else Decimal("1")
            quantity = to_quantity(line.quantity, field="quantity", allow_zero=False)
            price = line.unit_price
            if price in (None, ""):
                resolved = self.pricing.resolve_price(
                    ctx=ctx, product_id=product.id, party_detail_id=party.id,
                    on_date=data.invoice_date,
                    kind=(CC.INVOICE_PURCHASE if is_purchase else CC.INVOICE_SALE))
                price = resolved.price
            unit_price = to_money(price, field="unit_price")
            gross = (quantity * unit_price).quantize(MONEY)
            discount = to_money(line.discount, field="discount")
            if discount > gross:
                raise ValidationError(
                    f"ردیف {index}: تخفیف نمی‌تواند بیش از مبلغ ردیف باشد.", field="discount")
            percent = line.tax_percent
            if percent in (None, ""):
                percent = (self.pricing.resolve_tax_percent(
                    ctx=ctx, rate_id=line.tax_rate_id, on_date=data.invoice_date,
                    kind=("purchase" if is_purchase else "sale"))
                    if line.tax_rate_id else ZERO)
            tax_percent = to_percent(percent, field="tax_percent")
            prepared.append({
                "line_no": index, "product": product, "unit": unit, "quantity": quantity,
                "unit_price": unit_price, "gross": gross, "discount": discount,
                "tax_percent": tax_percent, "factor": factor,
                "description": clean_text(line.description, field="description",
                                          label="شرح ردیف", max_length=300),
            })
        totals = self._allocate(prepared, to_money(data.invoice_discount,
                                                   field="invoice_discount"),
                                to_money(data.charges, field="charges"))
        for entry in prepared:
            invoice.lines.append(InvoiceLine(
                line_no=entry["line_no"], product_id=entry["product"].id,
                description=entry["description"] or entry["product"].name_fa,
                quantity=entry["quantity"], unit_id=entry["unit"].id,
                factor=entry["factor"], unit_price=entry["unit_price"],
                discount=entry["discount"], tax_percent=entry["tax_percent"],
                tax_amount=entry["tax_amount"], line_total=entry["line_total"],
                cost_amount=ZERO,
            ))
        invoice.subtotal = totals["subtotal"]
        invoice.line_discount = totals["line_discount"]
        invoice.invoice_discount = totals["invoice_discount"]
        invoice.tax_total = totals["tax_total"]
        invoice.charge_total = totals["charge_total"]
        invoice.net_total = totals["net_total"]
        if existing is None:
            invoice.cogs_total = ZERO

        # stock feasibility is checked here for drafts too: failing early is kinder
        if data.kind in (CC.INVOICE_SALE, CC.INVOICE_PURCHASE_RETURN):
            self._assert_stock_available(session, invoice, warehouse, ctx)
        if data.kind == CC.INVOICE_SALE:
            self._assert_credit_limit(session, invoice, party, ctx)
        if source is not None:
            self._assert_return_quantities(session, invoice, source)
        session.flush()
        return invoice

    @staticmethod
    def _allocate(lines: list[dict], invoice_discount: Decimal,
                  charges: Decimal) -> dict[str, Decimal]:
        subtotal = sum((entry["gross"] for entry in lines), ZERO)
        line_discount = sum((entry["discount"] for entry in lines), ZERO)
        base_total = subtotal - line_discount
        if invoice_discount > base_total:
            raise ValidationError(
                "تخفیف کل فاکتور نمی‌تواند بیش از جمع خالص ردیف‌ها باشد.",
                field="invoice_discount")
        # distribute the invoice-level discount proportionally over the lines,
        # so tax is computed on the real taxable amount and the sum matches exactly
        allocated = ZERO
        for index, entry in enumerate(lines):
            if index == len(lines) - 1:
                share = invoice_discount - allocated
            elif base_total > 0:
                share = (invoice_discount * (entry["gross"] - entry["discount"])
                         / base_total).quantize(MONEY)
            else:
                share = ZERO
            allocated += share
            taxable = entry["gross"] - entry["discount"] - share
            tax = (taxable * entry["tax_percent"] / Decimal("100")).quantize(MONEY)
            entry["invoice_discount_share"] = share
            entry["taxable"] = taxable
            entry["tax_amount"] = tax
            entry["line_total"] = taxable + tax
        tax_total = sum((entry["tax_amount"] for entry in lines), ZERO)
        net_total = (subtotal - line_discount - invoice_discount + tax_total + charges)
        net_total = net_total.quantize(MONEY)
        return {
            "subtotal": subtotal, "line_discount": line_discount,
            "invoice_discount": invoice_discount, "tax_total": tax_total,
            "charge_total": charges, "net_total": net_total,
        }

    @staticmethod
    def preview_totals(lines: list[dict], invoice_discount=0, charges=0) -> dict:
        """Totals preview used by the invoice form (identical to stored maths)."""
        return InvoiceService._allocate(lines, to_money(invoice_discount,
                                                        field="invoice_discount"),
                                        to_money(charges, field="charges"))

    def _assert_stock_available(self, session, invoice: Invoice,
                                warehouse: Warehouse | None,
                                ctx: SecurityContext | None) -> None:
        goods = [line for line in invoice.lines
                 if (session.get(Product, line.product_id).kind != CC.PRODUCT_SERVICE)]
        if not goods:
            return
        if warehouse is None:
            raise ValidationError(
                "برای فاکتوری که کالای فیزیکی دارد، انبار را انتخاب کنید.",
                field="warehouse_id")
        for line in goods:
            product = session.get(Product, line.product_id)
            if product.kind == CC.PRODUCT_SERVICE:
                continue
            base_qty = line.quantity * line.factor
            available = self.inventory.stock_on_hand_in_session(
                session, product.id, warehouse_id=warehouse.id)
            if available < base_qty:
                if warehouse.allow_negative and ctx and ctx.has("stock.negative_override"):
                    continue
                raise ValidationError(
                    f"موجودی «{product.name_fa}» در انبار «{warehouse.title_fa}» کافی "
                    f"نیست (موجودی: {available}، درخواست: {base_qty}).")

    def _assert_credit_limit(self, session, invoice: Invoice, party: DetailAccount,
                             ctx: SecurityContext | None) -> None:
        """Refuse a sale that pushes the customer past their credit limit.

        The limit is commercial policy (a field on the person), never a legal
        rate: ``0`` means "no limit". Exceeding it needs ``sales.approve``.
        """
        try:
            warn = self.settings.snapshot().bool("commerce_invoice_warn_credit_limit")
        except Exception:  # pragma: no cover
            warn = True
        limit = Decimal(party.credit_limit or 0)
        if not warn or limit <= 0:
            return
        debit, credit = session.execute(
            select(func.coalesce(func.sum(JournalLine.debit), 0),
                   func.coalesce(func.sum(JournalLine.credit), 0))
            .join(Journal, Journal.id == JournalLine.journal_id)
            .where(JournalLine.detail_id == party.id,
                   Journal.status.in_(AC.EFFECTIVE_STATUSES))).one()
        balance = Decimal(debit or 0) - Decimal(credit or 0)
        projected = balance + invoice.net_total
        if projected <= limit:
            return
        if ctx is not None and ctx.has("sales.approve"):
            self.audit.log_security(
                event_type=EventType.NEGATIVE_STOCK_OVERRIDE,
                message_fa=(f"فروش به «{party.name}» از سقف اعتبار عبور کرد "
                            f"({projected} > {limit})."),
                ctx=ctx, details={"party_id": party.id, "balance": str(balance),
                                  "net_total": str(invoice.net_total),
                                  "credit_limit": str(limit)}, session=session)
            return
        raise ValidationError(
            f"سقف اعتبار «{party.name}» کافی نیست (مانده: {balance}، "
            f"این فاکتور: {invoice.net_total}، سقف: {limit}). "
            "برای عبور از سقف، مجوز تأیید فروش لازم است.", field="party_detail_id")

    def _assert_return_quantities(self, session, invoice: Invoice, source: Invoice) -> None:
        returned: dict[int, Decimal] = {}
        for ret in session.execute(
                select(Invoice).where(Invoice.source_invoice_id == source.id,
                                      Invoice.id != invoice.id,
                                      Invoice.status != CC.STATUS_VOID)).scalars():
            for line in ret.lines:
                returned[line.product_id] = (returned.get(line.product_id, ZERO)
                                             + line.quantity)
        for line in invoice.lines:
            product = session.get(Product, line.product_id)
            name = product.name_fa if product else str(line.product_id)
            original = next((l for l in source.lines if l.product_id == line.product_id),
                            None)
            if original is None:
                raise ValidationError(f"کالای «{name}» در فاکتور مرجع وجود ندارد.")
            allowed = original.quantity - returned.get(line.product_id, ZERO)
            if line.quantity > allowed:
                raise ValidationError(
                    f"مقدار برگشت «{name}» بیش از مقدار قابل برگشت است "
                    f"(قابل برگشت: {allowed}).")

    def _post_in_session(self, session, invoice: Invoice,
                         ctx: SecurityContext | None) -> PostingResult:
        party = session.get(DetailAccount, invoice.party_detail_id)
        warehouse = (session.get(Warehouse, invoice.warehouse_id)
                     if invoice.warehouse_id else None)
        goods_lines = [line for line in invoice.lines
                       if session.get(Product, line.product_id).kind != CC.PRODUCT_SERVICE]
        stock_doc: StockDocument | None = None
        if goods_lines:
            if warehouse is None:
                raise ValidationError(
                    "برای ثبت فاکتور کالایی، انبار را انتخاب کنید.", field="warehouse_id")
            kind = (CC.MOVE_RECEIPT if CC.invoice_moves_stock_in(invoice.kind)
                    else CC.MOVE_ISSUE)
            doc_lines: list[StockLineInput] = []
            source_map = {}
            if invoice.source_invoice_id:
                source = session.get(Invoice, invoice.source_invoice_id)
                source_map = {line.product_id: line for line in source.lines} if source else {}
            for line in goods_lines:
                cost = ZERO
                if kind == CC.MOVE_RECEIPT and invoice.kind == CC.INVOICE_PURCHASE_RETURN:
                    original = source_map.get(line.product_id)
                    cost = original.cost_amount if original else line.cost_amount
                elif invoice.kind == CC.INVOICE_PURCHASE:
                    # inventory is carried at the net purchase cost (after discounts)
                    taxable = (line.quantity * line.unit_price - line.discount)
                    share = self._discount_share(invoice, line)
                    taxable = taxable - share
                    cost = (taxable / line.quantity).quantize(MONEY) if line.quantity else ZERO
                elif invoice.kind == CC.INVOICE_PURCHASE_RETURN:
                    taxable = (line.quantity * line.unit_price - line.discount)
                    taxable = taxable - self._discount_share(invoice, line)
                    cost = (taxable / line.quantity).quantize(MONEY) if line.quantity else ZERO
                doc_lines.append(StockLineInput(
                    product_id=line.product_id, quantity=line.quantity,
                    unit_id=line.unit_id, unit_cost=cost,
                    direction="in" if kind == CC.MOVE_RECEIPT else "out",
                    note=f"فاکتور {invoice.number}"))
            doc = self.inventory.create_document_in_session(session, StockDocInput(
                kind=kind, doc_date=invoice.invoice_date,
                warehouse_id=warehouse.id, lines=tuple(doc_lines),
                party_detail_id=party.id if party else None,
                reference_no=invoice.number,
                note=f"{CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}",
                source_kind="invoice", source_id=invoice.id,
                idempotency_key=f"invoice:{invoice.id}:stock",
            ), ctx)
            self.inventory.post_document_in_session(session, doc, ctx)
            invoice.stock_document_id = doc.id
            stock_doc = doc
            # cost of goods moved is the value the valuation engine computed
            stock_value = doc.total_value
            for line in invoice.lines:
                if session.get(Product, line.product_id).kind == CC.PRODUCT_SERVICE:
                    continue
                matching = [l for l in stock_doc.lines if l.product_id == line.product_id]
                line.cost_amount = sum((l.value for l in matching), ZERO)
        else:
            stock_value = ZERO

        components = self._components(invoice, stock_value)
        party_account = None
        if party and party.account_id:
            party_account = party.account_id
        draft = self._posting().build_entry(
            session, operation=invoice.kind, components=components,
            party_detail_id=party.id if party else None,
            party_account_hint_id=party_account,
            description=f"{CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}"
                        + (f" — {party.name}" if party else ""))
        journal = self.journals.create_posted_system_entry(
            session, ctx=ctx,
            data=self._journal_input(invoice, draft, party),
            source_kind="invoice", source_id=invoice.id)
        invoice.journal_id = journal.id
        invoice.cogs_total = components[CC.SRC_COGS]
        invoice.status = CC.STATUS_POSTED
        invoice.posted_at = utcnow()
        invoice.posted_by_id = ctx.user_id if ctx else None
        invoice.updated_by_id = ctx.user_id if ctx else None
        session.flush()
        self.audit.log_audit(
            ctx=ctx, entity_type="invoice", entity_id=invoice.id, action="post",
            summary_fa=f"ثبت نهایی {CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}",
            after=self._snapshot(invoice), session=session)
        self.audit.log_security(
            event_type=EventType.INVOICE_POSTED,
            message_fa=f"{CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number} ثبت نهایی شد.",
            ctx=ctx, details={"invoice_id": invoice.id, "number": invoice.number,
                              "net_total": str(invoice.net_total),
                              "journal_id": invoice.journal_id,
                              "stock_document_id": invoice.stock_document_id},
            session=session)
        return PostingResult(invoice=self._row(session, invoice),
                             journal_id=invoice.journal_id,
                             stock_document_id=invoice.stock_document_id)

    def _components(self, invoice: Invoice, stock_value: Decimal) -> dict[str, Decimal]:
        purchase_side = invoice.kind in (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN)
        discount = invoice.line_discount + invoice.invoice_discount
        components = {
            CC.SRC_NET: invoice.net_total,
            CC.SRC_SUBTOTAL: invoice.subtotal,
            CC.SRC_DISCOUNT: discount,
            CC.SRC_TAX: invoice.tax_total,
            CC.SRC_CHARGES: invoice.charge_total,
            CC.SRC_COGS: ZERO,
            CC.SRC_INVENTORY_VALUE: ZERO,
            CC.SRC_ADJUSTMENT_VALUE: ZERO,
        }
        if purchase_side:
            components[CC.SRC_INVENTORY_VALUE] = stock_value
        elif invoice.kind == CC.INVOICE_SALE:
            components[CC.SRC_COGS] = stock_value
        else:  # sale return
            components[CC.SRC_INVENTORY_VALUE] = stock_value
            components[CC.SRC_COGS] = stock_value
        return components

    @staticmethod
    def _discount_share(invoice: Invoice, line: InvoiceLine) -> Decimal:
        base_total = invoice.subtotal - invoice.line_discount
        if not base_total:
            return ZERO
        base = line.quantity * line.unit_price - line.discount
        return (invoice.invoice_discount * base / base_total).quantize(MONEY)

    def _journal_input(self, invoice: Invoice, draft, party: DetailAccount | None):
        from pars_erp.services.journals_service import JournalInput, JournalLineInput

        return JournalInput(
            entry_date=invoice.invoice_date,
            title_fa=(f"{CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}"
                      + (f" — {party.name}" if party else "")),
            reference_no=invoice.number,
            currency_code=invoice.currency_code or "IRR",
            notes=invoice.notes or "",
            idempotency_key=f"invoice:{invoice.id}:journal",
            lines=tuple(JournalLineInput(
                account_id=line.account_id, debit=line.debit, credit=line.credit,
                description=line.description, detail_id=line.detail_id)
                for line in draft.lines),
        )

    def _reverse_journal(self, session, invoice: Invoice, ctx, reason: str) -> Journal:
        original = session.get(Journal, invoice.journal_id)
        if original is None:
            raise NotFoundError("سند حسابداری فاکتور یافت نشد.")
        from pars_erp.services.journals_service import JournalInput, JournalLineInput

        lines = tuple(JournalLineInput(
            account_id=line.account_id, debit=line.credit, credit=line.debit,
            description=(f"برگشت: {line.description or ''}")[:300],
            detail_id=line.detail_id) for line in original.lines)
        return self.journals.create_posted_system_entry(
            session, ctx=ctx,
            data=JournalInput(
                entry_date=_dt.date.today(),
                title_fa=f"برگشت {CC.INVOICE_TITLES_FA[invoice.kind]} {invoice.number}",
                reference_no=invoice.number, idempotency_key=f"invoice:{invoice.id}:void",
                notes=reason, lines=lines),
            source_kind="invoice_void", source_id=invoice.id)

    def _posting(self):
        from pars_erp.services.posting_service import PostingService

        return PostingService(self.db, self.audit)

    @staticmethod
    def _create_permission(kind: str) -> str:
        return {
            CC.INVOICE_PURCHASE: "purchase.invoice",
            CC.INVOICE_PURCHASE_RETURN: "purchase.return",
            CC.INVOICE_SALE: "sales.invoice",
            CC.INVOICE_SALE_RETURN: "sales.return",
        }.get(kind, "purchase.invoice")

    @staticmethod
    def _approve_permission(kind: str) -> str:
        return ("purchase.approve" if kind in (CC.INVOICE_PURCHASE,
                                               CC.INVOICE_PURCHASE_RETURN)
                else "sales.approve")

    @staticmethod
    def _post_permission(kind: str) -> str:
        return ("purchase.post" if kind in (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN)
                else "sales.post")

    def _row(self, session, invoice: Invoice) -> InvoiceRow:
        party = session.get(DetailAccount, invoice.party_detail_id)
        warehouse = (session.get(Warehouse, invoice.warehouse_id)
                     if invoice.warehouse_id else None)
        source = (session.get(Invoice, invoice.source_invoice_id)
                  if invoice.source_invoice_id else None)
        return InvoiceRow(
            id=invoice.id, number=invoice.number, kind=invoice.kind,
            kind_fa=CC.INVOICE_TITLES_FA.get(invoice.kind, invoice.kind),
            invoice_date=invoice.invoice_date, party_id=invoice.party_detail_id,
            party_name=party.name if party else "",
            warehouse_id=invoice.warehouse_id,
            warehouse_title=warehouse.title_fa if warehouse else "",
            status=invoice.status,
            status_fa=CC.DOC_STATUS_TITLES_FA.get(invoice.status, invoice.status),
            subtotal=invoice.subtotal, line_discount=invoice.line_discount,
            invoice_discount=invoice.invoice_discount, tax_total=invoice.tax_total,
            charge_total=invoice.charge_total, net_total=invoice.net_total,
            cogs_total=invoice.cogs_total,
            reference_no=invoice.reference_no or "", notes=invoice.notes or "",
            source_invoice_id=invoice.source_invoice_id,
            source_number=source.number if source else "",
            stock_document_id=invoice.stock_document_id,
            journal_id=invoice.journal_id, posted_at=invoice.posted_at,
            lines=tuple(self._line_row(session, line) for line in invoice.lines),
        )

    @staticmethod
    def _line_row(session, line: InvoiceLine) -> InvoiceLineRow:
        gross = (line.quantity * line.unit_price).quantize(MONEY)
        product = line.product or session.get(Product, line.product_id)
        return InvoiceLineRow(
            id=line.id, line_no=line.line_no, product_id=line.product_id,
            product_code=product.code if product else "",
            product_name=product.name_fa if product else "",
            unit_title=product.unit.title_fa if product and product.unit else "",
            quantity=line.quantity, unit_price=line.unit_price, gross=gross,
            discount=line.discount, tax_percent=line.tax_percent,
            tax_amount=line.tax_amount, line_total=line.line_total,
            cost_amount=line.cost_amount, description=line.description or "")

    @staticmethod
    def _snapshot(invoice: Invoice) -> dict:
        return {
            "number": invoice.number, "kind": invoice.kind, "status": invoice.status,
            "party_detail_id": invoice.party_detail_id,
            "subtotal": str(invoice.subtotal), "tax_total": str(invoice.tax_total),
            "net_total": str(invoice.net_total),
            "journal_id": invoice.journal_id,
            "stock_document_id": invoice.stock_document_id,
        }


def new_idempotency_key() -> str:
    return uuid.uuid4().hex
