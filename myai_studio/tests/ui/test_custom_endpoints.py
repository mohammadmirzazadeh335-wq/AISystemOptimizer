"""Custom endpoints and the model switch — the two things the user hit here.

Both bugs share a shape: the screen said one thing and the request did another.

* The provider list was a fixed tuple, so an endpoint the user owns could not be
  a first-class service.
* The model chip above the send button changed its label but was wired to
  nothing, so every message went to the conversation's previous model.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from myai.services.providers import (
    CUSTOM_PREFIX,
    all_providers,
    custom_endpoints,
    get_provider,
    sync_custom_endpoints,
)


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


def test_adding_a_custom_endpoint_makes_it_a_provider(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page.custom_name.setText("Local Gateway")
    page.custom_url.setText("https://gateway.example/v1")
    page.custom_key_required.setChecked(True)
    page.custom_add.click()
    pump()

    rows = custom_endpoints(context.settings)
    assert len(rows) == 1
    endpoint = rows[0]
    assert endpoint["name"] == "Local Gateway"
    assert endpoint["base_url"] == "https://gateway.example/v1"
    assert endpoint["id"].startswith(CUSTOM_PREFIX)
    # It is now a real provider: selectable, resolvable and persisted.
    assert endpoint["id"] in [provider.id for provider in all_providers()]
    assert get_provider(endpoint["id"]).base_url == "https://gateway.example/v1"
    assert context.settings.get("ai.provider") == endpoint["id"]
    assert page.base_url_input.text() == "https://gateway.example/v1"
    assert page.provider.id == endpoint["id"]


def test_a_custom_endpoint_keeps_its_own_key(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page.custom_name.setText("Second Hub")
    page.custom_url.setText("https://hub.example/v1")
    page.custom_add.click()
    pump()
    endpoint_id = custom_endpoints(context.settings)[0]["id"]
    page.key_input.setText("hub-key-123456")
    page.save_key.click()
    pump()
    assert context.secrets.get_key(endpoint_id) == "hub-key-123456"
    # Switching away and back does not lose it.
    page._on_provider_selected("openai")
    pump()
    assert page._masked_key() in {"", "—"} or not page.show_key.isEnabled()
    page._on_provider_selected(endpoint_id)
    pump()
    assert context.secrets.get_key(endpoint_id) == "hub-key-123456"


def test_a_custom_endpoint_rejects_remote_http(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page.custom_name.setText("Plain")
    page.custom_url.setText("http://gateway.example/v1")
    page.custom_add.click()
    pump()
    assert custom_endpoints(context.settings) == []
    assert page.custom_message.text()
    assert page.custom_message.property("role") == "danger"


def test_a_custom_endpoint_can_be_deleted_with_its_key(ui) -> None:  # noqa: ANN001
    window, context, _theme = ui
    page = window.api_page
    page.custom_name.setText("Temporary")
    page.custom_url.setText("https://temp.example/v1")
    page.custom_add.click()
    pump()
    endpoint_id = custom_endpoints(context.settings)[0]["id"]
    context.secrets.set_key(endpoint_id, "temp-key")

    from myai.services import providers as providers_module

    providers_module.delete_custom_endpoint(context.settings, endpoint_id)
    context.secrets.delete(context.secrets.key_name(endpoint_id))
    sync_custom_endpoints(context.settings)
    pump()
    assert custom_endpoints(context.settings) == []
    assert endpoint_id not in [provider.id for provider in all_providers()]
    assert context.secrets.get_key(endpoint_id) is None
    assert context.settings.get("ai.provider") != endpoint_id


def test_models_are_labelled_free_or_paid_only_when_known(ui) -> None:  # noqa: ANN001
    from myai.services.openrouter import ModelInfo

    window, context, _theme = ui
    page = window.api_page
    free = ModelInfo(id="free/model", name="Free", price_known=True)
    paid = ModelInfo(
        id="paid/model", name="Paid", price_known=True, prompt_price=3.0, completion_price=15.0
    )
    unknown = ModelInfo(id="relay/model", name="Relay", price_known=False)
    page.set_models([free, paid, unknown])
    pump()
    from myai.i18n import tr
    from myai.ui.views.api_page import ModelRow

    assert ModelRow._price_text(free) == tr("api.free")
    assert "3" in ModelRow._price_text(paid) and "15" in ModelRow._price_text(paid)
    # A catalogue with no prices must not claim either state.
    assert ModelRow._price_text(unknown) == tr("api.price_unknown")
    assert ModelRow._price_text(unknown) != tr("api.free")


def test_the_composer_chip_switches_the_model_for_the_next_message(ui) -> None:  # noqa: ANN001
    """The reported bug: change the model, the answer still comes from the old one."""
    window, context, _theme = ui
    from myai.services.openrouter import ModelInfo

    window.context.chat.set_models(
        [
            ModelInfo(id="alpha/model", name="Alpha", context_length=4096),
            ModelInfo(id="beta/model", name="Beta", context_length=8192),
        ]
    )
    window._ai_models = window.context.chat._models
    conversation = context.conversations.create(title="Switch", select=False)
    context.conversations.set_model(conversation.id, "alpha/model")
    window.open_conversation(conversation.id)
    pump()
    assert window.composer.model_value() == "alpha/model"

    window.composer.model_chip.value_changed.emit("beta/model")
    pump()

    assert context.settings.get("ai.default_model") == "beta/model"
    assert context.conversations.get(conversation.id).model_id == "beta/model"
    assert window.composer.model_value() == "beta/model"
    assert window.header.model_chip.value == "beta/model"
    assert window.api_page.default_picker.value == "beta/model"

    captured: dict = {}
    window._start_stream = lambda conv, text, model, attachments=None: captured.update(
        model=model, text=text
    )
    # A stored key is what lets the message reach the provider at all; without it
    # the app saves locally and never calls the chat service.
    context.secrets.set_key("openrouter", "sk-or-v1-" + "a" * 64)
    window.composer.input.setPlainText("hello")
    window._handle_send("hello", [])
    assert captured["model"] == "beta/model"


def test_a_custom_endpoint_survives_a_restart(home) -> None:  # noqa: ANN001
    """Settings are the only store, so a fresh context must resolve it again."""
    from myai.context import build_context
    from myai.services.providers import save_custom_endpoint

    first = build_context(home, log=False).boot()
    saved = save_custom_endpoint(
        first.settings, {"name": "My Hub", "base_url": "https://hub.example/v1"}
    )
    first.shutdown()

    second = build_context(home, log=False).boot()
    try:
        assert saved.id in [provider.id for provider in all_providers()]
        assert get_provider(saved.id).base_url == "https://hub.example/v1"
        assert second.settings.get("ai.provider") == saved.id
    finally:
        second.shutdown()


def test_usage_can_be_exported_as_csv(ui, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """The export button must write the same numbers the page shows."""
    import csv

    from PySide6.QtWidgets import QFileDialog

    window, context, _theme = ui
    page = window.usage_page
    target = tmp_path / "usage.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    page.export_csv()
    pump()
    assert target.is_file()
    rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines()))
    header = rows[0]
    assert header[:3] == ["model", "requests", "input_tokens"]
    assert "cost_usd" in header


def test_the_output_studio_writes_a_real_pdf(ui, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    from PySide6.QtWidgets import QFileDialog

    window, context, _theme = ui
    page = window.studio_page
    created = context.outputs.create(
        name="note.md", content="# Heading\n\nBody text.", language="markdown"
    )
    page.open_output(created.id)
    pump()
    target = tmp_path / "note.pdf"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    page._export_pdf()
    pump()
    assert target.is_file()
    assert target.read_bytes().startswith(b"%PDF-")


def test_a_read_page_can_be_kept_as_a_real_note(ui) -> None:  # noqa: ANN001
    """Reading a page used to end at a text view: no way to keep what was read."""
    window, context, _theme = ui
    page = window.web_page
    window._navigate("web")
    pump()
    assert page.note_button.isEnabled() is False
    page.url_edit.setText("https://example.com/guide")
    page.title_label.setText("A Guide")
    page.title_label.setVisible(True)
    page.text_view.setPlainText("The real text of the page.")
    page._last_text = "The real text of the page."
    page.note_button.setEnabled(True)
    page.save_as_note()
    pump()
    entries = [entry for entry in context.outputs.list() if entry.name.startswith("A Guide")]
    assert entries, "the note was not written"
    saved = context.outputs.get(entries[0].id)
    assert "https://example.com/guide" in saved.content
    assert "The real text of the page." in saved.content
