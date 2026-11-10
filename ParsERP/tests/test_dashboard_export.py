"""Dashboard aggregates and CSV export."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

import pars_erp

from pars_erp.core.errors import PermissionDeniedError
from pars_erp.services.audit_service import EventType, SecurityEventFilter
from pars_erp.services.context import AppServices
from pars_erp.services.export_service import CSV_BOM, rows_to_csv
from pars_erp.services.user_service import UserCreateData
from tests.conftest import TEST_USER_PASSWORD


class TestDashboard:
    def test_overview_reflects_real_data(self, services: AppServices, admin) -> None:
        services.users.create_user(admin, UserCreateData(
            username="dash1", full_name="کاربر داشبورد", password=TEST_USER_PASSWORD,
            confirm_password=TEST_USER_PASSWORD, role_codes=("viewer",)))
        overview = services.dashboard.overview(admin)
        assert overview.users_total == 2
        assert overview.users_active == 2
        assert overview.roles_total >= 5
        assert overview.users_must_change_password == 1
        assert overview.app_version == pars_erp.__version__
        assert overview.backend == "sqlite"
        assert overview.database_size_bytes and overview.database_size_bytes > 0
        assert overview.schema_revision is not None

    def test_failed_logins_are_counted(self, services: AppServices, admin) -> None:
        for _ in range(3):
            with pytest.raises(Exception):
                services.auth.authenticate("admin", "wrong-password-1")
        overview = services.dashboard.overview(admin)
        assert overview.failed_logins_24h >= 3
        assert overview.failed_logins_7d >= 3
        assert len(overview.failed_login_series) == 7
        assert all(point.label_fa for point in overview.failed_login_series)

    def test_sessions_and_logins_today(self, services: AppServices, admin) -> None:
        services.auth.authenticate("admin", "ModirPass1234")
        overview = services.dashboard.overview(admin)
        assert overview.logins_today >= 2
        assert overview.sessions_open >= 2

    def test_recent_events_only_with_audit_permission(self, services: AppServices, admin,
                                                      accountant) -> None:
        admin_view = services.dashboard.overview(admin)
        assert admin_view.recent_events
        keep = services.roles.list_roles(admin)
        role = [r for r in keep if r.code == "accountant"][0]
        services.roles.update_role(admin, role.id, title_fa=role.title_fa,
                                   permissions=("dashboard.view",))
        ctx = services.auth.reload_context(accountant)
        accountant_view = services.dashboard.overview(ctx)
        assert accountant_view.recent_events == ()

    def test_backup_status(self, services: AppServices, admin) -> None:
        assert services.dashboard.overview(admin).backup_is_stale is True
        services.backups.create_backup(admin)
        overview = services.dashboard.overview(admin)
        assert overview.backup_is_stale is False
        assert overview.backup_count == 1
        assert overview.last_backup_label

    def test_dashboard_requires_permission(self, services: AppServices) -> None:
        from pars_erp.security.permissions import build_context
        empty = build_context(user_id=99, username="nobody", full_name="—", role_codes=(), 
                              permissions=())
        with pytest.raises(PermissionDeniedError):
            services.dashboard.overview(empty)


class TestExport:
    def test_csv_helpers(self) -> None:
        text = rows_to_csv(["الف", "ب"], [["۱", "۲"], [None, "x"]])
        assert text.startswith(CSV_BOM)
        parsed = list(csv.reader(io.StringIO(text.lstrip(CSV_BOM))))
        assert parsed[0] == ["الف", "ب"]
        assert parsed[1] == ["۱", "۲"]
        assert parsed[2] == ["", "x"]

    def test_export_users(self, services: AppServices, admin, tmp_path: Path) -> None:
        services.users.create_user(admin, UserCreateData(
            username="exportme", full_name="کاربر خروجی", password=TEST_USER_PASSWORD,
            confirm_password=TEST_USER_PASSWORD, role_codes=("viewer",)))
        target = tmp_path / "users.csv"
        result = services.exporter.export_users(admin, target)
        assert result.rows == 2
        content = target.read_text(encoding="utf-8")
        assert content.startswith(CSV_BOM)
        assert "exportme" in content
        assert "کاربر خروجی" in content

    def test_export_security_events_requires_permission(self, services: AppServices,
                                                        accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            services.exporter.export_security_events(accountant)

    def test_export_security_events(self, services: AppServices, admin, tmp_path: Path) -> None:
        target = tmp_path / "events.csv"
        result = services.exporter.export_security_events(
            admin, target, filters=SecurityEventFilter(event_type=EventType.LOGIN_SUCCESS))
        assert result.rows >= 1
        assert "ورود موفق" in target.read_text(encoding="utf-8")

    def test_export_is_atomic(self, services: AppServices, admin, tmp_path: Path) -> None:
        target = tmp_path / "atomic.csv"
        services.exporter.export_users(admin, target)
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".export_")]
        assert leftovers == []
