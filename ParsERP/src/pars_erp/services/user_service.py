"""User administration (create, edit, activate/deactivate, role assignment)."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from sqlalchemy import func, or_, select

from pars_erp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from pars_erp.db.models import Role, User
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.passwords import (
    Argon2PasswordHasher,
    PasswordPolicy,
    validate_password,
)
from pars_erp.security.permissions import (
    ADMIN_ROLE_CODE,
    SecurityContext,
    require_permission,
)
from pars_erp.services.audit_service import AuditService, EventType
from pars_erp.services.common import Page, clamp_page, normalize_page
from pars_erp.services.settings_service import SettingsService
from pars_erp.services.validation import (
    validate_email,
    validate_full_name,
    validate_notes,
    validate_phone,
    validate_username,
)

STATUS_ALL = "all"
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_LOCKED = "locked"

STATUS_TITLES_FA = {
    STATUS_ALL: "همه",
    STATUS_ACTIVE: "فعال",
    STATUS_INACTIVE: "غیرفعال",
    STATUS_LOCKED: "قفل‌شده",
}


@dataclass(frozen=True)
class UserRow:
    id: int
    username: str
    full_name: str
    email: str | None
    phone: str | None
    role_codes: tuple[str, ...]
    role_titles: tuple[str, ...]
    is_active: bool
    is_protected: bool
    is_locked: bool
    locked_until: _dt.datetime | None
    must_change_password: bool
    failed_login_attempts: int
    last_login_at: _dt.datetime | None
    created_at: _dt.datetime
    version: int
    notes: str | None

    @property
    def status_fa(self) -> str:
        if not self.is_active:
            return "غیرفعال"
        if self.is_locked:
            return "قفل‌شده"
        return "فعال"

    @property
    def roles_fa(self) -> str:
        return "، ".join(self.role_titles) if self.role_titles else "—"


@dataclass(frozen=True)
class UserCreateData:
    username: str
    full_name: str
    password: str
    confirm_password: str
    role_codes: tuple[str, ...]
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UserUpdateData:
    full_name: str
    role_codes: tuple[str, ...]
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class UserService:
    def __init__(self, db: Database, settings: SettingsService, audit: AuditService, *,
                 hasher: Argon2PasswordHasher | None = None) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.hasher = hasher or Argon2PasswordHasher()

    # ---------------------------------------------------------------- helpers
    def _policy(self) -> PasswordPolicy:
        return PasswordPolicy(min_length=self.settings.snapshot().password_min_length)

    @staticmethod
    def _row(user: User) -> UserRow:
        return UserRow(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            role_codes=user.role_codes,
            role_titles=tuple(r.title_fa for r in user.roles),
            is_active=bool(user.is_active),
            is_protected=bool(user.is_protected),
            is_locked=user.is_locked(),
            locked_until=user.locked_until,
            must_change_password=bool(user.must_change_password),
            failed_login_attempts=int(user.failed_login_attempts or 0),
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            version=int(user.version or 1),
            notes=user.notes,
        )

    @staticmethod
    def _resolve_roles(session, role_codes: tuple[str, ...]) -> list[Role]:
        codes = tuple(dict.fromkeys(code for code in (role_codes or ()) if code))
        if not codes:
            raise ValidationError("حداقل یک نقش برای کاربر انتخاب کنید.", field="roles")
        roles = list(session.execute(select(Role).where(Role.code.in_(codes))).scalars())
        found = {role.code for role in roles}
        missing = set(codes) - found
        if missing:
            raise ValidationError(
                f"نقش‌های انتخاب‌شده معتبر نیستند: {'، '.join(sorted(missing))}", field="roles")
        return sorted(roles, key=lambda r: (r.sort_order, r.title_fa))

    @staticmethod
    def _guard_admin_scope(ctx: SecurityContext, roles: list[Role]) -> None:
        if any(r.code == ADMIN_ROLE_CODE for r in roles) and not ctx.is_admin:
            raise PermissionDeniedError(
                message="اعطای نقش «مدیر سیستم» فقط توسط مدیر سیستم مجاز است.")

    def _require_target(self, session, user_id: int) -> User:
        user = session.get(User, int(user_id))
        if user is None:
            raise NotFoundError("کاربر مورد نظر یافت نشد.")
        return user

    # ------------------------------------------------------------------- read
    def list_users(self, ctx: SecurityContext | None, *, search: str = "", status: str = STATUS_ALL,
                   role_code: str | None = None, page: int = 1, page_size: int = 25) -> Page[UserRow]:
        require_permission(ctx, "users.view")
        page, page_size = normalize_page(page, page_size)
        conditions = []
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            conditions.append(or_(User.username.ilike(pattern), User.full_name.ilike(pattern),
                                  User.email.ilike(pattern), User.phone.ilike(pattern)))
        if status == STATUS_ACTIVE:
            conditions.append(User.is_active.is_(True))
        elif status == STATUS_INACTIVE:
            conditions.append(User.is_active.is_(False))
        elif status == STATUS_LOCKED:
            conditions.append(User.locked_until.is_not(None))
            conditions.append(User.locked_until > utcnow())
        with self.db.session_scope() as session:
            stmt = select(User)
            count_stmt = select(func.count(User.id))
            if role_code:
                stmt = stmt.join(User.roles).where(Role.code == role_code)
                count_stmt = count_stmt.join(User.roles).where(Role.code == role_code)
            for condition in conditions:
                stmt = stmt.where(condition)
                count_stmt = count_stmt.where(condition)
            total = int(session.execute(count_stmt).scalar() or 0)
            page = clamp_page(page, page_size, total)
            stmt = stmt.order_by(User.is_active.desc(), User.username).limit(page_size).offset(
                (page - 1) * page_size)
            rows = [self._row(u) for u in session.execute(stmt).scalars()]
        return Page(rows, total, page, page_size)

    def get_user(self, ctx: SecurityContext | None, user_id: int) -> UserRow:
        require_permission(ctx, "users.view")
        with self.db.session_scope() as session:
            return self._row(self._require_target(session, user_id))

    def selectable_roles(self, ctx: SecurityContext | None) -> list[tuple[str, str]]:
        """Roles the current actor may assign (admins see everything)."""
        require_permission(ctx, "users.view")
        with self.db.session_scope() as session:
            roles = list(session.execute(
                select(Role).order_by(Role.sort_order, Role.title_fa)).scalars())
            return [(r.code, r.title_fa) for r in roles
                    if ctx.is_admin or r.code != ADMIN_ROLE_CODE]

    @staticmethod
    def _count_active_admins(session) -> int:
        return int(session.execute(
            select(func.count(func.distinct(User.id)))
            .join(User.roles).where(Role.code == ADMIN_ROLE_CODE)
            .where(User.is_active.is_(True))).scalar() or 0)

    def count_active_admins(self) -> int:
        with self.db.session_scope() as session:
            return self._count_active_admins(session)

    # ----------------------------------------------------------------- mutate
    def create_user(self, ctx: SecurityContext | None, data: UserCreateData) -> UserRow:
        require_permission(ctx, "users.create")
        username = validate_username(data.username)
        full_name = validate_full_name(data.full_name)
        email = validate_email(data.email)
        phone = validate_phone(data.phone)
        notes = validate_notes(data.notes)
        if data.password != data.confirm_password:
            raise ValidationError("رمز عبور و تکرار آن یکسان نیستند.", field="confirm_password")
        validate_password(data.password, self._policy(), username=username, full_name=full_name)

        with self.db.session_scope() as session:
            existing = session.execute(
                select(User).where(User.username == username)).scalar_one_or_none()
            if existing is not None:
                raise ConflictError(f"نام کاربری «{username}» قبلاً استفاده شده است.")
            roles = self._resolve_roles(session, data.role_codes)
            self._guard_admin_scope(ctx, roles)
            user = User(
                username=username,
                full_name=full_name,
                email=email,
                phone=phone,
                notes=notes,
                password_hash=self.hasher.hash(data.password),
                password_changed_at=utcnow(),
                must_change_password=True,
                is_active=True,
                is_protected=any(r.code == ADMIN_ROLE_CODE for r in roles),
                roles=roles,
                created_by_id=ctx.user_id if ctx else None,
                updated_by_id=ctx.user_id if ctx else None,
            )
            session.add(user)
            session.flush()
            self.audit.log_security(
                event_type=EventType.USER_CREATED,
                message_fa=f"کاربر «{username}» توسط «{ctx.username if ctx else '-'}» ایجاد شد.",
                ctx=ctx, details={"target_user": username,
                                  "roles": [r.code for r in roles]}, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="user", entity_id=user.id, action="create",
                summary_fa=f"ایجاد کاربر «{username}»",
                after={"username": username, "full_name": full_name,
                       "roles": [r.code for r in roles], "is_active": True}, session=session)
            return self._row(user)

    def update_user(self, ctx: SecurityContext | None, user_id: int,
                    data: UserUpdateData) -> UserRow:
        require_permission(ctx, "users.edit")
        full_name = validate_full_name(data.full_name)
        email = validate_email(data.email)
        phone = validate_phone(data.phone)
        notes = validate_notes(data.notes)
        with self.db.session_scope() as session:
            user = self._require_target(session, user_id)
            actor_is_admin = bool(ctx and ctx.is_admin)
            if user.is_protected and not actor_is_admin:
                raise PermissionDeniedError(
                    message="ویرایش حساب مدیر محافظت‌شده فقط توسط مدیر سیستم مجاز است.")
            roles = self._resolve_roles(session, data.role_codes)
            self._guard_admin_scope(ctx, roles)
            before = {"full_name": user.full_name, "email": user.email, "phone": user.phone,
                      "notes": user.notes, "roles": list(user.role_codes)}
            # never allow removing the last active administrator
            currently_admin = ADMIN_ROLE_CODE in user.role_codes
            still_admin = any(r.code == ADMIN_ROLE_CODE for r in roles)
            if currently_admin and not still_admin and user.is_active:
                if self._count_active_admins(session) <= 1:
                    raise ConflictError(
                        "این کاربر تنها مدیر فعال سیستم است؛ ابتدا مدیر دیگری تعریف کنید.")
            user.full_name = full_name
            user.email = email
            user.phone = phone
            user.notes = notes
            user.roles = roles
            user.is_protected = user.is_protected or still_admin
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id if ctx else None
            after = {"full_name": full_name, "email": email, "phone": phone, "notes": notes,
                     "roles": [r.code for r in roles]}
            changes = self.audit.diff(before, after)
            self.audit.log_audit(
                ctx=ctx, entity_type="user", entity_id=user.id, action="update",
                summary_fa=f"ویرایش کاربر «{user.username}»",
                before=before, after=after, session=session)
            if "roles" in changes:
                self.audit.log_security(
                    event_type=EventType.USER_ROLES_CHANGED,
                    message_fa=f"نقش‌های کاربر «{user.username}» تغییر کرد.",
                    ctx=ctx, details={"target_user": user.username,
                                      "roles": [r.code for r in roles]}, session=session)
            else:
                self.audit.log_security(
                    event_type=EventType.USER_UPDATED,
                    message_fa=f"اطلاعات کاربر «{user.username}» ویرایش شد.",
                    ctx=ctx, details={"target_user": user.username,
                                      "changed_fields": list(changes)}, session=session)
            return self._row(user)

    def set_active(self, ctx: SecurityContext | None, user_id: int, active: bool) -> UserRow:
        require_permission(ctx, "users.disable")
        if ctx is not None and int(user_id) == ctx.user_id and not active:
            raise ValidationError("نمی‌توانید حساب کاربری خودتان را غیرفعال کنید.")
        with self.db.session_scope() as session:
            user = self._require_target(session, user_id)
            if user.is_protected and not (ctx and ctx.is_admin):
                raise PermissionDeniedError(
                    message="فعال/غیرفعال کردن حساب مدیر محافظت‌شده فقط توسط مدیر سیستم مجاز است.")
            if not active and ADMIN_ROLE_CODE in user.role_codes and user.is_active:
                if self._count_active_admins(session) <= 1:
                    raise ConflictError(
                        "غیرفعال‌سازی آخرین مدیر فعال سیستم مجاز نیست.")
            if bool(user.is_active) == bool(active):
                return self._row(user)
            user.is_active = bool(active)
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id if ctx else None
            if not active:
                user.locked_until = None
            event = EventType.USER_ENABLED if active else EventType.USER_DISABLED
            self.audit.log_security(
                event_type=event,
                message_fa=(f"کاربر «{user.username}» "
                            f"{'فعال' if active else 'غیرفعال'} شد."),
                ctx=ctx, details={"target_user": user.username}, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="user", entity_id=user.id,
                action="enable" if active else "disable",
                summary_fa=(f"{'فعال‌سازی' if active else 'غیرفعال‌سازی'} کاربر «{user.username}»"),
                before={"is_active": not active}, after={"is_active": active}, session=session)
            return self._row(user)

    def set_must_change_password(self, ctx: SecurityContext | None, user_id: int,
                                 required: bool) -> None:
        require_permission(ctx, "users.edit")
        with self.db.session_scope() as session:
            user = self._require_target(session, user_id)
            user.must_change_password = bool(required)
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id if ctx else None
