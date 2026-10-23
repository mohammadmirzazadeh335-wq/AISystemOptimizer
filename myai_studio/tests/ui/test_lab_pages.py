"""The five LAB pages driven through the real window.

Every test navigates the actual main window, touches the real widgets and
asserts on the values the page computes — no paint mocks, no fake services.
"""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from myai.i18n import tr
from myai.services.projects import ProjectService
from myai.ui.theme import runtime
from myai.ui.widgets.dialogs import ConfirmDialog

LAB_ROUTES = ["review", "atlas", "context", "appearance", "doctor"]


def pump(ms: int = 60) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


@pytest.fixture()
def project(ui):  # noqa: ANN001
    window, ctx, _theme = ui
    root = ctx.paths.projects_dir / "lab-demo"
    (root / "src").mkdir(parents=True)
    (root / "main.py").write_text(
        "from src.engine import Engine\n\nprint(Engine().run())\n", encoding="utf-8"
    )
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "engine.py").write_text(
        "from .config import Config\n\nclass Engine:\n    def run(self):\n        return 'ok'\n",
        encoding="utf-8",
    )
    (root / "src" / "config.py").write_text(
        "class Config:\n    name = 'demo'\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Lab demo\n\nTiny project.\n", encoding="utf-8")
    service = ProjectService(ctx.paths, ctx.settings)
    window.code_page.set_project(service.open_folder(root))
    pump()
    return window, ctx, root


# ------------------------------------------------------------------ navigation
@pytest.mark.parametrize("route", LAB_ROUTES)
def test_every_lab_route_opens_a_real_page(ui, route: str) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate(route)
    pump()
    page = window._pages[route]
    assert window.stack.currentWidget() is page
    assert window.sidebar.nav_buttons[route].isChecked()
    assert window.header.title.text() == tr(f"{route}.title")
    assert not window.composer.isVisible()


