"""Authentication, session lifecycle and password management.

Every state change and the security event describing it are written in the same
transaction, so the log can never disagree with the data. Failed logins are
counted atomically (``UPDATE ... SET failed_login_attempts = failed_login_attempts + 1``)
so parallel attempts cannot slip past the lockout threshold.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass

from sqlalchemy import func, select, update

from pars_erp import __version__
from pars_erp.db.models import AppSetting, Role, User, UserSession
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.core.errors import (
    AccountInactiveError,
    AccountLockedError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    SetupAlreadyCompletedError,
    ValidationError,
)
from pars_erp.security.passwords import (
    Argon2PasswordHasher,
    PasswordPolicy,
    validate_password,
)
from pars_erp.security import session_registry
from pars_erp.security.permissions import (
    ADMIN_ROLE_CODE,
    SecurityContext,
    build_context,
    require_permission,
)
from pars_erp.services.audit_service import AuditService, EventType, SEVERITY_WARNING
from pars_erp.services.bootstrap_service import ensure_reference_data
from pars_erp.services.settings_service import SettingsService
from pars_erp.services.validation import validate_full_name, validate_username


@dataclass(frozen=True)
class SetupStatus:
    needs_setup: bool
    user_count: int
    has_active_admin: bool
    database_url: str
    schema_revision: str | None

    @property
    def message_fa(self) -> str:
        if self.needs_setup:
            return "سیستم آماده راه‌اندازی اولیه است."
        if not self.has_active_admin:
            return "هیچ مدیر فعالی وجود ندارد. از فرایند بازیابی مدیر استفاده کنید."
        return "سیستم راه‌اندازی شده است."


@dataclass(frozen=True)
class LoginResult:
    context: SecurityContext
    password_expired: bool = False


#: how long a positive session check may be reused (keeps a page full of
#: permission checks from turning into a page full of queries, while a logout on
#: another machine is still noticed within this window)
_SESSION_CHECK_SECONDS = 2.0


class AuthService:
    def __init__(self, db: Database, settings: SettingsService, audit: AuditService, *,
                 hasher: Argon2PasswordHasher | None = None, hostname: str | None = None,
                 app_version: str = __version__) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.hasher = hasher or Argon2PasswordHasher()
        self.hostname = hostname or audit.hostname
        self.app_version = app_version
        self._dummy_hash: str | None = None

    # ------------------------------------------------------------- helpers
    def _dummy(self) -> str:
        """A real hash used to equalise timing when the username does not exist."""
        if self._dummy_hash is None:
            self._dummy_hash = self.hasher.hash("timing-equaliser-3f91c2")
        return self._dummy_hash

    def policy(self) -> PasswordPolicy:
        snapshot = self.settings.snapshot()
        return PasswordPolicy(min_length=snapshot.password_min_length)

    def _context_from_user(self, user: User, session_id: int | None) -> SecurityContext:
        ctx = build_context(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            role_codes=user.role_codes,
            permissions=user.permission_codes,
            session_id=session_id,
            must_change_password=user.must_change_password,
        )
        if session_id is None:
            return ctx
        # every service call re-checks this: a session that was logged out or
        # locked must stop working immediately, not only in the interface
        state: dict[str, object] = {"checked_at": 0.0, "alive": True}

        def still_alive() -> bool:
            now = time.monotonic()
            if state.get("alive") is False:
                return False
            if now - float(state["checked_at"] or 0.0) < _SESSION_CHECK_SECONDS:
                return bool(state["alive"])
            with self.db.session_scope() as session:
                row = session.execute(
                    select(UserSession.id)
                    .join(User, User.id == UserSession.user_id)
                    .where(UserSession.id == session_id)
                    .where(UserSession.logout_at.is_(None))
                    .where(UserSession.is_locked.is_(False))
                    .where(User.is_active.is_(True))).first()
            state["checked_at"] = now
            state["alive"] = row is not None
            return bool(state["alive"])

        object.__setattr__(ctx, "session_guard", still_alive)
        object.__setattr__(ctx, "session_state", state)
        session_registry.register(user.id, session_id, state)
        return ctx

    # --------------------------------------------------------------- setup
    def setup_status(self) -> SetupStatus:
        with self.db.session_scope() as session:
            total = int(session.execute(select(func.count(User.id))).scalar() or 0)
            active_admins = int(session.execute(
                select(func.count(User.id))
                .join(User.roles)
                .where(Role.code == ADMIN_ROLE_CODE)
                .where(User.is_active.is_(True))
            ).scalar() or 0)
        return SetupStatus(
            needs_setup=total == 0,
            user_count=total,
            has_active_admin=active_admins > 0,
            database_url=self.db.url,
            schema_revision=self.db.schema_revision(),
        )

    def create_initial_admin(self, *, full_name: str, username: str, password: str,
                             confirm_password: str, company_name: str = "",
                             app_name: str = "") -> SecurityContext:
        """Secure first-run setup: allowed only while the users table is empty."""
        if password != confirm_password:
            raise ValidationError("رمز عبور و تکرار آن یکسان نیستند.", field="confirm_password")
        full_name = validate_full_name(full_name)
        username = validate_username(username)
        policy = self.policy()
        validate_password(password, policy, username=username, full_name=full_name)

        ensure_reference_data(self.db)

        with self.db.session_scope() as session:
            total = int(session.execute(select(func.count(User.id))).scalar() or 0)
            if total > 0:
                raise SetupAlreadyCompletedError()
            admin_role = session.execute(
                select(Role).where(Role.code == ADMIN_ROLE_CODE)).scalar_one_or_none()
            if admin_role is None:
                raise NotFoundError("نقش مدیر سیستم یافت نشد؛ راه‌اندازی ناقص است.")

            user = User(
                username=username,
                full_name=full_name,
                password_hash=self.hasher.hash(password),
                password_changed_at=utcnow(),
                is_active=True,
                is_protected=True,
                roles=[admin_role],
                version=1,
            )
            session.add(user)
            session.flush()

            login_session = UserSession(
                user_id=user.id, username=user.username, login_at=utcnow(),
                hostname=self.hostname, app_version=self.app_version)
            session.add(login_session)
            session.flush()
            user_id = user.id

            if company_name.strip():
                session.add(AppSetting(key="company_name", value=company_name.strip(),
                                       updated_by_id=user.id))
            if app_name.strip():
                session.add(AppSetting(key="app_name", value=app_name.strip(),
                                       updated_by_id=user.id))

            self.audit.log_security(
                event_type=EventType.SETUP_COMPLETED,
                message_fa=f"راه‌اندازی اولیه با ایجاد حساب مدیر «{username}» تکمیل شد.",
                user_id=user.id, username=user.username,
                details={"app_version": self.app_version}, session=session)
            self.audit.log_security(
                event_type=EventType.USER_CREATED,
                message_fa=f"حساب مدیر «{username}» ایجاد شد.",
                user_id=user.id, username=user.username, session=session)
            self.audit.log_security(
                event_type=EventType.LOGIN_SUCCESS,
                message_fa=f"ورود موفق «{username}» پس از راه‌اندازی اولیه.",
                user_id=user.id, username=user.username,
                details={"app_version": self.app_version}, session=session)
            self.audit.log_audit(
                ctx=None, entity_type="user", entity_id=user.id, action="create",
                summary_fa=f"ایجاد حساب مدیر اولیه «{username}»",
                after={"username": username, "full_name": full_name,
                       "roles": [ADMIN_ROLE_CODE]}, session=session)
            session_id = login_session.id

        ctx = self._load_context(user_id, session_id)
        return ctx

    # --------------------------------------------------------------- login
    def authenticate(self, username: str, password: str, *,
                     hostname: str | None = None) -> SecurityContext:
        uname = (username or "").strip().lower()
        if not uname or not password:
            raise AuthenticationError("نام کاربری و رمز عبور را وارد کنید.")

        with self.db.session_scope() as session:
            user = session.execute(select(User).where(User.username == uname)).scalar_one_or_none()
            user_id = user.id if user else None
            user_active = bool(user.is_active) if user else False
            locked_until = user.locked_until if user else None
            password_hash = user.password_hash if user else None

        now = utcnow()

        # 1) unknown user: burn the same amount of time, log, fail generically
        if user is None:
            self.hasher.verify(self._dummy(), password)
            self.audit.log_security(
                event_type=EventType.LOGIN_FAILED,
                message_fa=f"تلاش ناموفق ورود با نام کاربری ناشناس «{uname}».",
                severity=SEVERITY_WARNING, username=uname,
                details={"reason": "unknown_user", "hostname": hostname or self.hostname})
            raise AuthenticationError()

        # 2) locked account
        if locked_until is not None and locked_until > now:
            minutes_left = max(1, int((locked_until - now).total_seconds() // 60) + 1)
            self.audit.log_security(
                event_type=EventType.LOGIN_FAILED,
                message_fa=f"تلاش ورود به حساب قفل‌شده «{uname}».",
                severity=SEVERITY_WARNING, user_id=user_id, username=uname,
                details={"reason": "locked", "minutes_left": minutes_left})
            raise AccountLockedError(locked_until=locked_until, minutes_left=minutes_left)

        # 3) inactive account
        if not user_active:
            self.hasher.verify(password_hash or self._dummy(), password)
            self.audit.log_security(
                event_type=EventType.LOGIN_BLOCKED_INACTIVE,
                message_fa=f"تلاش ورود به حساب غیرفعال «{uname}».",
                severity=SEVERITY_WARNING, user_id=user_id, username=uname)
            raise AccountInactiveError()

        # 4) wrong password -> atomic counter + possible lock
        if not self.hasher.verify(password_hash or "", password):
            self._register_failed_attempt(user_id, uname)
            raise AuthenticationError()

        # 5) success
        return self._complete_login(user_id, uname, password, hostname)

    def _register_failed_attempt(self, user_id: int, username: str) -> None:
        snapshot = self.settings.snapshot()
        max_attempts = max(3, snapshot.max_failed_attempts)
        lockout_minutes = max(1, snapshot.lockout_minutes)
        now = utcnow()
        with self.db.session_scope() as session:
            session.execute(
                update(User)
                .where(User.id == user_id)
                .values(failed_login_attempts=User.failed_login_attempts + 1,
                        last_failed_login_at=now))
            user = session.get(User, user_id)
            attempts = int(user.failed_login_attempts or 0)
            if attempts >= max_attempts:
                user.locked_until = now + _dt.timedelta(minutes=lockout_minutes)
                user.failed_login_attempts = 0
                self.audit.log_security(
                    event_type=EventType.ACCOUNT_LOCKED,
                    message_fa=(f"حساب «{username}» پس از {attempts} تلاش ناموفق "
                                f"به مدت {lockout_minutes} دقیقه قفل شد."),
                    severity=SEVERITY_WARNING, user_id=user_id, username=username,
                    details={"attempts": attempts, "lockout_minutes": lockout_minutes},
                    session=session)
            self.audit.log_security(
                event_type=EventType.LOGIN_FAILED,
                message_fa=f"رمز عبور نادرست برای «{username}» (تلاش {attempts}).",
                severity=SEVERITY_WARNING, user_id=user_id, username=username,
                details={"reason": "wrong_password", "attempt": attempts,
                         "max_attempts": max_attempts},
                session=session)

    def _complete_login(self, user_id: int, username: str, password: str,
                        hostname: str | None) -> SecurityContext:
        now = utcnow()
        with self.db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:  # deleted between the two transactions
                raise AuthenticationError()
            if self.hasher.needs_rehash(user.password_hash):
                user.password_hash = self.hasher.hash(password)
                user.password_changed_at = now
            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login_at = now
            user.last_login_host = hostname or self.hostname
            login_session = UserSession(
                user_id=user.id, username=user.username, login_at=now,
                hostname=hostname or self.hostname, app_version=self.app_version)
            session.add(login_session)
            session.flush()
            session_id = login_session.id
            self.audit.log_security(
                event_type=EventType.LOGIN_SUCCESS,
                message_fa=f"ورود موفق «{username}».",
                user_id=user.id, username=user.username,
                details={"app_version": self.app_version, "hostname": hostname or self.hostname},
                session=session)
        return self._load_context(user_id, session_id)

    def _load_context(self, user_id: int, session_id: int | None) -> SecurityContext:
        with self.db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise AuthenticationError()
            return self._context_from_user(user, session_id)

    def reload_context(self, ctx: SecurityContext) -> SecurityContext:
        """Re-read roles/permissions (used after an administrator edits them)."""
        return self._load_context(ctx.user_id, ctx.session_id)

    # -------------------------------------------------------------- sessions
    @staticmethod
    def _end_session_cache(ctx: SecurityContext, *, reason: str = "logout") -> None:
        """Stop every context of this session, in this process, at once."""
        state = ctx.session_state
        if state is not None:
            state["alive"] = False
            state["reason"] = reason
            state["checked_at"] = time.monotonic()
        session_registry.invalidate_session(ctx.session_id, reason=reason)

    def logout(self, ctx: SecurityContext, *, reason: str = "logout") -> None:
        now = utcnow()
        with self.db.session_scope() as session:
            if ctx.session_id is not None:
                login_session = session.get(UserSession, ctx.session_id)
                if login_session is not None and login_session.logout_at is None:
                    login_session.logout_at = now
                    login_session.logout_reason = reason
            self._end_session_cache(ctx, reason=reason)
            session_registry.forget(ctx.session_id)
            self.audit.log_security(
                event_type=EventType.LOGOUT,
                message_fa=f"خروج «{ctx.username}» از سیستم ({reason}).",
                ctx=ctx, details={"reason": reason}, session=session)

    def lock_session(self, ctx: SecurityContext, *, reason: str = "idle") -> None:
        with self.db.session_scope() as session:
            if ctx.session_id is not None:
                login_session = session.get(UserSession, ctx.session_id)
                if login_session is not None:
                    login_session.is_locked = True
            self._end_session_cache(ctx, reason="locked")
            self.audit.log_security(
                event_type=EventType.SESSION_LOCKED,
                message_fa=f"نشست «{ctx.username}» قفل شد ({reason}).",
                ctx=ctx, details={"reason": reason}, session=session)

    def unlock_session(self, ctx: SecurityContext, password: str) -> SecurityContext:
        with self.db.session_scope() as session:
            user = session.get(User, ctx.user_id)
            if user is None:
                raise AuthenticationError()
            if not user.is_active:
                raise AccountInactiveError()
            if user.is_locked():
                minutes_left = None
                if user.locked_until is not None:
                    minutes_left = max(1, int((user.locked_until - utcnow()).total_seconds() // 60) + 1)
                raise AccountLockedError(locked_until=user.locked_until, minutes_left=minutes_left)
            if not self.hasher.verify(user.password_hash, password or ""):
                self.audit.log_security(
                    event_type=EventType.UNLOCK_FAILED,
                    message_fa=f"تلاش ناموفق برای باز کردن قفل نشست «{ctx.username}».",
                    severity=SEVERITY_WARNING, ctx=ctx, session=session)
                raise AuthenticationError("رمز عبور نادرست است.")
            if ctx.session_id is not None:
                login_session = session.get(UserSession, ctx.session_id)
                if login_session is not None:
                    login_session.is_locked = False
            session_registry.revive_session(ctx.session_id)
            state = ctx.session_state
            if state is not None:
                state["alive"] = True
                state["checked_at"] = 0.0
            self.audit.log_security(
                event_type=EventType.UNLOCK_SUCCESS,
                message_fa=f"قفل نشست «{ctx.username}» باز شد.",
                ctx=ctx, session=session)
        return ctx

    def verify_password(self, ctx: SecurityContext, password: str) -> bool:
        with self.db.session_scope() as session:
            user = session.get(User, ctx.user_id)
            if user is None:
                return False
            return self.hasher.verify(user.password_hash, password or "")

    def open_sessions(self, *, user_id: int | None = None) -> list[UserSession]:
        with self.db.session_scope() as session:
            stmt = select(UserSession).where(UserSession.logout_at.is_(None))
            if user_id is not None:
                stmt = stmt.where(UserSession.user_id == user_id)
            return list(session.execute(stmt.order_by(UserSession.login_at.desc())).scalars())

    # ------------------------------------------------------------- passwords
    def change_password(self, ctx: SecurityContext, *, current_password: str, new_password: str,
                        confirm_password: str) -> None:
        if new_password != confirm_password:
            raise ValidationError("رمز عبور جدید و تکرار آن یکسان نیستند.", field="confirm_password")
        with self.db.session_scope() as session:
            user = session.get(User, ctx.user_id)
            if user is None:
                raise AuthenticationError()
            if not self.hasher.verify(user.password_hash, current_password or ""):
                self.audit.log_security(
                    event_type=EventType.LOGIN_FAILED,
                    message_fa=f"تلاش ناموفق برای تغییر رمز «{user.username}» (رمز فعلی نادرست).",
                    severity=SEVERITY_WARNING, ctx=ctx, session=session)
                raise ValidationError("رمز عبور فعلی نادرست است.", field="current_password")
            validate_password(new_password, self.policy(), username=user.username,
                              full_name=user.full_name)
            if self.hasher.verify(user.password_hash, new_password):
                raise ValidationError("رمز عبور جدید نباید با رمز فعلی یکسان باشد.", field="new_password")
            user.password_hash = self.hasher.hash(new_password)
            user.password_changed_at = utcnow()
            user.must_change_password = False
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id
            # other sessions of this user must re-authenticate with the new password
            session_registry.invalidate_user(user.id, reason="password_changed",
                                             except_session=ctx.session_id)
            now = utcnow()
            for login_session in session.execute(
                    select(UserSession)
                    .where(UserSession.user_id == user.id)
                    .where(UserSession.logout_at.is_(None))
                    .where(UserSession.id != (ctx.session_id or -1))).scalars():
                login_session.logout_at = now
                login_session.logout_reason = "password_changed"
            self.audit.log_security(
                event_type=EventType.PASSWORD_CHANGED,
                message_fa=f"رمز عبور «{user.username}» توسط خود کاربر تغییر کرد.",
                ctx=ctx, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="user", entity_id=user.id, action="change_password",
                summary_fa=f"تغییر رمز عبور کاربر «{user.username}»",
                before={"password_changed_at": None}, after={"password_changed_at": utcnow()},
                session=session)

    def reset_password_by_admin(self, ctx: SecurityContext, *, user_id: int, new_password: str,
                                confirm_password: str, require_change: bool = True) -> None:
        require_permission(ctx, "users.reset_password")
        if new_password != confirm_password:
            raise ValidationError("رمز عبور جدید و تکرار آن یکسان نیستند.", field="confirm_password")
        with self.db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise NotFoundError("کاربر مورد نظر یافت نشد.")
            if user.id == ctx.user_id:
                raise ValidationError(
                    "برای تغییر رمز خودتان از گزینه «تغییر رمز عبور» استفاده کنید.", field="user_id")
            if user.is_protected and not ctx.is_admin:
                raise PermissionDeniedError(
                    message="تغییر رمز حساب مدیر محافظت‌شده فقط توسط مدیر سیستم مجاز است.")
            validate_password(new_password, self.policy(), username=user.username,
                              full_name=user.full_name)
            user.password_hash = self.hasher.hash(new_password)
            user.password_changed_at = utcnow()
            user.must_change_password = require_change
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id
            session_registry.invalidate_user(user.id, reason="password_reset")
            now = utcnow()
            for login_session in session.execute(
                    select(UserSession)
                    .where(UserSession.user_id == user.id)
                    .where(UserSession.logout_at.is_(None))).scalars():
                login_session.logout_at = now
                login_session.logout_reason = "password_reset"
            self.audit.log_security(
                event_type=EventType.PASSWORD_RESET,
                message_fa=f"رمز عبور «{user.username}» توسط «{ctx.username}» بازنشانی شد.",
                ctx=ctx, details={"target_user": user.username,
                                  "require_change": require_change}, session=session)
            self.audit.log_audit(
                ctx=ctx, entity_type="user", entity_id=user.id, action="reset_password",
                summary_fa=f"بازنشانی رمز عبور «{user.username}»",
                after={"must_change_password": require_change}, session=session)

    def unlock_user(self, ctx: SecurityContext, user_id: int) -> None:
        require_permission(ctx, "users.unlock")
        with self.db.session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise NotFoundError("کاربر مورد نظر یافت نشد.")
            was_locked = user.locked_until is not None or (user.failed_login_attempts or 0) > 0
            user.locked_until = None
            user.failed_login_attempts = 0
            user.version = int(user.version or 0) + 1
            user.updated_by_id = ctx.user_id
            if was_locked:
                self.audit.log_security(
                    event_type=EventType.ACCOUNT_UNLOCKED,
                    message_fa=f"قفل حساب «{user.username}» توسط «{ctx.username}» برداشته شد.",
                    ctx=ctx, details={"target_user": user.username}, session=session)
