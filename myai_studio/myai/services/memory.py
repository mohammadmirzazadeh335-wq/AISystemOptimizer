"""Durable assistant memory.

Two independent scopes:

* **global** — facts that follow the user across every conversation;
* **conversation** — facts bound to one chat, invisible to the others.

Rules enforced here (Phase 2 requirements):

* memory is always user-visible and user-editable;
* nothing is deleted or rewritten implicitly — summarisation adds rows;
* a summary never replaces history (the message table is untouched);
* storage size and estimated context usage are reported separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from ..core.errors import NotFoundError, ValidationError
from ..core.events import Events, SignalBus
from ..core.timeutil import utcnow
from ..data.db import Database
from ..data.models import Conversation, Memory, Message

logger = logging.getLogger(__name__)

GLOBAL = "global"
CONVERSATION = "conversation"
MAX_CONTENT = 4000
#: Rough characters-per-token ratio used for *estimates* only. Labelled as an
#: estimate everywhere it is displayed.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Deliberately approximate; provider-reported usage always wins."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    scope: str
    conversation_id: str | None
    content: str
    source: str
    pinned: bool
    created_at: Any
    updated_at: Any

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)


@dataclass(frozen=True)
class MemoryUsage:
    global_count: int
    conversation_count: int
    global_tokens: int
    conversation_tokens: int
    storage_bytes: int

    @property
    def total_tokens(self) -> int:
        return self.global_tokens + self.conversation_tokens


class MemoryService:
    def __init__(self, db: Database, bus: SignalBus | None = None) -> None:
        self._db = db
        self._bus = bus

    # ------------------------------------------------------------------ read
    def list(self, scope: str = GLOBAL, conversation_id: str | None = None) -> list[MemoryEntry]:
        scope, conversation_id = self._validate_scope(scope, conversation_id, creating=False)
        with self._db.session() as session:
            stmt = select(Memory).where(Memory.scope == scope)
            if scope == CONVERSATION:
                stmt = stmt.where(Memory.conversation_id == conversation_id)
            stmt = stmt.order_by(Memory.pinned.desc(), Memory.updated_at.desc())
            return [self._to_entry(row) for row in session.scalars(stmt)]

    def get(self, memory_id: str) -> MemoryEntry:
        with self._db.session() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                raise NotFoundError("Memory not found")
            return self._to_entry(row)

    def all_for_conversation(self, conversation_id: str | None) -> list[MemoryEntry]:
        """Global facts plus the facts of one conversation (context assembly)."""
        entries = self.list(GLOBAL)
        if conversation_id:
            entries += self.list(CONVERSATION, conversation_id)
        return entries

    def usage(self, conversation_id: str | None = None) -> MemoryUsage:
        with self._db.session() as session:
            def aggregate(scope: str, cid: str | None) -> tuple[int, int]:
                stmt = select(Memory.content).where(Memory.scope == scope)
                if scope == CONVERSATION:
                    if not cid:
                        return 0, 0
                    stmt = stmt.where(Memory.conversation_id == cid)
                rows = [row or "" for row in session.scalars(stmt)]
                return len(rows), sum(estimate_tokens(row) for row in rows)

            global_count, global_tokens = aggregate(GLOBAL, None)
            conv_count, conv_tokens = aggregate(CONVERSATION, conversation_id)
            total_chars = session.scalar(select(func.coalesce(func.sum(func.length(Memory.content)), 0))) or 0
        return MemoryUsage(
            global_count=global_count,
            conversation_count=conv_count,
            global_tokens=global_tokens,
            conversation_tokens=conv_tokens,
            storage_bytes=int(total_chars),
        )

    # ----------------------------------------------------------------- write
    def add(
        self,
        content: str,
        *,
        scope: str = GLOBAL,
        conversation_id: str | None = None,
        source: str = "manual",
        pinned: bool = False,
    ) -> MemoryEntry:
        text = self._clean(content)
        scope, conversation_id = self._validate_scope(scope, conversation_id, creating=True)
        with self._db.session() as session:
            row = Memory(
                scope=scope,
                conversation_id=conversation_id,
                content=text,
                source=source,
                pinned=pinned,
            )
            session.add(row)
            session.flush()
            entry = self._to_entry(row)
        self._emit(entry, "added")
        return entry

    def update(self, memory_id: str, content: str, *, pinned: bool | None = None) -> MemoryEntry:
        text = self._clean(content)
        with self._db.session() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                raise NotFoundError("Memory not found")
            row.content = text
            if pinned is not None:
                row.pinned = bool(pinned)
            session.flush()
            entry = self._to_entry(row)
        self._emit(entry, "updated")
        return entry

    def delete(self, memory_id: str) -> None:
        with self._db.session() as session:
            row = session.get(Memory, memory_id)
            if row is None:
                raise NotFoundError("Memory not found")
            scope, cid = row.scope, row.conversation_id
            session.delete(row)
        if self._bus:
            self._bus.emit(Events.MEMORY_CHANGED, action="deleted", scope=scope, conversation_id=cid)
        logger.info("memory_deleted id=%s scope=%s", memory_id, scope)

    def clear(self, scope: str, conversation_id: str | None = None) -> int:
        scope, conversation_id = self._validate_scope(scope, conversation_id, creating=False)
        with self._db.session() as session:
            stmt = select(Memory).where(Memory.scope == scope)
            if scope == CONVERSATION:
                stmt = stmt.where(Memory.conversation_id == conversation_id)
            rows = list(session.scalars(stmt))
            for row in rows:
                session.delete(row)
        if self._bus:
            self._bus.emit(Events.MEMORY_CHANGED, action="cleared", scope=scope, conversation_id=conversation_id)
        return len(rows)

    # ----------------------------------------------------------- summarising
    def summarize_conversation(
        self,
        conversation_id: str,
        *,
        max_items: int = 6,
        min_message_length: int = 40,
    ) -> list[MemoryEntry]:
        """Derive candidate facts from the conversation.

        This is a deterministic, local extraction — it does **not** call a model
        and it does not modify history. The caller shows the candidates and the
        user decides which ones become memories.
        """
        with self._db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError("Conversation not found")
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.role == "user")
                .order_by(Message.created_at)
            )
            messages = list(session.scalars(stmt))

        candidates: list[str] = []
        seen: set[str] = set()
        for message in reversed(messages):
            text = " ".join((message.content or "").split())
            if len(text) < min_message_length:
                continue
            sentence = self._first_sentence(text)
            key = sentence.casefold()
            if key in seen or len(candidates) >= max_items:
                continue
            seen.add(key)
            candidates.append(sentence)
        return [
            MemoryEntry(
                id="",
                scope=CONVERSATION,
                conversation_id=conversation_id,
                content=text,
                source="summary",
                pinned=False,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            for text in reversed(candidates)
        ]

    def commit_summary(self, conversation_id: str, items: list[str], *, replace: bool = False) -> list[MemoryEntry]:
        """Persist chosen summary items. History is never touched."""
        if replace:
            self.clear(CONVERSATION, conversation_id)
        return [
            self.add(
                item,
                scope=CONVERSATION,
                conversation_id=conversation_id,
                source="summary",
            )
            for item in items
            if item.strip()
        ]

    # --------------------------------------------------------------- helpers
    def build_context_block(self, conversation_id: str | None) -> str:
        """Render memories as a compact system-prompt block."""
        entries = self.all_for_conversation(conversation_id)
        if not entries:
            return ""
        global_lines = [f"- {e.content}" for e in entries if e.scope == GLOBAL]
        local_lines = [f"- {e.content}" for e in entries if e.scope == CONVERSATION]
        parts: list[str] = []
        if global_lines:
            parts.append("Facts about the user (global memory):\n" + "\n".join(global_lines))
        if local_lines:
            parts.append("Facts about this conversation:\n" + "\n".join(local_lines))
        return "\n\n".join(parts)

    def context_report(self, conversation_id: str | None, *, window: int) -> dict[str, Any]:
        """Separate *memory* usage from *conversation* usage."""
        usage = self.usage(conversation_id)
        with self._db.session() as session:
            history_chars = 0
            if conversation_id:
                history_chars = int(
                    session.scalar(
                        select(func.coalesce(func.sum(func.length(Message.content)), 0)).where(
                            Message.conversation_id == conversation_id
                        )
                    )
                    or 0
                )
        history_tokens = estimate_tokens("x" * history_chars)
        memory_tokens = usage.total_tokens
        total = memory_tokens + history_tokens
        ratio = (total / window) if window else 0.0
        return {
            "window": window,
            "memory_tokens": memory_tokens,
            "global_memory_tokens": usage.global_tokens,
            "conversation_memory_tokens": usage.conversation_tokens,
            "history_tokens": history_tokens,
            "total_tokens": total,
            "ratio": min(ratio, 1.0),
            "estimated": True,
        }

    @staticmethod
    def _first_sentence(text: str, limit: int = 220) -> str:
        match = re.split(r"(?<=[.!?؟])\s+", text, maxsplit=1)
        sentence = match[0] if match else text
        return sentence[:limit].strip()

    @staticmethod
    def _clean(content: str) -> str:
        text = " ".join((content or "").split())
        if not text:
            raise ValidationError("Memory content is empty", message_key="error.memory_empty")
        if len(text) > MAX_CONTENT:
            raise ValidationError(
                f"Memory content exceeds {MAX_CONTENT} characters",
                message_key="error.memory_too_long",
            )
        return text

    def _validate_scope(
        self, scope: str, conversation_id: str | None, *, creating: bool
    ) -> tuple[str, str | None]:
        if scope not in {GLOBAL, CONVERSATION}:
            raise ValidationError(f"Invalid memory scope: {scope}")
        if scope == GLOBAL:
            return GLOBAL, None
        if not conversation_id:
            raise ValidationError("Conversation memory requires a conversation")
        with self._db.session() as session:
            if session.get(Conversation, conversation_id) is None:
                raise NotFoundError("Conversation not found")
        return CONVERSATION, conversation_id

    def _emit(self, entry: MemoryEntry, action: str) -> None:
        if self._bus:
            self._bus.emit(
                Events.MEMORY_CHANGED,
                action=action,
                scope=entry.scope,
                conversation_id=entry.conversation_id,
            )
        logger.info("memory_%s scope=%s id=%s", action, entry.scope, entry.id)

    @staticmethod
    def _to_entry(row: Memory) -> MemoryEntry:
        return MemoryEntry(
            id=row.id,
            scope=row.scope,
            conversation_id=row.conversation_id,
            content=row.content or "",
            source=row.source or "manual",
            pinned=bool(row.pinned),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
