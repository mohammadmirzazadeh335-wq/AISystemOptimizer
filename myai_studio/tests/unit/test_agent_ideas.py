"""The seven tools added to Agent Mode in the Windows-readiness round."""

from __future__ import annotations

from pathlib import Path

import pytest

from myai.core.errors import ToolError, ValidationError
from myai.services.projects import ProjectService
from myai.services.tools import ToolContext, ToolUnavailable, registry
from myai.services.web import WebPage


class FakeWeb:
    """A page reader with no sockets: the tool still goes through WebService API."""

    def __init__(self, text: str = "Hello from the page") -> None:
        self.calls: list[str] = []
        self._text = text

    def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        return WebPage(
            url=url,
            final_url=url,
            title="Example page",
            text=self._text,
            status=200,
            content_type="text/html",
            bytes_received=len(self._text),
            elapsed_ms=12,
        )


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text(
        "def main():\n    # TODO: wire the CLI\n    return 0\n\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (root / "src" / "util.py").write_text(
        "def helper():\n    return 1\n\n# FIXME broken edge case\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Demo\n\nA tiny project.\n", encoding="utf-8")
    (root / "notes.txt").write_text("TODO write the docs\n", encoding="utf-8")
    return root


@pytest.fixture()
def tctx(ctx, project_dir: Path) -> ToolContext:  # noqa: ANN001
    projects = ProjectService(ctx.paths, ctx.settings)
    return ToolContext(
        projects=projects,
        project=projects.open_folder(project_dir),
        settings=ctx.settings,
        web=FakeWeb(),
    )


def run(tool_id: str, arguments: dict, context: ToolContext):  # noqa: ANN201
    return registry().execute(tool_id, arguments, context, confirm=lambda *_: True)


def test_the_registry_grew_by_exactly_seven() -> None:
    reg = registry()
    for tool_id, risk in (
        ("project_map", "read"),
        ("find_files", "read"),
        ("read_lines", "read"),
        ("scan_todos", "read"),
        ("diff_files", "read"),
        ("apply_patch", "write"),
        ("fetch_url", "network"),
    ):
        spec = reg.get(tool_id)
        assert spec is not None, tool_id
        assert spec.risk == risk
    # 22 after the tool round, plus the six creative generators (chart, PDF,
    # resize, contact sheet, zip, probe).
    assert len(reg.specs()) == 28


def test_project_map_counts_real_languages_and_entry_points(tctx: ToolContext) -> None:
    result = run("project_map", {}, tctx)
    assert result.ok
    assert result.data["files"] == 4
    assert result.data["languages"]["python"] == 2
    assert "main.py" in result.output
    assert "README.md" in result.output
    assert "lines" in result.output


def test_find_files_matches_the_glob_and_reports_nothing(tctx: ToolContext) -> None:
    result = run("find_files", {"pattern": "*.py"}, tctx)
    assert result.data["count"] == 2
    assert "src/util.py" in result.output
    empty = run("find_files", {"pattern": "*.rs"}, tctx)
    assert empty.data["count"] == 0 and "No files match" in empty.output


def test_find_files_refuses_to_escape_the_project(tctx: ToolContext) -> None:
    with pytest.raises(ValidationError):
        run("find_files", {"pattern": "../*.py"}, tctx)


def test_read_lines_numbers_only_the_requested_window(tctx: ToolContext) -> None:
    result = run("read_lines", {"path": "main.py", "start": 2, "end": 2}, tctx)
    assert "2 |" in result.output
    assert "TODO: wire the CLI" in result.output
    assert "1 |" not in result.output
    # Beyond EOF is a readable answer, not a crash.
    beyond = run("read_lines", {"path": "main.py", "start": 999}, tctx)
    assert "does not exist" in beyond.output


def test_scan_todos_finds_every_tag(tctx: ToolContext) -> None:
    result = run("scan_todos", {}, tctx)
    assert result.data["by_tag"] == {"TODO": 2, "FIXME": 1}
    assert "main.py:2" in result.output and "FIXME" in result.output


