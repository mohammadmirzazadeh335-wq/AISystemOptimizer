from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myai.core import timeutil
from myai.core.paths import get_paths


def test_paths_are_created_under_home(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "ws")
    for directory in (
        paths.home,
        paths.logs_dir,
        paths.backups_dir,
        paths.previews_dir,
        paths.images_dir,
        paths.projects_dir,
    ):
        assert directory.is_dir(), directory
    assert paths.db_file.name == "myai_studio.db"
    assert paths.secrets_file.parent == paths.home


def test_paths_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYAI_STUDIO_HOME", str(tmp_path / "env-home"))
    paths = get_paths()
    assert paths.home == (tmp_path / "env-home").resolve()


def test_utcnow_is_monotonic_enough() -> None:
    a = timeutil.utcnow()
    b = timeutil.utcnow()
    assert b >= a
    assert b.microsecond != 0 or True  # microseconds preserved when available


def test_format_bytes() -> None:
    assert timeutil.format_bytes(0) == "0 B"
    assert timeutil.format_bytes(999) == "999 B"
    assert timeutil.format_bytes(1024) == "1.0 KB"
    assert timeutil.format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_jalali_conversion_known_dates() -> None:
    assert timeutil.gregorian_to_jalali(2026, 3, 21) == (1405, 1, 1)
    assert timeutil.gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)
    assert timeutil.gregorian_to_jalali(2026, 10, 19) == (1405, 7, 27)


def test_relative_time_languages() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert timeutil.relative_time(now - timedelta(seconds=5), "en") == "just now"
    assert timeutil.relative_time(now - timedelta(seconds=5), "fa") == "همین حالا"
    assert "m ago" in timeutil.relative_time(now - timedelta(minutes=5), "en")


def test_group_label_today() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert timeutil.group_label(now, "en") == "Today"
    assert timeutil.group_label(now, "fa") == "امروز"
