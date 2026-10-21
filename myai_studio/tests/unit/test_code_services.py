"""Code Studio backend: toolchains, project folders and the real runner.

These tests execute real processes. They are the proof that "run" means run:
an interpreter prints, a compiler compiles, a missing toolchain is reported with
the exact reason, and a runaway program is killed by the wall-clock limit.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from myai.core.errors import NotFoundError, ValidationError
from myai.services.projects import ProjectService
from myai.services.runner import Runner
from myai.services.toolchains import (
    ToolchainRegistry,
    ToolchainUnavailable,
    build_plan,
    registry,
)


# ------------------------------------------------------------------ toolchains
def test_python_toolchain_is_detected_with_a_real_version() -> None:
    chain = ToolchainRegistry().detect()
    python = next(item for item in chain if item.id == "python")
    assert python.available is True
    assert "python" in python.version.lower()
    assert python.executables and Path(python.executables[0]).exists()


def test_missing_toolchains_name_the_missing_command() -> None:
    """A toolchain this machine does not have must say what is missing."""
    chain = {item.id: item for item in ToolchainRegistry().detect()}
    missing = [item for item in chain.values() if not item.available]
    assert missing, "at least one toolchain should be unavailable in this image"
    for item in missing:
        assert item.version == ""
        assert "not found" in item.detail or "did not answer" in item.detail
        assert item.detail


def test_registry_is_cached_and_can_refresh() -> None:
    first = registry().detect()
    second = registry().detect()
    assert [item.id for item in first] == [item.id for item in second]
    assert registry().summary()["count"] >= 1


def test_plan_for_python_uses_the_running_interpreter(tmp_path: Path) -> None:
    source = tmp_path / "hello.py"
    source.write_text("print('x')\n", encoding="utf-8")
    plan = build_plan(source, cwd=tmp_path)
    assert plan.language == "python"
    # The realpath of sys.executable: same interpreter, readable command line.
    assert plan.steps[0].argv[0] == os.path.realpath(sys.executable)
    assert plan.steps[0].argv[-1] == "hello.py"


def test_plan_for_c_compiles_then_runs_build_artifact(tmp_path: Path) -> None:
    if not shutil.which("gcc"):
        pytest.skip("gcc is not installed in this image")
    source = tmp_path / "hello.c"
    source.write_text("int main(void){return 0;}\n", encoding="utf-8")
    plan = build_plan(source, cwd=tmp_path)
    assert [step.kind for step in plan.steps] == ["compile", "run"]
    assert "-o" in plan.steps[0].argv
    assert plan.steps[1].argv[0].startswith(str(tmp_path / ".myai-build"))


def test_unknown_extension_cannot_be_planned(tmp_path: Path) -> None:
    source = tmp_path / "notes.xyz"
    source.write_text("hello", encoding="utf-8")
    with pytest.raises(ToolchainUnavailable):
        build_plan(source, cwd=tmp_path)


def test_missing_toolchain_cannot_be_planned(tmp_path: Path) -> None:
    if shutil.which("go"):
        pytest.skip("Go is installed; this test needs a missing toolchain")
    source = tmp_path / "main.go"
    source.write_text("package main\nfunc main(){}\n", encoding="utf-8")
    with pytest.raises(ToolchainUnavailable) as info:
        build_plan(source, cwd=tmp_path)
    assert "go" in info.value.detail


# ---------------------------------------------------------------------- runner
def _python_plan(tmp_path: Path, code: str, timeout: float = 10.0):  # noqa: ANN202
    source = tmp_path / "script.py"
    source.write_text(code, encoding="utf-8")
    return build_plan(source, cwd=tmp_path, timeout_seconds=timeout)


def test_runner_captures_real_stdout_and_exit_code(tmp_path: Path) -> None:
    plan = _python_plan(tmp_path, "print('hello from python')\n")
    result = Runner().run(plan)
    assert result.succeeded is True
    assert result.status == "ok"
    assert result.exit_code == 0
    assert "hello from python" in result.stdout
    assert result.duration_ms >= 0


def test_runner_reports_stderr_and_non_zero_exit(tmp_path: Path) -> None:
    plan = _python_plan(
        tmp_path,
        "import sys\nprint('visible', file=sys.stderr)\nsys.exit(3)\n",
    )
    result = Runner().run(plan)
    assert result.status == "failed"
    assert result.exit_code == 3
    assert "visible" in result.stderr


def test_runner_streams_lines_to_the_callback(tmp_path: Path) -> None:
    plan = _python_plan(tmp_path, "print('one')\nprint('two')\n")
    seen: list[tuple[str, str]] = []
    Runner().run(plan, on_output=lambda stream, line: seen.append((stream, line)))
    stdout = [line for stream, line in seen if stream == "stdout"]
    assert stdout == ["one", "two"]


def test_runner_enforces_the_wall_clock_limit(tmp_path: Path) -> None:
    plan = _python_plan(tmp_path, "import time\ntime.sleep(30)\n", timeout=1.0)
    started = time.monotonic()
    result = Runner().run(plan)
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.status == "timeout"
    assert elapsed < 8.0, f"timeout was not enforced ({elapsed:.1f}s)"


def test_runner_can_be_cancelled_from_another_thread(tmp_path: Path) -> None:
    plan = _python_plan(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(30)\n")
    stop = threading.Event()
    outcome: dict = {}

    def work() -> None:
        outcome["result"] = Runner().run(plan, cancel_event=stop)

    thread = threading.Thread(target=work)
    thread.start()
    time.sleep(0.6)
    stop.set()
    thread.join(timeout=10)
    result = outcome["result"]
    assert result.cancelled is True
    assert result.status == "cancelled"
    assert "started" in result.stdout


def test_runner_does_not_leak_the_api_key_into_the_child(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MYAI_LIVE_API_KEY", "sk-or-v1-should-not-be-visible")
    plan = _python_plan(
        tmp_path,
        "import os\nprint(os.environ.get('MYAI_LIVE_API_KEY', 'absent'))\n",
    )
    result = Runner().run(plan)
    assert "absent" in result.stdout
    assert "sk-or-v1" not in result.stdout


def test_c_program_really_compiles_and_runs(tmp_path: Path) -> None:
    if not shutil.which("gcc"):
        pytest.skip("gcc is not installed in this image")
    source = tmp_path / "hello.c"
    source.write_text(
        '#include <stdio.h>\nint main(void){printf("hello from c\\n");return 0;}\n',
        encoding="utf-8",
    )
    result = Runner().run(build_plan(source, cwd=tmp_path, timeout_seconds=20))
    assert result.succeeded is True, (result.stderr, result.stdout)
    assert "hello from c" in result.stdout
    assert (tmp_path / ".myai-build").is_dir()


def test_c_compile_error_is_surfaced_verbatim(tmp_path: Path) -> None:
    if not shutil.which("gcc"):
        pytest.skip("gcc is not installed in this image")
    source = tmp_path / "broken.c"
    source.write_text("int main(void){ this is not c }\n", encoding="utf-8")
    result = Runner().run(build_plan(source, cwd=tmp_path, timeout_seconds=20))
    assert result.status == "failed"
    assert result.exit_code not in (0, None)
    assert "error" in result.stderr.lower()
    # The compiler's own message must reach the panel untouched.
    assert "broken.c" in result.stderr


def test_javascript_runs_when_node_exists(tmp_path: Path) -> None:
    if not shutil.which("node"):
        pytest.skip("node is not installed in this image")
    source = tmp_path / "hello.js"
    source.write_text("console.log('hello from node');\n", encoding="utf-8")
    result = Runner().run(build_plan(source, cwd=tmp_path, timeout_seconds=20))
    assert result.succeeded is True, result.stderr
    assert "hello from node" in result.stdout


# -------------------------------------------------------------------- projects
@pytest.fixture()
def projects(ctx) -> ProjectService:  # noqa: ANN001
    return ProjectService(ctx.paths, ctx.settings)


def _sample(projects: ProjectService, tmp_path: Path):  # noqa: ANN202
    root = tmp_path / "demo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    return projects.open_folder(root)


def test_open_folder_lists_a_real_tree(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    entries = {entry.relative: entry for entry in projects.tree(project)}
    assert set(entries) == {"src", "src/main.py", "README.md"}
    assert entries["src"].is_dir is True
    assert entries["src/main.py"].language == "python"
    assert entries["README.md"].language == "markdown"


def test_open_folder_rejects_a_missing_path(projects: ProjectService, tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        projects.open_folder(tmp_path / "nope")


def test_read_write_roundtrip_touches_the_real_file(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    content = projects.read(project, "src/main.py")
    assert content.text == "print('hi')\n"
    projects.write(project, "src/main.py", "print('changed')\n")
    assert (project.root / "src" / "main.py").read_text(encoding="utf-8") == "print('changed')\n"


def test_create_rename_delete(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    projects.create_file(project, "notes.txt", "first")
    assert (project.root / "notes.txt").is_file()
    new_relative = projects.rename(project, "notes.txt", "notes2.txt")
    assert new_relative == "notes2.txt"
    assert not (project.root / "notes.txt").exists()
    projects.delete(project, "notes2.txt")
    assert not (project.root / "notes2.txt").exists()


@pytest.mark.parametrize(
    "relative",
    ["../outside.txt", "src/../../outside.txt", "/etc/passwd", "C:\\Windows\\win.ini"],
)
def test_paths_outside_the_project_are_rejected(
    projects: ProjectService, tmp_path: Path, relative: str
) -> None:
    project = _sample(projects, tmp_path)
    with pytest.raises(ValidationError):
        projects.resolve(project, relative)


def test_symlink_escape_is_rejected(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = project.root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported here")
    with pytest.raises(ValidationError):
        projects.resolve(project, "link.txt")


def test_binary_files_are_not_opened_as_text(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    (project.root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    content = projects.read(project, "image.png")
    assert content.binary is True
    assert content.editable is False
    assert content.text == ""


def test_recent_projects_are_remembered_in_order(projects: ProjectService, tmp_path: Path) -> None:
    first_project = _sample(projects, tmp_path)
    first = projects.open_folder(first_project.root)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second = projects.open_folder(second_root)
    recent = projects.recent()
    assert recent[0].root == second.root
    assert first.root in [item.root for item in recent]
    assert projects.last_project().root == second.root


def test_duplicate_file_creation_is_refused(projects: ProjectService, tmp_path: Path) -> None:
    project = _sample(projects, tmp_path)
    with pytest.raises(ValidationError):
        projects.create_file(project, "README.md", "again")