def test_diff_files_shows_a_real_diff_and_equality(tctx: ToolContext) -> None:
    changed = run("diff_files", {"path_a": "src/util.py", "path_b": "README.md"}, tctx)
    assert changed.data["identical"] is False
    assert "--- src/util.py" in changed.output and "+++ README.md" in changed.output
    same = run("diff_files", {"path_a": "README.md", "path_b": "README.md"}, tctx)
    assert same.data["identical"] is True


def test_apply_patch_writes_the_file_and_can_be_diffed_back(tctx: ToolContext) -> None:
    patch = """@@ -1,2 +1,2 @@
 def helper():
-    return 1
+    return 2
"""
    result = run("apply_patch", {"path": "src/util.py", "patch": patch}, tctx)
    assert result.data["hunks"] == 1
    text = tctx.projects.read(tctx.project, "src/util.py").text
    assert "return 2" in text
    assert "# FIXME broken edge case" in text


def test_a_failed_patch_leaves_the_file_untouched(tctx: ToolContext) -> None:
    before = tctx.projects.read(tctx.project, "src/util.py").text
    patch = """@@ -1,2 +1,2 @@
 def helper():
-    return 999
+    return 0
"""
    with pytest.raises(ValidationError):
        run("apply_patch", {"path": "src/util.py", "patch": patch}, tctx)
    assert tctx.projects.read(tctx.project, "src/util.py").text == before


def test_apply_patch_requires_the_write_confirmation(tmp_path: Path, ctx) -> None:  # noqa: ANN001
    projects = ProjectService(ctx.paths, ctx.settings)
    (tmp_path / "f.txt").write_text("one\n", encoding="utf-8")
    context = ToolContext(projects=projects, project=projects.open_folder(tmp_path), settings=ctx.settings)
    spec = registry().get("apply_patch")
    from myai.services.tools import ToolDenied

    with pytest.raises(ToolDenied):
        registry().execute(
            "apply_patch",
            {"path": "f.txt", "patch": "@@ -1 +1 @@\n-one\n+two\n"},
            context,
            require_confirmation=True,
        )
    assert spec.risk == "write"


def test_fetch_url_reads_the_page_and_records_the_call(tctx: ToolContext) -> None:
    tctx.settings.set("agent.allow_network", True)
    result = run("fetch_url", {"url": "https://example.com/doc"}, tctx)
    assert result.ok
    assert "Example page" in result.output and "Hello from the page" in result.output
    assert result.data["status"] == 200
    assert tctx.web.calls == ["https://example.com/doc"]


def test_fetch_url_is_unavailable_without_network_permission(tctx: ToolContext) -> None:
    tctx.settings.set("agent.allow_network", False)
    spec = registry().get("fetch_url")
    assert spec.reason(tctx) is not None
    with pytest.raises(ToolUnavailable):
        run("fetch_url", {"url": "https://example.com"}, tctx)


def test_fetch_url_maps_a_socket_failure_to_a_tool_error(tctx: ToolContext) -> None:
    import httpx

    class Broken:
        def fetch(self, url: str):  # noqa: ANN201
            raise httpx.ConnectError("no route to host")

    tctx.settings.set("agent.allow_network", True)
    tctx.web = Broken()
    with pytest.raises(ToolError) as caught:
        run("fetch_url", {"url": "https://example.com"}, tctx)
    assert caught.value.message_key == "agent.web_failed"


def test_fetch_url_keeps_the_rejected_url_message(tctx: ToolContext) -> None:
    class Rejecting:
        def fetch(self, url: str):  # noqa: ANN201
            raise ValidationError("only http", message_key="web.only_http")

    tctx.settings.set("agent.allow_network", True)
    tctx.web = Rejecting()
    with pytest.raises(ValidationError) as caught:
        run("fetch_url", {"url": "file:///etc/passwd"}, tctx)
    assert caught.value.message_key == "web.only_http"
