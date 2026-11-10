"""Tax rates, price lists and price resolution.

Nothing in this module hard-codes a legal rate: taxes live in ``com_tax_rates``
with a validity range, so a rate change is a new dated row instead of an edit
that would silently rewrite history. Invoices copy the rate/amount onto their
lines, therefore past invoices stay exactly as they were printed.

Price lists follow the same rule: a list may be limited to a date range and to
a customer, and it carries per-product prices with optional percent/fixed
discounts and a minimum sale price. :meth:`PricingService.resolve_price` picks
the most specific applicable list for a customer and a date.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import PriceList, PriceListItem, Product, TaxRate
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import (
    ZERO,
    clean_code,
    clean_text,
    get_or_404,
    to_money,
    to_percent,
)

TAX_APPLIES = (("both", "خرید و فروش"), ("sale", "فروش"), ("purchase", "خرید"))


def price_list_applies(price_list, day: _dt.date) -> bool:
    """True when ``price_list`` is active and inside its validity range."""
    if not price_list.is_active:
        return False
    if price_list.start_date and day < price_list.start_date:
        return False
    if price_list.end_date and day > price_list.end_date:
        return False
    return True


@dataclass(frozen=True)
class TaxRateRow:
    id: int
    code: str
    title_fa: str
    percent: Decimal
    applies_to: str
    applies_to_fa: str
    valid_from: _dt.date
    valid_to: _dt.date | None
    is_active: bool
    note: str

    @property
    def range_fa(self) -> str:
        return f"{self.valid_from} تا {self.valid_to or 'نامحدود'}"

    def applies_on(self, day: _dt.date, kind: str) -> bool:
        if not self.is_active:
            return False
        if self.applies_to != "both" and self.applies_to != kind:
            return False
        if self.valid_from and day < self.valid_from:
            return False
        if self.valid_to and day > self.valid_to:
            return False
        return True


@dataclass(frozen=True)
class PriceListItemRow:
    id: int
    product_id: int
    product_code: str
    product_name: str
    price: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    min_price: Decimal
    final_price: Decimal
    note: str


@dataclass(frozen=True)
class PriceListRow:
    id: int
    code: str
    title_fa: str
    kind: str
    kind_fa: str
    party_detail_id: int | None
    discount_percent: Decimal
    start_date: _dt.date | None
    end_date: _dt.date | None
    is_active: bool
    note: str
    items: tuple[PriceListItemRow, ...]

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"

    @property
    def range_fa(self) -> str:
        if not self.start_date and not self.end_date:
            return "بدون محدودیت تاریخ"
        return f"{self.start_date or '-'} تا {self.end_date or '-'}"

    def applies_on(self, day: _dt.date) -> bool:
        return price_list_applies(self, day)


@dataclass(frozen=True)
class ResolvedPrice:
    product_id: int
    price: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    min_price: Decimal
    source: str
    price_list_id: int | None = None

    @property
    def net_price(self) -> Decimal:
        value = self.price - self.discount_amount
        value = value - (self.price * self.discount_percent / Decimal("100"))
        return value.quantize(Decimal("0.01"))


class PricingService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # -------------------------------------------------------------- tax rates
    def list_tax_rates(self, ctx: SecurityContext | None, *, active: bool | None = None,
                       on_date: _dt.date | None = None,
                       kind: str | None = None) -> list[TaxRateRow]:
        require_permission(ctx, "pricing.view")
        query = select(TaxRate).order_by(TaxRate.valid_from.desc(), TaxRate.code)
        if active is not None:
            query = query.where(TaxRate.is_active.is_(bool(active)))
        with self.db.session_scope() as session:
            rows = [self._tax_row(rate) for rate in session.execute(query).scalars()]
        if on_date:
            day = on_date
            rows = [row for row in rows if row.applies_on(day, kind or "both")]
        return rows

    def tax_rate_choices(self, ctx: SecurityContext | None, *,
                         on_date: _dt.date | None = None,
                         kind: str | None = None) -> list[tuple[int, str]]:
        rows = self.list_tax_rates(ctx, active=True, on_date=on_date or _dt.date.today(),
                                   kind=kind)
        return [(row.id, f"{row.title_fa} ({row.percent}%)") for row in rows]

    def create_tax_rate(self, ctx: SecurityContext | None, *, code: str, title_fa: str,
                        percent, applies_to: str = "both",
                        valid_from: _dt.date | None = None,
                        valid_to: _dt.date | None = None,
                        note: str = "", is_active: bool = True) -> TaxRateRow:
        require_permission(ctx, "pricing.edit")
        if applies_to not in dict(TAX_APPLIES):
            raise ValidationError("دامنهٔ اعمال مالیات معتبر نیست.", field="applies_to")
        start = valid_from or _dt.date.today()
        if valid_to and valid_to < start:
            raise ValidationError("پایان اعتبار نمی‌تواند قبل از شروع باشد.", field="valid_to")
        with self.db.session_scope() as session:
            rate = TaxRate(
                code=clean_code(code, label="کد مالیات", max_length=24),
                title_fa=clean_text(title_fa, field="title_fa", label="عنوان مالیات",
                                    required=True, max_length=120),
                percent=to_percent(percent, field="percent"),
                applies_to=applies_to, valid_from=start, valid_to=valid_to,
                is_active=bool(is_active),
                note=clean_text(note, field="note", label="توضیح", max_length=300),
            )
            session.add(rate)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد مالیات تکراری است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="tax_rate", entity_id=rate.id, action="create",
                summary_fa=f"تعریف نرخ مالیات {rate.title_fa} ({rate.percent}%)",
                after={"percent": str(rate.percent), "valid_from": str(rate.valid_from),
                       "valid_to": str(rate.valid_to)}, session=session)
            return self._tax_row(rate)

    def resolve_tax_percent(self, ctx: SecurityContext | None, *,
                            rate_id: int | None, on_date: _dt.date,
                            kind: str) -> Decimal:
        """Return the persisted percentage for ``rate_id`` on ``on_date``."""
        if not rate_id:
            return ZERO
        with self.db.session_scope() as session:
            rate = get_or_404(session, TaxRate, rate_id, "نرخ مالیات یافت نشد.")
            if rate.applies_to not in ("both", kind):
                raise ValidationError(
                    f"نرخ «{rate.title_fa}» برای این نوع فاکتور تعریف نشده است.",
                    field="tax_rate_id")
            return Decimal(rate.percent)

    # ------------------------------------------------------------ price lists
    def list_price_lists(self, ctx: SecurityContext | None, *, kind: str | None = None,
                         active: bool | None = None,
                         on_date: _dt.date | None = None) -> list[PriceListRow]:
        require_permission(ctx, "pricing.view")
        query = select(PriceList).order_by(PriceList.code)
        if kind:
            query = query.where(PriceList.kind == kind)
        if active is not None:
            query = query.where(PriceList.is_active.is_(bool(active)))
        with self.db.session_scope() as session:
            rows = [self._list_row(item) for item in session.execute(query).scalars()]
        if on_date:
            rows = [row for row in rows if row.applies_on(on_date)]
        return rows

    def price_list_choices(self, ctx: SecurityContext | None, *,
                           on_date: _dt.date | None = None) -> list[tuple[int, str]]:
        rows = self.list_price_lists(ctx, active=True, on_date=on_date)
        return [(row.id, f"{row.title_fa} ({row.kind_fa})") for row in rows]

    def create_price_list(self, ctx: SecurityContext | None, *, code: str, title_fa: str,
                          kind: str = CC.PRICE_LIST_RETAIL,
                          party_detail_id: int | None = None, discount_percent=0,
                          start_date: _dt.date | None = None,
                          end_date: _dt.date | None = None,
                          items: tuple[tuple[int, Decimal, Decimal, Decimal, str], ...] = (),
                          note: str = "", is_active: bool = True) -> PriceListRow:
        """``items`` is ``(product_id, price, discount_percent, discount_amount, note)``."""
        require_permission(ctx, "pricing.edit")
        if kind not in CC.PRICE_LIST_KINDS:
            raise ValidationError("نوع لیست قیمت معتبر نیست.", field="kind")
        if start_date and end_date and end_date < start_date:
            raise ValidationError("پایان بازه نمی‌تواند قبل از شروع باشد.", field="end_date")
        with self.db.session_scope() as session:
            price_list = PriceList(
                code=clean_code(code, label="کد لیست", max_length=24),
                title_fa=clean_text(title_fa, field="title_fa", label="عنوان لیست",
                                    required=True, max_length=120),
                kind=kind, party_detail_id=party_detail_id,
                discount_percent=to_percent(discount_percent, field="discount_percent"),
                start_date=start_date, end_date=end_date, is_active=bool(is_active),
                note=clean_text(note, field="note", label="توضیح", max_length=300),
            )
            for product_id, price, percent, amount, item_note in items:
                product = get_or_404(session, Product, product_id, "کالای لیست قیمت یافت نشد.")
                if product.kind == CC.PRODUCT_SERVICE:
                    pass  # services may have prices too
                price_list.items.append(PriceListItem(
                    product_id=product.id, price=to_money(price, field="price"),
                    discount_percent=to_percent(percent, field="discount_percent"),
                    discount_amount=to_money(amount, field="discount_amount"),
                    note=clean_text(item_note, field="note", label="توضیح", max_length=300),
                ))
            session.add(price_list)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("کد لیست قیمت تکراری است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="price_list", entity_id=price_list.id, action="create",
                summary_fa=f"ایجاد لیست قیمت {price_list.title_fa}",
                after={"kind": kind, "items": len(price_list.items)}, session=session)
            return self._list_row(price_list)

    def set_item_price(self, ctx: SecurityContext | None, price_list_id: int, *,
                       product_id: int, price, discount_percent=0,
                       discount_amount=0, min_price=0, note: str = "",
                       reason: str = "") -> PriceListRow:
        require_permission(ctx, "pricing.edit")
        if len((reason or "").strip()) < 3:
            raise ValidationError("دلیل تغییر قیمت را بنویسید.", field="reason")
        with self.db.session_scope() as session:
            price_list = get_or_404(session, PriceList, price_list_id,
                                    "لیست قیمت یافت نشد.")
            item = session.execute(
                select(PriceListItem).where(PriceListItem.price_list_id == price_list.id,
                                            PriceListItem.product_id == product_id)
            ).scalars().first()
            before = str(item.price) if item else None
            if item is None:
                item = PriceListItem(price_list_id=price_list.id, product_id=product_id,
                                     price=to_money(price, field="price"))
                session.add(item)
            item.price = to_money(price, field="price")
            item.discount_percent = to_percent(discount_percent, field="discount_percent")
            item.discount_amount = to_money(discount_amount, field="discount_amount")
            item.min_price = to_money(min_price, field="min_price")
            item.note = clean_text(note, field="note", label="توضیح", max_length=300)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="price_list_item", entity_id=item.id,
                action="price_change",
                summary_fa=(f"تغییر قیمت کالا در لیست «{price_list.title_fa}»: "
                            f"{before or '—'} → {item.price}"),
                before={"price": before}, after={"price": str(item.price),
                                                 "reason": reason.strip()},
                session=session)
            return self._list_row(price_list)

    def resolve_price(self, ctx: SecurityContext | None, product_id: int, *,
                      party_detail_id: int | None = None,
                      on_date: _dt.date | None = None,
                      kind: str = CC.INVOICE_SALE) -> ResolvedPrice:
        """Most specific price for a customer/date; falls back to the product price."""
        require_permission(ctx, "pricing.view")
        day = on_date or _dt.date.today()
        with self.db.session_scope() as session:
            product = get_or_404(session, Product, product_id, "کالا یافت نشد.")
            base = (product.sale_price if kind != CC.INVOICE_PURCHASE
                    else product.purchase_price)
            candidates = [item for item in session.execute(
                select(PriceList).where(PriceList.is_active.is_(True))).scalars()
                if price_list_applies(item, day)
                and (item.party_detail_id in (None, party_detail_id))]
            if not candidates:
                return ResolvedPrice(product_id=product.id, price=base,
                                     discount_percent=ZERO, discount_amount=ZERO,
                                     min_price=ZERO, source="بهای کالا")
            # specificity: party list > seasonal > wholesale > retail
            priority = {CC.PRICE_LIST_SPECIAL: 0, CC.PRICE_LIST_SEASONAL: 1,
                        CC.PRICE_LIST_WHOLESALE: 2, CC.PRICE_LIST_RETAIL: 3}
            candidates.sort(key=lambda pl: (pl.party_detail_id is None,
                                            priority.get(pl.kind, 9)))
            for price_list in candidates:
                item = next((i for i in price_list.items if i.product_id == product.id),
                            None)
                if item is None:
                    continue
                return ResolvedPrice(
                    product_id=product.id, price=item.price,
                    discount_percent=(Decimal(item.discount_percent)
                                      + Decimal(price_list.discount_percent)),
                    discount_amount=item.discount_amount, min_price=item.min_price,
                    source=f"لیست {price_list.title_fa}", price_list_id=price_list.id)
            return ResolvedPrice(product_id=product.id, price=base,
                                 discount_percent=ZERO, discount_amount=ZERO,
                                 min_price=ZERO, source="بهای کالا")

    # ------------------------------------------------------------- internals
    @staticmethod
    def _tax_row(rate: TaxRate) -> TaxRateRow:
        return TaxRateRow(
            id=rate.id, code=rate.code, title_fa=rate.title_fa, percent=rate.percent,
            applies_to=rate.applies_to,
            applies_to_fa=dict(TAX_APPLIES).get(rate.applies_to, rate.applies_to),
            valid_from=rate.valid_from, valid_to=rate.valid_to,
            is_active=rate.is_active, note=rate.note or "")

    @staticmethod
    def _list_row(price_list: PriceList) -> PriceListRow:
        items = tuple(PriceListItemRow(
            id=item.id, product_id=item.product_id,
            product_code=item.product.code if item.product else "",
            product_name=item.product.name_fa if item.product else "",
            price=item.price, discount_percent=item.discount_percent,
            discount_amount=item.discount_amount, min_price=item.min_price,
            final_price=(item.price - item.discount_amount
                         - (item.price * item.discount_percent / Decimal("100"))
                         ).quantize(Decimal("0.01")),
            note=item.note or "") for item in price_list.items)
        return PriceListRow(
            id=price_list.id, code=price_list.code, title_fa=price_list.title_fa,
            kind=price_list.kind,
            kind_fa=CC.PRICE_LIST_TITLES_FA.get(price_list.kind, price_list.kind),
            party_detail_id=price_list.party_detail_id,
            discount_percent=price_list.discount_percent,
            start_date=price_list.start_date, end_date=price_list.end_date,
            is_active=price_list.is_active, note=price_list.note or "", items=items)
