"""Authorisation catalogue and the enforcement primitives.

Design rules (see docs/ARCHITECTURE.md):

* permissions are *codes* such as ``users.reset_password``;
* the UI uses the catalogue only to hide/disable controls - the **service layer
  enforces** every check through :func:`require_permission`, so calling a service
  directly (tests, scripts, a future internal API) cannot bypass authorisation;
* the catalogue is code, not user data: administrators assign permissions to
  roles, but cannot invent new codes;
* phase 1 catalogues only the capabilities that actually exist. Accounting,
  inventory, treasury, payroll, ... sections are added by their own phases, so no
  dead permissions are shipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from pars_erp.core.errors import PermissionDeniedError


@dataclass(frozen=True)
class PermissionDef:
    code: str
    title_fa: str
    section: str
    section_title_fa: str
    action: str
    sort_order: int

    @property
    def description_fa(self) -> str:
        return f"{self.section_title_fa} - {self.title_fa}"


@dataclass(frozen=True)
class PermissionSection:
    code: str
    title_fa: str
    permissions: tuple[PermissionDef, ...] = field(default_factory=tuple)


def _perm(code: str, action: str, title_fa: str, section: str, section_title: str,
          order: int) -> PermissionDef:
    return PermissionDef(code=code, title_fa=title_fa, section=section,
                         section_title_fa=section_title, action=action, sort_order=order)


# Order of sections as they appear in the role editor.
_SECTIONS: list[PermissionSection] = [
    PermissionSection("dashboard", "داشبورد", (
        _perm("dashboard.view", "view", "مشاهده داشبورد", "dashboard", "داشبورد", 10),
    )),
    PermissionSection("users", "کاربران", (
        _perm("users.view", "view", "مشاهده کاربران", "users", "کاربران", 20),
        _perm("users.create", "create", "ایجاد کاربر", "users", "کاربران", 21),
        _perm("users.edit", "edit", "ویرایش کاربر", "users", "کاربران", 22),
        _perm("users.disable", "delete", "غیرفعال‌سازی کاربر", "users", "کاربران", 23),
        _perm("users.reset_password", "edit", "تغییر رمز عبور کاربران", "users", "کاربران", 24),
        _perm("users.unlock", "edit", "رفع قفل حساب کاربری", "users", "کاربران", 25),
    )),
    PermissionSection("roles", "نقش‌ها و دسترسی‌ها", (
        _perm("roles.view", "view", "مشاهده نقش‌ها", "roles", "نقش‌ها و دسترسی‌ها", 30),
        _perm("roles.create", "create", "ایجاد نقش", "roles", "نقش‌ها و دسترسی‌ها", 31),
        _perm("roles.edit", "edit", "ویرایش دسترسی‌های نقش", "roles", "نقش‌ها و دسترسی‌ها", 32),
        _perm("roles.delete", "delete", "حذف نقش", "roles", "نقش‌ها و دسترسی‌ها", 33),
    )),
    PermissionSection("audit", "گزارش رویدادها", (
        _perm("audit.view", "view", "مشاهده رویدادهای امنیتی و تاریخچه", "audit", "گزارش رویدادها", 40),
        _perm("audit.export", "print", "خروجی گرفتن از رویدادها", "audit", "گزارش رویدادها", 41),
    )),
    PermissionSection("settings", "تنظیمات", (
        _perm("settings.view", "view", "مشاهده تنظیمات", "settings", "تنظیمات", 50),
        _perm("settings.edit", "edit", "ویرایش تنظیمات", "settings", "تنظیمات", 51),
    )),
    PermissionSection("backup", "پشتیبان‌گیری", (
        _perm("backup.view", "view", "مشاهده پشتیبان‌ها", "backup", "پشتیبان‌گیری", 60),
        _perm("backup.create", "create", "ایجاد پشتیبان", "backup", "پشتیبان‌گیری", 61),
        _perm("backup.restore", "approve", "بازیابی پایگاه داده", "backup", "پشتیبان‌گیری", 62),
        _perm("backup.delete", "delete", "حذف فایل پشتیبان", "backup", "پشتیبان‌گیری", 63),
    )),
    PermissionSection("accounts", "کدینگ حساب‌ها", (
        _perm("accounts.view", "view", "مشاهده کدینگ حساب‌ها", "accounts", "کدینگ حساب‌ها", 70),
        _perm("accounts.create", "create", "ایجاد حساب", "accounts", "کدینگ حساب‌ها", 71),
        _perm("accounts.edit", "edit", "ویرایش حساب", "accounts", "کدینگ حساب‌ها", 72),
        _perm("accounts.deactivate", "edit", "غیرفعال‌سازی حساب", "accounts", "کدینگ حساب‌ها", 73),
        _perm("accounts.delete", "delete", "حذف حساب بدون سابقه", "accounts", "کدینگ حساب‌ها", 74),
        _perm("details.view", "view", "مشاهده حساب‌های تفصیلی", "accounts", "کدینگ حساب‌ها", 75),
        _perm("details.edit", "edit", "ایجاد و ویرایش حساب‌های تفصیلی", "accounts",
              "کدینگ حساب‌ها", 76),
    )),
    PermissionSection("journals", "اسناد حسابداری", (
        _perm("journals.view", "view", "مشاهده اسناد حسابداری", "journals", "اسناد حسابداری", 80),
        _perm("journals.create", "create", "ایجاد سند", "journals", "اسناد حسابداری", 81),
        _perm("journals.edit_draft", "edit", "ویرایش پیش‌نویس سند", "journals",
              "اسناد حسابداری", 82),
        _perm("journals.delete_draft", "delete", "حذف پیش‌نویس سند", "journals",
              "اسناد حسابداری", 83),
        _perm("journals.submit", "edit", "ارسال سند برای تأیید", "journals",
              "اسناد حسابداری", 84),
        _perm("journals.approve", "approve", "تأیید سند", "journals", "اسناد حسابداری", 85),
        _perm("journals.post", "approve", "ثبت نهایی سند", "journals", "اسناد حسابداری", 86),
        _perm("journals.void", "delete", "ابطال سند ثبت‌شده", "journals", "اسناد حسابداری", 87),
        _perm("journals.reverse", "create", "ثبت سند معکوس/اصلاحی", "journals",
              "اسناد حسابداری", 88),
    )),
    PermissionSection("reports", "گزارش‌های حسابداری", (
        _perm("reports.journal_book", "view", "مشاهده دفتر روزنامه", "reports",
              "گزارش‌های حسابداری", 90),
        _perm("reports.general_ledger", "view", "مشاهده دفتر کل", "reports",
              "گزارش‌های حسابداری", 91),
        _perm("reports.subsidiary_ledger", "view", "مشاهده دفتر معین و گردش حساب", "reports",
              "گزارش‌های حسابداری", 92),
        _perm("reports.trial_balance", "view", "مشاهده تراز آزمایشی", "reports",
              "گزارش‌های حسابداری", 93),
        _perm("reports.statements", "view", "مشاهده صورت‌های مالی", "reports",
              "گزارش‌های حسابداری", 94),
        _perm("reports.export", "print", "خروجی Excel و PDF گزارش‌ها", "reports",
              "گزارش‌های حسابداری", 95),
        _perm("reports.print", "print", "چاپ گزارش‌ها", "reports", "گزارش‌های حسابداری", 96),
    )),
    PermissionSection("periods", "دوره‌های مالی", (
        _perm("periods.view", "view", "مشاهده دوره‌های مالی", "periods", "دوره‌های مالی", 100),
        _perm("periods.create", "create", "ایجاد و ویرایش دوره مالی", "periods",
              "دوره‌های مالی", 101),
        _perm("periods.close", "approve", "بستن و بازگشایی دوره مالی", "periods",
              "دوره‌های مالی", 102),
    )),
    PermissionSection("dimensions", "مراکز هزینه و پروژه‌ها", (
        _perm("dimensions.view", "view", "مشاهده مراکز هزینه و پروژه‌ها", "dimensions",
              "مراکز هزینه و پروژه‌ها", 110),
        _perm("dimensions.edit", "edit", "تعریف و ویرایش مراکز هزینه و پروژه‌ها", "dimensions",
              "مراکز هزینه و پروژه‌ها", 111),
    )),
    PermissionSection("accounting", "تنظیمات حسابداری", (
        _perm("accounting.settings", "edit", "مدیریت تنظیمات حسابداری", "accounting",
              "تنظیمات حسابداری", 120),
    )),
    PermissionSection("products", "کالاها و خدمات", (
        _perm("products.view", "view", "مشاهده کالاها و خدمات", "products", "کالاها و خدمات", 200),
        _perm("products.create", "create", "ایجاد کالا/خدمت", "products", "کالاها و خدمات", 201),
        _perm("products.edit", "edit", "ویرایش کالا/خدمت", "products", "کالاها و خدمات", 202),
        _perm("products.deactivate", "edit", "غیرفعال‌سازی کالا/خدمت", "products",
              "کالاها و خدمات", 203),
        _perm("products.delete", "delete", "حذف کالا/خدمت بدون سابقه", "products",
              "کالاها و خدمات", 204),
        _perm("products.price_change", "approve", "تغییر بهای فروش و خرید کالا", "products",
              "کالاها و خدمات", 205),
    )),
    PermissionSection("persons", "اشخاص (مشتریان و تأمین‌کنندگان)", (
        _perm("persons.view", "view", "مشاهده اشخاص", "persons",
              "اشخاص (مشتریان و تأمین‌کنندگان)", 210),
        _perm("persons.create", "create", "ایجاد شخص", "persons",
              "اشخاص (مشتریان و تأمین‌کنندگان)", 211),
        _perm("persons.edit", "edit", "ویرایش شخص", "persons",
              "اشخاص (مشتریان و تأمین‌کنندگان)", 212),
        _perm("persons.deactivate", "edit", "غیرفعال‌سازی شخص", "persons",
              "اشخاص (مشتریان و تأمین‌کنندگان)", 213),
        _perm("persons.delete", "delete", "حذف شخص بدون سابقه", "persons",
              "اشخاص (مشتریان و تأمین‌کنندگان)", 214),
    )),
    PermissionSection("warehouses", "انبارها", (
        _perm("warehouses.view", "view", "مشاهده انبارها", "warehouses", "انبارها", 220),
        _perm("warehouses.edit", "edit", "تعریف و ویرایش انبارها", "warehouses", "انبارها", 221),
    )),
    PermissionSection("stock", "عملیات انبار", (
        _perm("stock.view", "view", "مشاهده موجودی و کاردکس", "stock", "عملیات انبار", 230),
        _perm("stock.receipt", "create", "ثبت رسید انبار", "stock", "عملیات انبار", 231),
        _perm("stock.issue", "create", "ثبت حواله خروج", "stock", "عملیات انبار", 232),
        _perm("stock.transfer", "create", "انتقال بین انبارها", "stock", "عملیات انبار", 233),
        _perm("stock.adjust", "approve", "اصلاح موجودی", "stock", "عملیات انبار", 234),
        _perm("stock.cardex", "view", "مشاهده کاردکس", "stock", "عملیات انبار", 235),
        _perm("stock.count", "create", "انبارگردانی و ثبت شمارش", "stock", "عملیات انبار", 236),
        _perm("stock.count_approve", "approve", "تأیید انبارگردانی و مغایرت", "stock",
              "عملیات انبار", 237),
        _perm("stock.negative_override", "approve", "اجازه خروج بیش از موجودی (سیاست منفی)",
              "stock", "عملیات انبار", 238),
    )),
    PermissionSection("purchase", "خرید", (
        _perm("purchase.order", "create", "درخواست و سفارش خرید", "purchase", "خرید", 240),
        _perm("purchase.approve", "approve", "تأیید سفارش/پیش‌فاکتور خرید", "purchase",
              "خرید", 241),
        _perm("purchase.invoice", "create", "ثبت فاکتور خرید", "purchase", "خرید", 242),
        _perm("purchase.post", "approve", "ثبت نهایی فاکتور خرید", "purchase", "خرید", 243),
        _perm("purchase.return", "create", "ثبت برگشت از خرید", "purchase", "خرید", 244),
        _perm("purchase.reports", "view", "گزارش‌های خرید", "purchase", "خرید", 245),
    )),
    PermissionSection("sales", "فروش", (
        _perm("sales.order", "create", "پیش‌فاکتور و سفارش فروش", "sales", "فروش", 250),
        _perm("sales.approve", "approve", "تأیید سفارش/پیش‌فاکتور فروش", "sales", "فروش", 251),
        _perm("sales.invoice", "create", "ثبت فاکتور فروش", "sales", "فروش", 252),
        _perm("sales.post", "approve", "ثبت نهایی فاکتور فروش", "sales", "فروش", 253),
        _perm("sales.return", "create", "ثبت برگشت از فروش", "sales", "فروش", 254),
        _perm("sales.reports", "view", "گزارش‌های فروش", "sales", "فروش", 255),
    )),
    PermissionSection("pricing", "قیمت‌گذاری و تخفیف", (
        _perm("pricing.view", "view", "مشاهده لیست‌های قیمت و تخفیف", "pricing",
              "قیمت‌گذاری و تخفیف", 260),
        _perm("pricing.edit", "edit", "تعریف لیست قیمت و تخفیف", "pricing",
              "قیمت‌گذاری و تخفیف", 261),
    )),
    PermissionSection("commerce", "تنظیمات و گزارش‌های بازرگانی", (
        _perm("commerce.settings", "edit", "مدیریت الگوهای ثبت و روش ارزش‌گذاری", "commerce",
              "تنظیمات و گزارش‌های بازرگانی", 270),
        _perm("commerce.reports", "view", "گزارش‌های مدیریتی بازرگانی و انبار", "commerce",
              "تنظیمات و گزارش‌های بازرگانی", 271),

        # ------------------------------------------------------- treasury
        _perm("bank_accounts.view", "view", "مشاهده حساب‌های بانکی", "treasury",
              "خزانه‌داری", 300),
        _perm("bank_accounts.edit", "edit", "ایجاد و ویرایش حساب بانکی", "treasury",
              "خزانه‌داری", 301),
        _perm("cash_boxes.view", "view", "مشاهده صندوق‌ها", "treasury", "خزانه‌داری", 302),
        _perm("cash_boxes.edit", "edit", "مدیریت صندوق‌ها", "treasury", "خزانه‌داری", 303),
        _perm("receipts.view", "view", "مشاهده دریافت‌ها", "treasury", "خزانه‌داری", 304),
        _perm("receipts.create", "create", "ثبت دریافت وجه", "treasury", "خزانه‌داری", 305),
        _perm("payments.view", "view", "مشاهده پرداخت‌ها", "treasury", "خزانه‌داری", 306),
        _perm("payments.create", "create", "ثبت پرداخت وجه", "treasury", "خزانه‌داری", 307),
        _perm("vouchers.approve", "approve", "تأیید دریافت و پرداخت", "treasury",
              "خزانه‌داری", 308),
        _perm("vouchers.post", "approve", "ثبت نهایی دریافت و پرداخت", "treasury",
              "خزانه‌داری", 309),
        _perm("transfers.create", "create", "انتقال وجه بین حساب‌ها", "treasury",
              "خزانه‌داری", 310),
        _perm("cheques.view", "view", "مشاهده چک‌ها", "treasury", "خزانه‌داری", 311),
        _perm("cheques.create", "create", "ثبت چک دریافتی و پرداختی", "treasury",
              "خزانه‌داری", 312),
        _perm("cheques.change_status", "edit", "تغییر وضعیت چک", "treasury",
              "خزانه‌داری", 313),
        _perm("cheques.cancel", "approve", "ابطال چک", "treasury", "خزانه‌داری", 314),
        _perm("cheque_books.manage", "edit", "مدیریت دسته‌چک", "treasury",
              "خزانه‌داری", 315),
        _perm("reconciliation.manage", "edit", "مغایرت‌گیری بانکی", "treasury",
              "خزانه‌داری", 316),
        _perm("reconciliation.approve", "approve", "تأیید مغایرت بانکی", "treasury",
              "خزانه‌داری", 317),
        _perm("settlements.manage", "edit", "تسویه فاکتورها", "treasury",
              "خزانه‌داری", 318),
        _perm("treasury.reports", "view", "گزارش‌های خزانه‌داری", "treasury",
              "خزانه‌داری", 319),
        _perm("treasury.calendar", "view", "تقویم سررسیدها", "treasury",
              "خزانه‌داری", 320),
    )),
]

ALL_PERMISSIONS: tuple[PermissionDef, ...] = tuple(
    perm for section in _SECTIONS for perm in section.permissions)
PERMISSION_SECTIONS: tuple[PermissionSection, ...] = tuple(_SECTIONS)
PERMISSIONS_BY_CODE: dict[str, PermissionDef] = {p.code: p for p in ALL_PERMISSIONS}
ALL_PERMISSION_CODES: frozenset[str] = frozenset(PERMISSIONS_BY_CODE)


def iter_permissions() -> Iterable[PermissionDef]:
    return iter(ALL_PERMISSIONS)


def is_known_permission(code: str) -> bool:
    return code in PERMISSIONS_BY_CODE


def permission_title(code: str) -> str:
    perm = PERMISSIONS_BY_CODE.get(code)
    return perm.description_fa if perm else code


# --------------------------------------------------------------------- roles
@dataclass(frozen=True)
class RoleTemplate:
    code: str
    title_fa: str
    description: str
    permissions: frozenset[str]
    is_system: bool = True
    sort_order: int = 100

    def missing_codes(self) -> set[str]:
        return set(self.permissions) - set(ALL_PERMISSION_CODES)


_PHASE1_BASIC = {"dashboard.view"}

#: Read-only accounting access (reports and bookkeeping browsing).
_ACCOUNTING_VIEW = {
    "accounts.view", "details.view", "journals.view", "reports.journal_book",
    "reports.general_ledger", "reports.subsidiary_ledger", "reports.trial_balance",
    "reports.statements", "reports.export", "reports.print", "periods.view",
    "dimensions.view",
}

#: Read-only commerce access (catalogue, persons, stock, commercial reports).
_COMMERCE_VIEW = {
    "products.view", "persons.view", "warehouses.view", "stock.view", "stock.cardex",
    "purchase.reports", "sales.reports", "pricing.view", "commerce.reports",
}

#: Read-only treasury access (funds, vouchers, cheques, reports).
_TREASURY_VIEW = {
    "bank_accounts.view", "cash_boxes.view", "receipts.view", "payments.view",
    "cheques.view", "treasury.reports", "treasury.calendar",
}

#: Day-to-day treasury work: registering vouchers, cheques and settlements.
_TREASURY_ENTRY = _TREASURY_VIEW | {
    "receipts.create", "payments.create", "cheques.create", "cheques.change_status",
    "transfers.create", "settlements.manage", "reconciliation.manage",
}

#: What a bookkeeper may do: everything except approving/posting/closing.
_ACCOUNTING_ENTRY = _ACCOUNTING_VIEW | {
    "journals.create", "journals.edit_draft", "journals.delete_draft", "journals.submit",
    "accounts.create", "accounts.edit", "details.edit",
}

DEFAULT_ROLE_TEMPLATES: tuple[RoleTemplate, ...] = (
    RoleTemplate(
        code="admin",
        title_fa="مدیر سیستم",
        description="دسترسی کامل به تمام بخش‌های نرم‌افزار",
        permissions=frozenset(ALL_PERMISSION_CODES),
        sort_order=10,
    ),
    RoleTemplate(
        code="accountant",
        title_fa="حسابدار",
        description=("ثبت و ویرایش پیش‌نویس اسناد، تعریف حساب‌ها و مشاهدهٔ تمام "
                     "گزارش‌های حسابداری؛ تأیید و ثبت نهایی سند با مدیر سیستم است"),
        permissions=frozenset(
            _PHASE1_BASIC | {"audit.view"} | _ACCOUNTING_ENTRY | _COMMERCE_VIEW
            | _TREASURY_ENTRY
            | {"purchase.order", "purchase.invoice", "sales.order", "sales.invoice"}
        ),
        sort_order=20,
    ),
    RoleTemplate(
        code="chief_accountant",
        title_fa="مدیر مالی",
        description=("مانند حسابدار به‌همراه تأیید و ثبت نهایی اسناد و مدیریت "
                     "دوره‌های مالی"),
        permissions=frozenset(
            _PHASE1_BASIC | {"audit.view"} | _ACCOUNTING_ENTRY | _COMMERCE_VIEW
            | {"purchase.order", "purchase.approve", "purchase.invoice", "purchase.post",
               "purchase.return", "sales.order", "sales.approve", "sales.invoice",
               "sales.post", "sales.return", "pricing.edit", "products.price_change",
               "stock.adjust", "stock.count_approve", "stock.negative_override",
               "warehouses.edit", "commerce.settings",
               "journals.approve", "journals.post", "journals.void", "journals.reverse",
               "accounts.deactivate", "periods.create", "periods.close",
               "dimensions.edit", "accounting.settings",
               "bank_accounts.edit", "cash_boxes.edit", "cheque_books.manage",
               "vouchers.approve", "vouchers.post", "cheques.cancel",
               "reconciliation.approve"}),
        sort_order=30,
    ),
    RoleTemplate(
        code="storekeeper",
        title_fa="انباردار",
        description=("ثبت رسید، حواله، انتقال و شمارش انبار و مشاهده موجودی و کاردکس؛ "
                     "تأیید مغایرت و ثبت فاکتور بر عهده مدیر انبار/مدیر مالی است"),
        permissions=frozenset(
            _PHASE1_BASIC
            | {"products.view", "warehouses.view", "persons.view", "stock.view",
               "stock.cardex", "stock.receipt", "stock.issue", "stock.transfer",
               "stock.count", "commerce.reports"}
        ),
        sort_order=40,
    ),
    RoleTemplate(
        code="salesperson",
        title_fa="فروشنده",
        description=("ثبت پیش‌فاکتور/سفارش و فاکتور فروش و برگشت از فروش و ثبت مشتری؛ "
                     "ثبت نهایی فاکتور با مدیر فروش است"),
        permissions=frozenset(
            _PHASE1_BASIC
            | {"products.view", "persons.view", "persons.create", "persons.edit",
               "warehouses.view", "stock.view", "sales.order", "sales.invoice",
               "sales.return", "sales.reports", "pricing.view", "commerce.reports"}
        ),
        sort_order=50,
    ),
    RoleTemplate(
        code="viewer",
        title_fa="مشاهده‌گر",
        description="مشاهده داشبورد، گزارش‌های حسابداری و اطلاعات بازرگانی بدون هیچ تغییری",
        permissions=frozenset(_PHASE1_BASIC | _ACCOUNTING_VIEW | _COMMERCE_VIEW
                              | _TREASURY_VIEW),
        sort_order=60,
    ),
    RoleTemplate(
        code="treasurer",
        title_fa="خزانه‌دار",
        description=("ثبت دریافت، پرداخت، چک، انتقال وجه، تسویه فاکتور و مغایرت بانکی، "
                     "به‌همراه مدیریت صندوق‌ها و حساب‌های بانکی؛ ثبت نهایی اسناد با "
                     "مدیر مالی است"),
        permissions=frozenset(
            _PHASE1_BASIC | {"audit.view"} | _COMMERCE_VIEW | _TREASURY_ENTRY
            | {"bank_accounts.edit", "cash_boxes.edit", "cheque_books.manage"}
        ),
        sort_order=35,
    ),
)

ADMIN_ROLE_CODE = "admin"


# ---------------------------------------------------------------- enforcement
@dataclass(frozen=True)
class SecurityContext:
    """The authenticated identity used by every service call."""

    user_id: int
    username: str
    full_name: str
    role_codes: tuple[str, ...]
    permissions: frozenset[str]
    session_id: int | None = None
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE_CODE in self.role_codes

    def has(self, code: str) -> bool:
        return code in self.permissions

    def has_any(self, *codes: str) -> bool:
        return any(code in self.permissions for code in codes)

    def has_all(self, *codes: str) -> bool:
        return all(code in self.permissions for code in codes)


def require_permission(ctx: SecurityContext | None, code: str) -> None:
    """Raise :class:`PermissionDeniedError` unless ``ctx`` holds ``code``."""
    if code not in PERMISSIONS_BY_CODE:
        raise PermissionDeniedError(code, f"مجوز «{code}» در سیستم تعریف نشده است.")
    if ctx is None:
        raise PermissionDeniedError(code, "برای انجام این عملیات باید وارد سیستم شوید.")
    if code not in ctx.permissions:
        raise PermissionDeniedError(code)


def require_any(ctx: SecurityContext | None, *codes: str) -> None:
    if ctx is None:
        raise PermissionDeniedError(None, "برای انجام این عملیات باید وارد سیستم شوید.")
    if not any(code in ctx.permissions for code in codes):
        raise PermissionDeniedError("، ".join(codes))


def build_context(*, user_id: int, username: str, full_name: str, role_codes: Iterable[str],
                  permissions: Iterable[str], session_id: int | None = None,
                  must_change_password: bool = False) -> SecurityContext:
    known = {code for code in permissions if code in PERMISSIONS_BY_CODE}
    return SecurityContext(
        user_id=user_id,
        username=username,
        full_name=full_name,
        role_codes=tuple(sorted(set(role_codes))),
        permissions=frozenset(known),
        session_id=session_id,
        must_change_password=must_change_password,
    )
