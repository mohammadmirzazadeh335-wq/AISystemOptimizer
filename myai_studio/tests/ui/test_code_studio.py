"""Phase 3: Code Studio driven through the real window, real files, real processes.

No fake runners here. Each test creates files in ``tmp_path``, opens them through
the page and asserts what the machine actually produced. Tests that need a
compiler or a missing toolchain skip with a stated reason instead of inventing
a result.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from myai.i18n import tr
from myai.services.toolchains import registry
from myai.ui.views.placeholder import ROUTES

SLOW_SCRIPT = "import time\nprint('started', flush=True)\ntime.sleep(20)\n"


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def wait_for_run(page, timeout: float = 25.0) -> None:
    """Pump the event loop until the worker thread reports back."""
    deadline = time.monotonic() + timeout
    while page._is_running() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    QApplication.processEvents()
    assert not page._is_running(), "the run did not finish within the deadline"


@pytest.fixture()
def project(tmp_path: Path, ui):
    """A real folder with runnable sources, opened through the page."""
    window, ctx, theme = ui
    folder = tmp_path / "demo-project"
    folder.mkdir()
    (folder / "hello.py").write_text("print('hello from disk')\nprint('second line')\n")
    (folder / "fail.py").write_text("import sys\nprint('before exit')\nsys.exit(3)\n")
    (folder / "slow.py").write_text(SLOW_SCRIPT)
    (folder / "notes.md").write_text("# Notes\n\nPlain markdown, no runner.\n")
    (folder / "broken.c").write_text(
        "#include <stdio.h>\nint main(void) { retrun 0; }\n"
    )
    (folder / "main.c").write_text(
        '#include <stdio.h>\nint main(void) { printf("c-ran\\n"); return 0; }\n'
    )
    (folder / "src").mkdir()
    (folder / "src" / "util.py").write_text("VALUE = 41\n")
    ctx.settings.set("ui.language", "en")
    ctx.settings.set("ui.editor_autosave", False)
    pump()
    page = window.code_page
    window._navigate("code")
    pump()
    page.set_project(page.projects.open_folder(folder))
    pump()
    return page, folder


# --------------------------------------------------------------------- routing
def test_code_page_is_a_real_route(ui) -> None:
    window, ctx, theme = ui
    window._navigate("code")
    pump()
    page = window.code_page
    assert window.stack.currentWidget() is page
    assert window.stack.currentWidget() is not window.placeholder
    assert not window.composer.isVisible()
    assert window.sidebar.nav_buttons["code"].isChecked()
    assert window.header.title.text() == tr("code.title")
    assert window.windowTitle() == f"{tr('code.title')} — MyAI Studio Ultimate"
    assert "code" not in ROUTES, "code must not still be a phase-locked placeholder"


def _wired(button, messages: list[str]) -> bool:  # noqa: ANN001
    messages.clear()
    button.dumpObjectInfo()
    inside = False
    for line in messages:
        text = line.strip()
        if text.startswith("signal:"):
            inside = text.startswith(("signal: clicked", "signal: toggled"))
            continue
        if text.startswith("SIGNALS IN"):
            inside = False
            continue
        if inside and text.startswith(("-->", "<functor")):
            return True
    return False


def test_page_is_not_display_only(ui, monkeypatch) -> None:
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtWidgets import QPushButton

    window, ctx, theme = ui
    window._navigate("code")
    pump()
    page = window.code_page
    captured: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, message: captured.append(message))
    monkeypatch.setattr(QApplication, "_myai_prev_handler", previous, raising=False)
    dead = [
        button.text()
        for button in page.findChildren(QPushButton)
        if button.isVisible() and not _wired(button, captured)
    ]
    assert not dead, dead
    for button in (
        page.open_button,
        page.new_project_button,
        page.save_button,
        page.run_button,
        page.stop_button,
        page.clear_button,
        page.new_file_button,
        page.rename_button,
        page.delete_button,
        page.toolchain_toggle,
    ):
        assert button in page.findChildren(QPushButton) or button.parent() is not None
    assert page.save_button.shortcut().toString() == "Ctrl+S"
    assert page.run_button.shortcut().toString() == "Ctrl+R"


# --------------------------------------------------------------------- project
def test_opening_a_folder_lists_real_files(project) -> None:
    page, folder = project
    names = {page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())}
    assert {"hello.py", "fail.py", "slow.py", "notes.md", "broken.c", "main.c", "src"} <= names
    src = next(
        page.tree.topLevelItem(i)
        for i in range(page.tree.topLevelItemCount())
        if page.tree.topLevelItem(i).text(0) == "src"
    )
    assert src.childCount() == 1 and src.child(0).text(0) == "util.py"
    assert page.project_label.text() == folder.name
    assert page.project_label.toolTip() == str(folder.resolve())
    assert "7" in page.stats_label.text()


def test_open_file_reads_from_disk(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    assert page.editor.toPlainText() == (folder / "hello.py").read_text()
    assert page.file_label.text() == "hello.py"
    assert page.language_badge.text() == "PYTHON"
    assert page.run_button.isEnabled() is True
    assert page.editor.isReadOnly() is False
    assert page.cursor_label.text() == tr("code.cursor", line=1, column=1)


def test_subfolder_file_opens_and_highlights(project) -> None:
    page, folder = project
    page.open_file("src/util.py")
    pump()
    assert page.editor.toPlainText() == "VALUE = 41\n"
    assert page.language_badge.text() == "PYTHON"


# ----------------------------------------------------------------------- save
def test_edit_and_save_writes_the_real_file(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    page.editor.appendPlainText("print('typed in the editor')")
    pump()
    assert page._dirty is True
    assert page.dirty_label.isVisible() is True
    assert page.dirty_label.text() == tr("code.unsaved")
    assert page.save_file() is True
    pump()
    assert page._dirty is False
    assert page.dirty_label.isVisible() is False
    assert "typed in the editor" in (folder / "hello.py").read_text()


def test_reverting_the_text_clears_the_dirty_flag(project) -> None:
    """Re-highlighting emits textChanged; a formatting event is not an edit."""
    page, folder = project
    page.open_file("hello.py")
    pump()
    original = page.editor.toPlainText()
    page.editor.setPlainText(original + "x")
    pump()
    assert page._dirty is True
    page.editor.setPlainText(original)
    pump()
    assert page._dirty is False
    assert page.dirty_label.isVisible() is False


def test_autosave_writes_after_the_timer(project) -> None:
    page, folder = project
    page.context.settings.set("ui.editor_autosave", True)
    page.open_file("hello.py")
    pump()
    page.editor.appendPlainText("# autosaved")
    pump()
    assert "# autosaved" not in (folder / "hello.py").read_text()
    page._autosave_tick()
    pump()
    assert "# autosaved" in (folder / "hello.py").read_text()
    assert page._dirty is False
    page.context.settings.set("ui.editor_autosave", False)


def test_switching_files_saves_the_pending_edit(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    page.editor.appendPlainText("# pending")
    pump()
    page.open_file("notes.md")
    pump()
    assert "# pending" in (folder / "hello.py").read_text()
    assert page.file_label.text() == "notes.md"
    assert page._dirty is False


# ----------------------------------------------------------------------- run
def test_run_a_python_file_for_real(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    page.run_current()
    assert page.stop_button.isEnabled() is True
    wait_for_run(page)
    output = page.output_view.toPlainText()
    assert "hello from disk" in output
    assert "second line" in output
    assert page.status_badge.property("badge") == "success"
    assert page.status_badge.text().startswith("Exit 0")
    assert page.command_label.text().startswith(os.path.realpath(sys.executable))
    assert page.stop_button.isEnabled() is False
    assert page.run_button.isEnabled() is True


def test_non_zero_exit_is_reported(project) -> None:
    page, folder = project
    page.open_file("fail.py")
    pump()
    page.run_current()
    wait_for_run(page)
    assert "before exit" in page.output_view.toPlainText()
    assert page.status_badge.property("badge") == "danger"
    assert "3" in page.status_badge.text()


def test_run_does_not_block_the_ui(project) -> None:
    page, folder = project
    page.open_file("slow.py")
    pump()
    started = time.monotonic()
    page.run_current()
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, f"run_current blocked the GUI thread for {elapsed:.2f}s"
    assert page.stop_button.isEnabled() is True
    page.stop_run()
    wait_for_run(page, timeout=15)


def test_stop_kills_a_long_run(project) -> None:
    page, folder = project
    page.open_file("slow.py")
    pump()
    started = time.monotonic()
    page.run_current()
    deadline = time.monotonic() + 5
    while "started" not in page.output_view.toPlainText() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    page.stop_run()
    wait_for_run(page, timeout=10)
    assert time.monotonic() - started < 12
    assert page.status_badge.text() == tr("code.status_cancelled")
    assert page.run_button.isEnabled() is True


def test_run_saves_the_edited_file_first(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    page.editor.setPlainText("print('edited before run')\n")
    page.run_current()
    wait_for_run(page)
    assert "edited before run" in page.output_view.toPlainText()
    assert (folder / "hello.py").read_text() == "print('edited before run')\n"


def test_clear_output_resets_the_panel(project) -> None:
    page, folder = project
    page.open_file("hello.py")
    page.run_current()
    wait_for_run(page)
    page.clear_output()
    pump()
    assert page.output_view.toPlainText() == ""
    assert page.status_badge.text() == tr("code.not_run")
    assert page.command_label.text() == ""


def _gcc_available() -> bool:
    return registry().get("c").available


@pytest.mark.skipif(not _gcc_available(), reason="gcc is not installed on this machine")
def test_compiler_error_is_shown_verbatim(project) -> None:
    page, folder = project
    page.open_file("broken.c")
    pump()
    page.run_current()
    wait_for_run(page)
    output = page.output_view.toPlainText()
    assert "error" in output.lower()
    assert "broken.c" in output
    assert page.status_badge.property("badge") == "danger"
    assert not (folder / ".myai-build" / "broken").exists()


@pytest.mark.skipif(not _gcc_available(), reason="gcc is not installed on this machine")
def test_c_compiles_and_runs(project) -> None:
    page, folder = project
    page.open_file("main.c")
    pump()
    page.run_current()
    wait_for_run(page)
    assert "c-ran" in page.output_view.toPlainText()
    assert page.status_badge.property("badge") == "success"
    assert (folder / ".myai-build" / "main").exists()


def test_markdown_is_honestly_unrunnable(project) -> None:
    page, folder = project
    page.open_file("notes.md")
    pump()
    assert page.toolchain_badge.text() == tr("code.no_toolchain")
    page.run_current()
    pump()
    output = page.output_view.toPlainText()
    assert page.status_badge.text() == tr("code.unavailable_badge")
    assert output == "" or "markdown" in output.lower() or "not" in output.lower()


def test_missing_toolchain_names_the_executable(project) -> None:
    page, folder = project
    chain = registry().get("java")
    if chain.available:
        pytest.skip("java is installed here; the unavailable path cannot be proven")
    source = folder / "Hello.java"
    source.write_text("class Hello { public static void main(String[] a) {} }\n")
    page._populate_tree()
    page.open_file("Hello.java")
    pump()
    assert tr("code.toolchain_missing", name=chain.label) == page.toolchain_badge.text()
    page.run_current()
    pump()
    output = page.output_view.toPlainText()
    assert tr("code.unavailable_title") in output
    assert "javac" in output or "java" in output
    assert page.status_badge.text() == tr("code.unavailable_badge")


# --------------------------------------------------------------------- files
def test_new_file_through_the_dialog(project, monkeypatch) -> None:
    page, folder = project
    monkeypatch.setattr(
        "myai.ui.views.code_page.QInputDialog.getText", lambda *a, **k: ("added.py", True)
    )
    page.new_file()
    pump()
    assert (folder / "added.py").exists()
    assert page.file_label.text() == "added.py"
    names = {page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())}
    assert "added.py" in names


def test_new_file_rejects_traversal(project, monkeypatch) -> None:
    page, folder = project
    messages: list[tuple[str, str]] = []
    page.notify.connect(lambda message, level: messages.append((message, level)))
    monkeypatch.setattr(
        "myai.ui.views.code_page.QInputDialog.getText",
        lambda *a, **k: ("../../escaped.py", True),
    )
    page.new_file()
    pump()
    assert messages and messages[-1][1] == "error"
    assert not (folder.parent / "escaped.py").exists()


def test_rename_and_delete_update_disk_and_tree(project, monkeypatch) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    item = page.tree.currentItem()
    assert item is not None and item.text(0) == "hello.py"
    monkeypatch.setattr(
        "myai.ui.views.code_page.QInputDialog.getText", lambda *a, **k: ("renamed.py", True)
    )
    page.rename_selected()
    pump()
    assert (folder / "renamed.py").exists() and not (folder / "hello.py").exists()
    assert page.current_file == "renamed.py"
    assert page.file_label.text() == "renamed.py"
    page.delete_selected()
    pump()
    assert not (folder / "renamed.py").exists()
    assert page.current_file is None
    assert page.editor.toPlainText() == ""
    assert page.run_button.isEnabled() is False


def test_recent_projects_are_listed(project, tmp_path) -> None:
    page, folder = project
    page.projects.open_folder(tmp_path)
    page.refresh()
    pump()
    recent = {str(item.root) for item in page.projects.recent()}
    assert str(folder.resolve()) in recent
    assert page.project_select.isEnabled() is True


# --------------------------------------------------------------------- themes
def test_toolchain_inspector_lists_availability(project) -> None:
    page, folder = project
    text = page.toolchain_label.text()
    assert "Python" in text
    summary = registry().summary()
    if summary["missing"]:
        page._toggle_toolchain_details()
        pump()
        assert page.toolchain_detail.isVisible() is True
        assert "not found" in page.toolchain_detail.text()
        page._toggle_toolchain_details()
        assert page.toolchain_detail.isVisible() is False


@pytest.mark.parametrize("language", ["fa", "en"])
def test_language_switch_keeps_the_open_file(project, language) -> None:
    page, folder = project
    ctx = page.context
    page.open_file("hello.py")
    pump()
    page.editor.appendPlainText("# unsaved line")
    pump()
    ctx.settings.set("ui.language", language)
    pump()
    assert page.file_label.text() == "hello.py"
    assert "# unsaved line" in page.editor.toPlainText()
    assert page.editor.toPlainText().endswith("# unsaved line")
    assert page._dirty is True
    assert page.run_button.text() == tr("code.run")
    direction = QApplication.layoutDirection()
    assert direction == (Qt.LayoutDirection.RightToLeft if language == "fa" else Qt.LayoutDirection.LeftToRight)


def test_theme_switch_keeps_the_open_file(project) -> None:
    page, folder = project
    page.open_file("main.c")
    page.editor.appendPlainText("// unsaved")
    pump()
    page.context.settings.set("ui.theme", "dawn")
    pump()
    assert page.file_label.text() == "main.c"
    assert "// unsaved" in page.editor.toPlainText()
    assert page.language_badge.text() == "C"


@pytest.mark.parametrize("scale", [1.25, 1.5])
def test_font_scale_keeps_the_layout_usable(project, scale) -> None:
    page, folder = project
    page.open_file("hello.py")
    pump()
    page.context.settings.set("ui.font_scale", scale)
    pump()
    assert page.editor.font().pixelSize() >= int(12 * scale)
    widths = page.top_splitter.sizes()
    assert widths[0] > 0 and widths[1] > 0
    heights = page.splitter.sizes()
    assert heights[0] > 0 and heights[1] > 0
    assert page.file_label.full_text() == "hello.py"
    assert page.file_label.text() != ""
    assert page.current_file == "hello.py"
