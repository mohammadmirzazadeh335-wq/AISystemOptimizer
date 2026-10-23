"""File versions for Code Studio.

Every save writes a snapshot of the file **after** it was written; the history
therefore contains exactly the states that existed on disk, not a diff guessed
from keystrokes.  Restoring writes the chosen state back and records it as a new
version, so a restore is itself undoable.

Snapshots are plain UTF-8 text under ``<home>/history/<project>/<file>/``.
The folder name is a hash of the absolute project root, the file name a hash of
the relative path, so moving the workspace does not mix histories and no user
path ever becomes part of a file name.
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import NotFoundError, ValidationError
from ..core.paths import AppPaths
from ..i18n import tr

logger = logging.getLogger(__name__)

SNAPSHOT_LIMIT = 40
MAX_SNAPSHOT_BYTES = 1_000_000
REASONS = ("save", "create", "restore", "patch", "import")


@dataclass(frozen=True)
class Snapshot:
    id: str
    reason: str
    size: int
    created_at: datetime

    @property
    def stamp(self) -> str:
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.created_at.timestamp())


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


class HistoryService:
    def __init__(self, paths: AppPaths, limit: int = SNAPSHOT_LIMIT) -> None:
        self._root = paths.history_dir
        self._limit = max(2, int(limit))

    # ------------------------------------------------------------------ paths
    def folder(self, project_root: str | Path, relative: str) -> Path:
        root = str(Path(project_root).resolve())
        clean = (relative or "").replace("\\", "/").strip("/")
        if not clean:
            raise ValidationError("A file name is required", message_key="error.file_missing")
        return self._root / _digest(root) / _digest(clean)

    # ------------------------------------------------------------------ write
    def record(
        self,
        project_root: str | Path,
        relative: str,
        text: str,
        *,
        reason: str = "save",
    ) -> Snapshot | None:
        """Store one state; returns ``None`` when it repeats the newest one."""
        data = (text or "").encode("utf-8")
        if not data or len(data) > MAX_SNAPSHOT_BYTES:
            return None
        folder = self.folder(project_root, relative)
        existing = self.versions(project_root, relative)
        if existing:
            try:
                if self.read(project_root, relative, existing[0].id) == text:
                    return None
            except NotFoundError:
                pass
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        # Two versions can land inside one millisecond; ordering is by file name,
        # so the stamp must be strictly newer than every stored version or the
        # "newest" one would depend on the reason's spelling.
        used = set()
        for path in folder.glob("*.snap"):
            head = path.stem.split("-", 1)[0]
            try:
                used.add(int(head))
            except ValueError:
                continue
        # A wall clock can step backwards (NTP, VM suspend). Version order is the
        # file name, so never write a stamp at or below the newest one on disk —
        # otherwise the prune would delete the version that was just saved.
        stamp = max(stamp, max(used, default=0) + 1)
        while stamp in used:
            stamp += 1
        clean_reason = reason if reason in REASONS else "save"
        target = folder / f"{stamp}-{clean_reason}.snap"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        self._prune(folder)
        logger.info("history_snapshot file=%s reason=%s bytes=%s", relative, clean_reason, len(data))
        return self._entry(target)

    # ------------------------------------------------------------------- read
    def versions(self, project_root: str | Path, relative: str) -> list[Snapshot]:
        folder = self.folder(project_root, relative)
        if not folder.exists():
            return []
        entries = [self._entry(path) for path in folder.glob("*.snap") if path.is_file()]
        entries.sort(key=lambda item: item.id, reverse=True)
        return entries

    def read(self, project_root: str | Path, relative: str, snapshot_id: str) -> str:
        folder = self.folder(project_root, relative)
        target = folder / f"{Path(snapshot_id).name}.snap"
        if not target.is_file():
            raise NotFoundError("That version no longer exists", message_key="error.file_missing")
        return target.read_text(encoding="utf-8", errors="replace")

    # ---------------------------------------------------------------- restore
    def restore(
        self,
        project_service,  # noqa: ANN001 - avoids a circular import
        project,  # noqa: ANN001
        relative: str,
        snapshot_id: str,
    ) -> str:
        text = self.read(project.root, relative, snapshot_id)
        # The write records the snapshot itself, tagged "restore" when the
        # service understands reasons, so the restored state is undoable and
        # visibly different from a plain save.
        supports_reason = "reason" in inspect.signature(project_service.write).parameters
        if supports_reason:
            project_service.write(project, relative, text, reason="restore")
        else:
            project_service.write(project, relative, text)
            self.record(project.root, relative, text, reason="restore")
        return text

    def clear(self, project_root: str | Path, relative: str) -> int:
        folder = self.folder(project_root, relative)
        if not folder.exists():
            return 0
        removed = 0
        for path in folder.glob("*.snap"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed

    # ----------------------------------------------------------------- helpers
    def describe(self, snapshot: Snapshot) -> str:
        return tr(
            f"history.reason_{snapshot.reason}"
            if snapshot.reason in REASONS
            else "history.reason_save"
        )

    def _entry(self, path: Path) -> Snapshot:
        stem = path.stem
        stamp, _, reason = stem.partition("-")
        try:
            created = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            created = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return Snapshot(id=stem, reason=reason or "save", size=size, created_at=created)

    def _prune(self, folder: Path) -> None:
        files = sorted(folder.glob("*.snap"), key=lambda item: item.name)
        for path in files[: max(0, len(files) - self._limit)]:
            path.unlink(missing_ok=True)