def test_lab_group_is_reachable_without_scrolling_and_has_its_own_header(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    assert {key for key, _icon, _label in window.sidebar.LAB} == set(LAB_ROUTES)
    assert window.sidebar.lab_label.text() == tr("nav.lab")
    window._navigate("doctor")
    pump()
    window.sidebar.nav_scroll.ensureWidgetVisible(window.sidebar.nav_buttons["doctor"], 0, 8)
    pump()
    button = window.sidebar.nav_buttons["doctor"]
    viewport = window.sidebar.nav_scroll.viewport()
    assert button.geometry().top() >= 0
    assert button.mapTo(viewport, button.rect().topLeft()).y() + button.height() <= viewport.height() + 1


def test_command_palette_lists_the_lab_routes(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    actions = {action.id for action in window._palette_actions()}  # noqa: SLF001
    assert {f"go.{route}" for route in LAB_ROUTES} <= actions


# ---------------------------------------------------------------------- review
def test_review_pairs_two_real_files_and_counts_the_diff(project) -> None:  # noqa: ANN001
    window, _ctx, _root = project
    window._navigate("review")
    pump()
    page = window.review_page
    assert page.project is not None
    assert page.left_combo.count() == 5
    page.left_combo.setCurrentText("README.md")
    page.right_combo.setCurrentText("main.py")
    pump()
    assert page.diff_view.diff() is not None
    assert page.diff_view.row_count() > 0
    assert page.added_badge.text() == tr("review.added", count=page.diff_view.diff().stats.added)
    assert page.diff_stack.currentIndex() == 1


def test_review_swap_reverses_the_comparison(project) -> None:  # noqa: ANN001
    window, _ctx, _root = project
    window._navigate("review")
    pump()
    page = window.review_page
    page.left_combo.setCurrentText("main.py")
    page.right_combo.setCurrentText("README.md")
    pump()
    before = page.diff_view.diff().stats
    page._swap()  # noqa: SLF001
    pump()
    after = page.diff_view.diff().stats
    # Swapping the sides swaps additions and removals; equality is unchanged.
    assert after.added == before.removed
    assert after.removed == before.added
    assert after.equal == before.equal
    assert page.left_combo.currentText() == "README.md"
    assert page.right_combo.currentText() == "main.py"


def test_review_patch_preview_then_apply_writes_the_file(project, monkeypatch) -> None:  # noqa: ANN001
    window, _ctx, root = project
    window._navigate("review")
    pump()
    page = window.review_page
    page.target_combo.setCurrentText("src/config.py")
    page.patch_editor.setPlainText(
        "--- a/src/config.py\n+++ b/src/config.py\n@@ -1,2 +1,2 @@\n-class Config:\n+class Settings:\n     name = 'demo'\n"
    )
    page._preview_patch()  # noqa: SLF001
    assert page.apply_button.isEnabled() is True
    assert tr("review.patch_valid", hunks=1) == page.patch_status.text()
    # Nothing may be written by a preview.
    assert "class Config" in (root / "src" / "config.py").read_text(encoding="utf-8")
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page._apply_patch()  # noqa: SLF001
    pump()
    assert "class Settings" in (root / "src" / "config.py").read_text(encoding="utf-8")


def test_review_refuses_a_patch_that_does_not_apply(project, monkeypatch) -> None:  # noqa: ANN001
    window, _ctx, root = project
    window._navigate("review")
    pump()
    page = window.review_page
    page.target_combo.setCurrentText("src/config.py")
    page.patch_editor.setPlainText(
        "--- a\n+++ b\n@@ -1,2 +1,2 @@\n-this line does not exist\n+replacement\n"
    )
    page._preview_patch()  # noqa: SLF001
    assert page.apply_button.isEnabled() is False
    prefix = tr("review.patch_invalid", reason="|").split("|")[0]
    assert page.patch_status.text().startswith(prefix)
    assert "Hunk" in page.patch_status.text() or "hunk" in page.patch_status.text()
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    page._apply_patch()  # noqa: SLF001
    assert "class Config" in (root / "src" / "config.py").read_text(encoding="utf-8")


def test_review_without_a_project_shows_the_empty_state(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("review")
    pump()
    page = window.review_page
    page.set_project(None)
    assert page.project is None
    assert page.diff_stack.currentIndex() == 0
    assert page.project_badge.text() == tr("review.no_project")


# ----------------------------------------------------------------------- atlas
def test_atlas_draws_the_real_import_graph(project) -> None:  # noqa: ANN001
    window, _ctx, _root = project
    window._navigate("atlas")
    pump()
    page = window.atlas_page
    atlas = page.atlas
    assert atlas is not None
    edges = {(edge.source, edge.target) for edge in atlas.edges}
    assert ("main.py", "src/engine.py") in edges
    assert ("src/engine.py", "src/config.py") in edges
    assert page.canvas.node_count() == len(atlas.nodes)
    assert page.edges_stat.value.text() == str(len(atlas.edges))
    assert page.files_stat.value.text() == "5"


def test_clicking_a_hub_opens_the_file_in_code_studio(project) -> None:  # noqa: ANN001
    window, _ctx, _root = project
    window._navigate("atlas")
    pump()
    window.atlas_page._node_activated("src/config.py")  # noqa: SLF001
    pump()
    assert window.stack.currentWidget() is window.code_page
    assert window.code_page.current_file == "src/config.py"


def test_atlas_without_a_project_asks_for_one(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window.code_page.set_project(None)
    window._navigate("atlas")
    pump()
    page = window.atlas_page
    assert page.atlas is None
    assert page.empty.isVisibleTo(page)
    assert page.graph_stack.isVisibleTo(page) is False
    assert page.project_badge.text() == tr("atlas.no_project")


# --------------------------------------------------------------------- context
def test_context_map_measures_the_open_conversation(project) -> None:  # noqa: ANN001
    window, ctx, _root = project
    conversation = ctx.conversations.create("Measured", select=False)
    ctx.conversations.add_message(conversation.id, "user", "Explain the engine.")
    ctx.conversations.add_message(conversation.id, "assistant", "It returns a string.")
    window._current = ctx.conversations.get(conversation.id)
    window._navigate("context")
    pump()
    page = window.context_page
    assert page.report is not None
    assert page.report.history_messages == 2
    assert page.messages_fact[1].text() == "2"
    assert page.used_label.text() == tr("context.used", tokens=f"{page.report.total_tokens:,}")
    assert page.donut.isVisible()
    assert page.rows_box.count() >= 2


def test_context_map_explains_an_empty_state(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._current = None
    window._navigate("context")
    pump()
    page = window.context_page
    assert page.report is None
    assert page.empty_wrap.isVisibleTo(page)
    assert page.donut.isVisibleTo(page) is False


def test_context_map_notices_a_large_history(project) -> None:  # noqa: ANN001
    window, ctx, _root = project
    conversation = ctx.conversations.create("Big", select=False)
    ctx.conversations.add_message(conversation.id, "user", "x" * 8000)
    window._current = ctx.conversations.get(conversation.id)
    window._navigate("context")
    pump()
    page = window.context_page
    assert page.report is not None
    largest = page.report.largest()
    assert largest is not None and largest.category == "history"
    assert largest.chars >= 8000


# ------------------------------------------------------------------ appearance
def test_appearance_audits_the_current_theme(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("appearance")
    pump()
    page = window.appearance_page
    entries = page._audit_entries()  # noqa: SLF001
    assert len(entries) == 7
    body = next(entry for entry in entries if entry["label"] == "appearance.audit_body")
    assert body["ratio"] >= 7.0
    assert page.audit_grid.count() == 4 * len(entries)


def test_choosing_a_custom_colour_changes_the_candidate_and_hex(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("appearance")
    pump()
    page = window.appearance_page
    page.set_candidate("#12ab88", accent_key="custom")
    pump()
    assert page.candidate() == "#12ab88"
    assert page.hex_edit.text() == "#12ab88"
    assert page.apply_button.isEnabled()
    hue, saturation, brightness = page.hue_slider.value(), page.saturation_slider.value(), page.brightness_slider.value()
    assert (hue, saturation, brightness) != (0, 0, 0)


def test_applying_an_accent_updates_the_theme(ui) -> None:  # noqa: ANN001
    window, ctx, theme = ui
    window._navigate("appearance")
    pump()
    page = window.appearance_page
    page.set_candidate("#12ab88", accent_key="custom")
    page.apply_candidate()
    pump()
    assert ctx.settings.get("ui.accent") == "custom"
    assert ctx.settings.get("ui.accent_custom") == "#12ab88"
    assert theme.theme.color("accent").lower() == "#12ab88"


def test_builtin_accent_and_reset(ui) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    window._navigate("appearance")
    pump()
    page = window.appearance_page
    page._swatch_clicked("violet")  # noqa: SLF001
    page.apply_candidate()
    assert ctx.settings.get("ui.accent") == "violet"
    page.reset()
    pump()
    assert ctx.settings.get("ui.accent") == "azure"
    assert ctx.settings.get("ui.accent_custom") == ""


def test_slider_drag_moves_the_candidate(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("appearance")
    pump()
    page = window.appearance_page
    before = page.candidate()
    page.hue_slider.setValue((page.hue_slider.value() + 90) % 360)
    pump()
    assert page.candidate() != before
    assert page.hex_edit.text() == page.candidate()


# ---------------------------------------------------------------------- doctor
def test_doctor_runs_every_check_and_reports_a_score(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("doctor")
    pump()
    page = window.doctor_page
    report = page.run_now()
    pump()
    assert len(report.checks) == 14
    assert report.score == page.gauge.score()
    assert page.ok_badge.text() == tr("doctor.count_ok", count=report.counts["ok"])
    assert page.groups_box.count() >= 3
    names = [label.text() for label in page.findChildren(QLabel)]
    assert tr("doctor.check_database") in names


def test_doctor_copy_puts_the_text_report_on_the_clipboard(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    window._navigate("doctor")
    pump()
    page = window.doctor_page
    page.run_now()
    page._copy()  # noqa: SLF001
    clip = QApplication.clipboard().text()
    assert "score:" in clip and "database" in clip


def test_doctor_reports_a_broken_workspace(ui, monkeypatch) -> None:  # noqa: ANN001
    window, ctx, _theme = ui
    window._navigate("doctor")
    pump()
    page = window.doctor_page
    monkeypatch.setattr(ctx.db, "integrity_check", lambda: "corrupt")
    report = page.run_now()
    failing = [check for check in report.checks if check.status == "fail"]
    assert failing and failing[0].key == "database"
    assert report.verdict == "needs_care"
    assert page.verdict_label.text() == tr("doctor.verdict_needs_care")


# ------------------------------------------------------------- collapsed rail
def test_collapsed_rail_keeps_every_lab_tile_visible_and_icon_only(ui) -> None:  # noqa: ANN001
    window, _ctx, _theme = ui
    sidebar = window.sidebar
    sidebar.set_collapsed(True, animate=False)
    pump()
    assert sidebar.lab_label.isVisibleTo(sidebar) is False
    for tile in sidebar.lab_tiles:
        assert tile.isVisibleTo(sidebar)
        assert tile.width() >= 40
        assert tile.height() == runtime.px(40)
        assert tile.rect().right() <= sidebar.width()
    # Back to the two-column grid when expanded again.
    sidebar.set_collapsed(False, animate=False)
    pump()
    assert sidebar.lab_label.isVisibleTo(sidebar)
    assert sidebar.lab_tiles[0].height() == runtime.px(30)
    positions = {sidebar.lab_grid.getItemPosition(sidebar.lab_grid.indexOf(tile))[:2] for tile in sidebar.lab_tiles}
    assert len(positions) == len(sidebar.lab_tiles)
