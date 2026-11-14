"""Controlled updates: check, verify, stage, health-check and roll back.

The application never updates itself silently.  The pieces live here so that the
behaviour is testable, and the installer/updater script only *applies* a staged
package:

* **check** - reads a manifest from a configurable source (a local/UNC path, a
  ``file://`` URL or an ``https://`` URL) and compares its versions with the
  running version.  With no configured source the result is explicitly
  ``not_configured`` - the program never pretends to have checked anything.
* **verify** - a package must match the size, the SHA-256 and (when signature
  checking is enabled) the Ed25519 signature in the manifest.  A file that fails
  any check is deleted, never staged.
* **stage** - before anything is written outside the data folder, a *verified*
  backup of the database is taken, because the new version may migrate the
  schema.  The staged package and a ``pending.json`` marker are recorded.
* **health check** - after the update the database must answer, must be on the
  expected schema revision and the recorded version must match.
* **rollback** - restores the pre-update backup with the existing, already
  tested restore path and clears the marker.

Applying program files is done by the Windows updater script (see
``packaging/``): a running application cannot safely replace its own binaries.
That limitation is documented instead of being faked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pars_erp import __version__
from pars_erp.config.paths import AppPaths
from pars_erp.core.errors import AppError, ValidationError
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.backup_service import BackupService
from pars_erp.services.settings_service import SettingsService

STATUS_NOT_CONFIGURED = "not_configured"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_AVAILABLE = "available"
STATUS_UNREACHABLE = "unreachable"
STATUS_INVALID_MANIFEST = "invalid_manifest"
STATUS_AHEAD = "ahead_of_channel"

STATUS_TITLES_FA = {
    STATUS_NOT_CONFIGURED: "منبع به‌روزرسانی تنظیم نشده است",
    STATUS_UP_TO_DATE: "برنامه به‌روز است",
    STATUS_AVAILABLE: "نسخهٔ تازه‌تر موجود است",
    STATUS_UNREACHABLE: "منبع به‌روزرسانی در دسترس نیست",
    STATUS_INVALID_MANIFEST: "فهرست نسخه‌ها معتبر نیست",
    STATUS_AHEAD: "نسخهٔ نصب‌شده از کانال جلوتر است",
}

HEALTH_TITLES_FA = {
    "database": "اتصال به پایگاه داده",
    "schema_revision": "ثبت نسخهٔ ساختار",
    "schema_matches_update": "هم‌خوانی ساختار با نسخهٔ به‌روزرسانی",
    "migrations_current": "اجرای همهٔ مهاجرت‌ها",
    "backup_folder_writable": "قابل نوشتن بودن پوشهٔ پشتیبان",
}

MANIFEST_FORMAT = "pars-erp-update/1"
CHANNELS = ("stable", "beta")
DEFAULT_TIMEOUT = 15.0

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.\-]+))?$")


class UpdateError(AppError):
    """Raised when an update cannot be performed at all."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message_fa = message


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    released_at: str
    notes_fa: tuple[str, ...]
    url: str
    sha256: str
    size_bytes: int
    channel: str = "stable"
    schema_revision: str | None = None
    min_version: str | None = None
    signature: str | None = None

    @property
    def is_prerelease(self) -> bool:
        return "-" in self.version

    def notes_text(self) -> str:
        return "\n".join(f"• {line}" for line in self.notes_fa) if self.notes_fa else ""


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    current_version: str
    release: ReleaseInfo | None = None
    message_fa: str = ""
    source: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def status_fa(self) -> str:
        return STATUS_TITLES_FA.get(self.status, self.status)

    @property
    def has_update(self) -> bool:
        return self.status == STATUS_AVAILABLE


@dataclass(frozen=True)
class PackageVerification:
    ok: bool
    path: Path
    sha256: str
    size_bytes: int
    signature_status: str          # verified | unsigned | unavailable | invalid
    message_fa: str

    @property
    def installable(self) -> bool:
        return self.ok and self.signature_status in ("verified", "unsigned")


@dataclass(frozen=True)
class StagedUpdate:
    release: ReleaseInfo
    package: Path
    backup: Path | None
    marker: Path
    signature_status: str
    message_fa: str


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    checks: dict[str, bool]
    message_fa: str


def parse_version(text: str) -> tuple[int, int, int, str]:
    """Return ``(major, minor, patch, prerelease)``; invalid versions raise."""
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        raise ValidationError(f"شمارهٔ نسخهٔ «{text}» معتبر نیست.", field="version")
    major, minor, patch, suffix = match.groups()
    return int(major), int(minor), int(patch), suffix or ""


def version_key(text: str) -> tuple[int, int, int, int]:
    """Sortable key; a prerelease sorts *before* its final release."""
    major, minor, patch, suffix = parse_version(text)
    return major, minor, patch, 0 if suffix else 1


class UpdateService:
    def __init__(self, db: Database, settings: SettingsService, audit: AuditService,
                 backups: BackupService, paths: AppPaths, *,
                 app_version: str | None = None) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        self.backups = backups
        self.paths = paths
        self.app_version = app_version or __version__

    # ------------------------------------------------------------- locations
    @property
    def updates_dir(self) -> Path:
        path = self.paths.home / "updates"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def marker_path(self) -> Path:
        return self.updates_dir / "pending.json"

    # ----------------------------------------------------------------- check
    def source(self) -> str:
        return (self.settings.snapshot().str("update_source") or "").strip()

    def channel(self) -> str:
        channel = (self.settings.snapshot().str("update_channel") or "stable").strip()
        return channel if channel in CHANNELS else "stable"

    @staticmethod
    def _authorize(ctx: SecurityContext | None, code: str, system: bool) -> None:
        """``system=True`` is only for the CLI/installer (the OS already decided)."""
        if system:
            return
        require_permission(ctx, code)

    def check(self, ctx: SecurityContext | None, *, system: bool = False) -> UpdateCheck:
        self._authorize(ctx, "settings.view", system)
        source = self.source()
        if not source:
            return UpdateCheck(
                STATUS_NOT_CONFIGURED, self.app_version,
                message_fa=("منبع به‌روزرسانی تنظیم نشده است؛ برای بررسی نسخه‌های تازه، "
                            "نشانی مانیفست را در تنظیمات «به‌روزرسانی برنامه» وارد کنید."),
                source="")
        try:
            payload = self._read_manifest(source)
        except UpdateError as exc:
            return UpdateCheck(STATUS_UNREACHABLE, self.app_version,
                               message_fa=str(exc), source=source)
        try:
            releases = self._parse_manifest(payload)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            return UpdateCheck(STATUS_INVALID_MANIFEST, self.app_version,
                               message_fa=f"فهرست نسخه‌ها قابل خواندن نیست: {exc}",
                               source=source)

        channel = self.channel()
        candidates = [r for r in releases
                      if (channel == "beta" or not r.is_prerelease)
                      and version_key(r.version) > version_key(self.app_version)]
        if not candidates:
            ahead = any(version_key(r.version) < version_key(self.app_version) for r in releases)
            status = STATUS_AHEAD if ahead else STATUS_UP_TO_DATE
            message = ("نسخهٔ نصب‌شده از همهٔ نسخه‌های این کانال تازه‌تر است."
                       if ahead else "برنامه با آخرین نسخهٔ این کانال به‌روز است.")
            return UpdateCheck(status, self.app_version, message_fa=message, source=source)

        latest = max(candidates, key=lambda r: version_key(r.version))
        if ctx is not None and "settings.edit" in getattr(ctx, "permissions", frozenset()):
            try:
                self.settings.update(ctx, {"update_last_check_at": datetime.now(
                    timezone.utc).isoformat(timespec="seconds")})
            except Exception:  # pragma: no cover - a read-only check must not fail
                pass
        return UpdateCheck(
            STATUS_AVAILABLE, self.app_version, release=latest,
            message_fa=(f"نسخهٔ {latest.version} منتشر شده است "
                        f"(نسخهٔ نصب‌شده: {self.app_version})."),
            source=source)

    # -------------------------------------------------------------- download
    def download(self, ctx: SecurityContext | None, release: ReleaseInfo, *,
                 target_dir: Path | None = None, system: bool = False) -> Path:
        self._authorize(ctx, "settings.edit", system)
        target_dir = target_dir or self.updates_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        name = f"ZarrinHormoz-{release.version}{Path(release.url).suffix or '.bin'}"
        target = target_dir / name
        temp = target.with_suffix(target.suffix + ".part")
        try:
            if self._is_remote(release.url):
                with urllib.request.urlopen(release.url, timeout=DEFAULT_TIMEOUT) as response:
                    with temp.open("wb") as handle:
                        shutil.copyfileobj(response, handle)
            else:
                local = self._local_path(release.url)
                if not local.is_file():
                    raise UpdateError(f"فایل بستهٔ به‌روزرسانی یافت نشد: {local}")
                shutil.copy2(local, temp)
            os.replace(temp, target)
        except UpdateError:
            temp.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, OSError, ValueError) as exc:
            temp.unlink(missing_ok=True)
            raise UpdateError(f"دریافت بستهٔ به‌روزرسانی ناموفق بود: {exc}") from exc
        return target

    # ---------------------------------------------------------------- verify
    def verify_package(self, package: Path | str, release: ReleaseInfo) -> PackageVerification:
        path = Path(package)
        if not path.is_file():
            raise UpdateError(f"فایل بستهٔ به‌روزرسانی وجود ندارد: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
        expected = (release.sha256 or "").strip().lower()
        signature_status = "unsigned"
        problems: list[str] = []
        if size != release.size_bytes:
            problems.append(f"اندازهٔ فایل ({size}) با مانیفست ({release.size_bytes}) برابر نیست")
        if not expected:
            problems.append("مانیفست برای این نسخه هش SHA-256 ندارد")
        elif digest != expected:
            problems.append("هش SHA-256 فایل با مانیفست برابر نیست")

        require_signature = self.settings.snapshot().bool("update_require_signature")
        public_key = (self.settings.snapshot().str("update_public_key") or "").strip()
        if release.signature:
            if not public_key:
                signature_status = "unavailable"
                problems.append("امضای بسته وجود دارد اما کلید عمومی در تنظیمات ثبت نشده است")
            else:
                ok, message = self._verify_ed25519(path, release.signature, public_key)
                signature_status = "verified" if ok else "invalid"
                if not ok:
                    problems.append(message)
        else:
            signature_status = "unsigned"
            if require_signature:
                problems.append("این نسخه امضای دیجیتال ندارد و تنظیمات، امضا را الزامی کرده است")

        ok = not problems
        if not ok:
            # a package that fails verification is never kept around
            try:
                path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - read-only volume
                pass
        message = "بستهٔ به‌روزرسانی معتبر است." if ok else "؛ ".join(problems)
        return PackageVerification(ok=ok, path=path, sha256=digest, size_bytes=size,
                                   signature_status=signature_status, message_fa=message)

    # ----------------------------------------------------------------- stage
    def stage(self, ctx: SecurityContext | None, release: ReleaseInfo, package: Path | str, *,
              note: str | None = None, system: bool = False) -> StagedUpdate:
        """Verify a package, back up the database and record a pending update."""
        self._authorize(ctx, "settings.edit", system)
        verification = self.verify_package(package, release)
        if not verification.ok:
            raise UpdateError(f"بستهٔ به‌روزرسانی رد شد: {verification.message_fa}")
        if release.min_version and version_key(self.app_version) < version_key(
                release.min_version):
            raise UpdateError(
                f"برای نصب نسخهٔ {release.version} حداقل نسخهٔ {release.min_version} لازم است.")

        backup_path = None
        if self.db.is_sqlite:
            info = self.backups.create_backup(
                ctx, note=note or f"پیش از به‌روزرسانی به {release.version}", kind="safety",
                require_permission_check=False)
            backup_path = info.path
        marker = self.marker_path
        payload = {
            "format": MANIFEST_FORMAT,
            "from_version": self.app_version,
            "to_version": release.version,
            "package": verification.path.name,
            "sha256": release.sha256,
            "schema_revision": release.schema_revision,
            "signature_status": verification.signature_status,
            "backup": backup_path.name if backup_path else None,
            "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "staged_by": ctx.username if ctx else None,
        }
        marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.audit.log_security(
            event_type="update.staged", ctx=ctx, severity="warning",
            message_fa=(f"بستهٔ به‌روزرسانی نسخهٔ {release.version} آمادهٔ نصب شد "
                        f"(پشتیبان: {backup_path.name if backup_path else 'ندارد'})."),
            details={k: payload[k] for k in ("from_version", "to_version", "backup",
                                             "signature_status")})
        return StagedUpdate(
            release=release, package=verification.path, backup=backup_path, marker=marker,
            signature_status=verification.signature_status,
            message_fa=("بستهٔ به‌روزرسانی آماده است؛ پس از بستن برنامه، نصب‌کننده آن را "
                        "اعمال می‌کند." if verification.installable else
                        "بسته آماده است اما امضای دیجیتال آن تأیید نشده؛ نصب خودکار انجام نمی‌شود."))

    def pending(self) -> dict[str, Any] | None:
        marker = self.marker_path
        if not marker.is_file():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - corrupted marker
            return None

    def clear_pending(self) -> None:
        self.marker_path.unlink(missing_ok=True)

    # ----------------------------------------------------------- health/rollback
    def health_check(self, ctx: SecurityContext | None, *,
                     expected_revision: str | None = None,
                     system: bool = False) -> HealthReport:
        self._authorize(ctx, "settings.view", system)
        checks: dict[str, bool] = {}
        checks["database"] = bool(self.db.ping())
        revision = self.db.schema_revision()
        checks["schema_revision"] = revision is not None
        if expected_revision:
            checks["schema_matches_update"] = revision == expected_revision
        head = self._head_revision()
        checks["migrations_current"] = bool(head) and revision == head
        checks["backup_folder_writable"] = self._writable(self.paths.backups_dir)
        ok = all(checks.values())
        message = ("همهٔ بررسی‌های سلامت پس از به‌روزرسانی موفق بود."
                   if ok else "بررسی سلامت ناموفق بود: " + "، ".join(
                       name for name, value in checks.items() if not value))
        return HealthReport(ok=ok, checks=checks, message_fa=message)

    def rollback(self, ctx: SecurityContext | None, *, confirm_phrase: str = "",
                 system: bool = False) -> Path:
        """Restore the database backup taken before the staged update."""
        self._authorize(ctx, "backup.restore", system)
        pending = self.pending()
        if not pending or not pending.get("backup"):
            raise UpdateError("هیچ به‌روزرسانی در انتظار نصب نیست که بتوان بازگردانی کرد.")
        backup_file = self.paths.backups_dir / str(pending["backup"])
        if not backup_file.is_file():
            raise UpdateError(f"فایل پشتیبان پیش از به‌روزرسانی یافت نشد: {backup_file.name}")
        self.backups.restore_backup(ctx, backup_file, confirm_phrase=confirm_phrase)
        self.clear_pending()
        self.audit.log_security(
            event_type="update.rolled_back", ctx=ctx, severity="critical",
            message_fa=f"به‌روزرسانی به نسخهٔ {pending.get('to_version')} بازگردانی شد.",
            details={"backup": backup_file.name, "to_version": pending.get("to_version")})
        return backup_file

    # --------------------------------------------------------------- internals
    @staticmethod
    def _head_revision() -> str | None:
        """The alembic head the packaged code expects (``None`` if unreadable)."""
        try:
            from alembic.script import ScriptDirectory

            from pars_erp.db.session import Database
        except Exception:  # pragma: no cover - alembic missing
            return None
        try:
            config = Database("sqlite://").alembic_config()
            return ScriptDirectory.from_config(config).get_current_head()
        except Exception:  # pragma: no cover - broken installation
            return None

    @staticmethod
    def _writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-test"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def _is_remote(url: str) -> bool:
        return url.lower().startswith(("http://", "https://"))

    @classmethod
    def _local_path(cls, url: str) -> Path:
        text = url
        if text.lower().startswith("file://"):
            text = text[7:]
        return Path(text).expanduser()

    def _read_manifest(self, source: str) -> str:
        if self._is_remote(source):
            try:
                with urllib.request.urlopen(source, timeout=DEFAULT_TIMEOUT) as response:
                    return response.read().decode("utf-8")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                raise UpdateError(
                    f"اتصال به منبع به‌روزرسانی ناموفق بود: {exc}") from exc
        path = self._local_path(source)
        if path.is_dir():
            path = path / "releases.json"
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise UpdateError(f"خواندن فهرست نسخه‌ها ناموفق بود: {exc}") from exc

    def _parse_manifest(self, payload: str) -> list[ReleaseInfo]:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValidationError("ساختار مانیفست به‌روزرسانی درست نیست.")
        if str(data.get("format", "")) != MANIFEST_FORMAT:
            raise ValidationError(
                f"قالب مانیفست پشتیبانی نمی‌شود (انتظار: {MANIFEST_FORMAT}).")
        releases: list[ReleaseInfo] = []
        for raw in data.get("releases", []):
            if not isinstance(raw, dict):
                raise ValidationError("هر نسخه در مانیفست باید یک شیء باشد.")
            version = str(raw.get("version", "")).strip()
            parse_version(version)
            url = str(raw.get("url", "")).strip()
            if not url:
                raise ValidationError(f"نسخهٔ {version} نشانی فایل بسته را ندارد.")
            releases.append(ReleaseInfo(
                version=version,
                released_at=str(raw.get("released_at", "")),
                notes_fa=tuple(str(line) for line in raw.get("notes_fa", ())),
                url=url,
                sha256=str(raw.get("sha256", "")).strip().lower(),
                size_bytes=int(raw.get("size_bytes", 0)),
                channel=str(raw.get("channel", "stable")),
                schema_revision=(str(raw["schema_revision"])
                                 if raw.get("schema_revision") else None),
                min_version=(str(raw["min_version"]) if raw.get("min_version") else None),
                signature=(str(raw["signature"]) if raw.get("signature") else None),
            ))
        if not releases:
            raise ValidationError("مانیفست هیچ نسخه‌ای ندارد.")
        return releases

    def _verify_ed25519(self, path: Path, signature_b64: str, public_key_b64: str
                        ) -> tuple[bool, str]:
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except Exception:  # pragma: no cover - optional dependency
            return False, ("بستهٔ «cryptography» نصب نیست، بنابراین امضا قابل بررسی نیست؛ "
                           "برای نصب آن «pip install cryptography» را اجرا کنید")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
            public_key.verify(base64.b64decode(signature_b64), path.read_bytes())
        except InvalidSignature:
            return False, "امضای دیجیتال بسته با کلید عمومی ثبت‌شده مطابقت ندارد"
        except Exception as exc:
            return False, f"بررسی امضای دیجیتال ممکن نشد: {exc}"
        return True, "امضای دیجیتال بسته تأیید شد"
