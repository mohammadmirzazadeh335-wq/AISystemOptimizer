"""Pure commerce vocabulary for phase 3: catalogue, stock, purchase and sale.

No Qt, no SQLAlchemy - exactly like :mod:`pars_erp.accounting.constants`, so the
rules can be unit-tested and reused by services, the CLI and the UI.
"""

from __future__ import annotations

# ----------------------------------------------------------------- products
PRODUCT_GOODS = "goods"
PRODUCT_SERVICE = "service"
PRODUCT_KINDS: tuple[str, ...] = (PRODUCT_GOODS, PRODUCT_SERVICE)
PRODUCT_KIND_TITLES_FA: dict[str, str] = {
    PRODUCT_GOODS: "کالا",
    PRODUCT_SERVICE: "خدمت",
}

# --------------------------------------------------------------- categories
CATEGORY_MAX_DEPTH = 4

# -------------------------------------------------------------------- units
UNIT_KINDS: tuple[tuple[str, str], ...] = (
    ("count", "عدد"),
    ("kilogram", "کیلوگرم"),
    ("gram", "گرم"),
    ("meter", "متر"),
    ("centimeter", "سانتی‌متر"),
    ("liter", "لیتر"),
    ("pack", "بسته"),
    ("carton", "کارتن"),
    ("box", "جعبه"),
    ("other", "سایر"),
)
UNIT_KIND_TITLES_FA: dict[str, str] = dict(UNIT_KINDS)

# ------------------------------------------------------------------ parties
PERSON_LEGAL = "legal"
PERSON_REAL = "real"
PERSON_TYPES: tuple[str, ...] = (PERSON_REAL, PERSON_LEGAL)
PERSON_TYPE_TITLES_FA: dict[str, str] = {
    PERSON_REAL: "حقیقی",
    PERSON_LEGAL: "حقوقی",
}

# -------------------------------------------------------------------- stock
MOVE_RECEIPT = "receipt"          # رسید انبار (in)
MOVE_ISSUE = "issue"              # حواله انبار (out)
MOVE_TRANSFER = "transfer"        # انتقال بین انبارها
MOVE_ADJUSTMENT = "adjustment"    # اصلاح موجودی
MOVE_COUNT = "count"              # اصلاح ناشی از انبارگردانی
STOCK_MOVE_KINDS: tuple[str, ...] = (MOVE_RECEIPT, MOVE_ISSUE, MOVE_TRANSFER,
                                     MOVE_ADJUSTMENT, MOVE_COUNT)
STOCK_MOVE_TITLES_FA: dict[str, str] = {
    MOVE_RECEIPT: "رسید انبار",
    MOVE_ISSUE: "حواله انبار",
    MOVE_TRANSFER: "انتقال بین انبارها",
    MOVE_ADJUSTMENT: "اصلاح موجودی",
    MOVE_COUNT: "اصلاح انبارگردانی",
}

#: Which document kinds add stock (+) and which remove it (-).
MOVE_DIRECTION: dict[str, int] = {
    MOVE_RECEIPT: 1,
    MOVE_ISSUE: -1,
    MOVE_TRANSFER: 0,   # handled per side
    MOVE_ADJUSTMENT: 0,  # sign comes from the line quantity
    MOVE_COUNT: 0,
}

# ------------------------------------------------------- valuation policies
VALUATION_AVERAGE = "average"
VALUATION_FIFO = "fifo"
VALUATION_METHODS: tuple[str, ...] = (VALUATION_AVERAGE, VALUATION_FIFO)
VALUATION_TITLES_FA: dict[str, str] = {
    VALUATION_AVERAGE: "میانگین موزون",
    VALUATION_FIFO: "اولین صادره از اولین وارده (FIFO)",
}

# ----------------------------------------------------------------- invoices
INVOICE_PURCHASE = "purchase"
INVOICE_SALE = "sale"
INVOICE_PURCHASE_RETURN = "purchase_return"
INVOICE_SALE_RETURN = "sale_return"
INVOICE_KINDS: tuple[str, ...] = (INVOICE_PURCHASE, INVOICE_SALE,
                                  INVOICE_PURCHASE_RETURN, INVOICE_SALE_RETURN)
INVOICE_TITLES_FA: dict[str, str] = {
    INVOICE_PURCHASE: "فاکتور خرید",
    INVOICE_SALE: "فاکتور فروش",
    INVOICE_PURCHASE_RETURN: "برگشت از خرید",
    INVOICE_SALE_RETURN: "برگشت از فروش",
}
INVOICE_PREFIX: dict[str, str] = {
    INVOICE_PURCHASE: "PUR",
    INVOICE_SALE: "SAL",
    INVOICE_PURCHASE_RETURN: "PRT",
    INVOICE_SALE_RETURN: "SRT",
}


