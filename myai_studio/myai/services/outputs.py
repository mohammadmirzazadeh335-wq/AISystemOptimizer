"""Output Studio backend: artefacts, revisions, diffs and file export.

Every save creates an immutable revision of the *previous* content, so a user
can compare versions and restore any of them. Nothing is ever overwritten
without leaving a trace.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..core.errors import NotFoundError, ValidationError
from ..core.events import Events, SignalBus
from ..core.paths import AppPaths
from ..core.timeutil import utcnow
from ..data.db import Database
from ..data.models import OutputFile, OutputRevision

logger = logging.getLogger(__name__)

KINDS = ("code", "text", "prompt", "markdown", "json")
MAX_CONTENT = 2_000_000

LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".java": "java", ".rs": "rust", ".go": "go", ".html": "html",
    ".css": "css", ".json": "json", ".md": "markdown", ".txt": "text",
    ".sh": "bash", ".ps1": "powershell", ".sql": "sql", ".yml": "yaml", ".yaml": "yaml",
}

KIND_BY_EXTENSION = {
    ".json": "json", ".md": "markdown", ".markdown": "markdown", ".txt": "text",
    ".prompt": "prompt",
}


@dataclass(frozen=True)
class OutputEntry:
    id: str
    conversation_id: str | None
    name: str
    kind: str
    language: str
    content: str
    path: str
    created_at: datetime
    updated_at: datetime
    revision_count: int = 0

    @property
    def line_count(self) -> int:
        return len(self.content.splitlines()) if self.content else 0

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))

    def is_json(self) -> bool:
        return self.kind == "json" or self.language == "json"


@dataclass(frozen=True)
class RevisionEntry:
    id: str
    output_id: str
    content: str
    note: str
    created_at: datetime

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


@dataclass(frozen=True)
class DiffResult:
    left_label: str
    right_label: str
    unified: str
    added: int
    removed: int

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)


def detect_language(name: str) -> str:
    return LANGUAGE_BY_EXTENSION.get(Path(name).suffix.lower(), "text")


def detect_kind(name: str) -> str:
    return KIND_BY_EXTENSION.get(Path(name).suffix.lower(), "code")


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", name or "", flags=re.UNICODE).strip().replace(" ", "-")
    return cleaned or "untitled"


class OutputService:
    def __init__(self, db: Database, paths: AppPaths, bus: SignalBus | None = None) -> None:
        self._db = db
        self._paths = paths
        self._bus = bus

    # ------------------------------------------------------------------ read
    def list(self, conversation_id: str | None = None, *, limit: int = 200) -> list[OutputEntry]:
        with self._db.session() as session:
            stmt = select(OutputFile).order_by(OutputFile.updated_at.desc()).limit(limit)
            if conversation_id:
                stmt = stmt.where(OutputFile.conversation_id == conversation_id)
            rows = list(session.scalars(stmt))
            return [self._to_entry(row, len(row.revisions)) for row in rows]

    def get(self, output_id: str) -> OutputEntry:
        with self._db.session() as session:
            row = session.get(OutputFile, output_id)
            if row is None:
                raise NotFoundError("Output not found")
            return self._to_entry(row, len(row.revisions))

    def revisions(self, output_id: str) -> list[RevisionEntry]:
        with self._db.session() as session:
            stmt = (
                select(OutputRevision)
                .where(OutputRevision.output_id == output_id)
                .order_by(OutputRevision.created_at.desc())
            )
            return [
                RevisionEntry(
                    id=row.id,
                    output_id=row.output_id,
                    content=row.content or "",
                    note=row.note or "",
                    created_at=row.created_at,
                )
                for row in session.scalars(stmt)
            ]

    # ----------------------------------------------------------------- write
    def create(
        self,
        name: str,
        content: str = "",
        *,
        kind: str | None = None,
        language: str | None = None,
        conversation_id: str | None = None,
    ) -> OutputEntry:
        clean_name = self._validate_name(name)
        self._validate_content(content)
        resolved_kind = kind or detect_kind(clean_name)
        if resolved_kind not in KINDS:
            raise ValidationError(f"Unknown output kind: {resolved_kind}")
        with self._db.session() as session:
            row = OutputFile(
                name=clean_name,
                kind=resolved_kind,
                language=language or detect_language(clean_name),
                content=content,
                conversation_id=conversation_id,
            )
            session.add(row)
            session.flush()
            entry = self._to_entry(row, 0)
        self._emit(entry, "created")
        logger.info("output_created id=%s kind=%s bytes=%s", entry.id, entry.kind, entry.size_bytes)
        return entry

    def update(
        self,
        output_id: str,
        *,
        content: str | None = None,
        name: str | None = None,
        note: str = "",
        keep_revision: bool = True,
    ) -> OutputEntry:
        with self._db.session() as session:
            row = session.get(OutputFile, output_id)
            if row is None:
                raise NotFoundError("Output not found")
            if content is not None:
                self._validate_content(content)
                if content != row.content and keep_revision:
                    session.add(
                        OutputRevision(
                            output_id=output_id,
                            content=row.content or "",
                            note=note or "before edit",
                        )
                    )
                row.content = content
            if name is not None:
                row.name = self._validate_name(name)
                row.language = detect_language(row.name) or row.language
            row.updated_at = utcnow()
            session.flush()
            entry = self._to_entry(row, len(row.revisions))
        self._emit(entry, "updated")
        return entry

    def delete(self, output_id: str) -> None:
        with self._db.session() as session:
            row = session.get(OutputFile, output_id)
            if row is None:
                raise NotFoundError("Output not found")
            name = row.name
            session.delete(row)
        if self._bus:
            self._bus.emit(Events.OUTPUT_CHANGED, action="deleted", name=name)
        logger.info("output_deleted id=%s", output_id)

    def restore(self, output_id: str, revision_id: str) -> OutputEntry:
        with self._db.session() as session:
            revision = session.get(OutputRevision, revision_id)
            if revision is None or revision.output_id != output_id:
                raise NotFoundError("Revision not found")
            content = revision.content or ""
        # Restoring is itself an edit: the replaced content is kept as a revision.
        return self.update(output_id, content=content, note="restore")

    # ------------------------------------------------------------------ diff
    def diff(
        self,
        output_id: str,
        left_revision: str | None = None,
        right_revision: str | None = None,
        *,
        context_lines: int = 3,
    ) -> DiffResult:
        output = self.get(output_id)
        revisions = {rev.id: rev for rev in self.revisions(output_id)}
        if left_revision is None:
            candidates = sorted(revisions.values(), key=lambda r: r.created_at)
            left_text = candidates[0].content if candidates else ""
            left_label = "revision 1" if candidates else "empty"
        else:
            if left_revision not in revisions:
                raise NotFoundError("Revision not found")
            left_text = revisions[left_revision].content
            left_label = f"revision {left_revision[:6]}"
        if right_revision is None:
            right_text = output.content
            right_label = "current"
        else:
            if right_revision not in revisions:
                raise NotFoundError("Revision not found")
            right_text = revisions[right_revision].content
            right_label = f"revision {right_revision[:6]}"

        added = removed = 0
        lines: list[str] = []
        diff = difflib.unified_diff(
            left_text.splitlines(),
            right_text.splitlines(),
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
            n=context_lines,
        )
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
            lines.append(line)
        return DiffResult(
            left_label=left_label,
            right_label=right_label,
            unified="\n".join(lines),
            added=added,
            removed=removed,
        )

    # ----------------------------------------------------------------- files
    def save_to_file(self, output_id: str, target: str | Path | None = None) -> Path:
        """Write the output next to the workspace (or an explicit path)."""
        output = self.get(output_id)
        if target is None:
            directory = self._paths.outputs_dir
            directory.mkdir(parents=True, exist_ok=True)
            target_path = directory / slugify(output.name)
        else:
            target_path = Path(target).expanduser()
            if target_path.is_dir():
                target_path = target_path / slugify(output.name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.suffix == "" and Path(output.name).suffix:
            target_path = target_path.with_suffix(Path(output.name).suffix)
        target_path.write_text(output.content, encoding="utf-8")
        with self._db.session() as session:
            row = session.get(OutputFile, output_id)
            if row is not None:
                row.path = str(target_path)
        self._emit(output, "saved", path=str(target_path))
        logger.info("output_saved id=%s path=%s", output_id, target_path)
        return target_path

    def import_file(self, source: str | Path, *, conversation_id: str | None = None) -> OutputEntry:
        path = Path(source).expanduser()
        if not path.is_file():
            raise NotFoundError(f"File not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        entry = self.create(
            path.name,
            content,
            kind=detect_kind(path.name),
            language=detect_language(path.name),
            conversation_id=conversation_id,
        )
        with self._db.session() as session:
            row = session.get(OutputFile, entry.id)
            if row is not None:
                row.path = str(path)
        return self.get(entry.id)

    def validate_json(self, text: str) -> tuple[bool, str]:
        """JSON editor helper: returns (valid, message)."""
        import json as _json

        try:
            _json.loads(text or "{}")
        except _json.JSONDecodeError as exc:
            return False, f"{exc.msg} (line {exc.lineno}, column {exc.colno})"
        return True, ""

    def format_json(self, text: str) -> str:
        import json as _json

        try:
            return _json.dumps(_json.loads(text or "{}"), ensure_ascii=False, indent=2)
        except _json.JSONDecodeError as exc:
            raise ValidationError(
                f"Invalid JSON: {exc.msg}", message_key="error.invalid_json"
            ) from exc

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _validate_name(name: str) -> str:
        clean = " ".join((name or "").split())[:120]
        if not clean:
            raise ValidationError("Output name is empty", message_key="error.output_name")
        return clean

    @staticmethod
    def _validate_content(content: str) -> None:
        if content and len(content) > MAX_CONTENT:
            raise ValidationError("Output is too large", message_key="error.output_too_large")

    def _emit(self, entry: OutputEntry, action: str, **extra: Any) -> None:
        if self._bus:
            self._bus.emit(Events.OUTPUT_CHANGED, action=action, output_id=entry.id,
                           conversation_id=entry.conversation_id, **extra)

    @staticmethod
    def _to_entry(row: OutputFile, revision_count: int) -> OutputEntry:
        return OutputEntry(
            id=row.id,
            conversation_id=row.conversation_id,
            name=row.name or "untitled",
            kind=row.kind or "text",
            language=row.language or "text",
            content=row.content or "",
            path=row.path or "",
            created_at=row.created_at,
            updated_at=row.updated_at,
            revision_count=revision_count,
        )
