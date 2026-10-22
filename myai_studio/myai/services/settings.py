"""Central settings registry.

Settings are flat dotted keys with typed defaults.  Reads are cheap and
thread-safe; writes are validated, persisted and announced on the event bus.
Secrets never live here (see :mod:`myai.security.secrets`).
"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlparse

from ..core.errors import ValidationError
from ..core.events import Events, SignalBus
from ..data.repositories import SettingRepository

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    # Interface
    "ui.language": "fa",
    "ui.theme": "midnight",
    "ui.accent": "azure",
    "ui.font_scale": 1.0,
    "ui.reduce_motion": False,
    "ui.density": "comfortable",
    "ui.start_view": "chat",
    "ui.inspector_open": True,
    "ui.sidebar_collapsed": False,
    "ui.sidebar_width": 288,
    "ui.confirm_delete": True,
    "ui.editor_autosave": True,
    "ui.window_width": 1440,
    "ui.window_height": 900,
    # AI provider (phase 2)
    "ai.provider": "openrouter",
    "ai.base_url": "https://openrouter.ai/api/v1",
    "ai.default_model": "",
    "ai.temperature": 0.7,
    "ai.max_tokens": 4096,
    "ai.stream": True,
    "ai.persona_enabled": False,
    "ai.persona_text": "",
    "ai.language_preference": "auto",
    "ai.tone": "precise",
    "ai.detail": "balanced",
    "ai.context_warn_ratio": 0.8,
    "ai.openrouter_cache": [],
    "ai.last_model_sync": "",
    # Memory (phase 2)
    "memory.enabled": True,
    "memory.auto_capture": True,
    "memory.context_warning_ratio": 0.8,
    # Code Studio (phase 3)
    "code.last_project": "",
    "code.recent_projects": [],
    "code.timeout_seconds": 10.0,
    "code.show_whitespace": False,
    # Agent (phase 4)
    "agent.require_confirmation": True,
    "agent.max_steps": 12,
    "agent.allow_network": False,
    "web.search_provider": "duckduckgo",
    "web.search_url": "",
    "web.safe_search": True,
    # Data
    "data.backup_on_exit": False,
    "data.backups_to_keep": 10,
    "data.last_backup": "",
    "logging.level": "INFO",
}


class SettingsService:
    def __init__(self, repository: SettingRepository, bus: SignalBus) -> None:
        self._repo = repository
        self._bus = bus
        self._values: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self._lock = threading.RLock()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._loaded = False

    # ------------------------------------------------------------------ load
    def load(self) -> dict[str, Any]:
        stored = self._repo.all()
        with self._lock:
            self._values = copy.deepcopy(DEFAULTS)
            for key, value in stored.items():
                if key in DEFAULTS:
                    try:
                        self._values[key] = self._coerce(key, value)
                    except ValidationError:
                        logger.warning("settings_ignored_invalid key=%s value=%r", key, value)
                else:
                    # Preserve forward-compatible keys written by a newer build.
                    self._values[key] = value
            self._loaded = True
        return dict(self._values)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ------------------------------------------------------------------ read
    def get(self, key: str, default: Any = None) -> Any:
        self._ensure_loaded()
        with self._lock:
            return self._values.get(key, DEFAULTS.get(key, default))

    def as_dict(self) -> dict[str, Any]:
        self._ensure_loaded()
        with self._lock:
            return copy.deepcopy(self._values)

    def public_export(self) -> dict[str, Any]:
        """Settings safe to include in a backup (no secrets are stored here)."""
        return {k: v for k, v in self.as_dict().items() if not k.startswith(("secret.", "auth."))}

    # ----------------------------------------------------------------- write
    def set(self, key: str, value: Any, *, persist: bool = True) -> Any:
        self._ensure_loaded()
        value = self._coerce(key, value)
        with self._lock:
            old = self._values.get(key)
            if old == value:
                return value
            self._values[key] = value
        if persist:
            self._repo.set(key, value)
        changed = {key: value}
        self._apply_side_effects(changed)
        self._notify(changed)
        logger.info("setting_changed key=%s", key)
        return value

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        self._ensure_loaded()
        clean: dict[str, Any] = {}
        for key, value in changes.items():
            clean[key] = self._coerce(key, value)
        with self._lock:
            actual = {k: clean[k] for k in clean if self._values.get(k) != clean[k]}
            if not actual:
                return {}
            self._values.update(actual)
        self._repo.set_many(actual)
        self._apply_side_effects(actual)
        self._notify(actual)
        logger.info("settings_updated keys=%s", ",".join(sorted(actual)))
        return actual

    def reset(self, keys: Iterable[str]) -> dict[str, Any]:
        updates = {key: DEFAULTS[key] for key in keys if key in DEFAULTS}
        return self.update(updates)

    def reset_all(self) -> dict[str, Any]:
        return self.update({key: copy.deepcopy(value) for key, value in DEFAULTS.items()})

    @staticmethod
    def _apply_side_effects(changed: dict[str, Any]) -> None:
        if "ui.language" in changed:
            from ..i18n import set_language

            set_language(changed["ui.language"])

    # -------------------------------------------------------------- listeners
    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _notify(self, changed: dict[str, Any]) -> None:
        self._bus.emit(Events.SETTINGS_CHANGED, changes=changed, settings=self.as_dict())
        for listener in list(self._listeners):
            try:
                listener(changed)
            except Exception:  # pragma: no cover - listener isolation
                logger.exception("settings_listener_failed")

    # ------------------------------------------------------------- validation
    def _coerce(self, key: str, value: Any) -> Any:
        if key not in DEFAULTS:
            if not isinstance(key, str) or not key:
                raise ValidationError("Invalid settings key", message_key="error.settings")
            return value
        default = DEFAULTS[key]
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Setting {key} expects an integer", message_key="error.settings"
                ) from exc
            if key == "ai.max_tokens" and not 32 <= number <= 131072:
                raise ValidationError("max_tokens out of range", message_key="error.settings")
            if key == "agent.max_steps" and not 1 <= number <= 50:
                raise ValidationError("max_steps out of range", message_key="error.settings")
            if key == "ui.sidebar_width" and not 220 <= number <= 420:
                raise ValidationError("sidebar width out of range", message_key="error.settings")
            if key == "data.backups_to_keep" and not 1 <= number <= 100:
                raise ValidationError("backup retention out of range", message_key="error.settings")
            if key == "ui.window_width" and not 900 <= number <= 8000:
                raise ValidationError("window width out of range", message_key="error.settings")
            if key == "ui.window_height" and not 600 <= number <= 8000:
                raise ValidationError("window height out of range", message_key="error.settings")
            return number
        if isinstance(default, float):
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"Setting {key} expects a number", message_key="error.settings"
                ) from exc
            if key == "ai.temperature" and not 0.0 <= number <= 2.0:
                raise ValidationError("temperature out of range", message_key="error.settings")
            if key == "ui.font_scale" and not 0.8 <= number <= 1.5:
                raise ValidationError("font scale out of range", message_key="error.settings")
            if key in {"memory.context_warning_ratio", "ai.context_warn_ratio"} and not 0.5 <= number <= 0.99:
                raise ValidationError("context warning ratio out of range", message_key="error.settings")
            if key == "code.timeout_seconds" and not 1.0 <= number <= 120.0:
                raise ValidationError("code timeout out of range", message_key="error.settings")
            return number
        if key == "web.search_url":
            text = str(value or "").strip()
            if text and not text.startswith(("https://", "http://")):
                raise ValidationError("Search endpoint must be an http(s) URL",
                                      message_key="error.settings")
            return text
        if key in {"ui.language"}:
            if value not in {"fa", "en"}:
                raise ValidationError("Unsupported language", message_key="error.settings")
            return value
        if key in {"ui.theme"}:
            if value not in {"midnight", "dawn", "aurora", "system"}:
                raise ValidationError("Unsupported theme", message_key="error.settings")
            return value
        if key in {"ui.accent"}:
            if value not in {"azure", "violet", "teal", "amber", "rose"}:
                raise ValidationError("Unsupported accent", message_key="error.settings")
            return value
        if key in {"ui.density"}:
            if value not in {"comfortable", "compact"}:
                raise ValidationError("Unsupported density", message_key="error.settings")
            return value
        if key == "ui.start_view":
            if value not in {"chat", "last"}:
                raise ValidationError("Unsupported start view", message_key="error.settings")
            return value
        if key == "ai.tone":
            if value not in {"precise", "friendly", "formal", "concise"}:
                raise ValidationError("Unsupported tone", message_key="error.settings")
            return value
        if key == "ai.detail":
            if value not in {"brief", "balanced", "detailed"}:
                raise ValidationError("Unsupported detail level", message_key="error.settings")
            return value
        if key == "ai.language_preference":
            if value not in {"auto", "fa", "en"}:
                raise ValidationError("Unsupported language preference", message_key="error.settings")
            return value
        if key == "ai.base_url":
            url = str(value).strip().rstrip("/")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValidationError(
                    "Provider base URL must be an https address", message_key="error.settings"
                )
            return url
        if isinstance(default, str):
            return str(value)
        return value
