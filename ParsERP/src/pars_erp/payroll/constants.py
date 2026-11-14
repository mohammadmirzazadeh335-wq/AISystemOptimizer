"""Phase-5 payroll constants: settings keys, run/payslip states, posting operations.

The golden rule of this phase: **no statutory number is hard-coded here**. Tax
brackets, insurance rates, allowances and overtime factors are rows in a dated
settings version that an authorised user maintains from an official source; the
engine only multiplies and adds what it is given.
"""

from __future__ import annotations

# ----------------------------------------------------------- settings versions
VERSION_DRAFT = "draft"
VERSION_ACTIVE = "active"
VERSION_ARCHIVED = "archived"
VERSION_STATUSES: tuple[tuple[str, str], ...] = (
    (VERSION_DRAFT, "پیش‌نویس"),
    (VERSION_ACTIVE, "فعال"),
    (VERSION_ARCHIVED, "بایگانی"),
)
VERSION_TITLES_FA: dict[str, str] = dict(VERSION_STATUSES)

#: Every rate/amount the engine may read. A value that is missing is treated as
#: zero and the payslip records that it was not configured - never a guess.
SETTING_BASE_HOURS = "base_hours_per_month"
SETTING_WORK_DAYS = "work_days_per_month"
SETTING_OVERTIME_FACTOR = "overtime_factor"
SETTING_HOLIDAY_FACTOR = "holiday_overtime_factor"
SETTING_HOUSING = "housing_allowance"
SETTING_FOOD = "food_allowance"
SETTING_CHILD = "child_allowance_per_child"
SETTING_MARRIAGE = "marriage_allowance"
SETTING_SENIORITY = "seniority_allowance_per_year"
SETTING_CONTINUOUS = "continuous_benefit_default"
SETTING_NON_CONTINUOUS = "non_continuous_benefit_default"
SETTING_INSURANCE_EMPLOYEE = "insurance_employee_rate"
SETTING_INSURANCE_EMPLOYER = "insurance_employer_rate"
SETTING_INSURANCE_BASE_CAP = "insurance_base_cap"
SETTING_TAX_EXEMPT = "income_tax_exempt_amount"
SETTING_ABSENCE = "absence_deduction_per_day"
SETTING_LOAN_MAX_RATIO = "loan_max_share_of_salary"
SETTING_ROUNDING = "rounding_step"

PAY_SETTING_KEYS: tuple[str, ...] = (
    SETTING_BASE_HOURS, SETTING_WORK_DAYS, SETTING_OVERTIME_FACTOR,
    SETTING_HOLIDAY_FACTOR, SETTING_HOUSING, SETTING_FOOD, SETTING_CHILD,
    SETTING_MARRIAGE, SETTING_SENIORITY, SETTING_CONTINUOUS,
    SETTING_NON_CONTINUOUS, SETTING_INSURANCE_EMPLOYEE, SETTING_INSURANCE_EMPLOYER,
    SETTING_INSURANCE_BASE_CAP, SETTING_TAX_EXEMPT, SETTING_ABSENCE,
    SETTING_LOAN_MAX_RATIO, SETTING_ROUNDING,
)
PAY_SETTING_TITLES_FA: dict[str, str] = {
    SETTING_BASE_HOURS: "ساعت کاری موظفی ماه",
    SETTING_WORK_DAYS: "روز کاری ماه",
    SETTING_OVERTIME_FACTOR: "ضریب اضافه‌کاری",
    SETTING_HOLIDAY_FACTOR: "ضریب اضافه‌کاری ایام تعطیل",
    SETTING_HOUSING: "کمک‌هزینه مسکن",
    SETTING_FOOD: "کمک‌هزینه خواربار",
    SETTING_CHILD: "حق اولاد (به ازای هر فرزند)",
    SETTING_MARRIAGE: "حق تأهل",
    SETTING_SENIORITY: "پایه سنوات (به ازای هر سال)",
    SETTING_CONTINUOUS: "مزایای مستمر پیش‌فرض",
    SETTING_NON_CONTINUOUS: "مزایای غیرمستمر پیش‌فرض",
    SETTING_INSURANCE_EMPLOYEE: "نرخ بیمه سهم کارمند",
    SETTING_INSURANCE_EMPLOYER: "نرخ بیمه سهم کارفرما",
    SETTING_INSURANCE_BASE_CAP: "سقف مبنای بیمه",
    SETTING_TAX_EXEMPT: "مبلغ معافیت مالیات",
    SETTING_ABSENCE: "کسر غیبت برای هر روز",
    SETTING_LOAN_MAX_RATIO: "حداکثر نسبت قسط به حقوق",
    SETTING_ROUNDING: "گام گرد کردن مبالغ",
}
#: Percentage settings are stored as percentages (e.g. ``7`` meaning ۷٪).
PERCENT_KEYS: frozenset[str] = frozenset({SETTING_INSURANCE_EMPLOYEE,
                                         SETTING_INSURANCE_EMPLOYER,
                                         SETTING_LOAN_MAX_RATIO})
FACTOR_KEYS: frozenset[str] = frozenset({SETTING_OVERTIME_FACTOR,
                                         SETTING_HOLIDAY_FACTOR})

# ------------------------------------------------------------------ pay runs
RUN_DRAFT = "draft"
RUN_CALCULATED = "calculated"
RUN_APPROVED = "approved"
RUN_POSTED = "posted"
RUN_PAID = "paid"
RUN_CANCELLED = "cancelled"
RUN_STATUSES: tuple[tuple[str, str], ...] = (
    (RUN_DRAFT, "پیش‌نویس"),
    (RUN_CALCULATED, "محاسبه‌شده"),
    (RUN_APPROVED, "تأییدشده"),
    (RUN_POSTED, "ثبت‌شده"),
    (RUN_PAID, "پرداخت‌شده"),
    (RUN_CANCELLED, "لغوشده"),
)
RUN_STATUS_TITLES_FA: dict[str, str] = dict(RUN_STATUSES)
RUN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    RUN_DRAFT: (RUN_CALCULATED, RUN_CANCELLED),
    RUN_CALCULATED: (RUN_APPROVED, RUN_CALCULATED, RUN_CANCELLED),
    RUN_APPROVED: (RUN_POSTED, RUN_CALCULATED, RUN_CANCELLED),
    RUN_POSTED: (RUN_PAID,),
    RUN_PAID: (),
    RUN_CANCELLED: (),
}

SLIP_DRAFT = "draft"
SLIP_APPROVED = "approved"
SLIP_PAID = "paid"
SLIP_STATUSES: tuple[tuple[str, str], ...] = (
    (SLIP_DRAFT, "محاسبه‌شده"),
    (SLIP_APPROVED, "تأییدشده"),
    (SLIP_PAID, "پرداخت‌شده"),
)
SLIP_STATUS_TITLES_FA: dict[str, str] = dict(SLIP_STATUSES)

# ------------------------------------------------------------- payslip lines
LINE_BASE = "base"
LINE_HOUSING = "housing"
LINE_FOOD = "food"
LINE_CHILD = "child"
LINE_MARRIAGE = "marriage"
LINE_SENIORITY = "seniority"
LINE_CONTINUOUS = "continuous"
LINE_NON_CONTINUOUS = "non_continuous"
LINE_OVERTIME = "overtime"
LINE_MISSION = "mission"
LINE_BONUS = "bonus"
LINE_INSURANCE = "insurance_employee"
LINE_TAX = "income_tax"
LINE_ABSENCE = "absence"
LINE_LOAN = "loan_installment"
LINE_ADVANCE = "advance"
LINE_OTHER = "other_deduction"
EARNING_KINDS: tuple[tuple[str, str], ...] = (
    (LINE_BASE, "حقوق پایه"),
    (LINE_HOUSING, "کمک‌هزینه مسکن"),
    (LINE_FOOD, "کمک‌هزینه خواربار"),
    (LINE_CHILD, "حق اولاد"),
    (LINE_MARRIAGE, "حق تأهل"),
    (LINE_SENIORITY, "پایه سنوات"),
    (LINE_CONTINUOUS, "مزایای مستمر"),
    (LINE_NON_CONTINUOUS, "مزایای غیرمستمر"),
    (LINE_OVERTIME, "اضافه‌کاری"),
    (LINE_MISSION, "مأموریت"),
    (LINE_BONUS, "پاداش"),
)
DEDUCTION_KINDS: tuple[tuple[str, str], ...] = (
    (LINE_INSURANCE, "بیمه سهم کارمند"),
    (LINE_TAX, "مالیات بر درآمد"),
    (LINE_ABSENCE, "کسر غیبت"),
    (LINE_LOAN, "قسط وام"),
    (LINE_ADVANCE, "بازپرداخت مساعده"),
    (LINE_OTHER, "سایر کسور"),
)
LINE_TITLES_FA: dict[str, str] = dict(EARNING_KINDS + DEDUCTION_KINDS)
EARNING_CODES: frozenset[str] = frozenset(code for code, _ in EARNING_KINDS)

# --------------------------------------------------------------- loans/advances
LOAN_KIND_LOAN = "loan"
LOAN_KIND_ADVANCE = "advance"
LOAN_KINDS: tuple[tuple[str, str], ...] = (
    (LOAN_KIND_LOAN, "وام"),
    (LOAN_KIND_ADVANCE, "مساعده"),
)
LOAN_KIND_TITLES_FA: dict[str, str] = dict(LOAN_KINDS)

