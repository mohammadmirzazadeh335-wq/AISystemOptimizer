"""Lazy pages and the foldable, filterable navigation.

Three complaints are pinned here:

* the window took seconds to appear because every page was built up front;
* the left column was a flat list of nineteen rows with nothing to fold;
* finding "Usage" meant scrolling, not typing.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from myai.i18n import tr


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def test_the_window_starts_with_only_the_chat_view_built(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    # Nothing but the chat is built; ``_pages`` fills as pages are opened.
    assert window._pages == {}
    assert window.stack.count() == 1


def test_opening_a_page_builds_it_and_keeps_the_object(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    window._navigate("usage")
    pump()
    built = window._pages
    assert set(built) == {"usage"}
    page = built["usage"]
    window._navigate("chat")
    window._navigate("usage")
    pump()
    assert window._pages["usage"] is page
    assert window.stack.count() == 2


def test_a_language_switch_does_not_build_every_page(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    window._navigate("prompts")
    pump()
    context.settings.set("ui.language", "fa")
    pump()
    window._retranslate()
    pump()
    # The page that exists is relabelled in place; the other eighteen are not
    # built just to be translated.
    assert set(window._pages) == {"prompts"}
    assert window._pages["prompts"].lead.text() == tr("prompts.subtitle")


def test_a_group_can_be_folded_and_unfolded_without_losing_its_tiles(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    sidebar = window.sidebar
    sidebar._set_group_open("library", True)
    header = sidebar.library_label
    host = sidebar.library_host
    assert header.isVisible() and host.isVisible()

    QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=QPoint(header.width() // 2, header.height() // 2))
    pump()
    assert header.is_open() is False
    assert host.isVisibleTo(sidebar) is False

    QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=QPoint(header.width() // 2, header.height() // 2))
    pump()
    assert header.is_open() is True
    assert host.isVisibleTo(sidebar) is True
    assert all(tile.isVisibleTo(sidebar) for tile in sidebar.library_tiles)


def test_navigating_into_a_folded_group_opens_it(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    sidebar = window.sidebar
    sidebar._set_group_open("lab", False)
    pump()
    window._navigate("doctor")
    pump()
    assert sidebar.lab_label.is_open() is True
    assert sidebar.nav_buttons["doctor"].isVisible()


def test_the_tool_filter_narrows_the_tiles_and_says_when_nothing_matches(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    sidebar = window.sidebar

    # Both the visible label and the route name match, so the filter works in
    # either language.
    for query in ("usage", tr("nav.usage")):
        sidebar.tools_filter.set_text(query)
        pump()
        assert sidebar.nav_buttons["usage"].isVisibleTo(sidebar), query
        assert not sidebar.nav_buttons["images"].isVisibleTo(sidebar), query

    sidebar.tools_filter.set_text("no such tool")
    pump()
    assert sidebar.no_tools_match.isVisibleTo(sidebar)

    sidebar.tools_filter.set_text("")
    pump()
    assert sidebar.nav_buttons["images"].isVisibleTo(sidebar)
    assert sidebar.no_tools_match.isVisibleTo(sidebar) is False
    assert sidebar.library_label.isVisibleTo(sidebar)
