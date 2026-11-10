"""Phase-4 treasury constants: funds, vouchers, cheques and posting operations.

Nothing here is a legal/regulatory rate: every amount that a document posts comes
from the document itself, and every account comes from the company's own chart
through :class:`pars_erp.services.posting_service.PostingService`.
"""

from __future__ import annotations

# --------------------------------------------------------------------- funds
FUND_CASH = "cash"
FUND_BANK = "bank"
FUND_CHEQUE = "cheque"
FUND_KINDS: tuple[tuple[str, str], ...] = (
    (FUND_CASH, "صندوق نقدی"),
    (FUND_BANK, "حساب بانکی"),
    (FUND_CHEQUE, "چک"),
)
FUND_TITLES_FA: dict[str, str] = dict(FUND_KINDS)

#: chart codes the treasury links to by default; a fund may always point at any
#: subsidiary account of the company's own chart instead (``account_id``)
DEFAULT_CASH_PARENT_CODE = "101005"
DEFAULT_BANK_PARENT_CODE = "101006"
CHEQUE_IN_HAND_CODE = "101007"
CHEQUE_PAYABLE_CODE = "201004"

# --------------------------------------------------------------- documents
STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_POSTED = "posted"
STATUS_VOID = "void"
STATUS_TITLES_FA: dict[str, str] = {
    STATUS_DRAFT: "پیش‌نویس",
    STATUS_APPROVED: "تأییدشده",
    STATUS_POSTED: "ثبت نهایی‌شده",
    STATUS_VOID: "ابطال‌شده",
}
STATUSES: tuple[str, ...] = (STATUS_DRAFT, STATUS_APPROVED, STATUS_POSTED, STATUS_VOID)
# A transfer is an internal move of the company's own money between two funds:
# there is no third party and no invoice involved, so it needs no separate
# approval step and may be posted straight from the draft.
TRANSFER_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_POSTED, STATUS_VOID),
    STATUS_POSTED: (STATUS_VOID,),
    STATUS_VOID: (),
}
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_APPROVED, STATUS_VOID),
    STATUS_APPROVED: (STATUS_POSTED, STATUS_DRAFT, STATUS_VOID),
    STATUS_POSTED: (STATUS_VOID,),
    STATUS_VOID: (),
}

# ------------------------------------------------------------------ receipts
RECEIPT_CUSTOMER = "customer"
RECEIPT_OTHER = "other"
RECEIPT_ADVANCE = "advance"
RECEIPT_TYPES: tuple[tuple[str, str], ...] = (
    (RECEIPT_CUSTOMER, "دریافت از مشتری"),
    (RECEIPT_OTHER, "دریافت متفرقه"),
    (RECEIPT_ADVANCE, "پیش‌دریافت"),
)
RECEIPT_TYPE_TITLES_FA: dict[str, str] = dict(RECEIPT_TYPES)

METHOD_CASH = "cash"
METHOD_CARD = "card"
METHOD_TRANSFER = "transfer"
METHOD_CHEQUE = "cheque"
METHOD_OTHER = "other"
RECEIPT_METHODS: tuple[tuple[str, str], ...] = (
    (METHOD_CASH, "نقدی"),
    (METHOD_CARD, "کارت‌خوان"),
    (METHOD_TRANSFER, "انتقال بانکی"),
    (METHOD_CHEQUE, "چک"),
    (METHOD_OTHER, "سایر"),
)
RECEIPT_METHOD_TITLES_FA: dict[str, str] = dict(RECEIPT_METHODS)

# ------------------------------------------------------------------ payments
PAYMENT_SUPPLIER = "supplier"
PAYMENT_SALARY = "salary"
PAYMENT_EXPENSE = "expense"
PAYMENT_OTHER = "other"
PAYMENT_ADVANCE = "advance"
PAYMENT_TYPES: tuple[tuple[str, str], ...] = (
    (PAYMENT_SUPPLIER, "پرداخت به تأمین‌کننده"),
    (PAYMENT_SALARY, "پرداخت حقوق"),
    (PAYMENT_EXPENSE, "پرداخت هزینه"),
    (PAYMENT_ADVANCE, "پیش‌پرداخت"),
    (PAYMENT_OTHER, "پرداخت متفرقه"),
)
PAYMENT_TYPE_TITLES_FA: dict[str, str] = dict(PAYMENT_TYPES)

PAYMENT_METHODS: tuple[tuple[str, str], ...] = (
    (METHOD_CASH, "نقدی"),
    (METHOD_TRANSFER, "حساب بانکی"),
    (METHOD_CHEQUE, "چک"),
    (METHOD_CARD, "کارت‌خوان"),
    (METHOD_OTHER, "سایر"),
)
PAYMENT_METHOD_TITLES_FA: dict[str, str] = dict(PAYMENT_METHODS)

