"""Filesystem layout of a ParsERP installation.

Everything writable lives under a single *home* directory::

    <home>/
        config.json        runtime configuration (database URL, logging, ...)
        data/pars_erp.db   SQLite database (development / small deployments)
        backups/           database backups (zip + manifest)
        logs/              rotating log files
        exports/           user-initiated exports (CSV in phase 1)

The home defaults to ``%APPDATA%/ParsERP`` on Windows and
``~/.local/share/ParsERP`` elsewhere. It can be overridden with the
``PARSERP_HOME`` environment variable or by dropping a ``portable.flag`` file next
to the executable (portable installations keep their data next to the program).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "ParsERP"


def _default_home() -> Path:
    override = os.environ.get("PARSERP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    portable_root = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else None
    if portable_root and (portable_root / "portable.flag").exists():
        return portable_root / "data"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


@dataclass(frozen=True)
class AppPaths:
    home: Path

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(_default_home())

    @property
    def config_file(self) -> Path:
        return self.home / "config.json"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "pars_erp.db"

    @property
    def backups_dir(self) -> Path:
        return self.home / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    def ensure(self) -> "AppPaths":
        for directory in (self.home, self.data_dir, self.backups_dir, self.logs_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def as_dict(self) -> dict[str, str]:
        return {
            "home": str(self.home),
            "database_file": str(self.database_file),
            "backups_dir": str(self.backups_dir),
            "logs_dir": str(self.logs_dir),
            "exports_dir": str(self.exports_dir),
        }
