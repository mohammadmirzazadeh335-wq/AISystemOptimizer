"""Qt-free accounting vocabulary shared by models, services and the UI.

Keeping every code string, Persian title and validation rule in one module means
the database layer, the business services and the screens cannot drift apart.
"""

from __future__ import annotations

from decimal import Decimal

# --------------------------------------------------------------------- levels
LEVEL_GROUP = "group"          # گروه حساب
LEVEL_TOTAL = "total"          # حساب کل
LEVEL_SUBSIDIARY = "subsidiary"  # حساب معین

ACCOUNT_LEVELS: tuple[str, ...] = (LEVEL_GROUP, LEVEL_TOTAL, LEVEL_SUBSIDIARY)

LEVEL_TITLES_FA: dict[str, str] = {
    LEVEL_GROUP: "گروه حساب",
    LEVEL_TOTAL: "حساب کل",
    LEVEL_SUBSIDIARY: "حساب معین",
}

#: Which level a parent may have for a given child level (root groups have none).
PARENT_LEVEL: dict[str, str | None] = {
    LEVEL_GROUP: None,
    LEVEL_TOTAL: LEVEL_GROUP,
    LEVEL_SUBSIDIARY: LEVEL_TOTAL,
}

# ---------------------------------------------------------------- account type
TYPE_ASSET = "asset"
TYPE_LIABILITY = "liability"
TYPE_EQUITY = "equity"
TYPE_REVENUE = "revenue"
TYPE_EXPENSE = "expense"

ACCOUNT_TYPES: tuple[str, ...] = (TYPE_ASSET, TYPE_LIABILITY, TYPE_EQUITY,
                                  TYPE_REVENUE, TYPE_EXPENSE)

TYPE_TITLES_FA: dict[str, str] = {
    TYPE_ASSET: "دارایی",
    TYPE_LIABILITY: "بدهی",
    TYPE_EQUITY: "سرمایه",
    TYPE_REVENUE: "درآمد",
    TYPE_EXPENSE: "هزینه",
}

#: Normal balance of each account type.
TYPE_NATURE: dict[str, str] = {
    TYPE_ASSET: "debit",
    TYPE_LIABILITY: "credit",
    TYPE_EQUITY: "credit",
    TYPE_REVENUE: "credit",
    TYPE_EXPENSE: "debit",
}

NATURE_DEBIT = "debit"
NATURE_CREDIT = "credit"
NATURES: tuple[str, ...] = (NATURE_DEBIT, NATURE_CREDIT)
NATURE_TITLES_FA: dict[str, str] = {NATURE_DEBIT: "بدهکار", NATURE_CREDIT: "بستانکار"}

#: Account types allowed per statement section.
BALANCE_SHEET_SECTIONS: tuple[str, ...] = (
    "current_assets", "non_current_assets", "current_liabilities",
    "non_current_liabilities", "equity",
)
INCOME_SECTIONS: tuple[str, ...] = (
    "revenue", "cogs", "operating_expense", "other_income", "other_expense",
)

SECTION_TITLES_FA: dict[str, str] = {
    "current_assets": "دارایی‌های جاری",
    "non_current_assets": "دارایی‌های غیرجاری",
    "current_liabilities": "بدهی‌های جاری",
    "non_current_liabilities": "بدهی‌های غیرجاری",
    "equity": "سرمایه",
    "revenue": "درآمدها",
    "cogs": "بهای تمام‌شده کالای فروش‌رفته",
    "operating_expense": "هزینه‌های عملیاتی",
    "other_income": "سایر درآمدها",
    "other_expense": "سایر هزینه‌ها",
}

#: Sections each account type may be mapped to.
SECTIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    TYPE_ASSET: ("current_assets", "non_current_assets"),
    TYPE_LIABILITY: ("current_liabilities", "non_current_liabilities"),
    TYPE_EQUITY: ("equity",),
    TYPE_REVENUE: ("revenue", "other_income"),
    TYPE_EXPENSE: ("cogs", "operating_expense", "other_expense"),
}

DEFAULT_SECTION_BY_TYPE: dict[str, str] = {
    TYPE_ASSET: "current_assets",
    TYPE_LIABILITY: "current_liabilities",
    TYPE_EQUITY: "equity",
    TYPE_REVENUE: "revenue",
    TYPE_EXPENSE: "operating_expense",
}

