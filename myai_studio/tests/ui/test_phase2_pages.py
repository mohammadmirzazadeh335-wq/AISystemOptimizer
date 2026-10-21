"""Phase 2 surfaces inside the real window: API, memory, persona, studio.

Everything here drives the actual widgets on the offscreen platform. Provider
calls are the only mocked part (via ``httpx.MockTransport``) because the
sandbox cannot reach openrouter.ai.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from PySide6.QtWidgets import QApplication

from myai.i18n import set_language, tr
from myai.services.openrouter import ModelInfo, OpenRouterClient

CATALOGUE = {
    "data": [
        {
            "id": "test/model-a",
            "name": "Model A",
            "context_length": 128000,
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "architecture": {"input_modalities": ["text"]},
            "supported_parameters": ["temperature"],
        },
        {
            "id": "test/model-b",
            "name": "Model B",
            "context_length": 32000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text", "image"]},
            "supported_parameters": ["tools"],
        },
    ]
}


def pump() -> None:
    QApplication.processEvents()
    QApplication.processEvents()


# --------------------------------------------------------------------- routing
@pytest.mark.parametrize("route", ["api", "memory", "persona", "studio"])
def test_ai_pages_are_reachable(ui, route) -> None:
    window, ctx, theme = ui
    window._navigate(route)
    pump()
    page = window._pages[route]
    assert window.stack.currentWidget() is page
    assert not window.composer.isVisible()
    assert window.sidebar.nav_buttons[route].isChecked()
    assert window.windowTitle().endswith("MyAI Studio Ultimate")


def test_sidebar_has_phase2_group(ui) -> None:
    window, ctx, theme = ui
    for key in ("api", "memory", "persona", "studio"):
        assert key in window.sidebar.nav_buttons
    assert window.sidebar.ai_label.text() == tr("nav.ai_section")


# ------------------------------------------------------------------------ api
def test_api_page_shows_missing_key_state(ui) -> None:
    window, ctx, theme = ui
    window._navigate("api")
    pump()
    page = window.api_page
    assert page.key_state.text() == tr("api.key_missing")
    assert page.delete_key.isEnabled() is False
    assert page.test_button.isEnabled() is False
    assert any(
        badge.text() == tr("api.not_configured")
        for badge in page.findChildren(type(page.key_badge_layout.itemAt(0).widget()))
    )


def test_api_key_save_and_delete(ui) -> None:
    window, ctx, theme = ui
    page = window.api_page
    page.key_input.setText("sk-or-v1-abcdefghijklmnop")
    page._save_key()
    pump()
    assert ctx.secrets.has_api_key()
    assert "sk-or-v1-abcdefghijklmnop" not in page.key_state.text()
    assert "abcdefghijklmnop" not in page.key_input.placeholderText()
    assert page.test_button.isEnabled()

    ctx.secrets.set_api_key("")
    page._refresh_key_state()
    assert not ctx.secrets.has_api_key()
    assert page.delete_key.isEnabled() is False


def test_api_key_format_is_validated(ui) -> None:
    window, ctx, theme = ui
    page = window.api_page
    page.key_input.setText("not-a-key")
    page._save_key()
    assert not ctx.secrets.has_api_key()
    assert page.key_error.text()
    assert "sk-or-" in page.key_error.text()


def test_live_catalogue_renders_models(ui) -> None:
    window, ctx, theme = ui
    page = window.api_page
    ctx.secrets.set_api_key("sk-or-v1-test")
    page._refresh_key_state()
    models = [ModelInfo(**item) for item in [
        {"id": "test/model-a", "name": "Model A", "context_length": 128000,
         "prompt_price": 1.0, "completion_price": 2.0, "supports_tools": False,
         "supports_vision": False},
        {"id": "test/model-b", "name": "Model B", "context_length": 32000,
         "prompt_price": 0.0, "completion_price": 0.0, "supports_tools": True,
         "supports_vision": True},
    ]]
    page._on_models(models)
    pump()
    assert page.models_layout.count() == 2
    assert tr("api.models_loaded_short", count=2, shown=2) == page.model_count.text()
    page.search.setText("model-b")
    pump()
    assert page.models_layout.count() == 1
    page.search.clear()
    pump()


def test_models_flow_into_header_and_composer(ui) -> None:
    window, ctx, theme = ui
    models = [ModelInfo(id="test/model-a", name="Model A", context_length=8000)]
    window._on_models_loaded(models)
    pump()
    assert window.header.model_chip.value == ""
    assert ("test/model-a", "Model A") in window.header.model_chip._items
    assert window._ai_models[0].id == "test/model-a"
    cached = ctx.settings.get("ai.openrouter_cache")
    assert cached and cached[0]["id"] == "test/model-a"


def test_model_selection_updates_default(ui) -> None:
    window, ctx, theme = ui
    window._on_models_loaded([ModelInfo(id="test/model-b", name="Model B")])
    window._on_api_model_selected("test/model-b")
    pump()
    assert ctx.settings.get("ai.default_model") == "test/model-b"
    assert window.header.model_chip.value == "test/model-b"


def test_api_page_error_messages_are_localised(ui) -> None:
    window, ctx, theme = ui
    page = window.api_page
    assert "کیف پول" not in page._explain("provider.credit", "x")
    set_language("fa")
    try:
        text_fa = page._explain("provider.credit", "x")
        assert "اعتبار" in text_fa
        assert page._explain("provider.auth", "x") != page._explain("provider.credit", "x")
    finally:
        set_language("en")


# --------------------------------------------------------------------- memory
def test_memory_page_add_edit_delete(ui) -> None:
    window, ctx, theme = ui
    window._navigate("memory")
    pump()
    page = window.memory_page
    page.editor.setPlainText("I prefer TypeScript")
    page._save_entry()
    pump()
    entries = ctx.memory.list("global")
    assert [e.content for e in entries] == ["I prefer TypeScript"]
    assert page.usage_memory._value_label.text() == "1"
    assert page.rows_layout.count() == 2  # row + stretch

    page._start_edit(entries[0].id)
    assert page.editor.toPlainText() == "I prefer TypeScript"
    page.editor.setPlainText("I prefer Rust")
    page._save_entry()
    pump()
    assert ctx.memory.list("global")[0].content == "I prefer Rust"

    ctx.memory.delete(ctx.memory.list("global")[0].id)
    page.refresh()
    assert page.rows_layout.count() == 1
    assert page.empty_label.isVisible()


def test_memory_page_scopes_are_separate(ui, sample_conversation) -> None:
    window, ctx, theme = ui
    window._navigate("memory")
    pump()
    page = window.memory_page
    page.set_context(sample_conversation.id)
    page.scope_picker.set_value("conversation")
    page.editor.setPlainText("chat-only fact")
    page._save_entry()
    pump()
    ctx.memory.add("global fact", scope="global")
    page.scope_picker.set_value("global")
    pump()
    assert page.rows_layout.count() == 2
    page.scope_picker.set_value("conversation")
    pump()
    assert page.rows_layout.count() == 2
    assert ctx.memory.usage(sample_conversation.id).conversation_count == 1


def test_memory_summary_is_previewed_before_saving(ui, sample_conversation) -> None:
    window, ctx, theme = ui
    ctx.conversations.add_message(
        sample_conversation.id, "user", "We standardised on SQLite for every local database."
    )
    window._navigate("memory")
    pump()
    page = window.memory_page
    page.set_context(sample_conversation.id)
    page._summarize()
    pump()
    assert page._candidates
    assert ctx.memory.list("conversation", sample_conversation.id) == []
    page._commit_summary()
    pump()
    assert ctx.memory.list("conversation", sample_conversation.id)
    assert not page.commit_button.isVisible()


# -------------------------------------------------------------------- persona
def test_persona_page_saves_profile_and_settings(ui) -> None:
    window, ctx, theme = ui
    window._navigate("persona")
    pump()
    page = window.persona_page
    page.profile_editor.setPlainText("# Me\n\n- Name: Nima\n")
    page._save_profile()
    assert "Nima" in ctx.persona.read_profile()

    page.persona_editor.setPlainText("Answer like a reviewer.")
    page.enabled_toggle.setChecked(True)
    page.tone_picker.set_value("concise")
    page.detail_picker.set_value("brief")
    page.language_picker.set_value("fa")
    page._save_persona()
    config = ctx.persona.config()
    assert config.enabled and config.tone == "concise" and config.detail == "brief"
    assert "reviewer" in ctx.persona.build_system_block()
    assert "Nima" in ctx.persona.build_system_block()


def test_persona_reload_discards_editor_changes(ui) -> None:
    window, ctx, theme = ui
    window._navigate("persona")
    pump()
    page = window.persona_page
    ctx.persona.write_profile("- Name: FromDisk\n")
    page._reload_profile()
    assert "FromDisk" in page.profile_editor.toPlainText()


# --------------------------------------------------------------------- studio
def test_studio_creates_edits_and_versions(ui) -> None:
    window, ctx, theme = ui
    window._navigate("studio")
    pump()
    page = window.studio_page
    entry = ctx.outputs.create("script.py", "print('v1')\n")
    page.refresh()
    page.open_output(entry.id)
    pump()
    assert page.editor.toPlainText() == "print('v1')\n"

    page.editor.setPlainText("print('v2')\n")
    page._save()
    pump()
    assert ctx.outputs.get(entry.id).content == "print('v2')\n"
    assert len(ctx.outputs.revisions(entry.id)) == 1
    assert page.history_list.count() == 1

    page._show_diff()
    pump()
    assert "+print('v2')" in page.diff_view.toPlainText()
    assert page.preview_tabs.currentIndex() == 2


def test_studio_json_validation_and_formatting(ui) -> None:
    window, ctx, theme = ui
    window._navigate("studio")
    pump()
    page = window.studio_page
    entry = ctx.outputs.create("config.json", '{"b":2,"a":1}')
    page.refresh()
    page.open_output(entry.id)
    pump()
    assert page.format_button.isEnabled()
    page._format_json()
    assert page.editor.toPlainText() == '{\n  "b": 2,\n  "a": 1\n}'
    page.editor.setPlainText("{broken")
    page._update_live_preview()
    pump()
    assert page.preview_note.text() != tr("studio.json_valid")
    assert tr("studio.json_invalid", error="").split("{error}")[0] in page.preview_note.text()


def test_studio_retranslates(ui) -> None:
    window, ctx, theme = ui
    window._navigate("studio")
    pump()
    page = window.studio_page
    set_language("fa")
    try:
        page.retranslate()
        assert page.lead.text() == tr("studio.subtitle")
        assert page.tab_history.text() == tr("studio.tab_history")
    finally:
        set_language("en")


def test_chat_message_can_be_drafted_in_studio(ui, sample_conversation) -> None:
    window, ctx, theme = ui
    window.open_conversation(sample_conversation.id)
    window._draft_message_in_studio("reply.md", "# Saved reply\n")
    pump()
    assert window.stack.currentWidget() is window.studio_page
    outputs = ctx.outputs.list()
    assert outputs and outputs[0].name == "reply.md"
    assert outputs[0].content == "# Saved reply\n"
    assert outputs[0].kind == "markdown"


# ------------------------------------------------------------------ streaming
def test_streaming_bubble_then_final_message(ui, sample_conversation) -> None:
    window, ctx, theme = ui
    window.open_conversation(sample_conversation.id)
    window.chat_view.begin_stream("test/model-a")
    pump()
    assert window.chat_view.is_streaming
    window.chat_view.append_stream("Hel")
    window.chat_view.append_stream("Hello world")
    pump()
    assert window.chat_view._stream_card.text() == "Hello world"
    window.chat_view.set_stream_latency("first token 120 ms")
    text = window.chat_view.end_stream(silent=True)
    assert text == "Hello world"
    assert not window.chat_view.is_streaming


def test_streaming_widget_survives_language_switch(ui) -> None:
    window, ctx, theme = ui
    window.chat_view.begin_stream("test/model-a")
    window.chat_view.append_stream("partial")
    set_language("fa")
    try:
        window.chat_view.retranslate()
        assert window.chat_view._stream_card.status_label.text() == tr("chat.generating")
    finally:
        set_language("en")


def test_send_without_key_saves_locally(ui) -> None:
    window, ctx, theme = ui
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A")])
    window._on_api_model_selected("test/model-a")
    window.composer.input.setPlainText("hello")
    window.composer._submit()
    pump()
    conversations = ctx.conversations.list()
    assert conversations
    messages = ctx.conversations.messages(conversations[0].id)
    assert [m.role for m in messages] == ["user"]
    assert not window._generating


def test_streaming_round_trip_through_the_window(ui) -> None:
    """Full GUI path with a mocked provider — proves wiring, not the network."""
    window, ctx, theme = ui
    ctx.secrets.set_api_key("sk-or-v1-test")

    def handler(request: httpx.Request) -> httpx.Response:
        body = "".join(
            f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n\n"
            for chunk in ["Streamed ", "through ", "the window"]
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})

    ctx.chat._client_factory = lambda: OpenRouterClient(
        ctx.secrets.get_api_key, transport=httpx.MockTransport(handler), timeout=5.0
    )
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A", context_length=8192)])
    window._on_api_model_selected("test/model-a")
    window.composer.input.setPlainText("stream please")
    window.composer._submit()
    deadline = time.time() + 10
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.02)
    pump()
    assert not window._generating
    conversations = ctx.conversations.list()
    messages = ctx.conversations.messages(conversations[0].id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[-1].content == "Streamed through the window"
    assert messages[-1].status == "complete"
    assert messages[-1].meta["stats"]["chunk_count"] == 3


# ------------------------------------------------- regression: screenshots pass
def test_ai_pages_are_fully_retranslated_on_language_switch(ui) -> None:
    """Stale strings were found in screenshots: rebuild must relabel everything."""
    window, ctx, theme = ui
    window._navigate("api")
    pump()
    set_language("fa")
    try:
        window._retranslate()
    finally:
        pass
    fa_page = window.api_page
    assert window.header.title.text() == tr("api.title")
    assert fa_page.lead.text() == tr("api.subtitle")
    fa_save = fa_page.save_key.text()

    set_language("en")
    try:
        window._retranslate()
    finally:
        pass
    en_page = window.api_page
    assert window.header.title.text() == "OpenRouter connection"
    assert en_page.lead.text() == tr("api.subtitle")
    assert en_page.save_key.text() != fa_save
    studio = window.studio_page
    assert studio.lead.text() == tr("studio.subtitle")
    assert studio.tab_history.text() == "History"
    assert studio.kind_picker._current_label() in {"Code", "Text", "Prompt", "Markdown", "JSON"}
    memory = window.memory_page
    assert memory.scope_hint.text() == tr("memory.scope_hint")
    assert memory.save_button.text() == tr("memory.add")


def test_studio_editor_keeps_usable_width_at_1440(ui) -> None:
    window, ctx, theme = ui
    window.resize(1440, 900)
    window._navigate("studio")
    pump()
    page = window.studio_page
    assert page.editor.width() >= 280
    assert page.preview_tabs.isVisible()
    assert page.preview_tabs.height() >= 180
    assert page.file_list.width() >= 150


def test_studio_unsaved_edit_survives_language_switch(ui) -> None:
    window, ctx, theme = ui
    entry = ctx.outputs.create("keep.py", "print('saved')\n")
    window._navigate("studio")
    page = window.studio_page
    page.open_output(entry.id)
    pump()
    page.editor.setPlainText("print('unsaved edit')\n")
    page._mark_dirty()
    set_language("fa")
    try:
        window._retranslate()
        assert "unsaved edit" in page.editor.toPlainText()
        assert page._dirty is True
    finally:
        set_language("en")
        window._retranslate()


def test_inspector_connect_button_opens_the_api_page(ui) -> None:
    window, ctx, theme = ui
    window.inspector.connect_requested.emit()
    pump()
    assert window.stack.currentWidget() is window.api_page


def test_singular_counts_use_correct_plural_forms(ui, sample_conversation) -> None:
    window, ctx, theme = ui
    set_language("en")
    window._retranslate()
    ctx.memory.add("one fact", scope="conversation", conversation_id=sample_conversation.id)
    window._navigate("memory")
    pump()
    page = window.memory_page
    page.set_context(sample_conversation.id)
    page.scope_picker.set_value("conversation")
    pump()
    assert page.count_label.text() == "1 entry in this chat"
    ctx.memory.add("second fact", scope="conversation", conversation_id=sample_conversation.id)
    page.refresh()
    assert page.count_label.text() == "2 entries in this chat"


def test_text_editors_use_per_paragraph_direction(ui) -> None:
    """Persian bullets and English code must both read correctly."""
    from PySide6.QtCore import Qt

    window, ctx, theme = ui
    for editor in (
        window.persona_page.profile_editor,
        window.persona_page.persona_editor,
        window.memory_page.editor,
        window.studio_page.editor,
    ):
        option = editor.document().defaultTextOption()
        assert option.textDirection() == Qt.LayoutDirection.LayoutDirectionAuto


def test_retry_does_not_duplicate_the_user_turn(ui) -> None:
    window, ctx, theme = ui
    conversation = ctx.conversations.create("Retry", select=False)
    user = ctx.conversations.add_message(conversation.id, "user", "please answer")
    failed = ctx.conversations.add_message(
        conversation.id, "assistant", "", model_id="test/model-a", status="error"
    )
    ctx.conversations.set_model(conversation.id, "test/model-a")
    window.open_conversation(conversation.id)

    calls: list[tuple[str, str, str]] = []
    window._start_stream = lambda conv, text, model: calls.append((conv.id, text, model))  # type: ignore[method-assign]
    window._retry_last(failed.id)

    remaining = ctx.conversations.messages(conversation.id)
    assert remaining == []
    assert calls == [(conversation.id, "please answer", "test/model-a")]
    assert user.id not in {m.id for m in remaining}


# --------------------------------------------------- threading & network errors
def _slow_sse(chunks: list[str], delay: float = 0.06):
    def body():
        for chunk in chunks:
            yield (
                "data: " + json.dumps({"choices": [{"delta": {"content": chunk}}]}) + "\n\n"
            ).encode()
            time.sleep(delay)
        yield b"data: [DONE]\n\n"

    return body


def _install_transport(ctx, body_factory) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body_factory(), headers={"content-type": "text/event-stream"}
        )

    ctx.chat._client_factory = lambda: OpenRouterClient(
        ctx.secrets.get_api_key, transport=httpx.MockTransport(handler), timeout=10.0
    )


def test_ui_stays_responsive_while_streaming(ui) -> None:
    """The GUI thread must keep processing events during a slow stream."""
    from PySide6.QtCore import QTimer

    window, ctx, theme = ui
    ctx.secrets.set_api_key("sk-or-v1-test")
    _install_transport(ctx, _slow_sse(["alpha ", "beta ", "gamma ", "delta "]))
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A", context_length=8192)])
    window._on_api_model_selected("test/model-a")

    ticks = {"count": 0}
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.__setitem__("count", ticks["count"] + 1))
    timer.start()

    window.composer.input.setPlainText("stream slowly")
    window.composer._submit()
    deadline = time.time() + 10
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.01)
    timer.stop()
    pump()

    assert not window._generating
    assert ticks["count"] > 3, "the event loop was blocked by the worker thread"
    messages = ctx.conversations.messages(ctx.conversations.list()[0].id)
    assert messages[-1].content == "alpha beta gamma delta "
    assert messages[-1].status == "complete"


def test_network_error_is_reported_and_the_app_recovers(ui) -> None:
    window, ctx, theme = ui
    ctx.secrets.set_api_key("sk-or-v1-test")
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("network down")
        return httpx.Response(
            200,
            content=(
                "data: " + json.dumps({"choices": [{"delta": {"content": "recovered"}}]}) + "\n\n"
                "data: [DONE]\n\n"
            ).encode(),
            headers={"content-type": "text/event-stream"},
        )

    ctx.chat._client_factory = lambda: OpenRouterClient(
        ctx.secrets.get_api_key, transport=httpx.MockTransport(handler), timeout=5.0
    )
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A")])
    window._on_api_model_selected("test/model-a")

    window.composer.input.setPlainText("first try")
    window.composer._submit()
    deadline = time.time() + 8
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.01)
    pump()
    conversation = ctx.conversations.list()[0]
    messages = ctx.conversations.messages(conversation.id)
    assert messages[-1].status == "error"
    assert messages[-1].error
    assert not window._generating

    # The window is still usable: a second send succeeds.
    window.composer.input.setPlainText("second try")
    window.composer._submit()
    deadline = time.time() + 8
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.01)
    pump()
    messages = ctx.conversations.messages(conversation.id)
    assert messages[-1].content == "recovered"
    assert messages[-1].status == "complete"


def test_invalid_key_error_is_surfaced_in_the_window(ui) -> None:
    window, ctx, theme = ui
    ctx.secrets.set_api_key("sk-or-v1-wrong")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    ctx.chat._client_factory = lambda: OpenRouterClient(
        ctx.secrets.get_api_key, transport=httpx.MockTransport(handler), timeout=5.0
    )
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A")])
    window._on_api_model_selected("test/model-a")
    shown: list[str] = []
    window._show_toast = lambda message, level="info": shown.append(f"{level}:{message}")

    window.composer.input.setPlainText("will fail")
    window.composer._submit()
    deadline = time.time() + 8
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.01)
    pump()
    assert shown, "no feedback was given to the user"
    assert any(item.startswith("error:") for item in shown)
    assert any("key" in item.lower() or "کلید" in item for item in shown)
    messages = ctx.conversations.messages(ctx.conversations.list()[0].id)
    assert messages[-1].status == "error"


def test_cancel_from_the_window_keeps_partial_text(ui) -> None:
    window, ctx, theme = ui
    ctx.secrets.set_api_key("sk-or-v1-test")
    _install_transport(ctx, _slow_sse([f"w{i} " for i in range(40)], delay=0.03))
    window._on_models_loaded([ModelInfo(id="test/model-a", name="Model A")])
    window._on_api_model_selected("test/model-a")

    window.composer.input.setPlainText("cancel me")
    window.composer._submit()
    deadline = time.time() + 8
    for _ in range(200):
        pump()
        if window._stream_text:
            break
        time.sleep(0.01)
    assert window._stream_text, "no token arrived"
    window._stop_generation()
    while window._generating and time.time() < deadline:
        pump()
        time.sleep(0.01)
    pump()
    messages = ctx.conversations.messages(ctx.conversations.list()[0].id)
    assert messages[-1].status == "cancelled"
    assert messages[-1].content
    assert "w39" not in messages[-1].content


@pytest.mark.parametrize("scale", [1.25, 1.5])
def test_layout_survives_font_scale_and_small_window(ui, scale) -> None:
    """DPI scaling (1.25×/1.5×) at the minimum window size must not overflow."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QWidget

    window, ctx, theme = ui
    window.resize(1120, 720)
    ctx.settings.set("ui.font_scale", scale)
    pump()
    try:
        for route in ("api", "memory", "persona", "studio"):
            window._navigate(route)
            pump()
            page = window._pages[route]
            assert page.width() > 0 and page.height() > 0
            # Only laid-out page content is checked: popups live at global
    # coordinates and scroll content may legitimately be scrolled.
            for card in page.body.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if not card.isVisible():
                    continue
                origin = card.mapTo(page, QPoint(0, 0))
                assert origin.x() >= -2, (route, scale, type(card).__name__, origin.x())
                assert origin.x() + card.width() <= page.width() + 2, (
                    route, scale, type(card).__name__, origin.x(), card.width(), page.width()
                )
            origin = page.lead.mapTo(page, QPoint(0, 0))
            assert origin.x() >= -2 and origin.x() + page.lead.width() <= page.width() + 2
    finally:
        ctx.settings.set("ui.font_scale", 1.0)
        pump()


