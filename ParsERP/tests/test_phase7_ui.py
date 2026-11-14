"""Phase-7 screens: navigation, report centre, designer, alerts, dashboard, about.

The Qt-free tests always run; the GUI tests build the real widgets and are skipped
when no Qt platform is available, so a green run never claims a screen was drawn
when it was not. Every GUI assertion is made against documents the service layer
wrote to the database or against files the exporter actually produced.
"""

from __future__ import annotations

import datetime as _dt
import zipfile
from dataclasses import replace
from decimal import Decimal

import pytest

from pars_erp.security.permissions import SecurityContext
from pars_erp.ui.navigation import ALL_ITEMS, NAV_GROUPS, visible_items

NEW_KEYS = ("management_dashboard", "report_center", "report_designer", "alerts", "about")
ENTRY_DATE = _dt.date(2026, 4, 15)


def _role_permissions(code: str) -> tuple[str, ...]:
    from pars_erp.security.permissions import DEFAULT_ROLE_TEMPLATES

    for template in DEFAULT_ROLE_TEMPLATES:
        if template.code == code:
            return tuple(template.permissions)
    return ()


def _context(code: str) -> SecurityContext:
    return SecurityContext(user_id=99, username=code, full_name=f"کاربر {code}",
                           role_codes=(code,), permissions=frozenset(_role_permissions(code)))


def _keys(ctx) -> set[str]:
    return {item.key for group in visible_items(ctx) for item in group.items}


# ------------------------------------------------------------------ navigation
class TestPhase7Navigation:
    def test_reporting_group_exists_before_commerce(self) -> None:
        keys = [group.key for group in NAV_GROUPS]
        assert "reporting" in keys
        assert keys.index("overview") < keys.index("reporting") < keys.index("commerce")

    def test_new_items_are_real_and_iconed(self) -> None:
        for key in NEW_KEYS:
            item = ALL_ITEMS[key]
            assert item.description_fa
            assert not item.is_placeholder
            assert item.permission is None or item.permission in {
                "dashboard.view", "reports.center", "reports.designer", "alerts.view"}

    def test_visibility_follows_permissions(self) -> None:
        for code in ("admin", "accountant", "viewer", "storekeeper"):
            ctx = _context(code)
            keys = _keys(ctx)
            for item in ALL_ITEMS.values():
                if item.permission and item.key in keys:
                    assert item.permission in ctx.permissions
            assert ("report_center" in keys) == ("reports.center" in ctx.permissions)
            assert ("alerts" in keys) == ("alerts.view" in ctx.permissions)
        # everybody may read the About screen
        assert "about" in _keys(_context("storekeeper"))

    def test_designer_is_not_offered_to_everyone(self) -> None:
        assert "report_designer" in _keys(_context("chief_accountant"))
        assert "report_designer" not in _keys(_context("storekeeper"))


# ---------------------------------------------------------------------- about
def test_about_page_data_is_real() -> None:
    from pars_erp import __version__
    from pars_erp.ui.pages.about_page import LIBRARIES

    assert __version__
    names = {name for name, _licence, _usage in LIBRARIES}
    assert "PySide6 (Qt for Python)" in names
    assert all(licence and usage for _name, licence, usage in LIBRARIES)


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
        from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
    except Exception:  # pragma: no cover
        return
    monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: QDialog.DialogCode.Rejected,
                        raising=False)
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: 0, raising=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)


@pytest.fixture()
def formatter():
    from pars_erp.ui.formatting import Formatter

    return Formatter()


def _post_journal(services, ctx, title="سند گزارش"):
    from pars_erp.services.journals_service import JournalInput, JournalLineInput

    accounts = {row.code: row for row in
                services.accounts.list_accounts(ctx, level="subsidiary")}
    journal = services.journals.create(ctx, JournalInput(
        entry_date=ENTRY_DATE, title_fa=title,
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("1000000")),
               JournalLineInput(account_id=accounts["301001"].id, credit=Decimal("1000000"))]))
    services.journals.submit(ctx, journal.id)
    services.journals.approve(ctx, journal.id)
    return services.journals.post(ctx, journal.id)


