"""Command palette and attachment widgets on the real window."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from myai.i18n import tr
from myai.ui.widgets.palette import CommandPalette


def pump(ms: int = 30) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)


def test_shortcut_is_registered(ui) -> None:
    window, _context, _theme = ui
    assert window.shortcut_palette.key().toString().replace(" ", "") == "Ctrl+Shift+P"


def test_palette_lists_every_page(ui) -> None:
    window, _context, _theme = ui
    ids = {action.id for action in window._palette_actions()}  # noqa: SLF001
    for route in (
        "agent", "code", "prompts", "tasks", "performance",
        "images", "video", "web", "plugins", "memory", "persona", "api", "studio",
    ):
        assert f"go.{route}" in ids


def test_filter_narrows_and_reports_empty(ui) -> None:
    window, _context, _theme = ui
    palette = CommandPalette(window, window._palette_actions())  # noqa: SLF001
    palette.search.setText("prompt")
    pump()
    assert [row.action.id for row in palette._rows] == ["go.prompts"]  # noqa: SLF001
    palette.search.setText("نشد پیدا")
    pump()
    assert palette._rows == []  # noqa: SLF001
    palette.close()


def test_running_an_action_navigates(ui) -> None:
    window, _context, _theme = ui
    palette = CommandPalette(window, window._palette_actions())  # noqa: SLF001
    palette.search.setText("performance")
    pump()
    palette._run_current()  # noqa: SLF001
    pump(60)
    assert window._current_route == "performance"  # noqa: SLF001
    assert palette.result == "go.performance"


def test_keyboard_moves_the_selection(ui) -> None:
    window, _context, _theme = ui
    palette = CommandPalette(window, window._palette_actions())  # noqa: SLF001
    palette.show()
    pump()
    # The highlight is a real state, not Qt focus: it must be visible even when
    # the window itself is not the active one (offscreen run, or Windows before
    # activation settles).
    assert palette._index == 0  # noqa: SLF001
    assert palette._rows[0].property("selected") == "true"  # noqa: SLF001
    palette._move(1)  # noqa: SLF001
    pump()
    assert palette._index == 1  # noqa: SLF001
    assert palette._rows[1].property("selected") == "true"  # noqa: SLF001
    assert palette._rows[0].property("selected") == "false"  # noqa: SLF001
    palette._move(-1)  # noqa: SLF001
    pump()
    assert palette._index == 0  # noqa: SLF001
    palette._move(-1)  # noqa: SLF001 - cannot go above the first row
    assert palette._index == 0  # noqa: SLF001
    palette._move(999)  # noqa: SLF001 - clamps to the last row
    assert palette._index == len(palette._rows) - 1  # noqa: SLF001
    palette.close()


def test_typing_keeps_the_highlight_in_range(ui) -> None:
    window, _context, _theme = ui
    palette = CommandPalette(window, window._palette_actions())  # noqa: SLF001
    palette._move(999)  # noqa: SLF001
    palette.search.setText("prompt")  # rebuilds the list
    pump()
    assert palette._index == 0  # noqa: SLF001
    assert palette._rows[0].property("selected") == "true"  # noqa: SLF001
    palette.search.setText("no-such-command-xyz")
    pump()
    assert palette._index == -1  # noqa: SLF001
    palette.close()


def test_cycle_theme_changes_the_real_setting(ui) -> None:
    window, context, theme = ui
    window.cycle_theme()
    first = str(context.settings.get("ui.theme"))
    assert first in {"midnight", "dawn", "aurora", "system"}
    window.cycle_theme()
    second = str(context.settings.get("ui.theme"))
    assert second != first
    theme.apply()


def test_attachment_chip_preview_emits_the_path(ui, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    # The window really opens a modal preview; return immediately so the test
    # stays offscreen-safe while still exercising construction + extraction.
    from myai.ui.widgets.dialogs import PreviewDialog

    monkeypatch.setattr(PreviewDialog, "exec", lambda self: 1)
    source = tmp_path / "readme.md"
    source.write_text("hello", encoding="utf-8")
    window.composer._add_attachment(str(source))  # noqa: SLF001
    pump()
    seen: list[str] = []
    window.composer.preview_requested.connect(seen.append)
    from myai.ui.widgets.fields import AttachmentChip

    chip = window.composer.findChildren(AttachmentChip)[0]
    chip.opened.emit(chip.ident)
    assert seen == [str(source)]


def test_web_pill_says_search_is_unavailable(ui) -> None:
    window, _context, _theme = ui
    toasts: list[tuple[str, str]] = []
    window._show_toast = lambda message, tone: toasts.append((message, tone))  # noqa: SLF001
    window.composer._on_web_toggled(True)  # noqa: SLF001
    assert toasts and toasts[0][1] == "warning"
    assert not window.composer.web_toggle.isChecked()
    assert tr("web.search_blocked") in toasts[0][0]


def test_agent_pill_opens_the_agent_page(ui) -> None:
    window, _context, _theme = ui
    window.composer._on_agent_toggled(True)  # noqa: SLF001
    pump(60)
    assert window._current_route == "agent"  # noqa: SLF001
    assert not window.composer.agent_toggle.isChecked()


def test_drop_zone_accepts_local_files(ui, tmp_path: Path) -> None:
    window, _context, _theme = ui
    assert window.composer.acceptDrops()
    source = tmp_path / "dropped.txt"
    source.write_text("dropped", encoding="utf-8")
    window.composer._add_attachment(str(source))  # noqa: SLF001 - same handler the drop calls
    assert window.composer.attachments()[0].name == "dropped.txt"


def test_tab_never_leaves_the_window(ui) -> None:
    window, _context, _theme = ui
    window.activateWindow()
    window.setFocus()
    visited: set[int] = set()
    for _ in range(40):
        QTest.keyClick(QApplication.focusWidget() or window, Qt.Key.Key_Tab)
        pump(5)
        focused = QApplication.focusWidget()
        assert focused is None or window.isAncestorOf(focused) or focused is window
        if focused is not None:
            visited.add(id(focused))
    assert len(visited) > 5, "Tab should move through several controls"
