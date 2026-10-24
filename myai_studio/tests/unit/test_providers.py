"""Multi-provider support: specs, keys, catalogues and the three protocols.

Every network interaction here goes through ``httpx.MockTransport``, so the
assertions are about the real client code (headers, paths, payload shape, SSE
parsing) and never about a live vendor. No test claims a live call.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from myai.core.errors import ConfigurationError, NetworkError, ProviderError, ValidationError
from myai.security.secrets import SecretStore
from myai.services import providers
from myai.services.net import NetworkOptions
from myai.services.providers import (
    ProviderClient,
    base_url_for,
    build_client,
    cached_models,
    get_provider,
    key_problem,
    models_cache,
    network_for,
    normalize_base_url,
    provider_ids,
    save_base_url,
    validate_key,
)

OPENROUTER_KEY = "sk-or-v1-" + "a" * 64


# ------------------------------------------------------------------ registry
def test_every_provider_id_is_unique_and_the_default_exists() -> None:
    ids = [provider.id for provider in providers.all_providers()]
    assert len(ids) == len(set(ids))
    assert "openrouter" in ids
    assert get_provider("openrouter").id == "openrouter"


def test_unknown_provider_falls_back_instead_of_crashing() -> None:
    assert get_provider("nope").id == "openrouter"
    assert get_provider(None).id == "openrouter"
    assert get_provider("GEMINI").id == "gemini"


def test_each_published_provider_has_a_documented_base_url() -> None:
    for provider in providers.all_providers():
        if provider.id == "custom":
            assert provider.base_url == ""
            continue
        assert provider.base_url.startswith(("https://", "http://")), provider.id
        assert provider.protocol in {"openai", "anthropic", "gemini"}


def test_local_providers_do_not_require_a_key() -> None:
    for provider in providers.all_providers():
        if provider.local:
            assert provider.key_required is False, provider.id


# ---------------------------------------------------------------------- keys
def test_openrouter_still_rejects_a_key_with_the_wrong_prefix() -> None:
    assert key_problem(get_provider("openrouter"), "sk-live-123") == "api.key_format"
    assert key_problem(get_provider("openrouter"), OPENROUTER_KEY) is None


def test_other_providers_accept_their_own_key_formats() -> None:
    openai = get_provider("openai")
    anthropic = get_provider("anthropic")
    assert key_problem(openai, "sk-proj-abc123") is None
    assert key_problem(anthropic, "sk-ant-api03-xyz") is None
    assert key_problem(get_provider("gemini"), "AIzaSyD-123") is None


def test_keys_are_rejected_for_whitespace_and_absurd_length() -> None:
    provider = get_provider("openai")
    assert key_problem(provider, "sk-abc def") == "api.key_invalid_chars"
    assert key_problem(provider, "sk-" + "x" * 5000) == "api.key_too_long"
    assert key_problem(provider, "sk-\nInjected: 1") == "api.key_invalid_chars"


def test_a_missing_key_is_only_an_error_where_it_is_required() -> None:
    assert key_problem(get_provider("openai"), "") == "error.api_key_missing"
    assert key_problem(get_provider("ollama"), "") is None
    assert key_problem(get_provider("custom"), "") is None


def test_validate_key_raises_a_translated_configuration_error() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        validate_key(get_provider("openai"), "")
    assert excinfo.value.message_key == "error.api_key_missing"


# ----------------------------------------------------------------- base URLs
def test_base_urls_are_https_except_on_the_loopback_interface() -> None:
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert normalize_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert normalize_base_url("http://localhost:1234/v1") == "http://localhost:1234/v1"
    with pytest.raises(ValidationError):
        normalize_base_url("http://api.example.com/v1")
    with pytest.raises(ValidationError):
        normalize_base_url("ftp://api.example.com")
    with pytest.raises(ValidationError):
        normalize_base_url("api.example.com/v1")


def test_custom_provider_needs_a_url_but_the_others_fall_back() -> None:
    with pytest.raises(ValidationError):
        normalize_base_url("", provider=get_provider("custom"))
    assert normalize_base_url("", provider=get_provider("openai")) == "https://api.openai.com/v1"


def test_saved_urls_are_remembered_per_provider(ctx) -> None:  # noqa: ANN001
    gemini = get_provider("gemini")
    save_base_url(ctx.settings, gemini, "https://gemini-proxy.local/v1beta/")
    assert base_url_for(gemini, ctx.settings) == "https://gemini-proxy.local/v1beta"
    assert base_url_for(get_provider("openai"), ctx.settings) == "https://api.openai.com/v1"
    assert ctx.settings.get("ai.provider") == "gemini"


def test_an_old_single_base_url_is_still_honoured(ctx) -> None:  # noqa: ANN001
    ctx.settings.update({"ai.base_url": "https://openrouter-proxy.example/api/v1"})
    assert base_url_for(get_provider("openrouter"), ctx.settings).endswith("/api/v1")
    assert base_url_for(get_provider("openai"), ctx.settings) == "https://api.openai.com/v1"


# -------------------------------------------------------------------- models
def _client(provider: str, *, key: str = "test-key", handler=None, **kwargs) -> ProviderClient:  # noqa: ANN001
    return ProviderClient(
        lambda: key,
        provider=provider,
        transport=httpx.MockTransport(handler) if handler else None,
        network=NetworkOptions(mode="off"),
        **kwargs,
    )


def test_openai_compatible_catalogue_is_parsed_without_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-4o-mini", "object": "model"},
                    {"id": "gpt-4o", "object": "model"},
                ]
            },
        )

    models = _client("openai", handler=handler).list_models(refresh=True)
    assert [model.id for model in models] == ["gpt-4o", "gpt-4o-mini"]
    assert all(model.price_known is False for model in models)
    # No prices in the payload means "unknown", never "free".
    assert all(model.is_free() is False for model in models)


def test_openrouter_catalogue_keeps_its_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/free-model:free",
                        "name": "Free",
                        "context_length": 8192,
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                    {
                        "id": "vendor/paid",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    },
                ]
            },
        )

    models = _client("openrouter", key=OPENROUTER_KEY, handler=handler).list_models(refresh=True)
    free = next(model for model in models if model.id.endswith(":free"))
    paid = next(model for model in models if model.id == "vendor/paid")
    assert free.is_free() is True
    assert paid.is_free() is False
    assert paid.prompt_price == pytest.approx(1.0)


def test_anthropic_catalogue_uses_display_names_and_follows_pages() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "sk-ant-1"
        assert "authorization" not in request.headers
        after = request.url.params.get("after_id")
        calls.append(after or "")
        if not after:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-sonnet-4", "display_name": "Claude Sonnet 4"}],
                    "has_more": True,
                    "last_id": "claude-sonnet-4",
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [{"id": "claude-haiku-3.5", "display_name": "Claude Haiku 3.5"}],
                "has_more": False,
            },
        )

    models = _client("anthropic", key="sk-ant-1", handler=handler).list_models(refresh=True)
    assert [model.id for model in models] == ["claude-haiku-3.5", "claude-sonnet-4"]
    assert models[1].name == "Claude Sonnet 4"
    assert calls == ["", "claude-sonnet-4"]


def test_gemini_catalogue_drops_embedding_models_and_strips_the_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models"
        assert request.headers["x-goog-api-key"] == "AIza-1"
        assert "key" not in request.url.params
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-pro",
                        "displayName": "Gemini 2.5 Pro",
                        "inputTokenLimit": 1048576,
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    },
                    {
                        "name": "models/text-embedding-004",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    models = _client("gemini", key="AIza-1", handler=handler).list_models(refresh=True)
    assert [model.id for model in models] == ["gemini-2.5-pro"]
    assert models[0].context_length == 1_048_576
    assert models[0].price_known is False


def test_a_missing_catalogue_on_a_custom_endpoint_is_not_a_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    models = _client("custom", handler=handler, base_url="http://127.0.0.1:9999/v1").list_models(
        refresh=True
    )
    assert models == []


def test_local_catalogue_falls_back_to_a_stated_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    models = _client("ollama", key="", handler=handler).list_models(refresh=True)
    ids = [model.id for model in models]
    assert "llama3.2" in ids
    assert all(model.price_known is False for model in models)


def test_transport_failure_is_wrapped_with_the_stage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("TLS handshake failed", request=request)

    with pytest.raises(NetworkError) as excinfo:
        _client("openai", handler=handler).list_models(refresh=True)
    assert excinfo.value.context.get("stage") == "tls"


# ------------------------------------------------------------------ headers
def test_headers_match_each_vendor_protocol() -> None:
    openai = _client("openai", key="sk-proj-1")._headers()
    assert openai["Authorization"] == "Bearer sk-proj-1"
    anthropic = _client("anthropic", key="sk-ant-1")._headers()
    assert anthropic["x-api-key"] == "sk-ant-1"
    assert anthropic["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in anthropic
    gemini = _client("gemini", key="AIza-1")._headers()
    assert gemini["x-goog-api-key"] == "AIza-1"
    assert "Authorization" not in gemini
    router = _client("openrouter", key=OPENROUTER_KEY)._headers()
    assert router["HTTP-Referer"]


def test_a_key_that_does_not_fit_the_provider_fails_before_the_request() -> None:
    client = _client("openrouter", key="sk-live-123")
    with pytest.raises(ConfigurationError):
        client._headers()


def test_local_providers_send_no_authorization_header() -> None:
    headers = _client("ollama", key="")._headers()
    assert "Authorization" not in headers
    assert "x-api-key" not in headers


# ------------------------------------------------------------------- streams
def _sse(*events: str) -> bytes:
    return ("".join(f"data: {event}\n\n" for event in events)).encode()


def test_anthropic_stream_hoists_system_and_reads_usage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        body = _sse(
            json.dumps(
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 12, "output_tokens": 1}},
                }
            ),
            json.dumps(
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}}
            ),
            json.dumps(
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}}
            ),
            json.dumps(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 2},
                }
            ),
            json.dumps({"type": "message_stop"}),
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    chunks: list[str] = []
    result = _client("anthropic", key="sk-ant-1", handler=handler).stream_chat(
        model="claude-sonnet-4",
        messages=[
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "Hi"},
        ],
        temperature=1.7,
        max_tokens=100,
        on_delta=chunks.append,
    )
    assert result.text == "Hello"
    assert chunks == ["Hel", "lo"]
    assert result.stats.prompt_tokens == 12
    assert result.stats.completion_tokens == 2
    assert result.stats.finish_reason == "end_turn"
    assert seen["system"] == "Be precise."
    assert seen["messages"] == [{"role": "user", "content": "Hi"}]
    assert seen["temperature"] == 1.0  # clamped to Anthropic's range


def test_gemini_stream_maps_roles_and_reads_parts() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models/gemini-2.5-flash:streamGenerateContent"
        assert request.url.params.get("alt") == "sse"
        seen.update(json.loads(request.content))
        body = _sse(
            json.dumps(
                {
                    "candidates": [{"content": {"parts": [{"text": "Bon"}]}}],
                    "usageMetadata": {"promptTokenCount": 4},
                }
            ),
            json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "jour"}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 3},
                }
            ),
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = _client("gemini", key="AIza-1", handler=handler).stream_chat(
        model="gemini-2.5-flash",
        messages=[
            {"role": "system", "content": "Answer in French."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Salut"},
            {"role": "user", "content": "Again"},
        ],
    )
    assert result.text == "Bonjour"
    assert result.stats.prompt_tokens == 4
    assert result.stats.completion_tokens == 3
    assert result.stats.finish_reason == "STOP"
    assert seen["systemInstruction"]["parts"][0]["text"] == "Answer in French."
    roles = [row["role"] for row in seen["contents"]]
    assert roles == ["user", "model", "user"]


def test_openai_protocol_is_used_for_every_compatible_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openai/v1/chat/completions"
        body = _sse(
            json.dumps({"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}),
            "[DONE]",
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = _client("groq", key="gsk_1", handler=handler).stream_chat(
        model="llama-3.3-70b",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result.text == "hi"


def test_anthropic_provider_error_event_becomes_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse(
            json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    with pytest.raises(ProviderError) as excinfo:
        _client("anthropic", key="sk-ant-1", handler=handler).stream_chat(
            model="claude-sonnet-4", messages=[{"role": "user", "content": "hi"}]
        )
    assert "busy" in excinfo.value.message


def test_gemini_prompt_block_is_reported_not_silently_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}))
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    with pytest.raises(ProviderError) as excinfo:
        _client("gemini", key="AIza-1", handler=handler).stream_chat(
            model="gemini-2.5-flash", messages=[{"role": "user", "content": "hi"}]
        )
    assert "SAFETY" in excinfo.value.message


def test_streaming_can_be_cancelled() -> None:
    import threading

    cancel = threading.Event()
    cancel.set()

    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse(json.dumps({"type": "content_block_delta", "delta": {"text": "x"}}))
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    result = _client("anthropic", key="sk-ant-1", handler=handler).stream_chat(
        model="claude-sonnet-4", messages=[{"role": "user", "content": "hi"}], cancel=cancel
    )
    assert result.cancelled is True
    assert result.text == ""


# ---------------------------------------------------------------- integration
def test_build_client_binds_the_selected_provider_and_its_own_key(ctx) -> None:  # noqa: ANN001
    store = SecretStore(ctx.paths.secrets_file, ctx.paths.secret_key_file)
    store.set_key("openai", "sk-openai-1")
    store.set_key("openrouter", OPENROUTER_KEY)
    ctx.settings.update({"ai.provider": "openai"})
    client = build_client(ctx.settings, store)
    assert client.spec.id == "openai"
    assert client._headers()["Authorization"] == "Bearer sk-openai-1"
    ctx.settings.update({"ai.provider": "openrouter"})
    assert build_client(ctx.settings, store)._headers()["Authorization"] == f"Bearer {OPENROUTER_KEY}"


def test_local_provider_bypasses_the_system_proxy(ctx) -> None:  # noqa: ANN001
    ctx.settings.update({"network.proxy_mode": "manual", "network.proxy_url": "http://127.0.0.1:10809"})
    local = network_for(get_provider("ollama"), ctx.settings)
    remote = network_for(get_provider("openai"), ctx.settings)
    assert local.mode == "off"
    assert remote.mode == "manual"


def test_secrets_are_stored_per_provider(ctx) -> None:  # noqa: ANN001
    store = SecretStore(ctx.paths.secrets_file, ctx.paths.secret_key_file)
    store.set_key("openai", "sk-openai-1")
    store.set_key("gemini", "AIza-1")
    assert store.get_key("openai") == "sk-openai-1"
    assert store.get_key("gemini") == "AIza-1"
    assert store.get_key("openrouter") is None
    assert store.configured_providers() == ["gemini", "openai"]
    store.set_key("openai", "")
    assert store.get_key("openai") is None
    with pytest.raises(ValueError):
        store.key_name("../evil")


def test_the_old_openrouter_key_slot_is_reused(ctx) -> None:  # noqa: ANN001
    store = SecretStore(ctx.paths.secrets_file, ctx.paths.secret_key_file)
    store.set_api_key(OPENROUTER_KEY)  # the 0.8 method
    assert store.get_key("openrouter") == OPENROUTER_KEY
    assert store.has_key("openrouter") is True


def test_model_cache_is_per_provider_and_migrates_the_old_list(ctx) -> None:  # noqa: ANN001
    settings = ctx.settings
    settings.update({"ai.openrouter_cache": [{"id": "a/b"}]})
    assert cached_models(settings, "openrouter") == [{"id": "a/b"}]
    settings.update({"ai.model_cache": {"openai": [{"id": "gpt-4o"}]}})
    assert cached_models(settings, "openai") == [{"id": "gpt-4o"}]
    assert models_cache(settings)["openrouter"] == [{"id": "a/b"}]


def test_settings_reject_an_unknown_provider_but_accept_known_ones(ctx) -> None:  # noqa: ANN001
    from myai.core.errors import ValidationError as SettingsError

    with pytest.raises(SettingsError):
        ctx.settings.update({"ai.provider": "not-a-provider"})
    ctx.settings.update({"ai.provider": "anthropic"})
    assert ctx.settings.get("ai.provider") == "anthropic"


def test_settings_accept_http_only_for_a_local_provider(ctx) -> None:  # noqa: ANN001
    from myai.core.errors import ValidationError as SettingsError

    ctx.settings.update({"ai.base_urls": {"ollama": "http://127.0.0.1:11434/v1"}})
    assert ctx.settings.get("ai.base_urls")["ollama"].endswith("/v1")
    with pytest.raises(SettingsError):
        ctx.settings.update({"ai.base_url": "http://api.openai.com/v1"})


def test_settings_and_providers_import_in_a_fresh_interpreter() -> None:
    """A real cycle would only show in a process that has no modules loaded."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import myai.services.settings, myai.services.providers, "
            "myai.services.chat, myai.context; print('ok')",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout


