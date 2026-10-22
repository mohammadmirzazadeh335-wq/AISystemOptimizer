"""Structured logging with rotating JSON files and an in-memory ring buffer."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .redaction import redact

_CONFIGURED = False
_RING: deque[dict[str, Any]] = deque(maxlen=1000)
_RING_LOCK = threading.Lock()


class RedactFilter(logging.Filter):
    """Last line of defence: no handler ever sees a raw credential.

    A filter (rather than a formatter concern) means the JSON file, the console
    and the inspector ring buffer all get the same redacted record, including
    messages produced by third-party libraries we do not control.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                record.args = tuple(
                    redact(arg) if isinstance(arg, str) else arg for arg in record.args
                )
            fields = getattr(record, "fields", None)
            if isinstance(fields, dict):
                record.fields = {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in fields.items()
                }
        except Exception:  # noqa: BLE001 - redaction must never drop a log line
            pass
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class SafeStreamHandler(logging.StreamHandler):
    """A console handler that cannot crash on a legacy Windows code page.

    ``StreamHandler`` writes to ``sys.stderr``, which on a Windows console is
    encoded with the active code page (often cp1252/cp437). A Persian message
    would raise ``UnicodeEncodeError`` from inside logging; this handler
    re-encodes the line with ``errors="replace"`` instead.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = self.stream
            try:
                stream.write(message + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "utf-8"
                safe = message.encode(encoding, "replace").decode(encoding, "replace")
                stream.write(safe + self.terminator)
            self.flush()
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)


class RingBufferHandler(logging.Handler):
    """Keep the most recent records available to the UI inspector."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            fields = getattr(record, "fields", None)
            if isinstance(fields, dict):
                item.update(fields)
            with _RING_LOCK:
                _RING.append(item)
        except Exception:  # pragma: no cover - logging must never raise
            pass


def setup_logging(log_dir=None, level: int = logging.INFO, console: bool = True) -> logging.Logger:
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        return root
    root.setLevel(level)
    formatter = JsonFormatter()

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "myai_studio.jsonl", maxBytes=2_000_000, backupCount=4, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(RedactFilter())
        root.addHandler(file_handler)

    if console and sys.stderr is not None:
        stream = SafeStreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        stream.addFilter(RedactFilter())
        root.addHandler(stream)

    ring = RingBufferHandler()
    ring.addFilter(RedactFilter())
    root.addHandler(ring)
    _CONFIGURED = True
    return root


def get_recent_logs(limit: int = 200) -> list[dict[str, Any]]:
    with _RING_LOCK:
        return list(_RING)[-limit:]


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"fields": fields})
