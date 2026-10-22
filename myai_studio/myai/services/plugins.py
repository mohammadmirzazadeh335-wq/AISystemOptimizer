"""Plugin discovery (Phase 5).

This build loads **data plugins**: a folder with a ``plugin.json`` manifest that
declares prompt packs. Plugins are disabled by default, are validated before they
are listed, and never execute code — a manifest that asks for a code plugin is
reported as unsupported with the exact reason instead of being loaded.

Enabling a prompt pack copies its prompts into the library with the source
``plugin:<id>``. Disabling it removes the copies the user has not edited; edited
copies are kept and reported, so a disable never silently destroys user text.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError
from ..core.events import Events, SignalBus
from ..core.paths import AppPaths
from .prompts import PLUGIN_PREFIX, PromptService

logger = logging.getLogger(__name__)

MANIFEST = "plugin.json"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
SUPPORTED_KINDS = {"prompt_pack"}
KNOWN_KINDS = {"prompt_pack", "tool", "theme", "provider"}
ALLOWED_PERMISSIONS = {"prompts.write", "library.read"}
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PROMPTS = 100
MAX_PROMPT_BODY = 20000

ENABLED_KEY = "plugins.enabled"


@dataclass(frozen=True)
class PluginPrompt:
    title: str
    body: str
    category: str = "plugin"
    tags: tuple[str, ...] = ()


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    description: str
    author: str
    kind: str
    permissions: tuple[str, ...]
    prompts: tuple[PluginPrompt, ...]
    path: Path
    enabled: bool
    valid: bool = True
    error: str = ""
    error_key: str = ""
    imported: int = 0

    @property
    def supported(self) -> bool:
        return self.valid and self.kind in SUPPORTED_KINDS


class PluginService:
    def __init__(
        self,
        paths: AppPaths,
        settings,  # noqa: ANN001 - SettingsService, kept duck-typed
        prompts: PromptService,
        bus: SignalBus | None = None,
    ) -> None:
        self._paths = paths
        self._settings = settings
        self._prompts = prompts
        self._bus = bus

    # ------------------------------------------------------------------ folders
    @property
    def folder(self) -> Path:
        return self._paths.home / "plugins"

    def ensure_folder(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder

    # ----------------------------------------------------------------- discovery
    def enabled_ids(self) -> list[str]:
        value = self._settings.get(ENABLED_KEY, []) if self._settings else []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, str)]

    def discover(self) -> list[PluginInfo]:
        self.ensure_folder()
        enabled = set(self.enabled_ids())
        plugins: list[PluginInfo] = []
        for entry in sorted(self.folder.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            info = self._read_manifest(entry)
            info.enabled = info.id in enabled and info.supported
            if info.supported:
                info.imported = len(self._prompts.from_plugin(info.id))
            plugins.append(info)
        return plugins

    def get(self, plugin_id: str) -> PluginInfo | None:
        return next((item for item in self.discover() if item.id == plugin_id), None)

    # ------------------------------------------------------------------- toggle
    def set_enabled(self, plugin_id: str, enabled: bool) -> tuple[bool, int, int, str]:
        """Enable or disable one plugin.

        Returns ``(enabled, imported, kept, error)``. ``kept`` counts edited
        prompts that survived a disable.
        """
        info = self.get(plugin_id)
        if info is None:
            return False, 0, 0, "No plugin with that id was found."
        if not info.supported:
            return False, 0, 0, info.error or "This plugin kind is not supported."

        current = set(self.enabled_ids())
        if enabled:
            current.add(plugin_id)
            self._save(current)
            imported = self._import(info)
            self._emit()
            logger.info("plugin_enabled id=%s prompts=%s", plugin_id, imported)
            return True, imported, 0, ""

        current.discard(plugin_id)
        self._save(current)
        kept = self._remove_unedited(info)
        self._emit()
        logger.info("plugin_disabled id=%s kept_edited=%s", plugin_id, kept)
        return False, 0, kept, ""

    def _save(self, ids: set[str]) -> None:
        if self._settings is not None:
            self._settings.update({ENABLED_KEY: sorted(ids)})

    # ------------------------------------------------------------------ example
    def write_example(self) -> Path:
        """Create (or refresh) a tiny example prompt pack so the format is visible."""
        target = self.ensure_folder() / "example-prompt-pack"
        target.mkdir(parents=True, exist_ok=True)
        manifest = {
            "id": "example-prompt-pack",
            "name": "Example prompt pack",
            "version": "1.0.0",
            "description": "Two starter prompts that show the data-plugin format.",
            "author": "MyAI Studio",
            "kind": "prompt_pack",
            "permissions": ["prompts.write"],
            "prompts": [
                {
                    "title": "Explain a stack trace",
                    "body": (
                        "Read this stack trace and explain, in order, what failed and why. "
                        "Name the first line that belongs to the project's own code and give "
                        "the smallest fix.\n\n{trace}"
                    ),
                    "category": "debugging",
                    "tags": ["debug", "errors"],
                },
                {
                    "title": "Commit message",
                    "body": (
                        "Write a conventional commit message for this diff: one summary line "
                        "under 72 characters, then a body explaining why (not what).\n\n"
                        "```diff\n{diff}\n```"
                    ),
                    "category": "code",
                    "tags": ["git"],
                },
            ],
        }
        (target / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target

    # ----------------------------------------------------------------- internals
    def _import(self, info: PluginInfo) -> int:
        existing = {entry.title for entry in self._prompts.from_plugin(info.id)}
        imported = 0
        for prompt in info.prompts:
            if prompt.title in existing:
                continue
            try:
                self._prompts.create(
                    prompt.title,
                    prompt.body,
                    category=prompt.category,
                    tags=list(prompt.tags),
                    source=f"{PLUGIN_PREFIX}{info.id}",
                )
                imported += 1
            except ValidationError:
                logger.warning("plugin_prompt_rejected plugin=%s title=%s", info.id, prompt.title)
        return imported

    def _remove_unedited(self, info: PluginInfo) -> int:
        manifest = {prompt.title: prompt for prompt in info.prompts}
        kept = 0
        for entry in self._prompts.from_plugin(info.id):
            original = manifest.get(entry.title)
            edited = (
                original is None
                or original.body.strip() != entry.body.strip()
                or original.category != entry.category
            )
            if edited:
                kept += 1
                continue
            self._prompts.delete(entry.id)
        return kept

    def _emit(self) -> None:
        if self._bus is not None:
            self._bus.emit(Events.PLUGINS_CHANGED)

    def _read_manifest(self, folder: Path) -> PluginInfo:
        path = folder / MANIFEST
        base = PluginInfo(
            id=folder.name,
            name=folder.name,
            version="",
            description="",
            author="",
            kind="",
            permissions=(),
            prompts=(),
            path=folder,
            enabled=False,
        )
        if not path.is_file():
            base.valid = False
            base.error = f"{MANIFEST} is missing."
            base.error_key = "plugins.error_no_manifest"
            return base
        try:
            raw = path.stat().st_size
            if raw > MAX_MANIFEST_BYTES:
                raise ValueError("manifest is larger than 256 KB")
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            base.valid = False
            base.error = f"{MANIFEST} is not valid JSON ({exc})."
            base.error_key = "plugins.error_bad_json"
            return base
        if not isinstance(data, dict):
            base.valid = False
            base.error = f"{MANIFEST} must contain a JSON object."
            base.error_key = "plugins.error_bad_json"
            return base

        plugin_id = str(data.get("id") or folder.name).strip()
        if not ID_PATTERN.match(plugin_id):
            base.valid = False
            base.error = "The plugin id must be 2–40 lowercase letters, digits, '-' or '_'."
            base.error_key = "plugins.error_bad_id"
            return base
        if plugin_id != folder.name:
            base.valid = False
            base.error = f"The id '{plugin_id}' does not match the folder name '{folder.name}'."
            base.error_key = "plugins.error_id_mismatch"
            return base
        version = str(data.get("version") or "").strip()
        if version and not VERSION_PATTERN.match(version):
            base.valid = False
            base.error = f"Version '{version}' is not major.minor.patch."
            base.error_key = "plugins.error_bad_version"
            return base

        kind = str(data.get("kind") or "").strip() or "prompt_pack"
        permissions: list[str] = []
        for permission in data.get("permissions") or []:
            text = str(permission).strip()
            if text and text not in ALLOWED_PERMISSIONS:
                base.valid = False
                base.error = f"Unknown permission '{text}'."
                base.error_key = "plugins.error_bad_permission"
                return base
            if text and text not in permissions:
                permissions.append(text)

        prompts: list[PluginPrompt] = []
        raw_prompts = data.get("prompts") or []
        if not isinstance(raw_prompts, list):
            base.valid = False
            base.error = "'prompts' must be a list."
            base.error_key = "plugins.error_bad_prompts"
            return base
        for item in raw_prompts[:MAX_PROMPTS]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if not title or not body:
                continue
            prompts.append(
                PluginPrompt(
                    title=title[:240],
                    body=body[:MAX_PROMPT_BODY],
                    category=str(item.get("category") or "plugin").strip()[:60] or "plugin",
                    tags=tuple(str(tag)[:32] for tag in (item.get("tags") or []) if str(tag).strip()),
                )
            )

        info = PluginInfo(
            id=plugin_id,
            name=str(data.get("name") or plugin_id)[:120],
            version=version,
            description=str(data.get("description") or "")[:600],
            author=str(data.get("author") or "")[:120],
            kind=kind,
            permissions=tuple(permissions),
            prompts=tuple(prompts),
            path=folder,
            enabled=False,
        )
        if kind not in KNOWN_KINDS:
            info.valid = False
            info.error = f"Unknown plugin kind '{kind}'."
            info.error_key = "plugins.error_bad_kind"
        elif kind not in SUPPORTED_KINDS:
            info.valid = False
            info.error = (
                f"'{kind}' plugins need code execution, which this build does not allow. "
                "Only data plugins (prompt packs) are loaded."
            )
            info.error_key = "plugins.error_code_plugins"
        elif not prompts:
            info.valid = False
            info.error = "The manifest declares no usable prompt."
            info.error_key = "plugins.error_no_prompts"
        return info
