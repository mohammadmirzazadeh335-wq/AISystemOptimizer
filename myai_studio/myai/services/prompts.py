"""Prompt library (Phase 5).

A prompt is a title, a body, a category and optional tags. The library ships a
small set of built-in prompts, seeds them once, and otherwise stores exactly what
the user writes. Nothing is generated or "enhanced" behind the user's back.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select

from ..core.errors import NotFoundError, ValidationError
from ..core.events import Events, SignalBus
from ..core.timeutil import utcnow
from ..data.db import Database
from ..data.models import Prompt

logger = logging.getLogger(__name__)

BUILTIN = "builtin"
USER = "user"
PLUGIN_PREFIX = "plugin:"
MAX_TITLE = 240
MAX_BODY = 20000
MAX_TAGS = 8

_BUILTINS: list[tuple[str, str, str, list[str]]] = [
    (
        "Review this diff",
        "You are a senior reviewer. Review the diff below. Report only real defects "
        "(correctness, security, resource leaks, broken edge cases), each with file, "
        "line and a concrete fix. Say plainly when there is nothing to fix.\n\n"
        "```diff\n{diff}\n```",
        "code",
        ["review", "diff"],
    ),
    (
        "Explain this code",
        "Explain what this code does, step by step, for a developer who has never seen "
        "it. Name the inputs, the outputs, the side effects and any assumption that "
        "could break in production. Do not invent behaviour that the code does not show."
        "\n\n```\n{code}\n```",
        "code",
        ["explain"],
    ),
    (
        "Write tests for this function",
        "Write focused tests for the function below using the project's existing test "
        "framework. Cover the happy path, empty input and one failure path. If the "
        "function is untestable as written, say why instead of guessing.\n\n"
        "```\n{code}\n```",
        "code",
        ["tests"],
    ),
    (
        "Research brief",
        "Research the question below. Give a short answer first, then the evidence "
        "with sources and dates. Separate what is confirmed from what is uncertain, "
        "and say when the sources disagree.\n\nQuestion: {question}",
        "research",
        ["research", "sources"],
    ),
    (
        "Summarise a document",
        "Summarise the text below in at most 12 bullet points, then list every decision, "
        "owner and deadline it mentions. Do not add facts that are not in the text.\n\n"
        "{text}",
        "writing",
        ["summary"],
    ),
    (
        "Persian writing pass",
        "متن زیر را ویرایش کن: ابهام‌ها را برطرف کن، جمله‌های بلند را بشکن و لحن را "
        "یکدست کن. معنی را تغییر نده و هیچ واقعیتی به آن اضافه نکن. نسخهٔ ویرایش‌شده را "
        "بنویس و در پایان فهرست کوتاهی از تغییرهای مهم بده.\n\n{text}",
        "writing",
        ["fa", "editing"],
    ),
]


@dataclass(frozen=True)
class PromptEntry:
    id: str
    title: str
    body: str
    category: str
    tags: tuple[str, ...]
    source: str
    uses: int
    updated_at: datetime

    @property
    def builtin(self) -> bool:
        return self.source == BUILTIN

    @property
    def from_plugin(self) -> str | None:
        return self.source[len(PLUGIN_PREFIX):] if self.source.startswith(PLUGIN_PREFIX) else None


class PromptService:
    def __init__(self, db: Database, bus: SignalBus | None = None) -> None:
        self._db = db
        self._bus = bus
        self._seeded = False

    # ------------------------------------------------------------------ seeding
    def seed(self) -> int:
        """Insert the built-in prompts once; never overwrite user edits."""
        with self._db.session() as session:
            existing = session.scalar(select(func.count()).select_from(Prompt)) or 0
            if existing:
                self._seeded = True
                return 0
            for title, body, category, tags in _BUILTINS:
                session.add(
                    Prompt(
                        title=title,
                        body=body,
                        category=category,
                        tags=list(tags),
                        source=BUILTIN,
                    )
                )
        self._seeded = True
        logger.info("prompt_library_seeded count=%s", len(_BUILTINS))
        return len(_BUILTINS)

    # --------------------------------------------------------------------- read
    def list(self, search: str = "", category: str = "") -> list[PromptEntry]:
        with self._db.session() as session:
            stmt = select(Prompt)
            if category and category not in {"all", "*"}:
                stmt = stmt.where(Prompt.category == category)
            term = search.strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.where(
                    or_(Prompt.title.ilike(like), Prompt.body.ilike(like), Prompt.category.ilike(like))
                )
            stmt = stmt.order_by(Prompt.updated_at.desc(), Prompt.title)
            return [self._to_entry(row) for row in session.scalars(stmt)]

    def get(self, prompt_id: str) -> PromptEntry:
        with self._db.session() as session:
            row = session.get(Prompt, prompt_id)
            if row is None:
                raise NotFoundError("Prompt not found")
            return self._to_entry(row)

    def categories(self) -> list[str]:
        with self._db.session() as session:
            rows = session.scalars(select(Prompt.category).distinct().order_by(Prompt.category))
            return [str(row) for row in rows if row]

    def count(self) -> int:
        with self._db.session() as session:
            return int(session.scalar(select(func.count()).select_from(Prompt)) or 0)

    def from_plugin(self, plugin_id: str) -> list[PromptEntry]:
        with self._db.session() as session:
            rows = session.scalars(select(Prompt).where(Prompt.source == f"{PLUGIN_PREFIX}{plugin_id}"))
            return [self._to_entry(row) for row in rows]

    # -------------------------------------------------------------------- write
    def create(
        self,
        title: str,
        body: str,
        *,
        category: str = "general",
        tags: list[str] | None = None,
        source: str = USER,
    ) -> PromptEntry:
        title = self._clean_title(title)
        body = self._clean_body(body)
        category = self._clean_category(category)
        with self._db.session() as session:
            row = Prompt(
                title=title,
                body=body,
                category=category,
                tags=self._clean_tags(tags),
                source=source,
            )
            session.add(row)
            session.flush()
            entry = self._to_entry(row)
        self._emit("created", entry)
        return entry

    def update(
        self,
        prompt_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> PromptEntry:
        with self._db.session() as session:
            row = session.get(Prompt, prompt_id)
            if row is None:
                raise NotFoundError("Prompt not found")
            if title is not None:
                row.title = self._clean_title(title)
            if body is not None:
                row.body = self._clean_body(body)
            if category is not None:
                row.category = self._clean_category(category)
            if tags is not None:
                row.tags = self._clean_tags(tags)
            row.updated_at = utcnow()
            session.flush()
            entry = self._to_entry(row)
        self._emit("updated", entry)
        return entry

    def delete(self, prompt_id: str) -> None:
        with self._db.session() as session:
            row = session.get(Prompt, prompt_id)
            if row is None:
                raise NotFoundError("Prompt not found")
            session.delete(row)
        self._emit("deleted", None)
        logger.info("prompt_deleted id=%s", prompt_id)

    def delete_source(self, source: str) -> int:
        """Remove every prompt that came from one source (used when disabling a plugin)."""
        with self._db.session() as session:
            result = session.execute(delete(Prompt).where(Prompt.source == source))
        count = int(result.rowcount or 0)
        if count:
            self._emit("deleted", None)
        return count

    def touch(self, prompt_id: str) -> PromptEntry:
        """Record a real use (inserting the prompt into the composer or a task)."""
        with self._db.session() as session:
            row = session.get(Prompt, prompt_id)
            if row is None:
                raise NotFoundError("Prompt not found")
            row.uses = int(row.uses or 0) + 1
            session.flush()
            return self._to_entry(row)

    def restore_defaults(self) -> int:
        """Re-add any built-in prompt whose title is missing; never duplicate rows."""
        existing = {entry.title for entry in self.list()}
        added = 0
        for title, body, category, tags in _BUILTINS:
            if title in existing:
                continue
            self.create(title, body, category=category, tags=list(tags), source=BUILTIN)
            added += 1
        return added

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _clean_title(title: str) -> str:
        text = " ".join(str(title or "").split())
        if not text:
            raise ValidationError("A prompt needs a title.", message_key="prompts.title_required")
        if len(text) > MAX_TITLE:
            raise ValidationError("The title is too long.", message_key="prompts.title_too_long")
        return text

    @staticmethod
    def _clean_body(body: str) -> str:
        text = str(body or "").strip()
        if not text:
            raise ValidationError("A prompt needs a body.", message_key="prompts.body_required")
        if len(text) > MAX_BODY:
            raise ValidationError("The prompt is too long.", message_key="prompts.body_too_long")
        return text

    @staticmethod
    def _clean_category(category: str) -> str:
        text = re.sub(r"[^A-Za-z0-9_\u0600-\u06FF -]", "", str(category or "")).strip()
        return (text or "general")[:60]

    @staticmethod
    def _clean_tags(tags: list[str] | None) -> list[str]:
        cleaned: list[str] = []
        for tag in tags or []:
            text = " ".join(str(tag).split())[:32]
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= MAX_TAGS:
                break
        return cleaned

    def _emit(self, action: str, entry: PromptEntry | None) -> None:
        if self._bus is not None:
            self._bus.emit(Events.PROMPTS_CHANGED, action=action, prompt_id=entry.id if entry else "")

    @staticmethod
    def _to_entry(row: Prompt) -> PromptEntry:
        return PromptEntry(
            id=row.id,
            title=row.title,
            body=row.body or "",
            category=row.category or "general",
            tags=tuple(row.tags or []),
            source=row.source or USER,
            uses=int(row.uses or 0),
            updated_at=row.updated_at,
        )
