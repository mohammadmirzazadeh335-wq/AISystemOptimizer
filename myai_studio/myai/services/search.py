"""One query over everything the app already stores.

The overlay in the UI calls :meth:`SearchService.search`, which asks each
service for its own rows — no table is read with hand-written SQL here, so a
source that changes shape (or disappears) cannot break the search page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ValidationError

logger = logging.getLogger(__name__)

SOURCE_ORDER = ("conversation", "message", "prompt", "output", "memory", "task", "file")
MIN_QUERY = 2
SNIPPET_WIDTH = 96


@dataclass(frozen=True)
class SearchHit:
    source: str
    title: str
    snippet: str
    ref: str
    subtitle: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def snippet(text: str, needle: str, width: int = SNIPPET_WIDTH) -> str:
    """A single line around the first match, with the match kept in view."""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    position = flat.lower().find((needle or "").lower())
    if position < 0:
        return flat[:width] + ("…" if len(flat) > width else "")
    start = max(0, position - width // 3)
    end = min(len(flat), start + width)
    prefix = "…" if start else ""
    suffix = "…" if end < len(flat) else ""
    return f"{prefix}{flat[start:end]}{suffix}"


class SearchService:
    """Fan-out search across the local workspace.

    ``project`` is optional: when Code Studio has a folder open, file contents
    are searched too, otherwise the source is skipped entirely instead of
    silently returning nothing.
    """

    def __init__(
        self,
        conversations,  # noqa: ANN001 - duck-typed services keep this testable
        prompts=None,  # noqa: ANN001
        memory=None,  # noqa: ANN001
        outputs=None,  # noqa: ANN001
        tasks=None,  # noqa: ANN001
        projects=None,  # noqa: ANN001
    ) -> None:
        self._conversations = conversations
        self._prompts = prompts
        self._memory = memory
        self._outputs = outputs
        self._tasks = tasks
        self._projects = projects

    # ------------------------------------------------------------------ query
    def search(
        self,
        query: str,
        *,
        project=None,  # noqa: ANN001
        conversation_id: str | None = None,
        per_source: int = 6,
    ) -> list[SearchHit]:
        term = (query or "").strip()
        if len(term) < MIN_QUERY:
            return []
        limit = max(1, min(20, int(per_source)))
        hits: list[SearchHit] = []
        hits.extend(self._conversations_hits(term, limit))
        hits.extend(self._message_hits(term, limit))
        hits.extend(self._prompt_hits(term, limit))
        hits.extend(self._output_hits(term, limit))
        hits.extend(self._memory_hits(term, limit, conversation_id))
        hits.extend(self._task_hits(term, limit))
        hits.extend(self._file_hits(term, limit, project))
        return hits

    # ----------------------------------------------------------------- sources
    def _conversations_hits(self, term: str, limit: int) -> list[SearchHit]:
        try:
            summaries = self._conversations.summaries(search=term)
        except ValidationError:
            return []
        return [
            SearchHit(
                source="conversation",
                title=item.display_title,
                snippet=snippet(item.preview, term) or "",
                ref=item.id,
                subtitle="",
                extra={"message_count": item.message_count},
            )
            for item in summaries[:limit]
        ]

    def _message_hits(self, term: str, limit: int) -> list[SearchHit]:
        try:
            rows = self._conversations.search_messages(term, limit)
        except ValidationError:
            return []
        hits = []
        for row in rows:
            title = row.get("conversation_title") or ""
            hits.append(
                SearchHit(
                    source="message",
                    title=title.strip() or "—",
                    snippet=snippet(row.get("content", ""), term),
                    ref=row.get("id", ""),
                    subtitle=row.get("role", ""),
                    extra={
                        "conversation_id": row.get("conversation_id", ""),
                        "created_at": row.get("created_at"),
                    },
                )
            )
        return hits

    def _prompt_hits(self, term: str, limit: int) -> list[SearchHit]:
        if self._prompts is None:
            return []
        try:
            entries = self._prompts.list(search=term)
        except Exception:  # noqa: BLE001 - a broken source must not kill search
            logger.exception("search_source_failed source=prompt")
            return []
        return [
            SearchHit(
                source="prompt",
                title=entry.title,
                snippet=snippet(entry.body, term),
                ref=entry.id,
                subtitle=entry.category,
            )
            for entry in entries[:limit]
        ]

    def _output_hits(self, term: str, limit: int) -> list[SearchHit]:
        if self._outputs is None:
            return []
        needle = term.lower()
        try:
            entries = self._outputs.list()
        except Exception:  # noqa: BLE001
            logger.exception("search_source_failed source=output")
            return []
        hits = []
        for entry in entries:
            if needle in (entry.name or "").lower() or needle in (entry.content or "").lower():
                hits.append(
                    SearchHit(
                        source="output",
                        title=entry.name,
                        snippet=snippet(entry.content, term),
                        ref=entry.id,
                        subtitle=entry.kind,
                    )
                )
            if len(hits) >= limit:
                break
        return hits

    def _memory_hits(
        self, term: str, limit: int, conversation_id: str | None
    ) -> list[SearchHit]:
        if self._memory is None:
            return []
        needle = term.lower()
        entries = []
        try:
            entries.extend(self._memory.list("global"))
            if conversation_id:
                entries.extend(self._memory.list("conversation", conversation_id))
        except Exception:  # noqa: BLE001
            logger.exception("search_source_failed source=memory")
            return []
        hits = []
        seen: set[str] = set()
        for entry in entries:
            if entry.id in seen or needle not in (entry.content or "").lower():
                continue
            seen.add(entry.id)
            hits.append(
                SearchHit(
                    source="memory",
                    title=entry.scope,
                    snippet=snippet(entry.content, term),
                    ref=entry.id,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _task_hits(self, term: str, limit: int) -> list[SearchHit]:
        if self._tasks is None:
            return []
        try:
            entries = self._tasks.list(search=term, limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("search_source_failed source=task")
            return []
        return [
            SearchHit(
                source="task",
                title=entry.title,
                snippet=snippet(entry.detail, term),
                ref=entry.id,
                subtitle=entry.kind,
            )
            for entry in entries[:limit]
        ]

    def _file_hits(self, term: str, limit: int, project) -> list[SearchHit]:  # noqa: ANN001
        if self._projects is None or project is None:
            return []
        try:
            rows = self._projects.search(project, term, limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("search_source_failed source=file")
            return []
        return [
            SearchHit(
                source="file",
                title=row.get("path", ""),
                snippet=row.get("text", "").strip(),
                ref=row.get("path", ""),
                subtitle="",
                extra={"line": row.get("line")},
            )
            for row in rows[:limit]
        ]
