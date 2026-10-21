"""Well-defined, overridable filesystem locations.

Nothing in the application writes into the program directory.  All mutable
state lives under a per-user application home so that installs stay clean and
backups are predictable.

Set ``MYAI_STUDIO_HOME`` to relocate everything (used by tests and the
portable build).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_home() -> Path:
    env = os.environ.get("MYAI_STUDIO_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "MyAIStudio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MyAIStudio"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "MyAIStudio"


def default_projects_dir() -> Path:
    if sys.platform.startswith("win"):
        docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        return docs / "MyAI Studio Projects"
    return Path.home() / "MyAI Studio Projects"


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @property
    def db_file(self) -> Path:
        return self.home / "myai_studio.db"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def secrets_file(self) -> Path:
        return self.home / "secrets.bin"

    @property
    def secret_key_file(self) -> Path:
        return self.home / "secret.key"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def outputs_dir(self) -> Path:
        return self.home / "outputs"

    @property
    def previews_dir(self) -> Path:
        return self.cache_dir / "previews"

    @property
    def images_dir(self) -> Path:
        return self.outputs_dir / "images"

    @property
    def videos_dir(self) -> Path:
        return self.outputs_dir / "videos"

    @property
    def documents_dir(self) -> Path:
        return self.outputs_dir / "documents"

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    def ensure(self) -> "AppPaths":
        for path in (
            self.home,
            self.logs_dir,
            self.backups_dir,
            self.cache_dir,
            self.previews_dir,
            self.outputs_dir,
            self.images_dir,
            self.videos_dir,
            self.documents_dir,
            self.projects_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def get_paths(home: str | Path | None = None) -> AppPaths:
    path = Path(home).expanduser().resolve() if home else _default_home()
    return AppPaths(home=path).ensure()
