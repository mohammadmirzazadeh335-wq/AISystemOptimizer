"""Project folders for Code Studio.

A project is a real directory on disk. Everything the editor does goes through
this service, which refuses any path that escapes the project root (``..``,
absolute paths and symlinks included), caps file sizes and refuses to treat a
binary file as text. Recent projects are remembered in settings, not in the
database, because they are just pointers to folders the user owns.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import NotFoundError, ValidationError
from ..core.paths import AppPaths
from .settings import SettingsService

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2_000_000
MAX_TREE_ENTRIES = 2_000
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".myai-build", "dist", "build",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".java": "java", ".rs": "rust", ".go": "go",
    ".html": "html", ".css": "css", ".scss": "scss",
    ".json": "json", ".md": "markdown", ".txt": "text", ".sh": "bash",
    ".ps1": "powershell", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".ini": "ini",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".pdf",
    ".zip", ".gz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".o",
    ".class", ".pyc", ".woff", ".woff2", ".ttf", ".mp3", ".mp4", ".mov",
    ".db", ".sqlite", ".bin",
}

_SAFE_NAME = re.compile(r"^[^/\\:*?\"<>|\x00]+$")


@dataclass(frozen=True)
class Project:
    root: Path
    name: str

    @property
    def path(self) -> str:
        return str(self.root)

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name}


@dataclass(frozen=True)
class TreeEntry:
    relative: str
    name: str
    is_dir: bool
    size: int
    language: str


@dataclass(frozen=True)
class FileContent:
    relative: str
    text: str
    size: int
    language: str
    binary: bool
    truncated: bool

    @property
    def editable(self) -> bool:
        return not self.binary


def language_for(path: Path | str) -> str:
    suffix = Path(path).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix, "text")


class ProjectService:
    def __init__(self, paths: AppPaths, settings: SettingsService) -> None:
        self._paths = paths
        self._settings = settings

    # ------------------------------------------------------------------ project
    def open_folder(self, path: str | Path) -> Project:
        root = Path(path).expanduser()
        if not root.exists():
            raise NotFoundError(f"Folder does not exist: {root}")
        if not root.is_dir():
            raise ValidationError(f"Not a folder: {root}")
        project = Project(root=root.resolve(), name=root.resolve().name or str(root))
        self._remember(project)
        return project

    def create_project(self, name: str) -> Project:
        clean = (name or "").strip()
        if not clean or not _SAFE_NAME.match(clean) or clean in {".", ".."}:
            raise ValidationError("Project name contains unsupported characters")
        root = self._paths.projects_dir / clean
        root.mkdir(parents=True, exist_ok=True)
        project = Project(root=root.resolve(), name=clean)
        self._remember(project)
        logger.info("project_created path=%s", project.path)
        return project

    def recent(self, limit: int = 8) -> list[Project]:
        raw = self._settings.get("code.recent_projects", []) or []
        projects: list[Project] = []
        for item in raw[:limit]:
            try:
                path = Path(str(item.get("path", "")))
            except (TypeError, ValueError):
                continue
            if path.is_dir():
                projects.append(Project(root=path, name=str(item.get("name") or path.name)))
        return projects

    def last_project(self) -> Project | None:
        items = self.recent(limit=1)
        return items[0] if items else None

    def _remember(self, project: Project) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw = [dict(item) for item in (self._settings.get("code.recent_projects", []) or [])]
        raw = [item for item in raw if str(item.get("path")) != project.path]
        raw.insert(0, {"path": project.path, "name": project.name, "at": stamp})
        self._settings.set("code.recent_projects", raw[:12])
        self._settings.set("code.last_project", project.path)

    # --------------------------------------------------------------------- tree
    def tree(self, project: Project, limit: int = MAX_TREE_ENTRIES) -> list[TreeEntry]:
        entries: list[TreeEntry] = []

        def walk(folder: Path, depth: int) -> None:
            if len(entries) >= limit or depth > 12:
                return
            try:
                children = sorted(
                    folder.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.lower()),
                )
            except OSError:
                return
            for child in children:
                if len(entries) >= limit:
                    return
                if child.name in SKIP_DIRS or child.name.startswith(".myai"):
                    continue
                try:
                    is_dir = child.is_dir()
                    size = 0 if is_dir else child.stat().st_size
                except OSError:
                    continue
                relative = child.relative_to(project.root).as_posix()
                entries.append(
                    TreeEntry(
                        relative=relative,
                        name=child.name,
                        is_dir=is_dir,
                        size=size,
                        language="" if is_dir else language_for(child),
                    )
                )
                if is_dir:
                    walk(child, depth + 1)

        walk(project.root, 0)
        return entries

    # -------------------------------------------------------------------- files
    def resolve(self, project: Project, relative: str) -> Path:
        """Resolve ``relative`` inside the project or raise :class:`ValidationError`."""
        raw = (relative or "").strip().replace("\\", "/")
        if not raw:
            raise ValidationError("An empty path is not a file")
        candidate = Path(raw)
        # A Windows drive path is absolute even when the app runs on Linux, so it
        # is rejected by shape rather than by ``Path.is_absolute``.
        if candidate.is_absolute() or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
            raise ValidationError("Absolute paths are not allowed inside a project")
        if any(part in {"..", ""} for part in candidate.parts):
            raise ValidationError("Path traversal is not allowed inside a project")
        root = project.root.resolve()
        target = (root / candidate).resolve()
        if target != root and root not in target.parents:
            raise ValidationError("The path escapes the project folder")
        return target

    def relative(self, project: Project, path: Path) -> str:
        return path.resolve().relative_to(project.root.resolve()).as_posix()

    def read(self, project: Project, relative: str) -> FileContent:
        target = self.resolve(project, relative)
        if not target.exists():
            raise NotFoundError(f"File does not exist: {relative}")
        if target.is_dir():
            raise ValidationError("This is a folder, not a file")
        size = target.stat().st_size
        suffix = target.suffix.lower()
        binary = suffix in BINARY_EXTENSIONS
        if not binary:
            with open(target, "rb") as handle:
                head = handle.read(8192)
            binary = b"\x00" in head
        if binary:
            return FileContent(
                relative=relative,
                text="",
                size=size,
                language=language_for(target),
                binary=True,
                truncated=False,
            )
        truncated = size > MAX_FILE_BYTES
        with open(target, encoding="utf-8", errors="replace") as handle:
            text = handle.read(MAX_FILE_BYTES if truncated else -1)
        return FileContent(
            relative=relative,
            text=text,
            size=size,
            language=language_for(target),
            binary=False,
            truncated=truncated,
        )

    def write(self, project: Project, relative: str, text: str) -> FileContent:
        target = self.resolve(project, relative)
        data = text.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValidationError(
                f"File is larger than the {MAX_FILE_BYTES // 1000} KB editor limit"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".myai-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        logger.info("project_file_saved path=%s bytes=%s", relative, len(data))
        return self.read(project, relative)

    def create_file(self, project: Project, relative: str, content: str = "") -> FileContent:
        target = self.resolve(project, relative)
        if target.exists():
            raise ValidationError("A file or folder with that name already exists")
        return self.write(project, relative, content)

    def rename(self, project: Project, relative: str, new_name: str) -> str:
        source = self.resolve(project, relative)
        clean = (new_name or "").strip()
        if not clean or not _SAFE_NAME.match(clean) or clean in {".", ".."}:
            raise ValidationError("New name contains unsupported characters")
        target = source.with_name(clean)
        if target.exists():
            raise ValidationError("A file or folder with that name already exists")
        source.rename(target)
        return self.relative(project, target)

    def delete(self, project: Project, relative: str) -> None:
        target = self.resolve(project, relative)
        if target == project.root.resolve():
            raise ValidationError("The project folder itself cannot be deleted")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            raise NotFoundError(f"File does not exist: {relative}")

    def stat(self, project: Project) -> dict:
        files = 0
        folders = 0
        total = 0
        for entry in self.tree(project):
            if entry.is_dir:
                folders += 1
            else:
                files += 1
                total += entry.size
        return {"files": files, "folders": folders, "bytes": total}
