"""Media library for Image Studio and Video Studio (Phase 5).

Neither studio can generate anything in this build: there is no image service and
no video service configured, and the pages say so with the exact missing piece.
What is real — and therefore implemented here — is the **library**: every file in
``<workspace>/outputs/images`` and ``outputs/videos`` is listed with its size and
modification time, can be previewed, opened in the system viewer or deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..core.errors import NotFoundError
from ..core.paths import AppPaths

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi"}

IMAGE_PROVIDER_NOTE = (
    "No image provider is configured. OpenRouter text models cannot return images, "
    "so generation stays unavailable until a real image API is added."
)
VIDEO_PROVIDER_NOTE = (
    "No video provider is configured. This build has no video generation service and "
    "does not simulate one."
)
#: i18n keys for the same two reasons. The UI must translate them: a Persian page
#: showing an English sentence was a real bug, not a label.
IMAGE_PROVIDER_KEY = "images.reason_no_provider"
VIDEO_PROVIDER_KEY = "video.reason_no_provider"


@dataclass(frozen=True)
class MediaItem:
    name: str
    path: Path
    size: int
    modified: datetime | None

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()


class MediaService:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths
        paths.images_dir.mkdir(parents=True, exist_ok=True)
        paths.videos_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- providers
    @staticmethod
    def image_provider() -> None:
        return None

    @staticmethod
    def video_provider() -> None:
        return None

    @property
    def images_available(self) -> bool:
        return self.image_provider() is not None

    @property
    def videos_available(self) -> bool:
        return self.video_provider() is not None

    # ------------------------------------------------------------------- listing
    def images(self) -> list[MediaItem]:
        return self._list(self._paths.images_dir, IMAGE_SUFFIXES)

    def videos(self) -> list[MediaItem]:
        return self._list(self._paths.videos_dir, VIDEO_SUFFIXES)

    def _list(self, folder: Path, suffixes: set[str]) -> list[MediaItem]:
        items: list[MediaItem] = []
        try:
            entries = list(folder.iterdir())
        except OSError:
            return items
        for entry in entries:
            if not entry.is_file() or entry.suffix.lower() not in suffixes:
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            items.append(
                MediaItem(
                    name=entry.name,
                    path=entry,
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                )
            )
        items.sort(key=lambda item: item.modified or datetime.min, reverse=True)
        return items

    # ------------------------------------------------------------------ mutation
    def delete(self, path: Path) -> None:
        target = Path(path)
        root = self._paths.outputs_dir.resolve()
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise NotFoundError("The file is no longer there.") from exc
        if root not in resolved.parents:
            raise NotFoundError("That file is outside the media library.")
        if not resolved.is_file():
            raise NotFoundError("The file is no longer there.")
        resolved.unlink()
        logger.info("media_deleted path=%s", resolved)

    def count(self) -> tuple[int, int]:
        return len(self.images()), len(self.videos())
