"""Append-only security-event and audit-trail logging.

Two separate streams are kept on purpose:

``security_events``
    authentication/authorisation/administrative-security facts (failed logins,
    lockouts, password resets, backups, restores, setup). Feeds the security
    dashboard and is written even when the surrounding operation fails.

``audit_logs``
    business change history ("who changed which record, before -> after").
    Phase 2+ accounting documents add their entries through the same API, which
    is why it is designed around ``entity_type``/``entity_id``/``before``/``after``.

Secrets never reach these tables: :func:`_sanitize` redacts sensitive keys a
second time, in addition to the callers never passing them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pars_erp.db.models import AuditLog, SecurityEvent
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext
from pars_erp.services.common import Page, clamp_page, normalize_page

_REDACTED = "***"
_SENSITIVE_KEY_PARTS = ("password", "passwd", "hash", "secret", "token", "credential", "cookie")


def _sanitize(value: Any) -> Any:
    """Recursively redact sensitive keys from structured log payloads."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                cleaned[str(key)] = _REDACTED
            else:
                cleaned[str(key)] = _sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    return value


class EventType:
    """Canonical event-type strings (kept in one place to avoid typos)."""

    SETUP_COMPLETED = "setup.completed"
    LOGIN_SUCCESS = "auth.login_success"
    LOGIN_FAILED = "auth.login_failed"
    ACCOUNT_LOCKED = "auth.account_locked"
    ACCOUNT_UNLOCKED = "auth.account_unlocked"
    LOGIN_BLOCKED_INACTIVE = "auth.login_blocked_inactive"
    LOGOUT = "auth.logout"
    SESSION_LOCKED = "auth.session_locked"
    UNLOCK_SUCCESS = "auth.unlock_success"
    UNLOCK_FAILED = "auth.unlock_failed"
    PASSWORD_CHANGED = "auth.password_changed"
    PASSWORD_RESET = "auth.password_reset"
    PERMISSION_DENIED = "auth.permission_denied"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DISABLED = "user.disabled"
    USER_ENABLED = "user.enabled"
    USER_ROLES_CHANGED = "user.roles_changed"
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    SETTINGS_UPDATED = "settings.updated"
    BACKUP_CREATED = "backup.created"
    BACKUP_VERIFIED = "backup.verified"
    BACKUP_DELETED = "backup.deleted"
    BACKUP_RESTORED = "backup.restored"
    BACKUP_FAILED = "backup.failed"
    APP_STARTED = "app.started"
    JOURNAL_POSTED = "accounting.journal_posted"
    JOURNAL_VOIDED = "accounting.journal_voided"
    PERIOD_CLOSED = "accounting.period_closed"
    PERIOD_REOPENED = "accounting.period_reopened"
    STOCK_POSTED = "commerce.stock_posted"
    STOCK_REVERSED = "commerce.stock_reversed"
    INVOICE_POSTED = "commerce.invoice_posted"
    INVOICE_VOIDED = "commerce.invoice_voided"
    STOCK_COUNT_APPROVED = "commerce.stock_count_approved"
    NEGATIVE_STOCK_OVERRIDE = "commerce.negative_stock_override"
    UPDATE_STAGED = "update.staged"
    UPDATE_CHECKED = "update.checked"
    UPDATE_FAILED = "update.failed"
    UPDATE_ROLLED_BACK = "update.rolled_back"

    ALL = (
        SETUP_COMPLETED, LOGIN_SUCCESS, LOGIN_FAILED, ACCOUNT_LOCKED, ACCOUNT_UNLOCKED,
        LOGIN_BLOCKED_INACTIVE, LOGOUT, SESSION_LOCKED, UNLOCK_SUCCESS, UNLOCK_FAILED,
        PASSWORD_CHANGED, PASSWORD_RESET, PERMISSION_DENIED, USER_CREATED, USER_UPDATED,
        USER_DISABLED, USER_ENABLED, USER_ROLES_CHANGED, ROLE_CREATED, ROLE_UPDATED,
        ROLE_DELETED, SETTINGS_UPDATED, BACKUP_CREATED, BACKUP_VERIFIED, BACKUP_DELETED,
        BACKUP_RESTORED, BACKUP_FAILED, APP_STARTED, JOURNAL_POSTED, JOURNAL_VOIDED,
        PERIOD_CLOSED, PERIOD_REOPENED, STOCK_POSTED, STOCK_REVERSED, INVOICE_POSTED,
        INVOICE_VOIDED, STOCK_COUNT_APPROVED, NEGATIVE_STOCK_OVERRIDE,
        UPDATE_STAGED, UPDATE_CHECKED, UPDATE_FAILED, UPDATE_ROLLED_BACK,
    )


