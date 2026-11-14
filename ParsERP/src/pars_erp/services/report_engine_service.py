"""The service behind the report centre: run reports, save them, export them.

The service is deliberately thin - all the interesting work (which reports exist,
what they may read, how rows are filtered and paged) lives in
:mod:`pars_erp.reporting.engine` and :mod:`pars_erp.reporting.catalogue`. What the
service adds is:

* permission checks per action (``reports.center`` to see the list,
  ``reports.export`` to write a file, ``reports.designer`` to change a definition,
  ``reports.share`` to share it, plus each report's own permission to run it);
* persistence of saved reports and their shares;
* audit entries for every change to a saved report (who, when, what changed);
* file export through the same renderer every other screen uses.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import SavedReport, SavedReportShare, User
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.reporting.engine import (
    ReportCatalogue,
    ReportDefinition,
    ReportQuery,
    ReportResult,
    run as run_report,
)
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.report_render_service import (
    ExportOutcome,
    ReportColumn,
    ReportRenderer,
    ReportTable,
)
from pars_erp.services.settings_service import SettingsService

SHARE_ROLE = "role"
SHARE_USER = "user"

MAX_SAVED_REPORTS_PER_USER = 80


@dataclass(frozen=True)
class SaveReportInput:
    name: str
    definition_key: str
    description: str = ""
    column_keys: tuple[str, ...] = ()
    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    period_id: int | None = None
    party_id: int | None = None
    account_id: int | None = None
    cost_center_id: int | None = None
    project_id: int | None = None
    product_id: int | None = None
    warehouse_id: int | None = None
    org_unit_id: int | None = None
    sort_key: str | None = None
    sort_desc: bool = False
    group_by: str | None = None
    page_size: int = 100
    params: Mapping[str, object] = field(default_factory=dict)
    is_shared: bool = False
    is_default: bool = False


@dataclass(frozen=True)
class SavedReportRow:
    id: int
    name: str
    definition_key: str
    definition_title_fa: str
    description: str
    owner_user_id: int
    owner_username: str
    column_keys: tuple[str, ...]
    sort_key: str | None
    sort_desc: bool
    group_by: str | None
    page_size: int
    is_shared: bool
    is_default: bool
    is_mine: bool
    run_count: int
    last_run_at: _dt.datetime | None
    shared_with_fa: tuple[str, ...] = ()

    @property
    def scope_fa(self) -> str:
        if self.is_mine:
            return "شخصی"
        return "اشتراکی"


class ReportEngineService:
    def __init__(self, db: Database, settings: SettingsService, audit: AuditService,
                 catalogue: ReportCatalogue) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.catalogue = catalogue

    # ------------------------------------------------------------------ listing
    def definition(self, ctx: SecurityContext | None, key: str) -> ReportDefinition:
        definition = self.catalogue.get(key)
        require_permission(ctx, definition.permission)
        return definition

    def definitions(self, ctx: SecurityContext | None) -> tuple[ReportDefinition, ...]:
        require_permission(ctx, "reports.center")
        return self.catalogue.visible(ctx)

    def sections(self, ctx: SecurityContext | None):
        require_permission(ctx, "reports.center")
        return self.catalogue.sections(ctx)

    def columns(self, ctx: SecurityContext | None, key: str) -> tuple[ReportColumn, ...]:
        """The columns a report produces, discovered by running it once."""
        definition = self.definition(ctx, key)
        result = run_report(definition, ReportQuery(page_size=100), ctx)
        return result.columns

    # --------------------------------------------------------------- execution
    def run(self, ctx: SecurityContext | None, *, definition_key: str,
            query: ReportQuery | None = None, saved_id: int | None = None) -> ReportResult:
        definition = self.definition(ctx, definition_key)
        result = run_report(definition, query or ReportQuery(), ctx)
        if saved_id is not None:
            self._touch_saved(ctx, saved_id, result.total_rows)
        return result

    def run_saved(self, ctx: SecurityContext | None, saved_id: int,
                  query: ReportQuery | None = None) -> ReportResult:
        with self.db.session_scope() as session:
            row = session.get(SavedReport, saved_id)
            if row is None:
                raise NotFoundError("گزارش ذخیره‌شده یافت نشد.")
            if not self._can_read(row, ctx):
                require_permission(ctx, "reports.center")
                raise NotFoundError("گزارش ذخیره‌شده یافت نشد.")
            definition_key = row.definition_key
            merged = self._merge_query(row, query)
        return self.run(ctx, definition_key=definition_key, query=merged, saved_id=saved_id)

    @staticmethod
    def _merge_query(row: SavedReport, query: ReportQuery | None) -> ReportQuery:
        payload = dict(row.filters or {})
        for key in ("date_from", "date_to"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                payload[key] = _dt.date.fromisoformat(value)
            elif not value:
                payload[key] = None
        payload.pop("period_id", None) if not payload.get("period_id") else None
        base = ReportQuery(**payload)
        base = replace(base,
                       sort_key=row.sort_key,
                       sort_desc=bool(row.sort_desc),
                       group_by=row.group_by,
                       page_size=int(row.page_size or 100),
                       column_keys=tuple(row.columns) if row.columns else None,
                       params=dict(row.params or {}))
        if query is None:
            return base
        overrides = {key: value for key, value in query.__dict__.items()
                     if value not in (None, "", False, 0) and key != "params"}
        overrides.pop("page", None)
        overrides.pop("page_size", None)
        merged = replace(base, **overrides)
        if query.params:
            merged = replace(merged, params={**base.params, **query.params})
        return merged

    def _touch_saved(self, ctx: SecurityContext | None, saved_id: int, rows: int) -> None:
        with self.db.session_scope() as session:
            row = session.get(SavedReport, saved_id)
            if row is None:
                return
            row.run_count = int(row.run_count or 0) + 1
            row.last_run_at = utcnow()

    # ------------------------------------------------------------------- saving
    def save(self, ctx: SecurityContext | None, data: SaveReportInput) -> SavedReportRow:
        require_permission(ctx, "reports.center")
        definition = self.definition(ctx, data.definition_key)
        self._validate_definition_columns(ctx, definition, data)
        name = (data.name or "").strip()
        if len(name) < 3:
            raise ValidationError("نام گزارش باید دست‌کم سه نویسه باشد.")
        with self.db.session_scope() as session:
            count = len(session.execute(
                select(SavedReport.id).where(SavedReport.owner_user_id == ctx.user_id)
            ).all())
            if count >= MAX_SAVED_REPORTS_PER_USER:
                raise ValidationError(
                    f"بیش از {MAX_SAVED_REPORTS_PER_USER} گزارش ذخیره‌شده برای هر کاربر مجاز نیست.")
            row = SavedReport(
                name=name, definition_key=definition.key, owner_user_id=ctx.user_id,
                description=(data.description or "").strip()[:400],
                columns=list(data.column_keys) if data.column_keys else None,
                filters=self._filters_payload(data), params=dict(data.params or {}),
                sort_key=data.sort_key, sort_desc=bool(data.sort_desc),
                group_by=data.group_by, page_size=int(data.page_size or 100),
                is_shared=bool(data.is_shared), is_default=bool(data.is_default))
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:  # pragma: no cover - depends on the backend
                raise ConflictError("گزارشی با همین نام برای شما ثبت شده است.") from exc
            if data.is_default:
                self._clear_default(session, ctx.user_id, keep=row.id)
            self.audit.log_audit(
                ctx=ctx, entity_type="saved_report", entity_id=row.id, action="create",
                summary_fa=f"ذخیرهٔ گزارش «{row.name}» از منبع {definition.key}",
                after={"definition_key": row.definition_key, "shared": row.is_shared},
                session=session)
            return self.describe(ctx, self._row(session, row))

    def update(self, ctx: SecurityContext | None, report_id: int,
               data: SaveReportInput) -> SavedReportRow:
        require_permission(ctx, "reports.designer")
        definition = self.definition(ctx, data.definition_key)
        self._validate_definition_columns(ctx, definition, data)
        with self.db.session_scope() as session:
            row = self._owned(session, report_id, ctx)
            before = {"name": row.name, "definition_key": row.definition_key}
            row.name = (data.name or "").strip() or row.name
            row.definition_key = definition.key
            row.description = (data.description or "").strip()[:400]
            row.columns = list(data.column_keys) if data.column_keys else None
            row.filters = self._filters_payload(data)
            row.params = dict(data.params or {})
            row.sort_key = data.sort_key
            row.sort_desc = bool(data.sort_desc)
            row.group_by = data.group_by
            row.page_size = int(data.page_size or 100)
            row.is_shared = bool(data.is_shared)
            row.is_default = bool(data.is_default)
            if data.is_default:
                self._clear_default(session, row.owner_user_id, keep=row.id)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="saved_report", entity_id=row.id, action="update",
                summary_fa=f"ویرایش گزارش ذخیره‌شدهٔ «{row.name}»",
                before=before, after={"name": row.name, "definition_key": row.definition_key},
                session=session)
            return self.describe(ctx, self._row(session, row))

    def delete(self, ctx: SecurityContext | None, report_id: int) -> None:
        require_permission(ctx, "reports.center")
        with self.db.session_scope() as session:
            row = self._owned(session, report_id, ctx)
            name = row.name
            session.delete(row)
            self.audit.log_audit(
                ctx=ctx, entity_type="saved_report", entity_id=report_id, action="delete",
                summary_fa=f"حذف گزارش ذخیره‌شدهٔ «{name}»", session=session)

    def set_default(self, ctx: SecurityContext | None, report_id: int,
                    value: bool = True) -> None:
        require_permission(ctx, "reports.center")
        with self.db.session_scope() as session:
            row = self._owned(session, report_id, ctx)
            row.is_default = bool(value)
            if value:
                self._clear_default(session, row.owner_user_id, keep=row.id)

    def share(self, ctx: SecurityContext | None, report_id: int, *,
              role_codes: Sequence[str] = (), usernames: Sequence[str] = ()) -> SavedReportRow:
        require_permission(ctx, "reports.share")
        with self.db.session_scope() as session:
            row = self._owned(session, report_id, ctx)
            row.is_shared = True
            existing = {(share.scope_kind, share.scope_value)
                        for share in session.execute(
                            select(SavedReportShare).where(
                                SavedReportShare.report_id == row.id)).scalars()}
            for code in role_codes:
                code = (code or "").strip()
                if not code or (SHARE_ROLE, code) in existing:
                    continue
                session.add(SavedReportShare(report_id=row.id, scope_kind=SHARE_ROLE,
                                             scope_value=code))
            for username in usernames:
                username = (username or "").strip()
                if not username or (SHARE_USER, username) in existing:
                    continue
                user = session.execute(
                    select(User).where(User.username == username)).scalar_one_or_none()
                if user is None:
                    raise ValidationError(f"کاربر «{username}» یافت نشد.")
                session.add(SavedReportShare(report_id=row.id, scope_kind=SHARE_USER,
                                             scope_value=username))
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="saved_report", entity_id=row.id, action="share",
                summary_fa=f"اشتراک‌گذاری گزارش «{row.name}»",
                after={"roles": list(role_codes), "users": list(usernames)}, session=session)
            return self.describe(ctx, self._row(session, row))

    def saved_reports(self, ctx: SecurityContext | None) -> tuple[SavedReportRow, ...]:
        require_permission(ctx, "reports.center")
        with self.db.session_scope() as session:
            rows = session.execute(select(SavedReport).order_by(
                SavedReport.is_default.desc(), SavedReport.name)).scalars().all()
            result = [self.describe(ctx, self._row(session, row))
                      for row in rows if self._can_read(row, ctx)]
            return tuple(result)

    def default_report(self, ctx: SecurityContext | None) -> SavedReportRow | None:
        for row in self.saved_reports(ctx):
            if row.is_mine and row.is_default:
                return row
        return None

    # ------------------------------------------------------------------ exports
    def export_csv(self, ctx: SecurityContext | None, result: ReportResult, path: Path,
                   *, delimiter: str = ",", include_header: bool = True) -> Path:
        require_permission(ctx, "reports.export")
        table = result.table or ReportTable(title=result.title_fa, columns=result.columns,
                                            rows=result.rows)
        if "\n" in delimiter or not delimiter:
            raise ValidationError("جداکنندهٔ فایل CSV نامعتبر است.")
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL,
                            lineterminator="\r\n")
        writer.writerow([table.title])
        for line in (*table.meta, *result.filter_labels):
            writer.writerow([line])
        writer.writerow([])
        if include_header:
            writer.writerow([column.title_fa for column in table.columns])
        for row in table.rows:
            writer.writerow(["" if value is None else value for value in row])
        self._write_atomic(path, buffer.getvalue())
        return path

    def export_excel(self, ctx: SecurityContext | None, result: ReportResult,
                     path: Path) -> ExportOutcome:
        require_permission(ctx, "reports.export")
        return self._renderer(ctx).to_excel(self._export_table(result), path)

    def export_pdf(self, ctx: SecurityContext | None, result: ReportResult,
                   path: Path, *, theme: str = "light") -> ExportOutcome:
        require_permission(ctx, "reports.export")
        return self._renderer(ctx).to_pdf(self._export_table(result), path, theme=theme)

    def export_html(self, ctx: SecurityContext | None, result: ReportResult, *,
                    theme: str = "light") -> str:
        require_permission(ctx, "reports.export")
        return self._renderer(ctx).to_html(self._export_table(result), theme=theme)

    def _export_table(self, result: ReportResult) -> ReportTable:
        table = result.table or ReportTable(title=result.title_fa, columns=result.columns,
                                            rows=result.rows)
        meta = tuple(table.meta) + result.filter_labels
        return replace(table, meta=meta)

    def _renderer(self, ctx: SecurityContext | None) -> ReportRenderer:
        snapshot = self.settings.snapshot()
        return ReportRenderer(app_name=snapshot.app_name,
                              persian_digits=snapshot.bool("persian_digits"))

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=".report_", suffix=path.suffix,
                                             dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _filters_payload(data: SaveReportInput) -> dict:
        return {
            "date_from": data.date_from.isoformat() if data.date_from else None,
            "date_to": data.date_to.isoformat() if data.date_to else None,
            "period_id": data.period_id,
            "party_id": data.party_id,
            "account_id": data.account_id,
            "cost_center_id": data.cost_center_id,
            "project_id": data.project_id,
            "product_id": data.product_id,
            "warehouse_id": data.warehouse_id,
            "org_unit_id": data.org_unit_id,
        }

    def _validate_definition_columns(self, ctx: SecurityContext | None,
                                     definition: ReportDefinition,
                                     data: SaveReportInput) -> None:
        if not data.column_keys:
            return
        columns = self.columns(ctx, definition.key)
        known = {column.key for column in columns}
        unknown = [key for key in data.column_keys if key not in known]
        if unknown:
            raise ValidationError("ستون‌های انتخاب‌شده در این گزارش وجود ندارند.")
        if data.group_by and data.group_by not in known:
            raise ValidationError("ستون گروه‌بندی در این گزارش وجود ندارد.")
        if data.sort_key and data.sort_key not in known:
            raise ValidationError("ستون مرتب‌سازی در این گزارش وجود ندارد.")

    @staticmethod
    def _clear_default(session, user_id: int, *, keep: int | None) -> None:
        for other in session.execute(
                select(SavedReport).where(SavedReport.owner_user_id == user_id,
                                          SavedReport.is_default.is_(True))).scalars():
            if keep is None or other.id != keep:
                other.is_default = False

    def _owned(self, session, report_id: int, ctx: SecurityContext | None, *,
               allow_designer: bool = False) -> SavedReport:
        row = session.get(SavedReport, report_id)
        if row is None:
            raise NotFoundError("گزارش ذخیره‌شده یافت نشد.")
        if ctx is None:
            require_permission(ctx, "reports.center")
        mine = row.owner_user_id == ctx.user_id
        if mine:
            return row
        if allow_designer and ctx.has("reports.designer"):
            return row
        raise NotFoundError("گزارش ذخیره‌شده یافت نشد.")

    def _can_read(self, row: SavedReport, ctx: SecurityContext | None) -> bool:
        if ctx is None:
            return False
        if row.owner_user_id == ctx.user_id:
            return True
        if not row.is_shared:
            return False
        if ctx.has("reports.designer"):
            return True
        shares = {(share.scope_kind, share.scope_value) for share in row.shares}
        if (SHARE_USER, ctx.username) in shares:
            return True
        return any((SHARE_ROLE, code) in shares for code in ctx.role_codes)

    def _row(self, session, row: SavedReport) -> SavedReportRow:
        definition = self.catalogue.get(row.definition_key) \
            if self.catalogue.has(row.definition_key) else None
        owner = session.get(User, row.owner_user_id)
        shares = session.execute(
            select(SavedReportShare).where(SavedReportShare.report_id == row.id)
        ).scalars().all()
        shared_with = tuple(
            (f"نقش {share.scope_value}" if share.scope_kind == SHARE_ROLE
             else f"کاربر {share.scope_value}") for share in shares)
        return SavedReportRow(
            id=row.id, name=row.name, definition_key=row.definition_key,
            definition_title_fa=(definition.title_fa if definition else "گزارش ناموجود"),
            description=row.description or "",
            owner_user_id=row.owner_user_id,
            owner_username=owner.username if owner else "",
            column_keys=tuple(row.columns or ()),
            sort_key=row.sort_key, sort_desc=bool(row.sort_desc), group_by=row.group_by,
            page_size=int(row.page_size or 100), is_shared=bool(row.is_shared),
            is_default=bool(row.is_default), is_mine=False,
            run_count=int(row.run_count or 0), last_run_at=row.last_run_at,
            shared_with_fa=shared_with)

    def describe(self, ctx: SecurityContext | None, row: SavedReportRow) -> SavedReportRow:
        """Return the row with ``is_mine`` filled in for this caller."""
        return replace(row, is_mine=(ctx is not None and row.owner_user_id == ctx.user_id))
