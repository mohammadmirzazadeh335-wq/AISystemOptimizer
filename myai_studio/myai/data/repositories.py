"""Repository layer.

All SQL lives here.  Repositories return ORM objects that were loaded inside a
session and are therefore safe to read after the session closes (attributes
are not expired on commit).  Mutations are explicit and whitelisted.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, text

from ..core.errors import NotFoundError
from ..core.timeutil import utcnow
from .db import Database
from .models import Conversation, Folder, Message, Project, Setting

logger = logging.getLogger(__name__)


class FolderRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[Folder]:
        with self.db.session() as session:
            return list(session.scalars(select(Folder).order_by(Folder.sort_order, Folder.created_at)))

    def get(self, folder_id: str) -> Folder:
        with self.db.session() as session:
            folder = session.get(Folder, folder_id)
            if folder is None:
                raise NotFoundError(f"Folder {folder_id} not found", message_key="state.empty")
            return folder

    def create(self, name: str, color: str = "#4F8CFF") -> Folder:
        name = name.strip()
        if not name:
            raise ValueError("Folder name is required")
        with self.db.session() as session:
            folder = Folder(name=name, color=color)
            session.add(folder)
            session.flush()
            return folder

    def rename(self, folder_id: str, name: str) -> Folder:
        with self.db.session() as session:
            folder = session.get(Folder, folder_id)
            if folder is None:
                raise NotFoundError(f"Folder {folder_id} not found", message_key="state.empty")
            folder.name = name.strip() or folder.name
            return folder

    def delete(self, folder_id: str) -> None:
        with self.db.session() as session:
            folder = session.get(Folder, folder_id)
            if folder:
                session.delete(folder)


class ProjectRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[Project]:
        with self.db.session() as session:
            return list(session.scalars(select(Project).order_by(Project.updated_at.desc())))

    def create(self, name: str, description: str = "", root_path: str = "", color: str = "#8B5CF6") -> Project:
        with self.db.session() as session:
            project = Project(name=name.strip() or "Untitled project", description=description, root_path=root_path, color=color)
            session.add(project)
            session.flush()
            return project

    def delete(self, project_id: str) -> None:
        with self.db.session() as session:
            project = session.get(Project, project_id)
            if project:
                session.delete(project)


class ConversationRepository:
    WRITABLE = {
        "title",
        "folder_id",
        "project_id",
        "model_id",
        "mode",
        "pinned",
        "archived",
        "message_count",
        "preview",
        "meta",
    }

    def __init__(self, db: Database) -> None:
        self.db = db

    def list(
        self,
        *,
        search: str = "",
        folder_id: str | None = None,
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[Conversation]:
        with self.db.session() as session:
            stmt = select(Conversation)
            if not include_archived:
                stmt = stmt.where(Conversation.archived.is_(False))
            if folder_id:
                stmt = stmt.where(Conversation.folder_id == folder_id)
            term = search.strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.where(
                    or_(
                        Conversation.title.ilike(like),
                        Conversation.preview.ilike(like),
                    )
                )
            stmt = stmt.order_by(
                Conversation.pinned.desc(),
                Conversation.updated_at.desc(),
            ).limit(limit)
            return list(session.scalars(stmt))

    def get(self, conversation_id: str) -> Conversation:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError(
                    f"Conversation {conversation_id} not found", message_key="chat.empty_title"
                )
            return conversation

    def create(
        self,
        title: str = "",
        *,
        model_id: str = "",
        folder_id: str | None = None,
        project_id: str | None = None,
    ) -> Conversation:
        with self.db.session() as session:
            conversation = Conversation(
                title=title.strip(),
                model_id=model_id,
                folder_id=folder_id or None,
                project_id=project_id or None,
            )
            session.add(conversation)
            session.flush()
            return conversation

    def update(self, conversation_id: str, **changes: Any) -> Conversation:
        unknown = set(changes) - self.WRITABLE
        if unknown:
            raise ValueError(f"Unsupported conversation fields: {sorted(unknown)}")
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError(f"Conversation {conversation_id} not found")
            for key, value in changes.items():
                setattr(conversation, key, value)
            conversation.updated_at = utcnow()
            session.flush()
            return conversation

    def touch(self, conversation_id: str) -> None:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = utcnow()

    def delete(self, conversation_id: str) -> None:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                session.delete(conversation)

    def clear_folder(self, folder_id: str) -> None:
        with self.db.session() as session:
            session.execute(
                Conversation.__table__.update()
                .where(Conversation.folder_id == folder_id)
                .values(folder_id=None)
            )

    def stats(self, conversation_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError(f"Conversation {conversation_id} not found")
            counts = session.execute(
                select(Message.role, func.count(Message.id))
                .where(Message.conversation_id == conversation_id)
                .group_by(Message.role)
            ).all()
            tokens = session.execute(
                select(
                    func.coalesce(func.sum(Message.input_tokens), 0),
                    func.coalesce(func.sum(Message.output_tokens), 0),
                ).where(Message.conversation_id == conversation_id)
            ).one()
            return {
                "messages": sum(int(c) for _, c in counts),
                "by_role": {role: int(count) for role, count in counts},
                "input_tokens": int(tokens[0]),
                "output_tokens": int(tokens[1]),
                "created_at": conversation.created_at,
                "updated_at": conversation.updated_at,
            }


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_for(self, conversation_id: str) -> list[Message]:
        with self.db.session() as session:
            # ``rowid`` is SQLite's insertion counter: a stable tiebreaker for
            # messages created within the same microsecond.
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, text("messages.rowid"))
            )
            return list(session.scalars(stmt))

    def add(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        model_id: str = "",
        status: str = "complete",
        meta: dict[str, Any] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> Message:
        with self.db.session() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise NotFoundError(f"Conversation {conversation_id} not found")
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                model_id=model_id,
                status=status,
                meta=meta or {},
                input_tokens=max(0, int(input_tokens or 0)),
                output_tokens=max(0, int(output_tokens or 0)),
            )
            session.add(message)
            conversation.message_count = int(conversation.message_count or 0) + 1
            conversation.preview = _preview(content)
            conversation.updated_at = utcnow()
            session.flush()
            return message

    def get(self, message_id: str) -> Message:
        with self.db.session() as session:
            message = session.get(Message, message_id)
            if message is None:
                raise NotFoundError(f"Message {message_id} not found")
            return message

    def delete(self, message_id: str) -> None:
        with self.db.session() as session:
            message = session.get(Message, message_id)
            if message:
                conversation = session.get(Conversation, message.conversation_id)
                session.delete(message)
                if conversation:
                    conversation.message_count = max(0, int(conversation.message_count or 0) - 1)

    def count(self, conversation_id: str | None = None) -> int:
        with self.db.session() as session:
            stmt = select(func.count()).select_from(Message)
            if conversation_id:
                stmt = stmt.where(Message.conversation_id == conversation_id)
            return int(session.scalar(stmt) or 0)

    def search_text(self, needle: str, limit: int = 20) -> list[dict[str, Any]]:
        """Newest messages whose body contains ``needle`` (case-insensitive)."""
        with self.db.session() as session:
            like = f"%{needle}%"
            stmt = (
                select(Message, Conversation.title)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Message.content.ilike(like))
                .order_by(Message.created_at.desc())
                .limit(max(1, int(limit)))
            )
            return [
                {
                    "id": message.id,
                    "conversation_id": message.conversation_id,
                    "conversation_title": title or "",
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                }
                for message, title in session.execute(stmt).all()
            ]

    def usage_since(self, since: datetime) -> list[dict[str, Any]]:
        """Tokens grouped by UTC day, model and role.

        Only rows that carry usage are interesting; an empty assistant reply
        still counts as a request, a user message never does.
        """
        with self.db.session() as session:
            day = func.date(Message.created_at)
            stmt = (
                select(
                    day,
                    Message.model_id,
                    Message.role,
                    func.coalesce(func.sum(Message.input_tokens), 0),
                    func.coalesce(func.sum(Message.output_tokens), 0),
                    func.count(Message.id),
                )
                .where(Message.created_at >= since)
                .group_by(day, Message.model_id, Message.role)
            )
            return [
                {
                    "day": str(row[0]),
                    "model_id": row[1] or "",
                    "role": row[2] or "",
                    "input_tokens": int(row[3] or 0),
                    "output_tokens": int(row[4] or 0),
                    "messages": int(row[5] or 0),
                }
                for row in session.execute(stmt).all()
            ]


class SettingRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self) -> dict[str, Any]:
        with self.db.session() as session:
            return {row.key: row.value for row in session.scalars(select(Setting))}

    def get(self, key: str, default: Any = None) -> Any:
        with self.db.session() as session:
            row = session.get(Setting, key)
            return row.value if row is not None else default

    def set(self, key: str, value: Any) -> None:
        with self.db.session() as session:
            row = session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=value)
                session.add(row)
            else:
                row.value = value
                row.updated_at = utcnow()

    def set_many(self, values: dict[str, Any]) -> None:
        with self.db.session() as session:
            for key, value in values.items():
                row = session.get(Setting, key)
                if row is None:
                    session.add(Setting(key=key, value=value))
                else:
                    row.value = value
                    row.updated_at = utcnow()

    def delete(self, keys: Iterable[str]) -> None:
        keys = list(keys)
        if not keys:
            return
        with self.db.session() as session:
            session.execute(delete(Setting).where(Setting.key.in_(keys)))


def _preview(content: str, limit: int = 180) -> str:
    text = " ".join((content or "").split())
    return text[:limit]