EVENT_TITLES_FA: dict[str, str] = {
    EventType.SETUP_COMPLETED: "تکمیل راه‌اندازی اولیه",
    EventType.LOGIN_SUCCESS: "ورود موفق",
    EventType.LOGIN_FAILED: "تلاش ناموفق ورود",
    EventType.ACCOUNT_LOCKED: "قفل حساب کاربری",
    EventType.ACCOUNT_UNLOCKED: "رفع قفل حساب کاربری",
    EventType.LOGIN_BLOCKED_INACTIVE: "ورود به حساب غیرفعال",
    EventType.LOGOUT: "خروج از سیستم",
    EventType.SESSION_LOCKED: "قفل نشست",
    EventType.UNLOCK_SUCCESS: "باز کردن قفل نشست",
    EventType.UNLOCK_FAILED: "تلاش ناموفق باز کردن قفل",
    EventType.PASSWORD_CHANGED: "تغییر رمز عبور",
    EventType.PASSWORD_RESET: "بازنشانی رمز عبور توسط مدیر",
    EventType.PERMISSION_DENIED: "عدم مجوز دسترسی",
    EventType.USER_CREATED: "ایجاد کاربر",
    EventType.USER_UPDATED: "ویرایش کاربر",
    EventType.USER_DISABLED: "غیرفعال‌سازی کاربر",
    EventType.USER_ENABLED: "فعال‌سازی کاربر",
    EventType.USER_ROLES_CHANGED: "تغییر نقش کاربر",
    EventType.ROLE_CREATED: "ایجاد نقش",
    EventType.ROLE_UPDATED: "ویرایش نقش",
    EventType.ROLE_DELETED: "حذف نقش",
    EventType.SETTINGS_UPDATED: "تغییر تنظیمات",
    EventType.BACKUP_CREATED: "ایجاد پشتیبان",
    EventType.BACKUP_VERIFIED: "بررسی صحت پشتیبان",
    EventType.BACKUP_DELETED: "حذف پشتیبان",
    EventType.BACKUP_RESTORED: "بازیابی پشتیبان",
    EventType.BACKUP_FAILED: "خطا در پشتیبان‌گیری",
    EventType.APP_STARTED: "اجرای برنامه",
    EventType.JOURNAL_POSTED: "ثبت نهایی سند حسابداری",
    EventType.JOURNAL_VOIDED: "ابطال سند حسابداری",
    EventType.PERIOD_CLOSED: "بستن دوره مالی",
    EventType.PERIOD_REOPENED: "بازگشایی دوره مالی",
    EventType.STOCK_POSTED: "ثبت سند انبار",
    EventType.STOCK_REVERSED: "برگشت سند انبار",
    EventType.INVOICE_POSTED: "ثبت نهایی فاکتور بازرگانی",
    EventType.INVOICE_VOIDED: "ابطال فاکتور بازرگانی",
    EventType.STOCK_COUNT_APPROVED: "تأیید انبارگردانی",
    EventType.NEGATIVE_STOCK_OVERRIDE: "عبور از محدودیت موجودی منفی",
    EventType.UPDATE_STAGED: "آماده‌سازی بستهٔ به‌روزرسانی",
    EventType.UPDATE_CHECKED: "بررسی به‌روزرسانی",
    EventType.UPDATE_FAILED: "شکست به‌روزرسانی",
    EventType.UPDATE_ROLLED_BACK: "بازگردانی به‌روزرسانی",
}

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

SEVERITY_TITLES_FA = {
    SEVERITY_INFO: "اطلاع",
    SEVERITY_WARNING: "هشدار",
    SEVERITY_CRITICAL: "بحرانی",
}


@dataclass(frozen=True)
class SecurityEventFilter:
    event_type: str | None = None
    severity: str | None = None
    username: str | None = None
    search: str | None = None
    date_from: _dt.datetime | None = None
    date_to: _dt.datetime | None = None


