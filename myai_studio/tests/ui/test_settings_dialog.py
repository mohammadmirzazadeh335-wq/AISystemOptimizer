from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from myai.services.backup import BackupService
from myai.ui.views.settings_dialog import CATEGORIES, SettingsDialog


@pytest.fixture()
def dialog(ui):
    window, ctx, theme = ui
    backup = BackupService(ctx.paths, ctx.db, ctx.settings)
    settings = SettingsDialog(window, ctx.settings, theme, ctx.paths, ctx.db, ctx.secrets, backup)
    settings.show()
    QApplication.processEvents()
    yield settings, ctx, theme
    settings.reject()


def test_every_category_builds(dialog) -> None:
    settings, ctx, theme = dialog
    for key, _icon, _label in CATEGORIES:
        settings._select(key)
        QApplication.processEvents()
        assert key in settings._pages
        page = settings._pages[key]
        assert page is not None and page.sizeHint().height() > 0


def test_theme_choice_writes_setting(dialog) -> None:
    settings, ctx, theme = dialog
    settings._select("appearance")
    QApplication.processEvents()
    settings._choose_theme("dawn")
    QApplication.processEvents()
    assert ctx.settings.get("ui.theme") == "dawn"
    assert theme.theme.mode == "light"


def test_accent_choice_writes_setting(dialog) -> None:
    settings, ctx, theme = dialog
    settings._select("appearance")
    settings._choose_accent("violet")
    assert ctx.settings.get("ui.accent") == "violet"


def test_language_choice_retranslates(dialog) -> None:
    settings, ctx, theme = dialog
    settings._select("language")
    settings._choose_language("en")
    QApplication.processEvents()
    assert ctx.settings.get("ui.language") == "en"
    assert "Settings" in settings.title_label.text()


def test_backup_created_from_data_page(dialog) -> None:
    settings, ctx, theme = dialog
    settings._select("data")
    QApplication.processEvents()
    settings._create_backup()
    QApplication.processEvents()
    assert settings.backups_list.count() >= 1


def test_ai_page_points_at_the_real_key_page(dialog) -> None:
    """The settings page must not duplicate a fake, disabled key field.

    Keys are entered on Connection & models, where their save path is tested
    against the real secret store; this page only states where that is.
    """
    settings, ctx, theme = dialog
    settings._select("ai")
    QApplication.processEvents()
    from PySide6.QtWidgets import QLineEdit

    from myai.i18n import tr
    from myai.ui.widgets.foundation import Badge

    assert not settings._pages["ai"].findChildren(QLineEdit)
    badges = [badge.text() for badge in settings._pages["ai"].findChildren(Badge)]
    assert tr("settings.provider_where") in badges


def test_scroll_pages_have_finite_height(dialog) -> None:
    settings, ctx, theme = dialog
    for key, *_ in CATEGORIES:
        settings._select(key)
        QApplication.processEvents()
        page = settings._pages[key]
        assert page.height() > 0
        assert page.width() <= settings.width()


def test_temperature_slider_writes_the_real_setting(dialog) -> None:
    settings, ctx, _theme = dialog
    settings._select("ai")
    QApplication.processEvents()
    assert ctx.settings.get("ai.temperature") == 0.7
    settings.temperature_row.slider.setValue(120)  # the slider scale is 100 → 1.2
    QApplication.processEvents()
    assert ctx.settings.get("ai.temperature") == 1.2


def test_memory_page_shows_the_database_count(dialog) -> None:
    settings, ctx, _theme = dialog
    settings._select("memory")
    QApplication.processEvents()
    assert "0" in settings.memory_count_label.text()
    ctx.memory.add("A fact that really exists", scope="global")
    settings._pages.pop("memory")  # force a rebuild so the count is read again
    settings._select("memory")
    QApplication.processEvents()
    assert "1" in settings.memory_count_label.text()


def test_memory_toggle_is_written_and_used(dialog) -> None:
    from myai.ui.widgets.buttons import ToggleSwitch

    settings, ctx, _theme = dialog
    ctx.memory.add("The user is testing the memory toggle", scope="global")
    conversation = ctx.conversations.get(ctx.conversations.create("toggle").id)

    def prompt_text() -> str:
        messages, _diagnostics = ctx.chat.build_messages(conversation)
        return "\n".join(str(message["content"]) for message in messages)

    assert "testing the memory toggle" in prompt_text()
    settings._select("memory")
    QApplication.processEvents()
    toggle = settings._pages["memory"].findChildren(ToggleSwitch)[0]
    toggle.setChecked(False)
    QApplication.processEvents()
    assert ctx.settings.get("memory.enabled") is False
    assert "testing the memory toggle" not in prompt_text()


def test_open_memory_asks_the_window_to_navigate(dialog) -> None:
    settings, ctx, theme = dialog
    seen: list[str] = []
    settings.navigate.connect(seen.append)
    settings._go("memory")
    assert seen == ["memory"]
