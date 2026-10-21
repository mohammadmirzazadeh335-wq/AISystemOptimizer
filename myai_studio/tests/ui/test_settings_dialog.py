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
    for key, _icon, _label, _phase in CATEGORIES:
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


def test_api_key_inputs_are_disabled_until_phase_two(dialog) -> None:
    settings, ctx, theme = dialog
    settings._select("ai")
    QApplication.processEvents()
    from PySide6.QtWidgets import QLineEdit

    inputs = settings._pages["ai"].findChildren(QLineEdit)
    assert inputs
    assert all(not widget.isEnabled() for widget in inputs)


def test_scroll_pages_have_finite_height(dialog) -> None:
    settings, ctx, theme = dialog
    for key, *_ in CATEGORIES:
        settings._select(key)
        QApplication.processEvents()
        page = settings._pages[key]
        assert page.height() > 0
        assert page.width() <= settings.width()