@dataclass(frozen=True)
class AuditFilter:
    entity_type: str | None = None
    action: str | None = None
    actor: str | None = None
    search: str | None = None
    date_from: _dt.datetime | None = None
    date_to: _dt.datetime | None = None


@dataclass(frozen=True)
class SecurityEventRow:
    id: int
    occurred_at: _dt.datetime
    event_type: str
    event_title_fa: str
    severity: str
    severity_title_fa: str
    username: str | None
    message_fa: str
    hostname: str | None
    details: dict | None


@dataclass(frozen=True)
class AuditRow:
    id: int
    occurred_at: _dt.datetime
    actor_username: str | None
    entity_type: str
    entity_id: str | None
    action: str
    summary_fa: str
    hostname: str | None
    before_data: dict | None
    after_data: dict | None


class AuditService:
    """Writes and reads both logs."""

    def __init__(self, db: Database, *, hostname: str | None = None) -> None:
        self.db = db
        self.hostname = hostname

    # -------------------------------------------------------------- writers
    def log_security(self, *, event_type: str, message_fa: str,
                     severity: str = SEVERITY_INFO, ctx: SecurityContext | None = None,
                     user_id: int | None = None, username: str | None = None,
                     details: dict[str, Any] | None = None,
                     session: Session | None = None,
                     occurred_at: _dt.datetime | None = None) -> SecurityEvent:
        event = SecurityEvent(
            occurred_at=occurred_at or utcnow(),
            event_type=event_type,
            severity=severity,
            user_id=user_id if user_id is not None else (ctx.user_id if ctx else None),
            username=username if username is not None else (ctx.username if ctx else None),
            message_fa=message_fa,
            details=_sanitize(details) if details else None,
            hostname=self.hostname,
        )
        if session is not None:
            session.add(event)
            return event
        with self.db.session_scope() as own_session:
            own_session.add(event)
        return event

    def log_audit(self, *, ctx: SecurityContext | None, entity_type: str, entity_id: Any,
                  action: str, summary_fa: str, before: dict[str, Any] | None = None,
                  after: dict[str, Any] | None = None, session: Session | None = None,
                  occurred_at: _dt.datetime | None = None) -> AuditLog:
        entry = AuditLog(
            occurred_at=occurred_at or utcnow(),
            user_id=ctx.user_id if ctx else None,
            actor_username=ctx.username if ctx else None,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            action=action,
            summary_fa=summary_fa,
            before_data=_sanitize(before) if before else None,
            after_data=_sanitize(after) if after else None,
            hostname=self.hostname,
        )
        if session is not None:
            session.add(entry)
            return entry
        with self.db.session_scope() as own_session:
            own_session.add(entry)
        return entry

    # -------------------------------------------------------------- readers
    def list_security_events(self, filters: SecurityEventFilter | None = None,
                             *, page: int = 1, page_size: int = 25) -> Page[SecurityEventRow]:
        filters = filters or SecurityEventFilter()
        page, page_size = normalize_page(page, page_size)
        conditions = []
        if filters.event_type:
            conditions.append(SecurityEvent.event_type == filters.event_type)
        if filters.severity:
            conditions.append(SecurityEvent.severity == filters.severity)
        if filters.username:
            conditions.append(SecurityEvent.username.ilike(f"%{filters.username.strip()}%"))
        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            conditions.append(or_(SecurityEvent.message_fa.ilike(pattern),
                                  SecurityEvent.username.ilike(pattern),
                                  SecurityEvent.event_type.ilike(pattern)))
        if filters.date_from:
            conditions.append(SecurityEvent.occurred_at >= filters.date_from)
        if filters.date_to:
            conditions.append(SecurityEvent.occurred_at <= filters.date_to)

        with self.db.session_scope() as session:
            count_stmt = select(func.count(SecurityEvent.id))
            stmt = select(SecurityEvent)
            for condition in conditions:
                count_stmt = count_stmt.where(condition)
                stmt = stmt.where(condition)
            total = int(session.execute(count_stmt).scalar() or 0)
            page = clamp_page(page, page_size, total)
            stmt = stmt.order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc())
            stmt = stmt.limit(page_size).offset((page - 1) * page_size)
            events = list(session.execute(stmt).scalars())
            rows = [self._event_row(event) for event in events]
        return Page(rows, total, page, page_size)

    def list_audit_logs(self, filters: AuditFilter | None = None,
                        *, page: int = 1, page_size: int = 25) -> Page[AuditRow]:
        filters = filters or AuditFilter()
        page, page_size = normalize_page(page, page_size)
        conditions = []
        if filters.entity_type:
            conditions.append(AuditLog.entity_type == filters.entity_type)
        if filters.action:
            conditions.append(AuditLog.action == filters.action)
        if filters.actor:
            conditions.append(AuditLog.actor_username.ilike(f"%{filters.actor.strip()}%"))
        if filters.search:
            pattern = f"%{filters.search.strip()}%"
            conditions.append(or_(AuditLog.summary_fa.ilike(pattern),
                                  AuditLog.actor_username.ilike(pattern)))
        if filters.date_from:
            conditions.append(AuditLog.occurred_at >= filters.date_from)
        if filters.date_to:
            conditions.append(AuditLog.occurred_at <= filters.date_to)

        with self.db.session_scope() as session:
            count_stmt = select(func.count(AuditLog.id))
            stmt = select(AuditLog)
            for condition in conditions:
                count_stmt = count_stmt.where(condition)
                stmt = stmt.where(condition)
            total = int(session.execute(count_stmt).scalar() or 0)
            page = clamp_page(page, page_size, total)
            stmt = stmt.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            stmt = stmt.limit(page_size).offset((page - 1) * page_size)
            entries = list(session.execute(stmt).scalars())
            rows = [AuditRow(
                id=e.id, occurred_at=e.occurred_at, actor_username=e.actor_username,
                entity_type=e.entity_type, entity_id=e.entity_id, action=e.action,
                summary_fa=e.summary_fa, hostname=e.hostname,
                before_data=e.before_data, after_data=e.after_data) for e in entries]
        return Page(rows, total, page, page_size)

    def recent_events(self, limit: int = 8) -> list[SecurityEventRow]:
        page = self.list_security_events(page=1, page_size=max(1, min(limit, 50)))
        return list(page.items)

    def count_events(self, event_type: str, *, since: _dt.datetime | None = None,
                     username: str | None = None, severity: str | None = None) -> int:
        conditions = [SecurityEvent.event_type == event_type]
        if since is not None:
            conditions.append(SecurityEvent.occurred_at >= since)
        if username:
            conditions.append(SecurityEvent.username == username)
        if severity:
            conditions.append(SecurityEvent.severity == severity)
        with self.db.session_scope() as session:
            stmt = select(func.count(SecurityEvent.id))
            for condition in conditions:
                stmt = stmt.where(condition)
            return int(session.execute(stmt).scalar() or 0)

    def failed_login_series(self, days: int = 7) -> list[tuple[_dt.datetime, int]]:
        """Return ``[(day_start_utc, count)]`` for the last ``days`` local days."""
        from pars_erp.core.timeutil import day_bounds_utc

        days = max(1, min(days, 90))
        today = utcnow()
        series: list[tuple[_dt.datetime, int]] = []
        with self.db.session_scope() as session:
            for offset in range(days - 1, -1, -1):
                start, end = day_bounds_utc((today - _dt.timedelta(days=offset)).date())
                stmt = (select(func.count(SecurityEvent.id))
                        .where(SecurityEvent.event_type == EventType.LOGIN_FAILED)
                        .where(SecurityEvent.occurred_at >= start)
                        .where(SecurityEvent.occurred_at < end))
                count = int(session.execute(stmt).scalar() or 0)
                series.append((start, count))
        return series

    @staticmethod
    def _event_row(event: SecurityEvent) -> SecurityEventRow:
        return SecurityEventRow(
            id=event.id,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            event_title_fa=EVENT_TITLES_FA.get(event.event_type, event.event_type),
            severity=event.severity,
            severity_title_fa=SEVERITY_TITLES_FA.get(event.severity, event.severity),
            username=event.username,
            message_fa=event.message_fa,
            hostname=event.hostname,
            details=event.details,
        )

    # ------------------------------------------------------------- helpers
    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Only the fields that actually changed - keeps audit rows readable."""
        changes = {}
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            if old != new:
                changes[key] = {"before": old, "after": new}
        return _sanitize(changes)

    def event_types(self) -> Iterable[tuple[str, str]]:
        return sorted(((code, EVENT_TITLES_FA.get(code, code)) for code in EventType.ALL),
                      key=lambda item: item[1])
