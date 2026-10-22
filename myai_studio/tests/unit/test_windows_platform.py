"""Windows 11 rules that can be proven from a Linux runner.

The Windows *API* cannot run here, but the rules that decide whether the app is
correct on Windows are pure functions. These tests pin them: reserved device
names, trailing dots, long paths, console-code-page decoding, hidden child
consoles and the frozen-build interpreter choice.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from myai.core import platform as plat
from myai.core.errors import ValidationError
from myai.core.logging import SafeStreamHandler
from myai.services import toolchains
from myai.services.projects import ProjectService
from myai.services.runner import Runner
from myai.services.toolchains import Toolchain


# ----------------------------------------------------------------- decoding
def test_utf8_output_wins() -> None:
    assert plat.decode_output("سلام دنیا".encode()) == "سلام دنیا"


def test_legacy_console_code_page_does_not_raise() -> None:
    # 0xE9 is "é" in cp1252 and an invalid UTF-8 start byte.
    assert plat.decode_output(b"caf\xe9") == "café"


def test_utf16_bom_is_honoured() -> None:
    assert plat.decode_output("نمونه".encode("utf-16")) == "نمونه"


def test_empty_output_is_empty_string() -> None:
    assert plat.decode_output(b"") == ""


# -------------------------------------------------------------- file naming
@pytest.mark.parametrize(
    "name",
    ["CON", "con.txt", "NUL", "com1.log", "LPT9.md", "a:b", "question?", "pipe|name",
     "trailing.", "trailing ", "", "   ", ".", "..", "x" * 121],
)
def test_unsafe_names_are_rejected(name: str) -> None:
    assert plat.filename_problem(name) is not None


@pytest.mark.parametrize("name", ["main.py", "report-2026.md", "پروژه من", "a.b.c", "index"])
def test_normal_names_pass(name: str) -> None:
    assert plat.filename_problem(name) is None


def test_reserved_name_has_its_own_reason() -> None:
    assert plat.filename_problem("CON.txt") == "reserved"
    assert plat.filename_problem("name.") == "trailing"
    assert plat.filename_problem("a?b") == "invalid_chars"


def test_long_path_is_refused_before_windows_truncates_it() -> None:
    parts = ["src", "a" * 120, "b" * 120, "c" * 30]
    assert plat.path_problem(parts) == "path_too_long"


def test_path_problem_checks_every_component() -> None:
    assert plat.path_problem(["src", "NUL.txt"]) == "reserved"
    assert plat.path_problem(["src", "ok.py"]) is None


# --------------------------------------------------------------- processes
def test_creation_flags_are_zero_off_windows() -> None:
    if plat.IS_WINDOWS:  # pragma: no cover - CI is Linux
        assert plat.creation_flags() == getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
    else:
        assert plat.creation_flags() == 0


def test_runner_passes_platform_creation_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real child process must receive the hidden-console flag on Windows."""
    import subprocess

    from myai.services import runner as runner_module

    seen: list[int] = []
    real_popen = subprocess.Popen

    class Recording:
        def __init__(self, *args, **kwargs):  # noqa: ANN002,ANN003
            seen.append(kwargs.get("creationflags", -1))
            # Linux rejects a non-zero value; the point of the test is that the
            # runner *passed* it, so it is stripped before the real call.
            kwargs.pop("creationflags", None)
            self._inner = real_popen(*args, **kwargs)

        def __getattr__(self, item):  # noqa: ANN001
            return getattr(self._inner, item)

    import types

    shim = types.SimpleNamespace(
        Popen=Recording,
        DEVNULL=subprocess.DEVNULL,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
        run=subprocess.run,
    )
    monkeypatch.setattr(runner_module, "creation_flags", lambda: 0x08000000)
    monkeypatch.setattr(runner_module, "subprocess", shim)
    script = tmp_path / "hi.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    plan = Runner().plan_for(script, cwd=tmp_path, timeout_seconds=20)
    result = Runner().run(plan)
    assert result.exit_code == 0 and "ok" in result.stdout
    assert seen and seen[0] == 0x08000000


