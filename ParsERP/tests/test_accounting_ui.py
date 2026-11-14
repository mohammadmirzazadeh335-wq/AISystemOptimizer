"""Accounting screens: navigation catalogue, permissions and report plumbing.

Most of these tests are Qt-free on purpose: they assert the rules the UI relies
on (which menu entries a role may see, that every accounting page key maps to a
permission that really exists, that report tables are built from posted
documents only). One smoke test builds the real widgets and is skipped when Qt
cannot be imported.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.accounting import constants as C
from pars_erp.security.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_TEMPLATES
from pars_erp.services.context import AppServices
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.report_render_service import ReportTable
from pars_erp.ui.navigation import ALL_ITEMS, NAV_GROUPS, first_page_key, visible_items

ACCOUNTING_KEYS = (
    "acc_dashboard", "accounts", "journals", "acc_periods", "journal_book",
    "general_ledger", "subsidiary_ledger", "turnover", "trial_balance",
    "balance_sheet", "income_statement", "acc_dimensions", "acc_currencies",
    "acc_settings",
)


def _permission_codes() -> set[str]:
    return {definition.code for definition in ALL_PERMISSIONS}





class TestNavigation:
    def test_accounting_group_exists_and_is_visible_in_order(self) -> None:
        keys = [group.key for group in NAV_GROUPS]
        assert "accounting" in keys
        assert keys.index("accounting") < keys.index("administration")
        group = next(group for group in NAV_GROUPS if group.key == "accounting")
        assert group.title_fa == "حسابداری مالی"
        assert len(group.items) == len(ACCOUNTING_KEYS)

    def test_every_accounting_page_is_real(self) -> None:
        for key in ACCOUNTING_KEYS:
            item = ALL_ITEMS[key]
            assert not item.is_placeholder, f"{key} is still a placeholder"
            assert item.enabled is True
            assert item.description_fa, f"{key} has no description"

    def test_every_item_requires_a_known_permission(self) -> None:
        known = _permission_codes()
        # phase 7 added informational screens («دربارهٔ زرین هرمز») that carry no
        # permission because they expose no business data; every other item must
        # point at a permission that really exists.
        permissionless = {key for key, item in ALL_ITEMS.items() if item.permission is None}
        assert permissionless <= {"about"}, permissionless
        for item in ALL_ITEMS.values():
            if item.is_placeholder or item.permission is None:
                continue
            assert item.permission in known, f"{item.key}: unknown permission"
        # the accounting menu must only point at accounting-style permissions;
        # commerce entries are covered by their own suite.
        for item in ALL_ITEMS.values():
            if item.group != "accounting":
                continue
            assert item.permission.startswith(
                ("accounts", "journals", "reports", "periods", "dimensions",
                 "accounting")), item.permission

    def test_viewer_sees_reports_but_not_settings(self, services: AppServices, admin) -> None:
        from pars_erp.services.user_service import UserCreateData
        from tests.conftest import TEST_USER_PASSWORD

        services.users.create_user(admin, UserCreateData(
            username="nazer", full_name="کاربر ناظر", password=TEST_USER_PASSWORD,
            confirm_password=TEST_USER_PASSWORD, role_codes=("viewer",)))
        viewer_ctx = services.auth.authenticate("nazer", TEST_USER_PASSWORD)
        keys = {item.key for group in visible_items(viewer_ctx) for item in group.items}
        assert "trial_balance" in keys
        assert "balance_sheet" in keys
        assert "journal_book" in keys
        assert "acc_settings" not in keys      # read-only role cannot reconfigure
        assert "acc_periods" in keys           # may read period status
        assert not viewer_ctx.has("periods.create")
        assert "journals" in keys              # but may read documents
        assert viewer_ctx.has("journals.view")
        assert not viewer_ctx.has("journals.post")

    def test_first_page_is_the_management_dashboard(self, services: AppServices, admin) -> None:
        # phase 7 made the management dashboard the landing screen; the phase-1
        # system dashboard is still one click away and must remain visible.
        assert first_page_key(admin) == "management_dashboard"
        visible = {item.key for group in visible_items(admin) for item in group.items}
        assert "dashboard" in visible

    def test_roles_that_can_account_see_the_section(self, services: AppServices,
                                                    admin, accountant) -> None:
        keys = {item.key for group in visible_items(accountant) for item in group.items}
        for key in ("accounts", "journals", "trial_balance", "acc_dashboard", "acc_periods"):
            assert key in keys
        assert "acc_settings" not in keys


class TestPermissionTemplates:
    def test_accountant_cannot_close_periods_or_change_settings(self) -> None:
        template = next(t for t in DEFAULT_ROLE_TEMPLATES if t.code == "accountant")
        assert "periods.close" not in template.permissions
        assert "accounting.settings" not in template.permissions
        assert "journals.post" not in template.permissions  # separation of duties
        assert {"journals.create", "journals.submit"} <= template.permissions

    def test_chief_accountant_holds_the_posting_rights(self) -> None:
        template = next(t for t in DEFAULT_ROLE_TEMPLATES if t.code == "chief_accountant")
        assert {"journals.approve", "journals.post", "journals.void",
                "periods.close"} <= template.permissions

    def test_viewer_has_no_write_permission(self) -> None:
        template = next(t for t in DEFAULT_ROLE_TEMPLATES if t.code == "viewer")
        offenders = [code for code in template.permissions
                     if code.split(".")[-1] in ("create", "edit", "delete", "post",
                                                "approve", "void", "reverse", "close")]
        assert offenders == []

    def test_admin_has_every_accounting_permission(self) -> None:
        template = next(t for t in DEFAULT_ROLE_TEMPLATES if t.code == "admin")
        accounting = {code for code in _permission_codes()
                      if code.split(".")[0] in ("accounts", "details", "journals",
                                                "reports", "periods", "dimensions")
                      or code == "accounting.settings"}
        assert accounting <= template.permissions


class TestReportDataFlow:
    """The tables the screens render must come from posted documents only."""

    def _post(self, services: AppServices, ctx, *, day: int, title: str,
              lines: list[tuple[int, Decimal, Decimal]], post: bool = True):
        journal = services.journals.create(ctx, JournalInput(
            entry_date=_dt.date(2026, 4, day), title_fa=title,
            lines=[JournalLineInput(account_id=account_id, debit=debit, credit=credit)
                   for account_id, debit, credit in lines]))
        services.journals.submit(ctx, journal.id)
        services.journals.approve(ctx, journal.id)
        if post:
            services.journals.post(ctx, journal.id)
        return journal

    def test_draft_documents_never_reach_the_reports(self, services: AppServices,
                                                     admin, chart) -> None:
        from pars_erp.ui import report_tables
        from pars_erp.ui.formatting import Formatter

        accounts = services.accounts.list_accounts(admin, level=C.LEVEL_SUBSIDIARY)
        self._post(services, admin, day=10, title="سند ثبت‌شده",
                   lines=[(accounts[0].id, Decimal(1000), Decimal(0)),
                          (accounts[1].id, Decimal(0), Decimal(1000))])
        self._post(services, admin, day=11, title="سند پیش‌نویس",
                   lines=[(accounts[0].id, Decimal(500), Decimal(0)),
                          (accounts[1].id, Decimal(0), Decimal(500))], post=False)
        report = report_tables.trial_balance_table(
            services, admin, Formatter(), start=_dt.date(2026, 4, 1),
            end=_dt.date(2026, 4, 30), mode=6)
        assert isinstance(report, ReportTable)
        assert report.totals[-2] == Decimal(1000), "a non-posted document leaked in"
        assert report.totals[-1] == Decimal(1000)

    def test_balances_survive_the_rendered_table(self, services: AppServices,
                                                 admin, chart) -> None:
        from pars_erp.ui import report_tables
        from pars_erp.ui.formatting import Formatter

        accounts = services.accounts.list_accounts(admin, level=C.LEVEL_SUBSIDIARY)
        capital = next(account for account in accounts if account.code.startswith("3"))
        cash = accounts[0]
        self._post(services, admin, day=12, title="سرمایه",
                   lines=[(cash.id, Decimal(250_000), Decimal(0)),
                          (capital.id, Decimal(0), Decimal(250_000))])
        report = report_tables.balance_sheet_table(
            services, admin, Formatter(), as_of=_dt.date(2026, 4, 30))
        labels = {row[1]: row[2] for row in report.rows}
        assert any(label.startswith("جمع دارایی") for label in labels)
        assert labels.get("اختلاف") == 0
        assert report.currency_code == Formatter().currency_code

    def test_journal_book_rows_and_totals(self, services: AppServices, admin, chart) -> None:
        from pars_erp.ui import report_tables
        from pars_erp.ui.formatting import Formatter

        accounts = services.accounts.list_accounts(admin, level=C.LEVEL_SUBSIDIARY)
        for day in range(1, 4):
            self._post(services, admin, day=day, title=f"سند {day}",
                       lines=[(accounts[0].id, Decimal(10), Decimal(0)),
                              (accounts[1].id, Decimal(0), Decimal(10))])
        report, page = report_tables.journal_book_table(
            services, admin, Formatter(), start=_dt.date(2026, 4, 1),
            end=_dt.date(2026, 4, 30))
        assert len(report.rows) == 6  # three documents × two lines
        assert page.total == 6
        assert report.totals[-1] == Decimal(30)

    def test_subsidiary_ledger_running_balance(self, services: AppServices,
                                               admin, chart) -> None:
        from pars_erp.ui import report_tables
        from pars_erp.ui.formatting import Formatter

        accounts = services.accounts.list_accounts(admin, level=C.LEVEL_SUBSIDIARY)
        cash = accounts[0]
        self._post(services, admin, day=1, title="واریز",
                   lines=[(cash.id, Decimal(100), Decimal(0)),
                          (accounts[1].id, Decimal(0), Decimal(100))])
        self._post(services, admin, day=2, title="برداشت",
                   lines=[(accounts[1].id, Decimal(40), Decimal(0)),
                          (cash.id, Decimal(0), Decimal(40))])
        report = report_tables.subsidiary_ledger_table(
            services, admin, Formatter(), account_id=cash.id,
            start=_dt.date(2026, 4, 1), end=_dt.date(2026, 4, 30))
        balances = [row[-1] for row in report.rows[1:-1]]
        assert balances == [Decimal(100), Decimal(60)]
        assert report.rows[-1][-1] == Decimal(60)

    def test_empty_ledger_explains_itself(self, services: AppServices, admin, chart) -> None:
        from pars_erp.ui import report_tables
        from pars_erp.ui.formatting import Formatter

        report = report_tables.subsidiary_ledger_table(
            services, admin, Formatter(), account_id=None,
            start=_dt.date(2026, 4, 1), end=_dt.date(2026, 4, 30))
        assert report.is_empty
        assert any("حساب" in note for note in report.notes)


def _qt_available() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.gui
@pytest.mark.skipif(not _qt_available(), reason="Qt is not installed")
class TestWidgetsSmoke:
    def test_jalali_picker_round_trip(self) -> None:
        from PySide6.QtWidgets import QApplication

        from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit

        app = QApplication.instance() or QApplication([])
        widget = JalaliDateEdit(_dt.date(2026, 3, 21))
        assert widget.edit.text() == "۱۴۰۵/۰۱/۰۱"
        assert widget.date() == _dt.date(2026, 3, 21)
        widget.edit.setText("۱۴۰۵/۱۲/۲۹")
        widget._on_edited()
        assert widget.date() == _dt.date(2027, 3, 20)
        widget.edit.setText("۱۴۰۵/۱۳/۰۱")  # impossible month keeps the old value
        widget._on_edited()
        assert widget.date() == _dt.date(2027, 3, 20)
        assert app is not None

    def test_money_edit_never_loses_precision(self) -> None:
        from PySide6.QtWidgets import QApplication

        from pars_erp.ui.pages.accounting.widgets import MoneyEdit

        QApplication.instance() or QApplication([])
        widget = MoneyEdit()
        widget.setText("۱۲٬۳۴۵٬۶۷۸٫۹۱")
        assert widget.amount == Decimal("12345678.91")
        assert isinstance(widget.amount, Decimal)
        widget.set_amount(Decimal("0.05"))
        assert widget.amount == Decimal("0.05")
