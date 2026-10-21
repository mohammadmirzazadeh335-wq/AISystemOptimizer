"""ORM entities.

The schema is intentionally explicit and migration-friendly.  Every table is
owned by one repository; the UI never touches SQLAlchemy directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..core.timeutil import utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(24), default="#4F8CFF")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="folder")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    root_path: Mapped[str] = mapped_column(Text, default="")
    default_model: Mapped[str] = mapped_column(String(200), default="")
    color: Mapped[str] = mapped_column(String(24), default="#8B5CF6")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="Untitled chat")
    folder_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(20), default="chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    preview: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    folder: Mapped[Folder | None] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (
        Index("ix_conversations_updated", "updated_at"),
        Index("ix_conversations_folder", "folder_id"),
        Index("ix_conversations_project", "project_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    model_id: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="complete")
    error: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Memory(Base):
    """A durable fact remembered by the assistant.

    ``scope`` is either ``global`` (applies to every conversation) or
    ``conversation`` (bound to ``conversation_id``). Facts are never deleted
    implicitly: summarisation creates new rows and the UI asks before removing
    anything.
    """

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(20), default="global", nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_memories_scope", "scope"),
        Index("ix_memories_conversation", "conversation_id"),
    )


class OutputFile(Base):
    """A saved artefact produced in the workspace (code, text, prompt, JSON…)."""

    __tablename__ = "outputs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="untitled")
    kind: Mapped[str] = mapped_column(String(20), default="text")
    language: Mapped[str] = mapped_column(String(40), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    revisions: Mapped[list["OutputRevision"]] = relationship(
        back_populates="output", cascade="all, delete-orphan", order_by="OutputRevision.created_at"
    )

    __table_args__ = (Index("ix_outputs_conversation", "conversation_id"),)


class OutputRevision(Base):
    """Immutable snapshot of an output, used for diff and restore."""

    __tablename__ = "output_revisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    output_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("outputs.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    output: Mapped[OutputFile] = relationship(back_populates="revisions")

    __table_args__ = (Index("ix_revisions_output", "output_id"),)


class SchemaInfo(Base):
    __tablename__ = "schema_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
