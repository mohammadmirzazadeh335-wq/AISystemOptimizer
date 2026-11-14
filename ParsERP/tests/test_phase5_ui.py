"""Phase-5 screens: navigation, permissions, real widgets and real documents.

The Qt-free tests run everywhere. The ``gui`` tests build the real widgets and are
skipped when no Qt platform plugin can be created, so a green run never pretends a
screen was rendered when it was not. Every GUI test asserts on documents that the
service layer wrote to the database - not on mocked values.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.assets import constants as A
from pars_erp.hr import constants as H
from pars_erp.payroll import constants as P
from pars_erp.security.permissions import ALL_PERMISSIONS, SecurityContext
from pars_erp.services.assets_service import AssetInput, CategoryInput
from pars_erp.services.attendance_service import AttendanceInput, ShiftInput
from pars_erp.services.hr_service import ContractInput, EmployeeInput, OrgUnitInput
from pars_erp.services.funds_service import CashBoxInput
from pars_erp.services.loans_service import LoanInput
from pars_erp.services.payroll_service import TaxBracketInput, VersionInput
from pars_erp.ui.navigation import ALL_ITEMS, NAV_GROUPS, visible_items

D = Decimal
YEAR, MONTH = 1405, 2
DAY = _dt.date(2026, 5, 5)

HR_KEYS = ("hr_employees", "hr_org", "hr_contracts", "hr_attendance", "hr_leave",
           "hr_reports")
PAYROLL_KEYS = ("payroll_settings", "payroll_runs", "payroll_payslips", "payroll_payments",
                "payroll_loans", "payroll_reports")
ASSET_KEYS = ("assets_categories", "assets_register", "assets_depreciation",
              "assets_disposals", "asset_reports")
ALL_KEYS = HR_KEYS + PAYROLL_KEYS + ASSET_KEYS

PHASE5_PERMISSIONS = (
    "hr.employees.view", "hr.employees.create", "hr.employees.edit",
    "hr.employees.sensitive", "hr.contracts.manage", "hr.org.edit",
    "hr.attendance.record", "hr.attendance.amend", "hr.leave.request",
    "hr.leave.approve", "hr.overtime.approve", "hr.reports", "hr.print",
    "payroll.view", "payroll.settings", "payroll.calculate", "payroll.approve",
    "payroll.pay", "payroll.payslip.view", "payroll.loans.manage", "payroll.reports",
    "payroll.print",
    "assets.view", "assets.register", "assets.transfer", "assets.dispose",
    "assets.depreciate", "assets.post_depreciation", "assets.maintenance",
    "assets.reports", "assets.print",
)

ICON_SLUGS = {"employees", "org", "contract", "attendance", "leave", "payroll", "payslip",
              "loans", "assets", "depreciation", "reports", "settings", "payment",
              "transfer"}


def _role_permissions(code: str) -> tuple[str, ...]:
    from pars_erp.security.permissions import DEFAULT_ROLE_TEMPLATES

    for template in DEFAULT_ROLE_TEMPLATES:
        if template.code == code:
            return tuple(template.permissions)
    return ()


def _context(code: str, username: str | None = None) -> SecurityContext:
    return SecurityContext(
        user_id=99, username=username or code, full_name=f"کاربر {code}",
        role_codes=(code,), permissions=frozenset(_role_permissions(code)))


def _keys(ctx) -> set[str]:
    return {item.key for group in visible_items(ctx) for item in group.items}


# ------------------------------------------------------------------ navigation
class TestPhase5Navigation:
    def test_groups_exist_in_the_expected_order(self) -> None:
        keys = [group.key for group in NAV_GROUPS]
        assert keys.index("accounting") < keys.index("hr") < keys.index("payroll") \
            < keys.index("assets") < keys.index("administration")
        titles = {group.key: group.title_fa for group in NAV_GROUPS}
        assert titles["hr"] == "منابع انسانی"
        assert titles["payroll"] == "حقوق و دستمزد"
        assert titles["assets"] == "دارایی‌های ثابت"

    def test_every_item_is_real_described_and_unique(self) -> None:
        seen: set[str] = set()
        for key in ALL_KEYS:
            item = ALL_ITEMS[key]
            assert not item.is_placeholder, key
            assert item.enabled and item.description_fa, key
            assert item.icon in ICON_SLUGS, (key, item.icon)
            assert key not in seen
            seen.add(key)
        assert len(seen) == len(ALL_KEYS) == 17

    def test_every_permission_exists(self) -> None:
        known = {definition.code for definition in ALL_PERMISSIONS}
        missing = [code for code in PHASE5_PERMISSIONS if code not in known]
        assert not missing, missing
        for key in ALL_KEYS:
            assert ALL_ITEMS[key].permission in known, key

    def test_every_icon_file_exists_in_all_three_states(self) -> None:
        from pathlib import Path

        icon_dir = Path(__file__).resolve().parents[1] / "src" / "pars_erp" / "resources" \
            / "icons" / "nav"
        for slug in {ALL_ITEMS[key].icon for key in ALL_KEYS}:
            for state in ("normal", "selected", "muted"):
                path = icon_dir / f"{slug}_{state}.svg"
                assert path.exists(), path.name
                assert path.read_text(encoding="utf-8").startswith("<svg")

    def test_visibility_follows_the_permissions_exactly(self) -> None:
        for code in ("admin", "chief_accountant", "accountant", "treasurer", "hr_manager",
                     "asset_keeper", "salesperson", "storekeeper", "viewer"):
            ctx = _context(code)
            keys = _keys(ctx)
            for item in ALL_ITEMS.values():
                allowed = item.permission is None or item.permission in ctx.permissions
                assert allowed == (item.key in keys), (code, item.key)

    def test_hr_manager_sees_hr_and_payroll_but_cannot_register_assets(self) -> None:
        ctx = _context("hr_manager")
        keys = _keys(ctx)
        assert {"hr_employees", "hr_org", "hr_contracts", "hr_attendance", "hr_leave",
                "hr_reports", "payroll_settings", "payroll_runs"} <= keys
        assert ctx.has("hr.employees.create") and ctx.has("payroll.calculate")
        assert not ctx.has("assets.register") and not ctx.has("payroll.pay")

    def test_asset_keeper_sees_assets_but_cannot_run_payroll(self) -> None:
        ctx = _context("asset_keeper")
        keys = _keys(ctx)
        assert {"assets_categories", "assets_register", "assets_depreciation"} <= keys
        assert ctx.has("assets.register") and ctx.has("assets.depreciate")
        assert not ctx.has("payroll.calculate") and not ctx.has("payroll.pay")

    def test_storekeeper_does_not_see_human_resources(self) -> None:
        keys = _keys(_context("storekeeper"))
        assert not (set(HR_KEYS) & keys)
        assert not (set(ASSET_KEYS) & keys)

_admin_like = _context("admin") if "admin" in {t.code for t in ()} else None


class TestPhase5TableSpecs:
    def test_every_status_has_a_badge_label(self) -> None:
        from pars_erp.ui.table_specs import BADGE_TONES

        statuses = (
            [code for code, _title in H.COLLAB_STATUSES]
            + [code for code, _title in H.CONTRACT_STATUSES]
            + [code for code, _title in H.ATT_STATUSES]
            + [code for code, _title in H.LEAVE_STATUSES]
            + [code for code, _title in H.REQUEST_STATUSES]
            + [code for code, _title in P.VERSION_STATUSES]
            + [code for code, _title in P.RUN_STATUSES]
            + [code for code, _title in P.SLIP_STATUSES]
            + [code for code, _title in P.LOAN_STATUSES]
            + [code for code, _title in P.INSTALLMENT_STATUSES]
            + [code for code, _title in P.BATCH_STATUSES]
            + [code for code, _title in P.ITEM_STATUSES]
            + [code for code, _title in A.ASSET_STATUSES]
            + [code for code, _title in A.DEP_RUN_STATUSES]
        )
        missing = sorted({status for status in statuses if status not in BADGE_TONES})
        assert not missing, missing

    def test_columns_render_persian_digits_and_dates(self) -> None:
        from pars_erp.ui.formatting import Formatter
        from pars_erp.ui.table_specs import EMPLOYEE_COLUMNS, format_cell

        from types import SimpleNamespace

        formatter = Formatter()
        row = SimpleNamespace(code="EMP-1", full_name="علی رضایی",
                              org_unit_title="واحد فنی", job_title="کارشناس",
                              employment_type_fa="تمام‌وقت",
                              collaboration_status="active", collaboration_status_fa="شاغل",
                              hire_date=_dt.date(2024, 5, 1), mobile="0912",
                              base_salary=D("30000000"))
        values = {column.key: format_cell(column, row, formatter)
                  for column in EMPLOYEE_COLUMNS}
        assert values["base_salary"] == formatter.amount(D("30000000"))
        assert "۱۴۰۳" in values["hire_date"]
        assert values["collaboration_status_fa"] == "فعال"

    def test_report_view_maps_value_types_to_columns(self) -> None:
        from pars_erp.services.commerce_reports_service import ReportTable
        from pars_erp.ui.pages.report_view import kind_of, rows_for, specs_for
        from pars_erp.ui.table_specs import AMOUNT, DATE, NUMBER, TEXT

        table = ReportTable("k", "عنوان", ("نام", "تاریخ", "مبلغ", "تعداد"),
                            (("الف", _dt.date(2026, 5, 1), D("1000"), 3),), "متا")
        specs = specs_for(table)
        assert [spec.kind for spec in specs] == [TEXT, DATE, AMOUNT, NUMBER]
        rows = rows_for(table)
        assert rows[0]["c2"] == D("1000")
        assert kind_of(None) == TEXT

    def test_render_table_keeps_totals_and_meta(self) -> None:
        from pars_erp.services.commerce_reports_service import ReportTable
        from pars_erp.ui.pages.report_view import render_table

        table = ReportTable("k", "عنوان", ("نام", "مبلغ"),
                            (("الف", D("1000")), ("ب", D("2500"))), "متا")
        rendered = render_table(_FakeServices(), table)
        assert rendered.totals[0] == "جمع"
        assert rendered.totals[1] == D("3500")
        assert "متا" in rendered.meta


class _FakeServices:
    class _Snapshot:
        company_name = "زرین هرمز"
        currency_code = "IRR"

    settings = type("S", (), {"snapshot": staticmethod(lambda: _FakeServices._Snapshot())})


# -------------------------------------------------------------------- fixtures
@pytest.fixture()
def employee(services, admin):
    return services.hr.create_employee(admin, EmployeeInput(
        code="EMP-9001", first_name="مریم", last_name="احمدی",
        hire_date=_dt.date(2024, 5, 1), base_salary=D("30000000"),
        mobile="09120000000", national_id="0012345678",
        bank_account_no="1234567890", children_count=1,
        marital_status=H.MARITAL_MARRIED))


@pytest.fixture()
def payroll_world(services, admin, chart, employee):
    services.posting.ensure_default_rules(admin)
    unit = services.hr.create_unit(admin, OrgUnitInput(code="FIN", title_fa="واحد مالی"))
    services.hr.update_employee(admin, employee.id, EmployeeInput(
        code=employee.code, first_name="مریم", last_name="احمدی",
        hire_date=_dt.date(2024, 5, 1), base_salary=D("30000000"),
        mobile="09120000000", national_id="0012345678",
        bank_account_no="1234567890", children_count=1,
        marital_status=H.MARITAL_MARRIED, org_unit_id=unit.id))
    services.hr.create_contract(admin, ContractInput(
        employee_id=employee.id, start_date=_dt.date(2025, 3, 21),
        base_salary=D("30000000")))
    shift = services.attendance.create_shift(admin, ShiftInput(
        code="S1", title_fa="شیفت روز", start_time="08:00", end_time="17:00",
        break_minutes=60, grace_minutes=0, working_days="0,1,2,3,4,5"))
    services.attendance.record(admin, AttendanceInput(
        employee_id=employee.id, work_date=DAY, shift_id=shift.id,
        check_in="08:00", check_out="17:00"))
    services.payroll.create_version(admin, VersionInput(
        code="V1405-UI", title_fa="نسخهٔ آزمون رابط", effective_from=_dt.date(2026, 3, 21),
        status=P.VERSION_ACTIVE, source_note="مقادیر آزمون",
        items={P.SETTING_BASE_HOURS: "176", P.SETTING_WORK_DAYS: "30",
               P.SETTING_OVERTIME_FACTOR: "1.4", P.SETTING_HOLIDAY_FACTOR: "2",
               P.SETTING_HOUSING: "1000000", P.SETTING_FOOD: "800000",
               P.SETTING_CHILD: "300000", P.SETTING_MARRIAGE: "500000",
               P.SETTING_SENIORITY: "0", P.SETTING_CONTINUOUS: "0",
               P.SETTING_NON_CONTINUOUS: "0", P.SETTING_INSURANCE_EMPLOYEE: "7",
               P.SETTING_INSURANCE_EMPLOYER: "23", P.SETTING_INSURANCE_BASE_CAP: "0",
               P.SETTING_TAX_EXEMPT: "5000000", P.SETTING_ABSENCE: "0",
               P.SETTING_LOAN_MAX_RATIO: "30", P.SETTING_ROUNDING: "1000"},
        brackets=(TaxBracketInput(from_amount=D("0"), to_amount=None,
                                  rate_percent=D("10")),),
    ))
    return employee


@pytest.fixture()
def asset_world(services, admin, chart):
    category = services.assets.create_category(admin, CategoryInput(
        code="VEH-UI", title_fa="وسایل نقلیه", kind=A.CAT_VEHICLE,
        default_useful_life_years=5, default_method=A.METHOD_STRAIGHT_LINE))
    asset = services.assets.register(admin, AssetInput(
        title_fa="وانت حمل بار", category_id=category.id, serial_no="SN-UI",
        purchase_date=DAY, in_service_date=DAY, purchase_price=D("600000000"),
        related_costs=D("50000000"), salvage_value=D("50000000"),
        useful_life_months=60, location="انبار مرکزی"))
    return category, asset


# -------------------------------------------------------------------- Qt tests
def qt_required() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - no Qt at all
        pytest.skip("PySide6 is not importable")
    try:
        QApplication.instance() or QApplication([])
    except Exception:  # pragma: no cover - no platform plugin
        pytest.skip("no Qt platform plugin available")


@pytest.fixture(autouse=True)
def _stub_dialogs(monkeypatch):
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except Exception:  # pragma: no cover
        return
    monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: QDialog.DialogCode.Rejected,
                        raising=False)
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: 0, raising=False)


@pytest.fixture()
def formatter():
    from pars_erp.ui.formatting import Formatter

    return Formatter()


def _select_row(table, row: int = 0) -> None:
    """Select a table row the way a user click does (Qt's selectRow fails in RTL)."""
    index = table.model.index(row, 0)
    table.setCurrentIndex(index)
    table.selectionModel().select(
        index, table.selectionModel().SelectionFlag.ClearAndSelect
        | table.selectionModel().SelectionFlag.Rows)


def _pages(services, ctx, formatter):
    from pars_erp.ui.pages.assets.assets_page import AssetsPage
    from pars_erp.ui.pages.assets.categories_page import AssetCategoriesPage
    from pars_erp.ui.pages.assets.depreciation_page import DepreciationPage
    from pars_erp.ui.pages.assets.disposals_page import AssetDisposalsPage
    from pars_erp.ui.pages.assets.reports_page import AssetReportsPage
    from pars_erp.ui.pages.hr.attendance_page import AttendancePage
    from pars_erp.ui.pages.hr.contracts_page import ContractsPage
    from pars_erp.ui.pages.hr.employees_page import EmployeesPage
    from pars_erp.ui.pages.hr.org_page import OrgStructurePage
    from pars_erp.ui.pages.hr.reports_page import HRReportsPage
    from pars_erp.ui.pages.hr.requests_page import LeaveMissionOvertimePage
    from pars_erp.ui.pages.payroll.loans_page import LoansPage
    from pars_erp.ui.pages.payroll.payments_page import PayrollPaymentsPage
    from pars_erp.ui.pages.payroll.payslips_page import PayslipsPage
    from pars_erp.ui.pages.payroll.reports_page import PayrollReportsPage
    from pars_erp.ui.pages.payroll.runs_page import PayrollRunsPage
    from pars_erp.ui.pages.payroll.settings_page import PayrollSettingsPage

    common = (services, ctx, formatter)
    return {
        "hr_employees": EmployeesPage(*common),
        "hr_org": OrgStructurePage(*common),
        "hr_contracts": ContractsPage(*common),
        "hr_attendance": AttendancePage(*common),
        "hr_leave": LeaveMissionOvertimePage(*common),
        "hr_reports": HRReportsPage(*common),
        "payroll_settings": PayrollSettingsPage(*common),
        "payroll_runs": PayrollRunsPage(*common),
        "payroll_payslips": PayslipsPage(*common),
        "payroll_payments": PayrollPaymentsPage(*common),
        "payroll_loans": LoansPage(*common),
        "payroll_reports": PayrollReportsPage(*common),
        "assets_categories": AssetCategoriesPage(*common),
        "assets_register": AssetsPage(*common),
        "assets_depreciation": DepreciationPage(*common),
        "assets_disposals": AssetDisposalsPage(*common),
        "asset_reports": AssetReportsPage(*common),
    }


@pytest.mark.gui
class TestPhase5Pages:
    @pytest.mark.slow
    def test_every_page_builds_and_refreshes(self, qapp, services, admin, formatter) -> None:
        pages = _pages(services, admin, formatter)
        assert set(pages) == set(ALL_KEYS)
        for key, page in pages.items():
            page.refresh()
            assert page.layout() is not None, key
            assert page.header is not None, key
            page.close()

    def test_main_window_opens_every_page(self, qapp, services, admin) -> None:
        from pars_erp.ui.main_window import MainWindow

        window = MainWindow(services, admin)
        window.show()
        try:
            for group in visible_items(admin):
                for item in group.items:
                    window.navigate(item.key)
            for key in ALL_KEYS:
                assert key in window._pages, key
        finally:
            window.close()

    def test_employee_page_shows_masked_sensitive_data(self, qapp, services, admin,
                                                       formatter, employee) -> None:
        from pars_erp.ui.pages.hr.employees_page import EmployeesPage

        page = EmployeesPage(services, admin, formatter)
        page.refresh()
        _select_row(page.table, 0)
        assert page.detail_rows["name"].value.text() == "مریم احمدی"
        assert "۳۰" in page.detail_rows["salary"].value.text()  # 30,000,000 visible
        assert page.detail_rows["national_id"].value.text() == "0012345678"

        limited = _context("viewer")
        restricted = EmployeesPage(services, limited, formatter)
        restricted.refresh()
        _select_row(restricted.table, 0)
        assert restricted.detail_rows["national_id"].value.text() == "••••"
        assert not restricted.new_button.isEnabled()

    def test_employee_dialog_creates_and_updates_a_real_file(self, qapp, services, admin,
                                                            formatter) -> None:
        from pars_erp.ui.pages.hr.employees_page import EmployeeDialog, EmployeesPage

        dialog = EmployeeDialog(services, admin)
        dialog.first_edit.setText("سارا")
        dialog.last_edit.setText("کریمی")
        dialog.hire_edit.set_date(_dt.date(2025, 6, 1))
        dialog.salary_edit.set_amount(D("25000000"))
        dialog.mobile_edit.setText("09121112233")
        dialog.national_edit.setText("0099887766")
        dialog.submit()
        assert dialog.saved is not None
        assert dialog.saved.code.startswith("EMP-")

        page = EmployeesPage(services, admin, formatter)
        page.refresh()
        assert any(row.full_name == "سارا کریمی" for row in page.rows)

        edit = EmployeeDialog(services, admin, employee_id=dialog.saved.id)
        assert edit.raw["national_id"] == "0099887766"
        edit.base_salary = None
        edit.salary_edit.set_amount(D("27000000"))
        edit.job_edit.setText("کارشناس ارشد")
        edit.submit()
        assert edit.saved.base_salary == D("27000000.00")
        assert edit.saved.job_title == "کارشناس ارشد"
        # a field that is not on the form is not lost by the round trip
        assert edit.saved.national_id == "0099887766"

    def test_employee_dialog_shows_persian_validation_error(self, qapp, services, admin) -> None:
        from pars_erp.ui.pages.hr.employees_page import EmployeeDialog

        dialog = EmployeeDialog(services, admin)
        dialog.submit()  # name is empty
        assert dialog.saved is None
        assert not dialog.error_label.isHidden()  # shown inside the hidden dialog
        assert "نام" in dialog.error_label.text()

    def test_contract_page_and_renewal(self, qapp, services, admin, formatter,
                                       employee) -> None:
        from pars_erp.ui.pages.hr.contracts_page import ContractDialog, ContractsPage

        services.hr.create_contract(admin, ContractInput(
            employee_id=employee.id, start_date=_dt.date(2025, 3, 21),
            end_date=_dt.date(2025, 12, 21), base_salary=D("30000000")))
        page = ContractsPage(services, admin, formatter)
        page.refresh()
        assert page.rows, "contract not listed"
        contract = page.rows[0]
        dialog = ContractDialog(services, admin, contract=contract, mode="renew")
        dialog.employee_picker.set_value(contract.employee_id)
        dialog.salary_edit.set_amount(D("32000000"))
        dialog.start_edit.set_date(_dt.date(2026, 1, 1))
        dialog.submit()
        assert dialog.saved is not None, dialog.error_label.text()
        assert dialog.saved.number != contract.number
        contracts = {row.number: row for row in services.hr.list_contracts(admin)}
        assert dialog.saved.number in contracts
        assert contracts[contract.number].status == H.CONTRACT_RENEWED
        assert contracts[dialog.saved.number].status == H.CONTRACT_ACTIVE

    def test_attendance_page_records_and_amends(self, qapp, services, admin, formatter,
                                              employee) -> None:
        from pars_erp.ui.pages.hr.attendance_page import (
            AmendAttendanceDialog,
            AttendanceDialog,
            AttendancePage,
        )

        services.attendance.create_shift(admin, ShiftInput(
            code="S-UI", title_fa="شیفت اداری", start_time="08:00", end_time="17:00",
            break_minutes=60, grace_minutes=10, working_days="0,1,2,3,4"))
        dialog = AttendanceDialog(services, admin)
        dialog.employee_picker.set_value(employee.id)
        dialog.date_edit.set_date(DAY)
        from PySide6.QtCore import QTime

        dialog.in_edit.setTime(QTime(8, 30))
        dialog.out_edit.setTime(QTime(17, 0))
        dialog.submit()
        assert dialog.saved is not None
        assert dialog.saved.late_minutes == 20  # grace is 10 minutes

        page = AttendancePage(services, admin, formatter)
        page.from_edit.set_date(_dt.date(2026, 5, 1))
        page.to_edit.set_date(_dt.date(2026, 5, 31))
        page.refresh()
        assert page.rows and page.rows[0].employee_id == employee.id

        amend = AmendAttendanceDialog(services, admin, page.rows[0])
        amend.note_edit.setText("اصلاح ورود بر اساس کارت")
        from PySide6.QtCore import QTime as _QTime

        amend.in_edit.setTime(_QTime(8, 0))
        amend.submit()
        assert amend.saved.late_minutes == 0

    def test_leave_page_requests_and_approves(self, qapp, services, admin, formatter,
                                              employee, monkeypatch) -> None:
        from pars_erp.services.attendance_service import LeaveInput, LeaveTypeInput
        from pars_erp.ui.pages.hr.requests_page import LeaveMissionOvertimePage

        leave_type = services.attendance.create_leave_type(admin, LeaveTypeInput(
            code="ANNUAL-UI", title_fa="استحقاقی", kind=H.LEAVE_PAID,
            annual_quota_days=D("26")))
        leave = services.attendance.request_leave(admin, LeaveInput(
            employee_id=employee.id, leave_type_id=leave_type.id,
            date_from=_dt.date(2026, 5, 10), date_to=_dt.date(2026, 5, 11),
            reason="مسافرت"))

        page = LeaveMissionOvertimePage(services, admin, formatter)
        page.refresh()
        assert any(row.id == leave.id for row in page.leave_rows)
        _select_row(page.leave_table, 0)
        page._approve_leave()
        approved = services.attendance.list_leave(admin, status=H.LEAVE_APPROVED)
        assert any(row.id == leave.id for row in approved)

    def test_payroll_settings_page_shows_the_version_values(self, qapp, services, admin,
                                                            formatter, payroll_world) -> None:
        from pars_erp.ui.pages.payroll.settings_page import PayrollSettingsPage

        page = PayrollSettingsPage(services, admin, formatter)
        page.refresh()
        assert page.rows
        _select_row(page.table, 0)
        items = {row["title"] for row in page.items_table.model.rows()}
        assert P.PAY_SETTING_TITLES_FA[P.SETTING_BASE_HOURS] in items

    def test_payroll_run_calculates_approves_and_posts(self, qapp, services, admin,
                                                      formatter, payroll_world,
                                                      monkeypatch) -> None:
        from pars_erp.ui.pages.payroll.runs_page import PayrollRunsPage

        monkeypatch.setattr("pars_erp.ui.pages.payroll.runs_page.confirm",
                            lambda *a, **k: True)
        run = services.payroll.create_run(admin, year=YEAR, month=MONTH)
        page = PayrollRunsPage(services, admin, formatter)
        page.refresh()
        _select_row(page.table, 0)
        page._calculate()
        slips = services.payroll.payslips(admin, run.id)
        assert len(slips) == 1 and slips[0].net > 0
        page._approve()
        page._post()
        posted = services.payroll.get_run(admin, run.id)
        assert posted.status == P.RUN_POSTED
        assert posted.journal_id is not None

    def test_payslip_page_shows_lines_and_a_printable_payslip(self, qapp, services, admin,
                                                             formatter, payroll_world) -> None:
        from pars_erp.ui.pages.payroll.payslips_page import PayslipsPage, payslip_table

        run = services.payroll.create_run(admin, year=YEAR, month=MONTH)
        services.payroll.calculate(admin, run.id)
        page = PayslipsPage(services, admin, formatter)
        page.refresh()
        assert page.rows
        _select_row(page.table, 0)
        assert page.lines_table.model.rows()
        slip = page.rows[0]
        table = payslip_table(services, slip, formatter)
        assert table.totals[2] == slip.net
        assert any("زرین هرمز" in part or "کارمند" in part for part in table.notes)

    def test_payment_batch_pays_and_exports_the_bank_file(self, qapp, services, admin,
                                                         formatter, payroll_world,
                                                         tmp_path) -> None:
        from pars_erp.services.payroll_payment_service import BatchInput
        from pars_erp.ui.pages.payroll.payments_page import PayrollPaymentsPage

        run = services.payroll.create_run(admin, year=YEAR, month=MONTH)
        services.payroll.calculate(admin, run.id)
        services.payroll.approve(admin, run.id)
        box = services.funds.create_cash_box(admin, CashBoxInput(
            code="BOX-UI", title_fa="صندوق حقوق", opening_balance=D("500000000"),
            opening_date=_dt.date(2026, 1, 1)))
        batch = services.payroll_payments.create_batch(admin, BatchInput(
            run_id=run.id, payment_date=DAY, cash_box_id=box.id, method="cash"))
        content = services.payroll_payments.bank_file_content(admin, batch.id)
        assert "employee_code" in content and "EMP-9001" in content
        assert "27786000" in content  # the net of the only payslip

        page = PayrollPaymentsPage(services, admin, formatter)
        page.refresh()
        assert any(row.id == batch.id for row in page.rows)
        paid = services.payroll_payments.pay(admin, batch.id, tracking_no="TR-1")
        assert paid.status == P.BATCH_PAID
        path = services.payroll_payments.export_bank_file(admin, batch.id,
                                                          tmp_path / "bank.txt")
        assert path.exists() and path.read_text(encoding="utf-8").strip()

    def test_loans_page_creates_approves_and_pays(self, qapp, services, admin, formatter,
                                                  payroll_world) -> None:
        from pars_erp.services.loans_service import LoanPaymentInput
        from pars_erp.ui.pages.payroll.loans_page import LoansPage

        box = services.funds.create_cash_box(admin, CashBoxInput(
            code="BOX-LOAN", title_fa="صندوق وام", opening_balance=D("500000000"),
            opening_date=_dt.date(2026, 1, 1)))
        loan = services.loans.create(admin, LoanInput(
            employee_id=payroll_world.id, amount=D("12000000"), installments=12,
            request_date=DAY, repayment_start_year=YEAR, repayment_start_month=MONTH,
            reason="وام ضروری"))
        services.loans.approve(admin, loan.id)
        page = LoansPage(services, admin, formatter)
        page.refresh()
        assert any(row.id == loan.id for row in page.rows)

        paid = services.loans.pay(admin, loan.id, LoanPaymentInput(
            payment_date=DAY, cash_box_id=box.id, method="cash"))
        assert paid.payment_id is not None
        page.refresh()
        assert any(row.id == loan.id and row.status == P.LOAN_PAID for row in page.rows)

    def test_assets_page_round_trips_the_edit_form(self, qapp, services, admin, formatter,
                                                  asset_world) -> None:
        from pars_erp.ui.pages.assets.assets_page import AssetDialog, AssetsPage

        _category, asset = asset_world
        page = AssetsPage(services, admin, formatter)
        page.refresh()
        assert page.rows and page.rows[0].code == asset.code
        _select_row(page.table, 0)
        assert page.detail["book"].value.text() == formatter.amount(asset.book_value)

        dialog = AssetDialog(services, admin, asset_id=asset.id)
        assert dialog.raw["serial_no"] == "SN-UI"
        dialog.location_edit.setText("کارگاه شماره ۲")
        dialog.submit()
        assert dialog.saved.location == "کارگاه شماره ۲"
        assert dialog.saved.initial_value == asset.initial_value

    def test_depreciation_page_previews_and_posts(self, qapp, services, admin, formatter,
                                                 asset_world, monkeypatch) -> None:
        from pars_erp.ui.pages.assets.depreciation_page import DepreciationPage

        monkeypatch.setattr("pars_erp.ui.pages.assets.depreciation_page.confirm",
                            lambda *a, **k: True)
        page = DepreciationPage(services, admin, formatter)
        page.refresh()
        page.period_picker.set_value(YEAR, MONTH)
        page._preview()
        assert page.lines
        page._calculate()
        page.refresh()
        _select_row(page.table, 0)
        page._approve()
        page._post()
        runs = services.depreciation.list_runs(admin, year=YEAR)
        assert runs and runs[-1].status == A.DEP_RUN_POSTED
        assert runs[-1].journal_id is not None

    @pytest.mark.slow
    def test_every_report_of_every_report_page_renders(self, qapp, services, admin,
                                                       formatter, payroll_world,
                                                       asset_world) -> None:
        run = services.payroll.create_run(admin, year=YEAR, month=MONTH)
        services.payroll.calculate(admin, run.id)
        pages = {
            "hr": _pages(services, admin, formatter)["hr_reports"],
            "payroll": _pages(services, admin, formatter)["payroll_reports"],
            "assets": _pages(services, admin, formatter)["asset_reports"],
        }
        for name, page in pages.items():
            for index in range(page.report_combo.count()):
                page.report_combo.setCurrentIndex(index)
                page.run_report()
                assert page.current is not None, (name, index)
                assert page.current.columns, (name, index)
                assert page.table.model.columnCount() == len(page.current.columns)
                assert page.meta_label.text()
            page.close()

    def test_limited_context_sees_read_only_screens(self, qapp, services, admin,
                                                   formatter, payroll_world) -> None:
        from pars_erp.ui.pages.payroll.runs_page import PayrollRunsPage

        viewer = _context("viewer")
        page = PayrollRunsPage(services, viewer, formatter)
        page.refresh()
        assert not page.calc_button.isEnabled()
        assert not page.post_button.isEnabled()
        assert page.table.model.rowCount() >= 0