class TestReportCentreGui:
    @pytest.mark.slow
    def test_centre_lists_only_permitted_reports_and_runs_one(self, qapp, services, admin,
                                                             chart, formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.reports.center_page import ReportCenterPage

        _post_journal(services, admin)
        page = ReportCenterPage(services, admin, formatter)
        assert page.section_combo.count() >= 1
        page.date_from.set_date(ENTRY_DATE)
        page.date_to.set_date(ENTRY_DATE)
        index = page.source_combo.findData("acc_journal_book")
        assert index >= 0
        page.source_combo.setCurrentIndex(index)
        page.run_report()
        assert page._result is not None
        assert page._result.total_rows == 2
        assert page.table.model.rowCount() == 2
        # a report the role may not run is not in the list at all
        limited = replace(admin, permissions=frozenset({"reports.center"}))
        restricted = ReportCenterPage(services, limited, formatter)
        assert restricted.source_combo.count() == 0

    def test_exports_from_the_screen_write_real_files(self, qapp, services, admin, chart,
                                                     formatter, tmp_path) -> None:
        qt_required()
        from pars_erp.ui.pages.reports.center_page import ReportCenterPage

        _post_journal(services, admin, title="سند خروجی صفحه")
        page = ReportCenterPage(services, admin, formatter)
        page.date_from.set_date(ENTRY_DATE)
        page.date_to.set_date(ENTRY_DATE)
        page.source_combo.setCurrentIndex(page.source_combo.findData("acc_journal_book"))
        page.run_report()

        csv_path = tmp_path / "screen.csv"
        page.export_to("csv", str(csv_path))
        assert "سند خروجی صفحه" in csv_path.read_text(encoding="utf-8-sig")

        xlsx_path = tmp_path / "screen.xlsx"
        page.export_to("xlsx", str(xlsx_path))
        assert zipfile.ZipFile(xlsx_path).testzip() is None

        pdf_path = tmp_path / "screen.pdf"
        page.export_to("pdf", str(pdf_path))
        assert pdf_path.read_bytes()[:4] == b"%PDF"

    def test_saving_a_report_from_the_screen_persists_it(self, qapp, services, admin, chart,
                                                         formatter) -> None:
        qt_required()
        from pars_erp.services.report_engine_service import SaveReportInput
        from pars_erp.ui.pages.reports.center_page import ReportCenterPage

        saved = services.report_engine.save(admin, SaveReportInput(
            name="گزارش صفحه", definition_key="acc_journal_book"))
        page = ReportCenterPage(services, admin, formatter)
        page._fill_saved()
        index = page.saved_combo.findData(saved.id)
        assert index >= 0
        page.saved_combo.setCurrentIndex(index)
        assert page._result is not None
        assert page._result.definition_key == "acc_journal_book"


class TestDesignerGui:
    def test_designer_saves_a_report_and_previews_it(self, qapp, services, admin, chart,
                                                    formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.reports.designer_page import ReportDesignerPage

        _post_journal(services, admin, title="سند طراح")
        page = ReportDesignerPage(services, admin, formatter)
        page.name_edit.setText("طراح روزنامه")
        page.source_combo.setCurrentIndex(page.source_combo.findData("acc_journal_book"))
        page.page_size_box.setValue(50)
        page.date_from.set_date(ENTRY_DATE)
        page.date_to.set_date(ENTRY_DATE)
        page.save()
        saved = services.report_engine.saved_reports(admin)
        assert [row.name for row in saved] == ["طراح روزنامه"]

        page.preview()
        assert page.table.model.rowCount() >= 1

    def test_designer_is_hidden_from_a_role_without_the_permission(self, qapp, services, admin,
                                                                  formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.reports.designer_page import ReportDesignerPage

        viewer = _context("storekeeper")
        page = ReportDesignerPage(services, viewer, formatter)
        assert page.source_combo.count() == 0


class TestAlertsGui:
    def test_alerts_page_lists_rules_and_can_evaluate(self, qapp, services, admin, formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.reports.alerts_page import AlertsPage

        services.alerts.set_rule(admin, "backup_stale", threshold={"hours": 1})
        page = AlertsPage(services, admin, formatter)
        assert page.rules_table.model.rowCount() >= 3
        page.evaluate()
        assert page.table.model.rowCount() >= 1
        assert services.alerts.open_count(admin) >= 1


class TestDashboardsGui:
    def test_management_dashboard_renders_real_cards(self, qapp, services, admin, chart,
                                                    formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.management_dashboard_page import ManagementDashboardPage

        page = ManagementDashboardPage(services, admin, formatter)
        page.refresh()
        assert page._cards, "an admin must see at least the sales and treasury cards"
        titles = [card.title_label.text() for card in page._cards]
        assert "ماندهٔ صندوق‌ها" in titles

    def test_card_click_requests_navigation(self, qapp, services, admin, chart, formatter) -> None:
        qt_required()
        from pars_erp.ui.pages.management_dashboard_page import ManagementDashboardPage

        visited: list[str] = []
        page = ManagementDashboardPage(services, admin, formatter, on_navigate=visited.append)
        page.refresh()
        page._navigate("report_center")
        assert visited == ["report_center"]

    def test_about_page_shows_the_brand_and_version(self, qapp, services, admin, formatter) -> None:
        qt_required()
        from pars_erp import APP_NAME_DEFAULT, __version__
        from pars_erp.ui.pages.about_page import AboutPage

        page = AboutPage(services, admin, formatter)
        labels = [child.text() for child in page.findChildren(type(page.support_label))]
        assert APP_NAME_DEFAULT in labels
        assert __version__ in labels

    def test_about_page_checks_for_updates_honestly(self, qapp, services, admin, formatter,
                                                    tmp_path, monkeypatch) -> None:
        qt_required()
        from pars_erp.ui.pages.about_page import AboutPage

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr("pars_erp.ui.pages.about_page.show_error",
                            lambda _p, title, exc: shown.append(("error", str(exc))))
        monkeypatch.setattr("pars_erp.ui.pages.about_page.show_info",
                            lambda _p, title, message, details=None: shown.append(
                                ("info", message)))
        page = AboutPage(services, admin, formatter)
        # no source configured -> the screen says so and offers nothing to install
        assert "تنظیم نشده" in page.update_status_label.text()
        assert page.stage_button.isEnabled() is False
        page.check_for_updates()
        assert "تنظیم نشده" in page.update_status_label.text()
        assert page.stage_button.isEnabled() is False

        # a real manifest listing a newer release
        import hashlib
        import json

        from pars_erp.services.update_service import MANIFEST_FORMAT

        package = tmp_path / "setup.bin"
        package.write_bytes(b"installer")
        manifest = tmp_path / "releases.json"
        manifest.write_text(json.dumps({
            "format": MANIFEST_FORMAT,
            "releases": [{
                "version": "0.9.9", "released_at": "2026-11-01",
                "notes_fa": ["گزارش تازه"], "url": str(package),
                "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "size_bytes": package.stat().st_size,
            }]}), encoding="utf-8")
        services.settings.update(admin, {"update_source": str(manifest),
                                        "update_require_signature": False})
        page = AboutPage(services, admin, formatter)
        page.check_for_updates()
        assert "0.9.9" in page.update_status_label.text()
        assert page.update_notes_label.isVisible() or "گزارش تازه" in page.update_notes_label.text()
        assert page.stage_button.isEnabled() is True

        page.stage_update()
        assert services.updates.pending() is not None
        assert shown and shown[-1][0] == "info"
        assert "آماده" in page.update_status_label.text()