# --------------------------------------------------------------- toolchains
def test_batch_files_need_windows() -> None:
    ids = {item[0] for item in toolchains.specs()}
    assert ("cmd" in ids) == plat.IS_WINDOWS


def test_frozen_build_never_runs_the_exe_as_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """In a PyInstaller build ``sys.executable`` is MyAIStudio.exe, not Python."""
    fake = Toolchain(id="python", label="Python", available=True,
                     executables=(r"C:\Python311\python.exe",), extensions=(".py",))
    monkeypatch.setattr(toolchains, "IS_FROZEN", True)
    monkeypatch.setattr(toolchains, "registry", lambda: type("R", (), {"get": lambda self, key: fake})())
    assert toolchains.python_executable() == r"C:\Python311\python.exe"


def test_frozen_build_without_interpreter_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = Toolchain(
        id="python", label="Python", available=True, version="3.12", executables=(),
        extensions=(".py",),
    )

    class FakeRegistry:
        def get(self, key: str) -> Toolchain:  # noqa: ARG002
            return missing

        def for_extension(self, suffix: str) -> Toolchain:  # noqa: ARG002
            return missing

    monkeypatch.setattr(toolchains, "IS_FROZEN", True)
    monkeypatch.setattr(toolchains, "registry", lambda: FakeRegistry())
    assert toolchains.python_executable() == ""
    script = tmp_path / "a.py"
    script.write_text("print(1)\n", encoding="utf-8")
    with pytest.raises(toolchains.ToolchainUnavailable) as excinfo:
        toolchains.build_plan(script, cwd=tmp_path)
    assert "No Python interpreter" in excinfo.value.detail


# ------------------------------------------------------------- project guard
@pytest.fixture()
def projects(ctx) -> ProjectService:  # noqa: ANN001
    return ProjectService(ctx.paths, ctx.settings)


def test_project_names_windows_cannot_store_are_refused(projects: ProjectService) -> None:
    with pytest.raises(ValidationError) as excinfo:
        projects.create_project("CON")
    assert excinfo.value.message_key == "error.filename_reserved"
    with pytest.raises(ValidationError):
        projects.create_project("bad:name")
    assert not (projects._paths.projects_dir / "CON").exists()  # noqa: SLF001


def test_files_and_folders_with_reserved_names_are_refused(projects: ProjectService, tmp_path: Path) -> None:
    project = projects.open_folder(tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        projects.create_file(project, "src/NUL.txt")
    assert excinfo.value.message_key == "error.filename_reserved"
    with pytest.raises(ValidationError):
        projects.make_folder(project, "aux")
    with pytest.raises(ValidationError):
        projects.write(project, "name.", "x")


def test_long_relative_path_is_reported_not_crashing(projects: ProjectService, tmp_path: Path) -> None:
    project = projects.open_folder(tmp_path)
    relative = "/".join(["a" * 110] * 3)
    with pytest.raises(ValidationError) as excinfo:
        projects.write(project, f"{relative}/main.py", "x")
    assert excinfo.value.message_key == "error.path_too_long"


def test_valid_project_still_works(projects: ProjectService) -> None:
    project = projects.create_project("demo-app")
    content = projects.create_file(project, "src/main.py", "print('hi')\n")
    assert content.text.startswith("print")
    assert (project.root / "src" / "main.py").is_file()


# ------------------------------------------------------------------ logging
class _LegacyConsole(io.TextIOBase):
    """A stream that fails exactly like a Windows console does for Persian."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:  # noqa: D102
        text.encode(self.encoding)  # raises UnicodeEncodeError for Persian
        self.written.append(text)
        return len(text)


def test_console_handler_survives_a_legacy_code_page() -> None:
    stream = _LegacyConsole()
    handler = SafeStreamHandler(stream)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "سلام", None, None)
    handler.emit(record)  # must not raise
    assert stream.written and "?" in stream.written[0]
