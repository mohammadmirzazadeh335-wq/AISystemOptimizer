"""The file-creation and project-search tools added after Phase 5."""

from __future__ import annotations

from pathlib import Path

import pytest

from myai.core.errors import ToolError, ValidationError
from myai.services.projects import ProjectService
from myai.services.tools import ToolContext, ToolDenied, registry


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "src" / "util.py").write_text("def helper():\n    return 'NEEDLE'\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\nneedle in docs\n", encoding="utf-8")
    return root


@pytest.fixture()
def tctx(ctx, project_dir: Path) -> ToolContext:  # noqa: ANN001
    projects = ProjectService(ctx.paths, ctx.settings)
    return ToolContext(projects=projects, project=projects.open_folder(project_dir), settings=ctx.settings)


def run(tool_id: str, arguments: dict, context: ToolContext):  # noqa: ANN201
    return registry().execute(tool_id, arguments, context, confirm=lambda *_: True)


def test_tools_are_registered_with_the_right_risk() -> None:
    reg = registry()
    assert reg.get("search_files").risk == "read"
    assert reg.get("make_folder").risk == "write"
    assert reg.get("create_project").risk == "write"
    assert reg.get("create_project").requires_project is False
    assert reg.get("search_files").requires_project is True


def test_search_finds_matches_case_insensitively(tctx: ToolContext) -> None:
    result = run("search_files", {"query": "needle"}, tctx)
    assert result.ok
    assert "src/util.py:2" in result.output
    assert "README.md:2" in result.output
    assert result.data["count"] == 2


def test_search_honours_the_glob(tctx: ToolContext) -> None:
    result = run("search_files", {"query": "needle", "glob": "*.py"}, tctx)
    assert result.data["count"] == 1
    assert "README.md" not in result.output


def test_search_without_matches_says_so(tctx: ToolContext) -> None:
    result = run("search_files", {"query": "absent-token"}, tctx)
    assert result.ok and result.data["count"] == 0
    assert "No files" in result.output


def test_search_rejects_an_empty_query(tctx: ToolContext) -> None:
    with pytest.raises(ValidationError) as excinfo:
        run("search_files", {"query": "   "}, tctx)
    assert excinfo.value.message_key == "error.empty_search"


def test_make_folder_creates_nested_directories(tctx: ToolContext, project_dir: Path) -> None:
    result = run("make_folder", {"path": "packages/api/tests"}, tctx)
    assert result.ok
    assert (project_dir / "packages" / "api" / "tests").is_dir()


def test_make_folder_refuses_to_clobber_a_file(tctx: ToolContext) -> None:
    with pytest.raises(ValidationError):
        run("make_folder", {"path": "main.py"}, tctx)


def test_make_folder_blocks_traversal(tctx: ToolContext) -> None:
    with pytest.raises(ValidationError):
        run("make_folder", {"path": "../escape"}, tctx)


def test_create_project_makes_a_real_folder(ctx) -> None:  # noqa: ANN001
    context = ToolContext(projects=ProjectService(ctx.paths, ctx.settings))
    result = run("create_project", {"name": "new-app"}, context)
    assert result.ok
    root = ctx.paths.projects_dir / "new-app"
    assert root.is_dir()
    assert str(root) in result.output


def test_create_project_refuses_windows_reserved_names(ctx) -> None:  # noqa: ANN001
    context = ToolContext(projects=ProjectService(ctx.paths, ctx.settings))
    with pytest.raises(ValidationError) as excinfo:
        run("create_project", {"name": "CON"}, context)
    assert excinfo.value.message_key == "error.filename_reserved"


def test_write_tools_still_need_approval(tctx: ToolContext) -> None:
    with pytest.raises(ToolDenied):
        registry().execute("make_folder", {"path": "x"}, tctx)


def test_create_project_without_a_project_service_is_unavailable() -> None:
    from myai.services.tools import ToolUnavailable

    with pytest.raises(ToolUnavailable):
        registry().execute("create_project", {"name": "x"}, ToolContext(), confirm=lambda *_: True)


def test_unknown_tool_is_a_tool_error(tctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        run("nope", {}, tctx)