# ------------------------------------------------------------------- cheques
CHEQUE_RECEIVED = "received"
CHEQUE_ISSUED = "issued"
CHEQUE_DIRECTIONS: tuple[tuple[str, str], ...] = (
    (CHEQUE_RECEIVED, "چک دریافتی"),
    (CHEQUE_ISSUED, "چک پرداختی"),
)
CHEQUE_DIRECTION_TITLES_FA: dict[str, str] = dict(CHEQUE_DIRECTIONS)

#: received-cheque lifecycle
CHQ_RECEIVED = "received"
CHQ_IN_SAFE = "in_safe"
CHQ_DEPOSITED = "deposited"
CHQ_COLLECTED = "collected"
CHQ_BOUNCED = "bounced"
CHQ_SPENT = "spent"
CHQ_TRANSFERRED = "transferred"
CHQ_CANCELLED = "cancelled"

#: issued-cheque lifecycle (draft..cancelled)
CHQ_DRAFT = "draft"
CHQ_ISSUED = "issued"
CHQ_DELIVERED = "delivered"
CHQ_PENDING = "pending"
CHQ_PAID = "paid"
CHQ_RETURNED = "returned"

CHEQUE_STATUSES: tuple[tuple[str, str], ...] = (
    (CHQ_RECEIVED, "دریافت‌شده"),
    (CHQ_IN_SAFE, "نزد صندوق"),
    (CHQ_DEPOSITED, "واگذارشده به بانک"),
    (CHQ_COLLECTED, "وصول‌شده"),
    (CHQ_BOUNCED, "برگشت‌خورده"),
    (CHQ_SPENT, "خرج‌شده"),
    (CHQ_TRANSFERRED, "منتقل‌شده"),
    (CHQ_DRAFT, "پیش‌نویس"),
    (CHQ_ISSUED, "صادرشده"),
    (CHQ_DELIVERED, "تحویل‌شده"),
    (CHQ_PENDING, "در انتظار وصول"),
    (CHQ_PAID, "وصول‌شده (پرداخت)"),
    (CHQ_RETURNED, "برگشت‌خورده (پرداخت)"),
    (CHQ_CANCELLED, "باطل‌شده"),
)
CHEQUE_STATUS_TITLES_FA: dict[str, str] = dict(CHEQUE_STATUSES)

RECEIVED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    CHQ_RECEIVED: (CHQ_IN_SAFE, CHQ_DEPOSITED, CHQ_SPENT, CHQ_TRANSFERRED, CHQ_CANCELLED),
    CHQ_IN_SAFE: (CHQ_DEPOSITED, CHQ_SPENT, CHQ_TRANSFERRED, CHQ_CANCELLED),
    CHQ_DEPOSITED: (CHQ_COLLECTED, CHQ_BOUNCED),
    CHQ_COLLECTED: (),
    CHQ_BOUNCED: (CHQ_IN_SAFE, CHQ_CANCELLED),
    CHQ_SPENT: (),
    CHQ_TRANSFERRED: (),
    CHQ_CANCELLED: (),
}
ISSUED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    CHQ_DRAFT: (CHQ_ISSUED, CHQ_CANCELLED),
    CHQ_ISSUED: (CHQ_DELIVERED, CHQ_CANCELLED),
    CHQ_DELIVERED: (CHQ_PENDING, CHQ_PAID, CHQ_RETURNED),
    CHQ_PENDING: (CHQ_PAID, CHQ_RETURNED),
    CHQ_PAID: (),
    CHQ_RETURNED: (CHQ_CANCELLED,),
    CHQ_CANCELLED: (),
}

#: statuses that still represent money owed to us / by us (for dashboards)
RECEIVED_OPEN_STATUSES: tuple[str, ...] = (CHQ_RECEIVED, CHQ_IN_SAFE, CHQ_DEPOSITED)
ISSUED_OPEN_STATUSES: tuple[str, ...] = (CHQ_DRAFT, CHQ_ISSUED, CHQ_DELIVERED, CHQ_PENDING)

# --------------------------------------------------------------- cheque books
BOOK_ACTIVE = "active"
BOOK_FINISHED = "finished"
BOOK_CANCELLED = "cancelled"
BOOK_STATUSES: tuple[tuple[str, str], ...] = (
    (BOOK_ACTIVE, "در جریان"),
    (BOOK_FINISHED, "پایان‌یافته"),
    (BOOK_CANCELLED, "باطل‌شده"),
)
BOOK_STATUS_TITLES_FA: dict[str, str] = dict(BOOK_STATUSES)

LEAF_FREE = "free"
LEAF_USED = "used"
LEAF_VOID = "void"

# ----------------------------------------------------------- reconciliation
RECON_OPEN = "open"
RECON_MATCHED = "matched"
RECON_CLOSED = "closed"
RECON_STATUSES: tuple[tuple[str, str], ...] = (
    (RECON_OPEN, "در جریان"),
    (RECON_MATCHED, "تطبیق‌شده"),
    (RECON_CLOSED, "بسته‌شده"),
)
RECON_STATUS_TITLES_FA: dict[str, str] = dict(RECON_STATUSES)