def test_studio_action_row_wraps_instead_of_clipping(ui) -> None:
    """1.5x font scale at the minimum width must keep every action visible."""
    window, ctx, theme = ui
    ctx.settings.set("ui.font_scale", 1.5)
    window.resize(1120, 720)
    window._navigate("studio")
    pump()
    try:
        page = window.studio_page
        host = page.actions_host
        page_right = page.mapToGlobal(host.rect().topRight()).x()
        assert page.actions_host.width() > 0
        for button in (page.save_button, page.format_button, page.export_button, page.delete_button):
            assert button.isVisible(), button.text()
            right = button.mapToGlobal(button.rect().topRight()).x()
            assert right <= page_right + 2, (button.text(), right, page_right)
            assert button.width() >= button.minimumSizeHint().width() - 2
    finally:
        ctx.settings.set("ui.font_scale", 1.0)
        pump()


def test_studio_action_row_follows_rtl(ui) -> None:
    from PySide6.QtCore import Qt

    window, ctx, theme = ui
    window._navigate("studio")
    pump()
    page = window.studio_page
    try:
        set_language("fa")
        window._retranslate()
        pump()
        assert page.layoutDirection() == Qt.LayoutDirection.RightToLeft
        save_x = page.save_button.mapTo(page, page.save_button.rect().topLeft()).x()
        delete_x = page.delete_button.mapTo(page, page.delete_button.rect().topLeft()).x()
        # The primary action sits first, i.e. furthest right in RTL.
        assert save_x > delete_x, (save_x, delete_x)
    finally:
        set_language("en")
        window._retranslate()
        pump()


