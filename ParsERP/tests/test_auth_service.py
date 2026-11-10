"""Authentication, lockout, sessions and password management."""

from __future__ import annotations

import datetime as dt

import pytest

from pars_erp.core.errors import (
    AccountInactiveError,
    AccountLockedError,
    AuthenticationError,
    PasswordPolicyError,
    SetupAlreadyCompletedError,
    ValidationError,
)
from pars_erp.security.permissions import ADMIN_ROLE_CODE
from pars_erp.services.audit_service import EventType
from pars_erp.services.auth_service import SetupStatus
from pars_erp.services.context import AppServices
from pars_erp.services.user_service import UserCreateData
from tests.conftest import ADMIN_PASSWORD, TEST_USER_PASSWORD


class TestSetup:
    def test_fresh_database_requires_setup(self, services: AppServices) -> None:
        status = services.auth.setup_status()
        assert isinstance(status, SetupStatus)
        assert status.needs_setup is True
        assert status.user_count == 0
        assert status.has_active_admin is False

    def test_initial_admin_creation(self, services: AppServices, admin) -> None:
        status = services.auth.setup_status()
        assert status.needs_setup is False
        assert status.has_active_admin is True
        assert admin.username == "admin"
        assert ADMIN_ROLE_CODE in admin.role_codes
        assert admin.is_admin
        # the administrator receives every permission in the catalogue
        from pars_erp.security.permissions import ALL_PERMISSION_CODES
        assert set(admin.permissions) == set(ALL_PERMISSION_CODES)

    def test_setup_cannot_run_twice(self, services: AppServices, admin) -> None:
        with pytest.raises(SetupAlreadyCompletedError):
            services.auth.create_initial_admin(
                full_name="مهاجم", username="admin2", password="AnotherPass123",
                confirm_password="AnotherPass123")

    def test_setup_rejects_mismatched_confirmation(self, services: AppServices) -> None:
        with pytest.raises(ValidationError):
            services.auth.create_initial_admin(
                full_name="مدیر", username="admin", password="ValidPass1234",
                confirm_password="ValidPass9999")

    def test_setup_rejects_weak_password(self, services: AppServices) -> None:
        with pytest.raises(PasswordPolicyError):
            services.auth.create_initial_admin(
                full_name="مدیر", username="admin", password="weak",
                confirm_password="weak")

    def test_setup_rejects_invalid_username(self, services: AppServices) -> None:
        with pytest.raises(ValidationError):
            services.auth.create_initial_admin(
                full_name="مدیر", username="مدیر", password="ValidPass1234",
                confirm_password="ValidPass1234")

    def test_setup_stores_company_name(self, services: AppServices, admin) -> None:
        assert services.settings.snapshot().company_name == "شرکت آزمون"

    def test_setup_writes_events(self, services: AppServices, admin) -> None:
        page = services.audit.list_security_events(page_size=50)
        types = [row.event_type for row in page.items]
        assert EventType.SETUP_COMPLETED in types
        assert EventType.LOGIN_SUCCESS in types


