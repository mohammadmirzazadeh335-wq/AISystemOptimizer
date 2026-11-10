"""Backup, verification and restore of the database.

Backup format (a real, self-describing artefact)::

    pars_erp_backup_YYYYMMDD-HHMMSS_kind.zip
        database/<db file>      consistent copy (SQLite online-backup API)
        manifest.json           app/schema version, sizes, sha256, integrity result

Restore is deliberately conservative:

1. the archive is fully verified *before* anything is touched (zip structure,
   manifest checksum, SQLite ``integrity_check`` on an extracted copy, required
   tables present);
2. a safety backup of the current data is taken first;
3. the live database is replaced atomically, keeping the old file so an
   unexpected failure can be rolled back;
4. every step is recorded in the audit/security log.

PostgreSQL is not silently "supported": :meth:`BackupService.create_backup`
raises a clear, documented error for non-SQLite deployments.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, text

from pars_erp import __version__
from pars_erp.config.paths import AppPaths
from pars_erp.core.errors import BackupError, PermissionDeniedError, RestoreError, ValidationError
from pars_erp.db.models import BackupRecord
from pars_erp.db.session import Database
from pars_erp.db.types import utcnow
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService, EventType, SEVERITY_CRITICAL

MANIFEST_NAME = "manifest.json"
BACKUP_PREFIX = "pars_erp_backup_"
SUPPORTED_FORMAT = 1
REQUIRED_TABLES = ("users", "roles", "permissions", "app_settings", "audit_logs", "security_events")


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    filename: str
    size_bytes: int
    created_at: _dt.datetime
    kind: str
    note: str | None
    verified_at: _dt.datetime | None
    schema_revision: str | None
    app_version: str | None
    exists: bool = True

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 2)

    @property
    def kind_fa(self) -> str:
        return {"manual": "دستی", "auto": "خودکار", "safety": "پیش از بازیابی",
                "startup": "شروع برنامه"}.get(self.kind, self.kind)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    message_fa: str
    checks: dict[str, bool]
    manifest: dict | None = None


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message_fa: str
    safety_backup: Path | None = None
    restored_from: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_integrity(path: Path) -> tuple[bool, str]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            return (str(row[0]).lower() == "ok", str(row[0]))
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        return False, str(exc)


def _sqlite_tables(path: Path) -> set[str]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(r[0]) for r in rows}
    finally:
        connection.close()


class BackupService:
    def __init__(self, db: Database, paths: AppPaths, audit: AuditService, *,
                 app_version: str = __version__) -> None:
        self.db = db
        self.paths = paths
        self.audit = audit
        self.app_version = app_version

    # ------------------------------------------------------------- utilities
    def backup_dir(self) -> Path:
        self.paths.backups_dir.mkdir(parents=True, exist_ok=True)
        return self.paths.backups_dir

    def _timestamp(self, now: _dt.datetime | None = None) -> str:
        value = (now or utcnow()).astimezone(_dt.timezone.utc)
        return value.strftime("%Y%m%d-%H%M%S")

    def _record(self, session, *, info: BackupInfo, ctx: SecurityContext | None,
                status: str = "created") -> BackupRecord:
        record = BackupRecord(
            filename=info.filename,
            file_path=str(info.path),
            size_bytes=info.size_bytes,
            checksum_sha256=_sha256(info.path) if info.path.exists() else None,
            kind=info.kind,
            status=status,
            note=info.note,
            created_at=info.created_at,
            created_by_id=ctx.user_id if ctx else None,
            created_by_username=ctx.username if ctx else "system",
            schema_revision=info.schema_revision,
            app_version=self.app_version,
        )
        session.add(record)
        return record

    def create_backup(self, ctx: SecurityContext | None, *, note: str | None = None,
                      kind: str = "manual", require_permission_check: bool = True) -> BackupInfo:
        """Create a verified backup archive and return its description."""
        if require_permission_check:
            require_permission(ctx, "backup.create")
        if kind not in ("manual", "auto", "safety", "startup"):
            raise ValidationError(f"نوع پشتیبان «{kind}» شناخته‌شده نیست.", field="kind")
        if not self.db.is_sqlite:
            raise BackupError(
                "پشتیبان‌گیری داخلی فقط برای پایگاه داده SQLite پیاده‌سازی شده است. "
                "برای PostgreSQL از pg_dump استفاده کنید (بخش پشتیبان‌گیری در مستندات).")

        created_at = utcnow()
        filename = f"{BACKUP_PREFIX}{self._timestamp(created_at)}_{kind}.zip"
        target = self.backup_dir() / filename
        counter = 1
        while target.exists():
            target = self.backup_dir() / filename.replace(".zip", f"-{counter}.zip")
            counter += 1

        db_file = self.db.file_path()
        if db_file is None:
            raise BackupError("مسیر فایل پایگاه داده مشخص نیست.")

        workdir = Path(tempfile.mkdtemp(prefix="pars_erp_backup_"))
        try:
            snapshot = workdir / db_file.name
            self.db.copy_database_to(snapshot)
            integrity_ok, integrity_message = _sqlite_integrity(snapshot)
            if not integrity_ok:
                raise BackupError(f"یکپارچگی نسخه پشتیبان تأیید نشد: {integrity_message}")
            revision = self.db.schema_revision()
            manifest = {
                "format": SUPPORTED_FORMAT,
                "app_version": self.app_version,
                "schema_revision": revision,
                "created_at": created_at.isoformat(),
                "kind": kind,
                "note": note or "",
                "database_file": db_file.name,
                "database_bytes": snapshot.stat().st_size,
                "database_sha256": _sha256(snapshot),
                "integrity_check": integrity_message,
                "created_by": ctx.username if ctx else "system",
                "installation_tables": sorted(_sqlite_tables(snapshot)),
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, arcname=f"database/{db_file.name}")
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            info = BackupInfo(
                path=target, filename=target.name, size_bytes=target.stat().st_size,
                created_at=created_at, kind=kind, note=note or None, verified_at=None,
                schema_revision=revision, app_version=self.app_version)
            with self.db.session_scope() as session:
                self._record(session, info=info, ctx=ctx)
                self.audit.log_security(
                    event_type=EventType.BACKUP_CREATED,
                    message_fa=f"پشتیبان «{target.name}» ایجاد شد ({info.size_mb} مگابایت).",
                    ctx=ctx, details={"file": target.name, "kind": kind}, session=session)
            return info
        except (BackupError, ValidationError):
            raise
        except Exception as exc:  # pragma: no cover - filesystem failures
            if target.exists():
                target.unlink(missing_ok=True)
            self.audit.log_security(
                event_type=EventType.BACKUP_FAILED,
                message_fa=f"ایجاد پشتیبان ناموفق بود: {exc}",
                severity=SEVERITY_CRITICAL, ctx=ctx)
            raise BackupError(f"ایجاد پشتیبان ناموفق بود: {exc}") from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ---------------------------------------------------------------- verify
    def verify_backup(self, path: Path | str, *, ctx: SecurityContext | None = None,
                      log: bool = True) -> VerifyResult:
        target = Path(path)
        checks: dict[str, bool] = {}
        if not target.exists():
            return VerifyResult(False, "فایل پشتیبان یافت نشد.", {"exists": False})
        checks["exists"] = True
        manifest: dict | None = None
        details = ""
        workdir = Path(tempfile.mkdtemp(prefix="pars_erp_verify_"))
        try:
            try:
                with zipfile.ZipFile(target) as archive:
                    checks["zip_valid"] = True
                    names = archive.namelist()
                    checks["has_manifest"] = MANIFEST_NAME in names
                    database_name = next((n for n in names if n.startswith("database/")), None)
                    checks["has_database"] = database_name is not None
                    if not (checks["has_manifest"] and checks["has_database"]):
                        return VerifyResult(False, "ساختار فایل پشتیبان معتبر نیست.", checks)
                    manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                    checks["format_supported"] = int(manifest.get("format", 0)) == SUPPORTED_FORMAT
                    extracted = workdir / Path(str(database_name)).name
                    with archive.open(database_name) as source, extracted.open("wb") as out:
                        shutil.copyfileobj(source, out)
            except zipfile.BadZipFile:
                checks["zip_valid"] = False
                return VerifyResult(False, "فایل پشتیبان یک آرشیو معتبر نیست.", checks)

            expected_hash = str((manifest or {}).get("database_sha256") or "")
            actual_hash = _sha256(extracted)
            checks["checksum"] = bool(expected_hash) and expected_hash == actual_hash
            ok, message = _sqlite_integrity(extracted)
            checks["sqlite_integrity"] = ok
            tables = _sqlite_tables(extracted) if ok else set()
            checks["required_tables"] = all(t in tables for t in REQUIRED_TABLES)
            details = message
            all_ok = all(checks.values())
            if all_ok:
                with self.db.session_scope() as session:
                    record = session.execute(
                        select(BackupRecord).where(BackupRecord.filename == target.name)
                    ).scalar_one_or_none()
                    if record is not None:
                        record.verified_at = utcnow()
                        record.status = "verified"
                if log:
                    self.audit.log_security(
                        event_type=EventType.BACKUP_VERIFIED,
                        message_fa=f"صحت پشتیبان «{target.name}» تأیید شد.",
                        ctx=ctx, details={"file": target.name})
            return VerifyResult(all_ok, "صحت پشتیبان تأیید شد." if all_ok
                                else f"بررسی پشتیبان ناموفق بود ({details or 'سازگاری فایل'}).",
                                checks, manifest)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # --------------------------------------------------------------- restore
    def restore_backup(self, ctx: SecurityContext | None, path: Path | str, *,
                       confirm_phrase: str = "") -> RestoreResult:
        require_permission(ctx, "backup.restore")
        if (confirm_phrase or "").strip() != "بازیابی":
            raise ValidationError("برای انجام بازیابی، عبارت «بازیابی» را دقیقاً وارد کنید.",
                                  field="confirm_phrase")
        source = Path(path)
        verification = self.verify_backup(source, ctx=ctx, log=False)
        if not verification.ok:
            raise RestoreError(f"فایل پشتیبان معتبر نیست: {verification.message_fa}")

        # 1) safety backup of the current state
        safety = self.create_backup(ctx, note="پشتیبان خودکار پیش از بازیابی",
                                    kind="safety", require_permission_check=False)

        db_file = self.db.file_path()
        if db_file is None:
            raise RestoreError("مسیر فایل پایگاه داده مشخص نیست.")
        workdir = Path(tempfile.mkdtemp(prefix="pars_erp_restore_"))
        staged = workdir / db_file.name
        backup_of_current = db_file.with_suffix(db_file.suffix + ".pre-restore")
        try:
            with zipfile.ZipFile(source) as archive:
                database_name = next(n for n in archive.namelist() if n.startswith("database/"))
                with archive.open(database_name) as src, staged.open("wb") as out:
                    shutil.copyfileobj(src, out)
            ok, message = _sqlite_integrity(staged)
            if not ok:
                raise RestoreError(f"فایل پشتیبان سالم نیست: {message}")
            missing = [t for t in REQUIRED_TABLES if t not in _sqlite_tables(staged)]
            if missing:
                raise RestoreError(f"جداول ضروری در پشتیبان موجود نیست: {'، '.join(missing)}")

            self.db.dispose()
            for suffix in ("-wal", "-shm"):
                Path(str(db_file) + suffix).unlink(missing_ok=True)
            if db_file.exists():
                shutil.copy2(db_file, backup_of_current)
            shutil.copy2(staged, db_file)
            restored_revision = self.db.schema_revision()
            if restored_revision is None:
                raise RestoreError("فایل بازیابی‌شده نسخه ساختار پایگاه داده را مشخص نمی‌کند.")
            # bring an older backup up to the current schema
            self.db.upgrade_to_head()
            self.audit.log_security(
                event_type=EventType.BACKUP_RESTORED,
                message_fa=(f"پایگاه داده از پشتیبان «{source.name}» توسط "
                            f"«{ctx.username if ctx else 'system'}» بازیابی شد."),
                severity=SEVERITY_CRITICAL, ctx=ctx,
                details={"file": source.name, "safety_backup": safety.filename,
                         "restored_revision": restored_revision})
            with self.db.session_scope() as session:
                self.audit.log_audit(
                    ctx=ctx, entity_type="database", entity_id="main", action="restore",
                    summary_fa=f"بازیابی پایگاه داده از «{source.name}»",
                    after={"safety_backup": safety.filename, "source": source.name},
                    session=session)
            return RestoreResult(True, "پایگاه داده با موفقیت بازیابی شد.",
                                 safety_backup=safety.path, restored_from=source)
        except (BackupError, RestoreError, ValidationError):
            self._rollback_restore(db_file, backup_of_current)
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self._rollback_restore(db_file, backup_of_current)
            raise RestoreError(f"بازیابی ناموفق بود و وضعیت قبلی بازگردانده شد: {exc}") from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            self.db.dispose()

    @staticmethod
    def _rollback_restore(db_file: Path, previous: Path) -> None:
        if previous.exists():
            try:
                shutil.copy2(previous, db_file)
            except OSError:  # pragma: no cover - last-resort path
                pass

    # ----------------------------------------------------------------- list
    def list_backups(self, ctx: SecurityContext | None) -> list[BackupInfo]:
        require_permission(ctx, "backup.view")
        infos: dict[str, BackupInfo] = {}
        with self.db.session_scope() as session:
            records = list(session.execute(
                select(BackupRecord).order_by(BackupRecord.created_at.desc())).scalars())
            for record in records:
                path = Path(record.file_path)
                if not path.exists():
                    continue
                infos[record.filename] = BackupInfo(
                    path=path, filename=record.filename, size_bytes=path.stat().st_size,
                    created_at=record.created_at, kind=record.kind, note=record.note,
                    verified_at=record.verified_at, schema_revision=record.schema_revision,
                    app_version=record.app_version, exists=True)
        # Also surface archives dropped into the folder manually.
        for path in sorted(self.backup_dir().glob(f"{BACKUP_PREFIX}*.zip"), reverse=True):
            if path.name in infos:
                continue
            created = _dt.datetime.fromtimestamp(path.stat().st_mtime, tz=_dt.timezone.utc)
            infos[path.name] = BackupInfo(
                path=path, filename=path.name, size_bytes=path.stat().st_size,
                created_at=created, kind="unknown", note=None, verified_at=None,
                schema_revision=None, app_version=None)
        return sorted(infos.values(), key=lambda i: i.created_at, reverse=True)

    def delete_backup(self, ctx: SecurityContext | None, path: Path | str) -> None:
        require_permission(ctx, "backup.delete")
        target = Path(path)
        if not target.exists():
            raise BackupError("فایل پشتیبان یافت نشد.")
        if target.resolve().parent != self.backup_dir().resolve():
            raise BackupError("حذف فایل‌های خارج از پوشه پشتیبان مجاز نیست.")
        target.unlink()
        with self.db.session_scope() as session:
            record = session.execute(
                select(BackupRecord).where(BackupRecord.filename == target.name)
            ).scalar_one_or_none()
            if record is not None:
                record.status = "deleted"
            self.audit.log_security(
                event_type=EventType.BACKUP_DELETED,
                message_fa=f"فایل پشتیبان «{target.name}» حذف شد.",
                ctx=ctx, details={"file": target.name}, session=session)

    # ------------------------------------------------------------- retention
    def prune(self, ctx: SecurityContext | None, *, keep: int | None = None,
              kinds: tuple[str, ...] = ("manual", "auto", "startup", "safety")) -> list[str]:
        """Delete the oldest backups beyond the retention count."""
        if keep is None:
            from pars_erp.services.settings_service import SettingsService  # local import
            keep = 20
        removed: list[str] = []
        archives = sorted(self.backup_dir().glob(f"{BACKUP_PREFIX}*.zip"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        for path in archives[max(0, keep):]:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:  # pragma: no cover
                continue
        if removed:
            with self.db.session_scope() as session:
                for name in removed:
                    record = session.execute(
                        select(BackupRecord).where(BackupRecord.filename == name)
                    ).scalar_one_or_none()
                    if record is not None:
                        record.status = "pruned"
                self.audit.log_security(
                    event_type=EventType.BACKUP_DELETED,
                    message_fa=f"{len(removed)} پشتیبان قدیمی بر اساس سیاست نگهداری حذف شد.",
                    ctx=ctx, details={"files": removed})
        return removed

    def last_backup(self) -> BackupInfo | None:
        with self.db.session_scope() as session:
            record = session.execute(
                select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1)
            ).scalar_one_or_none()
        if record is None:
            return None
        path = Path(record.file_path)
        if not path.exists():
            return None
        return BackupInfo(path=path, filename=record.filename,
                          size_bytes=path.stat().st_size, created_at=record.created_at,
                          kind=record.kind, note=record.note, verified_at=record.verified_at,
                          schema_revision=record.schema_revision, app_version=record.app_version)

    def last_backup_at(self) -> _dt.datetime | None:
        with self.db.session_scope() as session:
            value = session.execute(select(func.max(BackupRecord.created_at))).scalar()
        return value

    def total_backup_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.backup_dir().glob(f"{BACKUP_PREFIX}*.zip"))

    # ---------------------------------------------------------------- startup
    def startup_backup_if_due(self, *, interval_hours: int = 24) -> BackupInfo | None:
        """Automatic backup used at application start (no user context)."""
        last = self.last_backup_at()
        now = utcnow()
        if last is not None and (now - last) < _dt.timedelta(hours=max(1, interval_hours)):
            return None
        if not self.db.is_sqlite:
            return None
        info = self.create_backup(None, note="پشتیبان خودکار شروع برنامه", kind="startup",
                                  require_permission_check=False)
        return info
