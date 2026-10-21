"""In-memory activity feed shown in the inspector.

The authoritative audit trail is the structured JSON log; this feed exists so
the inspector can render recent events without re-reading log files.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from ..core.events import Events, SignalBus
from ..core.timeutil import utcnow


@dataclass(frozen=True)
class ActivityItem:
    id: str
    text: str
    level: str = "info"
    kind: str = "general"
    at: datetime = field(default_factory=utcnow)
    meta: dict = field(default_factory=dict)
    key: str = ""
    kwargs: dict = field(default_factory=dict)

    def display(self) -> str:
        if self.key:
            from ..i18n import tr

            return tr(self.key, **self.kwargs)
        return self.text

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "level": self.level,
            "kind": self.kind,
            "at": self.at.isoformat(),
        }


class ActivityService:
    def __init__(self, bus: SignalBus, limit: int = 250) -> None:
        self._bus = bus
        self._limit = limit
        self._items: list[ActivityItem] = []
        self._lock = threading.Lock()

    def record(
        self,
        text: str = "",
        *,
        level: str = "info",
        kind: str = "general",
        meta: dict | None = None,
        key: str = "",
        kwargs: dict | None = None,
    ) -> ActivityItem:
        item = ActivityItem(
            id=uuid.uuid4().hex[:12],
            text=text,
            level=level,
            kind=kind,
            meta=meta or {},
            key=key,
            kwargs=kwargs or {},
        )
        with self._lock:
            self._items.append(item)
            if len(self._items) > self._limit:
                del self._items[: len(self._items) - self._limit]
        self._bus.emit(Events.ACTIVITY, item=item)
        return item

    def recent(self, limit: int = 50) -> list[ActivityItem]:
        with self._lock:
            return list(reversed(self._items[-limit:]))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
