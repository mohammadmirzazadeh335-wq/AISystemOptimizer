"""Phase 5 pages: prompts, tasks, performance, images, video, web, plugins.

The tests drive the real widgets through their real handlers. Modal dialogs are
the only thing replaced: ``exec`` returns ``Accepted``/``Rejected`` so the test
exercises the code after the dialog without opening a window.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from myai.core.errors import NotFoundError
from myai.i18n import tr
from myai.services.web import WebPage
from myai.ui.widgets.dialogs import ConfirmDialog
from myai.ui.widgets.foundation import ElidedLabel

LIBRARY_ROUTES = ["prompts", "tasks", "performance", "images", "video", "web", "plugins"]


def pump(ms: int = 40) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)


def accept_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)


def reject_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Rejected)


def texts(widget) -> list[str]:  # noqa: ANN001
    values = [label.text() for label in widget.findChildren(QLabel) if label.text()]
    values += [label.text() for label in widget.findChildren(ElidedLabel) if label.text()]
    return values


# ------------------------------------------------------------------- navigation


@pytest.mark.parametrize("route", LIBRARY_ROUTES)
def test_every_library_route_opens_a_real_page(ui, route: str) -> None:
    window, ctx, _theme = ui
    window._navigate(route)
    pump()
    page = window._pages[route]
    assert window.stack.currentWidget() is page
    assert not window.composer.isVisible()
    assert window.sidebar.nav_buttons[route].isChecked()
    assert window.header.title.text() == tr(f"{route}.title")


def test_sidebar_lists_video_and_plugins(ui) -> None:
    window, _ctx, _theme = ui
    assert "video" in window.sidebar.nav_buttons
    assert "plugins" in window.sidebar.nav_buttons
    assert window.sidebar.nav_buttons["plugins"].isVisible()
    assert tr("nav.plugins") != "nav.plugins"


# ---------------------------------------------------------------------- prompts


def test_prompt_library_lists_builtins_and_searches(ui) -> None:
    window, ctx, _theme = ui
    window._navigate("prompts")
    pump()
    page = window.prompts_page
    assert ctx.prompts.count() >= 6
    assert page.list_layout.count() - 1 == ctx.prompts.count()

    page.search._edit.setText("review")
    pump()
    visible = page.list_layout.count() - 1
    assert 1 <= visible < ctx.prompts.count()

    page.search.clear()
    pump()
    assert page.list_layout.count() - 1 == ctx.prompts.count()
    assert not page.empty.isVisible()


def test_prompt_use_fills_the_composer_and_counts(ui) -> None:
    window, ctx, _theme = ui
    window._navigate("prompts")
    pump()
    page = window.prompts_page
    entry = ctx.prompts.list()[0]
    button = next(
        child
        for child in page.findChildren(QPushButton)
        if child.objectName() == "PromptUse"
    )
    button.click()
    pump()

    assert ctx.prompts.get(entry.id).uses == 1
    assert window.stack.currentWidget() is window.chat_view
    assert window.composer.input.toPlainText() == entry.body


def test_prompt_editor_creates_a_prompt(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    window._navigate("prompts")
    pump()
    page = window.prompts_page
    before = ctx.prompts.count()

    from myai.ui.views.prompts_page import PromptEditor

    monkeypatch.setattr(PromptEditor, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(
        PromptEditor,
        "result_data",
        lambda self: {"title": "Release notes", "body": "Write the changelog.", "category": "writing", "tags": ["docs"]},
    )
    next(child for child in page.findChildren(QPushButton) if child.objectName() == "PromptNew").click()
    pump()
    assert ctx.prompts.count() == before + 1
    assert any("Release notes" in text for text in texts(page))
    assert page.list_layout.count() - 1 == ctx.prompts.count()


def test_prompt_delete_requires_confirmation(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    window._navigate("prompts")
    pump()
    page = window.prompts_page
    entry = ctx.prompts.list()[0]

    reject_dialogs(monkeypatch)
    page._delete(entry.id)
    assert ctx.prompts.get(entry.id).id == entry.id

    accept_dialogs(monkeypatch)
    page._delete(entry.id)
    pump(20)
    with pytest.raises(NotFoundError):
        ctx.prompts.get(entry.id)


# ------------------------------------------------------------------------ tasks


def test_task_center_shows_a_real_run(ui) -> None:
    window, ctx, _theme = ui
    ctx.tasks.record(
        kind="agent",
        title="Audit the runner",
        status="ok",
        tool_count=3,
        duration_ms=4200,
        steps=[{"index": 1, "kind": "final", "text": "done", "tool": "", "ok": True}],
    )
    window._navigate("tasks")
    pump()
    page = window.tasks_page
    assert page.list_layout.count() - 1 == 1
    shown = texts(page)
    assert any("Audit the runner" in text for text in shown)
    assert not page.empty.isVisible()
    assert page.clear_button.isEnabled()


def test_task_center_filters_by_kind_and_expands_steps(ui) -> None:
    window, ctx, _theme = ui
    ctx.tasks.record(kind="agent", title="Agent job", status="ok")
    ctx.tasks.record(kind="code", title="python main.py", status="error")
    window._navigate("tasks")
    pump()
    page = window.tasks_page
    assert page.list_layout.count() - 1 == 2

    page._on_kind("code")
    pump()
    assert page.list_layout.count() - 1 == 1
    assert any("python main.py" in text for text in texts(page))

    page._on_kind("")
    pump()
    row = page.list_layout.itemAt(0).widget()
    row._toggle()
    assert row.details.isVisible() or row.details.text()


def test_task_clear_is_confirmed_and_removes_rows(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    ctx.tasks.record(kind="agent", title="One", status="ok")
    window._navigate("tasks")
    pump()
    page = window.tasks_page

    reject_dialogs(monkeypatch)
    page.clear_all()
    assert ctx.tasks.count() == 1

    accept_dialogs(monkeypatch)
    page.clear_all()
    pump(20)
    assert ctx.tasks.count() == 0
    assert page.list_layout.count() - 1 == 0
    assert page.empty.isVisible()


# ------------------------------------------------------------------ performance


def test_performance_page_samples_real_numbers(ui) -> None:
    window, ctx, _theme = ui
    window._navigate("performance")
    pump()
    page = window.performance_page
    assert page.cpu_tile.value.text() != ""
    assert page.threads_tile.value.text().isdigit()
    assert page.uptime_tile.value.text() != ""
    assert page.memory_meter.ratio() is None or 0.0 <= page.memory_meter.ratio() <= 1.0
    assert page.updated.text().startswith(tr("performance.updated").split("{")[0])


def test_performance_auto_refresh_toggles_the_timer(ui) -> None:
    window, _ctx, _theme = ui
    window._navigate("performance")
    pump()
    page = window.performance_page
    assert page.auto_toggle.isChecked()
    assert page._timer.isActive()

    page.auto_toggle.setChecked(False)
    pump()
    assert not page._timer.isActive()

    page.auto_toggle.setChecked(True)
    pump()
    assert page._timer.isActive()


# ------------------------------------------------------------- images / video


def test_image_studio_is_honest_and_lists_files(ui) -> None:
    window, ctx, _theme = ui
    window._navigate("images")
    pump()
    page = window.images_page
    assert not page.generate_button.isEnabled(), "nothing may pretend to generate images"
    assert tr("images.unavailable") in texts(page)
    assert page.grid_host.isVisible() is False
    assert page.empty.isVisible()

    (ctx.paths.images_dir / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    page.refresh()
    pump()
    assert page.grid.count() - 1 == 1
    assert page.grid_host.isVisible()
    assert not page.empty.isVisible()


def test_video_studio_is_honest_and_lists_files(ui) -> None:
    window, ctx, _theme = ui
    window._navigate("video")
    pump()
    page = window.video_page
    assert not page.generate_button.isEnabled()
    assert page.empty.isVisible()

    (ctx.paths.videos_dir / "clip.mp4").write_bytes(b"mp4")
    page.refresh()
    pump()
    assert page.grid.count() - 1 == 1
    assert page.grid.itemAt(0).widget().item.name == "clip.mp4"
    assert any("clip.mp4" in text for text in texts(page))


def test_media_delete_removes_the_file_after_confirmation(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    target = ctx.paths.images_dir / "gone.png"
    target.write_bytes(b"png")
    window._navigate("images")
    pump()
    page = window.images_page
    card = page.grid.itemAt(0).widget()

    reject_dialogs(monkeypatch)
    page._delete(card.item)
    assert target.exists()

    accept_dialogs(monkeypatch)
    page._delete(card.item)
    pump(20)
    assert not target.exists()


# -------------------------------------------------------------------------- web


class _FakeWeb:
    search_available = False
    reading_available = True

    def __init__(self, page: WebPage) -> None:
        self._page = page
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebPage:
        self.calls.append(url)
        return self._page


def test_web_page_labels_search_as_unavailable(ui) -> None:
    window, _ctx, _theme = ui
    window._navigate("web")
    pump()
    page = window.web_page
    assert not page.search_field.isEnabled()
    assert not page.search_button.isEnabled()
    assert tr("web.search_unavailable") in texts(page)
    assert page.url_edit.isEnabled()
    assert page.fetch_button.isEnabled()


def test_web_fetch_shows_the_extracted_text(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    result = WebPage(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status=200,
        content_type="text/html",
        title="Example article",
        text="First paragraph.\nSecond paragraph.",
        bytes_received=2048,
        elapsed_ms=42,
    )
    fake = _FakeWeb(result)
    monkeypatch.setattr(ctx, "web", fake)
    window._navigate("web")
    pump()
    page = window.web_page
    page.service = fake
    page.url_edit.setText("example.com/a")
    page.fetch_button.click()
    deadline = time.monotonic() + 3
    while page.text_view.toPlainText() == "" and time.monotonic() < deadline:
        pump(30)
    assert fake.calls == ["example.com/a"]
    assert page.text_view.toPlainText() == "First paragraph.\nSecond paragraph."
    assert page.title_label.text() == "Example article"
    assert page.copy_button.isEnabled() and page.save_button.isEnabled()
    assert page.result_badge.text() == tr("web.fetched")


def test_web_save_writes_a_markdown_output(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    result = WebPage(
        url="https://example.com/b",
        final_url="https://example.com/b",
        status=200,
        content_type="text/html",
        title="Saved page",
        text="Body text.",
        bytes_received=10,
        elapsed_ms=5,
    )
    window._navigate("web")
    pump()
    page = window.web_page
    page.service = _FakeWeb(result)
    page._on_fetched(result)
    before = len(ctx.outputs.list())
    page._save()
    pump(20)
    outputs = ctx.outputs.list()
    assert len(outputs) == before + 1
    assert outputs[0].name.startswith("Saved page")
    assert "Body text." in outputs[0].content
    assert "Source: https://example.com/b" in outputs[0].content


# ---------------------------------------------------------------------- plugins


def test_plugins_page_writes_and_enables_the_example(ui, monkeypatch: pytest.MonkeyPatch) -> None:
    window, ctx, _theme = ui
    window._navigate("plugins")
    pump()
    page = window.plugins_page
    assert page.empty.isVisible()

    page.write_example()
    pump()
    assert page.list_layout.count() - 1 == 1
    plugin = ctx.plugins.discover()[0]
    assert plugin.id == "example-prompt-pack"
    assert any("example-prompt-pack" in text for text in texts(page))

    page._toggle(plugin.id, True)
    pump()
    assert ctx.prompts.from_plugin(plugin.id)
    enabled = ctx.plugins.get(plugin.id)
    assert enabled.enabled

    accept_dialogs(monkeypatch)
    page._toggle(plugin.id, False)
    pump()
    assert ctx.prompts.from_plugin(plugin.id) == []
    assert not ctx.plugins.get(plugin.id).enabled


def test_plugins_page_rejects_a_code_plugin(ui) -> None:
    window, ctx, _theme = ui
    folder = ctx.plugins.ensure_folder() / "runner"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(
        '{"id": "runner", "name": "Runner", "version": "1.0.0", "kind": "tool",'
        ' "prompts": [{"title": "x", "body": "y"}]}',
        encoding="utf-8",
    )
    window._navigate("plugins")
    pump()
    page = window.plugins_page
    shown = " ".join(texts(page))
    assert tr("plugins.unsupported") in shown
    assert tr("plugins.error_code_plugins") in shown
    row = page.list_layout.itemAt(0).widget()
    assert not row.toggle.isEnabled()
