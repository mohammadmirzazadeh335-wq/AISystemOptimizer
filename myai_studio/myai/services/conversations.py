"""Conversation, folder and project use-cases.

The UI talks to this service only.  Each method is a small transaction and
announces the resulting change on the event bus so every view stays in sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError
from ..core.events import Events, SignalBus
from ..core.timeutil import format_datetime
from ..data.models import Conversation, Folder, Message, Project
from ..data.repositories import (
    ConversationRepository,
    FolderRepository,
    MessageRepository,
    ProjectRepository,
)
from ..i18n import tr
from .activity import ActivityService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    title: str
    preview: str
    pinned: bool
    folder_id: str | None
    message_count: int
    model_id: str
    updated_at: Any

    @property
    def display_title(self) -> str:
        return self.title.strip() or tr("chat.untitled")


class ConversationService:
    def __init__(
        self,
        bus: SignalBus,
        conversations: ConversationRepository,
        messages: MessageRepository,
        folders: FolderRepository,
        projects: ProjectRepository,
        activity: ActivityService,
        default_model: str = "",
    ) -> None:
        self._bus = bus
        self._conversations = conversations
        self._messages = messages
        self._folders = folders
        self._projects = projects
        self._activity = activity
        self._default_model = default_model

    def set_default_model(self, model_id: str) -> None:
        self._default_model = model_id or ""

    # ------------------------------------------------------------- queries
    def list(self, search: str = "", folder_id: str | None = None) -> list[Conversation]:
        return self._conversations.list(search=search, folder_id=folder_id)

    def summaries(self, search: str = "", folder_id: str | None = None) -> list[ConversationSummary]:
        return [
            ConversationSummary(
                id=c.id,
                title=c.title,
                preview=c.preview,
                pinned=bool(c.pinned),
                folder_id=c.folder_id,
                message_count=int(c.message_count or 0),
                model_id=c.model_id or "",
                updated_at=c.updated_at,
            )
            for c in self.list(search=search, folder_id=folder_id)
        ]

    def get(self, conversation_id: str) -> Conversation:
        return self._conversations.get(conversation_id)

    def messages(self, conversation_id: str) -> list[Message]:
        return self._messages.list_for(conversation_id)

    def stats(self, conversation_id: str) -> dict[str, Any]:
        return self._conversations.stats(conversation_id)

    def search_messages(self, needle: str, limit: int = 20) -> list[dict[str, Any]]:
        """Message bodies matching ``needle``, newest first (global search)."""
        term = (needle or "").strip()
        if not term:
            return []
        return self._messages.search_text(term, limit)

    def folders(self) -> list[Folder]:
        return self._folders.list()

    def projects(self) -> list[Project]:
        return self._projects.list()

    # ------------------------------------------------------------- mutations
    def create(
        self,
        title: str = "",
        *,
        model_id: str = "",
        folder_id: str | None = None,
        project_id: str | None = None,
        select: bool = True,
    ) -> Conversation:
        conversation = self._conversations.create(
            title=title,
            model_id=model_id or self._default_model,
            folder_id=folder_id,
            project_id=project_id,
        )
        self._bus.emit(Events.CONVERSATION_CREATED, conversation=conversation)
        if select:
            self._bus.emit(Events.CONVERSATION_SELECTED, conversation_id=conversation.id)
        self._activity.record(key="chat.new_created", kind="conversation")
        logger.info("conversation_created id=%s", conversation.id)
        return conversation

    def rename(self, conversation_id: str, title: str) -> Conversation:
        title = " ".join((title or "").split())[:200]
        conversation = self._conversations.update(conversation_id, title=title)
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        self._activity.record(key="chat.renamed", kind="conversation")
        return conversation

    def set_pinned(self, conversation_id: str, pinned: bool) -> Conversation:
        conversation = self._conversations.update(conversation_id, pinned=bool(pinned))
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        self._activity.record(key="chat.pinned" if pinned else "chat.unpinned", kind="conversation")
        return conversation

    def move_to_folder(self, conversation_id: str, folder_id: str | None) -> Conversation:
        if folder_id is not None:
            self._folders.get(folder_id)  # raises if missing
        conversation = self._conversations.update(conversation_id, folder_id=folder_id)
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        return conversation

    def set_model(self, conversation_id: str, model_id: str) -> Conversation:
        conversation = self._conversations.update(conversation_id, model_id=model_id)
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        return conversation

    def set_mode(self, conversation_id: str, mode: str) -> Conversation:
        if mode not in {"chat", "agent"}:
            raise ValidationError("Invalid mode")
        conversation = self._conversations.update(conversation_id, mode=mode)
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        return conversation

    def delete(self, conversation_id: str) -> None:
        self._conversations.delete(conversation_id)
        self._bus.emit(Events.CONVERSATION_DELETED, conversation_id=conversation_id)
        self._activity.record(key="chat.deleted", kind="conversation", level="warning")
        logger.info("conversation_deleted id=%s", conversation_id)

    # -------------------------------------------------------------- messages
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        model_id: str = "",
        status: str = "complete",
        meta: dict | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> Message:
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValidationError(f"Invalid role: {role}")
        message = self._messages.add(
            conversation_id,
            role,
            content,
            model_id=model_id,
            status=status,
            meta=meta,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        conversation = self._conversations.get(conversation_id)
        self._bus.emit(Events.MESSAGE_CREATED, message=message, conversation=conversation)
        self._bus.emit(Events.CONVERSATION_UPDATED, conversation=conversation)
        return message

    def get_message(self, message_id: str):
        """Fetch one message by id (used after streaming to refresh the UI row)."""
        return self._messages.get(message_id)

    def delete_message(self, message_id: str) -> None:
        self._messages.delete(message_id)

    # ---------------------------------------------------------------- folders
    def create_folder(self, name: str) -> Folder:
        folder = self._folders.create(name)
        self._activity.record(key="nav.new_folder", kind="folder")
        return folder

    def rename_folder(self, folder_id: str, name: str) -> Folder:
        return self._folders.rename(folder_id, name)

    def delete_folder(self, folder_id: str) -> None:
        self._conversations.clear_folder(folder_id)
        self._folders.delete(folder_id)
        self._activity.record(key="toast.deleted", kind="folder")

    # --------------------------------------------------------------- projects
    def create_project(self, name: str, description: str = "") -> Project:
        project = self._projects.create(name, description)
        self._activity.record(text=name, kind="project")
        return project

    # ----------------------------------------------------------------- export
    def export_markdown(self, conversation_id: str, path: str | Path) -> Path:
        conversation = self._conversations.get(conversation_id)
        messages = self._messages.list_for(conversation_id)
        if not messages:
            raise ValidationError(tr("dialog.nothing_to_export"), message_key="dialog.nothing_to_export")
        language = "fa" if any("\u0600" <= ch <= "\u06FF" for ch in conversation.title) else "en"
        lines = [
            f"# {conversation.title.strip() or tr('chat.untitled')}",
            "",
            f"- **{tr('inspector.created')}:** {format_datetime(conversation.created_at, language)}",
            f"- **{tr('inspector.messages')}:** {len(messages)}",
            f"- **{tr('inspector.model')}:** {conversation.model_id or '—'}",
            "",
            "---",
            "",
        ]
        for message in messages:
            speaker = tr("chat.you") if message.role == "user" else tr("chat.assistant")
            if message.role == "system":
                speaker = "System"
            lines.append(f"### {speaker}")
            lines.append("")
            lines.append(message.content.strip() or "_— empty —_")
            lines.append("")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines), encoding="utf-8")
        self._activity.record(key="toast.exported", kind="export")
        self._bus.emit(Events.TOAST, message=tr("toast.exported"), level="success")
        return target

    # ------------------------------------------------------------------ helper
    def search_first_message(self, conversation_id: str) -> str:
        for message in self._messages.list_for(conversation_id):
            if message.role == "user" and message.content.strip():
                return message.content.strip().splitlines()[0][:80]
        return ""

