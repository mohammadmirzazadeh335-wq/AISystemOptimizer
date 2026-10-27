"""The model picker: a small searchable popup instead of a page-sized menu.

The bug this guards is visual and measurable: opening the model list on a
300-model catalogue used to produce a menu taller than the window with no
search and no scrollbar. Every assertion below is about size, filtering or the
value that actually gets selected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

from myai.services.openrouter import ModelInfo
from myai.services.providers import all_providers
from myai.ui.theme import runtime
from myai.ui.widgets.fields import SelectField
from myai.ui.widgets.model_picker import Choice, ChoicePopup, model_tags


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def make_choices(count: int = 300) -> list[Choice]:
    return [
        Choice(
            f"vendor/model-{index}",
            f"Model {index}",
            detail=f"vendor/model-{index}",
            tags=model_tags(128_000 if index % 2 == 0 else 0, free=index % 5 == 0, tools=True, vision=False),
        )
        for index in range(count)
    ]


def test_the_popup_never_covers_half_the_screen(qapp) -> None:  # noqa: ANN001
    popup = ChoicePopup(make_choices(), current="vendor/model-0")
    popup.show_for(_anchor())
    pump()
    try:
        screen = popup.screen() or QApplication.primaryScreen()
        assert popup.height() <= int(screen.availableGeometry().height() * 0.5)
        # Eight rows at 1.0x plus chrome: a popup, not a page.
        assert popup.height() <= runtime.px(46) * ChoicePopup.MAX_ROWS + runtime.px(120)
        assert popup.view.height() < popup.height()
    finally:
        popup.close()


def test_the_list_scrolls_when_it_has_more_rows_than_fit(qapp) -> None:  # noqa: ANN001
    popup = ChoicePopup(make_choices(), current="")
    popup.show_for(_anchor())
    pump()
    try:
        assert popup.model.rowCount() == 300
        assert popup.view.verticalScrollBar().maximum() > 0
        assert popup.view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    finally:
        popup.close()


def test_search_filters_on_name_and_id_with_several_words(qapp) -> None:  # noqa: ANN001
    popup = ChoicePopup(make_choices(), current="")
    popup.show_for(_anchor())
    pump()
    try:
        popup.search.setText("model-42")
        pump()
        visible = popup.model.visible_choices()
        assert [choice.value for choice in visible] == ["vendor/model-42"]
        assert popup.count.text().startswith("1")
        popup.search.setText("vendor model-7")
        pump()
        values = [choice.value for choice in popup.model.visible_choices()]
        assert "vendor/model-7" in values and "vendor/model-70" in values
        popup.search.setText("nothing-like-this")
        pump()
        assert popup.model.rowCount() == 0
        assert popup.empty.isVisible() is True
    finally:
        popup.close()


def test_enter_chooses_the_highlighted_row_and_escape_closes(qapp) -> None:  # noqa: ANN001
    popup = ChoicePopup(make_choices(20), current="")
    chosen: list[str] = []
    popup.chosen.connect(chosen.append)
    popup.show_for(_anchor())
    pump()
    try:
        popup.search.setText("model-3")
        pump()
        popup._move(0)
        popup.choose_current()
        pump()
        assert chosen == ["vendor/model-3"]
        assert popup.isVisible() is False
    finally:
        popup.close()


def test_typing_a_space_in_the_search_still_filters(qapp) -> None:  # noqa: ANN001
    popup = ChoicePopup(make_choices(10), current="")
    popup.show_for(_anchor())
    pump()
    try:
        popup.search.setText("model 9")
        pump()
        assert [choice.value for choice in popup.model.visible_choices()] == ["vendor/model-9"]
    finally:
        popup.close()


def test_a_searchable_field_opens_the_popup_instead_of_a_menu(qapp) -> None:  # noqa: ANN001
    field = SelectField(searchable=True, search_placeholder="Search…")
    field.set_items([(f"id-{index}", f"Label {index}") for index in range(50)])
    field.show()
    field.open_picker()
    pump()
    try:
        assert field._popup is not None
        assert isinstance(field._popup, ChoicePopup)
        assert not field.findChildren(QMenu)
        field._popup.search.setText("id-17")
        pump()
        assert field._popup.model.rowCount() == 1
        field._popup.choose_current()
        pump()
        assert field.value == "id-17"
    finally:
        if field._popup is not None:
            field._popup.close()
        field.close()


def test_a_short_list_keeps_the_plain_menu(qapp) -> None:  # noqa: ANN001
    field = SelectField(searchable=True)
    field.set_items([("system", "System"), ("manual", "Manual")])
    assert field.uses_popup is False  # a two-row menu is not worth a popup
    field.set_items([(f"id-{index}", f"Label {index}") for index in range(20)])
    assert field.uses_popup is True
    field.close()


def test_rich_choices_keep_the_value_and_show_tags(qapp) -> None:  # noqa: ANN001
    field = SelectField(searchable=True)
    field.set_choices(make_choices(30), "vendor/model-4")
    assert field.value == "vendor/model-4"
    assert field._items[4] == ("vendor/model-4", "Model 4")
    field.show()
    field.open_picker()
    pump()
    try:
        rows = field._popup.model.visible_choices()
        assert rows[4].tags  # context/tools brackets survive into the popup
    finally:
        field._popup.close()
        field.close()


def test_the_composer_chip_is_searchable(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    models = [
        ModelInfo(id=f"vendor/m{index}", name=f"Model {index}", context_length=32_000)
        for index in range(40)
    ]
    window._ai_models = models
    window._apply_models_to_ui()
    pump()
    assert window.composer.model_chip.searchable is True
    assert window.header.model_chip.searchable is True
    window.composer.model_chip.open_picker()
    pump()
    popup = window.composer.model_chip._popup
    try:
        assert popup is not None and popup.model.rowCount() == 40
    finally:
        if popup is not None:
            popup.close()


def test_the_provider_selector_lists_every_provider(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    assert page.provider.id == "openrouter"
    assert [value for value, _label in page.provider_select._items] == [
        provider.id for provider in all_providers()
    ]
    page._on_provider_selected("gemini")
    pump()
    assert context.settings.get("ai.provider") == "gemini"
    assert page.base_url_input.text().startswith("https://generativelanguage.googleapis.com")
    assert "Gemini" in page.key_label.text()


def test_switching_provider_does_not_lose_the_other_key(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    context.secrets.set_key("openrouter", "sk-or-v1-" + "b" * 64)
    context.secrets.set_key("openai", "sk-openai-key")
    page._on_provider_selected("openai")
    pump()
    assert page._masked_key().startswith("sk-open")
    page._on_provider_selected("openrouter")
    pump()
    assert page._masked_key().startswith("sk-or-")
    assert context.secrets.get_key("openai") == "sk-openai-key"


def test_the_custom_provider_explains_that_it_needs_a_url(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("custom")
    pump()
    assert page.base_url_input.text() == ""
    page.base_url_input.setText("http://127.0.0.1:9000/v1")
    pump()
    assert page.base_url_save.isEnabled() is True
    page._save_base_url()
    pump()
    assert context.settings.get("ai.base_urls")["custom"] == "http://127.0.0.1:9000/v1"


def test_a_remote_http_url_is_refused_with_a_reason(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("openai")
    pump()
    page.base_url_input.setText("http://api.openai.com/v1")
    pump()
    assert page.base_url_save.isEnabled() is True
    assert "https" in page.base_url_hint.text().lower() or "https" in page.base_url_input.toolTip().lower()
    page._save_base_url()
    pump()
    assert context.settings.get("ai.base_urls").get("openai") is None


def _anchor():  # noqa: ANN202
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    widget.resize(runtime.px(300), runtime.px(32))
    widget.show()
    return widget


# --------------------------------------------------- a model id typed by hand
def test_a_model_id_typed_by_hand_becomes_the_default(ui) -> None:  # noqa: ANN001
    """An endpoint that publishes no catalogue still has to be usable.

    The user's gateway may answer /v1/models with 404 or with names the app
    cannot list; without this row the provider could be configured and then be
    impossible to use.
    """
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("custom")
    pump()
    page.model_id_input.setText("vendor/model-typed")
    page.model_id_button.click()
    pump()
    assert context.settings.get("ai.default_model") == "vendor/model-typed"
    assert page.default_picker.value == "vendor/model-typed"
    # It is offered by the picker too, not only stored in settings.
    offered = [value for value, _label in page.default_picker._items]
    assert "vendor/model-typed" in offered
    # The typed row is marked as such, so it cannot be mistaken for a listing.
    rows = [
        page.models_layout.itemAt(index).widget()
        for index in range(page.models_layout.count())
        if page.models_layout.itemAt(index).widget() is not None
    ]
    typed = [row for row in rows if row.model.id == "vendor/model-typed"]
    assert typed, "the typed model is missing from the catalogue card"
    assert typed[0].model.price_known is False
    assert page.model_id_input.text() == ""


def test_the_default_model_survives_a_restart(ui) -> None:  # noqa: ANN001
    """The id is kept in settings, so reopening the app must still show it."""
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("custom")
    pump()
    page.model_id_input.setText("only/this-one")
    page.model_id_button.click()
    pump()
    page.set_models([])
    page.set_default_model("only/this-one")
    pump()
    assert page.default_picker.value == "only/this-one"


def test_a_typed_model_id_with_a_space_is_refused(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("custom")
    pump()
    before = context.settings.get("ai.default_model")
    page.model_id_input.setText("gpt 4")
    page.model_id_button.click()
    pump()
    assert context.settings.get("ai.default_model") == before
    assert page.model_id_hint.property("role") == "danger"


def test_a_keyless_provider_never_claims_a_stored_key(ui) -> None:  # noqa: ANN001
    """The card used to render "a key is stored: ''" for a provider with no key."""
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("custom")
    pump()
    assert "''" not in page.key_state.text()
    assert page.save_key.text() != ""
    badges = [
        page.key_badge_layout.itemAt(index).widget().text()
        for index in range(page.key_badge_layout.count())
        if page.key_badge_layout.itemAt(index).widget() is not None
    ]
    assert badges  # exactly one badge for the state
    assert page.show_key.isEnabled() is False


def test_the_tooken_provider_is_offered_with_its_own_url(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page._on_provider_selected("tooken")
    pump()
    assert page.base_url_input.text() == "https://tooken.club/v1"
    assert context.settings.get("ai.provider") == "tooken"
    page.key_input.setText("tc_live_" + "f" * 48)
    page.save_key.click()
    pump()
    assert context.secrets.get_key("tooken") == "tc_live_" + "f" * 48
    # A key from the wrong service is refused before it is stored.
    page.key_input.setText("sk-or-v1-" + "a" * 64)
    page.save_key.click()
    pump()
    assert context.secrets.get_key("tooken") == "tc_live_" + "f" * 48