LOAN_REQUESTED = "requested"
LOAN_APPROVED = "approved"
LOAN_PAID = "paid"
LOAN_CLOSED = "closed"
LOAN_REJECTED = "rejected"
LOAN_CANCELLED = "cancelled"
LOAN_STATUSES: tuple[tuple[str, str], ...] = (
    (LOAN_REQUESTED, "درخواست"),
    (LOAN_APPROVED, "تأییدشده"),
    (LOAN_PAID, "پرداخت‌شده"),
    (LOAN_CLOSED, "تسویه‌شده"),
    (LOAN_REJECTED, "رد‌شده"),
    (LOAN_CANCELLED, "لغوشده"),
)
LOAN_STATUS_TITLES_FA: dict[str, str] = dict(LOAN_STATUSES)
LOAN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    LOAN_REQUESTED: (LOAN_APPROVED, LOAN_REJECTED, LOAN_CANCELLED),
    LOAN_APPROVED: (LOAN_PAID, LOAN_CANCELLED),
    LOAN_PAID: (LOAN_CLOSED,),
    LOAN_CLOSED: (),
    LOAN_REJECTED: (),
    LOAN_CANCELLED: (),
}

INSTALLMENT_PENDING = "pending"
INSTALLMENT_DEDUCTED = "deducted"
INSTALLMENT_PAID = "paid"  # early settlement or manual payment
INSTALLMENT_STATUSES: tuple[tuple[str, str], ...] = (
    (INSTALLMENT_PENDING, "در انتظار کسر"),
    (INSTALLMENT_DEDUCTED, "کسرشده از حقوق"),
    (INSTALLMENT_PAID, "پرداخت‌شده"),
)
INSTALLMENT_TITLES_FA: dict[str, str] = dict(INSTALLMENT_STATUSES)

# ------------------------------------------------------------- payment batches
BATCH_DRAFT = "draft"
BATCH_APPROVED = "approved"
BATCH_PAID = "paid"
BATCH_PARTIAL = "partial"
BATCH_CANCELLED = "cancelled"
BATCH_STATUSES: tuple[tuple[str, str], ...] = (
    (BATCH_DRAFT, "پیش‌نویس"),
    (BATCH_APPROVED, "آمادهٔ پرداخت"),
    (BATCH_PAID, "پرداخت‌شده"),
    (BATCH_PARTIAL, "پرداخت ناقص"),
    (BATCH_CANCELLED, "لغوشده"),
)
BATCH_TITLES_FA: dict[str, str] = dict(BATCH_STATUSES)
ITEM_PENDING = "pending"
ITEM_PAID = "paid"
ITEM_FAILED = "failed"
ITEM_STATUSES: tuple[tuple[str, str], ...] = (
    (ITEM_PENDING, "در انتظار"),
    (ITEM_PAID, "پرداخت‌شده"),
    (ITEM_FAILED, "ناموفق"),
)
ITEM_TITLES_FA: dict[str, str] = dict(ITEM_STATUSES)

# ------------------------------------------------------- posting operations
#: The salary *accrual* is the only new pattern: the payment of salaries and of
#: loans goes through the phase-4 treasury payment documents (which have their own
#: configurable patterns and a counter account), so no duplicate rule is shipped.
POSTING_SALARY = "payroll.salary"

POSTING_OPERATIONS: tuple[str, ...] = (POSTING_SALARY,)
POSTING_TITLES_FA: dict[str, str] = {POSTING_SALARY: "ثبت حقوق و دستمزد ماهانه"}

SRC_GROSS = "gross_salary"
#: The amount actually charged to the salary expense account: gross minus
#: the absence deduction, plus/minus the payslip rounding difference.
SRC_SALARY_EXPENSE = "salary_expense"
SRC_EMPLOYER_INSURANCE = "employer_insurance"
SRC_INSURANCE_TOTAL = "insurance_total"
SRC_TAX = "income_tax"
SRC_NET = "net_salary"
SRC_LOAN = "loan_installment"
SRC_ADVANCE = "advance_deduction"
SRC_OTHER_DEDUCTION = "other_deduction"
SRC_EMPLOYEE = "employee_amount"

AMOUNT_SOURCES: tuple[str, ...] = (
    SRC_SALARY_EXPENSE, SRC_GROSS, SRC_EMPLOYER_INSURANCE, SRC_INSURANCE_TOTAL,
    SRC_TAX, SRC_NET, SRC_LOAN, SRC_ADVANCE, SRC_OTHER_DEDUCTION, SRC_EMPLOYEE,
)
AMOUNT_SOURCE_TITLES_FA: dict[str, str] = {
    SRC_GROSS: "جمع حقوق و مزایای ناخالص",
    SRC_SALARY_EXPENSE: "هزینهٔ حقوق (ناخالص منهای غیبت و تعدیل گرد کردن)",
    SRC_EMPLOYER_INSURANCE: "بیمه سهم کارفرما",
    SRC_INSURANCE_TOTAL: "جمع بیمه (کارمند + کارفرما)",
    SRC_TAX: "مالیات بر درآمد",
    SRC_NET: "حقوق خالص قابل پرداخت",
    SRC_LOAN: "قسط وام کسرشده",
    SRC_ADVANCE: "مساعده کسرشده",
    SRC_OTHER_DEDUCTION: "سایر کسور",
    SRC_EMPLOYEE: "مبلغ کارمند (پرداخت دسته‌ای)",
}
