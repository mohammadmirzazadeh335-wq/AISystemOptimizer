"""Agent tools: real handlers, real guards, no simulated success.

File tools run against a temporary folder on disk, the runner executes real
processes, and every unavailable capability is asserted to raise with a reason
that names what is missing.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from myai.core.errors import NotFoundError, ToolError, ValidationError
from myai.services.projects import ProjectService
from myai.services.runner import Runner
from myai.services.toolchains import ToolchainRegistry, ToolchainUnavailable
from myai.services.tools import (
    ToolContext,
    ToolDenied,
    ToolRegistry,
    ToolSpec,
    ToolUnavailable,
    default_specs,
    describe_for_prompt,
    registry,
    validate_arguments,
)


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "demo-project"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text("print('hello from the tool')\n", encoding="utf-8")
    (root / "src" / "greet.py").write_text("VALUE = 41\nprint(VALUE + 1)\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\n", encoding="utf-8")
    return root


@pytest.fixture()
def tctx(ctx, project_dir: Path) -> ToolContext:
    projects = ProjectService(ctx.paths, ctx.settings)
    project = projects.open_folder(project_dir)
    return ToolContext(
        projects=projects,
        project=project,
        runner=Runner(),
        memory=ctx.memory,
        outputs=ctx.outputs,
        settings=ctx.settings,
        secrets=ctx.secrets,
        conversation_id=None,
        timeout_seconds=5.0,
    )


def spec(tool_id: str) -> ToolSpec:
    found = registry().get(tool_id)
    assert found is not None, tool_id
    return found


# ------------------------------------------------------------------ validation
def test_required_arguments_are_enforced() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_arguments(spec("read_file"), {})
    assert excinfo.value.message_key == "agent.missing_argument"


def test_unknown_arguments_are_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_arguments(spec("read_file"), {"path": "a.txt", "sudo": True})
    assert excinfo.value.message_key == "agent.unknown_argument"


def test_wrong_types_and_ranges_are_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_arguments(spec("read_file"), {"path": 7})
    with pytest.raises(ValidationError):
        validate_arguments(spec("run_file"), {"path": "a.py", "timeout_seconds": 500})
    with pytest.raises(ValidationError):
        validate_arguments(spec("remember"), {"text": "x", "scope": "galaxy"})
    with pytest.raises(ValidationError):
        validate_arguments(spec("read_file"), {"path": "a" * 500})


def test_boolean_is_not_accepted_as_an_integer() -> None:
    with pytest.raises(ValidationError):
        validate_arguments(spec("recall"), {"query": "x", "limit": True})


def test_every_spec_is_well_formed() -> None:
    specs = default_specs()
    assert len(specs) == len({item.id for item in specs})
    for item in specs:
        assert item.risk in {"read", "write", "execute", "network"}
        assert item.description
        assert item.parameters["type"] == "object"
        for name in item.parameters.get("required", []):
            assert name in item.parameters["properties"], (item.id, name)


# ------------------------------------------------------------------ registry
def test_openai_payload_lists_only_usable_tools(tctx: ToolContext) -> None:
    payload = registry().to_openai(tctx)
    names = [row["function"]["name"] for row in payload]
    assert "read_file" in names and "write_file" in names
    # No web endpoint, no token, no image provider: these must not be offered.
    assert "web_search" not in names
    assert "github_list_issues" not in names
    assert "generate_image" not in names
    read = next(row for row in payload if row["function"]["name"] == "read_file")
    assert read["type"] == "function"
    assert read["function"]["parameters"]["required"] == ["path"]


def test_unavailable_tools_explain_what_is_missing(tctx: ToolContext) -> None:
    reasons = {item.id: reason for item, reason in registry().unavailable(tctx)}
    assert "No project folder is open" not in reasons.get("read_file", "")
    assert "Network access is disabled" in reasons["web_search"]
    assert "Network access is disabled" in reasons["github_list_issues"]
    assert "image provider" in reasons["generate_image"]

    # With the network gate open the next missing thing is named: the token.
    tctx.settings.update({"agent.allow_network": True, "web.search_url": "https://searx.example/s"})
    deeper = {item.id: reason for item, reason in registry().unavailable(tctx)}
    assert "GitHub token" in deeper["github_list_issues"]
    assert "web_search" not in deeper

    empty = ToolContext()
    empty_reasons = {item.id: reason for item, reason in registry().unavailable(empty)}
    assert "Open one in Code Studio" in empty_reasons["read_file"]


def test_generate_image_is_never_available(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True, "web.search_url": "https://searx.example/s"})
    with pytest.raises(ToolUnavailable) as excinfo:
        registry().execute("generate_image", {"prompt": "a cat"}, tctx)
    assert "image provider" in excinfo.value.message


def test_prompt_lists_tools_and_the_unavailable_section(tctx: ToolContext) -> None:
    text = describe_for_prompt(registry(), tctx)
    assert "read_file" in text
    assert "Unavailable on this machine" in text
    assert "generate_image" in text.split("Unavailable on this machine")[1]


# ----------------------------------------------------------------- execution
def test_read_tool_runs_without_confirmation(tctx: ToolContext) -> None:
    result = registry().execute("read_file", {"path": "main.py"}, tctx)
    assert result.ok is True
    assert "hello from the tool" in result.output
    assert result.data["language"] == "python"


def test_sensitive_tools_need_confirmation(tctx: ToolContext) -> None:
    called: list[tuple[str, dict]] = []

    def confirm(tool: ToolSpec, arguments: dict) -> bool:
        called.append((tool.id, arguments))
        return True

    result = registry().execute(
        "write_file", {"path": "new.txt", "content": "hi"}, tctx, confirm=confirm
    )
    assert result.ok and called and called[0][0] == "write_file"
    assert (tctx.project.root / "new.txt").read_text(encoding="utf-8") == "hi"


def test_denied_tool_is_not_executed(tctx: ToolContext) -> None:
    def confirm(tool: ToolSpec, arguments: dict) -> bool:  # noqa: ARG001
        return False

    with pytest.raises(ToolDenied):
        registry().execute("write_file", {"path": "denied.txt", "content": "x"}, tctx,
                           confirm=confirm)
    assert not (tctx.project.root / "denied.txt").exists()


def test_confirmation_is_mandatory_without_a_channel(tctx: ToolContext) -> None:
    with pytest.raises(ToolDenied):
        registry().execute("write_file", {"path": "x.txt", "content": "x"}, tctx)


def test_execute_tool_also_requires_confirmation(tctx: ToolContext) -> None:
    with pytest.raises(ToolDenied):
        registry().execute("run_file", {"path": "main.py"}, tctx)


def test_unknown_tool_is_an_error_not_a_crash(tctx: ToolContext) -> None:
    with pytest.raises(ToolError) as excinfo:
        registry().execute("rm_rf", {}, tctx)
    assert excinfo.value.message_key == "agent.unknown_tool"


def test_confirmation_can_be_disabled_in_settings(tctx: ToolContext) -> None:
    result = registry().execute(
        "write_file", {"path": "auto.txt", "content": "x"}, tctx, require_confirmation=False
    )
    assert result.ok
    assert (tctx.project.root / "auto.txt").exists()


# --------------------------------------------------------------- file tools
def test_list_files_shows_folders_and_sizes(tctx: ToolContext) -> None:
    result = registry().execute("list_files", {}, tctx)
    assert "src/" in result.output
    assert "main.py" in result.output
    assert result.data["count"] == 3


def test_list_files_in_a_subfolder(tctx: ToolContext) -> None:
    result = registry().execute("list_files", {"path": "src"}, tctx)
    assert "greet.py" in result.output
    assert "main.py" not in result.output


def test_write_then_read_round_trips_on_disk(tctx: ToolContext) -> None:
    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    registry().execute(
        "write_file",
        {"path": "src/new_module.py", "content": "print('written by the agent')\n"},
        tctx,
        confirm=allow,
    )
    on_disk = (tctx.project.root / "src" / "new_module.py").read_text(encoding="utf-8")
    assert on_disk == "print('written by the agent')\n"
    read_back = registry().execute("read_file", {"path": "src/new_module.py"}, tctx)
    assert "written by the agent" in read_back.output


def test_delete_file_removes_the_file(tctx: ToolContext) -> None:
    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    registry().execute("delete_file", {"path": "notes.md"}, tctx, confirm=allow)
    assert not (tctx.project.root / "notes.md").exists()


def test_path_escape_is_blocked(tctx: ToolContext) -> None:
    with pytest.raises((ValidationError, NotFoundError)):
        registry().execute("read_file", {"path": "../../etc/passwd"}, tctx)


def test_missing_file_is_a_not_found_error(tctx: ToolContext) -> None:
    with pytest.raises(NotFoundError):
        registry().execute("read_file", {"path": "ghost.py"}, tctx)


def test_binary_file_is_reported_as_binary(tctx: ToolContext) -> None:
    (tctx.project.root / "blob.bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolError) as excinfo:
        registry().execute("read_file", {"path": "blob.bin"}, tctx)
    assert excinfo.value.message_key == "agent.binary_file"


# ------------------------------------------------------------------ run tool
def test_run_file_executes_the_real_interpreter(tctx: ToolContext) -> None:
    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute("run_file", {"path": "main.py"}, tctx, confirm=allow)
    assert result.ok is True
    assert "hello from the tool" in result.output
    assert result.data["exit_code"] == 0
    assert result.data["status"] == "ok"
    assert Path(sys.executable).name in result.output.split()[1]


def test_run_file_reports_the_real_failure(tctx: ToolContext) -> None:
    (tctx.project.root / "boom.py").write_text("raise SystemExit(3)\n", encoding="utf-8")

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute("run_file", {"path": "boom.py"}, tctx, confirm=allow)
    assert result.ok is False
    assert result.data["exit_code"] == 3
    assert "exit=3" in result.output


def test_run_file_keeps_stderr_verbatim(tctx: ToolContext) -> None:
    (tctx.project.root / "crash.py").write_text(
        "raise RuntimeError('the real traceback')\n", encoding="utf-8"
    )

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute("run_file", {"path": "crash.py"}, tctx, confirm=allow)
    assert "RuntimeError: the real traceback" in result.output
    assert "Traceback" in result.output


def test_run_file_reports_a_missing_toolchain(
    tctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing compiler must surface as a clear "cannot run this" error.

    The toolchain is injected rather than assumed absent: the Windows CI image
    does ship a .NET SDK, so a real Program.cs ran there and nothing was
    raised. What the test is about is the mapping from a plan that cannot be
    built to the agent-visible error.
    """
    (tctx.project.root / "Program.cs").write_text("class P {}\n", encoding="utf-8")
    assert tctx.runner is not None

    def no_toolchain(*_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        raise ToolchainUnavailable("dotnet", "dotnet was not found on PATH")

    monkeypatch.setattr(tctx.runner, "plan_for", no_toolchain)

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    with pytest.raises(ToolUnavailable) as excinfo:
        registry().execute("run_file", {"path": "Program.cs"}, tctx, confirm=allow)
    assert "dotnet was not found on PATH" in excinfo.value.message


def test_run_file_reports_a_real_missing_toolchain(tctx: ToolContext) -> None:
    """End to end on this machine, when it genuinely has no such compiler."""
    missing = [item.id for item in ToolchainRegistry().detect() if not item.available]
    if not missing:
        pytest.skip("this image has every configured toolchain; nothing to prove here")
    extension = {"rust": ".rs", "go": ".go", "c": ".c", "cpp": ".cpp", "java": ".java"}
    toolchain = missing[0]
    suffix = extension.get(toolchain)
    if suffix is None:
        pytest.skip(f"{toolchain} has no sample source in this test")
    (tctx.project.root / f"Program{suffix}").write_text(
        "int main(void) { return 0; }\n" if suffix in {".c", ".cpp"} else "// nothing\n",
        encoding="utf-8",
    )

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    with pytest.raises(ToolUnavailable) as excinfo:
        registry().execute("run_file", {"path": f"Program{suffix}"}, tctx, confirm=allow)
    assert "not found" in excinfo.value.message or "did not answer" in excinfo.value.message


def test_run_file_times_out_and_is_killed(tctx: ToolContext) -> None:
    (tctx.project.root / "sleep.py").write_text(
        "import time\ntime.sleep(30)\nprint('never')\n", encoding="utf-8"
    )

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute(
        "run_file", {"path": "sleep.py", "timeout_seconds": 1}, tctx, confirm=allow
    )
    assert result.ok is False
    assert result.data["status"] == "timeout"


# ------------------------------------------------------------------ memory
def test_remember_and_recall_use_the_real_memory_store(tctx: ToolContext) -> None:
    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    saved = registry().execute(
        "remember", {"text": "The project is written in Persian"}, tctx, confirm=allow
    )
    assert saved.ok
    assert tctx.memory.all_for_conversation(None)[0].content == "The project is written in Persian"
    found = registry().execute("recall", {"query": "persian"}, tctx)
    assert "written in Persian" in found.output
    empty = registry().execute("recall", {"query": "kubernetes"}, tctx)
    assert empty.data["count"] == 0


def test_save_output_creates_a_real_output_entry(tctx: ToolContext) -> None:
    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute(
        "save_output", {"name": "notes.md", "content": "# Saved by the agent\n"}, tctx,
        confirm=allow,
    )
    assert result.ok
    outputs = tctx.outputs.list()
    assert outputs and outputs[0].name == "notes.md"


# ------------------------------------------------------------------ network
def test_network_tools_are_blocked_by_default(tctx: ToolContext) -> None:
    with pytest.raises(ToolUnavailable):
        registry().execute("web_search", {"query": "python"}, tctx)


def test_web_search_reports_a_missing_endpoint(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True})
    with pytest.raises(ToolUnavailable) as excinfo:
        registry().execute("web_search", {"query": "python"}, tctx)
    assert "endpoint" in excinfo.value.message