# ------------------------------------------------------------- journal status
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_POSTED = "posted"
STATUS_VOID = "void"

JOURNAL_STATUSES: tuple[str, ...] = (STATUS_DRAFT, STATUS_PENDING, STATUS_APPROVED,
                                     STATUS_POSTED, STATUS_VOID)

STATUS_TITLES_FA: dict[str, str] = {
    STATUS_DRAFT: "پیش‌نویس",
    STATUS_PENDING: "در انتظار تأیید",
    STATUS_APPROVED: "تأییدشده",
    STATUS_POSTED: "ثبت نهایی",
    STATUS_VOID: "باطل‌شده",
}

# Document kinds -------------------------------------------------------------
KIND_NORMAL = "normal"
KIND_OPENING = "opening"
KIND_CLOSING = "closing"
JOURNAL_KINDS: tuple[str, ...] = (KIND_NORMAL, KIND_OPENING, KIND_CLOSING)
KIND_TITLES_FA: dict[str, str] = {
    KIND_NORMAL: "عادی",
    KIND_OPENING: "افتتاحیه",
    KIND_CLOSING: "اختتامیه",
}

#: Statuses whose lines count for balances and reports.
EFFECTIVE_STATUSES: tuple[str, ...] = (STATUS_POSTED,)

#: Allowed forward transitions of the document workflow.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_PENDING,),
    STATUS_PENDING: (STATUS_APPROVED, STATUS_DRAFT),
    STATUS_APPROVED: (STATUS_POSTED, STATUS_PENDING),
    STATUS_POSTED: (STATUS_VOID,),
    STATUS_VOID: (),
}

EDITABLE_STATUSES: tuple[str, ...] = (STATUS_DRAFT,)

# ------------------------------------------------------------------- periods
PERIOD_OPEN = "open"
PERIOD_CLOSED = "closed"
PERIOD_TITLES_FA: dict[str, str] = {PERIOD_OPEN: "باز", PERIOD_CLOSED: "بسته"}

# ------------------------------------------------------------------- details
DETAIL_CUSTOMER = "customer"
DETAIL_SUPPLIER = "supplier"
DETAIL_EMPLOYEE = "employee"
DETAIL_BANK = "bank"
DETAIL_CASHBOX = "cashbox"
DETAIL_OTHER = "other"

DETAIL_KINDS: tuple[str, ...] = (DETAIL_CUSTOMER, DETAIL_SUPPLIER, DETAIL_EMPLOYEE,
                                 DETAIL_BANK, DETAIL_CASHBOX, DETAIL_OTHER)

DETAIL_KIND_TITLES_FA: dict[str, str] = {
    DETAIL_CUSTOMER: "مشتری",
    DETAIL_SUPPLIER: "تأمین‌کننده",
    DETAIL_EMPLOYEE: "کارمند",
    DETAIL_BANK: "بانک",
    DETAIL_CASHBOX: "صندوق",
    DETAIL_OTHER: "سایر",
}

# ------------------------------------------------------------------- projects
PROJECT_ACTIVE = "active"
PROJECT_CLOSED = "closed"
PROJECT_STATUS_TITLES_FA: dict[str, str] = {
    PROJECT_ACTIVE: "در جریان",
    PROJECT_CLOSED: "بسته‌شده",
}

# --------------------------------------------------------------------- limits
CODE_MAX_LENGTH = 32
TITLE_MAX_LENGTH = 160
ZERO = Decimal("0")

#: Default reporting dimension flags; dimensions are optional by design.
DIMENSION_OPTIONAL_NOTE_FA = (
    "مرکز هزینه و پروژه اختیاری هستند و نبود آن‌ها مانع ثبت سند نمی‌شود."
)


def section_titles_for(account_type: str) -> tuple[tuple[str, str], ...]:
    """``(code, title)`` pairs the UI offers for an account type."""
    return tuple((code, SECTION_TITLES_FA[code])
                 for code in SECTIONS_BY_TYPE.get(account_type, ()))


def statement_of_section(section: str) -> str:
    return "income_statement" if section in INCOME_SECTIONS else "balance_sheet"