def test_provider_ids_are_exported_for_the_ui() -> None:
    assert "custom" in provider_ids()
    assert len(provider_ids()) == len(providers.PROVIDERS)


def test_describe_reports_the_effective_endpoint() -> None:
    client = _client("openai")
    described = client.describe()
    assert described["base_url"] == "https://api.openai.com/v1"
    assert described["tools"] is True
    assert _client("gemini", key="AIza-1").describe()["tools"] is False


def test_paths_do_not_leak_into_the_key(tmp_path: Path) -> None:
    """A provider id is never a path fragment (defensive, cheap)."""
    store = SecretStore(tmp_path / "s.bin", tmp_path / "k.key")
    assert store.key_name("openrouter") == SecretStore.OPENROUTER_KEY
    assert store.key_name("gemini") == "ai.key.gemini"


def test_settings_service_roundtrip_of_the_new_keys() -> None:
    """The new defaults exist, so a fresh install is coherent without migration."""
    from myai.services.settings import DEFAULTS

    assert DEFAULTS["ai.provider"] == "openrouter"
    assert DEFAULTS["ai.base_urls"] == {}
    assert DEFAULTS["ai.model_cache"] == {}


def test_a_keyless_custom_provider_builds_headers_without_authorization(ctx) -> None:  # noqa: ANN001
    store = SecretStore(ctx.paths.secrets_file, ctx.paths.secret_key_file)
    ctx.settings.update(
        {
            "ai.provider": "custom",
            "ai.base_urls": {"custom": "http://127.0.0.1:9999/v1"},
        }
    )
    client = build_client(ctx.settings, store)
    headers = client._headers()
    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers
