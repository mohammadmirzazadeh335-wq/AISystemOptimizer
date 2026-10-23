"""System doctor: real, measured checks of the workspace and the app itself.

Every check reads a real file, runs a real query or calls the app's own safety
rules — nothing is simulated and nothing is "assumed healthy". Failures carry a
stable ``key`` so the page can translate the title and the advice, while the
``detail`` stays a measured fact (a version, a byte count, a path name).
"""

from __future__ import annotations

import json
import logging
import os
import secrets as random_secrets
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import AppPaths
from ..core.platform import filename_problem, path_problem
from ..core.redaction import contains_secret, find_secrets
from ..core.timeutil import format_bytes
from ..data.db import LATEST_SCHEMA, Database
from ..i18n.translator import LOCALES_DIR
from ..security.secrets import SecretStore
from .openrouter import api_key_problem
from .settings import SettingsService

logger = logging.getLogger(__name__)

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"

GROUPS = ("storage", "security", "runtime", "interface")

#: Sizes in bytes that turn a green check into an amber one.
LOG_WARN_BYTES = 25 * 1024 * 1024
FREE_WARN_BYTES = 500 * 1024 * 1024
FREE_FAIL_BYTES = 50 * 1024 * 1024
ATTACHMENT_WARN_BYTES = 500 * 1024 * 1024
STALE_BACKUP_DAYS = 7


@dataclass(frozen=True)
class HealthCheck:
    key: str
    group: str
    status: str
    detail: str = ""
    fix_key: str = ""
    ms: int = 0
    advice: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "group": self.group,
            "status": self.status,
            "detail": self.detail,
            "fix_key": self.fix_key,
            "ms": self.ms,
            "advice": self.advice,
        }


@dataclass(frozen=True)
class HealthReport:
    checks: tuple[HealthCheck, ...] = ()
    generated_at: str = ""
    duration_ms: int = 0

    # ------------------------------------------------------------------ counts
    @property
    def counts(self) -> dict[str, int]:
        result = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
        for check in self.checks:
            result[check.status] = result.get(check.status, 0) + 1
        return result

    @property
    def score(self) -> int:
        counts = self.counts
        return max(0, 100 - 22 * counts[FAIL] - 7 * counts[WARN])

    @property
    def verdict(self) -> str:
        counts = self.counts
        if counts[FAIL]:
            return "needs_care"
        if counts[WARN] > 1:
            return "attention"
        return "healthy"

    @property
    def problems(self) -> tuple[HealthCheck, ...]:
        rank = {FAIL: 0, WARN: 1}
        return tuple(
            sorted(
                (check for check in self.checks if check.status in rank),
                key=lambda check: (rank[check.status], check.key),
            )
        )

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
            "score": self.score,
            "verdict": self.verdict,
            "counts": self.counts,
            "checks": [check.to_dict() for check in self.checks],
        }


def _timed(key: str, group: str, fn) -> HealthCheck:  # noqa: ANN001 - internal helper
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - a broken check must not hide the rest
        logger.exception("doctor_check_crashed key=%s", key)
        result = HealthCheck(key, group, FAIL, f"{type(exc).__name__}", "doctor.fix_restart")
    elapsed = int((time.perf_counter() - started) * 1000)
    return HealthCheck(
        key=result.key,
        group=result.group,
        status=result.status,
        detail=result.detail,
        fix_key=result.fix_key,
        advice=result.advice,
        ms=elapsed,
    )


def _tree_size(root: Path) -> tuple[int, int]:
    total = 0
    files = 0
    if not root.exists():
        return 0, 0
    for folder, _dirs, names in os.walk(root):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                files += 1
            except OSError:
                continue
    return total, files


def run_checks(
    *,
    paths: AppPaths,
    settings: SettingsService,
    db: Database,
    secrets: SecretStore,
    toolchain_registry=None,  # noqa: ANN001 - avoids importing subprocess at module load
) -> HealthReport:
    """Run every check and return a report. Never raises."""
    started = time.perf_counter()
    checks: list[HealthCheck] = []

    # ------------------------------------------------------------- storage
    def database_check() -> HealthCheck:
        verdict = db.integrity_check()
        size = db.file_size()
        if verdict.lower() != "ok":
            return HealthCheck("database", "storage", FAIL, f"integrity_check: {verdict}", "doctor.fix_database")
        return HealthCheck("database", "storage", OK, f"integrity_check ok · {format_bytes(size)}")

    checks.append(_timed("database", "storage", database_check))

    def schema_check() -> HealthCheck:
        version = db.schema_version()
        if version == LATEST_SCHEMA:
            return HealthCheck("schema", "storage", OK, f"v{version}")
        if version > LATEST_SCHEMA:
            return HealthCheck("schema", "storage", FAIL, f"v{version} > v{LATEST_SCHEMA}", "doctor.fix_schema")
        return HealthCheck("schema", "storage", WARN, f"v{version} < v{LATEST_SCHEMA}", "doctor.fix_schema")

    checks.append(_timed("schema", "storage", schema_check))

    def workspace_check() -> HealthCheck:
        probe = paths.home / f".doctor-{random_secrets.token_hex(6)}.tmp"
        try:
            probe.write_text("myai-doctor", encoding="utf-8")
            written = probe.read_text(encoding="utf-8") == "myai-doctor"
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
        if not written:
            return HealthCheck("workspace", "storage", FAIL, "write/read mismatch", "doctor.fix_workspace")
        return HealthCheck("workspace", "storage", OK, "write · read · delete")

    checks.append(_timed("workspace", "storage", workspace_check))

    def disk_check() -> HealthCheck:
        usage = shutil.disk_usage(paths.home)
        free = int(usage.free)
        detail = f"{format_bytes(free)} free of {format_bytes(usage.total)}"
        if free < FREE_FAIL_BYTES:
            return HealthCheck("disk", "storage", FAIL, detail, "doctor.fix_disk")
        if free < FREE_WARN_BYTES:
            return HealthCheck("disk", "storage", WARN, detail, "doctor.fix_disk")
        return HealthCheck("disk", "storage", OK, detail)

    checks.append(_timed("disk", "storage", disk_check))

    def backup_check() -> HealthCheck:
        last = str(settings.get("data.last_backup", "") or "")
        folder = paths.backups_dir
        size, files = _tree_size(folder)
        if not last or not files:
            return HealthCheck(
                "backups", "storage", WARN, f"none · {format_bytes(size)}", "doctor.fix_backup"
            )
        try:
            stamp = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - stamp).days
        except ValueError:
            return HealthCheck("backups", "storage", WARN, last[:10], "doctor.fix_backup")
        detail = f"{days}d ago · {files} file(s) · {format_bytes(size)}"
        if days > STALE_BACKUP_DAYS:
            return HealthCheck("backups", "storage", WARN, detail, "doctor.fix_backup")
        return HealthCheck("backups", "storage", OK, detail)

    checks.append(_timed("backups", "storage", backup_check))

    def logs_check() -> HealthCheck:
        size, files = _tree_size(paths.logs_dir)
        detail = f"{format_bytes(size)} · {files} file(s)"
        if size > LOG_WARN_BYTES:
            return HealthCheck("logs", "storage", WARN, detail, "doctor.fix_logs")
        return HealthCheck("logs", "storage", OK, detail)

    checks.append(_timed("logs", "storage", logs_check))

    def attachments_check() -> HealthCheck:
        root = paths.home / "attachments"
        size, files = _tree_size(root)
        detail = f"{format_bytes(size)} · {files} file(s)"
        if size > ATTACHMENT_WARN_BYTES:
            return HealthCheck("attachments", "storage", WARN, detail, "doctor.fix_attachments")
        return HealthCheck("attachments", "storage", OK, detail)

    checks.append(_timed("attachments", "storage", attachments_check))

    # ------------------------------------------------------------ security
    def secrets_check() -> HealthCheck:
        api_key: str | None = None
        raw = b""
        if paths.secrets_file.exists():
            try:
                raw = paths.secrets_file.read_bytes()
            except OSError:
                return HealthCheck("secrets", "security", FAIL, "unreadable", "doctor.fix_secrets")
        try:
            api_key = secrets.get_api_key()
        except Exception:  # noqa: BLE001 - a damaged store is a finding, not a crash
            api_key = None
        # The envelope must never contain a credential in clear text — checked
        # by shape too, so this also works when decryption itself fails.
        raw_text = raw.decode("utf-8", "ignore")
        plaintext = find_secrets(raw_text)
        if (api_key and contains_secret(raw_text, [api_key])) or plaintext:
            return HealthCheck("secrets", "security", FAIL, "plaintext key on disk", "doctor.fix_secrets")
        if not api_key:
            return HealthCheck("secrets", "security", WARN, "no key stored", "doctor.fix_key")
        return HealthCheck(
            "secrets", "security", OK, f"1 key · encrypted · {format_bytes(len(raw))}"
        )

    checks.append(_timed("secrets", "security", secrets_check))

    def api_key_check() -> HealthCheck:
        api_key = secrets.get_api_key()
        if not api_key:
            return HealthCheck("api_key", "security", SKIP, "no key", "doctor.fix_key")
        problem = api_key_problem(api_key)
        if problem:
            return HealthCheck("api_key", "security", FAIL, problem, "doctor.fix_key")
        return HealthCheck("api_key", "security", OK, f"{len(api_key)} chars · sk-or- prefix")

    checks.append(_timed("api_key", "security", api_key_check))

    # ------------------------------------------------------------- runtime
    def platform_check() -> HealthCheck:
        cases = {
            "CON": "reserved",
            "a:b.txt": "invalid_chars",
            "name.": "trailing",
            "name ": "trailing",
        }
        for name, expected in cases.items():
            if filename_problem(name) != expected:
                return HealthCheck(
                    "platform", "runtime", FAIL, f"{name!r} was not rejected", "doctor.fix_platform"
                )
        if filename_problem("ok.py") is not None:
            return HealthCheck("platform", "runtime", FAIL, "valid name was rejected", "doctor.fix_platform")
        if path_problem(["x" * 200, "y" * 200]) is None:
            return HealthCheck("platform", "runtime", FAIL, "long path was accepted", "doctor.fix_platform")
        return HealthCheck("platform", "runtime", OK, "4 rejects · 2 accepts")

    checks.append(_timed("platform", "runtime", platform_check))

    def toolchain_check() -> HealthCheck:
        if toolchain_registry is None:
            return HealthCheck("toolchains", "runtime", SKIP, "registry unavailable")
        try:
            items = toolchain_registry.detect()
        except Exception:  # noqa: BLE001
            return HealthCheck("toolchains", "runtime", FAIL, "detection failed", "doctor.fix_toolchain")
        available = [item.id for item in items if item.available]
        missing = [item.id for item in items if not item.available]
        detail = f"{', '.join(available) or 'none'}"
        if missing:
            detail += f" · missing: {', '.join(missing)}"
        if "python" not in available:
            return HealthCheck("toolchains", "runtime", WARN, detail, "doctor.fix_toolchain")
        return HealthCheck("toolchains", "runtime", OK, detail)

    checks.append(_timed("toolchains", "runtime", toolchain_check))

    def memory_check() -> HealthCheck:
        stats = db.counts()
        total = sum(stats.values())
        detail = " · ".join(
            f"{name} {value}" for name, value in sorted(stats.items()) if value
        ) or "empty database"
        return HealthCheck("tables", "runtime", OK, f"{total} rows · {detail}")

    checks.append(_timed("tables", "runtime", memory_check))

    # ----------------------------------------------------------- interface
    def locale_check() -> HealthCheck:
        loaded: dict[str, dict] = {}
        for language in ("en", "fa"):
            path = LOCALES_DIR / f"{language}.json"
            try:
                loaded[language] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return HealthCheck("locales", "interface", FAIL, f"{language}.json unreadable", "doctor.fix_locales")
        en, fa = set(loaded["en"]), set(loaded["fa"])
        if en != fa:
            return HealthCheck(
                "locales", "interface", FAIL, f"{len(en - fa)} only-en · {len(fa - en)} only-fa", "doctor.fix_locales"
            )
        return HealthCheck("locales", "interface", OK, f"{len(en)} keys · en = fa")

    checks.append(_timed("locales", "interface", locale_check))

    def settings_check() -> HealthCheck:
        language = settings.get("ui.language")
        theme = settings.get("ui.theme")
        accent = settings.get("ui.accent")
        if language not in {"fa", "en"} or theme not in {"midnight", "dawn", "aurora", "system"}:
            return HealthCheck("settings", "interface", FAIL, f"{language} / {theme}", "doctor.fix_settings")
        return HealthCheck("settings", "interface", OK, f"{language} · {theme} · {accent}")

    checks.append(_timed("settings", "interface", settings_check))

    report = HealthReport(
        checks=tuple(checks),
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    logger.info(
        "doctor_report score=%s verdict=%s fail=%s warn=%s",
        report.score,
        report.verdict,
        report.counts[FAIL],
        report.counts[WARN],
    )
    return report


def report_text(report: HealthReport, *, title: str = "MyAI Studio — system report") -> str:
    """Plain-text report, safe to paste (no key material is ever included)."""
    lines = [
        title,
        f"generated: {report.generated_at}",
        f"score: {report.score}/100 · {report.verdict}",
        f"checks: {len(report.checks)} · {report.duration_ms} ms",
        "",
    ]
    for check in report.checks:
        mark = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}[check.status]
        lines.append(f"[{mark}] {check.key:12s} {check.detail}")
    return "\n".join(lines)


__all__ = [
    "FAIL",
    "GROUPS",
    "HealthCheck",
    "HealthReport",
    "OK",
    "SKIP",
    "WARN",
    "report_text",
    "run_checks",
]
