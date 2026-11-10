"""Dashboard aggregation - every number comes from the database, never invented."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from sqlalchemy import func, select

from pars_erp import __version__
from pars_erp.core.timeutil import day_bounds_utc, days_ago_utc, humanize_delta_fa
from pars_erp.db.models import AppMetadata, BackupRecord, Role, User, UserSession
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import (
    AuditService,
    EventType,
    SecurityEventRow,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)
from pars_erp.services.backup_service import BackupService
from pars_erp.services.settings_service import SettingsService


@dataclass(frozen=True)
class SeriesPoint:
    label_fa: str
    value: int


@dataclass(frozen=True)
class DashboardOverview:
    generated_at: _dt.datetime
    app_version: str
    schema_revision: str | None
    backend: str
    database_size_bytes: int | None

    app_name: str
    company_name: str
    currency_code: str

    users_total: int
    users_active: int
    users_inactive: int
    users_locked: int
    users_must_change_password: int

    roles_total: int
    roles_custom: int

    sessions_open: int
    logins_today: int
    failed_logins_24h: int
    failed_logins_7d: int
    events_today: int
    critical_events_today: int
    warning_events_today: int

    last_backup_at: _dt.datetime | None
    last_backup_label: str
    backup_count: int
    backup_size_mb: float
    backup_is_stale: bool

    failed_login_series: tuple[SeriesPoint, ...] = ()
    recent_events: tuple[SecurityEventRow, ...] = ()
    installation_id: str | None = None
    startup_count: int = 0
    idle_lock_minutes: int = 10

    @property
    def can_view_audit(self) -> bool:
        return bool(self.recent_events)

    @property
    def database_size_label(self) -> str:
        if self.database_size_bytes is None:
            return "—"
        size = self.database_size_bytes
        if size < 1024 * 1024:
            return f"{size / 1024:.0f} کیلوبایت"
        return f"{size / (1024 * 1024):.1f} مگابایت"


class DashboardService:
    def __init__(self, db: Database, settings: SettingsService, audit: AuditService,
                 backups: BackupService, *, app_version: str = __version__) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.backups = backups
        self.app_version = app_version

    def overview(self, ctx: SecurityContext | None) -> DashboardOverview:
        require_permission(ctx, "dashboard.view")
        snapshot = self.settings.snapshot()
        now = utcnow()
        today_start, today_end = day_bounds_utc()
        since_24h = now - _dt.timedelta(hours=24)
        since_7d = days_ago_utc(6)

        with self.db.session_scope() as session:
            users_total = self._count(session, select(func.count(User.id)))
            users_active = self._count(session, select(func.count(User.id)).where(
                User.is_active.is_(True)))
            users_inactive = users_total - users_active
            users_locked = self._count(session, select(func.count(User.id)).where(
                User.locked_until.is_not(None), User.locked_until > now))
            must_change = self._count(session, select(func.count(User.id)).where(
                User.must_change_password.is_(True), User.is_active.is_(True)))
            roles_total = self._count(session, select(func.count(Role.id)))
            roles_custom = self._count(session, select(func.count(Role.id)).where(
                Role.is_system.is_(False)))
            sessions_open = self._count(session, select(func.count(UserSession.id)).where(
                UserSession.logout_at.is_(None)))
            logins_today = self._count(session, select(func.count(UserSession.id)).where(
                UserSession.login_at >= today_start, UserSession.login_at < today_end))
            backup_count = self._count(session, select(func.count(BackupRecord.id)))
            metadata = session.get(AppMetadata, 1)
            installation_id = metadata.installation_id if metadata else None
            startup_count = int(metadata.startup_count or 0) if metadata else 0

        failed_24h = self.audit.count_events(EventType.LOGIN_FAILED, since=since_24h)
        failed_7d = self.audit.count_events(EventType.LOGIN_FAILED, since=since_7d)
        events_today = self._events_today(today_start, today_end)
        critical_today = self._count_by_severity(today_start, today_end, SEVERITY_CRITICAL)
        warning_today = self._count_by_severity(today_start, today_end, SEVERITY_WARNING)

        series = tuple(SeriesPoint(label_fa=self._day_label(start), value=value)
                       for start, value in self.audit.failed_login_series(days=7))

        recent: tuple[SecurityEventRow, ...] = ()
        if ctx is not None and ctx.has("audit.view"):
            recent = tuple(self.audit.recent_events(limit=8))

        last_backup = self.backups.last_backup()
        last_backup_at = last_backup.created_at if last_backup else None
        backup_stale = (last_backup_at is None or
                        (now - last_backup_at) > _dt.timedelta(
                            hours=max(1, snapshot.int("backup_interval_hours")) + 1))

        return DashboardOverview(
            generated_at=now,
            app_version=self.app_version,
            schema_revision=self.db.schema_revision(),
            backend=self.db.dialect_name(),
            database_size_bytes=self.db.size_bytes(),
            app_name=snapshot.app_name,
            company_name=snapshot.company_name,
            currency_code=snapshot.currency_code,
            users_total=users_total,
            users_active=users_active,
            users_inactive=users_inactive,
            users_locked=users_locked,
            users_must_change_password=must_change,
            roles_total=roles_total,
            roles_custom=roles_custom,
            sessions_open=sessions_open,
            logins_today=logins_today,
            failed_logins_24h=failed_24h,
            failed_logins_7d=failed_7d,
            events_today=events_today,
            critical_events_today=critical_today,
            warning_events_today=warning_today,
            last_backup_at=last_backup_at,
            last_backup_label=(humanize_delta_fa(last_backup_at) if last_backup_at
                               else "هیچ پشتیبانی گرفته نشده"),
            backup_count=backup_count,
            backup_size_mb=round(self.backups.total_backup_bytes() / (1024 * 1024), 2),
            backup_is_stale=backup_stale,
            failed_login_series=series,
            recent_events=recent,
            installation_id=installation_id,
            startup_count=startup_count,
            idle_lock_minutes=snapshot.idle_lock_minutes,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _count(session, stmt) -> int:
        return int(session.execute(stmt).scalar() or 0)

    def _events_today(self, start: _dt.datetime, end: _dt.datetime) -> int:
        from pars_erp.db.models import SecurityEvent
        with self.db.session_scope() as session:
            return int(session.execute(
                select(func.count(SecurityEvent.id))
                .where(SecurityEvent.occurred_at >= start)
                .where(SecurityEvent.occurred_at < end)).scalar() or 0)

    def _count_by_severity(self, start: _dt.datetime, end: _dt.datetime, severity: str) -> int:
        from pars_erp.db.models import SecurityEvent
        with self.db.session_scope() as session:
            return int(session.execute(
                select(func.count(SecurityEvent.id))
                .where(SecurityEvent.occurred_at >= start)
                .where(SecurityEvent.occurred_at < end)
                .where(SecurityEvent.severity == severity)).scalar() or 0)

    @staticmethod
    def _day_label(day_start_utc: _dt.datetime) -> str:
        from pars_erp.core.jalali import JalaliDate
        from pars_erp.core.timeutil import to_local
        local = to_local(day_start_utc)
        jalali = JalaliDate.from_gregorian(local.date())
        return f"{jalali.day} {jalali.month_name}"
