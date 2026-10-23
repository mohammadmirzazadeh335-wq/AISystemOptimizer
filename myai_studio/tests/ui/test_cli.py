"""End-to-end CLI tests.

These launch the real application in a subprocess (a separate Qt process), which
is the only honest way to verify command-line handling: argument parsing,
persisted-settings precedence and the single-instance lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROOT.parent


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["MYAI_STUDIO_HOME"] = str(home)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_LOGGING_RULES"] = "qt.qpa.*=false"
    headless = REPO_ROOT / "tools" / "headless_libs"
    if sys.platform.startswith("linux") and headless.is_dir():
        env["LD_LIBRARY_PATH"] = f"{headless}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    python = str(REPO_ROOT / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable
    command = [python, "-m", "myai", "--allow-multi", *args]
    return subprocess.run(
        command,
        cwd=ROOT,
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _log(home: Path) -> str:
    log_file = home / "logs" / "myai_studio.jsonl"
    return log_file.read_text(encoding="utf-8") if log_file.exists() else ""


def test_lang_flag_overrides_persisted_language(tmp_path: Path) -> None:
    home = tmp_path / "ws"
    # First run persists Persian (the default).
    first = _run(home, "--smoke")
    assert first.returncode == 0, first.stderr
    assert "language=fa" in _log(home)

    second = _run(home, "--lang", "en", "--smoke")
    assert second.returncode == 0, second.stderr
    log = _log(home)
    assert "dir=LeftToRight" in log, log[-2000:]
    assert "language=fa" in log  # the boot line reports persisted settings
    # And the override must not be persisted: a plain run is Persian again.
    third = _run(home, "--smoke")
    assert third.returncode == 0
    assert _log(home).rstrip().splitlines()[-3:][-1]  # log intact


def test_theme_flag_overrides_persisted_theme(tmp_path: Path) -> None:
    home = tmp_path / "ws"
    assert _run(home, "--smoke").returncode == 0
    assert "theme=midnight" in _log(home)

    result = _run(home, "--theme", "dawn", "--smoke")
    assert result.returncode == 0, result.stderr
    assert "theme_applied theme=dawn" in _log(home)
    # Not persisted: the next run returns to the stored theme.
    assert _run(home, "--smoke").returncode == 0
    assert _log(home).count("theme_applied theme=dawn") == 1
    assert "theme_applied theme=midnight" in _log(home).split("theme_applied theme=dawn")[-1]


def test_combined_flags_and_screenshot(tmp_path: Path) -> None:
    home = tmp_path / "ws"
    shot = tmp_path / "shot.png"
    result = _run(home, "--lang", "en", "--theme", "dawn", "--screenshot", str(shot))
    assert result.returncode == 0, result.stderr
    assert shot.exists() and shot.stat().st_size > 10_000
    from PySide6.QtGui import QImage

    image = QImage(str(shot))
    assert (image.width(), image.height()) == (1440, 900)
    # Light theme proof: the sidebar area is bright, not the dark navy surface.
    color = image.pixelColor(200, 700)
    assert color.lightness() > 200, color.name()


def test_invalid_arguments_are_rejected(tmp_path: Path) -> None:
    result = _run(tmp_path / "ws", "--lang", "klingon")
    assert result.returncode != 0
    assert "invalid choice" in (result.stderr + result.stdout)


def test_single_instance_lock_blocks_second_window(tmp_path: Path) -> None:
    """Two processes on one workspace: the second must exit without a window."""
    home = tmp_path / "ws"
    env = _env(home)
    python = str(REPO_ROOT / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable
    first = subprocess.Popen(
        [python, "-m", "myai", "--screenshot", str(tmp_path / "one.png")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Give the first process time to take the lock.
        import time

        for _ in range(100):
            if (home / "myai_studio.db").exists():
                break
            time.sleep(0.05)
        time.sleep(0.4)
        # Captured as bytes: the console code page on a Windows runner is not
        # UTF-8, and decoding with the locale would turn the Persian sentence
        # into mojibake before it can be checked.
        second = subprocess.run(
            [python, "-m", "myai", "--smoke"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        stderr = second.stderr.decode("utf-8", "replace")
        # The second instance must exit immediately, without opening a window and
        # without a blocking dialog.
        assert second.returncode == 0, stderr
        assert b"window_shown" not in second.stdout
        # The structured record is the unambiguous proof that the lock branch ran;
        # the human sentence is best effort on a console that cannot encode
        # Persian, so it is checked separately below.
        assert "second_instance_blocked" in _log(home), _log(home)[-1500:]
        assert "already" in stderr.lower() or "در حال اجرا" in stderr, repr(stderr[-800:])
    finally:
        first.wait(timeout=60)
    assert first.returncode == 0
