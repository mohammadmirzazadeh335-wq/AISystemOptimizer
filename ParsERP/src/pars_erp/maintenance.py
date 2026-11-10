"""Maintenance operations callable from the CLI.

These functions are Qt-free and unit-tested. In particular the *administrator
recovery* is deliberately narrow:

* it requires explicit interactive confirmation;
* it only works for accounts that hold the administrator role;
* it never touches the database schema or bypasses authentication tables - it
  performs exactly the same password update as a normal reset, and records a
  critical security event that names the operator as ``cli``;
* it also clears a lockout, because a locked-out sole administrator would
  otherwise be unable to recover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

from pars_erp.core.errors import (
    AccountInactiveError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from pars_erp.db.models import Role, User, UserSession
from pars_erp.db.types import utcnow
from pars_erp.security.passwords import PasswordPolicy, validate_password
from pars_erp.security.permissions import ADMIN_ROLE_CODE
from pars_erp.services.audit_service import EventType, SEVERITY_CRITICAL
from pars_erp.services.context import AppServices

RECOVERY_PHRASE = "بازیابی"


@dataclass(frozen=True)
class MaintenanceResult:
    ok: bool
    message_fa: str


def list_administrators(services: AppServices) -> list[tuple[str, str, bool, bool]]:
    """``[(username, full_name, is_active, is_locked)]`` for every admin account."""
    with services.db.session_scope() as session:
        rows = session.execute(
            select(User).join(User.roles).where(Role.code == ADMIN_ROLE_CODE)
            .order_by(User.username)).scalars().all()
        return [(user.username, user.full_name, bool(user.is_active), user.is_locked())
                for user in rows]


def recover_admin_password(services: AppServices, *, username: str, new_password: str,
                           confirm_password: str, confirm_phrase: str) -> MaintenanceResult:
    """Offline administrator recovery (see the rules in the module docstring)."""
    if (confirm_phrase or "").strip() != RECOVERY_PHRASE:
        raise ValidationError(
            f"برای انجام بازیابی، عبارت «{RECOVERY_PHRASE}» را دقیقاً وارد کنید.",
            field="confirm_phrase")
    if new_password != confirm_password:
        raise ValidationError("رمز عبور جدید و تکرار آن یکسان نیستند.", field="confirm_password")
    normalized = (username or "").strip().lower()
    if not normalized:
        raise ValidationError("نام کاربری مدیر را وارد کنید.", field="username")

    with services.db.session_scope() as session:
        user = session.execute(
            select(User).where(User.username == normalized)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("کاربری با این نام کاربری یافت نشد.")
        if ADMIN_ROLE_CODE not in user.role_codes:
            raise PermissionDeniedError(
                message="این کاربر مدیر سیستم نیست؛ بازیابی رمز مدیر فقط برای حساب‌های مدیر مجاز است.")
        if not user.is_active:
            raise AccountInactiveError("این حساب مدیر غیرفعال است؛ ابتدا آن را فعال کنید.")
        validate_password(new_password, PasswordPolicy(min_length=8), username=user.username,
                          full_name=user.full_name)
        user.password_hash = services.hasher.hash(new_password)
        user.password_changed_at = utcnow()
        user.must_change_password = False
        user.locked_until = None
        user.failed_login_attempts = 0
        user.version = int(user.version or 0) + 1
        for login_session in session.execute(
                select(UserSession)
                .where(UserSession.user_id == user.id)
                .where(UserSession.logout_at.is_(None))).scalars():
            login_session.logout_at = utcnow()
            login_session.logout_reason = "admin_recovery"
        services.audit.log_security(
            event_type=EventType.PASSWORD_RESET,
            message_fa=(f"بازیابی رمز مدیر «{user.username}» از طریق ابزار خط فرمان انجام شد."),
            severity=SEVERITY_CRITICAL, username="cli",
            details={"target_user": user.username, "method": "cli_recovery"},
            session=session)
        services.audit.log_audit(
            ctx=None, entity_type="user", entity_id=user.id, action="recover_password",
            summary_fa=f"بازیابی رمز مدیر «{user.username}» از طریق خط فرمان",
            after={"must_change_password": False, "locked": False}, session=session)
    return MaintenanceResult(True, f"رمز عبور مدیر «{normalized}» بازنشانی شد.")


def system_info(services: AppServices) -> dict[str, object]:
    status = services.auth.setup_status()
    metadata = services.db.table_names()
    return {
        "database_url": services.db.url,
        "backend": services.db.dialect_name(),
        "home": str(services.paths.home),
        "schema_revision": services.db.schema_revision(),
        "tables": metadata,
        "users": status.user_count,
        "has_active_admin": status.has_active_admin,
        "needs_setup": status.needs_setup,
        "last_backup": (services.backups.last_backup().filename
                        if services.backups.last_backup() else None),
        "app_version": services.app_version,
    }


def create_backup_cli(services: AppServices, note: str | None = None) -> str:
    info = services.backups.create_backup(None, note=note or "پشتیبان خط فرمان",
                                          kind="manual", require_permission_check=False)
    return info.filename


def integrity_report(services: AppServices) -> list[tuple[str, bool, str]]:
    """Sanity checks used by ``pars-erp info --check``."""
    report: list[tuple[str, bool, str]] = []
    report.append(("اتصال به پایگاه داده", services.db.ping(), "SELECT 1"))
    revision = services.db.schema_revision()
    report.append(("نسخه ساختار پایگاه داده", revision is not None, str(revision)))
    status = services.auth.setup_status()
    report.append(("راه‌اندازی اولیه انجام شده", not status.needs_setup,
                   f"{status.user_count} کاربر"))
    report.append(("مدیر فعال موجود است", status.has_active_admin, status.message_fa))
    return report
