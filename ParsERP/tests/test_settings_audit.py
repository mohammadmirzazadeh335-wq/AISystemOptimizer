"""Settings registry, validation and the audit/security log readers."""

from __future__ import annotations

import datetime as dt

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.audit_service import AuditFilter, EventType, SecurityEventFilter
from pars_erp.services.context import AppServices
from pars_erp.services.settings_service import SETTING_DEFS, SettingsService


class TestSettings:
    def test_defaults_without_overrides(self, services: AppServices) -> None:
        snapshot = services.settings.snapshot()
        assert snapshot.app_name == "زرین هرمز"   # official product brand
        assert snapshot.currency_code == "IRR"
        assert snapshot.theme == "light"
        assert snapshot.font_size == 11
        assert snapshot.persian_digits is True
        assert snapshot.idle_lock_minutes == 10

    def test_snapshot_reflects_overrides(self, services: AppServices, admin) -> None:
        services.settings.update(admin, {"app_name": "حساب‌یار", "theme": "dark",
                                         "font_size": 13, "company_name": "شرکت نمونه"})
        snapshot = services.settings.snapshot()
        assert snapshot.app_name == "حساب‌یار"
        assert snapshot.theme == "dark"
        assert snapshot.font_size == 13
        assert snapshot.company_name == "شرکت نمونه"

    def test_validation_rules(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"theme": "rainbow"})
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"font_size": 2})
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"font_size": "big"})
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"currency_code": "GBP"})
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"app_name": "x" * 41})
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"not_a_setting": 1})

    def test_all_values_validated_before_any_write(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.settings.update(admin, {"theme": "dark", "font_size": 999})
        assert services.settings.snapshot().theme == "light"

    def test_requires_permission(self, services: AppServices, admin, accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            services.settings.update(accountant, {"theme": "dark"})
        # reading is always allowed (the login window needs it)
        assert services.settings.snapshot().theme == "light"

    def test_no_change_returns_empty(self, services: AppServices, admin) -> None:
        assert services.settings.update(admin, {"theme": "light"}) == {}
        changed = services.settings.update(admin, {"theme": "dark"})
        assert changed == {"theme": "dark"}
        assert services.settings.update(admin, {"theme": "dark"}) == {}

    def test_change_is_audited(self, services: AppServices, admin) -> None:
        services.settings.update(admin, {"idle_lock_minutes": 5})
        entries = services.audit.list_audit_logs(
            AuditFilter(entity_type="app_setting")).items
        assert entries and "idle_lock_minutes" in str(entries[0].after_data)
        events = services.audit.list_security_events(
            SecurityEventFilter(event_type=EventType.SETTINGS_UPDATED)).items
        assert events

    def test_reset_to_defaults(self, services: AppServices, admin) -> None:
        services.settings.update(admin, {"font_size": 15})
        services.settings.reset_to_defaults(admin, ["font_size"])
        assert services.settings.snapshot().font_size == 11

    def test_registry_metadata_is_complete(self) -> None:
        for definition in SETTING_DEFS:
            assert definition.label_fa
            assert definition.group
            if definition.type == "choice":
                assert definition.choices
                assert any(choice[0] == definition.default for choice in definition.choices)
            definition.coerce(definition.default)  # defaults must be valid

    def test_corrupted_value_falls_back_to_default(self, services: AppServices, admin) -> None:
        from pars_erp.db.models import AppSetting
        with services.db.session_scope() as session:
            session.add(AppSetting(key="font_size", value="huge"))
        assert services.settings.snapshot().font_size == 11

    def test_persian_digits_and_boolean_coercion(self, services: AppServices, admin) -> None:
        services.settings.update(admin, {"persian_digits": "false", "font_size": "۱۲"})
        snapshot = services.settings.snapshot()
        assert snapshot.persian_digits is False
        assert snapshot.font_size == 12

    def test_grouping_for_ui(self) -> None:
        grouped = SettingsService.definitions_by_group()
        assert set(grouped) == {"general", "appearance", "security", "backup",
                                "accounting", "commerce", "treasury"}
        assert any(d.key == "app_name" for d in grouped["general"])


class TestAuditLog:
    def test_filters_and_paging(self, services: AppServices, admin) -> None:
        for _ in range(5):
            services.audit.log_security(event_type="test.event", message_fa="رویداد آزمایشی",
                                        severity="warning", username="tester")
        page = services.audit.list_security_events(
            SecurityEventFilter(event_type="test.event"), page=1, page_size=2)
        assert page.total == 5
        assert len(page.items) == 2
        assert page.pages == 3
        by_user = services.audit.list_security_events(
            SecurityEventFilter(username="tester"), page_size=10)
        assert by_user.total == 5
        by_search = services.audit.list_security_events(
            SecurityEventFilter(search="آزمایشی"), page_size=10)
        assert by_search.total == 5

    def test_date_range_filter(self, services: AppServices, admin) -> None:
        old = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        services.audit.log_security(event_type="test.old", message_fa="قدیمی", occurred_at=old)
        recent = services.audit.list_security_events(
            SecurityEventFilter(date_from=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)))
        assert all(e.occurred_at >= dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
                   for e in recent.items)

    def test_sensitive_payload_is_redacted(self, services: AppServices, admin) -> None:
        services.audit.log_security(
            event_type="test.secret", message_fa="آزمون پوشش داده حساس",
            details={"password": "SuperSecret123", "nested": {"token": "abc", "ok": 1}})
        row = services.audit.recent_events(limit=1)[0]
        assert row.details["password"] == "***"
        assert row.details["nested"]["token"] == "***"
        assert row.details["nested"]["ok"] == 1

    def test_event_titles_are_persian(self, services: AppServices, admin) -> None:
        row = services.audit.recent_events(limit=1)[0]
        assert row.event_title_fa and row.severity_title_fa
        assert all(ord(ch) < 128 or "\u0600" <= ch <= "\u06ff" for ch in row.event_title_fa)

    def test_diff_helper(self) -> None:
        from pars_erp.services.audit_service import AuditService
        diff = AuditService.diff({"name": "a", "phone": "1"}, {"name": "b", "phone": "1"})
        assert diff == {"name": {"before": "a", "after": "b"}}

    def test_failed_login_series_has_seven_points(self, services: AppServices, admin) -> None:
        with pytest.raises(Exception):
            services.auth.authenticate("admin", "wrong-1")
        series = services.audit.failed_login_series(days=7)
        assert len(series) == 7
        assert sum(value for _, value in series) >= 1
