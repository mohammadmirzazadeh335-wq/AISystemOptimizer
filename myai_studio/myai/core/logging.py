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

_CONFIGURED = False
_RING: deque[dict[str, Any]] = deque(maxlen=1000)
_RING_LOCK = threading.Lock()


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
        root.addHandler(file_handler)

    if console and sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(stream)

    root.addHandler(RingBufferHandler())
    _CONFIGURED = True
    return root


def get_recent_logs(limit: int = 200) -> list[dict[str, Any]]:
    with _RING_LOCK:
        return list(_RING)[-limit:]


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"fields": fields})
