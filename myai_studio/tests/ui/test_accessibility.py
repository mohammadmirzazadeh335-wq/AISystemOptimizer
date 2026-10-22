"""Keyboard and screen-reader surface for every page.

These assertions are deliberately mechanical: a control that cannot be reached by
Tab, or that announces an empty name, fails the test even if it looks fine.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from myai.ui.main_window import AI_ROUTES

SKIP_TYPES = (QWidget,)


def focusable_widgets(root: QWidget) -> list[QWidget]:
    out: list[QWidget] = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisible() or not widget.isEnabled():
            continue
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
            continue
        if isinstance(widget, QLineEdit | QPlainTextEdit | QTextEdit | QComboBox | QAbstractButton):
            out.append(widget)
    return out


def name_of(widget: QWidget) -> str:
    name = widget.accessibleName().strip()
    if name:
        return name
    text = getattr(widget, "text", None)
    if callable(text):
        value = str(text() or "").strip()
        if value:
            return value
    return widget.toolTip().strip()


@pytest.mark.parametrize("route", sorted(AI_ROUTES))
def test_every_page_is_named_for_screen_readers(ui, route: str) -> None:
    window, ctx, _theme = ui
    window._navigate(route)
    QApplication.processEvents()
    page = window._pages[route]
    assert page.accessibleName().strip(), f"{route} page has no accessible name"
    assert window.header.title.text().strip()


@pytest.mark.parametrize("route", sorted(AI_ROUTES))
def test_every_focusable_control_has_a_name(ui, route: str) -> None:
    window, ctx, _theme = ui
    window._navigate(route)
    QApplication.processEvents()
    page = window._pages[route]
    # Cards and rows are created lazily; give the page one more paint cycle.
    page.grab()
    QApplication.processEvents()
    unnamed = [type(widget).__name__ for widget in focusable_widgets(page) if not name_of(widget)]
    assert not unnamed, f"{route}: unnamed focusable controls {unnamed}"


@pytest.mark.parametrize("route", ["chat", "prompts", "tasks", "plugins", "performance"])
def test_tab_never_leaves_the_window(ui, route: str) -> None:
    window, ctx, _theme = ui
    if route == "chat":
        window._go_chat()
    else:
        window._navigate(route)
    QApplication.processEvents()
    window.activateWindow()
    window.setFocus()
    QApplication.processEvents()

    for _ in range(40):
        QTest.keyClick(window, Qt.Key.Key_Tab)
        QApplication.processEvents()
        focused = QApplication.focusWidget()
        assert focused is not None, "Tab moved focus out of the application"
        assert window.isAncestorOf(focused) or focused is window, (
            f"{route}: focus escaped to {type(focused).__name__}"
        )


@pytest.mark.parametrize("route", ["prompts", "tasks", "plugins"])
def test_shift_tab_also_stays_inside(ui, route: str) -> None:
    window, ctx, _theme = ui
    window._navigate(route)
    QApplication.processEvents()
    for _ in range(20):
        QTest.keyClick(window, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        QApplication.processEvents()
        focused = QApplication.focusWidget()
        assert focused is not None
        assert window.isAncestorOf(focused) or focused is window


def test_every_sidebar_entry_is_a_tab_stop(ui) -> None:
    window, _ctx, _theme = ui
    for route, button in window.sidebar.nav_buttons.items():
        assert button.focusPolicy() != Qt.FocusPolicy.NoFocus, route
        assert name_of(button), route


def test_dialog_closes_with_escape(qapp) -> None:
    from myai.ui.widgets.dialogs import ConfirmDialog

    host = QWidget()
    host.resize(900, 600)
    host.show()
    dialog = ConfirmDialog(
        host,
        "Delete this?",
        "Nothing happens unless you confirm.",
        confirm_text="Delete",
        cancel_text="Cancel",
    )
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert not dialog.isVisible(), "Escape must dismiss a modal"
    host.close()
    host.deleteLater()
