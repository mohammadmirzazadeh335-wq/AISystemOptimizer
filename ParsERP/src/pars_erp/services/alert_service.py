"""Management alerts: rules that are evaluated against real data, never faked.

Rules are **code** (a key exists or it does not), but their state is data: an
administrator can switch a rule off, change its severity and change its
threshold. Evaluation never invents a warning:

* a rule whose module the caller may not read is skipped, not guessed;
* a rule with nothing to report produces nothing;
* the same condition cannot raise the same alert twice - ``dedupe_key`` (rule +
  scope + day) is unique in the database, so evaluating the rules on every screen
  refresh is harmless.

Alert history is kept: acknowledging and resolving set timestamps and the acting
user, and every transition is written to the audit log.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.core.errors import AppError, NotFoundError, ValidationError
from pars_erp.core.money import format_amount
from pars_erp.core.timeutil import now_local
from pars_erp.db.models import Alert, AlertRule
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITIES: tuple[tuple[str, str], ...] = (
    (SEVERITY_INFO, "اطلاع"),
    (SEVERITY_WARNING, "هشدار"),
    (SEVERITY_CRITICAL, "بحرانی"),
)
SEVERITY_TITLES_FA = dict(SEVERITIES)
SEVERITY_ORDER = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}


@dataclass(frozen=True)
class AlertRuleDef:
    key: str
    title_fa: str
    section: str
    severity: str
    description_fa: str
    default_threshold: dict
    cooldown_hours: int = 24


@dataclass(frozen=True)
class AlertCandidate:
    rule_key: str
    title_fa: str
    message_fa: str
    severity: str
    dedupe_scope: str
    entity_type: str | None = None
    entity_id: str | None = None
    value_amount: Decimal | None = None


@dataclass(frozen=True)
class AlertRuleRow:
    id: int
    key: str
    title_fa: str
    section: str
    severity: str
    severity_fa: str
    is_enabled: bool
    threshold: dict
    cooldown_hours: int
    description_fa: str
    last_evaluated_at: _dt.datetime | None


@dataclass(frozen=True)
class AlertRow:
    id: int
    rule_key: str
    severity: str
    severity_fa: str
    title_fa: str
    message_fa: str
    raised_at: _dt.datetime
    acknowledged_at: _dt.datetime | None
    resolved_at: _dt.datetime | None
    value_amount: Decimal | None
    note_fa: str

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None


#: The catalogue of rules the product ships. Thresholds are data.
ALERT_RULE_DEFS: tuple[AlertRuleDef, ...] = (
    AlertRuleDef(
        "low_stock", "کمبود موجودی کالا", "inventory", SEVERITY_WARNING,
        "کالاهایی که موجودی آن‌ها به حد سفارش رسیده است.", {"min_items": 1}),
    AlertRuleDef(
        "cheques_due", "چک نزدیک سررسید", "treasury", SEVERITY_WARNING,
        "چک‌های باز که در بازهٔ پیش‌رو سررسید می‌شوند.", {"days": 7, "min_items": 1}),
    AlertRuleDef(
        "receivables_overdue", "مطالبات سررسیدگذشته", "treasury", SEVERITY_WARNING,
        "مطالباتی که بیش از حد مجاز معطل مانده‌اند.", {"min_amount": "1"}),
    AlertRuleDef(
        "payables_overdue", "بدهی سررسیدگذشته", "treasury", SEVERITY_CRITICAL,
        "بدهی‌هایی که بیش از حد مجاز معطل مانده‌اند.", {"min_amount": "1"}),
    AlertRuleDef(
        "backup_stale", "کهنه بودن پشتیبان", "system", SEVERITY_CRITICAL,
        "از آخرین پشتیبان سالم بیش از حد انتظار گذشته است.", {"hours": 48}),
)
RULE_DEFS_BY_KEY = {rule.key: rule for rule in ALERT_RULE_DEFS}


class AlertService:
    def __init__(self, db: Database, audit: AuditService, *, backups=None,
                 treasury_reports=None, commerce_reports=None) -> None:
        self.db = db
        self.audit = audit
        self.backups = backups
        self.treasury_reports = treasury_reports
        self.commerce_reports = commerce_reports

    # ------------------------------------------------------------------- rules
    def ensure_rules(self) -> None:
        """Create the missing rule rows (idempotent; safe on every start)."""
        with self.db.session_scope() as session:
            existing = {row.key for row in session.execute(select(AlertRule)).scalars()}
            for definition in ALERT_RULE_DEFS:
                if definition.key in existing:
                    continue
                session.add(AlertRule(
                    key=definition.key, title_fa=definition.title_fa,
                    section=definition.section, severity=definition.severity,
                    is_enabled=True, threshold=dict(definition.default_threshold),
                    cooldown_hours=definition.cooldown_hours))

    def rules(self, ctx: SecurityContext | None) -> tuple[AlertRuleRow, ...]:
        require_permission(ctx, "alerts.view")
        self.ensure_rules()
        with self.db.session_scope() as session:
            rows = session.execute(select(AlertRule).order_by(AlertRule.key)).scalars().all()
            return tuple(self._rule_row(row) for row in rows)

    def set_rule(self, ctx: SecurityContext | None, key: str, *, is_enabled: bool | None = None,
                 severity: str | None = None, threshold: dict | None = None) -> AlertRuleRow:
        require_permission(ctx, "alerts.manage")
        if key not in RULE_DEFS_BY_KEY:
            raise ValidationError("این قاعدهٔ هشدار در سیستم تعریف نشده است.")
        if severity is not None and severity not in SEVERITY_TITLES_FA:
            raise ValidationError("سطح اهمیت هشدار نامعتبر است.")
        self.ensure_rules()
        with self.db.session_scope() as session:
            row = session.execute(select(AlertRule).where(AlertRule.key == key)).scalar_one()
            before = {"enabled": row.is_enabled, "severity": row.severity,
                      "threshold": dict(row.threshold or {})}
            if is_enabled is not None:
                row.is_enabled = bool(is_enabled)
            if severity is not None:
                row.severity = severity
            if threshold is not None:
                row.threshold = dict(threshold)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="alert_rule", entity_id=row.id, action="update",
                summary_fa=f"تغییر تنظیم قاعدهٔ هشدار «{row.title_fa}»",
                before=before,
                after={"enabled": row.is_enabled, "severity": row.severity,
                       "threshold": dict(row.threshold or {})}, session=session)
            return self._rule_row(row)

    # -------------------------------------------------------------- evaluation
    def evaluate(self, ctx: SecurityContext | None) -> tuple[AlertRow, ...]:
        """Evaluate every enabled rule and store the new alerts."""
        require_permission(ctx, "alerts.view")
        self.ensure_rules()
        created: list[int] = []
        with self.db.session_scope() as session:
            rules = session.execute(
                select(AlertRule).where(AlertRule.is_enabled.is_(True))).scalars().all()
            for rule in rules:
                definition = RULE_DEFS_BY_KEY.get(rule.key)
                if definition is None:
                    continue
                try:
                    candidates = self._candidates(ctx, rule, definition)
                except AppError:
                    continue  # no permission for this module: no alert, no guess

                for candidate in candidates:
                    dedupe_key = self._dedupe_key(rule, candidate)
                    exists = session.execute(
                        select(Alert.id).where(Alert.dedupe_key == dedupe_key)).first()
                    if exists:
                        continue
                    alert = Alert(
                        rule_key=rule.key, severity=rule.severity,
                        title_fa=candidate.title_fa, message_fa=candidate.message_fa,
                        dedupe_key=dedupe_key, entity_type=candidate.entity_type,
                        entity_id=candidate.entity_id,
                        value_amount=candidate.value_amount,
                        raised_at=utcnow())
                    session.add(alert)
                    try:
                        session.flush()
                    except IntegrityError:  # pragma: no cover - concurrent evaluation
                        session.rollback()
                        continue
                    created.append(alert.id)
                rule.last_evaluated_at = utcnow()
            rows = [self._alert_row(session.get(Alert, alert_id)) for alert_id in created]
        return tuple(rows)

    def _candidates(self, ctx, rule: AlertRule, definition: AlertRuleDef) -> list[AlertCandidate]:
        threshold = dict(rule.threshold or definition.default_threshold)
        if rule.key == "low_stock":
            if self.commerce_reports is None:
                return []
            table = self.commerce_reports.low_stock(ctx)
            minimum = int(threshold.get("min_items", 1))
            if table.row_count < minimum:
                return []
            return [AlertCandidate(
                rule_key=rule.key, title_fa=definition.title_fa, severity=rule.severity,
                message_fa=f"{table.row_count} کالا به حد سفارش رسیده است.",
                dedupe_scope=f"count:{table.row_count}")]
        if rule.key == "cheques_due":
            if self.treasury_reports is None:
                return []
            table = self.treasury_reports.cheques_due(ctx, days=int(threshold.get("days", 7)))
            minimum = int(threshold.get("min_items", 1))
            if table.row_count < minimum:
                return []
            return [AlertCandidate(
                rule_key=rule.key, title_fa=definition.title_fa, severity=rule.severity,
                message_fa=f"{table.row_count} چک در روزهای آینده سررسید می‌شود.",
                dedupe_scope=f"count:{table.row_count}")]
        if rule.key in ("receivables_overdue", "payables_overdue"):
            if self.treasury_reports is None:
                return []
            figures = self.treasury_reports.dashboard(ctx)
            amount = (figures.overdue_receivables if rule.key == "receivables_overdue"
                      else figures.overdue_payables)
            minimum = Decimal(str(threshold.get("min_amount", "1")))
            if amount < minimum or amount <= 0:
                return []
            label = "مطالبات" if rule.key == "receivables_overdue" else "بدهی‌"
            return [AlertCandidate(
                rule_key=rule.key, title_fa=definition.title_fa, severity=rule.severity,
                message_fa=f"{label} سررسیدگذشته: {format_amount(amount)}",
                dedupe_scope="amount", value_amount=amount)]
        if rule.key == "backup_stale":
            if self.backups is None:
                return []
            last_at = self.backups.last_backup_at()
            hours = int(threshold.get("hours", 48))
            now = utcnow()
            if last_at is None:
                return [AlertCandidate(
                    rule_key=rule.key, title_fa=definition.title_fa, severity=rule.severity,
                    message_fa="هیچ پشتیبان سالمی ثبت نشده است.", dedupe_scope="never")]
            age_hours = (now - last_at).total_seconds() / 3600
            if age_hours < hours:
                return []
            return [AlertCandidate(
                rule_key=rule.key, title_fa=definition.title_fa, severity=rule.severity,
                message_fa=f"از آخرین پشتیبان {int(age_hours)} ساعت گذشته است.",
                dedupe_scope="stale")]
        return []

    @staticmethod
    def _dedupe_key(rule: AlertRule, candidate: AlertCandidate) -> str:
        day = now_local().date().isoformat()
        return f"{rule.key}:{candidate.dedupe_scope}:{day}"[:180]

    # --------------------------------------------------------------- read/act
    def open_alerts(self, ctx: SecurityContext | None, *, limit: int = 100) -> tuple[AlertRow, ...]:
        require_permission(ctx, "alerts.view")
        with self.db.session_scope() as session:
            rows = session.execute(
                select(Alert).where(Alert.resolved_at.is_(None))
                .order_by(Alert.raised_at.desc()).limit(max(1, min(limit, 500)))).scalars().all()
            result = [self._alert_row(row) for row in rows]
        return tuple(sorted(result, key=lambda row: (
            SEVERITY_ORDER.get(row.severity, 9), -row.raised_at.timestamp())))

    def open_count(self, ctx: SecurityContext | None) -> int:
        require_permission(ctx, "alerts.view")
        with self.db.session_scope() as session:
            return len(session.execute(
                select(Alert.id).where(Alert.resolved_at.is_(None))).all())

    def history(self, ctx: SecurityContext | None, *, limit: int = 200) -> tuple[AlertRow, ...]:
        require_permission(ctx, "alerts.view")
        with self.db.session_scope() as session:
            rows = session.execute(select(Alert).order_by(Alert.raised_at.desc())
                                   .limit(max(1, min(limit, 1000)))).scalars().all()
            return tuple(self._alert_row(row) for row in rows)

    def acknowledge(self, ctx: SecurityContext | None, alert_id: int,
                    note: str = "") -> AlertRow:
        require_permission(ctx, "alerts.manage")
        with self.db.session_scope() as session:
            row = self._get(session, alert_id)
            row.acknowledged_at = utcnow()
            row.acknowledged_by_id = ctx.user_id if ctx else None
            if note:
                row.note_fa = note.strip()[:400]
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="alert", entity_id=row.id, action="acknowledge",
                summary_fa=f"تأیید مشاهدهٔ هشدار «{row.title_fa}»", session=session)
            return self._alert_row(row)

    def resolve(self, ctx: SecurityContext | None, alert_id: int, note: str = "") -> AlertRow:
        require_permission(ctx, "alerts.manage")
        with self.db.session_scope() as session:
            row = self._get(session, alert_id)
            row.resolved_at = utcnow()
            row.resolved_by_id = ctx.user_id if ctx else None
            if note:
                row.note_fa = note.strip()[:400]
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="alert", entity_id=row.id, action="resolve",
                summary_fa=f"بستن هشدار «{row.title_fa}»", session=session)
            return self._alert_row(row)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _get(session, alert_id: int) -> Alert:
        row = session.get(Alert, alert_id)
        if row is None:
            raise NotFoundError("هشدار یافت نشد.")
        return row

    @staticmethod
    def _rule_row(row: AlertRule) -> AlertRuleRow:
        definition = RULE_DEFS_BY_KEY.get(row.key)
        return AlertRuleRow(
            id=row.id, key=row.key, title_fa=row.title_fa, section=row.section,
            severity=row.severity, severity_fa=SEVERITY_TITLES_FA.get(row.severity, row.severity),
            is_enabled=bool(row.is_enabled), threshold=dict(row.threshold or {}),
            cooldown_hours=int(row.cooldown_hours or 24),
            description_fa=definition.description_fa if definition else "",
            last_evaluated_at=row.last_evaluated_at)

    @staticmethod
    def _alert_row(row: Alert) -> AlertRow:
        return AlertRow(
            id=row.id, rule_key=row.rule_key, severity=row.severity,
            severity_fa=SEVERITY_TITLES_FA.get(row.severity, row.severity),
            title_fa=row.title_fa, message_fa=row.message_fa or "",
            raised_at=row.raised_at, acknowledged_at=row.acknowledged_at,
            resolved_at=row.resolved_at, value_amount=row.value_amount,
            note_fa=row.note_fa or "")
