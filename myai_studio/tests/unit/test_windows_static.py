"""The Windows static gate must catch real hazards, not just print PASS.

Every rule gets a snippet that violates it, so a rule that silently stops
working (an AST change, a typo in a set) fails the suite instead of turning the
portability report green.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_windows_static as gate  # noqa: E402


def findings_for(tmp_path: Path, source: str) -> list[gate.Finding]:
    target = tmp_path / "sample.py"
    target.write_text(source, encoding="utf-8")
    return gate.scan_file(target, source)


def rules(tmp_path: Path, source: str) -> set[str]:
    return {finding.rule for finding in findings_for(tmp_path, source)}


def test_module_level_posix_import_is_rejected(tmp_path: Path) -> None:
    assert "posix-import" in rules(tmp_path, "import fcntl\nimport os\n")
    assert "posix-import" in rules(tmp_path, "from pwd import getpwuid\n")


def test_posix_import_inside_a_platform_guard_is_allowed(tmp_path: Path) -> None:
    source = """import os

def read_posix_status():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except Exception:
        return None
"""
    assert "posix-import" not in rules(tmp_path, source)


def test_subprocess_without_creationflags_is_rejected(tmp_path: Path) -> None:
    source = "import subprocess\nsubprocess.run(['git', 'status'])\n"
    assert "console-window" in rules(tmp_path, source)


def test_subprocess_with_flags_is_accepted(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "from myai.core.platform import creation_flags\n"
        "subprocess.run(['git', 'status'], capture_output=True, creationflags=creation_flags())\n"
    )
    assert "console-window" not in rules(tmp_path, source)


def test_shell_true_is_rejected(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "from myai.core.platform import creation_flags\n"
        "subprocess.run('echo hi', shell=True, creationflags=creation_flags())\n"
    )
    assert "shell" in rules(tmp_path, source)


def test_text_io_without_encoding_is_rejected(tmp_path: Path) -> None:
    assert "encoding" in rules(tmp_path, "open('notes.txt', 'w')\n")
    assert "encoding" in rules(tmp_path, "from pathlib import Path\nPath('a').write_text('x')\n")
    assert "encoding" in rules(tmp_path, "from pathlib import Path\nPath('a').read_text()\n")
    # Binary reads have no encoding and are fine.
    assert "encoding" not in rules(tmp_path, "open('a.bin', 'rb')\n")


def test_posix_only_process_apis_need_a_guard(tmp_path: Path) -> None:
    assert "posix-api" in rules(tmp_path, "import os\nos.fork()\n")
    assert "posix-api" in rules(tmp_path, "import os\nos.setsid()\n")
    guarded = (
        "import os\n"
        "def kill(process):\n"
        "    if os.name == 'nt':\n"
        "        pass\n"
        "    else:\n"
        "        os.killpg(os.getpgid(process.pid), 9)\n"
    )
    assert "posix-api" not in rules(tmp_path, guarded)


def test_sigkill_needs_a_guard(tmp_path: Path) -> None:
    assert "posix-api" in rules(tmp_path, "import signal\nsignal.raise_signal(signal.SIGKILL)\n")
    guarded = (
        "import os, signal\n"
        "def kill(process):\n"
        "    if os.name == 'nt':\n"
        "        return\n"
        "    signal.raise_signal(signal.SIGKILL)\n"
    )
    assert "posix-api" not in rules(tmp_path, guarded)


def test_sys_executable_as_a_command_is_rejected(tmp_path: Path) -> None:
    source = "import sys, subprocess\nsubprocess.run([sys.executable, 'app.py'])\n"
    assert "frozen-interpreter" in rules(tmp_path, source)
    allowed = (
        "import sys\n"
        "def python_executable():\n"
        "    return sys.executable\n"
    )
    assert "frozen-interpreter" not in rules(tmp_path, allowed)


def test_hardcoded_posix_paths_are_rejected(tmp_path: Path) -> None:
    assert "posix-path" in rules(tmp_path, "PATH = '/tmp/scratch'\n")
    assert "posix-path" in rules(tmp_path, "SHELL = '/bin/sh'\n")


def test_the_real_source_tree_is_clean() -> None:
    """The gate that runs in CI; a new hazard fails here with its location."""
    findings = gate.scan([ROOT / "myai"])
    assert findings == [], "\n".join(str(finding) for finding in findings)


def test_the_script_reports_failure_for_bad_input(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    bad = tmp_path / "bad.py"
    bad.write_text("import fcntl\n", encoding="utf-8")
    code = gate.main(["check_windows_static.py", str(tmp_path)])
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_the_script_reports_success_for_clean_input(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    good = tmp_path / "good.py"
    good.write_text("import os\n", encoding="utf-8")
    code = gate.main(["check_windows_static.py", str(tmp_path)])
    assert code == 0
    assert "No platform hazard" in capsys.readouterr().out
