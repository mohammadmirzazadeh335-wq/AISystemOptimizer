"""Phase-5 fixed assets and depreciation: registration, movement, sale, runs."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.assets import constants as A
from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.services.assets_service import (
    AssetInput,
    CategoryInput,
    DisposalInput,
    MaintenanceInput,
)
from pars_erp.services.depreciation_service import DepreciationService, month_bounds
from pars_erp.services.hr_service import EmployeeInput, OrgUnitInput

D = Decimal
# 1405/02 = 2026-04-21 .. 2026-05-21
YEAR, MONTH = 1405, 2
IN_SERVICE = _dt.date(2026, 4, 25)


@pytest.fixture()
def category(services, admin, chart):
    return services.assets.create_category(admin, CategoryInput(
        code="VEH", title_fa="وسایل نقلیه", kind=A.CAT_VEHICLE,
        default_useful_life_years=5, default_method=A.METHOD_STRAIGHT_LINE))


@pytest.fixture()
def asset(services, admin, category):
    return services.assets.register(admin, AssetInput(
        title_fa="وانت حمل بار", category_id=category.id, serial_no="SN-1",
        purchase_date=IN_SERVICE, in_service_date=IN_SERVICE,
        purchase_price=D("600000000"), related_costs=D("50000000"),
        salvage_value=D("50000000"), useful_life_months=60,
        location="انبار مرکزی", notes="خرید نقدی"))


# ----------------------------------------------------------------- categories
def test_category_inherits_the_standard_accounts(services, admin, chart, category):
    accounts, _period = chart
    assert category.asset_account_id == accounts["102001"].id
    assert category.accumulated_account_id == accounts["102003"].id
    assert category.expense_account_id == accounts["502005"].id
    assert category.default_method_fa == "خط مستقیم"
    assert category.assets_count == 0


def test_category_rejects_an_unknown_kind(services, admin, chart):
    with pytest.raises(ValidationError):
        services.assets.create_category(admin, CategoryInput(
            code="X", title_fa="نامعتبر", kind="nonsense"))


# -------------------------------------------------------------------- assets
def test_registering_an_asset_sets_the_initial_value(services, admin, asset):
    assert asset.code.startswith("AST-")
    assert asset.purchase_price == D("600000000.00")
    assert asset.related_costs == D("50000000.00")
    assert asset.initial_value == D("650000000.00")
    assert asset.book_value == D("650000000.00")     # nothing depreciated yet
    assert asset.accumulated == D("0.00")
    assert asset.status == A.ASSET_IN_USE
    assert asset.monthly_depreciation == D("10000000.00")  # (650M − 50M) ÷ 60


def test_asset_requires_salvage_below_cost(services, admin, category):
    with pytest.raises(ValidationError):
        services.assets.register(admin, AssetInput(
            title_fa="دارایی نامعتبر", category_id=category.id,
            in_service_date=IN_SERVICE, purchase_price=D("1000"),
            salvage_value=D("1000")))


def test_asset_needs_a_positive_value_and_a_date(services, admin, category):
    with pytest.raises(ValidationError):
        services.assets.register(admin, AssetInput(
            title_fa="بدون ارزش", category_id=category.id,
            in_service_date=IN_SERVICE, purchase_price=0))
    with pytest.raises(ValidationError):
        services.assets.register(admin, AssetInput(
            title_fa="بدون تاریخ", category_id=category.id, purchase_price=D("1000")))


def test_duplicate_asset_code_is_refused(services, admin, category, asset):
    with pytest.raises(ConflictError):
        services.assets.register(admin, AssetInput(
            code=asset.code, title_fa="تکراری", category_id=category.id,
            in_service_date=IN_SERVICE, purchase_price=D("1000")))


def test_editing_value_or_method_needs_the_policy_path(services, admin, asset):
    with pytest.raises(ValidationError):
        services.assets.update(admin, asset.id, AssetInput(
            title_fa=asset.title_fa, category_id=asset.category_id,
            in_service_date=IN_SERVICE, purchase_price=D("600000000"),
            related_costs=D("50000000"), salvage_value=D("50000000"),
            useful_life_months=48))


def test_price_and_life_changes_are_recorded_with_a_reason(services, admin, asset):
    with pytest.raises(ValidationError):
        services.assets.change_depreciation_policy(admin, asset.id,
                                                   useful_life_months=48, note="")
    changed = services.assets.change_depreciation_policy(
        admin, asset.id, useful_life_months=48, note="بازنگری عمر مفید توسط کارشناس")
    assert changed.useful_life_months == 48
    history = services.assets.history(admin, asset.id)
    assert any(row.kind == A.MOVE_POLICY and "48" in row.to_value for row in history)


def test_registering_an_asset_writes_its_opening_history(services, admin, asset):
    history = services.assets.history(admin, asset.id)
    assert history[0].kind == A.MOVE_STATUS
    assert history[0].to_value == A.ASSET_STATUS_TITLES_FA[A.ASSET_IN_USE]


def test_filtering_assets(services, admin, asset):
    assert len(services.assets.list_assets(admin, search="وانت")) == 1
    assert len(services.assets.list_assets(admin, category_id=asset.category_id)) == 1
    assert len(services.assets.list_assets(admin, search="چیزی که نیست")) == 0
    assert len(services.assets.list_assets(admin, location="انبار")) == 1


# ------------------------------------------------------------------ movement
def test_transfer_records_unit_custodian_and_location(services, admin, asset):
    unit = services.hr.create_unit(admin, OrgUnitInput(code="U1", title_fa="واحد فنی"))
    employee = services.hr.create_employee(admin, EmployeeInput(
        code="EMP-6001", first_name="سعید", last_name="رستمی", hire_date=IN_SERVICE))
    moved = services.assets.transfer(admin, asset.id, to_org_unit_id=unit.id,
                                     to_employee_id=employee.id,
                                     location="سالن تولید",
                                     movement_date=_dt.date(2026, 5, 2),
                                     note="انتقال با مجوز مدیر")
    assert moved.org_unit_title == "واحد فنی"
    assert moved.custodian_name == "سعید رستمی"
    assert moved.location == "سالن تولید"
    history = services.assets.history(admin, asset.id)
    kinds = {row.kind for row in history}
    assert {A.MOVE_TRANSFER, A.MOVE_CUSTODIAN, A.MOVE_LOCATION} <= kinds


def test_maintenance_is_summed_per_asset(services, admin, asset):
    services.assets.add_maintenance(admin, MaintenanceInput(
        asset_id=asset.id, kind=A.MAINT_SERVICE, service_date=IN_SERVICE,
        cost=D("5000000"), contractor="تعمیرگاه مرکزی", is_periodic=True,
        next_service_date=_dt.date(2026, 8, 1)))
    services.assets.add_maintenance(admin, MaintenanceInput(
        asset_id=asset.id, kind=A.MAINT_REPAIR, service_date=_dt.date(2026, 5, 3),
        cost=D("2500000")))
    report = services.asset_reports.maintenance(admin, asset_id=asset.id)
    assert report.row_count == 1
    assert report.rows[0][2] == 2
    assert report.rows[0][3] == D("7500000.00")
    detail = services.asset_reports.maintenance_detail(admin, asset.id)
    assert detail.row_count == 2


# ------------------------------------------------------------------ disposal
def test_selling_an_asset_books_the_gain_and_blocks_a_second_sale(services, admin,
                                                                  asset, treasury):
    sold = services.assets.dispose(admin, DisposalInput(
        asset_id=asset.id, kind=A.DISPOSAL_SALE,
        disposal_date=_dt.date(2026, 5, 10), sale_amount=D("700000000"),
        buyer_name="خریدار آزمون", bank_account_id=treasury.bank.id,
        reason="فروش ناوگان قدیمی"))
    assert sold.gain_loss == D("50000000.00")     # 700M − 650M book value
    assert sold.book_value == D("650000000.00")
    assert sold.journal_id and sold.receipt_id
    assert services.assets.get_asset(admin, asset.id).status == A.ASSET_SOLD

    with services.db.session_scope() as session:
        from sqlalchemy import select
        from pars_erp.db.models import JournalLine
        lines = list(session.execute(
            select(JournalLine).where(JournalLine.journal_id == sold.journal_id)
        ).scalars())
        debit = sum((D(line.debit or 0) for line in lines), D("0"))
        credit = sum((D(line.credit or 0) for line in lines), D("0"))
    # the receipt credited the cost account with the 700M proceeds, so the journal
    # only clears the remaining 50M and books the same 50M as gain
    assert debit == credit == D("50000000.00")

    with pytest.raises(ConflictError):
        services.assets.dispose(admin, DisposalInput(
            asset_id=asset.id, kind=A.DISPOSAL_SALE,
            sale_amount=D("1000"), bank_account_id=treasury.bank.id))


def test_sale_requires_a_fund_and_a_price(services, admin, asset, treasury):
    with pytest.raises(ValidationError):
        services.assets.dispose(admin, DisposalInput(
            asset_id=asset.id, kind=A.DISPOSAL_SALE, sale_amount=D("1000")))
    with pytest.raises(ValidationError):
        services.assets.dispose(admin, DisposalInput(
            asset_id=asset.id, kind=A.DISPOSAL_SALE, sale_amount=0,
            bank_account_id=treasury.bank.id))


def test_retiring_an_asset_writes_off_the_book_value(services, admin, asset):
    retired = services.assets.dispose(admin, DisposalInput(
        asset_id=asset.id, kind=A.DISPOSAL_RETIRE,
        disposal_date=_dt.date(2026, 5, 11), reason="پایان عمر مفید"))
    assert retired.gain_loss == D("-650000000.00")
    assert retired.receipt_id is None
    assert services.assets.get_asset(admin, asset.id).status == A.ASSET_RETIRED
    with pytest.raises(ConflictError):
        services.assets.transfer(admin, asset.id, location="جایی")


# -------------------------------------------------------------- depreciation
def test_preview_does_not_write_anything(services, admin, asset):
    preview = services.depreciation.preview(admin, YEAR, MONTH)
    assert preview.run is None
    assert len(preview.lines) == 1
    assert preview.total_amount == D("10000000.00")
    assert services.depreciation.list_runs(admin) == []


def test_calculate_approve_and_post_a_month(services, admin, asset):
    services.posting.ensure_default_rules(admin)
    result = services.depreciation.calculate(admin, YEAR, MONTH)
    assert result.run is not None and result.run.status == A.DEP_RUN_DRAFT
    assert result.total_amount == D("10000000.00")

    approved = services.depreciation.approve(admin, result.run.id)
    assert approved.status == A.DEP_RUN_APPROVED

    posted = services.depreciation.post(admin, result.run.id)
    assert posted.status == A.DEP_RUN_POSTED
    assert posted.journal_id

    refreshed = services.assets.get_asset(admin, asset.id)
    assert refreshed.accumulated == D("10000000.00")
    assert refreshed.book_value == D("640000000.00")

    with services.db.session_scope() as session:
        from sqlalchemy import select
        from pars_erp.db.models import JournalLine
        lines = list(session.execute(
            select(JournalLine).where(JournalLine.journal_id == posted.journal_id)
        ).scalars())
    debit = sum((D(line.debit or 0) for line in lines), D("0"))
    credit = sum((D(line.credit or 0) for line in lines), D("0"))
    assert debit == credit == D("10000000.00")


def test_a_period_can_only_be_posted_once(services, admin, asset):
    services.posting.ensure_default_rules(admin)
    result = services.depreciation.calculate(admin, YEAR, MONTH)
    services.depreciation.approve(admin, result.run.id)
    services.depreciation.post(admin, result.run.id)
    with pytest.raises(ConflictError):
        services.depreciation.calculate(admin, YEAR, MONTH)
    with pytest.raises(ConflictError):
        services.depreciation.post(admin, result.run.id)


def test_post_requires_approval_first(services, admin, asset):
    services.posting.ensure_default_rules(admin)
    result = services.depreciation.calculate(admin, YEAR, MONTH)
    with pytest.raises(ConflictError):
        services.depreciation.post(admin, result.run.id)


def test_asset_is_not_depreciated_before_its_in_service_month(services, admin, asset):
    from pars_erp.assets.depreciation import first_period
    year, month = first_period(IN_SERVICE)
    earlier = (year, month - 1) if month > 1 else (year - 1, 12)
    preview = services.depreciation.preview(admin, *earlier)
    assert preview.total_amount == D("0.00")
    assert any("نرسیده" in reason for _code, reason in preview.skipped)


def test_fully_depreciated_asset_is_skipped(services, admin, category):
    services.posting.ensure_default_rules(admin)
    cheap = services.assets.register(admin, AssetInput(
        title_fa="دارایی کم‌ارزش", category_id=category.id,
        in_service_date=IN_SERVICE, purchase_price=D("1000000"),
        useful_life_months=1))
    first = services.depreciation.calculate(admin, YEAR, MONTH)
    services.depreciation.approve(admin, first.run.id)
    services.depreciation.post(admin, first.run.id)
    assert services.assets.get_asset(admin, cheap.id).book_value == D("0.00")

    year, month = (YEAR, MONTH + 1) if MONTH < 12 else (YEAR + 1, 1)
    second = services.depreciation.calculate(admin, year, month)
    codes = {line.asset_code for line in second.lines}
    assert cheap.code not in codes
    assert second.total_amount == D("0.00")


def test_units_of_production_needs_a_reading(services, admin, category):
    machine = services.assets.register(admin, AssetInput(
        title_fa="دستگاه پرس", category_id=category.id, in_service_date=IN_SERVICE,
        purchase_price=D("120000000"), useful_life_months=12,
        method=A.METHOD_UNITS, total_units=D("12000")))
    preview = services.depreciation.preview(admin, YEAR, MONTH)
    assert any(code == machine.code and "کارکرد" in reason
               for code, reason in preview.skipped)
    with_reading = services.depreciation.preview(
        admin, YEAR, MONTH, unit_readings={machine.id: D("1000")})
    assert with_reading.total_amount == D("10000000.00")   # 120M ÷ 12000 × 1000


def test_draft_run_can_be_deleted_but_a_posted_one_cannot(services, admin, asset):
    services.posting.ensure_default_rules(admin)
    services.depreciation.calculate(admin, YEAR, MONTH)
    services.depreciation.skip_run(admin, YEAR, MONTH)
    assert services.depreciation.list_runs(admin) == []
    result = services.depreciation.calculate(admin, YEAR, MONTH)
    services.depreciation.approve(admin, result.run.id)
    with pytest.raises(ConflictError):
        services.depreciation.skip_run(admin, YEAR, MONTH)


def test_asset_history_shows_the_posted_month(services, admin, asset):
    services.posting.ensure_default_rules(admin)
    result = services.depreciation.calculate(admin, YEAR, MONTH)
    services.depreciation.approve(admin, result.run.id)
    services.depreciation.post(admin, result.run.id)
    history = services.depreciation.asset_history(admin, asset.id)
    assert len(history) == 1
    assert history[0].amount == D("10000000.00")
    assert history[0].book_value_after == D("640000000.00")


def test_month_bounds_cover_the_whole_jalali_month():
    start, end = month_bounds(1405, 2)
    assert end > start
    assert (end - start).days == 30


def test_depreciation_service_exposes_its_public_surface():
    public = {name for name in dir(DepreciationService) if not name.startswith("_")}
    assert {"preview", "calculate", "approve", "post", "list_runs",
            "run_lines", "asset_history"} <= public
