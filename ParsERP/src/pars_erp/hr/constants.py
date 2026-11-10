"""Phase-5 human-resources constants: org units, employees, contracts, attendance.

Nothing in this module is a legal rate. Working-hour rules, leave quotas and
payroll rates live in **dated, versioned settings** (``hr_work_rules`` /
``pay_settings_*``) so an installation can follow its own labour contract and the
official rules that apply to it, without a code change.
"""

from __future__ import annotations

# ---------------------------------------------------------------- org structure
UNIT_COMPANY = "company"
UNIT_BRANCH = "branch"
UNIT_UNIT = "unit"
UNIT_SECTION = "section"
UNIT_POSITION = "position"
UNIT_JOB_TITLE = "job_title"
ORG_UNIT_KINDS: tuple[tuple[str, str], ...] = (
    (UNIT_COMPANY, "شرکت"),
    (UNIT_BRANCH, "شعبه"),
    (UNIT_UNIT, "واحد"),
    (UNIT_SECTION, "بخش"),
    (UNIT_POSITION, "پست سازمانی"),
    (UNIT_JOB_TITLE, "عنوان شغلی"),
)
ORG_UNIT_TITLES_FA: dict[str, str] = dict(ORG_UNIT_KINDS)
TOP_LEVEL_KINDS: tuple[str, ...] = (UNIT_COMPANY, UNIT_BRANCH)

# -------------------------------------------------------------------- employees
EMPLOYMENT_FULL_TIME = "full_time"
EMPLOYMENT_PART_TIME = "part_time"
EMPLOYMENT_CONTRACTOR = "contractor"
EMPLOYMENT_TEMPORARY = "temporary"
EMPLOYMENT_INTERN = "intern"
EMPLOYMENT_TYPES: tuple[tuple[str, str], ...] = (
    (EMPLOYMENT_FULL_TIME, "تمام‌وقت"),
    (EMPLOYMENT_PART_TIME, "پاره‌وقت"),
    (EMPLOYMENT_CONTRACTOR, "پیمانکاری"),
    (EMPLOYMENT_TEMPORARY, "موقت"),
    (EMPLOYMENT_INTERN, "کارآموز"),
)
EMPLOYMENT_TITLES_FA: dict[str, str] = dict(EMPLOYMENT_TYPES)

COLLAB_ACTIVE = "active"
COLLAB_SUSPENDED = "suspended"
COLLAB_LEFT = "left"
COLLAB_RETIRED = "retired"
COLLAB_STATUSES: tuple[tuple[str, str], ...] = (
    (COLLAB_ACTIVE, "شاغل"),
    (COLLAB_SUSPENDED, "تعلیق موقت"),
    (COLLAB_LEFT, "ترک خدمت"),
    (COLLAB_RETIRED, "بازنشسته"),
)
COLLAB_TITLES_FA: dict[str, str] = dict(COLLAB_STATUSES)

GENDER_MALE = "male"
GENDER_FEMALE = "female"
GENDERS: tuple[tuple[str, str], ...] = ((GENDER_MALE, "مرد"), (GENDER_FEMALE, "زن"))
GENDER_TITLES_FA: dict[str, str] = dict(GENDERS)

MARITAL_SINGLE = "single"
MARITAL_MARRIED = "married"
MARITAL_STATUSES: tuple[tuple[str, str], ...] = (
    (MARITAL_SINGLE, "مجرد"),
    (MARITAL_MARRIED, "متأهل"),
)
MARITAL_TITLES_FA: dict[str, str] = dict(MARITAL_STATUSES)

# -------------------------------------------------------------------- contracts
CONTRACT_PERMANENT = "permanent"
CONTRACT_FIXED = "fixed"
CONTRACT_PROJECT = "project"
CONTRACT_INTERNSHIP = "internship"
CONTRACT_TYPES: tuple[tuple[str, str], ...] = (
    (CONTRACT_PERMANENT, "دائم"),
    (CONTRACT_FIXED, "مدت‌دار"),
    (CONTRACT_PROJECT, "پروژه‌ای"),
    (CONTRACT_INTERNSHIP, "کارآموزی"),
)
CONTRACT_TITLES_FA: dict[str, str] = dict(CONTRACT_TYPES)

