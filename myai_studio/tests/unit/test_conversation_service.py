from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from myai.core.errors import ValidationError
from myai.core.events import Events
from myai.services.backup import BackupService


def test_create_selects_and_emits(ctx) -> None:
    selected = []
    created = []
    ctx.bus.subscribe(Events.CONVERSATION_SELECTED, lambda conversation_id: selected.append(conversation_id))
    ctx.bus.subscribe(Events.CONVERSATION_CREATED, lambda conversation: created.append(conversation.id))
    conversation = ctx.conversations.create("Hello")
    assert selected == [conversation.id]
    assert created == [conversation.id]


def test_rename_pin_move_delete(ctx) -> None:
    conversation = ctx.conversations.create("Old title", select=False)
    renamed = ctx.conversations.rename(conversation.id, "  New   title  ")
    assert renamed.title == "New title"
    folder = ctx.conversations.create_folder("Research")
    moved = ctx.conversations.move_to_folder(conversation.id, folder.id)
    assert moved.folder_id == folder.id
    pinned = ctx.conversations.set_pinned(conversation.id, True)
    assert pinned.pinned is True
    ctx.conversations.delete_folder(folder.id)
    assert ctx.conversations.get(conversation.id).folder_id is None
    ctx.conversations.delete(conversation.id)
    assert ctx.conversations.list() == []


def test_messages_are_ordered_and_counted(ctx) -> None:
    conversation = ctx.conversations.create("Ordering", select=False)
    for index in range(5):
        ctx.conversations.add_message(conversation.id, "user", f"m{index}")
    rows = ctx.conversations.messages(conversation.id)
    assert [m.content for m in rows] == [f"m{i}" for i in range(5)]
    stats = ctx.conversations.stats(conversation.id)
    assert stats["messages"] == 5 and stats["by_role"]["user"] == 5


def test_invalid_role_rejected(ctx) -> None:
    conversation = ctx.conversations.create("Roles", select=False)
    with pytest.raises(ValidationError):
        ctx.conversations.add_message(conversation.id, "root", "nope")


def test_invalid_mode_rejected(ctx) -> None:
    conversation = ctx.conversations.create("Modes", select=False)
    with pytest.raises(ValidationError):
        ctx.conversations.set_mode(conversation.id, "hacker")


def test_export_markdown(ctx, tmp_path: Path) -> None:
    conversation = ctx.conversations.create("Exported", select=False)
    ctx.conversations.add_message(conversation.id, "user", "سلام")
    ctx.conversations.add_message(conversation.id, "assistant", "**bold** answer")
    target = ctx.conversations.export_markdown(conversation.id, tmp_path / "out.md")
    content = target.read_text(encoding="utf-8")
    assert "# Exported" in content
    assert "سلام" in content
    assert "**bold** answer" in content


def test_export_empty_conversation_fails(ctx, tmp_path: Path) -> None:
    conversation = ctx.conversations.create("Empty", select=False)
    with pytest.raises(ValidationError):
        ctx.conversations.export_markdown(conversation.id, tmp_path / "x.md")


def test_backup_contains_database_and_no_secrets(ctx, tmp_path: Path) -> None:
    ctx.secrets.set("openrouter.api_key", "sk-or-v1-supersecret")
    conversation = ctx.conversations.create("Backed up", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    service = BackupService(ctx.paths, ctx.db, ctx.settings)
    info = service.create_backup()
    assert info.path.exists() and info.size_bytes > 0
    with zipfile.ZipFile(info.path) as archive:
        names = set(archive.namelist())
        assert {"workspace.db", "settings.json", "manifest.json"} <= names
        blob = b"".join(archive.read(name) for name in names)
        assert b"sk-or-v1-supersecret" not in blob
        manifest = archive.read("manifest.json").decode()
        assert '"contains_secrets": false' in manifest
    backups = service.list_backups()
    assert backups and backups[0].path == info.path
    assert service.last_backup() is not None


def test_backup_retention(ctx) -> None:
    ctx.settings.set("data.backups_to_keep", 2)
    service = BackupService(ctx.paths, ctx.db, ctx.settings)
    created = [service.create_backup() for _ in range(3)]
    remaining = service.list_backups()
    assert len(remaining) == 2
    assert created[-1].path in {info.path for info in remaining}


def test_backup_snapshot_integrity(ctx) -> None:
    service = BackupService(ctx.paths, ctx.db, ctx.settings)
    info = service.create_backup()
    import sqlite3

    with zipfile.ZipFile(info.path) as archive:
        data = archive.read("workspace.db")
    tmp = ctx.paths.cache_dir / "verify.db"
    tmp.write_bytes(data)
    connection = sqlite3.connect(str(tmp))
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"conversations", "messages", "settings"} <= tables
    connection.close()
