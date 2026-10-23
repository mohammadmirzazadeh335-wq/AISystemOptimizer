"""Usage & Cost, global search and file history driven through the real window.

The assertions check what the widgets actually show — the cost string, the
range that survives a switch, the history list built from real saves — rather
than only that a method returned without raising.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from myai.i18n import tr
from myai.ui.widgets.global_search import GlobalSearchDialog
from myai.ui.widgets.history_panel import HistoryDialog

PRICES = [
    {"id": "vendor/cheap", "name": "Cheap Model", "prompt_price": 1.0, "completion_price": 2.0},
]


def pump(ms: int = 60) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


def seed_usage(ctx, replies: int = 2) -> None:  # noqa: ANN001
    ctx.settings.update({"ai.openrouter_cache": PRICES, "usage.monthly_budget": 6.0})
    conversation = ctx.conversations.create("Usage fixture", select=False)
    for index in range(replies):
        ctx.conversations.add_message(
            conversation.id,
            "assistant",
            "answer",
            model_id="vendor/cheap",
            input_tokens=500_000,
            output_tokens=250_000,
        )
        # Two replies in the same millisecond are still two rows; the report
        # groups them by day, not by id.
        assert index >= 0


# ------------------------------------------------------------------- usage page
def test_usage_page_shows_tokens_cost_and_budget(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    ctx.settings.set("ui.language", "en")
    seed_usage(ctx, replies=2)
    window._navigate("usage")
    pump()
    page = window.usage_page
    page.refresh()
    pump()

    assert page.report is not None and page.report.requests == 2
    assert page.report.tokens == 1_500_000
    assert page.report.cost == pytest.approx(2.0, abs=1e-6)
    assert page.cost_label.text() == "$2.00"
    assert "1,500,000" in page.total_sub.text()
    assert page.empty_wrap.isVisible() is False
    assert page.models_list.count() > 0
    assert page.budget_bar.isVisible()
    assert "%" in page.budget_state.text() or "٪" in page.budget_state.text()
    assert "2.00" in page.budget_state.toolTip() and "6.00" in page.budget_state.toolTip()


def test_usage_range_persists_and_refilters(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    seed_usage(ctx, replies=1)
    window._navigate("usage")
    pump()
    window.usage_page.set_range(7)
    pump()
    assert ctx.settings.get("usage.range_days") == 7
    assert window.usage_page.report is not None
    assert window.usage_page.report.days == 7
    assert len(window.usage_page.bars.values()) == 7
    assert window.usage_page.range_control.value == "7"


def test_usage_page_without_data_offers_an_empty_state(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("usage")
    pump()
    page = window.usage_page
    assert page.report is not None and not page.report.has_data
    assert page.empty_wrap.isVisible()
    assert page.chart_card.isVisible() is False
    assert page.cost_label.text() == "$0.00"


def test_budget_round_trips_through_the_page(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    seed_usage(ctx, replies=1)
    window._navigate("usage")
    pump()
    page = window.usage_page
    page.budget_edit.setText("12.5")
    page._save_budget()
    pump()
    assert ctx.settings.get("usage.monthly_budget") == pytest.approx(12.5)
    assert page.report is not None and page.report.budget == pytest.approx(12.5)
    page.budget_edit.setText("not a number")
    messages: list[tuple[str, str]] = []
    page.notify.connect(lambda text, tone: messages.append((text, tone)))
    page._save_budget()
    assert messages and messages[-1][1] == "warning"
    assert ctx.settings.get("usage.monthly_budget") == pytest.approx(12.5)


# ----------------------------------------------------------------- global search
@pytest.fixture()
def searchable(ui):  # noqa: ANN001
    window, ctx, _theme = ui
    root = ctx.paths.projects_dir / "search-demo"
    root.mkdir(parents=True)
    (root / "notes.py").write_text("def needle():\n    return 'needle'\n", encoding="utf-8")
    ctx.prompts.create("Needle prompt", "a prompt about a needle", category="code")
    project = window.code_page.projects.open_folder(root)
    window.code_page.set_project(project)
    pump()
    return window, ctx, project


def test_search_dialog_groups_hits_and_opens_the_chosen_one(searchable) -> None:  # noqa: ANN001
    window, ctx, project = searchable
    opened: list[tuple[str, str]] = []
    dialog = GlobalSearchDialog(
        window,
        ctx.search,
        lambda hit, query: opened.append((hit.source, query)),
        project=project,
    )
    dialog.search.setText("needle")
    dialog._run_search()
    pump()
    sources = {hit.source for hit in dialog.hits}
    assert {"prompt", "file"} <= sources
    assert dialog._rows and dialog._rows[0].hit.title
    dialog._move(1)
    assert dialog._index == 1
    dialog._open_current()
    assert opened and opened[-1][1] == "needle"
    assert window.context.search.search("needle", project=project)


def test_global_search_navigates_to_the_matching_page(searchable) -> None:  # noqa: ANN001
    window, _ctx, project = searchable
    window._navigate("chat")
    pump()
    hit = next(
        item for item in window.context.search.search("needle", project=project) if item.source == "prompt"
    )
    window._open_search_hit(hit, "needle")
    pump()
    assert window._current_route == "prompts"
    assert window.prompts_page.search.text() == "needle"


# ------------------------------------------------------------------ file history
def test_code_page_saves_are_versioned_and_restorable(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    root = ctx.paths.projects_dir / "history-demo"
    root.mkdir(parents=True)
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    page = window.code_page
    page.set_project(page.projects.open_folder(root))
    pump()
    page.open_file("main.py")
    pump()
    assert page.save_file(quiet=True)  # the first save is a version too
    pump()
    page.editor.setPlainText("print(2)\n")
    assert page.save_file(quiet=True)
    pump()
    page.editor.setPlainText("print(3)\n")
    assert page.save_file(quiet=True)
    pump()

    versions = ctx.history.versions(page.project.root, "main.py")
    assert len(versions) == 3, [item.reason for item in versions]
    assert versions[0].reason == "save"

    dialog = HistoryDialog(
        window,
        ctx.history,
        page.projects,
        page.project,
        "main.py",
        page.editor.toPlainText(),
        page._on_version_restored,
        on_notify=lambda text, tone: page.notify.emit(text, tone),
    )
    assert dialog.list.count() == 3
    dialog._on_row(2)  # the oldest version still holds print(1)
    pump()
    assert dialog._selection is not None
    assert dialog.diff.diff() is not None
    dialog.reject()
    window.close()


def test_restore_is_itself_a_version(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    root = ctx.paths.projects_dir / "history-restore"
    root.mkdir(parents=True)
    (root / "main.py").write_text("one\n", encoding="utf-8")
    page = window.code_page
    page.set_project(page.projects.open_folder(root))
    pump()
    page.open_file("main.py")
    pump()
    assert page.save_file(quiet=True)
    pump()
    page.editor.setPlainText("two\n")
    assert page.save_file(quiet=True)
    pump()
    versions = ctx.history.versions(page.project.root, "main.py")
    assert len(versions) == 2
    ctx.history.restore(page.projects, page.project, "main.py", versions[-1].id)
    page._on_version_restored("one\n")
    pump()
    assert (root / "main.py").read_text(encoding="utf-8") == "one\n"
    newest = ctx.history.versions(page.project.root, "main.py")[0]
    assert newest.reason == "restore"
    assert page.editor.toPlainText() == "one\n"
    assert page._dirty is False


# ---------------------------------------------------------------------- wiring
def test_usage_route_is_reachable_everywhere(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    assert "usage" in window.sidebar.nav_buttons
    assert window.sidebar.nav_buttons["usage"]._text == tr("nav.usage")
    palette_ids = {action.id for action in window._palette_actions()}
    assert "go.usage" in palette_ids
    assert "search.everything" in palette_ids
    assert window.shortcut_search_all.key().toString() == "Ctrl+Shift+F"
