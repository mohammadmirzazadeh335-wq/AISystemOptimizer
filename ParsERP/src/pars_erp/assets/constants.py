"""Phase-5 fixed-asset constants: categories, status, depreciation methods."""

from __future__ import annotations

# ----------------------------------------------------------------- categories
CAT_LAND = "land"
CAT_BUILDING = "building"
CAT_MACHINERY = "machinery"
CAT_EQUIPMENT = "equipment"
CAT_VEHICLE = "vehicle"
CAT_OFFICE = "office"
CAT_IT = "it"
CAT_FURNITURE = "furniture"
CAT_OTHER = "other"
CATEGORY_KINDS: tuple[tuple[str, str], ...] = (
    (CAT_LAND, "زمین"),
    (CAT_BUILDING, "ساختمان"),
    (CAT_MACHINERY, "ماشین‌آلات"),
    (CAT_EQUIPMENT, "تجهیزات"),
    (CAT_VEHICLE, "وسایل نقلیه"),
    (CAT_OFFICE, "تجهیزات اداری"),
    (CAT_IT, "تجهیزات رایانه‌ای"),
    (CAT_FURNITURE, "اثاثیه و منصوبات"),
    (CAT_OTHER, "سایر"),
)
CATEGORY_TITLES_FA: dict[str, str] = dict(CATEGORY_KINDS)

# --------------------------------------------------------------- depreciation
METHOD_STRAIGHT_LINE = "straight_line"
METHOD_DECLINING = "declining_balance"
METHOD_UNITS = "units_of_production"
METHODS: tuple[tuple[str, str], ...] = (
    (METHOD_STRAIGHT_LINE, "خط مستقیم"),
    (METHOD_DECLINING, "نزولی (مانده کاهشی)"),
    (METHOD_UNITS, "بر مبنای کارکرد"),
)
METHOD_TITLES_FA: dict[str, str] = dict(METHODS)

# --------------------------------------------------------------------- status
ASSET_IN_USE = "in_use"
ASSET_IDLE = "idle"
ASSET_REPAIR = "under_repair"
ASSET_SOLD = "sold"
ASSET_RETIRED = "retired"
ASSET_WRITTEN_OFF = "written_off"
ASSET_STATUSES: tuple[tuple[str, str], ...] = (
    (ASSET_IN_USE, "در بهره‌برداری"),
    (ASSET_IDLE, "بی‌استفاده"),
    (ASSET_REPAIR, "در تعمیر"),
    (ASSET_SOLD, "فروخته‌شده"),
    (ASSET_RETIRED, "کنارگذاری"),
    (ASSET_WRITTEN_OFF, "مستهلک/حذف"),
)
ASSET_STATUS_TITLES_FA: dict[str, str] = dict(ASSET_STATUSES)
DISPOSED_STATUSES: frozenset[str] = frozenset({ASSET_SOLD, ASSET_RETIRED,
                                               ASSET_WRITTEN_OFF})
ASSET_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ASSET_IN_USE: (ASSET_IDLE, ASSET_REPAIR, ASSET_SOLD, ASSET_RETIRED, ASSET_WRITTEN_OFF),
    ASSET_IDLE: (ASSET_IN_USE, ASSET_REPAIR, ASSET_SOLD, ASSET_RETIRED, ASSET_WRITTEN_OFF),
    ASSET_REPAIR: (ASSET_IN_USE, ASSET_IDLE, ASSET_SOLD, ASSET_RETIRED),
    ASSET_SOLD: (),
    ASSET_RETIRED: (),
    ASSET_WRITTEN_OFF: (),
}

# ------------------------------------------------------------------ movements
MOVE_TRANSFER = "transfer"
MOVE_CUSTODIAN = "custodian"
MOVE_LOCATION = "location"
MOVE_STATUS = "status"
MOVE_POLICY = "policy"
MOVE_KINDS: tuple[tuple[str, str], ...] = (
    (MOVE_TRANSFER, "انتقال بین واحد/شعبه"),
    (MOVE_CUSTODIAN, "تغییر امانت‌دار"),
    (MOVE_LOCATION, "تغییر محل استقرار"),
    (MOVE_STATUS, "تغییر وضعیت"),
    (MOVE_POLICY, "تغییر روش/عمر مفید"),
)
MOVE_TITLES_FA: dict[str, str] = dict(MOVE_KINDS)

# ------------------------------------------------------------------ disposal
DISPOSAL_SALE = "sale"
DISPOSAL_RETIRE = "retire"
DISPOSAL_WRITE_OFF = "write_off"
DISPOSAL_KINDS: tuple[tuple[str, str], ...] = (
    (DISPOSAL_SALE, "فروش"),
    (DISPOSAL_RETIRE, "کنارگذاری"),
    (DISPOSAL_WRITE_OFF, "حذف/مستهلک کردن"),
)
DISPOSAL_TITLES_FA: dict[str, str] = dict(DISPOSAL_KINDS)

# -------------------------------------------------------------- depreciation runs
DEP_RUN_DRAFT = "draft"
DEP_RUN_APPROVED = "approved"
DEP_RUN_POSTED = "posted"
DEP_RUN_STATUSES: tuple[tuple[str, str], ...] = (
    (DEP_RUN_DRAFT, "پیش‌نمایش"),
    (DEP_RUN_APPROVED, "تأییدشده"),
    (DEP_RUN_POSTED, "ثبت‌شده"),
)
DEP_RUN_TITLES_FA: dict[str, str] = dict(DEP_RUN_STATUSES)

# ---------------------------------------------------------------- maintenance
MAINT_REPAIR = "repair"
MAINT_SERVICE = "service"
MAINT_KINDS: tuple[tuple[str, str], ...] = (
    (MAINT_REPAIR, "تعمیر"),
    (MAINT_SERVICE, "سرویس دوره‌ای"),
)
MAINT_TITLES_FA: dict[str, str] = dict(MAINT_KINDS)

# ------------------------------------------------------------- default accounts
DEFAULT_ASSET_ACCOUNT_CODE = "102001"
DEFAULT_ACCUMULATED_CODE = "102003"
DEFAULT_DEPRECIATION_EXPENSE_CODE = "502005"
DEFAULT_GAIN_CODE = "402002"
DEFAULT_LOSS_CODE = "503002"
DEFAULT_MAINTENANCE_EXPENSE_CODE = "502003"
