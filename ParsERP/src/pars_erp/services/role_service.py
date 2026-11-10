"""Role and permission administration.

Safety rules baked into the service layer:

* the built-in ``admin`` role keeps **all** permissions - it cannot be narrowed,
  renamed or deleted, so an administrator can never lock the company out;
* a role that is still assigned to users cannot be deleted;
* you cannot remove the permission you are currently relying on to edit roles
  unless another of your roles still grants it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select

from pars_erp.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from pars_erp.db.models import Role
from pars_erp.db.session import Database
from pars_erp.security.permissions import (
    ADMIN_ROLE_CODE,
    ALL_PERMISSION_CODES,
    PERMISSION_SECTIONS,
    SecurityContext,
    require_permission,
)
from pars_erp.services.audit_service import AuditService, EventType
from pars_erp.services.validation import validate_required_text

ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,29}$")


@dataclass(frozen=True)
class RoleRow:
    id: int
    code: str
    title_fa: str
    description: str | None
    is_system: bool
    member_count: int
    permission_codes: tuple[str, ...]

    @property
    def permissions_count(self) -> int:
        return len(self.permission_codes)

    @property
    def kind_fa(self) -> str:
        return "سیستمی" if self.is_system else "سفارشی"


@dataclass(frozen=True)
class PermissionGroupView:
    section: str
    title_fa: str
    permissions: tuple[tuple[str, str, str], ...]  # (code, title_fa, action)


class RoleService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def permission_groups() -> list[PermissionGroupView]:
        return [PermissionGroupView(
            section=section.code,
            title_fa=section.title_fa,
            permissions=tuple((p.code, p.title_fa, p.action) for p in section.permissions),
        ) for section in PERMISSION_SECTIONS]

    @staticmethod
    def _role_row(role: Role, member_count: int) -> RoleRow:
        return RoleRow(
            id=role.id, code=role.code, title_fa=role.title_fa, description=role.description,
            is_system=bool(role.is_system), member_count=member_count,
            permission_codes=tuple(sorted(role.permission_codes)),
        )

    @staticmethod
    def _validate_permissions(codes: tuple[str, ...]) -> set[str]:
        cleaned = {str(code).strip() for code in (codes or ()) if str(code).strip()}
        unknown = cleaned - set(ALL_PERMISSION_CODES)
        if unknown:
            raise ValidationError(
                f"مجوزهای ناشناخته: {'، '.join(sorted(unknown))}", field="permissions")
        if not cleaned:
            raise ValidationError("حداقل یک مجوز برای نقش انتخاب کنید.", field="permissions")
        return cleaned

    # ------------------------------------------------------------------- read
    def list_roles(self, ctx: SecurityContext | None) -> list[RoleRow]:
        require_permission(ctx, "roles.view")
        from pars_erp.db.models import user_roles
        with self.db.session_scope() as session:
            counts = dict(session.execute(
                select(user_roles.c.role_id, func.count(user_roles.c.user_id))
                .group_by(user_roles.c.role_id)).all())
            roles = list(session.execute(select(Role).order_by(Role.sort_order, Role.title_fa)).scalars())
            return [self._role_row(r, int(counts.get(r.id, 0))) for r in roles]

    def get_role(self, ctx: SecurityContext | None, role_id: int) -> RoleRow:
        require_permission(ctx, "roles.view")
        from pars_erp.db.models import user_roles
        with self.db.session_scope() as session:
            role = session.get(Role, int(role_id))
            if role is None:
                raise NotFoundError("نقش مورد نظر یافت نشد.")
            count = int(session.execute(
                select(func.count(user_roles.c.user_id))
                .where(user_roles.c.role_id == role.id)).scalar() or 0)
            return self._role_row(role, count)

    def role_choices(self) -> list[tuple[str, str]]:
        """All roles as ``(code, title)`` - used by filters."""
        with self.db.session_scope() as session:
            return [(r.code, r.title_fa) for r in session.execute(
                select(Role).order_by(Role.sort_order, Role.title_fa)).scalars()]

    # ----------------------------------------------------------------- mutate
    def create_role(self, ctx: SecurityContext | None, *, code: str, title_fa: str,
                    description: str = "", permissions: tuple[str, ...] = ()) -> RoleRow:
        require_permission(ctx, "roles.create")
        normalized = (code or "").strip().lower()
        if not ROLE_CODE_PATTERN.match(normalized):
            raise ValidationError(
                "کد نقش باید با حرف انگلیسی شروع شود و ۳ تا ۳۰ نویسه شامل حروف کوچک، ارقام یا زیرخط باشد.",
                field="code")
        title = validate_required_text(title_fa, field="title_fa", label="عنوان نقش",
                                       min_length=2, max_length=120)
        wanted = self._validate_permissions(permissions)
        with self.db.session_scope() as session:
            if session.execute(select(Role).where(Role.code == normalized)).scalar_one_or_none():
                raise ConflictError(f"نقش با کد «{normalized}» از قبل وجود دارد.")
            from pars_erp.db.models import Permission
            perms = list(session.execute(
                select(Permission).where(Permission.code.in_(wanted))).scalars())
            role = Role(code=normalized, title_fa=title,
                        description=validate_required_text(description, field="description",
                                                           label="توضیحات", min_length=0,
                                                           max_length=500) if description else None,
                        is_system=False, permissions=perms,
                        sort_order=200)
            session.add(role)
            session.flush()
            result = self._role_row(role, 0)
            self.audit.log_security(
                event_type=EventType.ROLE_CREATED,
                message_fa=f"نقش «{title}» با {len(wanted)} مجوز ایجاد شد.",
                ctx=ctx, details={"role": normalized, "permissions": sorted(wanted)},
                session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="role", entity_id=role.id, action="create",
                summary_fa=f"ایجاد نقش «{title}»",
                after={"code": normalized, "title_fa": title,
                       "permissions": sorted(wanted)}, session=session)
            return result

    def update_role(self, ctx: SecurityContext | None, role_id: int, *, title_fa: str,
                    description: str = "", permissions: tuple[str, ...] = ()) -> RoleRow:
        require_permission(ctx, "roles.edit")
        with self.db.session_scope() as session:
            role = session.get(Role, int(role_id))
            if role is None:
                raise NotFoundError("نقش مورد نظر یافت نشد.")
            if role.code == ADMIN_ROLE_CODE:
                raise ConflictError(
                    "نقش «مدیر سیستم» همیشه تمام مجوزها را دارد و قابل تغییر نیست.")
            title = validate_required_text(title_fa, field="title_fa", label="عنوان نقش",
                                           min_length=2, max_length=120)
            wanted = self._validate_permissions(permissions)
            before = {"title_fa": role.title_fa, "description": role.description,
                      "permissions": sorted(role.permission_codes)}
            if ctx is not None and role.id in self._actor_role_ids(session, ctx.user_id):
                lost = set(before["permissions"]) - wanted
                protected = {"roles.edit", "roles.view"} & lost
                if protected:
                    remaining = self._actor_permissions_without(session, ctx.user_id, role.id)
                    if not protected <= remaining:
                        raise ConflictError(
                            "با این تغییر، دسترسی خودتان به مدیریت نقش‌ها حذف می‌شود. "
                            "ابتدا نقش دیگری با این مجوز برای خود تعریف کنید.")
            from pars_erp.db.models import Permission
            perms = list(session.execute(
                select(Permission).where(Permission.code.in_(wanted))).scalars())
            role.title_fa = title
            role.description = description.strip() or None
            role.permissions = perms
            after = {"title_fa": title, "description": role.description,
                     "permissions": sorted(role.permission_codes)}
            result = self._role_row(role, self._role_member_count(session, role.id))
            changes = self.audit.diff(before, after)
            self.audit.log_security(
                event_type=EventType.ROLE_UPDATED,
                message_fa=f"نقش «{title}» ویرایش شد ({', '.join(changes) or 'بدون تغییر'}).",
                ctx=ctx, details={"role": role.code, "changed": list(changes)}, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="role", entity_id=role.id, action="update",
                summary_fa=f"ویرایش نقش «{title}»", before=before, after=after, session=session)
            return result

    def delete_role(self, ctx: SecurityContext | None, role_id: int) -> None:
        require_permission(ctx, "roles.delete")
        with self.db.session_scope() as session:
            role = session.get(Role, int(role_id))
            if role is None:
                raise NotFoundError("نقش مورد نظر یافت نشد.")
            if role.is_system or role.code == ADMIN_ROLE_CODE:
                raise ConflictError("نقش‌های سیستمی قابل حذف نیستند.")
            members = self._role_member_count(session, role.id)
            if members > 0:
                raise ConflictError(
                    f"این نقش به {members} کاربر اختصاص یافته است؛ ابتدا کاربران را از این نقش خارج کنید.")
            code, title = role.code, role.title_fa
            session.delete(role)
            self.audit.log_security(
                event_type=EventType.ROLE_DELETED,
                message_fa=f"نقش «{title}» حذف شد.",
                ctx=ctx, details={"role": code}, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="role", entity_id=role_id, action="delete",
                summary_fa=f"حذف نقش «{title}»", before={"code": code, "title_fa": title},
                session=session)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _role_member_count(session, role_id: int) -> int:
        from pars_erp.db.models import user_roles
        return int(session.execute(
            select(func.count(user_roles.c.user_id))
            .where(user_roles.c.role_id == role_id)).scalar() or 0)

    @staticmethod
    def _actor_role_ids(session, user_id: int) -> set[int]:
        from pars_erp.db.models import user_roles
        return {int(rid) for (rid,) in session.execute(
            select(user_roles.c.role_id).where(user_roles.c.user_id == user_id)).all()}

    @staticmethod
    def _actor_permissions_without(session, user_id: int, excluded_role_id: int) -> set[str]:
        from pars_erp.db.models import Permission, role_permissions, user_roles
        rows = session.execute(
            select(Permission.code)
            .join(role_permissions, Permission.id == role_permissions.c.permission_id)
            .join(user_roles, role_permissions.c.role_id == user_roles.c.role_id)
            .where(user_roles.c.user_id == user_id)
            .where(user_roles.c.role_id != excluded_role_id)).scalars()
        return set(rows)
