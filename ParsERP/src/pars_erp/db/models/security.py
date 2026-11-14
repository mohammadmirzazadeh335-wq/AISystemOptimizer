"""Identity, authorisation and security-trace models."""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pars_erp.db.base import Base, TimestampMixin
from pars_erp.db.types import JsonDocument, UtcDateTime

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    """An atomic capability, e.g. ``users.create``.

    The authoritative catalogue lives in :mod:`pars_erp.security.permissions`;
    rows here exist so roles can reference them with real foreign keys.
    """

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    section: Mapped[str] = mapped_column(String(40), nullable=False)
    section_title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    title_fa: Mapped[str] = mapped_column(String(160), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Permission {self.code}>"


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title_fa: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, lazy="selectin", order_by="Permission.sort_order")

    def has_permission(self, code: str) -> bool:
        return any(p.code == code for p in self.permissions)

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for p in self.permissions}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Role {self.code}>"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_login_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_failed_login_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_login_host: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, lazy="selectin", order_by="Role.sort_order")

    @property
    def role_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.roles)

    @property
    def permission_codes(self) -> set[str]:
        codes: set[str] = set()
        for role in self.roles:
            codes |= role.permission_codes
        return codes

    def is_locked(self, now: _dt.datetime | None = None) -> bool:
        from pars_erp.db.types import utcnow
        if self.locked_until is None:
            return False
        return self.locked_until > (now or utcnow())

    def display_name(self) -> str:
        return f"{self.full_name} ({self.username})"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username}>"


class UserSession(Base):
    """Login/logout trail - the basis of the 'who was on the system when' report."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    login_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    logout_at: Mapped[_dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    logout_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User | None] = relationship(lazy="joined")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserSession {self.username} @{self.login_at}>"


class SecurityEvent(Base):
    """Append-only security log (logins, lockouts, permission failures, ...)."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_severity", "severity", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    message_fa: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped[User | None] = relationship(lazy="joined")


class AuditLog(Base):
    """Append-only business audit trail (who changed which record and how)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[_dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    summary_fa: Mapped[str] = mapped_column(String(500), nullable=False)
    before_data: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