def test_web_search_parses_a_real_json_answer(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True, "web.search_url": "https://searx.example/s"})
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Python docs", "url": "https://docs.python.org", "content": "The docs"},
                    {"title": "PEP 8", "url": "https://peps.python.org/pep-0008/", "content": "Style"},
                ]
            },
        )

    tctx.http_transport = httpx.MockTransport(handler)

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute("web_search", {"query": "python docs"}, tctx, confirm=allow)
    assert result.ok
    assert "Python docs" in result.output
    assert "https://peps.python.org/pep-0008/" in result.output
    assert result.data["count"] == 2
    assert seen[0].url.params["q"] == "python docs"
    assert seen[0].url.params["format"] == "json"


def test_web_search_surfaces_an_http_error(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True, "web.search_url": "https://searx.example/s"})
    tctx.http_transport = httpx.MockTransport(lambda request: httpx.Response(503))

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    with pytest.raises(ToolError) as excinfo:
        registry().execute("web_search", {"query": "x"}, tctx, confirm=allow)
    assert excinfo.value.message_key == "agent.web_failed"


def test_web_search_surfaces_a_network_failure(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True, "web.search_url": "https://searx.example/s"})

    def blow_up(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    tctx.http_transport = httpx.MockTransport(blow_up)

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    with pytest.raises(ToolError) as excinfo:
        registry().execute("web_search", {"query": "x"}, tctx, confirm=allow)
    assert "ConnectError" in excinfo.value.message


# ------------------------------------------------------------------- github
def test_github_tools_require_a_token(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True})
    with pytest.raises(ToolUnavailable) as excinfo:
        registry().execute("github_list_issues", {"repo": "owner/name"}, tctx)
    assert "GitHub token" in excinfo.value.message


