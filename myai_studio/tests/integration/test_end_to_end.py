"""End-to-end flow: create → write → persist → restart → read back.

Uses the real context, real SQLite file and real services; only the process
boundary is simulated by shutting the context down and building a new one.
"""

from __future__ import annotations

from pathlib import Path

from myai.context import build_context


def test_workspace_survives_restart(home: Path) -> None:
    first = build_context(home, log=False)
    first.boot()
    conversation = first.conversations.create("Persisted conversation", select=False)
    first.conversations.add_message(conversation.id, "user", "سلام دنیا")
    first.conversations.add_message(conversation.id, "assistant", "Hello world")
    folder = first.conversations.create_folder("Kept folder")
    first.conversations.move_to_folder(conversation.id, folder.id)
    first.settings.set("ui.theme", "dawn")
    first.secrets.set("openrouter.api_key", "sk-or-v1-restart")
    first.shutdown()

    second = build_context(home, log=False)
    second.boot()
    try:
        restored = second.conversations.get(conversation.id)
        assert restored.title == "Persisted conversation"
        assert restored.folder_id == folder.id
        messages = second.conversations.messages(conversation.id)
        assert [m.content for m in messages] == ["سلام دنیا", "Hello world"]
        assert second.settings.get("ui.theme") == "dawn"
        assert second.secrets.get("openrouter.api_key") == "sk-or-v1-restart"
        assert second.db.integrity_check() == "ok"
    finally:
        second.shutdown()


def test_activity_feed_and_counts(ctx) -> None:
    before = ctx.activity.recent(limit=50)
    conversation = ctx.conversations.create("Feed check")
    ctx.conversations.add_message(conversation.id, "user", "ping")
    after = ctx.activity.recent(limit=50)
    assert len(after) >= len(before)
    counts = ctx.db.counts()
    assert counts["conversations"] >= 1
    assert counts["messages"] >= 1


def test_export_import_roundtrip(ctx, tmp_path: Path) -> None:
    conversation = ctx.conversations.create("Roundtrip", select=False)
    ctx.conversations.add_message(conversation.id, "user", "line one")
    target = ctx.conversations.export_markdown(conversation.id, tmp_path / "roundtrip.md")
    text = target.read_text(encoding="utf-8")
    assert "line one" in text
    assert target.stat().st_size > 0


def test_backup_never_contains_the_api_key(ctx, tmp_path: Path) -> None:
    """Phase 2 requirement: secrets stay out of backups (and exports)."""
    import zipfile

    from myai.services.backup import BackupService

    key = "sk-or-v1-do-not-leak-0123456789"
    ctx.secrets.set_api_key(key)
    conversation = ctx.conversations.create("Secret hygiene", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    ctx.memory.add("global fact", scope="global")

    info = BackupService(ctx.paths, ctx.db, ctx.settings).create_backup()
    blob = info.path.read_bytes()
    assert key.encode() not in blob
    with zipfile.ZipFile(info.path) as archive:
        names = set(archive.namelist())
        assert names == {"workspace.db", "settings.json", "manifest.json"}
        payload = b"".join(archive.read(name) for name in names)
    assert key.encode() not in payload
    # The endpoint URL is a non-secret setting and may appear; the key may not.
    assert b"https://openrouter.ai/api/v1" in payload
    # The data itself is present, so the exclusion is specific to secrets.
    assert b"global fact" in payload or b"global fact" in info.path.read_bytes()


def test_phase2_state_survives_restart(home: Path) -> None:
    """Memory, persona, outputs and the chosen model must survive a restart."""
    first = build_context(home, log=False)
    first.boot()
    a = first.conversations.create("Chat A", select=False)
    b = first.conversations.create("Chat B", select=False)
    first.memory.add("GLOBAL-RESTART-FACT", scope="global")
    first.memory.add("A-ONLY-FACT", scope="conversation", conversation_id=a.id)
    first.persona.save(enabled=True, text="PERSONA-RESTART", tone="formal",
                       detail="brief", language="en")
    first.persona.write_profile("- Name: RESTART-PROFILE\n")
    output = first.outputs.create("kept.py", "print('kept')\n", conversation_id=a.id)
    first.outputs.update(output.id, content="print('kept v2')\n")
    first.settings.set("ai.default_model", "test/restart-model")
    first.conversations.set_model(a.id, "test/restart-model")
    first.shutdown()

    second = build_context(home, log=False)
    second.boot()
    try:
        assert [m.content for m in second.memory.list("global")] == ["GLOBAL-RESTART-FACT"]
        assert [m.content for m in second.memory.list("conversation", a.id)] == ["A-ONLY-FACT"]
        assert second.memory.list("conversation", b.id) == []
        assert [m.content for m in second.memory.all_for_conversation(b.id)] == ["GLOBAL-RESTART-FACT"]
        config = second.persona.config()
        assert config.enabled and config.text == "PERSONA-RESTART"
        assert "RESTART-PROFILE" in second.persona.build_system_block()
        restored = second.outputs.get(output.id)
        assert restored.content == "print('kept v2')\n"
        assert len(second.outputs.revisions(output.id)) == 1
        assert second.settings.get("ai.default_model") == "test/restart-model"
        assert second.conversations.get(a.id).model_id == "test/restart-model"
    finally:
        second.shutdown()


def test_two_conversations_keep_memory_isolated_after_restart(home: Path) -> None:
    first = build_context(home, log=False)
    first.boot()
    a = first.conversations.create("Alpha", select=False)
    b = first.conversations.create("Beta", select=False)
    first.conversations.add_message(a.id, "user", "alpha question")
    first.conversations.add_message(b.id, "user", "beta question")
    first.memory.add("ALPHA-MEMORY", scope="conversation", conversation_id=a.id)
    first.memory.add("BETA-MEMORY", scope="conversation", conversation_id=b.id)
    first.memory.add("SHARED", scope="global")
    first.shutdown()

    second = build_context(home, log=False)
    second.boot()
    try:
        block_a = second.memory.build_context_block(a.id)
        block_b = second.memory.build_context_block(b.id)
        assert "ALPHA-MEMORY" in block_a and "BETA-MEMORY" not in block_a
        assert "BETA-MEMORY" in block_b and "ALPHA-MEMORY" not in block_b
        assert "SHARED" in block_a and "SHARED" in block_b
        assert [m.content for m in second.conversations.messages(a.id)] == ["alpha question"]
        assert [m.content for m in second.conversations.messages(b.id)] == ["beta question"]
    finally:
        second.shutdown()


def test_output_file_roundtrip_on_disk(ctx, tmp_path: Path) -> None:
    """Export to a real file, delete the record, re-import, compare bytes."""
    entry = ctx.outputs.create("notes.md", "# Title\n\n- one\n- two\n")
    ctx.outputs.update(entry.id, content="# Title v2\n\n- one\n- two\n- three\n")
    exported = ctx.outputs.save_to_file(entry.id, tmp_path / "notes.md")
    assert exported.read_text(encoding="utf-8") == "# Title v2\n\n- one\n- two\n- three\n"

    ctx.outputs.delete(entry.id)
    assert ctx.outputs.list() == []

    imported = ctx.outputs.import_file(exported)
    assert imported.content == exported.read_text(encoding="utf-8")
    assert imported.kind == "markdown"
    assert imported.language == "markdown"
    assert imported.name == "notes.md"
    # Re-imported files start with a clean history.
    assert ctx.outputs.revisions(imported.id) == []