CONTRACT_DRAFT = "draft"
CONTRACT_ACTIVE = "active"
CONTRACT_EXPIRED = "expired"
CONTRACT_TERMINATED = "terminated"
CONTRACT_RENEWED = "renewed"
CONTRACT_STATUSES: tuple[tuple[str, str], ...] = (
    (CONTRACT_DRAFT, "پیش‌نویس"),
    (CONTRACT_ACTIVE, "جاری"),
    (CONTRACT_EXPIRED, "منقضی"),
    (CONTRACT_TERMINATED, "خاتمه‌یافته"),
    (CONTRACT_RENEWED, "تمدیدشده"),
)
CONTRACT_STATUS_TITLES_FA: dict[str, str] = dict(CONTRACT_STATUSES)
CONTRACT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    CONTRACT_DRAFT: (CONTRACT_ACTIVE, CONTRACT_TERMINATED),
    CONTRACT_ACTIVE: (CONTRACT_EXPIRED, CONTRACT_TERMINATED, CONTRACT_RENEWED),
    CONTRACT_EXPIRED: (CONTRACT_RENEWED,),
    CONTRACT_RENEWED: (),
    CONTRACT_TERMINATED: (),
}

HISTORY_JOB = "job"
HISTORY_UNIT = "unit"
HISTORY_CONTRACT = "contract"
HISTORY_SALARY = "salary"
HISTORY_STATUS = "status"
HISTORY_KINDS: tuple[tuple[str, str], ...] = (
    (HISTORY_JOB, "تغییر سمت"),
    (HISTORY_UNIT, "تغییر واحد سازمانی"),
    (HISTORY_CONTRACT, "قرارداد"),
    (HISTORY_SALARY, "حقوق پایه"),
    (HISTORY_STATUS, "وضعیت همکاری"),
)
HISTORY_TITLES_FA: dict[str, str] = dict(HISTORY_KINDS)

# ----------------------------------------------------------------------- shifts
SHIFT_MORNING = "morning"
SHIFT_EVENING = "evening"
SHIFT_NIGHT = "night"
SHIFT_ROTATING = "rotating"
SHIFT_CUSTOM = "custom"
SHIFT_KINDS: tuple[tuple[str, str], ...] = (
    (SHIFT_MORNING, "صبح"),
    (SHIFT_EVENING, "عصر"),
    (SHIFT_NIGHT, "شب"),
    (SHIFT_ROTATING, "چرخشی"),
    (SHIFT_CUSTOM, "سفارشی"),
)
SHIFT_TITLES_FA: dict[str, str] = dict(SHIFT_KINDS)
WEEKDAY_TITLES_FA: tuple[str, ...] = (
    "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه")
#: Persian week starts on Saturday; the index matches ``date.weekday()`` is
#: *not* used: the work calendar stores Saturday-based indexes (0..6).
DEFAULT_WORKING_DAYS: tuple[int, ...] = (0, 1, 2, 3, 4)

# ------------------------------------------------------------------- attendance
ATT_SOURCE_MANUAL = "manual"
ATT_SOURCE_SELF = "self_service"
ATT_SOURCE_IMPORT = "import"
ATT_SOURCE_DEVICE = "device"
ATT_SOURCES: tuple[tuple[str, str], ...] = (
    (ATT_SOURCE_MANUAL, "ثبت دستی"),
    (ATT_SOURCE_SELF, "سلف‌سرویس کارمند"),
    (ATT_SOURCE_IMPORT, "ورود از فایل"),
    (ATT_SOURCE_DEVICE, "دستگاه حضور و غیاب"),
)
ATT_SOURCE_TITLES_FA: dict[str, str] = dict(ATT_SOURCES)

ATT_PRESENT = "present"
ATT_LATE = "late"
ATT_ABSENT = "absent"
ATT_LEAVE = "leave"
ATT_MISSION = "mission"
ATT_HOLIDAY = "holiday"
ATT_STATUSES: tuple[tuple[str, str], ...] = (
    (ATT_PRESENT, "حاضر"),
    (ATT_LATE, "تأخیر"),
    (ATT_ABSENT, "غیبت"),
    (ATT_LEAVE, "مرخصی"),
    (ATT_MISSION, "مأموریت"),
    (ATT_HOLIDAY, "تعطیل"),
)
ATT_STATUS_TITLES_FA: dict[str, str] = dict(ATT_STATUSES)

