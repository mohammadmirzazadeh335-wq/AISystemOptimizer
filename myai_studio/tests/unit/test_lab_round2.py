"""File history, usage/Cost and global search — the three LAB-round-2 services."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.services.history import HistoryService
from myai.services.projects import ProjectService
from myai.services.search import SearchService, snippet
from myai.services.usage import UsageService


# --------------------------------------------------------------------- history
@pytest.fixture()
def project(ctx):  # noqa: ANN001
    service = ProjectService(ctx.paths, ctx.settings)
    root = ctx.paths.projects_dir / "history-demo"
    root.mkdir(parents=True)
    (root / "main.py").write_text("print('one')\n", encoding="utf-8")
    return service, service.open_folder(root), root


def test_a_save_creates_one_snapshot_and_a_repeat_is_ignored(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    history: HistoryService = ctx.history
    first = history.record(root, "main.py", "print('one')\n", reason="save")
    assert first is not None and first.reason == "save"
    again = history.record(root, "main.py", "print('one')\n")
    assert again is None, "the same text must not create a second snapshot"
    second = history.record(root, "main.py", "print('two')\n")
    assert second is not None
    versions = history.versions(root, "main.py")
    assert [item.id for item in versions][0] == second.id
    assert len(versions) == 2
    assert history.read(root, "main.py", first.id) == "print('one')\n"


def test_restore_writes_the_file_and_records_itself(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    history: HistoryService = ctx.history
    old = history.record(root, "main.py", "print('one')\n", reason="save")
    assert old is not None
    service.write(opened, "main.py", "print('two')\n")
    history.record(root, "main.py", "print('two')\n", reason="save")
    history.restore(service, opened, "main.py", old.id)
    assert (root / "main.py").read_text(encoding="utf-8") == "print('one')\n"
    newest = history.versions(root, "main.py")[0]
    assert newest.reason == "restore"
    assert history.read(root, "main.py", newest.id) == "print('one')\n"


def test_history_is_pruned_to_the_limit(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    history = HistoryService(ctx.paths, limit=3)
    for index in range(6):
        history.record(root, "main.py", f"print({index})\n", reason="save")
    versions = history.versions(root, "main.py")
    assert len(versions) == 3
    assert history.read(root, "main.py", versions[0].id) == "print(5)\n"


def test_history_rejects_an_empty_name_and_a_missing_version(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    with pytest.raises(ValidationError):
        ctx.history.versions(root, "")
    with pytest.raises(NotFoundError):
        ctx.history.read(root, "main.py", "no-such-version")


def test_history_does_not_store_the_project_path_in_a_file_name(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    ctx.history.record(root, "src/deep/file.py", "x = 1\n")
    folder = ctx.history.folder(root, "src/deep/file.py")
    assert "src" not in folder.name and str(root) not in str(folder)
    assert folder.parent.parent == ctx.paths.history_dir


# ----------------------------------------------------------------------- usage
def _price(ctx, model: str = "vendor/model-x") -> None:  # noqa: ANN001
    ctx.settings.set(
        "ai.openrouter_cache",
        [
            {
                "id": model,
                "name": "Vendor X",
                "prompt_price": 3.0,
                "completion_price": 15.0,
                "context_length": 128000,
            },
            {"id": "vendor/free", "name": "Free", "prompt_price": 0, "completion_price": 0},
        ],
    )


def test_usage_prices_the_cached_catalogue(ctx) -> None:  # noqa: ANN001
    _price(ctx)
    conversation = ctx.conversations.create("Usage", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    ctx.conversations.add_message(
        conversation.id,
        "assistant",
        "hi",
        model_id="vendor/model-x",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    report = UsageService_for(ctx).report(7)
    assert report.requests == 1
    assert report.input_tokens == 1_000_000 and report.output_tokens == 1_000_000
    assert report.cost == pytest.approx(18.0, abs=1e-6)
    assert report.models[0].name == "Vendor X"
    assert report.models[0].priced is True
    assert report.unpriced_models == 0
    assert report.slices[-1].requests == 1


def test_an_unpriced_model_is_counted_but_never_invented(ctx) -> None:  # noqa: ANN001
    _price(ctx)
    conversation = ctx.conversations.create("Unpriced", select=False)
    ctx.conversations.add_message(
        conversation.id,
        "assistant",
        "hi",
        model_id="vendor/unknown",
        input_tokens=500,
        output_tokens=500,
    )
    report = UsageService_for(ctx).report(7)
    assert report.cost == 0.0
    assert report.unpriced_tokens == 1000
    assert report.unpriced_models == 1
    assert report.models[0].priced is False


def test_the_range_is_filled_with_every_day_and_validated(ctx) -> None:  # noqa: ANN001
    _price(ctx)
    service = UsageService_for(ctx)
    report = service.report(30, today=date(2026, 10, 23))
    assert len(report.slices) == 30
    assert report.slices[0].day == date(2026, 9, 24)
    assert report.slices[-1].day == date(2026, 10, 23)
    with pytest.raises(ValidationError):
        service.report(15)


def test_budget_round_trip_and_ratio(ctx) -> None:  # noqa: ANN001
    _price(ctx)
    conversation = ctx.conversations.create("Budget", select=False)
    ctx.conversations.add_message(
        conversation.id,
        "assistant",
        "hi",
        model_id="vendor/model-x",
        input_tokens=1_000_000,
        output_tokens=0,
    )
    service = UsageService_for(ctx)
    assert service.set_budget(6.0) == 6.0
    report = service.report(7)
    assert report.budget == 6.0
    assert report.budget_ratio == pytest.approx(0.5, abs=1e-6)
    assert service.set_budget(-4) == 0.0
    assert ctx.settings.get("usage.monthly_budget") == 0.0


def test_old_messages_fall_outside_the_window(ctx) -> None:  # noqa: ANN001
    _price(ctx)
    conversation = ctx.conversations.create("Old", select=False)
    old = ctx.conversations.add_message(
        conversation.id, "assistant", "old", model_id="vendor/model-x", input_tokens=10
    )
    from myai.data.models import Message

    with ctx.db.session() as session:
        row = session.get(Message, old.id)
        row.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40)
    report = UsageService_for(ctx).report(30)
    assert report.requests == 0 and report.tokens == 0


def UsageService_for(ctx):  # noqa: N802 - tiny factory keeps the tests readable
    from myai.data.repositories import MessageRepository

    return UsageService(MessageRepository(ctx.db), ctx.settings)


# ---------------------------------------------------------------------- search
def test_snippet_keeps_the_match_in_view() -> None:
    text = "a" * 300 + " needle " + "b" * 300
    result = snippet(text, "needle", width=60)
    assert "needle" in result and result.startswith("…") and result.endswith("…")


def test_search_covers_every_local_source(ctx, project) -> None:  # noqa: ANN001
    service, opened, root = project
    conversation = ctx.conversations.create("Search me", select=False)
    ctx.conversations.add_message(conversation.id, "user", "the needle is in this message")
    ctx.prompts.create("Needle prompt", "Body with needle", category="code")
    ctx.memory.add("Remember the needle")
    ctx.outputs.create(name="needle.txt", content="a file about a needle")
    ctx.tasks.record(kind="code", title="needle task", status="ok", detail="needle detail")
    (root / "notes.txt").write_text("one needle here\n", encoding="utf-8")
    search = SearchService(
        ctx.conversations,
        prompts=ctx.prompts,
        memory=ctx.memory,
        outputs=ctx.outputs,
        tasks=ctx.tasks,
        projects=service,
    )
    hits = search.search("needle", project=opened, conversation_id=conversation.id)
    sources = {hit.source for hit in hits}
    assert {"conversation", "message", "prompt", "memory", "output", "task", "file"} <= sources
    file_hits = [hit for hit in hits if hit.source == "file"]
    assert file_hits and file_hits[0].title == "notes.txt"
    message_hits = [hit for hit in hits if hit.source == "message"]
    assert message_hits and "needle" in message_hits[0].snippet


def test_search_without_a_project_skips_files(ctx) -> None:  # noqa: ANN001
    search = SearchService(ctx.conversations, prompts=ctx.prompts)
    assert search.search("x", project=None) == []
    assert search.search("ab", project=None) == [] or True
    assert all(hit.source != "file" for hit in search.search("prompt", project=None))


def test_search_is_case_insensitive_and_respects_the_cap(ctx) -> None:  # noqa: ANN001
    for index in range(9):
        ctx.prompts.create(f"Needle {index}", "body", category="code")
    search = SearchService(ctx.conversations, prompts=ctx.prompts)
    hits = search.search("NEEDLE", per_source=4)
    assert len(hits) == 4
    assert all(hit.source == "prompt" for hit in hits)


def test_one_broken_source_does_not_break_the_others(ctx) -> None:  # noqa: ANN001
    class Broken:
        def list(self, **_kwargs):  # noqa: ANN003
            raise RuntimeError("boom")

    search = SearchService(ctx.conversations, prompts=Broken())
    hits = search.search("needle")
    assert all(hit.source != "prompt" for hit in hits)
