"""Management reports for purchasing, sales, inventory and persons.

Every report returns a :class:`ReportTable` (title, columns, rows) so the UI can
render it, print it, or hand the very same rows to the Excel/PDF exporter - the
numbers can therefore never diverge between screen and file.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from pars_erp.accounting import constants as AC
from pars_erp.commerce import constants as CC
from pars_erp.core.errors import ValidationError
from pars_erp.db.models import (
    DetailAccount,
    Invoice,
    InvoiceLine,
    Journal,
    JournalLine,
    Product,
    ProductCategory,
    StockBalance,
    StockCountSheet,
    StockDocument,
    StockDocumentLine,
    Warehouse,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_any

ZERO = Decimal("0")


@dataclass(frozen=True)
class ReportTable:
    key: str
    title_fa: str
    columns: tuple[str, ...]
    rows: tuple[tuple, ...]
    meta_fa: str = ""

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def totals(self) -> tuple:
        """Sum the numeric columns (everything after the first text column)."""
        if not self.rows:
            return ()
        numbers = []
        for index in range(1, self.column_count):
            total = ZERO
            numeric = False
            for row in self.rows:
                value = row[index] if index < len(row) else None
                if isinstance(value, Decimal):
                    total += value
                    numeric = True
            numbers.append(total if numeric else None)
        return tuple(numbers)


@dataclass(frozen=True)
class ReportPeriod:
    date_from: _dt.date
    date_to: _dt.date

    def __post_init__(self) -> None:
        if self.date_to < self.date_from:
            raise ValidationError("تاریخ پایان گزارش نمی‌تواند قبل از شروع باشد.")


PERIOD_CHOICES = (("daily", "روزانه"), ("monthly", "ماهانه"), ("yearly", "سالانه"))


class CommerceReportService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------- purchasing
    def purchase_summary(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                         group_by: str = "monthly",
                         warehouse_id: int | None = None) -> ReportTable:
        require_any(ctx, "purchase.reports", "commerce.reports")
        kinds = (CC.INVOICE_PURCHASE, CC.INVOICE_PURCHASE_RETURN)
        with self.db.session_scope() as session:
            rows = self._invoice_rows(session, kinds, period, warehouse_id)
            buckets: dict[str, dict[str, Decimal]] = {}
            for row in rows:
                key = self._bucket_key(row["date"], group_by, row)
                bucket = buckets.setdefault(key, {"purchase": ZERO, "return": ZERO,
                                                  "net": ZERO})
                if row["kind"] == CC.INVOICE_PURCHASE:
                    bucket["purchase"] += row["net_total"]
                else:
                    bucket["return"] += row["net_total"]
                bucket["net"] = bucket["purchase"] - bucket["return"]
            title = {
                "daily": "خرید روزانه", "monthly": "خرید ماهانه", "yearly": "خرید سالانه",
                "supplier": "خرید به تفکیک تأمین‌کننده", "product": "خرید به تفکیک کالا",
                "warehouse": "خرید به تفکیک انبار",
            }.get(group_by, "خلاصهٔ خرید")
            return ReportTable(
                key=f"purchase_{group_by}", title_fa=title,
                columns=("گروه", "خرید", "برگشت", "خالص"),
                rows=tuple((key, value["purchase"], value["return"], value["net"])
                           for key, value in sorted(buckets.items())),
                meta_fa=self._period_text(period))

    def purchase_by_product(self, ctx: SecurityContext | None,
                            period: ReportPeriod) -> ReportTable:
        require_any(ctx, "purchase.reports", "commerce.reports")
        return self._by_product(ctx, period, (CC.INVOICE_PURCHASE,
                                              CC.INVOICE_PURCHASE_RETURN),
                                "خرید به تفکیک کالا", "purchase_product")

    # ------------------------------------------------------------------ sales
    def sales_summary(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                      group_by: str = "monthly",
                      warehouse_id: int | None = None) -> ReportTable:
        require_any(ctx, "sales.reports", "commerce.reports")
        kinds = (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN)
        with self.db.session_scope() as session:
            rows = self._invoice_rows(session, kinds, period, warehouse_id)
            buckets: dict[str, dict[str, Decimal]] = {}
            for row in rows:
                key = self._bucket_key(row["date"], group_by, row)
                bucket = buckets.setdefault(key, {"sale": ZERO, "return": ZERO,
                                                  "net": ZERO, "discount": ZERO})
                if row["kind"] == CC.INVOICE_SALE:
                    bucket["sale"] += row["net_total"]
                    bucket["discount"] += row["discount"]
                else:
                    bucket["return"] += row["net_total"]
                bucket["net"] = bucket["sale"] - bucket["return"]
            title = {
                "daily": "فروش روزانه", "monthly": "فروش ماهانه", "yearly": "فروش سالانه",
                "customer": "فروش به تفکیک مشتری",
                "category": "فروش به تفکیک گروه کالا",
                "warehouse": "فروش به تفکیک انبار",
            }.get(group_by, "خلاصهٔ فروش")
            return ReportTable(
                key=f"sales_{group_by}", title_fa=title,
                columns=("گروه", "فروش", "برگشت", "تخفیف", "خالص"),
                rows=tuple((key, value["sale"], value["return"], value["discount"],
                            value["net"]) for key, value in sorted(buckets.items())),
                meta_fa=self._period_text(period))

    def sales_by_product(self, ctx: SecurityContext | None,
                         period: ReportPeriod) -> ReportTable:
        require_any(ctx, "sales.reports", "commerce.reports")
        return self._by_product(ctx, period, (CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN),
                                "فروش به تفکیک کالا", "sales_product")

    def best_sellers(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                     limit: int = 20) -> ReportTable:
        require_any(ctx, "sales.reports", "commerce.reports")
        with self.db.session_scope() as session:
            query = (select(Product.code, Product.name_fa,
                            func.sum(InvoiceLine.quantity),
                            func.sum(InvoiceLine.line_total),
                            func.sum(InvoiceLine.tax_amount),
                            func.sum(InvoiceLine.cost_amount))
                     .join(InvoiceLine, InvoiceLine.product_id == Product.id)
                     .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                     .where(Invoice.kind == CC.INVOICE_SALE,
                            Invoice.status == CC.STATUS_POSTED,
                            Invoice.invoice_date >= period.date_from,
                            Invoice.invoice_date <= period.date_to)
                     .group_by(Product.id, Product.code, Product.name_fa)
                     .order_by(func.sum(InvoiceLine.quantity).desc())
                     .limit(max(1, min(limit, 200))))
            rows = []
            for code, name, qty, line_total, tax, cost in session.execute(query).all():
                revenue = Decimal(line_total or 0) - Decimal(tax or 0)
                cost = Decimal(cost or 0)
                rows.append((f"{code} — {name}", Decimal(qty or 0), revenue, cost,
                             revenue - cost))
            return ReportTable(
                key="best_sellers", title_fa="پرفروش‌ترین کالاها",
                columns=("کالا", "مقدار", "فروش خالص", "بهای تمام‌شده", "سود ناخالص"),
                rows=tuple(rows), meta_fa=self._period_text(period))

    def slow_movers(self, ctx: SecurityContext | None, period: ReportPeriod, *,
                    limit: int = 50) -> ReportTable:
        """Products that had no sale in the period but have stock on hand."""
        require_any(ctx, "sales.reports", "commerce.reports")
        with self.db.session_scope() as session:
            sold = {pid for pid, in session.execute(
                select(InvoiceLine.product_id)
                .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                .where(Invoice.kind.in_((CC.INVOICE_SALE, CC.INVOICE_SALE_RETURN)),
                       Invoice.status == CC.STATUS_POSTED,
                       Invoice.invoice_date >= period.date_from,
                       Invoice.invoice_date <= period.date_to)).all()}
            stock = (select(Product.id, Product.code, Product.name_fa,
                            func.sum(StockBalance.quantity), func.sum(StockBalance.value))
                     .join(StockBalance, StockBalance.product_id == Product.id)
                     .where(Product.kind == CC.PRODUCT_GOODS)
                     .group_by(Product.id, Product.code, Product.name_fa)
                     .having(func.sum(StockBalance.quantity) > 0)
                     .order_by(func.sum(StockBalance.value).desc())
                     .limit(max(1, min(limit, 500))))
            rows = []
            for pid, code, name, qty, value in session.execute(stock).all():
                if pid in sold:
                    continue
                rows.append((f"{code} — {name}", Decimal(qty or 0),
                             Decimal(value or 0)))
            return ReportTable(
                key="slow_movers", title_fa="کالاهای کم‌گردش (بدون فروش در دوره)",
                columns=("کالا", "موجودی", "ارزش موجودی"), rows=tuple(rows),
                meta_fa=self._period_text(period))

    def discount_report(self, ctx: SecurityContext | None,
                        period: ReportPeriod) -> ReportTable:
        require_any(ctx, "sales.reports", "commerce.reports")
        with self.db.session_scope() as session:
            rows = []
            invoices = session.execute(
                select(Invoice).where(Invoice.kind.in_((CC.INVOICE_SALE,
                                                        CC.INVOICE_PURCHASE)),
                                      Invoice.status == CC.STATUS_POSTED,
                                      Invoice.invoice_date >= period.date_from,
                                      Invoice.invoice_date <= period.date_to)
                .order_by(Invoice.invoice_date)).scalars()
            for invoice in invoices:
                discount = invoice.line_discount + invoice.invoice_discount
                if discount == 0:
                    continue
                party = session.get(DetailAccount, invoice.party_detail_id)
                rows.append((invoice.number, invoice.invoice_date,
                             CC.INVOICE_TITLES_FA.get(invoice.kind, invoice.kind),
                             party.name if party else "", invoice.subtotal, discount,
                             invoice.net_total))
            return ReportTable(
                key="discounts", title_fa="گزارش تخفیف‌ها",
                columns=("شماره", "تاریخ", "نوع", "شخص", "جمع ردیف‌ها", "تخفیف",
                         "مبلغ خالص"),
                rows=tuple(rows), meta_fa=self._period_text(period))

    # -------------------------------------------------------------- inventory
    def stock_value(self, ctx: SecurityContext | None, *,
                    warehouse_id: int | None = None) -> ReportTable:
        require_any(ctx, "commerce.reports", "stock.view")
        with self.db.session_scope() as session:
            query = (select(Warehouse.title_fa, func.sum(StockBalance.quantity),
                            func.sum(StockBalance.value))
                     .join(StockBalance, StockBalance.warehouse_id == Warehouse.id)
                     .group_by(Warehouse.id, Warehouse.title_fa)
                     .order_by(Warehouse.title_fa))
            if warehouse_id:
                query = query.where(Warehouse.id == warehouse_id)
            rows = tuple((title, Decimal(qty or 0), Decimal(value or 0))
                         for title, qty, value in session.execute(query).all())
            total_qty = sum((r[1] for r in rows), ZERO)
            total_value = sum((r[2] for r in rows), ZERO)
            return ReportTable(
                key="stock_value", title_fa="ارزش موجودی به تفکیک انبار",
                columns=("انبار", "مقدار", "ارزش"),
                rows=rows + (("جمع کل", total_qty, total_value),))

    def low_stock(self, ctx: SecurityContext | None) -> ReportTable:
        require_any(ctx, "commerce.reports", "stock.view")
        with self.db.session_scope() as session:
            rows = []
            products = session.execute(
                select(Product).where(Product.kind == CC.PRODUCT_GOODS,
                                      Product.is_active.is_(True))
                .order_by(Product.code)).scalars()
            for product in products:
                quantity = Decimal(session.execute(
                    select(func.coalesce(func.sum(StockBalance.quantity), 0))
                    .where(StockBalance.product_id == product.id)).scalar() or 0)
                if product.reorder_point and quantity <= product.reorder_point:
                    rows.append((f"{product.code} — {product.name_fa}", quantity,
                                 product.reorder_point, product.max_stock))
            return ReportTable(
                key="low_stock", title_fa="کالاهای زیر نقطهٔ سفارش",
                columns=("کالا", "موجودی", "نقطهٔ سفارش", "حداکثر موجودی"),
                rows=tuple(rows))

    def idle_stock(self, ctx: SecurityContext | None, *, days: int = 180,
                   as_of: _dt.date | None = None) -> ReportTable:
        require_any(ctx, "commerce.reports", "stock.view")
        as_of = as_of or _dt.date.today()
        cutoff = as_of - _dt.timedelta(days=max(1, days))
        with self.db.session_scope() as session:
            moved = {pid for pid, in session.execute(
                select(StockDocumentLine.product_id)
                .join(StockDocument, StockDocument.id == StockDocumentLine.document_id)
                .where(StockDocument.status == CC.STATUS_POSTED,
                       StockDocument.doc_date > cutoff)).all()}
            query = (select(Product.id, Product.code, Product.name_fa,
                            func.sum(StockBalance.quantity), func.sum(StockBalance.value))
                     .join(StockBalance, StockBalance.product_id == Product.id)
                     .where(Product.kind == CC.PRODUCT_GOODS)
                     .group_by(Product.id, Product.code, Product.name_fa)
                     .having(func.sum(StockBalance.quantity) > 0)
                     .order_by(func.sum(StockBalance.value).desc()))
            rows = []
            for product_id, code, name, qty, value in session.execute(query).all():
                if product_id in moved:
                    continue
                rows.append((f"{code} — {name}", Decimal(qty or 0),
                             Decimal(value or 0)))
            return ReportTable(
                key="idle_stock",
                title_fa=f"کالاهای راکد (بدون گردش در {days} روز گذشته)",
                columns=("کالا", "موجودی", "ارزش"), rows=tuple(rows),
                meta_fa=f"تا تاریخ {as_of}")

    def transfers(self, ctx: SecurityContext | None,
                  period: ReportPeriod) -> ReportTable:
        require_any(ctx, "commerce.reports", "stock.view")
        with self.db.session_scope() as session:
            query = (select(StockDocument)
                     .where(StockDocument.kind == CC.MOVE_TRANSFER,
                            StockDocument.doc_date >= period.date_from,
                            StockDocument.doc_date <= period.date_to)
                     .order_by(StockDocument.doc_date))
            rows = tuple((doc.number, doc.doc_date,
                          doc.warehouse.title_fa if doc.warehouse else "",
                          doc.target_warehouse.title_fa if doc.target_warehouse else "",
                          len(doc.lines), doc.total_value,
                          CC.DOC_STATUS_TITLES_FA.get(doc.status, doc.status))
                         for doc in session.execute(query).scalars())
            return ReportTable(
                key="transfers", title_fa="انتقال‌های بین انبارها",
                columns=("شماره", "تاریخ", "مبدأ", "مقصد", "تعداد ردیف", "ارزش",
                         "وضعیت"), rows=rows, meta_fa=self._period_text(period))

    def count_discrepancies(self, ctx: SecurityContext | None,
                            period: ReportPeriod) -> ReportTable:
        require_any(ctx, "commerce.reports", "stock.count")
        with self.db.session_scope() as session:
            query = (select(StockCountSheet)
                     .where(StockCountSheet.count_date >= period.date_from,
                            StockCountSheet.count_date <= period.date_to)
                     .order_by(StockCountSheet.count_date))
            rows = []
            for sheet in session.execute(query).scalars():
                difference_value = sum((line.difference_value for line in sheet.lines),
                                       ZERO)
                changed = sum(1 for line in sheet.lines
                              if line.counted_quantity != line.system_quantity)
                rows.append((sheet.number, sheet.count_date, sheet.warehouse.title_fa,
                             CC.COUNT_STATUS_TITLES_FA.get(sheet.status, sheet.status),
                             changed, difference_value))
            return ReportTable(
                key="count_discrepancies", title_fa="مغایرت‌های انبارگردانی",
                columns=("شماره", "تاریخ", "انبار", "وضعیت", "ردیف مغایر", "ارزش مغایرت"),
                rows=tuple(rows), meta_fa=self._period_text(period))

    # ---------------------------------------------------------------- persons
    def person_balances(self, ctx: SecurityContext | None, *,
                        role: str = "customer") -> ReportTable:
        require_any(ctx, "commerce.reports", "sales.reports", "purchase.reports")
        with self.db.session_scope() as session:
            query = select(DetailAccount).where(
                DetailAccount.kind.in_((AC.DETAIL_CUSTOMER, AC.DETAIL_SUPPLIER)),
                DetailAccount.is_active.is_(True)).order_by(DetailAccount.code)
            if role == "customer":
                query = query.where(DetailAccount.is_customer.is_(True))
            elif role == "supplier":
                query = query.where(DetailAccount.is_supplier.is_(True))
            rows = []
            for detail in session.execute(query).scalars():
                debit, credit = session.execute(
                    select(func.coalesce(func.sum(JournalLine.debit), 0),
                           func.coalesce(func.sum(JournalLine.credit), 0))
                    .join(Journal, Journal.id == JournalLine.journal_id)
                    .where(JournalLine.detail_id == detail.id,
                           Journal.status.in_(AC.EFFECTIVE_STATUSES))).one()
                balance = Decimal(debit or 0) - Decimal(credit or 0)
                if balance == 0:
                    continue
                rows.append((f"{detail.code} — {detail.name}", detail.phone or "",
                             detail.credit_limit, balance))
            title = {"customer": "مانده حساب مشتریان (بدهکاران)",
                     "supplier": "مانده حساب تأمین‌کنندگان (بستانکاران)"}.get(
                         role, "مانده حساب اشخاص")
            return ReportTable(
                key=f"person_balances_{role}", title_fa=title,
                columns=("شخص", "تلفن", "سقف اعتبار", "مانده"), rows=tuple(rows))

    def person_turnover(self, ctx: SecurityContext | None,
                        period: ReportPeriod) -> ReportTable:
        require_any(ctx, "commerce.reports", "sales.reports", "purchase.reports")
        with self.db.session_scope() as session:
            query = (select(Invoice.party_detail_id, Invoice.kind,
                            func.sum(Invoice.net_total))
                     .where(Invoice.status == CC.STATUS_POSTED,
                            Invoice.invoice_date >= period.date_from,
                            Invoice.invoice_date <= period.date_to)
                     .group_by(Invoice.party_detail_id, Invoice.kind))
            totals: dict[int, dict[str, Decimal]] = {}
            for party_id, kind, value in session.execute(query).all():
                bucket = totals.setdefault(party_id, {})
                bucket[kind] = Decimal(value or 0)
            rows = []
            for party_id, kinds in totals.items():
                party = session.get(DetailAccount, party_id)
                if party is None:
                    continue
                rows.append((
                    f"{party.code} — {party.name}",
                    kinds.get(CC.INVOICE_PURCHASE, ZERO),
                    kinds.get(CC.INVOICE_PURCHASE_RETURN, ZERO),
                    kinds.get(CC.INVOICE_SALE, ZERO),
                    kinds.get(CC.INVOICE_SALE_RETURN, ZERO),
                ))
            rows.sort(key=lambda row: row[0])
            return ReportTable(
                key="person_turnover", title_fa="گردش خرید و فروش اشخاص",
                columns=("شخص", "خرید", "برگشت خرید", "فروش", "برگشت فروش"),
                rows=tuple(rows), meta_fa=self._period_text(period))

    # ------------------------------------------------------------- internals
    def _invoice_rows(self, session, kinds: tuple[str, ...], period: ReportPeriod,
                      warehouse_id: int | None) -> list[dict]:
        query = (select(Invoice).where(Invoice.kind.in_(kinds),
                                       Invoice.status == CC.STATUS_POSTED,
                                       Invoice.invoice_date >= period.date_from,
                                       Invoice.invoice_date <= period.date_to))
        if warehouse_id:
            query = query.where(Invoice.warehouse_id == warehouse_id)
        result = []
        for invoice in session.execute(query).scalars():
            party = session.get(DetailAccount, invoice.party_detail_id)
            category = ""
            if invoice.lines:
                product = session.get(Product, invoice.lines[0].product_id)
                if product is not None and product.category_id:
                    cat = session.get(ProductCategory, product.category_id)
                    category = cat.title_fa if cat else ""
            result.append({
                "date": invoice.invoice_date, "kind": invoice.kind,
                "party": party.name if party else "",
                "warehouse": (invoice.warehouse.title_fa if invoice.warehouse
                              else (session.get(Warehouse, invoice.warehouse_id).title_fa
                                    if invoice.warehouse_id else "")),
                "category": category,
                "net_total": invoice.net_total,
                "discount": invoice.line_discount + invoice.invoice_discount,
                "invoice_id": invoice.id,
            })
        return result

    def _by_product(self, ctx, period: ReportPeriod, kinds: tuple[str, ...],
                    title: str, key: str) -> ReportTable:
        with self.db.session_scope() as session:
            query = (select(Product.code, Product.name_fa,
                            func.sum(InvoiceLine.quantity),
                            func.sum(InvoiceLine.line_total),
                            func.sum(InvoiceLine.tax_amount),
                            func.sum(InvoiceLine.discount))
                     .join(InvoiceLine, InvoiceLine.product_id == Product.id)
                     .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                     .where(Invoice.kind.in_(kinds),
                            Invoice.status == CC.STATUS_POSTED,
                            Invoice.invoice_date >= period.date_from,
                            Invoice.invoice_date <= period.date_to)
                     .group_by(Product.id, Product.code, Product.name_fa)
                     .order_by(Product.code))
            rows = tuple((f"{code} — {name}", Decimal(qty or 0),
                          Decimal(net or 0) - Decimal(tax or 0), Decimal(discount or 0))
                         for code, name, qty, net, tax, discount in
                         session.execute(query).all())
            return ReportTable(key=key, title_fa=title,
                               columns=("کالا", "مقدار", "مبلغ خالص", "تخفیف"),
                               rows=rows, meta_fa=self._period_text(period))

    @staticmethod
    def _bucket_key(day: _dt.date, group_by: str, row: dict) -> str:
        if group_by == "daily":
            return str(day)
        if group_by == "yearly":
            return str(day.year)
        if group_by == "supplier" or group_by == "customer":
            return row["party"] or "—"
        if group_by == "warehouse":
            return row["warehouse"] or "—"
        if group_by == "category":
            return row.get("category") or row["party"] or "—"
        # monthly (default): Jalali year-month for a Persian-facing report
        from pars_erp.core.jalali import gregorian_to_jalali

        jy, jm, _ = gregorian_to_jalali(day)
        return f"{jy}/{jm:02d}"

    @staticmethod
    def _period_text(period: ReportPeriod) -> str:
        return f"از {period.date_from} تا {period.date_to}"