# ------------------------------------------------------------------------ leave
LEAVE_PAID = "paid"
LEAVE_SICK = "sick"
LEAVE_UNPAID = "unpaid"
LEAVE_HOURLY = "hourly"
LEAVE_EMERGENCY = "emergency"
LEAVE_CUSTOM = "custom"
LEAVE_KINDS: tuple[tuple[str, str], ...] = (
    (LEAVE_PAID, "استحقاقی"),
    (LEAVE_SICK, "استعلاجی"),
    (LEAVE_UNPAID, "بدون حقوق"),
    (LEAVE_HOURLY, "ساعتی"),
    (LEAVE_EMERGENCY, "اضطراری"),
    (LEAVE_CUSTOM, "سفارشی"),
)
LEAVE_KIND_TITLES_FA: dict[str, str] = dict(LEAVE_KINDS)

LEAVE_DRAFT = "draft"
LEAVE_SUBMITTED = "submitted"
LEAVE_APPROVED = "approved"
LEAVE_REJECTED = "rejected"
LEAVE_CANCELLED = "cancelled"
LEAVE_STATUSES: tuple[tuple[str, str], ...] = (
    (LEAVE_DRAFT, "پیش‌نویس"),
    (LEAVE_SUBMITTED, "در انتظار تأیید"),
    (LEAVE_APPROVED, "تأییدشده"),
    (LEAVE_REJECTED, "رد‌شده"),
    (LEAVE_CANCELLED, "لغوشده"),
)
LEAVE_STATUS_TITLES_FA: dict[str, str] = dict(LEAVE_STATUSES)
LEAVE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    LEAVE_DRAFT: (LEAVE_SUBMITTED, LEAVE_CANCELLED),
    LEAVE_SUBMITTED: (LEAVE_APPROVED, LEAVE_REJECTED, LEAVE_CANCELLED),
    LEAVE_APPROVED: (LEAVE_CANCELLED,),
    LEAVE_REJECTED: (),
    LEAVE_CANCELLED: (),
}

# ------------------------------------------------------------ missions/overtime
REQUEST_DRAFT = "draft"
REQUEST_SUBMITTED = "submitted"
REQUEST_APPROVED = "approved"
REQUEST_REJECTED = "rejected"
REQUEST_CANCELLED = "cancelled"
REQUEST_STATUSES: tuple[tuple[str, str], ...] = (
    (REQUEST_DRAFT, "پیش‌نویس"),
    (REQUEST_SUBMITTED, "در انتظار تأیید"),
    (REQUEST_APPROVED, "تأییدشده"),
    (REQUEST_REJECTED, "رد‌شده"),
    (REQUEST_CANCELLED, "لغوشده"),
)
REQUEST_STATUS_TITLES_FA: dict[str, str] = dict(REQUEST_STATUSES)
REQUEST_TRANSITIONS: dict[str, tuple[str, ...]] = {
    REQUEST_DRAFT: (REQUEST_SUBMITTED, REQUEST_CANCELLED),
    REQUEST_SUBMITTED: (REQUEST_APPROVED, REQUEST_REJECTED, REQUEST_CANCELLED),
    REQUEST_APPROVED: (REQUEST_CANCELLED,),
    REQUEST_REJECTED: (),
    REQUEST_CANCELLED: (),
}

# ------------------------------------------------------------- posting/chart ids
DEFAULT_EMPLOYEE_ADVANCE_CODE = "101008"
DEFAULT_INSURANCE_PAYABLE_CODE = "201005"
DEFAULT_SALARY_PAYABLE_CODE = "201003"
DEFAULT_TAX_PAYABLE_CODE = "201002"
DEFAULT_SALARY_EXPENSE_CODE = "502001"
DEFAULT_EMPLOYER_INSURANCE_CODE = "502006"