LINE_UNMATCHED = "unmatched"
LINE_MATCHED = "matched"
LINE_IGNORED = "ignored"
LINE_STATUS_TITLES_FA: dict[str, str] = {
    LINE_UNMATCHED: "تطبیق‌نشده",
    LINE_MATCHED: "تطبیق‌شده",
    LINE_IGNORED: "نادیده گرفته‌شده",
}

# ------------------------------------------------------------------ calendar
PLAN_CHEQUE_RECEIVED = "cheque_received"
PLAN_CHEQUE_ISSUED = "cheque_issued"
PLAN_PAYMENT = "payment_planned"
PLAN_INVOICE_DUE = "invoice_due"

# ------------------------------------------------------- posting operations
POSTING_RECEIPT_CASH = "treasury.receipt_cash"
POSTING_RECEIPT_BANK = "treasury.receipt_bank"
POSTING_RECEIPT_CHEQUE = "treasury.receipt_cheque"
POSTING_PAYMENT_CASH = "treasury.payment_cash"
POSTING_PAYMENT_BANK = "treasury.payment_bank"
POSTING_PAYMENT_CHEQUE = "treasury.payment_cheque"
POSTING_CHEQUE_COLLECTED = "treasury.cheque_collected"
POSTING_CHEQUE_BOUNCED = "treasury.cheque_bounced"
POSTING_CHEQUE_CLEARED = "treasury.cheque_cleared"
POSTING_TRANSFER = "treasury.transfer"
POSTING_BANK_FEE = "treasury.bank_fee"

POSTING_OPERATIONS: tuple[str, ...] = (
    POSTING_RECEIPT_CASH, POSTING_RECEIPT_BANK, POSTING_RECEIPT_CHEQUE,
    POSTING_PAYMENT_CASH, POSTING_PAYMENT_BANK, POSTING_PAYMENT_CHEQUE,
    POSTING_CHEQUE_COLLECTED, POSTING_CHEQUE_BOUNCED, POSTING_CHEQUE_CLEARED,
    POSTING_TRANSFER, POSTING_BANK_FEE,
)
POSTING_TITLES_FA: dict[str, str] = {
    POSTING_RECEIPT_CASH: "دریافت نقدی",
    POSTING_RECEIPT_BANK: "دریافت بانکی",
    POSTING_RECEIPT_CHEQUE: "دریافت چک",
    POSTING_PAYMENT_CASH: "پرداخت نقدی",
    POSTING_PAYMENT_BANK: "پرداخت بانکی",
    POSTING_PAYMENT_CHEQUE: "صدور چک",
    POSTING_CHEQUE_COLLECTED: "وصول چک دریافتی",
    POSTING_CHEQUE_BOUNCED: "برگشت چک دریافتی",
    POSTING_CHEQUE_CLEARED: "وصول چک پرداختی",
    POSTING_TRANSFER: "انتقال وجه",
    POSTING_BANK_FEE: "کارمزد بانکی",
}

# ----------------------------------------------------------- amount sources
SRC_AMOUNT = "amount"
SRC_FEE = "fee"
SRC_FUND = "fund"
SRC_FUND_FROM = "fund_from"
SRC_FUND_TO = "fund_to"

AMOUNT_SOURCES: tuple[str, ...] = (SRC_AMOUNT, SRC_FEE, SRC_FUND, SRC_FUND_FROM,
                                   SRC_FUND_TO)
AMOUNT_SOURCE_TITLES_FA: dict[str, str] = {
    SRC_AMOUNT: "مبلغ سند",
    SRC_FEE: "کارمزد",
    SRC_FUND: "مبلغ سند از حساب صندوق/بانک",
    SRC_FUND_FROM: "مبلغ از حساب مبدأ",
    SRC_FUND_TO: "مبلغ به حساب مقصد",
}
#: rule lines using these sources get their account from the document, not the rule
DYNAMIC_SOURCES: tuple[str, ...] = (SRC_FUND, SRC_FUND_FROM, SRC_FUND_TO)

# ------------------------------------------------------------- report kinds
REPORT_BANK_LEDGER = "bank_ledger"
REPORT_BANK_BALANCE = "bank_balance"
REPORT_CASH_LEDGER = "cash_ledger"
REPORT_CASH_BALANCE = "cash_balance"
REPORT_CHEQUES_RECEIVED = "cheques_received"
REPORT_CHEQUES_ISSUED = "cheques_issued"
REPORT_CHEQUES_DUE = "cheques_due"
REPORT_CHEQUES_BOUNCED = "cheques_bounced"
REPORT_PERSON_RECEIPTS = "person_receipts"
REPORT_PERSON_PAYMENTS = "person_payments"
REPORT_OPEN_INVOICES = "open_invoices"
REPORT_CASH_FLOW = "cash_flow"
REPORT_FORECAST = "cash_forecast"
