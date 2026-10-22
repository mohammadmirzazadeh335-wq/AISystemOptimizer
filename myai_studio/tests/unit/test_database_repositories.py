from __future__ import annotations

from pathlib import Path

import pytest

from myai.core.errors import NotFoundError
from myai.data import Database
from myai.data.repositories import (
    ConversationRepository,
    FolderRepository,
    MessageRepository,
    ProjectRepository,
    SettingRepository,
)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "db.sqlite").initialize()
    yield database
    database.close()


def test_schema_created_and_versioned(db: Database) -> None:
    assert db.schema_version() == 3
    assert db.integrity_check() == "ok"
    counts = db.counts()
    assert counts == {
        "conversations": 0,
        "messages": 0,
        "folders": 0,
        "projects": 0,
        "memories": 0,
        "outputs": 0,
        "prompts": 0,
        "task_runs": 0,
    }


def test_wal_and_foreign_keys_enabled(db: Database) -> None:
    with db.engine.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_reopening_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    first = Database(path).initialize()
    conversation = ConversationRepository(first).create("Persisted")
    first.close()
    second = Database(path).initialize()
    assert ConversationRepository(second).get(conversation.id).title == "Persisted"
    second.close()


def test_conversation_crud_and_search(db: Database) -> None:
    repo = ConversationRepository(db)
    alpha = repo.create("Alpha design notes")
    beta = repo.create("Beta compiler plan")
    repo.update(alpha.id, pinned=True, preview="shared word")
    listed = repo.list()
    assert listed[0].id == alpha.id  # pinned first
    assert [c.id for c in repo.list(search="compiler")] == [beta.id]
    assert [c.id for c in repo.list(search="shared")] == [alpha.id]
    repo.delete(beta.id)
    with pytest.raises(NotFoundError):
        repo.get(beta.id)


def test_update_rejects_unknown_fields(db: Database) -> None:
    repo = ConversationRepository(db)
    conversation = repo.create("x")
    with pytest.raises(ValueError):
        repo.update(conversation.id, secret_field="nope")


def test_messages_order_and_cascade(db: Database) -> None:
    conversations = ConversationRepository(db)
    messages = MessageRepository(db)
    folder = FolderRepository(db).create("F")
    conversation = conversations.create("T", folder_id=folder.id)
    for index in range(10):
        messages.add(conversation.id, "user" if index % 2 == 0 else "assistant", f"m{index}")
    rows = messages.list_for(conversation.id)
    assert [m.content for m in rows] == [f"m{i}" for i in range(10)]
    assert conversations.get(conversation.id).message_count == 10
    assert conversations.get(conversation.id).preview == "m9"
    conversations.delete(conversation.id)
    assert messages.count(conversation.id) == 0
    with pytest.raises(NotFoundError):
        messages.add(conversation.id, "user", "orphan")


def test_folder_delete_moves_conversations_out(db: Database) -> None:
    folders = FolderRepository(db)
    conversations = ConversationRepository(db)
    folder = folders.create("Research")
    conversation = conversations.create("T", folder_id=folder.id)
    conversations.clear_folder(folder.id)
    folders.delete(folder.id)
    assert conversations.get(conversation.id).folder_id is None
    assert folders.list() == []


def test_settings_roundtrip(db: Database) -> None:
    repo = SettingRepository(db)
    repo.set("ui.theme", "dawn")
    repo.set_many({"ui.language": "en", "ai.max_tokens": 2048})
    assert repo.get("ui.theme") == "dawn"
    assert repo.all()["ai.max_tokens"] == 2048
    repo.delete(["ui.theme"])
    assert repo.get("ui.theme") is None


def test_folder_validation(db: Database) -> None:
    with pytest.raises(ValueError):
        FolderRepository(db).create("   ")


def test_project_repository(db: Database) -> None:
    projects = ProjectRepository(db)
    project = projects.create("Sandbox", description="generated code")
    assert projects.list()[0].id == project.id
    projects.delete(project.id)
    assert projects.list() == []