def invoice_moves_stock_in(kind: str) -> bool:
    """Purchase invoices and sales returns put goods *into* the warehouse."""
    return kind in (INVOICE_PURCHASE, INVOICE_SALE_RETURN)


def invoice_moves_stock_out(kind: str) -> bool:
    return kind in (INVOICE_SALE, INVOICE_PURCHASE_RETURN)


def invoice_is_return(kind: str) -> bool:
    return kind in (INVOICE_PURCHASE_RETURN, INVOICE_SALE_RETURN)


# ---------------------------------------------------------- shared workflow
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_POSTED = "posted"
STATUS_VOID = "void"
DOC_STATUSES: tuple[str, ...] = (STATUS_DRAFT, STATUS_PENDING, STATUS_APPROVED,
                                 STATUS_POSTED, STATUS_VOID)
DOC_STATUS_TITLES_FA: dict[str, str] = {
    STATUS_DRAFT: "پیش‌نویس",
    STATUS_PENDING: "در انتظار تأیید",
    STATUS_APPROVED: "تأییدشده",
    STATUS_POSTED: "ثبت نهایی",
    STATUS_VOID: "باطل‌شده",
}
EDITABLE_STATUSES: tuple[str, ...] = (STATUS_DRAFT,)
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    # a draft may go straight to posted (posting without the approval step) or
    # through the approval workflow; approved documents may only be posted.
    STATUS_DRAFT: (STATUS_PENDING, STATUS_APPROVED, STATUS_POSTED),
    STATUS_PENDING: (STATUS_APPROVED, STATUS_DRAFT),
    STATUS_APPROVED: (STATUS_POSTED, STATUS_PENDING),
    STATUS_POSTED: (STATUS_VOID,),
    STATUS_VOID: (),
}

# --------------------------------------------------------------- order flow
ORDER_PURCHASE_REQUEST = "purchase_request"
ORDER_PURCHASE = "purchase_order"
ORDER_SALES = "sales_order"
ORDER_KINDS: tuple[str, ...] = (ORDER_PURCHASE_REQUEST, ORDER_PURCHASE, ORDER_SALES)
ORDER_TITLES_FA: dict[str, str] = {
    ORDER_PURCHASE_REQUEST: "درخواست خرید",
    ORDER_PURCHASE: "سفارش خرید",
    ORDER_SALES: "سفارش فروش",
}
ORDER_PREFIX: dict[str, str] = {
    ORDER_PURCHASE_REQUEST: "PRQ",
    ORDER_PURCHASE: "PO",
    ORDER_SALES: "SO",
}

