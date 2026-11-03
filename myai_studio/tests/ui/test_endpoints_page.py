"""The "any API" page and the Arena.ai entry that ships with the app.

The user asked for two things that look the same from a distance and are not:
"Arena.ai keys" (a provider that is known up front) and "a section where any
kind of API can be added" (a provider this code has never heard of). These tests
pin both: the built-in row exists with the documented address, and the endpoints
page turns a typed URL, protocol, key and model list into a working provider.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from myai.services.providers import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_OPENAI,
    all_providers,
    custom_endpoints,
    get_provider,
)


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def test_arena_ai_is_a_built_in_openai_compatible_provider() -> None:
    provider = get_provider("arena")
    assert provider is not None
    assert provider.name == "Arena.ai"
    assert provider.base_url == "https://api.arena.ai/v1"
    assert provider.protocol == PROTOCOL_OPENAI
    # It is a real row in the list, not something hidden behind settings.
    assert "arena" in {item.id for item in all_providers()}


def test_any_api_page_saves_url_protocol_key_and_models(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    window._navigate("endpoints")
    pump()
    page = window.endpoints_page

    page.name_input.setText("Studio Gateway")
    page.url_input.setText("https://gateway.example/v1")
    page.protocol_picker.set_value(PROTOCOL_ANTHROPIC)
    page.models_input.setText("claude-a, claude-b")
    page.key_input.setText("sk-ant-test-key")
    page.save_button.click()
    pump()

    rows = custom_endpoints(context.settings)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Studio Gateway"
    assert row["base_url"] == "https://gateway.example/v1"
    assert row["protocol"] == PROTOCOL_ANTHROPIC
    assert row["models"] == ["claude-a", "claude-b"]

    provider = get_provider(row["id"])
    assert provider is not None
    # The typed ids are the honest fallback when the vendor has no catalogue.
    assert provider.fallback_models == ("claude-a", "claude-b")
    assert context.secrets.get_key(provider.id) == "sk-ant-test-key"
    assert context.settings.get("ai.provider") == provider.id
    # The form keeps what was saved (so it can be corrected) but never the key.
    assert page.url_input.text() == "https://gateway.example/v1"
    assert page.key_input.text() == ""


def test_any_api_page_refuses_an_endpoint_without_a_url(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    window._navigate("endpoints")
    pump()
    page = window.endpoints_page
    page.name_input.setText("Nowhere")
    page.save_button.click()
    pump()
    assert custom_endpoints(context.settings) == []
    assert page.status.text() != ""


def test_a_saved_endpoint_can_be_used_and_deleted_from_its_own_row(ui, monkeypatch) -> None:  # noqa: ANN001
    window, context, _theme = ui
    window._navigate("endpoints")
    pump()
    page = window.endpoints_page
    page.name_input.setText("Second Gateway")
    page.url_input.setText("https://second.example/v1")
    page.key_input.setText("second-key")
    page.save_button.click()
    pump()
    endpoint_id = custom_endpoints(context.settings)[0]["id"]

    # Another provider becomes active, then the row's own "Use" takes it back.
    context.settings.set("ai.provider", "openrouter")
    page.use_endpoint(endpoint_id)
    assert context.settings.get("ai.provider") == endpoint_id

    class _Yes:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def exec(self) -> int:
            return 1

    monkeypatch.setattr("myai.ui.views.endpoints_page.ConfirmDialog", _Yes)
    page.delete_endpoint(endpoint_id)
    pump()
    assert custom_endpoints(context.settings) == []
    assert context.secrets.get_key(endpoint_id) is None
    # Deleting the active endpoint cannot leave the app pointing at nothing.
    assert context.settings.get("ai.provider") == "openrouter"


def test_the_endpoints_page_is_reachable_from_the_sidebar(ui) -> None:  # noqa: ANN001
    window, _context, _theme = ui
    button = window.sidebar.nav_buttons["endpoints"]
    assert button.isVisible()
    button.click()
    pump()
    assert window.stack.currentWidget() is window.endpoints_page
    assert button.isChecked()
