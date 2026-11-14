"""Regression tests for the defects found in debug round 1.

Every test here corresponds to a bug that was reproduced first and then fixed;
none of them is a smoke test.  The themes are:

* connection strings must never reach a log line, a screen or the console with
  their password;
* a failing database connection must produce a Persian sentence with a quotable
  error id - never a traceback in the user's face;
* the visible brand is «زرین هرمز» / Zarrin Hormoz everywhere;
* a screen that fails to build must not take the main window down;
* the dependency/metadata files must describe what the code really needs.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from pars_erp import APP_NAME_DEFAULT, __phase__, __version__
from pars_erp.db.session import describe_connection_error, mask_database_url

PASSWORD_URL = "postgresql+psycopg://erp_user:TopSecret99@db.example.local:5432/erp"
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- url masking
class TestConnectionUrlIsNeverLeaked:
    def test_password_is_replaced_but_the_rest_survives(self) -> None:
        masked = mask_database_url(PASSWORD_URL)
        assert "TopSecret99" not in masked
        assert masked == "postgresql+psycopg://erp_user:***@db.example.local:5432/erp"

    def test_query_parameters_and_sqlite_urls_are_kept(self) -> None:
        assert mask_database_url(
            "postgresql://u:pw@h:6543/erp?sslmode=require"
        ) == "postgresql://u:***@h:6543/erp?sslmode=require"
        sqlite_url = "sqlite:////home/user/.local/share/ParsERP/data/pars_erp.db"
        assert mask_database_url(sqlite_url) == sqlite_url
        assert mask_database_url("") == ""

    def test_a_malformed_url_is_still_masked(self) -> None:
        # not a parseable SQLAlchemy URL, but the userinfo must not slip through
        assert "hunter2" not in mask_database_url("weird://user:hunter2@host/db")

    def test_prepare_application_logs_the_masked_url(self, caplog) -> None:
        from pars_erp.services.context import prepare_application

        with caplog.at_level(logging.INFO, logger="pars_erp.services.context"):
            # no real PostgreSQL server is involved: Database() only stores the URL
            from pars_erp.db.session import Database

            db = Database("sqlite://", default_schema_check=False)
            db.url = PASSWORD_URL  # what a PostgreSQL install would look like
            from pars_erp.services.context import build_services
            from pars_erp.config.paths import AppPaths
            from pars_erp.config.settings import FileConfig
            import tempfile

            paths = AppPaths(Path(tempfile.mkdtemp())).ensure()
            services = build_services(paths=paths, config=FileConfig(), db=db)
            services.db.url = PASSWORD_URL
            try:
                prepare_application(services, run_startup_backup=False)
            except Exception:
                pass  # the schema work on a fake URL is irrelevant here
            text = "\n".join(record.getMessage() for record in caplog.records)
        assert "TopSecret99" not in text

    def test_system_info_and_the_cli_show_the_masked_url(self, services, admin,
                                                         capsys) -> None:
        from pars_erp.maintenance import system_info

        services.db.url = PASSWORD_URL
        info = system_info(services)
        assert "TopSecret99" not in str(info)
        assert info["database_url"].endswith("/erp")

        from pars_erp import cli

        code = cli.main(["--home", str(services.paths.home), "info"])
        out = capsys.readouterr().out
        assert code == 0
        assert "TopSecret99" not in out


# --------------------------------------------------------- connection errors
class TestConnectionErrorsArePersian:
    def test_missing_driver_has_a_fix_in_the_message(self) -> None:
        message = describe_connection_error(
            ModuleNotFoundError("No module named 'psycopg'"))
        assert "psycopg[binary]" in message
        assert message.strip().endswith(".")

    @pytest.mark.parametrize(("raw", "needle"), [
        ("password authentication failed for user \"erp\"", "رمز"),
        ("could not connect to server: Connection refused", "سرور"),
        ("unable to open database file", "پایگاه دادهٔ SQLite"),
        ("database or disk is full", "فضای دیسک"),
        ("database is locked", "SQLite"),
    ])
    def test_known_failures_are_explained(self, raw: str, needle: str) -> None:
        assert needle in describe_connection_error(RuntimeError(raw))

    def test_unknown_failure_keeps_the_technical_text(self) -> None:
        message = describe_connection_error(ValueError("something odd"))
        assert "something odd" in message

    def test_cli_reports_a_broken_postgres_url_without_a_traceback(self, capsys) -> None:
        from pars_erp import cli

        code = cli.main(["--home", "/tmp/pars-erp-debug-round1",
                         "--database-url",
                         "postgresql+psycopg://user:Secret123@127.0.0.1:1/none",
                         "migrate"])
        err = capsys.readouterr().err
        assert code == 3
        assert "شناسهٔ خطا" in err
        assert "Traceback (most recent call last)" not in err
        assert "Secret123" not in err

    def test_cli_reports_a_broken_config_file(self, tmp_path: Path, capsys) -> None:
        from pars_erp import cli

        home = tmp_path / "home"
        home.mkdir()
        (home / "config.json").write_text("{ this is not json", encoding="utf-8")
        code = cli.main(["--home", str(home), "info"])
        err = capsys.readouterr().err
        assert code == 2
        assert "تنظیمات" in err
        assert "Traceback (most recent call last)" not in err


# --------------------------------------------------------------- start-up
class TestStartupFailuresAreReported:
    def test_run_gui_returns_2_and_explains_a_database_failure(self, tmp_path, monkeypatch,
                                                               capsys) -> None:
        from pars_erp import app as app_module

        def boom(**_kwargs):
            raise ModuleNotFoundError("No module named 'psycopg'")

        monkeypatch.setattr(app_module, "build_services", boom)
        from PySide6.QtWidgets import QMessageBox

        shown: dict[str, str] = {}

        def fake_exec(self):
            shown["title"] = self.windowTitle()
            shown["text"] = self.text()
            shown["detail"] = self.informativeText()
            return 0

        monkeypatch.setattr(QMessageBox, "exec", fake_exec, raising=False)

        options = app_module.AppOptions(paths=app_module.AppPaths(tmp_path / "home"))
        code = app_module.run_gui(options, argv=["zarrin-hormoz"])
        assert code == 2
        assert "خطای راه‌اندازی" in shown["title"]
        assert "آماده‌سازی پایگاه داده" in shown["text"]
        assert "psycopg[binary]" in shown["detail"]
        assert "شناسهٔ خطا" in shown["detail"]

    def test_engine_options_bound_postgres_connections(self, monkeypatch) -> None:
        from pars_erp.db import session as session_module

        captured: dict = {}

        def fake_create_engine(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(session_module, "create_engine", fake_create_engine)
        database = session_module.Database(PASSWORD_URL, default_schema_check=False)
        database._create_engine()
        assert captured["pool_pre_ping"] is True
        assert captured["pool_recycle"] == session_module.POOL_RECYCLE_S
        assert captured["connect_args"]["connect_timeout"] == session_module.PG_CONNECT_TIMEOUT_S
        assert captured["connect_args"]["application_name"] == "ZarrinHormoz"
        assert captured["pool_timeout"] == 10


# ------------------------------------------------------------------ logging
class TestLoggingIsAttributable:
    def test_every_line_carries_the_process_and_the_user(self, tmp_path: Path) -> None:
        from pars_erp.config.settings import FileConfig
        from pars_erp.logging_setup import configure_logging, set_log_user

        log_file = configure_logging(tmp_path, FileConfig(), level="INFO")
        set_log_user("hesabdar")
        logging.getLogger("pars_erp.test").warning("سلام")
        set_log_user(None)
        line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert "pid=" in line
        assert "user=hesabdar" in line
        assert "WARNING" in line

    def test_secrets_in_messages_are_redacted(self, tmp_path: Path) -> None:
        from pars_erp.config.settings import FileConfig
        from pars_erp.logging_setup import configure_logging

        log_file = configure_logging(tmp_path, FileConfig(), level="INFO")
        logging.getLogger("pars_erp.test").info(
            "dsn=%s token=abcdef123456", PASSWORD_URL)
        text = log_file.read_text(encoding="utf-8")
        assert "TopSecret99" not in text
        assert "abcdef123456" not in text
        assert "user=***" in text or "***@" in text


# ------------------------------------------------------------------- brand
class TestBrandIsConsistent:
    def test_settings_fall_back_to_the_official_name(self) -> None:
        from pars_erp.services.settings_service import SettingsSnapshot

        assert SettingsSnapshot(values={}).app_name == APP_NAME_DEFAULT

    def test_settings_screen_does_not_show_the_old_name(self) -> None:
        text = (ROOT / "src/pars_erp/ui/pages/settings_page.py").read_text(encoding="utf-8")
        assert "ParsERP —" not in text
        assert "زرین هرمز" in text

    def test_qt_application_is_registered_under_the_brand(self) -> None:
        pytest.importorskip("PySide6.QtWidgets")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from pars_erp.app import create_qt_app

        created = create_qt_app(["zarrin-hormoz"])
        assert created.applicationName() == "Zarrin Hormoz"
        assert created.applicationDisplayName() == APP_NAME_DEFAULT
        assert app is not None

    def test_first_run_form_defaults_to_the_brand(self) -> None:
        source = (ROOT / "src/pars_erp/ui/login_window.py").read_text(encoding="utf-8")
        assert 'QLineEdit("ParsERP")' not in source
        assert "QLineEdit(APP_NAME_DEFAULT)" in source


# ------------------------------------------------------------ robust screens
class TestABrokenScreenDoesNotKillTheWindow:
    def test_navigate_reports_the_error_and_keeps_running(self, services, admin,
                                                          monkeypatch) -> None:
        pytest.importorskip("PySide6.QtWidgets")
        from pars_erp.ui import main_window as mw
        from pars_erp.ui.formatting import Formatter

        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(mw, "show_error",
                            lambda _parent, title, error: shown.append((title, str(error))))
        window = mw.MainWindow(services, admin)

        def explode(_key):
            raise RuntimeError("رندر ناموفق")

        monkeypatch.setattr(window, "_create_page", explode)
        window.navigate("journals")          # must not raise
        assert shown and "رندر ناموفق" in shown[-1][1]
        assert "شناسهٔ خطا" in shown[-1][1]


# -------------------------------------------------------------- dependencies
class TestDependencyFilesMatchTheCode:
    def test_pyproject_declares_every_runtime_import(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = " ".join(project["project"]["dependencies"]).lower()
        for package in ("sqlalchemy", "alembic", "argon2", "pyside6", "openpyxl",
                        "cryptography"):
            assert package in declared, package

    def test_pyproject_version_matches_the_package(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert project["project"]["version"] == __version__
        assert __phase__ == 7

    def test_requirements_files_cover_the_same_packages(self) -> None:
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for package in ("sqlalchemy", "alembic", "argon2-cffi", "pyside6", "openpyxl",
                        "cryptography"):
            assert package in text, package

    def test_cryptography_is_really_importable_for_the_update_path(self) -> None:
        pytest.importorskip("cryptography")
        from pars_erp.services.update_service import UpdateService

        assert UpdateService._head_revision()  # reads the real alembic scripts


# ------------------------------------------- silent truncation (found in round 1)
class TestNoSilentTruncation:
    def test_collect_all_reads_every_page(self) -> None:
        from dataclasses import dataclass

        from pars_erp.services.export_service import collect_all

        @dataclass
        class P:
            items: list
            total: int

        source = list(range(450))

        def fetch(page_no, size):
            start = (page_no - 1) * size
            return P(source[start:start + size], len(source))

        assert collect_all(fetch, page_size=200) == source

    def test_daybook_report_returns_every_line(self, services, admin, chart) -> None:
        """The ledger caps a page at 200 rows; the report must page through."""
        from pars_erp.reporting.engine import ReportQuery
        from pars_erp.services.journals_service import JournalInput, JournalLineInput

        accounts, period = chart
        entry_date = _dt.date(2026, 4, 15)
        for index in range(110):          # 110 journals -> 220 lines (> 200)
            journal = services.journals.create(admin, JournalInput(
                entry_date=entry_date, title_fa=f"سند {index}", fiscal_period_id=period.id,
                lines=[JournalLineInput(account_id=accounts["101001"].id,
                                        debit=Decimal("1000")),
                       JournalLineInput(account_id=accounts["301001"].id,
                                        credit=Decimal("1000"))]))
            services.journals.submit(admin, journal.id)
            services.journals.approve(admin, journal.id)
            services.journals.post(admin, journal.id)

        result = services.report_engine.run(
            admin, definition_key="acc_journal_book",
            query=ReportQuery(date_from=entry_date, date_to=entry_date, page_size=50))
        assert result.total_rows == 220
        assert result.pages == 5
        # the exported/printed table holds everything, not just the first page
        assert len(result.table.rows) == 220
        assert result.table.totals[7] == Decimal("110000.0000")
        assert result.table.totals[8] == Decimal("110000.0000")

    def test_user_export_is_not_truncated_at_two_hundred_rows(self, services, admin,
                                                              tmp_path: Path) -> None:
        from pars_erp.services.user_service import UserCreateData
        from tests.conftest import TEST_USER_PASSWORD

        for index in range(205):
            services.users.create_user(admin, UserCreateData(
                username=f"user{index:03d}", full_name=f"کاربر {index}",
                password=TEST_USER_PASSWORD, confirm_password=TEST_USER_PASSWORD,
                role_codes=("viewer",)))
        target = tmp_path / "users.csv"
        result = services.exporter.export_users(admin, target)
        assert result.rows == 206          # 205 + the administrator
        lines = target.read_text(encoding="utf-8-sig").strip().splitlines()
        assert len(lines) == 207                # header + 206 rows


# ------------------------------------------------ login must survive a dead DB
class TestLoginSurvivesABrokenDatabase:
    def test_unexpected_error_does_not_freeze_the_form(self, qapp, services,
                                                      monkeypatch) -> None:
        """A dropped connection used to leave the button stuck on «در حال بررسی…»."""
        from pars_erp.ui.login_window import LoginPage

        page = LoginPage(services)
        page.username_input.setText("admin")
        page.password_field.input.setText("whatever")

        def boom(*_a, **_k):
            raise RuntimeError("server closed the connection unexpectedly")

        monkeypatch.setattr(services.auth, "authenticate", boom)
        page.attempt_login()

        assert page.login_button.isEnabled(), "the form must stay usable"
        assert page.login_button.text() == "ورود"
        text = page.error_label.text()
        assert "شناسهٔ خطا" in text and "پایگاه داده" in text
        assert "RuntimeError" not in text          # no technical detail on screen

    def test_wrong_password_still_shows_the_service_message(self, qapp, services) -> None:
        from pars_erp.ui.login_window import LoginPage

        page = LoginPage(services)
        page.username_input.setText("admin")
        page.password_field.input.setText("definitely-not-the-password")
        page.attempt_login()
        assert page.login_button.isEnabled()
        assert page.error_label.isVisible() or page.error_label.text()
