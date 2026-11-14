"""CSV export of list data (Excel-friendly, UTF-8 with BOM).

Excel and most Persian-language tooling expect a BOM to detect UTF-8, so the
writer emits it. Exports are written atomically (temp file + rename) so a
half-written file can never be mistaken for a complete one.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from pars_erp.config.paths import AppPaths
from pars_erp.core.jalali import format_datetime_as_jalali
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditFilter, AuditService, SecurityEventFilter
from pars_erp.services.user_service import STATUS_ALL, UserService

CSV_BOM = "\ufeff"


@dataclass(frozen=True)
class ExportResult:
    path: Path
    rows: int

    @property
    def message_fa(self) -> str:
        return f"{self.rows} سطر در فایل «{self.path.name}» ذخیره شد."


def rows_to_csv(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render CSV text (with BOM) - pure function, unit-tested."""
    buffer = io.StringIO()
    buffer.write(CSV_BOM)
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(list(headers))
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def write_csv_atomic(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".export_", suffix=".csv", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


#: An export never silently drops rows. The hard cap only protects the process
#: from an accidental multi-hundred-thousand-row file; reaching it is reported in
#: the returned row count, which the caller shows to the user.
MAX_EXPORT_ROWS = 50_000


def collect_all(fetch_page, *, page_size: int = 200, cap: int = MAX_EXPORT_ROWS) -> list:
    """Read every page of a paginated service listing.

    The services cap a page at ``MAX_PAGE_SIZE`` (200). Asking for 5 000 rows in
    one call therefore returns 200 and an export would quietly lose the rest;
    this helper asks page by page until ``total`` is reached.
    """
    items: list = []
    page_no = 1
    while True:
        page = fetch_page(page_no, page_size)
        batch = list(page.items)
        if not batch:
            break
        items.extend(batch)
        if len(items) >= int(getattr(page, "total", len(items))) or len(items) >= cap:
            break
        page_no += 1
    return items[:cap]


class ExportService:
    def __init__(self, users: UserService, audit: AuditService, paths: AppPaths) -> None:
        self.users = users
        self.audit = audit
        self.paths = paths

    def default_filename(self, prefix: str, extension: str = "csv") -> Path:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.paths.exports_dir / f"{prefix}_{stamp}.{extension}"

    # ------------------------------------------------------------------ users
    def export_users(self, ctx: SecurityContext | None, path: Path | None = None, *,
                     search: str = "", status: str = STATUS_ALL) -> ExportResult:
        require_permission(ctx, "users.view")
        users = collect_all(lambda page_no, size: self.users.list_users(
            ctx, search=search, status=status, page=page_no, page_size=size))
        rows = []
        for user in users:
            rows.append([
                user.id,
                user.username,
                user.full_name,
                user.roles_fa,
                user.status_fa,
                user.email or "",
                user.phone or "",
                format_datetime_as_jalali(user.last_login_at),
                format_datetime_as_jalali(user.created_at),
                "بله" if user.must_change_password else "خیر",
            ])
        headers = ["شناسه", "نام کاربری", "نام و نام خانوادگی", "نقش‌ها", "وضعیت",
                   "ایمیل", "تلفن", "آخرین ورود", "تاریخ ایجاد", "تغییر رمز در ورود بعدی"]
        target = path or self.default_filename("users")
        write_csv_atomic(target, rows_to_csv(headers, rows))
        return ExportResult(target, len(rows))

    # --------------------------------------------------------------- security
    def export_security_events(self, ctx: SecurityContext | None, path: Path | None = None, *,
                               filters: SecurityEventFilter | None = None) -> ExportResult:
        require_permission(ctx, "audit.export")
        events = collect_all(lambda page_no, size: self.audit.list_security_events(
            filters, page=page_no, page_size=size))
        rows = [[
            event.id,
            format_datetime_as_jalali(event.occurred_at),
            event.event_title_fa,
            event.severity_title_fa,
            event.username or "",
            event.message_fa,
            event.hostname or "",
        ] for event in events]
        headers = ["شناسه", "زمان", "رویداد", "سطح اهمیت", "کاربر", "شرح", "رایانه"]
        target = path or self.default_filename("security_events")
        write_csv_atomic(target, rows_to_csv(headers, rows))
        return ExportResult(target, len(rows))

    def export_audit_logs(self, ctx: SecurityContext | None, path: Path | None = None, *,
                          filters: AuditFilter | None = None) -> ExportResult:
        require_permission(ctx, "audit.export")
        entries = collect_all(lambda page_no, size: self.audit.list_audit_logs(
            filters, page=page_no, page_size=size))
        rows = [[
            entry.id,
            format_datetime_as_jalali(entry.occurred_at),
            entry.actor_username or "",
            entry.entity_type,
            entry.entity_id or "",
            entry.action,
            entry.summary_fa,
            entry.hostname or "",
        ] for entry in entries]
        headers = ["شناسه", "زمان", "کاربر", "نوع موجودیت", "شناسه موجودیت", "عملیات",
                   "شرح", "رایانه"]
        target = path or self.default_filename("audit_logs")
        write_csv_atomic(target, rows_to_csv(headers, rows))
        return ExportResult(target, len(rows))
