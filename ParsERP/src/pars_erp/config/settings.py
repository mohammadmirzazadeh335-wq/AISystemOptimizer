"""Runtime configuration loaded from ``<home>/config.json``.

This file only holds *deployment* concerns (where the database is, how to log).
Business/UI preferences (company name, currency, theme, session timeout, ...)
live in the database and are edited inside the application, see
:mod:`pars_erp.services.settings_service`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pars_erp.config.paths import AppPaths
from pars_erp.core.errors import ConfigurationError

CONFIG_VERSION = 1
_ENV_DB_URL = "PARSERP_DATABASE_URL"


@dataclass
class FileConfig:
    config_version: int = CONFIG_VERSION
    database_url: str = ""
    echo_sql: bool = False
    log_level: str = "INFO"
    log_max_bytes: int = 2_000_000
    log_backup_count: int = 5
    backup_retention: int = 20
    locale: str = "fa_IR"
    timezone: str = "Asia/Tehran"
    extras: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FileConfig":
        url = (self.database_url or "").strip()
        if not url:
            url = f"sqlite:///{AppPaths.default().database_file.as_posix()}"
        if url.startswith("postgres") and not url.startswith("postgresql+"):
            # Force the psycopg3 driver unless the URL already names one.
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.database_url = url
        self.log_level = (self.log_level or "INFO").upper()
        return self


def write_default_config(paths: AppPaths, *, database_url: str | None = None,
                         overwrite: bool = False) -> Path:
    paths.ensure()
    target = paths.config_file
    if target.exists() and not overwrite:
        return target
    config = FileConfig(database_url=database_url or f"sqlite:///{paths.database_file.as_posix()}")
    target.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_config(paths: AppPaths | None = None) -> FileConfig:
    paths = paths or AppPaths.default()
    paths.ensure()
    data: dict[str, Any] = {}
    if paths.config_file.exists():
        try:
            data = json.loads(paths.config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"فایل تنظیمات «{paths.config_file}» قابل خواندن نیست: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigurationError("ساختار فایل تنظیمات معتبر نیست.")
    known = {f for f in FileConfig.__dataclass_fields__ if f != "extras"}
    config = FileConfig(**{k: v for k, v in data.items() if k in known},
                        extras={k: v for k, v in data.items() if k not in known})
    env_url = os.environ.get(_ENV_DB_URL)
    if env_url:
        config.database_url = env_url
    if not config.database_url:
        config.database_url = f"sqlite:///{paths.database_file.as_posix()}"
    return config.normalized()


def save_config(config: FileConfig, paths: AppPaths | None = None) -> Path:
    paths = paths or AppPaths.default()
    paths.ensure()
    payload = asdict(config)
    paths.config_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths.config_file


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def sqlite_file_from_url(url: str) -> Path | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    raw = url[len(prefix):]
    if raw in ("", ":memory:"):
        return None
    return Path(raw)
