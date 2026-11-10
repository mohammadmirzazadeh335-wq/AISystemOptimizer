"""Logging configuration: rotating files under ``<home>/logs`` plus console output.

A redaction filter is installed on the root handlers so that a careless
``logger.info("... %s", payload)`` can never leak passwords or hashes into the
log files.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path
from typing import Iterable

from pars_erp.config.settings import FileConfig

_SECRET_PATTERN = re.compile(
    r"(password|passwd|secret|token|hash|credential)\s*[:=]\s*[^\s,;'\"]+",
    re.IGNORECASE)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - logging API
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        cleaned = _SECRET_PATTERN.sub(r"\1=***", message)
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

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=int(config.log_max_bytes or 2_000_000),
        backupCount=int(config.log_backup_count or 5), encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactionFilter())
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(SecretRedactionFilter())
    root.addHandler(console)

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if config.echo_sql else logging.WARNING)
    return log_file


def install_redaction(handlers: Iterable[logging.Handler]) -> None:
    for handler in handlers:
        handler.addFilter(SecretRedactionFilter())
