"""Logging configuration: rotating files under ``<home>/logs`` plus console output.

A redaction filter is installed on the root handlers so that a careless
``logger.info("... %s", payload)`` can never leak passwords or hashes into the
log files.
"""

from __future__ import annotations

import contextvars
import logging
import logging.handlers
import re
from pathlib import Path
from typing import Iterable

from pars_erp.config.settings import FileConfig

_SECRET_PATTERN = re.compile(
    r"(password|passwd|secret|token|hash|credential)\s*[:=]\s*[^\s,;'\"]+",
    re.IGNORECASE)
#: ``scheme://user:password@host`` as found in connection strings
_URL_PASSWORD_PATTERN = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")

#: the signed-in user, so every log line can be attributed without plumbing a
#: logger through every service (``contextvars`` keeps it per-thread safe)
_current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pars_erp_log_user", default="-")


def set_log_user(username: str | None) -> None:
    """Record who is signed in; called by the application controller."""
    _current_user.set((username or "-").strip() or "-")


def current_log_user() -> str:
    return _current_user.get()


class FileOnlyFilter(logging.Filter):
    """Drops records marked ``extra={"file_only": True}`` from the console.

    A traceback belongs in the log file, not in the user's terminal: the CLI
    prints one Persian sentence itself and marks the technical record this way.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - logging API
        return not getattr(record, "file_only", False)


class UserContextFilter(logging.Filter):
    """Adds the signed-in user to every record (``%(user)s`` in the format)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - logging API
        record.user = _current_user.get()
        return True


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - logging API
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        cleaned = _SECRET_PATTERN.sub(r"\1=***", message)
        cleaned = _URL_PASSWORD_PATTERN.sub(r"\1***@", cleaned)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def configure_logging(paths_logs_dir: Path, config: FileConfig, *,
                      level: str | None = None) -> Path:
    logs_dir = Path(paths_logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "pars_erp.log"
    level_name = (level or config.log_level or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name, logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover
            pass

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | pid=%(process)d | user=%(user)s | "
            "%(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    user_filter = UserContextFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=int(config.log_max_bytes or 2_000_000),
        backupCount=int(config.log_backup_count or 5), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(user_filter)
    file_handler.addFilter(SecretRedactionFilter())
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(user_filter)
    console.addFilter(SecretRedactionFilter())
    console.addFilter(FileOnlyFilter())
    root.addHandler(console)

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if config.echo_sql else logging.WARNING)
    # alembic logs every plugin/step at INFO; migrations are reported by US
    for name in ("alembic", "alembic.runtime.plugins", "alembic.runtime.migration"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return log_file


def close_logging() -> None:
    """Flush and remove every root handler (used when a CLI run finishes)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover
            pass
        try:
            handler.flush()
            handler.close()
        except Exception:  # pragma: no cover - a handler that refuses to close
            pass


def install_redaction(handlers: Iterable[logging.Handler]) -> None:
    for handler in handlers:
        handler.addFilter(SecretRedactionFilter())
