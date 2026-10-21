"""Persona/profile files and the Output Studio backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.services.outputs import OutputService, detect_kind, detect_language


# --------------------------------------------------------------------- persona
def test_profile_file_is_created_and_editable(ctx) -> None:
    path = ctx.persona.ensure_profile()
    assert path.exists()
    assert "دربارهٔ من" in path.read_text(encoding="utf-8")

    ctx.persona.write_profile("# Me\n\n- Name: Nima\n- Role: Backend engineer\n")
    assert "Nima" in ctx.persona.read_profile()
    assert path.read_text(encoding="utf-8").startswith("# Me")
    # Saved atomically: no temporary file left behind.
    assert not list(path.parent.glob("*.tmp"))


def test_profile_import(ctx, tmp_path: Path) -> None:
    source = tmp_path / "profile.md"
    source.write_text("- Name: Imported\n", encoding="utf-8")
    ctx.persona.import_profile(source)
    assert "Imported" in ctx.persona.read_profile()


def test_placeholder_profile_is_ignored_in_prompts(ctx) -> None:
    ctx.persona.ensure_profile()
    assert ctx.persona.build_system_block() == ""
    ctx.persona.write_profile("- Name: Real person\n- Domain: compilers\n")
    assert "Real person" in ctx.persona.build_system_block()


def test_persona_save_validation_and_prompt(ctx) -> None:
    config = ctx.persona.save(enabled=True, text="Be a terse compiler expert.", tone="concise",
                              detail="brief", language="fa")
    assert config.enabled is True
    assert ctx.settings.get("ai.tone") == "concise"
    block = ctx.persona.build_system_block()
    assert "terse compiler expert" in block
    assert "tone: concise" in block
    assert "detail: brief" in block
    assert "Persian" in block

    with pytest.raises(ValidationError):
        ctx.persona.save(enabled=True, text="", tone="sassy", detail="brief", language="fa")
    with pytest.raises(ValidationError):
        ctx.persona.save(enabled=True, text="", tone="precise", detail="huge", language="fa")
    with pytest.raises(ValidationError):
        ctx.persona.save(enabled=True, text="", tone="precise", detail="brief", language="klingon")


def test_disabled_persona_still_uses_profile(ctx) -> None:
    ctx.persona.save(enabled=False, text="ignored", tone="precise", detail="balanced", language="auto")
    ctx.persona.write_profile("- Name: Still used\n")
    block = ctx.persona.build_system_block()
    assert "ignored" not in block
    assert "Still used" in block


def test_persona_stored_separately_from_memory(ctx) -> None:
    ctx.memory.add("A remembered fact", scope="global")
    ctx.persona.save(enabled=True, text="Persona text", tone="friendly", detail="balanced", language="auto")
    assert [m.content for m in ctx.memory.list("global")] == ["A remembered fact"]
    assert "Persona text" not in json.dumps([m.content for m in ctx.memory.list("global")])


# --------------------------------------------------------------------- outputs
def test_output_create_update_revision_restore(ctx) -> None:
    service: OutputService = ctx.outputs
    entry = service.create("notes.md", "# First")
    assert entry.kind == "markdown"
    assert entry.language == "markdown"
    assert entry.revision_count == 0

    updated = service.update(entry.id, content="# Second")
    assert updated.content == "# Second"
    revisions = service.revisions(entry.id)
    assert len(revisions) == 1
    assert revisions[0].content == "# First"

    service.update(entry.id, content="# Third")
    assert len(service.revisions(entry.id)) == 2

    restored = service.restore(entry.id, revisions[0].id)
    assert restored.content == "# First"
    # Restoring kept the replaced content as a new revision.
    assert any(rev.content == "# Third" for rev in service.revisions(entry.id))


def test_output_kind_detection() -> None:
    assert detect_kind("main.py") == "code"
    assert detect_kind("data.json") == "json"
    assert detect_kind("README.md") == "markdown"
    assert detect_language("main.py") == "python"
    assert detect_language("app.tsx") == "tsx"
    assert detect_language("unknown.zzz") == "text"


def test_output_validation(ctx) -> None:
    with pytest.raises(ValidationError):
        ctx.outputs.create("  ")
    with pytest.raises(ValidationError):
        ctx.outputs.create("x.txt", kind="binary")
    with pytest.raises(NotFoundError):
        ctx.outputs.get("missing")
    with pytest.raises(NotFoundError):
        ctx.outputs.update("missing", content="x")


def test_output_diff_and_no_change_guard(ctx) -> None:
    entry = ctx.outputs.create("code.py", "print('a')\nprint('b')\n")
    ctx.outputs.update(entry.id, content="print('a')\nprint('c')\n")
    result = ctx.outputs.diff(entry.id)
    assert result.has_changes
    assert result.added == 1 and result.removed == 1
    assert "-print('b')" in result.unified
    assert "+print('c')" in result.unified

    # Saving identical content must not create a revision.
    count = len(ctx.outputs.revisions(entry.id))
    ctx.outputs.update(entry.id, content="print('a')\nprint('c')\n")
    assert len(ctx.outputs.revisions(entry.id)) == count


def test_output_save_to_disk_and_import(ctx, tmp_path: Path) -> None:
    entry = ctx.outputs.create("hello.py", "print('hi')\n")
    path = ctx.outputs.save_to_file(entry.id)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "print('hi')\n"
    assert path.parent == ctx.paths.outputs_dir

    explicit = tmp_path / "custom.py"
    assert ctx.outputs.save_to_file(entry.id, explicit) == explicit
    assert explicit.read_text(encoding="utf-8") == "print('hi')\n"

    imported = ctx.outputs.import_file(explicit)
    assert imported.name == "custom.py"
    assert imported.content == "print('hi')\n"
    assert imported.language == "python"


def test_json_helpers(ctx) -> None:
    ok, message = ctx.outputs.validate_json('{"a": 1}')
    assert ok and message == ""
    bad, message = ctx.outputs.validate_json("{oops}")
    assert not bad and "line" in message
    assert ctx.outputs.format_json('{"b":2,"a":1}') == '{\n  "b": 2,\n  "a": 1\n}'
    with pytest.raises(ValidationError):
        ctx.outputs.format_json("{")


def test_outputs_are_listed_per_conversation(ctx) -> None:
    conversation = ctx.conversations.create("Outputs", select=False)
    ctx.outputs.create("one.txt", "1", conversation_id=conversation.id)
    ctx.outputs.create("two.txt", "2")
    linked = ctx.outputs.list(conversation.id)
    assert [entry.name for entry in linked] == ["one.txt"]
    assert len(ctx.outputs.list()) == 2
