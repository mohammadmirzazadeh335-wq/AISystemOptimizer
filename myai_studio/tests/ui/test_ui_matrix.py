"""UI state matrix.

Every major surface is exercised in both languages, both themes, with the
sidebar open and collapsed, at three window sizes. The assertions are geometric
(does the widget physically fit?) rather than "did it render without raising",
because the defects found during Phase 1 were layout and text problems that no
exception would have caught.
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QFrame, QLabel, QWidget

from myai.i18n import tr
from myai.services.backup import BackupService
from myai.ui.views.placeholder import ROUTES
from myai.ui.views.settings_dialog import CATEGORIES, SettingsDialog

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
LANGUAGES = ["fa", "en"]
THEMES = ["midnight", "dawn"]
SIZES = [QSize(1280, 720), QSize(1440, 900), QSize(1920, 1080)]


def _visible(widget: QWidget) -> bool:
    return widget.isVisible() and widget.width() > 0 and widget.height() > 0


def _inside(child: QWidget, parent: QWidget, tolerance: int = 2) -> tuple[bool, str]:
    top_left = child.mapTo(parent, child.rect().topLeft())
    bottom_right = child.mapTo(parent, child.rect().bottomRight())
    ok = (
        top_left.x() >= -tolerance
        and top_left.y() >= -tolerance
        and bottom_right.x() <= parent.width() + tolerance
        and bottom_right.y() <= parent.height() + tolerance
    )
    return ok, f"{type(child).__name__} {top_left}..{bottom_right} in {parent.width()}x{parent.height()}"


def _scrollable(widget: QWidget, root: QWidget) -> bool:
    """True when the widget lives inside a scroll area (clipping is intended)."""
    parent = widget.parentWidget()
    while parent is not None and parent is not root:
        if isinstance(parent, QAbstractScrollArea):
            return True
        parent = parent.parentWidget()
    return False


def _raw_keys(root: QWidget) -> list[str]:
    found = []
    for label in root.findChildren(QLabel):
        text = label.text().strip()
        if text and _visible(label) and KEY_PATTERN.fullmatch(text):
            found.append(text)
    return found


def _open(window, ctx, conversation_id: int) -> None:  # noqa: ANN001
    window.open_conversation(conversation_id)
    QApplication.processEvents()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("theme_key", THEMES)
@pytest.mark.parametrize("collapsed", [False, True], ids=["sidebar-open", "sidebar-collapsed"])
def test_conversation_screen_states(ui, language: str, theme_key: str, collapsed: bool) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Compiler sandbox notes", select=False)
    ctx.conversations.add_message(conversation.id, "user", "Draft a safe sandbox policy for generated C code.")
    ctx.conversations.add_message(
        conversation.id,
        "assistant",
        "Use a jailed working directory, a wall-clock limit of ten seconds, and never install packages.",
    )
    ctx.settings.update({"ui.language": language, "ui.theme": theme_key})
    window.sidebar.set_collapsed(collapsed, animate=False)
    window.resize(1440, 900)
    QApplication.processEvents()
    _open(window, ctx, conversation.id)
    QApplication.processEvents()

    assert not _raw_keys(window), _raw_keys(window)
    for name, widget in (
        ("sidebar", window.sidebar),
        ("header", window.header),
        ("chat", window.chat_view),
        ("composer", window.composer),
        ("inspector", window.inspector),
    ):
        assert _visible(widget), name
    assert window.sidebar.width() == (88 if collapsed else window.sidebar._expanded_width_px) or collapsed is False
    expected = Qt.LayoutDirection.RightToLeft if language == "fa" else Qt.LayoutDirection.LeftToRight
    assert QApplication.layoutDirection() == expected
    assert theme.theme.key == theme_key
    assert theme.theme.is_dark == (theme_key == "midnight")


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("route", list(ROUTES))
def test_every_route_renders_in_both_languages(ui, language: str, route: str) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.language", language)
    QApplication.processEvents()
    window._navigate(route)
    QApplication.processEvents()
    assert window.stack.currentWidget() is window.placeholder
    assert not window.composer.isVisible()
    assert not _raw_keys(window.placeholder), _raw_keys(window.placeholder)

    title = window.header.title.text()
    assert title and not KEY_PATTERN.fullmatch(title)
    assert title == tr(ROUTES[route]["title"])

    # The feature list must fit inside the card, not be clipped by it.
    for child in window.placeholder.findChildren(QWidget):
        if not _visible(child) or child.width() < 40:
            continue
        if isinstance(child, QLabel) and child.wordWrap():
            continue
        if _scrollable(child, window.placeholder):
            continue
        parent = child.parentWidget()
        if parent is None or parent is window.placeholder:
            continue
        ok, detail = _inside(child, parent)
        assert ok or child.height() > parent.height(), detail

    window._go_chat()
    QApplication.processEvents()
    assert window.composer.isVisible()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("theme_key", THEMES)
def test_settings_dialog_categories(ui, language: str, theme_key: str) -> None:
    window, ctx, theme = ui
    ctx.settings.update({"ui.language": language, "ui.theme": theme_key})
    QApplication.processEvents()
    dialog = SettingsDialog(
        window,
        ctx.settings,
        theme,
        ctx.paths,
        ctx.db,
        ctx.secrets,
        BackupService(ctx.paths, ctx.db, ctx.settings),
    )
    dialog.show()
    QApplication.processEvents()
    try:
        for key, *_ in CATEGORIES:
            dialog._select(key)
            QApplication.processEvents()
            page = dialog._pages[key]
            assert page.height() > 0, key
            assert not _raw_keys(page), (key, _raw_keys(page))
            # The page must never be wider than its viewport (horizontal scroll is off).
            assert page.widget().width() <= page.viewport().width() + 2, key
        dialog._select("appearance")
        QApplication.processEvents()
        assert dialog.close_button.text() == tr("dialog.close")
    finally:
        dialog.reject()
        QApplication.processEvents()


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s.width()}x{s.height()}")
@pytest.mark.parametrize("language", LANGUAGES)
def test_layout_fits_at_multiple_window_sizes(ui, size: QSize, language: str) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.language", language)
    conversation = ctx.conversations.create("A rather long conversation title that should not break the header", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    window.resize(size.width(), size.height())
    QApplication.processEvents()
    _open(window, ctx, conversation.id)
    QApplication.processEvents()

    assert window.size() == size
    # Header: title and subtitle inside the bar.
    for label in (window.header.title, window.header.subtitle):
        top = label.mapTo(window.header, label.rect().topLeft()).y()
        assert top >= 0 and top + label.height() <= window.header.height() + 1, (
            top, label.height(), window.header.height())
    # Composer inside the centre column.
    centre = window.header.parentWidget()
    ok, detail = _inside(window.composer, centre)
    assert ok, detail
    # Inspector cards inside the panel (the panel itself scrolls vertically).
    cards = [c for c in window.inspector.findChildren(QFrame) if c.property("panel") == "card"]
    assert cards
    for card in cards:
        assert card.width() > 0 and card.width() <= window.inspector.width() + 2, card.width()
    # Chat area keeps a usable width.
    assert window.chat_view.width() >= 420


def test_no_widget_overflows_the_window(ui) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Overflow check", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    window.resize(1280, 720)
    _open(window, ctx, conversation.id)
    QApplication.processEvents()
    for child in window.findChildren(QWidget):
        if not _visible(child) or child.isWindow():
            continue
        if _scrollable(child, window):
            continue
        ok, detail = _inside(child, window)
        assert ok, detail


def test_high_dpi_scale_factor_keeps_layout_sane(qapp, home) -> None:
    """Emulate a scaled display: geometry must stay inside the window."""
    from myai.context import build_context
    from myai.ui.main_window import MainWindow
    from myai.ui.theme import runtime
    from myai.ui.theme.manager import ThemeManager

    ctx = build_context(home, log=False)
    ctx.boot()
    try:
        ctx.settings.set("ui.font_scale", 1.25)
        theme = ThemeManager(qapp, ctx.settings, ctx.paths)
        runtime.set_manager(theme)
        theme.apply()
        window = MainWindow(ctx, theme)
        window.resize(1366, 768)
        window.show()
        QApplication.processEvents()
        assert runtime.scale() >= 1.2
        assert window.inspector.width() >= 340
        assert window.sidebar.width() > 200
        assert not _raw_keys(window)
        for child in window.findChildren(QWidget):
            if not _visible(child) or child.isWindow():
                continue
            if _scrollable(child, window):
                continue
            ok, detail = _inside(child, window)
            assert ok, detail
        window.close()
        QApplication.processEvents()
    finally:
        ctx.shutdown()
