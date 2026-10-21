"""Local backups that never include secrets.

A backup is a zip containing a consistent SQLite snapshot (via the SQLite
online backup API), a JSON export of non-sensitive settings and a manifest.
API keys live in the encrypted secret store and are deliberately excluded.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..core.errors import AppError
from ..core.paths import AppPaths
from ..core.timeutil import utcnow
from ..data.db import Database
from ..services.settings import SettingsService
from ..version import PHASE, VERSION

logger = logging.getLogger(__name__)


class BackupError(AppError):
    code = "backup.error"


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: datetime
    size_bytes: int
    app_version: str
    schema_version: int

    @property
    def display_name(self) -> str:
        return self.path.name


class BackupService:
    def __init__(self, paths: AppPaths, db: Database, settings: SettingsService) -> None:
        self._paths = paths
        self._db = db
        self._settings = settings

    def create_backup(self) -> BackupInfo:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = self._paths.backups_dir / f"myai-backup-{stamp}.zip"
        sequence = 1
        while target.exists():  # never overwrite an existing backup
            target = self._paths.backups_dir / f"myai-backup-{stamp}-{sequence}.zip"
            sequence += 1
        work = self._paths.cache_dir / f"snapshot-{stamp}.db"
        work.parent.mkdir(parents=True, exist_ok=True)
        try:
            source = sqlite3.connect(str(self._paths.db_file))
            destination = sqlite3.connect(str(work))
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            integrity = sqlite3.connect(str(work)).execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise BackupError("Snapshot failed the integrity check", message_key="error.backup")
            manifest = {
                "app": "MyAI Studio Ultimate",
                "version": VERSION,
                "phase": PHASE,
                "created_at": utcnow().isoformat() + "Z",
                "schema_version": self._db.schema_version(),
                "contains_secrets": False,
                "settings": "settings.json",
                "database": "workspace.db",
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(work, "workspace.db")
                archive.writestr(
                    "settings.json", json.dumps(self._settings.public_export(), ensure_ascii=False, indent=2)
                )
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            info = BackupInfo(
                path=target,
                created_at=utcnow(),
                size_bytes=target.stat().st_size,
                app_version=VERSION,
                schema_version=self._db.schema_version(),
            )
            self._settings.set("data.last_backup", info.created_at.isoformat())
            self._prune()
            logger.info("backup_created path=%s bytes=%s", target, info.size_bytes)
            return info
        except BackupError:
            raise
        except Exception as exc:
            logger.exception("backup_failed")
            raise BackupError(
                "Backup could not be created", message_key="error.backup", details=str(exc), cause=exc
            ) from exc
        finally:
            try:
                work.unlink(missing_ok=True)
            except OSError:
                pass

    def list_backups(self) -> list[BackupInfo]:
        items: list[BackupInfo] = []
        if not self._paths.backups_dir.exists():
            return items
        for path in sorted(self._paths.backups_dir.glob("myai-backup-*.zip"), reverse=True):
            try:
                with zipfile.ZipFile(path) as archive:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                created = datetime.fromisoformat(str(manifest.get("created_at", "")).replace("Z", ""))
                items.append(
                    BackupInfo(
                        path=path,
                        created_at=created,
                        size_bytes=path.stat().st_size,
                        app_version=str(manifest.get("version", "?")),
                        schema_version=int(manifest.get("schema_version", 0)),
                    )
                )
            except Exception:
                logger.warning("backup_manifest_unreadable path=%s", path)
        return items

    def last_backup(self) -> datetime | None:
        backups = self.list_backups()
        return backups[0].created_at if backups else None

    def _prune(self) -> None:
        keep = int(self._settings.get("data.backups_to_keep", 10) or 10)
        backups = self.list_backups()
        for info in backups[keep:]:
            try:
                info.path.unlink()
                logger.info("backup_pruned path=%s", info.path)
            except OSError:
                logger.warning("backup_prune_failed path=%s", info.path)
