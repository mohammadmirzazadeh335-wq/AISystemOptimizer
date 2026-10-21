"""Assistant personality and the user profile file.

Three independent stores (Phase 2 requirement):

1. **global memory** — facts (``MemoryService``, scope=global);
2. **conversation memory** — facts per chat (``MemoryService``);
3. **persona / profile** — instructions about *how* to answer, kept here.

The user profile is a plain Markdown file the user owns and can edit inside the
app; it is read fresh on every prompt build so external edits take effect.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ValidationError
from ..core.events import Events, SignalBus
from ..core.paths import AppPaths
from .settings import SettingsService

logger = logging.getLogger(__name__)

PROFILE_FILENAME = "profile.md"
MAX_PROFILE_BYTES = 64 * 1024

DEFAULT_PROFILE = """# دربارهٔ من

<!-- این فایل را آزادانه ویرایش کنید؛ دستیار در هر گفتگو آن را می‌خواند. -->
<!-- Write freely: the assistant reads this file for every request. -->

- نام / Name:
- نقش / Role:
- زبان ترجیحی پاسخ / Preferred answer language:
- حوزهٔ تخصص / Domain:
- ترجیح سبک پاسخ / Answer style:
"""

TONES = ("precise", "friendly", "formal", "concise")
DETAIL_LEVELS = ("brief", "balanced", "detailed")
LANGUAGES = ("auto", "fa", "en")


@dataclass(frozen=True)
class PersonaConfig:
    enabled: bool
    text: str
    tone: str
    detail: str
    language: str

    def describe(self) -> str:
        parts = []
        if self.text.strip():
            parts.append(self.text.strip())
        style = []
        if self.tone in TONES:
            style.append(f"tone: {self.tone}")
        if self.detail in DETAIL_LEVELS:
            style.append(f"detail: {self.detail}")
        if self.language in {"fa", "en"}:
            style.append(f"answer language: {'Persian' if self.language == 'fa' else 'English'}")
        if style:
            parts.append("Answer style — " + ", ".join(style) + ".")
        return "\n".join(parts)


class PersonaService:
    def __init__(self, settings: SettingsService, paths: AppPaths, bus: SignalBus | None = None) -> None:
        self._settings = settings
        self._paths = paths
        self._bus = bus
        self._profile_path = paths.home / PROFILE_FILENAME

    # ---------------------------------------------------------------- profile
    @property
    def profile_path(self) -> Path:
        return self._profile_path

    def ensure_profile(self) -> Path:
        if not self._profile_path.exists():
            self._profile_path.parent.mkdir(parents=True, exist_ok=True)
            self._profile_path.write_text(DEFAULT_PROFILE, encoding="utf-8")
        return self._profile_path

    def read_profile(self) -> str:
        self.ensure_profile()
        try:
            data = self._profile_path.read_bytes()[:MAX_PROFILE_BYTES]
            return data.decode("utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover - filesystem failure
            logger.warning("profile_read_failed %s", exc)
            return ""

    def write_profile(self, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValidationError("Profile file is too large", message_key="error.profile_too_large")
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._profile_path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._profile_path)
        self._emit("profile_saved")
        logger.info("profile_saved bytes=%s", len(text.encode("utf-8")))

    def import_profile(self, source: Path) -> str:
        data = source.read_text(encoding="utf-8", errors="replace")
        self.write_profile(data)
        return data

    # ---------------------------------------------------------------- persona
    def config(self) -> PersonaConfig:
        return PersonaConfig(
            enabled=bool(self._settings.get("ai.persona_enabled", False)),
            text=str(self._settings.get("ai.persona_text", "") or ""),
            tone=str(self._settings.get("ai.tone", "precise")),
            detail=str(self._settings.get("ai.detail", "balanced")),
            language=str(self._settings.get("ai.language_preference", "auto")),
        )

    def save(self, *, enabled: bool, text: str, tone: str, detail: str, language: str) -> PersonaConfig:
        if tone not in TONES:
            raise ValidationError(f"Unknown tone: {tone}")
        if detail not in DETAIL_LEVELS:
            raise ValidationError(f"Unknown detail level: {detail}")
        if language not in LANGUAGES:
            raise ValidationError(f"Unknown language preference: {language}")
        self._settings.update(
            {
                "ai.persona_enabled": bool(enabled),
                "ai.persona_text": (text or "")[:8000],
                "ai.tone": tone,
                "ai.detail": detail,
                "ai.language_preference": language,
            }
        )
        self._emit("persona_saved")
        return self.config()

    # ------------------------------------------------------------- assembly
    def build_system_block(self) -> str:
        """Persona instructions + the user profile, ready for the prompt."""
        config = self.config()
        blocks: list[str] = []
        if config.enabled:
            described = config.describe()
            if described:
                blocks.append(described)
        profile = self.read_profile().strip()
        if profile and not self._is_template_only(profile):
            blocks.append("User profile (written by the user):\n" + profile)
        return "\n\n".join(blocks)

    @staticmethod
    def _is_template_only(text: str) -> bool:
        """True when the profile is still the shipped, unfilled template.

        A labelled line counts as filled only when it carries a value after the
        colon, so "- Name:" is a placeholder while "- Name: Nima" is real
        content. Free text (not starting with ``-`` or ``#``) always counts.
        """
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "<!--", "-->")):
                continue
            if line.startswith("- "):
                _, sep, value = line[2:].partition(":")
                if not sep or value.strip():
                    return False
                continue
            return False
        return True

    def _emit(self, action: str) -> None:
        if self._bus:
            self._bus.emit(Events.PERSONA_CHANGED, action=action)