class TestLogin:
    def test_successful_login_creates_session(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        assert ctx.username == "admin"
        assert ctx.session_id is not None
        sessions = services.auth.open_sessions()
        assert len(sessions) == 2  # setup session + this login

    def test_username_is_case_insensitive_and_trimmed(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("  ADMIN ", ADMIN_PASSWORD)
        assert ctx.username == "admin"

    @pytest.mark.parametrize("username,password", [("admin", "wrong-pass-1"), ("ghost", "whatever-1")])
    def test_failure_is_generic(self, services: AppServices, admin, username, password) -> None:
        with pytest.raises(AuthenticationError) as excinfo:
            services.auth.authenticate(username, password)
        assert "نام کاربری یا رمز عبور نادرست است" in str(excinfo.value)

    def test_failed_login_is_logged(self, services: AppServices, admin) -> None:
        with pytest.raises(AuthenticationError):
            services.auth.authenticate("admin", "wrong-pass-1")
        events = services.audit.list_security_events(page_size=10).items
        assert events[0].event_type == EventType.LOGIN_FAILED
        # no password material may appear in the event payload
        assert "wrong-pass-1" not in str(events[0].details)

    def test_lockout_after_max_attempts(self, services: AppServices, admin) -> None:
        limit = services.settings.snapshot().max_failed_attempts
        for _ in range(limit):
            with pytest.raises(AuthenticationError):
                services.auth.authenticate("admin", "bad-password-1")
        with pytest.raises(AccountLockedError) as excinfo:
            services.auth.authenticate("admin", ADMIN_PASSWORD)
        assert excinfo.value.minutes_left and excinfo.value.minutes_left >= 1
        events = [e.event_type for e in services.audit.list_security_events(page_size=30).items]
        assert EventType.ACCOUNT_LOCKED in events

    def test_admin_can_unlock_and_user_can_login_again(self, services: AppServices, admin) -> None:
        limit = services.settings.snapshot().max_failed_attempts
        for _ in range(limit):
            with pytest.raises(AuthenticationError):
                services.auth.authenticate("admin", "bad-password-1")
        admin_ctx = services.auth.authenticate("admin", ADMIN_PASSWORD) if False else admin
        services.auth.unlock_user(admin_ctx, admin.user_id)
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        assert ctx.user_id == admin.user_id

    def test_successful_login_resets_failed_counter(self, services: AppServices, admin) -> None:
        with pytest.raises(AuthenticationError):
            services.auth.authenticate("admin", "bad-password-1")
        services.auth.authenticate("admin", ADMIN_PASSWORD)
        row = services.users.get_user(admin, admin.user_id)
        assert row.failed_login_attempts == 0
        assert row.is_locked is False

    def test_inactive_user_cannot_login(self, services: AppServices, admin, accountant) -> None:
        services.users.set_active(admin, accountant.user_id, False)
        with pytest.raises(AccountInactiveError):
            services.auth.authenticate("hesabdar", TEST_USER_PASSWORD)

    def test_locked_until_in_past_allows_login(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        # simulate an expired lock
        with services.db.session_scope() as session:
            from pars_erp.db.models import User
            user = session.get(User, ctx.user_id)
            user.locked_until = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        assert services.auth.authenticate("admin", ADMIN_PASSWORD).username == "admin"


class TestSessions:
    def test_logout_closes_session(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        services.auth.logout(ctx)
        remaining = [s for s in services.auth.open_sessions() if s.id == ctx.session_id]
        assert remaining == []

    def test_lock_and_unlock_session(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        services.auth.lock_session(ctx)
        locked = [s for s in services.auth.open_sessions() if s.id == ctx.session_id][0]
        assert locked.is_locked is True
        with pytest.raises(AuthenticationError):
            services.auth.unlock_session(ctx, "wrong-password-1")
        services.auth.unlock_session(ctx, ADMIN_PASSWORD)
        unlocked = [s for s in services.auth.open_sessions() if s.id == ctx.session_id][0]
        assert unlocked.is_locked is False

    def test_session_events_recorded(self, services: AppServices, admin) -> None:
        ctx = services.auth.authenticate("admin", ADMIN_PASSWORD)
        services.auth.lock_session(ctx, reason="idle")
        services.auth.unlock_session(ctx, ADMIN_PASSWORD)
        services.auth.logout(ctx)
        types = [e.event_type for e in services.audit.list_security_events(page_size=40).items]
        for expected in (EventType.SESSION_LOCKED, EventType.UNLOCK_SUCCESS, EventType.LOGOUT):
            assert expected in types

    def test_verify_password_helper(self, services: AppServices, admin) -> None:
        assert services.auth.verify_password(admin, ADMIN_PASSWORD) is True
        assert services.auth.verify_password(admin, "nope-123456") is False


class TestPasswordChange:
    def test_user_changes_own_password(self, services: AppServices, admin) -> None:
        services.auth.change_password(
            admin, current_password=ADMIN_PASSWORD, new_password="NewSecret1234",
            confirm_password="NewSecret1234")
        with pytest.raises(AuthenticationError):
            services.auth.authenticate("admin", ADMIN_PASSWORD)
        assert services.auth.authenticate("admin", "NewSecret1234").username == "admin"

    def test_wrong_current_password_is_rejected(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError) as excinfo:
            services.auth.change_password(admin, current_password="bad-pass-123",
                                          new_password="NewSecret1234",
                                          confirm_password="NewSecret1234")
        assert "رمز عبور فعلی نادرست است" in str(excinfo.value)

    def test_new_password_must_follow_policy(self, services: AppServices, admin) -> None:
        with pytest.raises(PasswordPolicyError):
            services.auth.change_password(admin, current_password=ADMIN_PASSWORD,
                                          new_password="123", confirm_password="123")

    def test_reusing_same_password_is_rejected(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.auth.change_password(admin, current_password=ADMIN_PASSWORD,
                                          new_password=ADMIN_PASSWORD,
                                          confirm_password=ADMIN_PASSWORD)

    def test_confirmation_must_match(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.auth.change_password(admin, current_password=ADMIN_PASSWORD,
                                          new_password="NewSecret1234",
                                          confirm_password="NewSecret4321")

    def test_changing_password_closes_other_sessions(self, services: AppServices, admin) -> None:
        other = services.auth.authenticate("admin", ADMIN_PASSWORD)
        services.auth.change_password(admin, current_password=ADMIN_PASSWORD,
                                      new_password="NewSecret1234",
                                      confirm_password="NewSecret1234")
        still_open = [s.id for s in services.auth.open_sessions(user_id=admin.user_id)]
        assert other.session_id not in still_open
        assert admin.session_id in still_open

    def test_admin_resets_another_users_password(self, services: AppServices, admin) -> None:
        services.users.create_user(admin, UserCreateData(
            username="karbar", full_name="کاربر آزمایشی", password=TEST_USER_PASSWORD,
            confirm_password=TEST_USER_PASSWORD, role_codes=("viewer",)))
        target = services.auth.authenticate("karbar", TEST_USER_PASSWORD)
        services.auth.reset_password_by_admin(admin, user_id=target.user_id,
                                              new_password="TempPass12345",
                                              confirm_password="TempPass12345")
        ctx = services.auth.authenticate("karbar", "TempPass12345")
        assert ctx.must_change_password is True

    def test_admin_cannot_reset_own_password_via_admin_path(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.auth.reset_password_by_admin(admin, user_id=admin.user_id,
                                                  new_password="TempPass12345",
                                                  confirm_password="TempPass12345")

    def test_reset_requires_permission(self, services: AppServices, admin, accountant) -> None:
        from pars_erp.core.errors import PermissionDeniedError
        with pytest.raises(PermissionDeniedError):
            services.auth.reset_password_by_admin(accountant, user_id=admin.user_id,
                                                  new_password="TempPass12345",
                                                  confirm_password="TempPass12345")

    def test_reset_events_do_not_leak_passwords(self, services: AppServices, admin) -> None:
        services.users.create_user(admin, UserCreateData(
            username="karbar2", full_name="کاربر دوم", password=TEST_USER_PASSWORD,
            confirm_password=TEST_USER_PASSWORD, role_codes=("viewer",)))
        row = services.users.list_users(admin, search="karbar2").items[0]
        services.auth.reset_password_by_admin(admin, user_id=row.id,
                                              new_password="TempPass12345",
                                              confirm_password="TempPass12345")
        events = services.audit.list_security_events(page_size=50).items
        assert EventType.PASSWORD_RESET in [e.event_type for e in events]
        for event in events:
            assert "TempPass12345" not in (event.message_fa + str(event.details))
