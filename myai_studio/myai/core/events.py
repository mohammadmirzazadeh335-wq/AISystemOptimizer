"""A tiny, dependency-free publish/subscribe bus.

The core and service layers must not import Qt.  They announce state changes
on this bus; the UI adapter subscribes to it and re-emits Qt signals on the
GUI thread.  Subscriber exceptions are swallowed (and logged by the owner) so
one broken listener can never take down another.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[..., Any]


class SignalBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, event: str, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._subscribers[event].append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subscribers.get(event, []):
                    self._subscribers[event].remove(handler)

        return unsubscribe

    def emit(self, event: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._subscribers.get(event, ()))
        for handler in handlers:
            try:
                handler(**payload)
            except Exception:  # pragma: no cover - listener isolation
                logger.exception("event_handler_failed event=%s handler=%r", event, handler)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


class Events:
    """Namespaced event names used across the application."""

    AGENT_STARTED = "agent.started"
    AGENT_STEP = "agent.step"
    AGENT_TOOL_STARTED = "agent.tool_started"
    AGENT_TOOL_FINISHED = "agent.tool_finished"
    AGENT_FINISHED = "agent.finished"

    PROMPTS_CHANGED = "prompts.changed"
    PLUGINS_CHANGED = "plugins.changed"

    APP_STARTED = "app.started"
    APP_SHUTDOWN = "app.shutdown"
    THEME_CHANGED = "theme.changed"
    SETTINGS_CHANGED = "settings.changed"
    LANGUAGE_CHANGED = "language.changed"

    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_UPDATED = "conversation.updated"
    CONVERSATION_DELETED = "conversation.deleted"
    CONVERSATION_SELECTED = "conversation.selected"

    MESSAGE_CREATED = "message.created"
    MESSAGE_UPDATED = "message.updated"
    MESSAGE_DELTA = "message.delta"
    MESSAGE_COMPLETED = "message.completed"
    MESSAGE_FAILED = "message.failed"
    STREAM_STARTED = "stream.started"
    STREAM_FINISHED = "stream.finished"

    MEMORY_CHANGED = "memory.changed"
    PERSONA_CHANGED = "persona.changed"
    MODELS_LOADED = "models.loaded"
    OUTPUT_CHANGED = "output.changed"

    TOAST = "ui.toast"
    TASK_STARTED = "task.started"
    TASK_UPDATED = "task.updated"
    TASK_FINISHED = "task.finished"
    ACTIVITY = "activity.log"
