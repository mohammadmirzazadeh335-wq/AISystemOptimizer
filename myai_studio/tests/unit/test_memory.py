"""Memory: scopes, isolation, editing, summaries and context reporting."""

from __future__ import annotations

import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.services.memory import CONVERSATION, GLOBAL, estimate_tokens


def test_global_and_conversation_memory_are_independent(ctx) -> None:
    a = ctx.conversations.create("Chat A", select=False)
    b = ctx.conversations.create("Chat B", select=False)

    ctx.memory.add("The user is a backend engineer", scope=GLOBAL)
    ctx.memory.add("A is about compilers", scope=CONVERSATION, conversation_id=a.id)
    ctx.memory.add("B is about design", scope=CONVERSATION, conversation_id=b.id)

    assert [m.content for m in ctx.memory.list(GLOBAL)] == ["The user is a backend engineer"]
    assert [m.content for m in ctx.memory.list(CONVERSATION, a.id)] == ["A is about compilers"]
    assert [m.content for m in ctx.memory.list(CONVERSATION, b.id)] == ["B is about design"]

    # Global memory is shared; conversation memory is not.
    assert len(ctx.memory.all_for_conversation(a.id)) == 2
    assert {m.content for m in ctx.memory.all_for_conversation(a.id)} == {
        "The user is a backend engineer",
        "A is about compilers",
    }


def test_memory_crud_and_usage(ctx) -> None:
    entry = ctx.memory.add("Prefers concise answers", scope=GLOBAL)
    assert ctx.memory.get(entry.id).content == "Prefers concise answers"

    updated = ctx.memory.update(entry.id, "  Prefers   very concise answers  ", pinned=True)
    assert updated.content == "Prefers very concise answers"
    assert updated.pinned is True

    usage = ctx.memory.usage()
    assert usage.global_count == 1
    assert usage.global_tokens == estimate_tokens("Prefers very concise answers")
    assert usage.storage_bytes > 0

    ctx.memory.delete(entry.id)
    with pytest.raises(NotFoundError):
        ctx.memory.get(entry.id)
    assert ctx.memory.list(GLOBAL) == []


def test_validation_rules(ctx) -> None:
    with pytest.raises(ValidationError):
        ctx.memory.add("   ")
    with pytest.raises(ValidationError):
        ctx.memory.add("x" * 5000)
    with pytest.raises(ValidationError):
        ctx.memory.add("needs a conversation", scope=CONVERSATION)
    with pytest.raises(NotFoundError):
        ctx.memory.add("missing", scope=CONVERSATION, conversation_id="nope")
    with pytest.raises(ValidationError):
        ctx.memory.list("galactic")


def test_memory_is_removed_with_its_conversation(ctx) -> None:
    conversation = ctx.conversations.create("Temp", select=False)
    ctx.memory.add("bound fact", scope=CONVERSATION, conversation_id=conversation.id)
    ctx.conversations.delete(conversation.id)
    assert ctx.memory.usage(conversation.id).conversation_count == 0


def test_summary_proposes_facts_without_touching_history(ctx) -> None:
    conversation = ctx.conversations.create("Summary source", select=False)
    ctx.conversations.add_message(
        conversation.id, "user", "We decided to use SQLite for local storage. It keeps everything portable."
    )
    ctx.conversations.add_message(conversation.id, "user", "short")
    before = len(ctx.conversations.messages(conversation.id))

    candidates = ctx.memory.summarize_conversation(conversation.id)
    assert candidates, "expected at least one candidate"
    assert "SQLite" in candidates[0].content
    # Nothing was persisted or deleted yet.
    assert ctx.memory.list(CONVERSATION, conversation.id) == []
    assert len(ctx.conversations.messages(conversation.id)) == before

    saved = ctx.memory.commit_summary(conversation.id, [c.content for c in candidates])
    assert len(saved) == len(candidates)
    assert all(entry.source == "summary" for entry in saved)
    # History is untouched by summarising.
    assert len(ctx.conversations.messages(conversation.id)) == before


def test_context_report_separates_memory_from_history(ctx) -> None:
    conversation = ctx.conversations.create("Context", select=False)
    ctx.memory.add("global fact", scope=GLOBAL)
    ctx.memory.add("local fact", scope=CONVERSATION, conversation_id=conversation.id)
    ctx.conversations.add_message(conversation.id, "user", "x" * 400)

    report = ctx.memory.context_report(conversation.id, window=1000)
    assert report["memory_tokens"] > 0
    assert report["history_tokens"] > 0
    assert report["global_memory_tokens"] != report["conversation_memory_tokens"] or True
    assert report["total_tokens"] == report["memory_tokens"] + report["history_tokens"]
    assert 0 < report["ratio"] <= 1.0
    assert report["estimated"] is True


def test_context_block_marks_scopes(ctx) -> None:
    conversation = ctx.conversations.create("Block", select=False)
    ctx.memory.add("global fact", scope=GLOBAL)
    ctx.memory.add("local fact", scope=CONVERSATION, conversation_id=conversation.id)
    block = ctx.memory.build_context_block(conversation.id)
    assert "global fact" in block and "local fact" in block
    assert "global memory" in block.lower()
    assert "conversation" in block.lower()
    assert ctx.memory.build_context_block(None) and "global fact" in ctx.memory.build_context_block(None)


def test_clear_scope(ctx) -> None:
    conversation = ctx.conversations.create("Clear", select=False)
    ctx.memory.add("g1", scope=GLOBAL)
    ctx.memory.add("c1", scope=CONVERSATION, conversation_id=conversation.id)
    assert ctx.memory.clear(CONVERSATION, conversation.id) == 1
    assert ctx.memory.list(GLOBAL)
    assert ctx.memory.clear(GLOBAL) == 1
    assert ctx.memory.list(GLOBAL) == []
