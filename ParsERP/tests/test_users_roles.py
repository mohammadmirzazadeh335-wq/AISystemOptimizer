"""User and role administration, including the guard rails."""

from __future__ import annotations

import pytest

from pars_erp.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from pars_erp.security.permissions import ADMIN_ROLE_CODE, ALL_PERMISSION_CODES
from pars_erp.services.audit_service import EventType
from pars_erp.services.context import AppServices
from pars_erp.services.user_service import UserCreateData, UserUpdateData
from tests.conftest import ADMIN_PASSWORD, TEST_USER_PASSWORD


def make_user(services: AppServices, admin, username="mostafa", roles=("viewer",), **kwargs):
    return services.users.create_user(admin, UserCreateData(
        username=username, full_name=kwargs.pop("full_name", "مصطفی احمدی"),
        password=kwargs.pop("password", TEST_USER_PASSWORD),
        confirm_password=kwargs.pop("password", TEST_USER_PASSWORD),
        role_codes=roles, **kwargs))


class TestUserCreation:
    def test_create_and_read_back(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, email="mostafa@example.com", phone="09121234567")
        assert row.username == "mostafa"
        assert row.role_codes == ("viewer",)
        assert row.must_change_password is True
        fetched = services.users.get_user(admin, row.id)
        assert fetched.full_name == "مصطفی احمدی"
        assert fetched.email == "mostafa@example.com"

    def test_created_user_has_hashed_password(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, username="hashem")
        with services.db.session_scope() as session:
            from pars_erp.db.models import User
            user = session.get(User, row.id)
            assert user.password_hash.startswith("$argon2id$")
            assert TEST_USER_PASSWORD not in user.password_hash
        assert services.auth.authenticate("hashem", TEST_USER_PASSWORD).username == "hashem"

    def test_duplicate_username_rejected(self, services: AppServices, admin) -> None:
        make_user(services, admin, username="dup")
        with pytest.raises(ConflictError):
            make_user(services, admin, username="DUP")

    def test_validation_errors(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            make_user(services, admin, username="ab")            # too short
        with pytest.raises(ValidationError):
            make_user(services, admin, username="bad name")
        with pytest.raises(ValidationError):
            make_user(services, admin, roles=())                  # no role
        with pytest.raises(ValidationError):
            make_user(services, admin, roles=("no_such_role",))

    def test_permission_enforced_in_service_layer(self, services: AppServices, admin,
                                                  accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            make_user(services, accountant, username="hacker")

    def test_non_admin_cannot_grant_admin_role(self, services: AppServices, admin,
                                               accountant) -> None:
        # give the accountant the ability to create users, but not to grant admin
        role = [r for r in services.roles.list_roles(admin) if r.code == "accountant"][0]
        services.roles.update_role(admin, role.id, title_fa=role.title_fa, description="",
                                   permissions=tuple(set(role.permission_codes) | {"users.create"}))
        ctx = services.auth.reload_context(services.auth.authenticate("hesabdar", TEST_USER_PASSWORD))
        with pytest.raises(PermissionDeniedError):
            make_user(services, ctx, username="sneaky", roles=("admin",))

    def test_audit_and_security_events_written(self, services: AppServices, admin) -> None:
        make_user(services, admin, username="logged")
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.USER_CREATED in events
        audits = services.audit.list_audit_logs(page_size=20).items
        assert any(a.entity_type == "user" and a.action == "create" for a in audits)
        assert all("password" not in str(a.after_data or {}) or
                   str(a.after_data).count("***") > 0 for a in audits)


class TestUserUpdates:
    def test_update_fields_and_roles(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, username="editable")
        updated = services.users.update_user(admin, row.id, UserUpdateData(
            full_name="نام تازه", role_codes=("accountant",), email="new@example.com"))
        assert updated.full_name == "نام تازه"
        assert updated.role_codes == ("accountant",)
        assert updated.version == row.version + 1

    def test_role_change_is_audited(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, username="rolechange")
        services.users.update_user(admin, row.id, UserUpdateData(
            full_name=row.full_name, role_codes=("accountant",)))
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.USER_ROLES_CHANGED in events

    def test_cannot_demote_last_active_admin(self, services: AppServices, admin) -> None:
        with pytest.raises(ConflictError):
            services.users.update_user(admin, admin.user_id, UserUpdateData(
                full_name=admin.full_name, role_codes=("accountant",)))

    def test_cannot_deactivate_self(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.users.set_active(admin, admin.user_id, False)

    def test_admin_self_deactivation_is_blocked(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, username="otheradmin", roles=("admin",))
        with pytest.raises(ValidationError):
            services.users.set_active(admin, admin.user_id, False)
        # another administrator may be deactivated while one active admin remains
        services.users.set_active(admin, row.id, False)
        assert services.users.get_user(admin, row.id).is_active is False

    def test_non_admin_cannot_disable_protected_account(self, services: AppServices, admin) -> None:
        role = services.roles.create_role(admin, code="useradmin", title_fa="مدیر کاربران",
                                          permissions=("users.view", "users.disable"))
        make_user(services, admin, username="useradmin1", roles=("useradmin",))
        ctx = services.auth.reload_context(
            services.auth.authenticate("useradmin1", TEST_USER_PASSWORD))
        with pytest.raises(PermissionDeniedError):
            services.users.set_active(ctx, admin.user_id, False)

    def test_deactivate_and_reactivate(self, services: AppServices, admin) -> None:
        row = make_user(services, admin, username="toggle")
        services.users.set_active(admin, row.id, False)
        assert services.users.get_user(admin, row.id).is_active is False
        services.users.set_active(admin, row.id, True)
        assert services.users.get_user(admin, row.id).is_active is True
        events = [e.event_type for e in services.audit.list_security_events(page_size=30).items]
        assert EventType.USER_DISABLED in events and EventType.USER_ENABLED in events

    def test_unknown_user(self, services: AppServices, admin) -> None:
        with pytest.raises(NotFoundError):
            services.users.get_user(admin, 99999)


class TestUserListing:
    def test_search_status_and_paging(self, services: AppServices, admin) -> None:
        for index in range(12):
            make_user(services, admin, username=f"user{index:02d}",
                      full_name=f"کاربر شماره {index}")
        services.users.set_active(admin, make_user(services, admin, username="offuser").id, False)
        page1 = services.users.list_users(admin, page=1, page_size=5)
        assert page1.total == 14  # 13 created + admin
        assert len(page1.items) == 5
        assert page1.pages == 3
        assert services.users.list_users(admin, search="offuser").total == 1
        assert services.users.list_users(admin, status="inactive").total == 1
        assert services.users.list_users(admin, role_code="admin").total == 1
        page4 = services.users.list_users(admin, page=99, page_size=5)
        assert page4.page == page4.pages

    def test_listing_requires_permission(self, services: AppServices, accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            services.users.list_users(accountant)


class TestRoles:
    def test_default_roles_exist(self, services: AppServices, admin) -> None:
        roles = services.roles.list_roles(admin)
        codes = {r.code for r in roles}
        assert {"admin", "accountant", "storekeeper", "salesperson", "viewer"} <= codes
        admin_role = [r for r in roles if r.code == ADMIN_ROLE_CODE][0]
        assert set(admin_role.permission_codes) == set(ALL_PERMISSION_CODES)
        assert admin_role.member_count == 1

    def test_create_custom_role(self, services: AppServices, admin) -> None:
        role = services.roles.create_role(admin, code="auditor", title_fa="بازرس",
                                          description="فقط مشاهده",
                                          permissions=("dashboard.view", "audit.view"))
        assert role.is_system is False
        assert set(role.permission_codes) == {"dashboard.view", "audit.view"}
        assigned = make_user(services, admin, username="auditor1", roles=("auditor",))
        assert assigned.role_codes == ("auditor",)
        fetched = [r for r in services.roles.list_roles(admin) if r.code == "auditor"][0]
        assert fetched.member_count == 1

    def test_role_validation(self, services: AppServices, admin) -> None:
        with pytest.raises(ValidationError):
            services.roles.create_role(admin, code="Bad Code", title_fa="بد",
                                       permissions=("dashboard.view",))
        with pytest.raises(ValidationError):
            services.roles.create_role(admin, code="empty", title_fa="خالی", permissions=())
        with pytest.raises(ValidationError):
            services.roles.create_role(admin, code="unknown", title_fa="ناشناس",
                                       permissions=("does.not.exist",))
        services.roles.create_role(admin, code="dupcode", title_fa="تکراری",
                                   permissions=("dashboard.view",))
        with pytest.raises(ConflictError):
            services.roles.create_role(admin, code="dupcode", title_fa="تکراری",
                                       permissions=("dashboard.view",))

    def test_admin_role_is_immutable(self, services: AppServices, admin) -> None:
        admin_role = [r for r in services.roles.list_roles(admin) if r.code == ADMIN_ROLE_CODE][0]
        with pytest.raises(ConflictError):
            services.roles.update_role(admin, admin_role.id, title_fa="مدیر",
                                       permissions=("dashboard.view",))
        with pytest.raises(ConflictError):
            services.roles.delete_role(admin, admin_role.id)

    def test_update_role_permissions_changes_effective_access(self, services: AppServices, admin,
                                                              accountant) -> None:
        role = [r for r in services.roles.list_roles(admin) if r.code == "accountant"][0]
        services.roles.update_role(admin, role.id, title_fa=role.title_fa,
                                   permissions=tuple(set(role.permission_codes) | {"audit.export"}))
        refreshed = services.auth.reload_context(accountant)
        assert "audit.export" in refreshed.permissions
        services.roles.update_role(admin, role.id, title_fa=role.title_fa,
                                   permissions=("dashboard.view",))
        refreshed = services.auth.reload_context(accountant)
        assert "audit.export" not in refreshed.permissions

    def test_cannot_delete_role_in_use(self, services: AppServices, admin) -> None:
        role = services.roles.create_role(admin, code="temp", title_fa="موقت",
                                          permissions=("dashboard.view",))
        make_user(services, admin, username="tempuser", roles=("temp",))
        with pytest.raises(ConflictError):
            services.roles.delete_role(admin, role.id)

    def test_delete_unused_custom_role(self, services: AppServices, admin) -> None:
        role = services.roles.create_role(admin, code="spare", title_fa="یدکی",
                                          permissions=("dashboard.view",))
        services.roles.delete_role(admin, role.id)
        assert all(r.code != "spare" for r in services.roles.list_roles(admin))
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.ROLE_DELETED in events

    def test_cannot_lock_yourself_out_of_role_management(self, services: AppServices, admin,
                                                         accountant) -> None:
        role = services.roles.create_role(admin, code="rolemgr", title_fa="مدیر نقش‌ها",
                                          permissions=("roles.view", "roles.edit"))
        services.users.update_user(admin, accountant.user_id,
                                   UserUpdateData(full_name=accountant.full_name,
                                                  role_codes=("rolemgr",)))
        ctx = services.auth.reload_context(services.auth.authenticate("hesabdar", TEST_USER_PASSWORD))
        with pytest.raises(ConflictError):
            services.roles.update_role(ctx, role.id, title_fa=role.title_fa,
                                       permissions=("dashboard.view",))

    def test_permission_denied_without_role_permission(self, services: AppServices, accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            services.roles.create_role(accountant, code="xrole", title_fa="ایکس",
                                       permissions=("dashboard.view",))
