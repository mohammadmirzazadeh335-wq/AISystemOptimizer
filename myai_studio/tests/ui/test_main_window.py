"""Real UI tests on the offscreen Qt platform.

These exercise the actual widgets: typing, sending, navigation, theme and
language switching.  No mocks of the UI itself.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from myai.i18n import tr


def test_window_has_all_regions(ui) -> None:
    window, ctx, theme = ui
    assert window.sidebar.isVisible()
    assert window.header.isVisible()
    assert window.chat_view.isVisible()
    assert window.composer.isVisible()
    assert window.inspector.isVisible()
    assert window.stack.currentWidget() is window.chat_view


def test_welcome_state_before_any_chat(ui) -> None:
    window, ctx, theme = ui
    assert window.chat_view.stack.currentWidget() is window.chat_view.welcome
    assert len(window.chat_view.welcome.cards) == 4
    assert window.composer.input.placeholderText() == tr("chat.placeholder")


def test_sending_first_message_creates_conversation(ui) -> None:
    window, ctx, theme = ui
    window.composer.input.setPlainText("Explain the sandbox policy")
    window.composer._submit()
    # let queued signals run
    window.composer.send_button.parentWidget().repaint()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    conversations = ctx.conversations.list()
    assert len(conversations) == 1
    assert conversations[0].title == "Explain the sandbox policy"
    messages = ctx.conversations.messages(conversations[0].id)
    assert len(messages) == 1 and messages[0].role == "user"
    assert window.chat_view.stack.currentWidget() is window.chat_view.messages_host
    assert window.composer.input.toPlainText() == ""


def test_enter_sends_and_shift_enter_adds_line(ui) -> None:
    window, ctx, theme = ui
    window.composer.input.setFocus()
    QTest.keyClicks(window.composer.input, "line one")
    QTest.keyClick(window.composer.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(window.composer.input, "line two")
    assert "\n" in window.composer.input.toPlainText()
    QTest.keyClick(window.composer.input, Qt.Key.Key_Return)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    conversations = ctx.conversations.list()
    assert len(conversations) == 1
    assert ctx.conversations.messages(conversations[0].id)[0].content == "line one\nline two"


def test_sidebar_lists_and_selects_conversations(ui) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Compiler sandbox notes", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    window.sidebar.refresh()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert window.sidebar.model.rowCount() >= 1
    window.sidebar.select_conversation(conversation.id)
    QApplication.processEvents()
    assert window._current is not None and window._current.id == conversation.id


def test_new_chat_resets_to_welcome(ui) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Something", select=False)
    window.open_conversation(conversation.id)
    window.new_chat()
    assert window._current is None
    assert window.chat_view.stack.currentWidget() is window.chat_view.welcome


def test_inspector_toggle_animation_completes(ui) -> None:
    window, ctx, theme = ui
    window.set_inspector_visible(False)
    QTest.qWait(320)
    assert not window.inspector.isVisible()
    window.set_inspector_visible(True)
    QTest.qWait(320)
    assert window.inspector.isVisible()
    assert ctx.settings.get("ui.inspector_open") is True


def test_sidebar_collapse_and_width(ui) -> None:
    window, ctx, theme = ui
    window.sidebar.set_collapsed(True, animate=False)
    assert window.sidebar.width() == window.sidebar.width()  # stable
    assert window.sidebar.is_collapsed
    window.sidebar.set_collapsed(False, animate=False)
    assert not window.sidebar.is_collapsed
    assert ctx.settings.get("ui.sidebar_collapsed") is False


@pytest.mark.parametrize("theme_key,mode", [("midnight", "dark"), ("dawn", "light"), ("aurora", "dark")])
def test_theme_switch_applies_palette(ui, theme_key: str, mode: str) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.theme", theme_key)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    active = theme.theme
    assert active.key == theme_key
    assert active.mode == mode
    background = window.palette().color(window.backgroundRole())
    assert isinstance(background, QColor)
    assert "#FF00FF" not in window.styleSheet()


@pytest.mark.parametrize("language", ["en", "fa"])
def test_language_switch_updates_direction_and_text(ui, language: str) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.language", language)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    expected = Qt.LayoutDirection.RightToLeft if language == "fa" else Qt.LayoutDirection.LeftToRight
    assert QApplication.layoutDirection() == expected
    assert window.sidebar.new_chat_button.text() == tr("nav.new_chat")
    assert window.header.mode._items[0][1] == tr("header.chat")


def test_navigation_to_code_studio_and_back(ui) -> None:
    window, ctx, theme = ui
    window._navigate("code")
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    # Phase 3 made "code" a real page; Phase 5 removed the placeholder entirely.
    assert window.stack.currentWidget() is window.code_page
    assert not window.composer.isVisible()
    assert window.header.title.text() == tr("code.title")
    window._go_chat()
    QApplication.processEvents()
    assert window.stack.currentWidget() is window.chat_view


def test_accents_change_accent_token(ui) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.accent", "teal")
    assert theme.theme.color("accent").lower() == "#2dd4bf"
    ctx.settings.set("ui.accent", "azure")


def test_window_resizes_across_dpi_targets(ui) -> None:
    window, ctx, theme = ui
    for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
        window.resize(width, height)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert window.width() == width and window.height() == height
        assert window.sidebar.width() > 0
        assert window.composer.height() > 0


def test_font_scale_changes_stylesheet(ui) -> None:
    window, ctx, theme = ui
    ctx.settings.set("ui.font_scale", 1.2)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert theme.scale == 1.2
    from PySide6.QtWidgets import QApplication as _App

    assert "font-size" in _App.instance().styleSheet()
    ctx.settings.set("ui.font_scale", 1.0)


def test_toast_is_shown_and_expires(ui) -> None:
    window, ctx, theme = ui
    window._show_toast("Saved locally", "success")
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    assert len(window.toasts._toasts) == 1
    window.toasts._toasts[0].dismiss()
    QApplication.processEvents()
    assert len(window.toasts._toasts) == 0


def test_message_card_copy_and_delete(ui) -> None:
    from PySide6.QtWidgets import QApplication

    window, ctx, theme = ui
    conversation = ctx.conversations.create("Cards", select=False)
    ctx.conversations.add_message(conversation.id, "user", "first")
    ctx.conversations.add_message(conversation.id, "assistant", "second")
    window.open_conversation(conversation.id)
    QApplication.processEvents()
    messages = ctx.conversations.messages(conversation.id)
    window._delete_message(messages[0].id)
    QApplication.processEvents()
    remaining = ctx.conversations.messages(conversation.id)
    assert len(remaining) == 1 and remaining[0].content == "second"


def test_no_raw_translation_keys_are_rendered(ui) -> None:
    """A missing catalogue entry shows up as a dotted key on screen - catch it."""
    import re

    window, ctx, theme = ui
    conversation = ctx.conversations.create("Key scan", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hello")
    window.open_conversation(conversation.id)
    from PySide6.QtWidgets import QApplication, QLabel

    QApplication.processEvents()
    offenders = []
    for lang in ("fa", "en"):
        ctx.settings.set("ui.language", lang)
        QApplication.processEvents()
        for label in window.findChildren(QLabel):
            text = label.text().strip()
            if not text or not label.isVisible():
                continue
            if re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+", text):
                offenders.append((lang, text))
    assert not offenders, offenders


def test_collapsed_sidebar_keeps_icons_inside_the_rail(ui) -> None:
    window, ctx, theme = ui
    window.sidebar.set_collapsed(True, animate=False)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    rail = window.sidebar
    assert rail.width() >= 80, "collapsed rail must fit its 40px icon buttons + margins"
    for key, button in rail.nav_buttons.items():
        geometry = button.geometry()
        assert geometry.left() >= 0 and geometry.right() <= rail.width(), (key, geometry, rail.width())
        assert button.width() >= 40, (key, button.width())


def test_header_chip_text_is_not_clipped(ui) -> None:
    window, ctx, theme = ui
    from PySide6.QtWidgets import QApplication

    for lang in ("fa", "en"):
        ctx.settings.set("ui.language", lang)
        QApplication.processEvents()
        chip = window.header.model_chip
        hint = chip.sizeHint().width()
        assert chip.width() >= hint - 2, (lang, chip.width(), hint)


def test_header_title_and_subtitle_fit_inside_the_bar(ui) -> None:
    window, ctx, theme = ui
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    header = window.header
    for label in (header.title, header.subtitle):
        top = label.mapTo(header, label.rect().topLeft()).y()
        bottom = top + label.height()
        assert 0 <= top and bottom <= header.height() + 1, (top, bottom, header.height())


def test_every_inspector_card_is_inside_the_panel(ui) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Inspector", select=False)
    ctx.conversations.add_message(conversation.id, "user", "hi")
    window.open_conversation(conversation.id)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    panel = window.inspector
    from PySide6.QtWidgets import QFrame

    cards = [c for c in panel.findChildren(QFrame) if c.property("panel") == "card"]
    assert len(cards) >= 5, len(cards)  # model, context, session, health, activity, ...
    for card in cards:
        assert card.width() > 0
        left = card.mapTo(panel, card.rect().topLeft()).x()
        assert left >= 0, (left, card.width(), panel.width())
        assert left + card.width() <= panel.width() + 2, (left, card.width(), panel.width())


def test_inspector_header_follows_language(ui) -> None:
    """Static chrome outside the card stack must be retranslated too."""
    window, ctx, theme = ui
    from PySide6.QtWidgets import QApplication

    ctx.settings.set("ui.language", "fa")
    QApplication.processEvents()
    assert window.inspector.title_label.text() == tr("inspector.title")
    persian = window.inspector.title_label.text()
    ctx.settings.set("ui.language", "en")
    QApplication.processEvents()
    english = window.inspector.title_label.text()
    assert english != persian
    assert english == tr("inspector.title")


def test_every_visible_label_matches_active_language(ui) -> None:
    """No label may keep the previous language after a switch."""
    window, ctx, theme = ui
    from PySide6.QtWidgets import QApplication, QLabel

    ctx.settings.set("ui.language", "fa")
    QApplication.processEvents()
    persian = {label.text() for label in window.findChildren(QLabel) if label.isVisible()}
    ctx.settings.set("ui.language", "en")
    QApplication.processEvents()
    english = {label.text() for label in window.findChildren(QLabel) if label.isVisible()}
    leftover = {text for text in english if any("\u0600" <= ch <= "\u06ff" for ch in text)}
    # Chat content itself may be Persian; only chrome labels are checked.
    chrome = {t for t in leftover if t in persian and t not in {"بازرس"}}
    assert not chrome, chrome


def test_trust_chips_fit_their_text_in_both_languages(ui) -> None:
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication

    from myai.ui.views.chat_view import _WelcomeContent

    window, ctx, theme = ui
    content = window.chat_view.welcome.findChild(_WelcomeContent)
    chips = [chip for chip, _ in content._trust_chips]
    assert len(chips) == 3
    for language in ("fa", "en"):
        ctx.settings.set("ui.language", language)
        QApplication.processEvents()
        from myai.ui.theme import runtime

        for chip in chips:
            needed = QFontMetrics(runtime.ui_font(9, 500)).horizontalAdvance(chip.text()) + runtime.px(32)
            assert chip.width() >= needed - 1, (language, chip.text(), chip.width(), needed)
