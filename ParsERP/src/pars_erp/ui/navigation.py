"""Navigation catalogue.

Kept Qt-free so the permission rules that decide what a user may see are
unit-testable. Every item names the permission it needs; ``visible_items``
filters by the *authenticated* context, and the service layer re-checks
permissions anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pars_erp.security.permissions import SecurityContext


@dataclass(frozen=True)
class NavItem:
    key: str
    title_fa: str
    #: icon slug; matches ``resources/icons/nav/<slug>_normal.svg`` so the UI
    #: never depends on emoji fonts being installed on the machine.
    icon: str
    permission: str | None = None
    group: str = "main"
    enabled: bool = True
    planned_phase: int | None = None
    description_fa: str = ""

    @property
    def is_placeholder(self) -> bool:
        return self.planned_phase is not None


@dataclass(frozen=True)
class NavGroup:
    key: str
    title_fa: str
    items: tuple[NavItem, ...] = field(default_factory=tuple)


# Icon slugs point at the bundled SVG set (no emoji font dependency).
NAV_GROUPS: tuple[NavGroup, ...] = (
    NavGroup("overview", "نمای کلی", (
        NavItem("management_dashboard", "داشبورد مدیریتی", "dashboard", "dashboard.view",
                "overview",
                description_fa="کارت‌ها و نمودارهای واقعی فروش، خرید، خزانه و انبار"),
        NavItem("dashboard", "داشبورد سیستم", "dashboard", "dashboard.view", "overview",
                description_fa="نمای کلی وضعیت سیستم و رویدادهای امروز"),
    )),
    NavGroup("reporting", "گزارش‌ها و هشدارها", (
        NavItem("report_center", "مرکز گزارش‌ها", "reports", "reports.center", "reporting",
                description_fa="اجرای گزارش‌های همهٔ ماژول‌ها با فیلتر، صفحه‌بندی و خروجی"),
        NavItem("report_designer", "طراح گزارش", "design", "reports.designer", "reporting",
                description_fa="ساخت و ذخیرهٔ گزارش سفارشی از منابع مجاز"),
        NavItem("alerts", "هشدارهای مدیریتی", "alert", "alerts.view", "reporting",
                description_fa="هشدارهای ساخته‌شده از دادهٔ واقعی و تنظیم قواعد آن‌ها"),
    )),
    NavGroup("administration", "مدیریت سیستم", (
        NavItem("users", "کاربران", "users", "users.view", "administration",
                description_fa="ایجاد و مدیریت حساب‌های کاربری"),
        NavItem("roles", "نقش‌ها و دسترسی‌ها", "roles", "roles.view", "administration",
                description_fa="تعریف نقش‌ها و تعیین مجوزهای هر نقش"),
        NavItem("audit", "رویدادها و تاریخچه", "audit", "audit.view", "administration",
                description_fa="رویدادهای امنیتی و تاریخچه تغییرات"),
    )),
    NavGroup("system", "نگهداری سیستم", (
        NavItem("backup", "پشتیبان‌گیری", "backup", "backup.view", "system",
                description_fa="ایجاد، بررسی و بازیابی پشتیبان پایگاه داده"),
        NavItem("settings", "تنظیمات", "settings", "settings.view", "system",
                description_fa="تنظیمات شرکت، ظاهر برنامه، امنیت و پشتیبان‌گیری"),
        NavItem("about", "دربارهٔ زرین هرمز", "about", None, "system",
                description_fa="نسخه، شمارهٔ ساخت، کتابخانه‌ها و مجوزها"),
    )),
    NavGroup("commerce", "بازرگانی و انبار", (
        NavItem("products", "کالاها و خدمات", "products", "products.view", "commerce",
                description_fa="تعریف کالا/خدمت، دسته‌بندی، بارکد و قیمت‌ها"),
        NavItem("persons", "مشتریان و تأمین‌کنندگان", "persons", "persons.view",
                "commerce",
                description_fa="اشخاص، سقف اعتبار، مانده حساب و گردش"),
        NavItem("inventory", "انبارها و موجودی", "inventory", "stock.view", "commerce",
                description_fa="رسید، حواله، انتقال، کاردکس و انبارگردانی"),
        NavItem("purchase_invoices", "فاکتورهای خرید", "purchase", "purchase.reports",
                "commerce", description_fa="ثبت خرید، برگشت از خرید و ثبت نهایی"),
        NavItem("sales_invoices", "فاکتورهای فروش", "sales", "sales.reports",
                "commerce", description_fa="ثبت فروش، برگشت از فروش و ثبت نهایی"),
        NavItem("purchase_orders", "درخواست و سفارش خرید", "orders", "purchase.order",
                "commerce", description_fa="گردش درخواست تا تکمیل خرید"),
        NavItem("sales_orders", "سفارش فروش", "orders", "sales.order", "commerce",
                description_fa="گردش سفارش فروش تا آماده‌سازی و تحویل"),
        NavItem("pricing", "قیمت‌گذاری و مالیات", "pricing", "pricing.view",
                "commerce", description_fa="لیست‌های قیمت، تخفیف و نرخ‌های مالیات"),
        NavItem("commerce_reports", "گزارش‌های بازرگانی", "reports",
                "commerce.reports", "commerce",
                description_fa="خرید، فروش، موجودی و اشخاص با چاپ و Excel/PDF"),
        NavItem("commerce_settings", "تنظیمات بازرگانی", "settings",
                "commerce.settings", "commerce",
                description_fa="روش ارزش‌گذاری و الگوهای ثبت حسابداری"),
    )),
    NavGroup("treasury", "خزانه‌داری", (
        NavItem("treasury_dashboard", "داشبورد خزانه‌داری", "wallet", "treasury.reports",
                "treasury",
                description_fa="موجودی صندوق‌ها و بانک‌ها، دریافتی و پرداختی امروز و "
                               "چک‌های نزدیک سررسید"),
        NavItem("receipt_cash", "دریافت وجه", "receipt", "receipts.view", "treasury",
                description_fa="ثبت رسید دریافت نقدی، کارت‌خوان، انتقال، چک و متفرقه"),
        NavItem("payment_cash", "پرداخت وجه", "payment", "payments.view", "treasury",
                description_fa="ثبت سند پرداخت نقدی، بانکی، هزینه، حقوق و با چک"),
        NavItem("receipt_customer", "دریافت از مشتری", "receipt", "receipts.view",
                "treasury", description_fa="وصول مطالبات مشتریان با تسویهٔ فاکتورها"),
        NavItem("payment_supplier", "پرداخت به تأمین‌کننده", "payment", "payments.view",
                "treasury", description_fa="پرداخت بدهی تأمین‌کنندگان و تسویهٔ فاکتور خرید"),
        NavItem("cheque_received", "دریافت چک", "cheque", "cheques.view", "treasury",
                description_fa="ثبت و پیگیری چک‌های دریافتی تا وصول یا برگشت"),
        NavItem("cheque_issued", "پرداخت چک", "cheque", "cheques.view", "treasury",
                description_fa="ثبت و پیگیری چک‌های صادره و صدور از دسته‌چک"),
        NavItem("cash_boxes", "صندوق‌ها", "cashbox", "cash_boxes.view", "treasury",
                description_fa="چند صندوق، مسئول صندوق، دسترسی کاربران و گردش صندوق"),
        NavItem("bank_accounts", "حساب‌های بانکی", "bank", "bank_accounts.view",
                "treasury", description_fa="شبا، کارت، حساب معین، موجودی و صورت‌حساب"),
        NavItem("treasury_transfer", "انتقال وجه", "transfer", "transfers.create",
                "treasury", description_fa="انتقال بین صندوق‌ها و حساب‌های بانکی با کارمزد"),
        NavItem("cheque_books", "دسته‌چک‌ها", "cheque", "cheque_books.manage", "treasury",
                description_fa="شمارهٔ برگ‌ها، برگ‌های مصرف‌شده و جلوگیری از تکرار شماره"),
        NavItem("cheque_manage", "مدیریت چک‌ها", "cheque", "cheques.view", "treasury",
                description_fa="تغییر وضعیت چک، تاریخچه، وصول، برگشت و ابطال"),
        NavItem("receivables", "اسناد دریافتنی", "receipt", "cheques.view", "treasury",
                description_fa="چک‌ها و مطالبات در جریان وصول با سررسید"),
        NavItem("payables", "اسناد پرداختنی", "payment", "cheques.view", "treasury",
                description_fa="چک‌ها و بدهی‌های سررسیدشدهٔ شرکت"),
        NavItem("reconciliation", "مغایرت‌گیری بانکی", "reconcile", "reconciliation.manage",
                "treasury", description_fa="ورود صورت‌حساب، تطبیق خودکار/دستی و سند اصلاحی"),
        NavItem("settlements", "تسویه‌حساب‌ها", "transfer", "settlements.manage",
                "treasury", description_fa="مانده هر فاکتور، تسویهٔ کامل یا جزئی"),
        NavItem("fund_flow", "گزارش گردش وجوه", "reports", "treasury.reports", "treasury",
                description_fa="گردش صندوق و بانک، جریان نقدی و پیش‌بینی سررسیدها"),
        NavItem("treasury_reports", "گزارش خزانه‌داری", "reports", "treasury.reports",
                "treasury", description_fa="گزارش بانک، صندوق، چک، اشخاص و نقدینگی"),
        NavItem("treasury_settings", "تنظیمات خزانه‌داری", "settings",
                "treasury.reports", "treasury",
                description_fa="سیاست موجودی منفی، روزهای هشدار و الگوهای ثبت"),
    )),
    NavGroup("accounting", "حسابداری مالی", (
        NavItem("acc_dashboard", "داشبورد حسابداری", "dashboard",
                "accounts.view", "accounting",
                description_fa="وضعیت کدینگ، دوره مالی و اسناد"),
        NavItem("accounts", "کدینگ حساب‌ها", "roles", "accounts.view", "accounting",
                description_fa="گروه، کل، معین و حساب‌های تفصیلی"),
        NavItem("journals", "اسناد حسابداری", "audit", "journals.view", "accounting",
                description_fa="ثبت، تأیید، قطعی‌سازی و ابطال اسناد"),
        NavItem("acc_periods", "دوره‌های مالی", "backup", "periods.view", "accounting",
                description_fa="ایجاد، بستن و بازگشایی دوره مالی"),
        NavItem("journal_book", "دفتر روزنامه", "audit", "reports.journal_book",
                "accounting", description_fa="تمام سطرهای اسناد ثبت‌شده"),
        NavItem("general_ledger", "دفتر کل", "roles", "reports.general_ledger",
                "accounting", description_fa="مانده و گردش حساب‌ها"),
        NavItem("subsidiary_ledger", "دفتر معین", "users", "reports.subsidiary_ledger",
                "accounting", description_fa="ریز گردش یک حساب با مانده جاری"),
        NavItem("turnover", "گردش حساب‌ها", "dashboard", "reports.general_ledger",
                "accounting", description_fa="گردش بدهکار و بستانکار هر حساب"),
        NavItem("trial_balance", "تراز آزمایشی", "audit", "reports.trial_balance",
                "accounting", description_fa="تراز دو، چهار و شش‌ستونی"),
        NavItem("balance_sheet", "ترازنامه", "roles", "reports.statements",
                "accounting", description_fa="دارایی، بدهی و سرمایه"),
        NavItem("income_statement", "صورت سود و زیان", "dashboard",
                "reports.statements", "accounting",
                description_fa="درآمدها و هزینه‌های دوره"),
        NavItem("acc_dimensions", "مراکز هزینه و پروژه‌ها", "backup", "dimensions.view",
                "accounting", description_fa="ابعاد اختیاری سطرهای سند"),
        NavItem("acc_currencies", "ارزها و نرخ‌ها", "settings", "accounts.view",
                "accounting", description_fa="ارز پایه و نرخ‌های تاریخی"),
        NavItem("acc_settings", "تنظیمات حسابداری", "settings", "accounting.settings",
                "accounting", description_fa="الگوی کدینگ و گردش تأیید"),
    )),
    NavGroup("hr", "منابع انسانی", (
        NavItem("hr_employees", "کارکنان", "employees", "hr.employees.view", "hr",
                description_fa="پروندهٔ پرسنلی، سابقهٔ تغییرات، اطلاعات شغلی و بانکی"),
        NavItem("hr_org", "ساختار سازمانی", "org", "hr.employees.view", "hr",
                description_fa="درخت شرکت/شعبه/واحد، مدیر هر واحد و انتقال سازمانی"),
        NavItem("hr_contracts", "قراردادها", "contract", "hr.contracts.manage", "hr",
                description_fa="ثبت، تمدید، اصلاح، خاتمه و هشدار انقضای قرارداد"),
        NavItem("hr_attendance", "حضور و غیاب", "attendance", "hr.attendance.record", "hr",
                description_fa="ثبت روزانه، اصلاح با دلیل، ورود از فایل و شیفت‌ها"),
        NavItem("hr_leave", "مرخصی، مأموریت و اضافه‌کاری", "leave", "hr.leave.request",
                "hr", description_fa="درخواست، تأیید، رد، ماندهٔ مرخصی و ورودی حقوق"),
        NavItem("hr_reports", "گزارش‌های منابع انسانی", "reports", "hr.reports", "hr",
                description_fa="کارکنان، قرارداد، حضور، تأخیر، مرخصی و مأموریت"),
    )),
    NavGroup("payroll", "حقوق و دستمزد", (
        NavItem("payroll_settings", "تنظیمات حقوق", "settings", "payroll.settings",
                "payroll",
                description_fa="نسخه‌های تاریخ‌دار نرخ بیمه، مالیات، مزایا و ضرایب"),
        NavItem("payroll_runs", "دوره‌های حقوق", "payroll", "payroll.view", "payroll",
                description_fa="ایجاد دوره، محاسبه، تأیید، ثبت سند و لغو"),
        NavItem("payroll_payslips", "فیش حقوقی", "payslip", "payroll.payslip.view",
                "payroll", description_fa="فیش هر دوره، اقلام محاسبه و چاپ با PDF"),
        NavItem("payroll_payments", "پرداخت حقوق", "payment", "payroll.pay", "payroll",
                description_fa="دستهٔ پرداخت، فایل بانکی، پرداخت و ردیف ناموفق"),
        NavItem("payroll_loans", "وام و مساعده", "loans", "payroll.loans.manage",
                "payroll", description_fa="درخواست، تأیید، پرداخت، اقساط و تسویه"),
        NavItem("payroll_reports", "گزارش‌های حقوق", "reports", "payroll.reports",
                "payroll", description_fa="دفتر حقوق، ریز اقلام، پرداخت‌ها و ماندهٔ وام"),
    )),
    NavGroup("assets", "دارایی‌های ثابت", (
        NavItem("assets_categories", "دسته‌های دارایی", "assets", "assets.view", "assets",
                description_fa="دسته‌بندی، عمر مفید، روش استهلاک و سه حساب هر دسته"),
        NavItem("assets_register", "دارایی‌ها", "assets", "assets.view", "assets",
                description_fa="ثبت دارایی، انتقال، امانت‌داری، سیاست استهلاک و تعمیر"),
        NavItem("assets_depreciation", "استهلاک", "depreciation", "assets.depreciate",
                "assets", description_fa="پیش‌نمایش، محاسبهٔ ماهانه، تأیید و ثبت سند"),
        NavItem("assets_disposals", "فروش و کنارگذاری", "transfer", "assets.view",
                "assets", description_fa="واگذاری دارایی با سند فروش و فهرست تعمیرات"),
        NavItem("asset_reports", "گزارش‌های دارایی", "reports", "assets.reports", "assets",
                description_fa="فهرست دارایی، دسته، محل، امانت‌دار، استهلاک و واگذاری"),
    )),
)

#: Menu order: the accounting section sits directly under the overview because it
#: is where an accountant works all day.
_GROUP_ORDER = ("overview", "reporting", "commerce", "treasury", "accounting", "hr",
                "payroll", "assets", "administration", "system")
NAV_GROUPS: tuple[NavGroup, ...] = tuple(
    sorted(NAV_GROUPS, key=lambda group: (
        _GROUP_ORDER.index(group.key) if group.key in _GROUP_ORDER else len(_GROUP_ORDER))))

ALL_ITEMS: dict[str, NavItem] = {item.key: item for group in NAV_GROUPS for item in group.items}


def visible_items(ctx: SecurityContext | None) -> tuple[NavGroup, ...]:
    """Groups containing only the items the context may open (or planned ones)."""
    if ctx is None:
        return tuple(NavGroup(g.key, g.title_fa, tuple(i for i in g.items if i.is_placeholder))
                     for g in NAV_GROUPS)
    result = []
    for group in NAV_GROUPS:
        allowed = tuple(item for item in group.items
                        if item.is_placeholder or item.permission is None
                        or ctx.has(item.permission))
        if allowed:
            result.append(NavGroup(group.key, group.title_fa, allowed))
    return tuple(result)


def first_page_key(ctx: SecurityContext | None) -> str | None:
    for group in visible_items(ctx):
        for item in group.items:
            if not item.is_placeholder:
                return item.key
    return None


def menu_structure(ctx: SecurityContext | None) -> list[tuple[str, list[tuple[str, str, bool]]]]:
    """``[(menu_title, [(action_key, title, enabled)])]`` for the menu bar."""
    return [(group.title_fa,
             [(item.key, item.title_fa, item.enabled) for item in group.items])
            for group in visible_items(ctx)]