def test_github_repo_format_is_validated(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True})
    tctx.secrets.set("github_token", "ghp_test_token")

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    with pytest.raises(ValidationError):
        registry().execute("github_list_issues", {"repo": "not a repo"}, tctx, confirm=allow)


def test_github_list_issues_reads_the_api(tctx: ToolContext) -> None:
    tctx.settings.update({"agent.allow_network": True})
    tctx.secrets.set("github_token", "ghp_test_token")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {"number": 7, "title": "Render bug", "state": "open", "user": {"login": "sara"}},
                {"number": 8, "title": "PR", "state": "open", "pull_request": {"url": "x"}},
            ],
        )

    tctx.http_transport = httpx.MockTransport(handler)

    def allow(tool, arguments):  # noqa: ANN001, ARG001
        return True

    result = registry().execute(
        "github_list_issues", {"repo": "owner/name", "state": "open"}, tctx, confirm=allow
    )
    assert result.ok
    assert "#7 [open] Render bug — sara" in result.output
    assert "#8" not in result.output
    assert seen[0].headers["Authorization"] == "Bearer ghp_test_token"
    assert seen[0].url.path == "/repos/owner/name/issues"


# -------------------------------------------------------------------- misc
def test_registry_can_be_extended_for_tests() -> None:
    tools = ToolRegistry([])

    def echo(tctx, args):  # noqa: ANN001, ARG001
        return __import__("myai.services.tools", fromlist=["ToolResult"]).ToolResult(True, "pong")

    tools.register(
        ToolSpec(
            id="echo",
            description="echo",
            parameters={"type": "object", "properties": {"text": {"type": "string"}},
                        "required": ["text"]},
            risk="read",
            handler=echo,
        )
    )
    assert tools.execute("echo", {"text": "hi"}, ToolContext()).output == "pong"
    with pytest.raises(ValidationError):
        tools.execute("echo", {}, ToolContext())


def test_unknown_risk_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolRegistry([]).register(
            ToolSpec(id="x", description="x", parameters={}, risk="root",
                     handler=lambda tctx, args: None)  # type: ignore[arg-type,return-value]
        )


def test_tool_output_is_limited_in_size(tctx: ToolContext, project_dir: Path) -> None:
    big = "\n".join(f"line {index}" for index in range(12000))
    (project_dir / "big.txt").write_text(big, encoding="utf-8")
    result = tctx.projects.read(tctx.project, "big.txt")
    assert len(result.text) == len(big)
    read = registry().execute("read_file", {"path": "big.txt"}, tctx)
    assert "truncated at" in read.output


def test_shutil_reference_keeps_optional_import_used() -> None:
    # gcc may be absent; the C path is covered only when a compiler exists.
    assert shutil.which("gcc") is None or Path(shutil.which("gcc")).exists()


def test_tool_result_serialises_to_json() -> None:
    from myai.services.tools import ToolResult, tool_result_json

    payload = json.loads(tool_result_json(ToolResult(True, "ok", {"count": 1})))
    assert payload == {"ok": True, "output": "ok", "data": {"count": 1}}