ORDER_STATUS_DRAFT = "draft"
ORDER_STATUS_SUBMITTED = "submitted"
ORDER_STATUS_PENDING_APPROVAL = "pending_approval"
ORDER_STATUS_APPROVED = "approved"
ORDER_STATUS_IN_PROGRESS = "in_progress"
ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUSES: tuple[str, ...] = (
    ORDER_STATUS_DRAFT, ORDER_STATUS_SUBMITTED, ORDER_STATUS_PENDING_APPROVAL,
    ORDER_STATUS_APPROVED, ORDER_STATUS_IN_PROGRESS, ORDER_STATUS_COMPLETED,
    ORDER_STATUS_CANCELLED,
)
ORDER_STATUS_TITLES_FA: dict[str, str] = {
    ORDER_STATUS_DRAFT: "پیش‌نویس",
    ORDER_STATUS_SUBMITTED: "ثبت‌شده",
    ORDER_STATUS_PENDING_APPROVAL: "در انتظار تأیید",
    ORDER_STATUS_APPROVED: "تأییدشده",
    ORDER_STATUS_IN_PROGRESS: "در حال انجام",
    ORDER_STATUS_COMPLETED: "تکمیل‌شده",
    ORDER_STATUS_CANCELLED: "لغوشده",
}
ORDER_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ORDER_STATUS_DRAFT: (ORDER_STATUS_SUBMITTED, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_SUBMITTED: (ORDER_STATUS_PENDING_APPROVAL, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_PENDING_APPROVAL: (ORDER_STATUS_APPROVED, ORDER_STATUS_SUBMITTED,
                                    ORDER_STATUS_CANCELLED),
    ORDER_STATUS_APPROVED: (ORDER_STATUS_IN_PROGRESS, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_IN_PROGRESS: (ORDER_STATUS_COMPLETED, ORDER_STATUS_CANCELLED),
    ORDER_STATUS_COMPLETED: (),
    ORDER_STATUS_CANCELLED: (),
}

# ------------------------------------------------------------ price lists
PRICE_LIST_RETAIL = "retail"
PRICE_LIST_WHOLESALE = "wholesale"
PRICE_LIST_SPECIAL = "special"
PRICE_LIST_SEASONAL = "seasonal"
PRICE_LIST_KINDS: tuple[str, ...] = (PRICE_LIST_RETAIL, PRICE_LIST_WHOLESALE,
                                     PRICE_LIST_SPECIAL, PRICE_LIST_SEASONAL)
PRICE_LIST_TITLES_FA: dict[str, str] = {
    PRICE_LIST_RETAIL: "خرده‌فروشی",
    PRICE_LIST_WHOLESALE: "عمده",
    PRICE_LIST_SPECIAL: "ویژه مشتری",
    PRICE_LIST_SEASONAL: "مناسبتی",
}

# --------------------------------------------------------- posting (حسابداری)
#: Every commerce operation that can generate an accounting document.
POSTING_PURCHASE = "purchase"
POSTING_SALE = "sale"
POSTING_PURCHASE_RETURN = "purchase_return"
POSTING_SALE_RETURN = "sale_return"
POSTING_GOODS_RECEIPT = "goods_receipt"
POSTING_GOODS_ISSUE = "goods_issue"
POSTING_COUNT_ADJUSTMENT = "count_adjustment"
POSTING_OPERATIONS: tuple[str, ...] = (
    POSTING_PURCHASE, POSTING_SALE, POSTING_PURCHASE_RETURN, POSTING_SALE_RETURN,
    POSTING_GOODS_RECEIPT, POSTING_GOODS_ISSUE, POSTING_COUNT_ADJUSTMENT,
)
POSTING_TITLES_FA: dict[str, str] = {
    POSTING_PURCHASE: "خرید کالا",
    POSTING_SALE: "فروش کالا",
    POSTING_PURCHASE_RETURN: "برگشت از خرید",
    POSTING_SALE_RETURN: "برگشت از فروش",
    POSTING_GOODS_RECEIPT: "رسید انبار",
    POSTING_GOODS_ISSUE: "حواله انبار",
    POSTING_COUNT_ADJUSTMENT: "اصلاح موجودی انبارگردانی",
}

#: Amount sources a posting rule line may reference.
SRC_NET = "net"                 # مبلغ خالص فاکتور
SRC_SUBTOTAL = "subtotal"       # جمع ردیف‌ها پیش از تخفیف/مالیات
SRC_DISCOUNT = "discount"       # جمع تخفیف‌ها
SRC_TAX = "tax"                 # جمع مالیات و عوارض
SRC_CHARGES = "charges"         # هزینه‌های جانبی
SRC_COGS = "cogs"               # بهای تمام‌شده کالای فروش‌رفته
SRC_INVENTORY_VALUE = "inventory"  # ارزش موجودی (رسید/حواله)
SRC_ADJUSTMENT_VALUE = "adjustment"  # ارزش اختلاف انبارگردانی
AMOUNT_SOURCES: tuple[str, ...] = (SRC_NET, SRC_SUBTOTAL, SRC_DISCOUNT, SRC_TAX,
                                   SRC_CHARGES, SRC_COGS, SRC_INVENTORY_VALUE,
                                   SRC_ADJUSTMENT_VALUE)
AMOUNT_SOURCE_TITLES_FA: dict[str, str] = {
    SRC_NET: "مبلغ خالص",
    SRC_SUBTOTAL: "جمع ردیف‌ها",
    SRC_DISCOUNT: "تخفیف",
    SRC_TAX: "مالیات و عوارض",
    SRC_CHARGES: "هزینه‌های جانبی",
    SRC_COGS: "بهای تمام‌شده",
    SRC_INVENTORY_VALUE: "ارزش موجودی",
    SRC_ADJUSTMENT_VALUE: "ارزش اختلاف شمارش",
}

SIDE_DEBIT = "debit"
SIDE_CREDIT = "credit"
SIDES: tuple[str, ...] = (SIDE_DEBIT, SIDE_CREDIT)
SIDE_TITLES_FA: dict[str, str] = {SIDE_DEBIT: "بدهکار", SIDE_CREDIT: "بستانکار"}

# -------------------------------------------------------------- stock counts
COUNT_STATUS_DRAFT = "draft"
COUNT_STATUS_COUNTING = "counting"
COUNT_STATUS_APPROVED = "approved"
COUNT_STATUS_POSTED = "posted"
COUNT_STATUS_TITLES_FA: dict[str, str] = {
    COUNT_STATUS_DRAFT: "پیش‌نویس",
    COUNT_STATUS_COUNTING: "در حال شمارش",
    COUNT_STATUS_APPROVED: "تأییدشده",
    COUNT_STATUS_POSTED: "ثبت نهایی",
}

# ------------------------------------------------------------- policies/settings
SETTING_VALUATION_METHOD = "inventory_valuation_method"
SETTING_ALLOW_NEGATIVE_STOCK = "inventory_allow_negative_stock"
SETTING_NEGATIVE_STOCK_WAREHOUSE = "inventory_negative_stock_warehouses"
SETTING_DEFAULT_TAX_PERCENT = "sales_default_tax_percent"
