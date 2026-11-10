"""Commerce models (phase 3): catalogue, warehouses, stock, purchase and sale.

Design notes (mirrored in docs/PHASE3_SCHEMA.md):

* every quantity is a ``Numeric(18, 4)`` Decimal, every money value is
  :class:`pars_erp.db.types.MoneyAmount` - no float ever touches stock or money;
* a *stock movement* is the only way inventory changes: ``stock_documents`` +
  ``stock_document_lines``. Balances and FIFO layers are derived tables kept in
  step inside the same transaction, so a cardex can always be rebuilt from the
  documents;
* invoices are documents with their own state machine; they reference the stock
  document and the journal they produced, which makes double posting impossible
  to hide;
* party records extend :class:`pars_erp.db.models.accounting.DetailAccount`
  (تفصیلی) so purchase/sales balances land directly in the phase-2 ledger.
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

from pars_erp.commerce.constants import (
    INVOICE_SALE,
    MOVE_RECEIPT,
    ORDER_STATUS_DRAFT,
    PRICE_LIST_RETAIL,
    PRODUCT_GOODS,
    STATUS_DRAFT,
)
from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import MoneyAmount, UtcDateTime

ZERO = Decimal("0.0000")


class Unit(Base, TimestampMixin):
    """Measuring unit; sub-units carry a conversion factor to their base unit."""

    __tablename__ = "com_units"
    __table_args__ = (
        UniqueConstraint("code", name="uq_com_units_code"),
        UniqueConstraint("title_fa", name="uq_com_units_title_fa"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="count")
    #: how many *base* units one of this unit equals (عدد = ۱)
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False,
                                            default=Decimal("1"))
    base_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_units.id", ondelete="RESTRICT"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    base_unit: Mapped["Unit | None"] = relationship(remote_side="Unit.id", lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Unit {self.code} {self.title_fa}>"


class ProductCategory(Base, TimestampMixin):
    """Multi-level product category tree."""

    __tablename__ = "com_categories"
    __table_args__ = (
        UniqueConstraint("code", name="uq_com_categories_code"),
        Index("ix_com_categories_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_categories.id", ondelete="RESTRICT"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    parent: Mapped["ProductCategory | None"] = relationship(
        remote_side="ProductCategory.id", lazy="joined")


class Brand(Base, TimestampMixin):
    __tablename__ = "com_brands"
    __table_args__ = (UniqueConstraint("code", name="uq_com_brands_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Product(Base, TimestampMixin):
    """A good or a service."""

    __tablename__ = "com_products"
    __table_args__ = (
        UniqueConstraint("code", name="uq_com_products_code"),
        UniqueConstraint("barcode", name="uq_com_products_barcode"),
        Index("ix_com_products_category", "category_id"),
        Index("ix_com_products_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name_fa: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default=PRODUCT_GOODS)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_categories.id", ondelete="RESTRICT"), nullable=True)
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_brands.id", ondelete="RESTRICT"), nullable=True)
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("com_units.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    max_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    purchase_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    sale_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped["ProductCategory | None"] = relationship(lazy="joined")
    brand: Mapped["Brand | None"] = relationship(lazy="joined")
    unit: Mapped["Unit"] = relationship(lazy="joined")

    @property
    def is_service(self) -> bool:
        return self.kind != PRODUCT_GOODS

    @property
    def display(self) -> str:
        return f"{self.code} — {self.name_fa}"


class Warehouse(Base, TimestampMixin):
    __tablename__ = "com_warehouses"
    __table_args__ = (UniqueConstraint("code", name="uq_com_warehouses_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    keeper: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_negative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: ``None`` = inherit the company default; otherwise "average" or "fifo".
    valuation_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"


class StockDocument(Base, TimestampMixin):
    """Receipt / issue / transfer / adjustment / count-adjustment."""

    __tablename__ = "com_stock_documents"
    __table_args__ = (
        UniqueConstraint("number", name="uq_com_stock_documents_number"),
        UniqueConstraint("idempotency_key", name="uq_com_stock_documents_idempotency_key"),
        Index("ix_com_stock_documents_date", "doc_date"),
        Index("ix_com_stock_documents_source", "source_kind", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=MOVE_RECEIPT)
    doc_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=False)
    target_warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=True)
    party_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: "sales_invoice" / "purchase_invoice" / "stock_count" / None
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    total_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warehouse: Mapped["Warehouse"] = relationship(foreign_keys=[warehouse_id], lazy="joined")
    target_warehouse: Mapped["Warehouse | None"] = relationship(
        foreign_keys=[target_warehouse_id], lazy="joined")
    lines: Mapped[list["StockDocumentLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin",
        order_by="StockDocumentLine.line_no")


class StockDocumentLine(Base):
    __tablename__ = "com_stock_document_lines"
    __table_args__ = (Index("ix_com_stock_document_lines_product", "product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("com_stock_documents.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    #: signed quantity: positive moves stock in, negative moves it out
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    #: Movement direction for mixed documents (stock count adjustments): "in"/"out".
    #: For receipts/issues/transfers the document kind decides and this is ignored.
    direction: Mapped[str] = mapped_column(String(4), nullable=False, default="in")
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_units.id", ondelete="RESTRICT"), nullable=True)
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False,
                                            default=Decimal("1"))
    unit_cost: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    document: Mapped["StockDocument"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(lazy="joined")


class StockBalance(Base, TimestampMixin):
    """Current quantity and value per product/warehouse (kept in step)."""

    __tablename__ = "com_stock_balances"
    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_com_stock_balances_product_warehouse"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)

    product: Mapped["Product"] = relationship(lazy="joined")
    warehouse: Mapped["Warehouse"] = relationship(lazy="joined")

    @property
    def average_cost(self) -> Decimal:
        if self.quantity == 0:
            return Decimal("0")
        return (self.value / self.quantity).quantize(Decimal("0.0001"))


class StockLayer(Base, TimestampMixin):
    """FIFO cost layer: what is left of one receipt at its original cost."""

    __tablename__ = "com_stock_layers"
    __table_args__ = (Index("ix_com_stock_layers_product_wh", "product_id", "warehouse_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_stock_documents.id", ondelete="RESTRICT"), nullable=True)
    received_on: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False)


class TaxRate(Base, TimestampMixin):
    """A dated tax/levy definition - never a hard-coded legal rate."""

    __tablename__ = "com_tax_rates"
    __table_args__ = (UniqueConstraint("code", "valid_from", name="uq_com_tax_rates_code_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=ZERO)
    applies_to: Mapped[str] = mapped_column(String(16), nullable=False, default="both")
    valid_from: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PriceList(Base, TimestampMixin):
    __tablename__ = "com_price_lists"
    __table_args__ = (UniqueConstraint("code", name="uq_com_price_lists_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=PRICE_LIST_RETAIL)
    party_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=ZERO)
    start_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[_dt.date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    items: Mapped[list["PriceListItem"]] = relationship(
        back_populates="price_list", cascade="all, delete-orphan", lazy="selectin")


class PriceListItem(Base, TimestampMixin):
    __tablename__ = "com_price_list_items"
    __table_args__ = (Index("ix_com_price_list_items_lookup", "price_list_id", "product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    price_list_id: Mapped[int] = mapped_column(
        ForeignKey("com_price_lists.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=ZERO)
    discount_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    min_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    price_list: Mapped["PriceList"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(lazy="joined")


class Invoice(Base, TimestampMixin):
    """Purchase / sale (and their returns) - the commercial document."""

    __tablename__ = "com_invoices"
    __table_args__ = (
        UniqueConstraint("number", name="uq_com_invoices_number"),
        UniqueConstraint("idempotency_key", name="uq_com_invoices_idempotency_key"),
        Index("ix_com_invoices_date_kind", "invoice_date", "kind"),
        Index("ix_com_invoices_party", "party_detail_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=INVOICE_SALE)
    invoice_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    party_detail_id: Mapped[int] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=True)
    reference_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="IRR")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False,
                                                   default=Decimal("1"))
    subtotal: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    line_discount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    invoice_discount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False,
                                                     default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    charge_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    net_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    cogs_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    source_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_invoices.id", ondelete="RESTRICT"), nullable=True)
    stock_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_stock_documents.id", ondelete="RESTRICT"), nullable=True)
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_journals.id", ondelete="RESTRICT"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    posted_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    posted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warehouse: Mapped["Warehouse | None"] = relationship(
        foreign_keys=[warehouse_id], lazy="joined")
    party: Mapped["DetailAccount"] = relationship(
        "DetailAccount", primaryjoin="Invoice.party_detail_id == foreign(DetailAccount.id)",
        lazy="joined", viewonly=True)
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin",
        order_by="InvoiceLine.line_no")


class InvoiceLine(Base):
    __tablename__ = "com_invoice_lines"
    __table_args__ = (Index("ix_com_invoice_lines_product", "product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("com_invoices.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_units.id", ondelete="RESTRICT"), nullable=True)
    factor: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False,
                                            default=Decimal("1"))
    unit_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    discount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=ZERO)
    tax_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    line_total: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    cost_amount: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(lazy="joined")


class OrderDocument(Base, TimestampMixin):
    """Purchase request / purchase order / sales order with a status history."""

    __tablename__ = "com_order_documents"
    __table_args__ = (
        UniqueConstraint("number", name="uq_com_order_documents_number"),
        Index("ix_com_order_documents_kind_status", "kind", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    doc_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    party_detail_id: Mapped[int | None] = mapped_column(
        ForeignKey("acc_details.id", ondelete="RESTRICT"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ORDER_STATUS_DRAFT)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warehouse: Mapped["Warehouse | None"] = relationship(lazy="joined")
    party: Mapped["DetailAccount"] = relationship(
        "DetailAccount", primaryjoin="OrderDocument.party_detail_id == foreign(DetailAccount.id)",
        lazy="joined", viewonly=True)
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin",
        order_by="OrderLine.line_no")
    history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin",
        order_by="OrderStatusHistory.id")


class OrderLine(Base):
    __tablename__ = "com_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("com_order_documents.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    unit_price: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    document: Mapped["OrderDocument"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(lazy="joined")


class OrderStatusHistory(Base):
    __tablename__ = "com_order_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("com_order_documents.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    changed_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    changed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    document: Mapped["OrderDocument"] = relationship(back_populates="history")


class StockCountSheet(Base, TimestampMixin):
    """انبارگردانی: counted versus system quantity per product."""

    __tablename__ = "com_stock_counts"
    __table_args__ = (UniqueConstraint("number", name="uq_com_stock_counts_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    count_date: Mapped[_dt.date] = mapped_column(Date, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("com_warehouses.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stock_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("com_stock_documents.id", ondelete="RESTRICT"), nullable=True)
    approved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warehouse: Mapped["Warehouse"] = relationship(lazy="joined")
    lines: Mapped[list["StockCountLine"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", lazy="selectin",
        order_by="StockCountLine.id")


class StockCountLine(Base):
    __tablename__ = "com_stock_count_lines"
    __table_args__ = (Index("ix_com_stock_count_lines_product", "product_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_id: Mapped[int] = mapped_column(
        ForeignKey("com_stock_counts.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("com_products.id", ondelete="RESTRICT"), nullable=False)
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=ZERO)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    difference_value: Mapped[Decimal] = mapped_column(MoneyAmount, nullable=False, default=ZERO)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    sheet: Mapped["StockCountSheet"] = relationship(back_populates="lines")
    product: Mapped["Product"] = relationship(lazy="joined")

    @property
    def difference(self) -> Decimal:
        return self.counted_quantity - self.system_quantity


class PostingRule(Base, TimestampMixin):
    """Configurable accounting pattern for one commerce operation."""

    __tablename__ = "com_posting_rules"
    __table_args__ = (UniqueConstraint("operation", name="uq_com_posting_rules_operation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lines: Mapped[list["PostingRuleLine"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan", lazy="selectin",
        order_by="PostingRuleLine.line_no")


class PostingRuleLine(Base):
    __tablename__ = "com_posting_rule_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("com_posting_rules.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="debit")
    account_id: Mapped[int] = mapped_column(
        ForeignKey("acc_accounts.id", ondelete="RESTRICT"), nullable=False)
    amount_source: Mapped[str] = mapped_column(String(24), nullable=False, default="net")
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)

    rule: Mapped["PostingRule"] = relationship(back_populates="lines")
    account: Mapped["object"] = relationship("Account", lazy="joined")
