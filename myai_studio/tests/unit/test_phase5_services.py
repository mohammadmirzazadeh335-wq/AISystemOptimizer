"""Phase 5 services: prompts, tasks, performance, plugins, media, web.

Every assertion here is about real data: rows that exist in SQLite, files that
exist on disk, numbers produced by the sampler, or an HTTP response handed back by
a mock transport. Nothing is stubbed at the service boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.core.paths import AppPaths
from myai.services.agent import AgentService
from myai.services.media import MediaService
from myai.services.openrouter import ChatResult, StreamStats
from myai.services.performance import PerformanceService, format_uptime
from myai.services.plugins import PluginService
from myai.services.projects import ProjectService
from myai.services.prompts import BUILTIN, PLUGIN_PREFIX, PromptService
from myai.services.runner import Runner
from myai.services.tasks import AGENT, CODE, TaskService
from myai.services.tools import ToolContext, registry
from myai.services.web import WebService, validate_url

# --------------------------------------------------------------------- prompts


def test_prompt_seed_is_idempotent_and_complete(ctx) -> None:
    service: PromptService = ctx.prompts
    service.seed()
    first = service.count()
    assert first >= 6
    assert {entry.source for entry in service.list()} == {BUILTIN}
    service.seed()
    assert service.count() == first, "seeding twice must not duplicate rows"
    assert service.categories()


def test_prompt_create_update_search_and_delete(ctx) -> None:
    service = ctx.prompts
    entry = service.create(
        "Explain a regex",
        "Explain this pattern step by step.",
        category="snippets",
        tags=["regex", "teaching"],
    )
    assert entry.source == "user"
    assert entry.tags == ("regex", "teaching") and isinstance(entry.tags, tuple)

    found = service.list("regex")
    assert [item.id for item in found] == [entry.id]
    assert [item.id for item in service.list("", "snippets")] == [entry.id]

    updated = service.update(entry.id, title="Explain a regexp", body="Step by step.", tags=["regex"])
    assert updated.title == "Explain a regexp"
    assert updated.category == "snippets", "an omitted field keeps its stored value"
    assert updated.tags == ("regex",)

    service.delete(entry.id)
    with pytest.raises(NotFoundError):
        service.get(entry.id)


@pytest.mark.parametrize(
    "title,body,key",
    [
        ("", "body", "prompts.title_required"),
        ("title", "", "prompts.body_required"),
        ("x" * 400, "body", "prompts.title_too_long"),
        ("ok", "x" * 20_001, "prompts.body_too_long"),
    ],
)
def test_prompt_validation_reports_a_translatable_key(ctx, title: str, body: str, key: str) -> None:
    with pytest.raises(ValidationError) as info:
        ctx.prompts.create(title, body)
    assert info.value.message_key == key


def test_prompt_touch_counts_uses_and_restore_defaults(ctx) -> None:
    service = ctx.prompts
    builtin = service.list()[0]
    assert builtin.uses == 0
    service.touch(builtin.id)
    service.touch(builtin.id)
    assert service.get(builtin.id).uses == 2

    # Deleting one built-in and restoring brings exactly it back.
    service.delete(builtin.id)
    before = service.count()
    added = service.restore_defaults()
    assert added == 1
    assert service.count() == before + 1
    assert service.restore_defaults() == 0


# ----------------------------------------------------------------------- tasks


def test_task_record_list_filter_and_summary(ctx) -> None:
    service: TaskService = ctx.tasks
    first = service.record(
        kind=AGENT,
        title="Refactor the runner",
        status="ok",
        detail="Done in three steps",
        model_id="meta/llama",
        project="/tmp/project",
        tool_count=4,
        duration_ms=2500,
        steps=[{"index": 1, "kind": "final", "text": "done", "ok": True}],
    )
    second = service.record(kind=CODE, title="python main.py", status="error", duration_ms=900)

    assert service.count() == 2
    assert [item.id for item in service.list(AGENT)] == [first.id]
    assert [item.id for item in service.list(CODE)] == [second.id]
    assert [item.id for item in service.list(search="runner")] == [first.id]
    assert service.get(first.id).steps[0]["text"] == "done"
    assert service.get(first.id).created_at is not None

    summary = service.summary()
    assert summary[AGENT] == 1 and summary[CODE] == 1
    assert summary["ok"] == 1 and summary["error"] == 1

    service.delete(second.id)
    assert service.count() == 1
    assert service.clear(AGENT) == 1
    assert service.count() == 0


def test_task_rejects_unknown_kind_and_empty_text(ctx) -> None:
    with pytest.raises(ValidationError):
        ctx.tasks.record(kind="shell", title="rm -rf", status="ok")
    entry = ctx.tasks.record(kind=AGENT, title="   ", status="ok")
    assert entry.title == "(no task text)"


@dataclass
class _FakeTool:
    tool_id: str = "read_file"
    ok: bool = True
    error: str = ""


@dataclass
class _FakeStep:
    index: int = 1
    kind: str = "tool"
    text: str = "read_file"
    tool: _FakeTool | None = field(default_factory=_FakeTool)


@dataclass
class _FakeRun:
    task: str = "Summarise the repo"
    status: str = "ok"
    final_text: str = "Here is the summary"
    model_id: str = "meta/llama"
    project: str = "/tmp/repo"
    duration_ms: int = 1200
    tool_count: int = 1
    steps: list = field(default_factory=lambda: [_FakeStep()])


def test_agent_recorder_adapter_persists_a_real_run(ctx) -> None:
    entry = ctx.tasks.record_agent_run(_FakeRun())
    assert entry.kind == AGENT
    assert entry.title == "Summarise the repo"
    assert entry.status == "ok"
    assert entry.tool_count == 1
    assert entry.project == "/tmp/repo"
    assert entry.steps[0]["tool"] == "read_file"
    assert entry.steps[0]["ok"] is True


class _AnsweringClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[dict] = []

    def stream_chat(self, **kwargs):  # noqa: ANN201
        self.requests.append(kwargs)
        return ChatResult(text=self.text, stats=StreamStats(completion_tokens=2, total_tokens=5))


class _ChatShim:
    def __init__(self, client) -> None:  # noqa: ANN001
        self._client = client

    def client(self):  # noqa: ANN201
        return self._client


def test_a_finished_agent_run_becomes_a_real_task_row(ctx, tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    (project_root / "app.py").write_text("print(1)\n", encoding="utf-8")
    projects = ProjectService(ctx.paths, ctx.settings)
    tool_context = ToolContext(
        projects=projects,
        project=projects.open_folder(project_root),
        runner=Runner(),
        memory=ctx.memory,
        outputs=ctx.outputs,
        settings=ctx.settings,
        secrets=ctx.secrets,
    )
    client = _AnsweringClient("The file prints one.")
    agent = AgentService(
        chat=_ChatShim(client),  # type: ignore[arg-type]
        tools=registry(),
        settings=ctx.settings,
        bus=ctx.bus,
        activity=ctx.activity,
    )
    agent.set_recorder(ctx.tasks.record_agent_run)

    run = agent.run("What does app.py print?", model_id="test/model", context=tool_context,
                    project=str(project_root))

    rows = ctx.tasks.list(AGENT)
    assert len(rows) == 1
    row = rows[0]
    assert row.title == "What does app.py print?"
    assert row.status == run.status == "ok"
    assert row.detail.startswith("The file prints one.")
    assert row.project == str(project_root)
    assert row.model_id == "test/model"
    assert row.duration_ms >= 0
    assert any(step["kind"] == "final" for step in row.steps)


def test_a_failing_recorder_does_not_break_the_run(ctx, monkeypatch) -> None:
    def boom(_run):  # noqa: ANN001
        raise RuntimeError("disk full")

    agent = AgentService(
        chat=_ChatShim(_AnsweringClient("done")),  # type: ignore[arg-type]
        tools=registry(),
        settings=ctx.settings,
        bus=ctx.bus,
        activity=ctx.activity,
    )
    agent.set_recorder(boom)
    projects = ProjectService(ctx.paths, ctx.settings)
    context = ToolContext(
        projects=projects,
        project=None,
        runner=Runner(),
        memory=ctx.memory,
        outputs=ctx.outputs,
        settings=ctx.settings,
        secrets=ctx.secrets,
    )
    run = agent.run("Say done", model_id="test/model", context=context)
    assert run.status == "ok", "a broken persistence sink must not fail the agent"


# ----------------------------------------------------------------- performance


def test_performance_snapshot_uses_injected_clocks_and_reader(tmp_path: Path) -> None:
    home = tmp_path / "ws"
    (home / "logs").mkdir(parents=True)
    (home / "logs" / "app.log").write_bytes(b"x" * 1000)
    (home / "data.bin").write_bytes(b"y" * 2048)

    cpu = iter([10.0, 10.5])
    wall = iter([100.0, 102.0])
    service = PerformanceService(
        AppPaths(home=home).ensure(),
        status_reader=lambda: (5_000_000, 8_000_000_000, 6_000_000_000),
        cpu_clock=lambda: next(cpu),
        wall_clock=lambda: next(wall),
        started_at=90.0,
    )
    snapshot = service.snapshot()
    assert snapshot.cpu_percent == pytest.approx(25.0), "0.5s CPU over 2s wall = 25%"
    assert snapshot.rss_bytes == 5_000_000
    assert snapshot.threads >= 1
    assert snapshot.uptime_seconds == pytest.approx(12.0)
    assert snapshot.workspace_files == 2
    assert snapshot.logs_bytes == 1000
    assert snapshot.memory_used_ratio == pytest.approx(0.25)
    assert snapshot.disk_total and snapshot.disk_free is not None


def test_performance_reports_missing_values_instead_of_zero(tmp_path: Path) -> None:
    home = tmp_path / "ws"
    home.mkdir()
    service = PerformanceService(
        AppPaths(home=home).ensure(),
        status_reader=lambda: (None, None, None),
        cpu_clock=lambda: 1.0,
        wall_clock=lambda: 1.0,
    )
    snapshot = service.snapshot()
    assert snapshot.cpu_percent is None, "no elapsed time means no percentage"
    assert snapshot.rss_bytes is None
    assert snapshot.memory_used_ratio is None
    assert service.home == home


def test_format_uptime_shapes() -> None:
    assert format_uptime(9) == "9s"
    assert format_uptime(75) == "1m 15s"
    assert format_uptime(3 * 3600 + 61) == "3h 01m"


# --------------------------------------------------------------------- plugins


def _write_plugin(root: Path, name: str, manifest: dict) -> Path:
    folder = root / "plugins" / name
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def _manifest(**overrides) -> dict:
    data = {
        "id": "team-pack",
        "name": "Team pack",
        "version": "1.0.0",
        "kind": "prompt_pack",
        "permissions": ["prompts.write"],
        "prompts": [{"title": "Triage a bug", "body": "Reproduce, isolate, fix.", "category": "debug"}],
    }
    data.update(overrides)
    return data


def test_plugin_example_is_written_disabled_and_can_be_enabled(ctx) -> None:
    service: PluginService = ctx.plugins
    folder = service.write_example()
    assert (folder / "plugin.json").is_file()

    plugins = service.discover()
    assert [item.id for item in plugins] == ["example-prompt-pack"]
    example = plugins[0]
    assert example.supported and not example.enabled
    assert len(example.prompts) == 2

    enabled, imported, kept, error = service.set_enabled(example.id, True)
    assert (enabled, imported, kept, error) == (True, 2, 0, "")
    stored = ctx.prompts.from_plugin(example.id)
    assert len(stored) == 2
    assert all(entry.source == f"{PLUGIN_PREFIX}{example.id}" for entry in stored)
    assert {entry.title for entry in stored} == {"Explain a stack trace", "Commit message"}

    # Editing one copy keeps it when the plugin is disabled again.
    edited = stored[0]
    ctx.prompts.update(edited.id, body="My own wording.")
    enabled, imported, kept, error = service.set_enabled(example.id, False)
    assert (enabled, imported, kept, error) == (False, 0, 1, "")
    remaining = ctx.prompts.from_plugin(example.id)
    assert [entry.id for entry in remaining] == [edited.id]
    assert service.enabled_ids() == []


def test_plugin_manifest_errors_are_specific(ctx) -> None:
    service = ctx.plugins
    root = service.ensure_folder()

    _write_plugin(root.parent, "no-manifest", {})
    (root.parent / "plugins" / "no-manifest" / "plugin.json").unlink()
    _write_plugin(root.parent, "broken", {})
    (root.parent / "plugins" / "broken" / "plugin.json").write_text("{not json", encoding="utf-8")
    _write_plugin(root.parent, "bad-id", _manifest(id="bad-id-ok"))
    (root.parent / "plugins" / "bad-id" / "plugin.json").write_text(
        json.dumps(_manifest(id="UPPER CASE")), encoding="utf-8"
    )
    _write_plugin(root.parent, "runner", _manifest(id="runner", kind="tool"))
    _write_plugin(root.parent, "perm", _manifest(id="perm", permissions=["filesystem.write"]))
    _write_plugin(root.parent, "empty", _manifest(id="empty", prompts=[]))
    _write_plugin(root.parent, "wrong-folder", _manifest(id="different-id"))

    by_id = {item.id: item for item in service.discover()}
    assert by_id["no-manifest"].error_key == "plugins.error_no_manifest"
    assert by_id["broken"].error_key == "plugins.error_bad_json"
    assert by_id["bad-id"].error_key == "plugins.error_bad_id"
    assert by_id["runner"].error_key == "plugins.error_code_plugins"
    assert by_id["perm"].error_key == "plugins.error_bad_permission"
    assert by_id["empty"].error_key == "plugins.error_no_prompts"
    assert by_id["wrong-folder"].error_key == "plugins.error_id_mismatch"
    assert not any(item.supported for item in by_id.values())

    enabled, _imported, _kept, error = service.set_enabled("runner", True)
    assert enabled is False and "code execution" in error.lower()


# ----------------------------------------------------------------------- media


def test_media_lists_only_supported_files_and_deletes_inside_outputs(ctx) -> None:
    service: MediaService = ctx.media
    images = ctx.paths.images_dir
    (images / "shot.png").write_bytes(b"png")
    (images / "notes.txt").write_text("ignore me", encoding="utf-8")
    videos = ctx.paths.videos_dir
    (videos / "clip.mp4").write_bytes(b"mp4")

    assert [item.name for item in service.images()] == ["shot.png"]
    assert [item.name for item in service.videos()] == ["clip.mp4"]
    assert service.count() == (1, 1)
    assert service.images_available is False and service.videos_available is False

    service.delete(images / "shot.png")
    assert service.images() == []
    outside = images.parent.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(NotFoundError):
        service.delete(outside)


# ------------------------------------------------------------------------- web


def _html_response(body: str, status: int = 200) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8"}, text=body)

    return httpx.MockTransport(handler)


PAGE = """
<html><head><title>A useful page</title><style>body{color:red}</style></head>
<body><nav>skip me</nav><h1>Heading</h1><p>First paragraph with <b>bold</b> text.</p>
<script>alert(1)</script><p>Second&nbsp;paragraph.</p></body></html>
"""


def test_web_fetch_extracts_title_and_text() -> None:
    service = WebService(transport=_html_response(PAGE))
    page = service.fetch("example.com/article")
    assert page.url == "https://example.com/article"
    assert page.title == "A useful page"
    assert "First paragraph with bold text." in page.text
    assert "Second paragraph." in page.text
    assert "alert(1)" not in page.text and "skip me" not in page.text
    assert "color:red" not in page.text
    assert page.status == 200 and page.bytes_received > 0
    assert page.words >= 5


def test_web_fetch_reports_http_errors() -> None:
    service = WebService(transport=_html_response("missing", status=404))
    with pytest.raises(ValidationError) as info:
        service.fetch("https://example.com/gone")
    assert info.value.message_key == "web.error_status"


def test_web_rejects_private_and_local_addresses() -> None:
    for url in ("http://localhost:8000/x", "http://127.0.0.1/", "http://192.168.1.5/", "file:///etc/passwd"):
        with pytest.raises(ValidationError):
            validate_url(url)
    assert validate_url("openrouter.ai/docs") == "https://openrouter.ai/docs"
    assert validate_url("https://example.com") == "https://example.com"


def test_web_service_declares_search_unavailable() -> None:
    service = WebService()
    assert service.search_available is False
    assert service.reading_available is True