def test_header_declutters_instead_of_overlapping(ui) -> None:
    window, ctx, theme = ui
    window.resize(1120, 720)
    pump()
    header = window.header

    def geometry(widget):
        origin = widget.mapTo(header, widget.rect().topLeft())
        return origin.x(), origin.x() + widget.width()

    title_left, title_right = geometry(header.title)
    chip_left, chip_right = geometry(header.model_chip)
    # Direction-agnostic: whichever side the title is on, it must not run into
    # the model chip.
    assert title_right <= chip_left or chip_right <= title_left, (
        (title_left, title_right),
        (chip_left, chip_right),
    )
    # Nothing may extend past the header itself.
    for widget in (header.model_chip, header.status, header.context_ring, header.more_button):
        if not widget.isVisible():
            continue
        right = widget.mapTo(header, widget.rect().topRight()).x()
        assert right <= header.width() + 2, (type(widget).__name__, right, header.width())


# ------------------------------------------------- regression: language leakage
def _has_persian(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def _visible_text(root) -> list[str]:  # noqa: ANN001
    from PySide6.QtWidgets import QLabel, QPushButton

    texts: list[str] = []
    for widget in root.findChildren(QLabel) + root.findChildren(QPushButton):
        if widget.isVisible() and widget.text():
            texts.append(widget.text())
    return texts


def test_english_pages_contain_no_persian_text(ui) -> None:
    """Screenshot review found a Persian button on an English page.

    Everything that is built once and only relabelled later could keep the
    language it was constructed in; this walks the real pages and fails on any
    Arabic-script character while the UI is English.
    """
    window, ctx, theme = ui
    set_language("en")
    try:
        window._retranslate()
        for route in ("api", "memory", "persona", "studio", "code"):
            window._navigate(route)
            pump()
            page = window.stack.currentWidget()
            page.grab()  # force the widgets into their laid-out state
            pump()
            for text in _visible_text(page):
                assert not _has_persian(text), (route, text)
    finally:
        set_language("fa")


def test_placeholder_feature_rows_never_clip_wrapped_text(ui) -> None:
    """A clipped second line was visible in the fa rendering of Code Studio."""
    window, ctx, theme = ui
    set_language("fa")
    try:
        window._retranslate()
        window.resize(1120, 720)
        window._navigate("code")
        for _ in range(4):
            pump()
        content = window.placeholder.content
        assert content.features_grid.count() == 3
        for index in range(content.features_grid.count()):
            item = content.features_grid.itemAt(index).widget()
            label = item.label
            needed = label.heightForWidth(label.width())
            assert label.height() >= needed - 1, (index, label.text(), label.height(), needed)
            assert item.height() >= label.height(), (index, item.height(), label.height())
    finally:
        set_language("en")


def test_pill_toggle_label_never_underlaps_its_icon(ui) -> None:
    """The persona page drew the first letter on top of the check icon."""
    from PySide6.QtGui import QFontMetrics

    from myai.ui.theme import runtime
    from myai.ui.widgets.fields import PillToggle

    window, ctx, theme = ui
    pill = PillToggle("check", "Send persona with requests")
    pill.resize(pill.minimumWidth(), pill.height())
    pill.show()
    pump()
    try:
        icon, text = pill._icon_rect(), pill._text_rect()
        assert not icon.intersects(text), (icon.getRect(), text.getRect())
        needs = QFontMetrics(runtime.ui_font(11, 500)).horizontalAdvance(pill._text)
        assert text.width() >= needs, (text.width(), needs)
        assert pill.width() >= needs + runtime.px(36)
    finally:
        pill.deleteLater()

    ctx.settings.set("ui.language", "fa")
    QApplication.processEvents()
    try:
        pill = PillToggle("check", "ارسال شخصیت همراه درخواست‌ها")
        pill.resize(pill.minimumWidth(), pill.height())
        pump()
        assert pill._text_rect().right() < pill._icon_rect().left(), (
            pill._text_rect().getRect(), pill._icon_rect().getRect()
        )
    finally:
        ctx.settings.set("ui.language", "en")
        pill.deleteLater()


def test_chrome_sizes_follow_the_font_scale(ui) -> None:
    """Chat/Agent and the model chip overlapped at 1.5x in the DPI capture."""
    from PySide6.QtGui import QFontMetrics

    from myai.ui.theme import runtime

    window, ctx, theme = ui
    try:
        for scale in (1.0, 1.5):
            ctx.settings.set("ui.font_scale", scale)
            pump()
            window.resize(int(1440 / scale), int(900 / scale))
            pump()
            metrics = QFontMetrics(runtime.ui_font(12, 500))
            needed = sum(
                metrics.horizontalAdvance(label) + runtime.px(24)
                for _, label in window.header.mode._items
            ) + runtime.px(8)
            assert window.header.mode.width() >= needed, (scale, window.header.mode.width(), needed)
            chip = window.header.model_chip
            assert chip.width() >= runtime.px(92), (scale, chip.width())
            assert chip.height() == runtime.px(30), (scale, chip.height())
    finally:
        ctx.settings.set("ui.font_scale", 1.0)
        pump()


# ------------------------------------------------------- no dead buttons, ever
def _qt_messages(monkeypatch) -> list[str]:  # noqa: ANN001
    from PySide6.QtCore import qInstallMessageHandler

    captured: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, message: captured.append(message))
    monkeypatch.setattr(QApplication, "_myai_previous_handler", previous, raising=False)
    return captured


def _is_wired(button, messages: list[str]) -> bool:  # noqa: ANN001
    """True when the button has at least one receiver on clicked/toggled.

    Qt's own object dump is the source: it lists every connection, including
    the Python slots used by this app, so this is not a heuristic on our code.
    """
    messages.clear()
    button.dumpObjectInfo()
    wanted = ("signal: clicked", "signal: toggled")
    in_block = False
    for line in messages:
        stripped = line.strip()
        if stripped.startswith("signal:"):
            in_block = stripped.startswith(wanted)
            continue
        if stripped.startswith("SIGNALS IN"):
            in_block = False
            continue
        if in_block and (stripped.startswith("-->") or stripped.startswith("<functor")):
            return True
    return False


@pytest.mark.parametrize("route", ["api", "memory", "persona", "studio"])
def test_every_button_on_the_ai_pages_has_a_receiver(ui, monkeypatch, route) -> None:
    """A button that looks live but does nothing was an explicit acceptance fail."""
    from PySide6.QtWidgets import QLineEdit, QListWidget, QPlainTextEdit, QPushButton

    from myai.ui.widgets.fields import SelectField

    window, ctx, theme = ui
    window._navigate(route)
    pump()
    page = window._pages[route]
    messages = _qt_messages(monkeypatch)
    dead: list[str] = []
    for button in page.findChildren(QPushButton):
        if not button.isVisible():
            continue
        if not _is_wired(button, messages):
            dead.append(button.text())
    assert not dead, (route, dead)

    # A page must accept input or offer a real action, not just show text.
    interactive = sum(
        1
        for kind in (QPushButton, QLineEdit, QPlainTextEdit, QListWidget, SelectField)
        for widget in page.findChildren(kind)
        if widget.isVisible() and widget.isEnabled()
    )
    assert interactive >= 2, (route, interactive)
