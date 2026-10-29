"""Talk to more than OpenRouter.

The app used to have exactly one provider baked into every layer: the key was
validated as ``sk-or-…``, the client pointed at ``openrouter.ai`` and the
catalogue parser knew OpenRouter's price fields.  Anything else was impossible
even though most vendors speak the same wire protocol.

This module is the single place that knows the difference:

* :class:`Provider` — a named endpoint plus the protocol it speaks.
* :func:`key_problem` — what can be checked offline about a key for *that*
  provider (never the server's verdict).
* :class:`ProviderClient` — one streaming client for three real protocols:
  ``openai`` (OpenAI, OpenRouter, Groq, DeepSeek, Mistral, local Ollama and
  LM Studio, any custom OpenAI-compatible base URL), ``anthropic`` (Messages
  API) and ``gemini`` (generative language API).

Honesty rules kept from the OpenRouter client: no price is invented (a
catalogue without prices sets ``price_known=False`` instead of claiming
"free"), a capability is only advertised when the catalogue says so, and a
missing model list falls back to a *stated* static list, never a fake one.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..core.errors import (
    AppError,
    ConfigurationError,
    ProviderError,
    ValidationError,
)
from .net import NetworkOptions
from .openrouter import (
    APP_REFERER,
    APP_TITLE,
    CancelledProviderError,
    ChatResult,
    ModelInfo,
    OpenRouterClient,
    StreamStats,
)

logger = logging.getLogger(__name__)

PROTOCOL_OPENAI = "openai"
PROTOCOL_ANTHROPIC = "anthropic"
PROTOCOL_GEMINI = "gemini"

#: Prefixes that are cheap to check offline. Only OpenRouter's is enforced: the
#: others are hints, because vendors do change key formats and a wrong guess
#: would lock a paying user out of their own account.
KEY_MAX = 400


@dataclass(frozen=True)
class Provider:
    """One endpoint the app can talk to."""

    id: str
    name: str
    protocol: str
    base_url: str
    key_hint: str = ""
    key_prefix: str = ""
    key_required: bool = True
    local: bool = False
    docs_url: str = ""
    #: Shown when the catalogue cannot be listed (custom endpoints, offline).
    fallback_models: tuple[str, ...] = ()
    #: True when the vendor publishes token prices in its catalogue.
    publishes_prices: bool = False
    #: i18n key for the one-line note under the provider selector.
    note_key: str = ""
    #: True for an endpoint the user added on the API page. Custom endpoints are
    #: stored in settings, not in this module, and can be removed by their owner.
    custom: bool = False

    @property
    def needs_key(self) -> bool:
        return self.key_required

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "local": self.local,
            "key_required": self.key_required,
            "docs_url": self.docs_url,
            "custom": self.custom,
        }


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="openrouter",
        name="OpenRouter",
        protocol=PROTOCOL_OPENAI,
        base_url="https://openrouter.ai/api/v1",
        key_hint="sk-or-v1-…",
        key_prefix="sk-or-",
        docs_url="https://openrouter.ai/keys",
        publishes_prices=True,
        note_key="provider.note_openrouter",
    ),
    Provider(
        id="openai",
        name="OpenAI",
        protocol=PROTOCOL_OPENAI,
        base_url="https://api.openai.com/v1",
        key_hint="sk-…",
        docs_url="https://platform.openai.com/api-keys",
        note_key="provider.note_openai",
    ),
    Provider(
        id="anthropic",
        name="Anthropic",
        protocol=PROTOCOL_ANTHROPIC,
        base_url="https://api.anthropic.com/v1",
        key_hint="sk-ant-…",
        docs_url="https://console.anthropic.com/settings/keys",
        note_key="provider.note_anthropic",
    ),
    Provider(
        id="gemini",
        name="Google Gemini",
        protocol=PROTOCOL_GEMINI,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        key_hint="AIza…",
        docs_url="https://aistudio.google.com/app/apikey",
        note_key="provider.note_gemini",
    ),
    Provider(
        id="groq",
        name="Groq",
        protocol=PROTOCOL_OPENAI,
        base_url="https://api.groq.com/openai/v1",
        key_hint="gsk_…",
        docs_url="https://console.groq.com/keys",
        note_key="provider.note_openai_compatible",
    ),
    Provider(
        id="deepseek",
        name="DeepSeek",
        protocol=PROTOCOL_OPENAI,
        base_url="https://api.deepseek.com/v1",
        key_hint="sk-…",
        docs_url="https://platform.deepseek.com/api_keys",
        note_key="provider.note_openai_compatible",
    ),
    Provider(
        id="mistral",
        name="Mistral",
        protocol=PROTOCOL_OPENAI,
        base_url="https://api.mistral.ai/v1",
        key_hint="…",
        docs_url="https://console.mistral.ai/api-keys/",
        note_key="provider.note_openai_compatible",
    ),
    Provider(
        id="gapgpt",
        name="GapGPT",
        protocol=PROTOCOL_OPENAI,
        base_url="https://api.gapgpt.app/v1",
        key_hint="…",
        docs_url="https://gapgpt.app",
        note_key="provider.note_gapgpt",
    ),
    Provider(
        id="tooken",
        name="Tooken Club",
        protocol=PROTOCOL_OPENAI,
        base_url="https://tooken.club/v1",
        key_hint="tc_live_…",
        key_prefix="tc_live_",
        docs_url="https://tooken.club/dashboard",
        note_key="provider.note_tooken",
    ),
    Provider(
        id="ollama",
        name="Ollama (local)",
        protocol=PROTOCOL_OPENAI,
        base_url="http://127.0.0.1:11434/v1",
        key_required=False,
        local=True,
        fallback_models=("llama3.2", "qwen2.5-coder", "mistral", "gemma3"),
        note_key="provider.note_local",
    ),
    Provider(
        id="lmstudio",
        name="LM Studio (local)",
        protocol=PROTOCOL_OPENAI,
        base_url="http://127.0.0.1:1234/v1",
        key_required=False,
        local=True,
        note_key="provider.note_local",
    ),
    Provider(
        id="custom",
        name="Custom (OpenAI-compatible)",
        protocol=PROTOCOL_OPENAI,
        base_url="",
        key_hint="…",
        key_required=False,
        note_key="provider.note_custom",
    ),
)

_BY_ID = {provider.id: provider for provider in PROVIDERS}
DEFAULT_PROVIDER = "openrouter"

#: Ids of endpoints the user added start here. The vault accepts only
#: ``^[a-z][a-z0-9_-]{0,30}$`` as a provider id, so ``custom:<name>`` is not an
#: option — and a fixed prefix keeps a user endpoint from shadowing a built-in.
CUSTOM_PREFIX = "cx-"
SETTING_CUSTOM_ENDPOINTS = "ai.custom_endpoints"
PROTOCOLS = (PROTOCOL_OPENAI, PROTOCOL_ANTHROPIC, PROTOCOL_GEMINI)

#: Registered custom endpoints, in insertion order. Kept in a module-level map
#: because every layer already asks ``get_provider(id)`` without settings.
_CUSTOM: dict[str, Provider] = {}


def slugify_endpoint_id(name: str) -> str:
    """A stable, vault-safe id from a display name (``My Gateway`` → ``cx-my-gateway``)."""
    slug = "".join(
        character if character.isalnum() else "-"
        for character in (name or "").strip().lower()
    )
    slug = "-".join(part for part in slug.split("-") if part)
    if not slug:
        slug = "endpoint"
    if not slug[0].isalpha():
        slug = f"e{slug}"
    # The prefix costs three characters of the 31 the vault allows.
    return f"{CUSTOM_PREFIX}{slug[:28]}"


def custom_provider(
    *,
    name: str,
    base_url: str,
    protocol: str = PROTOCOL_OPENAI,
    key_required: bool = True,
    endpoint_id: str = "",
) -> Provider:
    """Build the :class:`Provider` described by one saved custom endpoint."""
    clean_name = (name or "").strip() or "Custom endpoint"
    identifier = (endpoint_id or "").strip().lower() or slugify_endpoint_id(clean_name)
    return Provider(
        id=identifier,
        name=clean_name,
        protocol=protocol if protocol in PROTOCOLS else PROTOCOL_OPENAI,
        base_url=(base_url or "").strip().rstrip("/"),
        key_hint="…",
        key_required=bool(key_required),
        note_key="",
        custom=True,
        publishes_prices=False,
    )


def register_custom_endpoints(rows: list[dict] | None) -> tuple[Provider, ...]:
    """Replace the custom-endpoint registry (called after settings load/save)."""
    _CUSTOM.clear()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        provider = custom_provider(
            name=str(row.get("name", "")),
            base_url=str(row.get("base_url", "")),
            protocol=str(row.get("protocol", PROTOCOL_OPENAI)),
            key_required=bool(row.get("key_required", True)),
            endpoint_id=str(row.get("id", "")),
        )
        if provider.base_url:
            _CUSTOM[provider.id] = provider
    return tuple(_CUSTOM.values())


def custom_endpoints(settings) -> list[dict]:  # noqa: ANN001 - settings is duck-typed
    raw = settings.get(SETTING_CUSTOM_ENDPOINTS, []) or []
    return [dict(row) for row in raw if isinstance(row, dict)]


def sync_custom_endpoints(settings) -> tuple[Provider, ...]:  # noqa: ANN001
    return register_custom_endpoints(custom_endpoints(settings))


def save_custom_endpoint(settings, row: dict) -> Provider:  # noqa: ANN001
    """Add or replace one custom endpoint and make it the active provider."""
    provider = custom_provider(
        name=str(row.get("name", "")),
        base_url=str(row.get("base_url", "")),
        protocol=str(row.get("protocol", PROTOCOL_OPENAI)),
        key_required=bool(row.get("key_required", True)),
        endpoint_id=str(row.get("id", "")),
    )
    if not provider.base_url:
        raise ValidationError(
            "A custom endpoint needs a base URL", message_key="api.base_url_required"
        )
    # Same https rule as every other remote host; loopback may stay http.
    provider = replace(
        provider, base_url=normalize_base_url(provider.base_url, provider=provider)
    )
    rows = [entry for entry in custom_endpoints(settings) if entry.get("id") != provider.id]
    rows.append(
        {
            "id": provider.id,
            "name": provider.name,
            "base_url": provider.base_url,
            "protocol": provider.protocol,
            "key_required": provider.key_required,
        }
    )
    # Register before saving: the settings layer validates ``ai.provider``
    # against the registry, so the new id has to exist by then.
    register_custom_endpoints(rows)
    settings.update({SETTING_CUSTOM_ENDPOINTS: rows, "ai.provider": provider.id})
    return provider


def delete_custom_endpoint(settings, endpoint_id: str) -> bool:  # noqa: ANN001
    """Remove one custom endpoint (and its stored URL). Returns True if it existed."""
    rows = custom_endpoints(settings)
    kept = [row for row in rows if str(row.get("id", "")) != endpoint_id]
    if len(kept) == len(rows):
        return False
    urls = settings.get("ai.base_urls", {}) or {}
    urls = (
        {key: value for key, value in urls.items() if key != endpoint_id}
        if isinstance(urls, dict)
        else {}
    )
    updates: dict[str, Any] = {SETTING_CUSTOM_ENDPOINTS: kept, "ai.base_urls": urls}
    if str(settings.get("ai.provider", "")) == endpoint_id:
        updates["ai.provider"] = DEFAULT_PROVIDER
    register_custom_endpoints(kept)
    settings.update(updates)
    return True


def all_providers() -> tuple[Provider, ...]:
    """Built-in services first, then the endpoints the user added (by name)."""
    custom = sorted(_CUSTOM.values(), key=lambda provider: provider.name.casefold())
    return (*PROVIDERS, *custom)


def provider_ids() -> tuple[str, ...]:
    return tuple(provider.id for provider in all_providers())


def get_provider(provider_id: str | None) -> Provider:
    """Look up a provider; an unknown id falls back to the default.

    Falling back (instead of raising) keeps an old settings row or a
    hand-edited file from making the app unusable — the API page then shows the
    default provider and the URL it is actually using.
    """
    key = (provider_id or "").strip().lower()
    if key in _CUSTOM:
        return _CUSTOM[key]
    return _BY_ID.get(key, _BY_ID[DEFAULT_PROVIDER])


def current_provider(settings) -> Provider:  # noqa: ANN001 - avoid an import cycle
    return get_provider(str(settings.get("ai.provider", DEFAULT_PROVIDER) or DEFAULT_PROVIDER))


def is_loopback(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def normalize_base_url(value: str | None, *, provider: Provider | None = None) -> str:
    """Clean and validate a provider base URL.

    Plain ``https`` everywhere, except loopback addresses: a local server speaks
    ``http`` and there is nothing to encrypt on the same machine. ``http`` to a
    remote host is rejected instead of being silently upgraded, because forcing
    https on a server that does not offer it produces a confusing TLS error.
    """
    raw = (value or "").strip()
    if not raw:
        if provider is not None and (provider.id == "custom" or provider.custom):
            raise ValidationError(
                "A custom provider needs a base URL",
                message_key="api.base_url_required",
            )
        raw = provider.base_url if provider is not None else ""
    raw = raw.rstrip("/")
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise ValidationError("Malformed URL", message_key="error.settings") from exc
    scheme = (parts.scheme or "").lower()
    if not parts.netloc:
        raise ValidationError("Provider base URL has no host", message_key="error.settings")
    if scheme == "http" and not is_loopback(raw):
        raise ValidationError(
            "A remote provider must use https",
            message_key="api.base_url_https",
        )
    if scheme not in {"http", "https"}:
        raise ValidationError("Provider base URL must be http(s)", message_key="error.settings")
    return raw


def base_url_for(provider: Provider, settings) -> str:  # noqa: ANN001
    """Saved URL for this provider, else its documented default."""
    stored: dict[str, Any] = {}
    raw = settings.get("ai.base_urls", {}) or {}
    if isinstance(raw, dict):
        stored = {str(key): str(value) for key, value in raw.items() if value}
    if provider.id in stored:
        return stored[provider.id]
    if provider.id == DEFAULT_PROVIDER:
        # An install from before multi-provider kept a single ai.base_url.
        legacy = str(settings.get("ai.base_url", "") or "")
        if legacy:
            return legacy
    return provider.base_url


def save_base_url(settings, provider: Provider, url: str) -> str:  # noqa: ANN001
    clean = normalize_base_url(url, provider=provider)
    stored = settings.get("ai.base_urls", {}) or {}
    stored = dict(stored) if isinstance(stored, dict) else {}
    stored[provider.id] = clean
    updates: dict[str, Any] = {"ai.base_urls": stored, "ai.provider": provider.id}
    if provider.id == DEFAULT_PROVIDER:
        updates["ai.base_url"] = clean
    settings.update(updates)
    return clean


def key_problem(provider: Provider, value: str | None) -> str | None:
    """What can be known offline about this key, or ``None``.

    Never the server's verdict: a key that passes here may still be revoked.
    """
    key = (value or "").strip()
    if not key:
        return None if not provider.key_required else "error.api_key_missing"
    if len(key) > KEY_MAX:
        return "api.key_too_long"
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in key):
        return "api.key_invalid_chars"
    if provider.key_prefix and not key.startswith(provider.key_prefix):
        return "api.key_format"
    return None


def validate_key(provider: Provider, value: str | None) -> str:
    problem = key_problem(provider, value)
    if problem is not None:
        raise ConfigurationError(
            "The stored API key is not usable for this provider",
            message_key=problem,
            hint_key="settings.ai_key_hint",
        )
    return (value or "").strip()


def has_key(provider: Provider, secrets) -> bool:  # noqa: ANN001
    """Whether this provider can be used right now.

    A provider whose key is optional (a local server, or a custom gateway behind
    another authentication layer) counts as ready even with an empty vault:
    blocking the chat would be a guess, and the endpoint's own 401 is the
    truthful answer. ``has_stored_key`` is what the UI uses to avoid claiming a
    key is configured when none is.
    """
    # Local servers and "no key" endpoints need no vault entry to be usable.
    if not provider.key_required:
        return True
    try:
        return bool(secrets.has_key(provider.id))
    except Exception:  # noqa: BLE001 - a broken vault must not crash a page
        return False


def has_stored_key(provider: Provider, secrets) -> bool:  # noqa: ANN001
    try:
        return bool(secrets.has_key(provider.id))
    except Exception:  # noqa: BLE001
        return False


#: A model id is what the provider calls the model: ``vendor/name``,
#: ``claude-sonnet-4``, ``gemini-2.5-pro``. Typed by hand for endpoints that
#: publish no catalogue, so it is validated before it reaches a request body.
MODEL_ID_MAX = 200


def model_id_problem(value: str | None) -> str | None:
    """Offline check for a hand-typed model id (never the provider's verdict)."""
    model = (value or "").strip()
    if not model:
        return "api.model_id_empty"
    if len(model) > MODEL_ID_MAX:
        return "api.model_id_too_long"
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in model):
        return "api.model_id_invalid_chars"
    return None


def models_cache(settings) -> dict[str, list[dict]]:  # noqa: ANN001
    """Per-provider catalogue cache, with the pre-0.9 single list migrated."""
    raw = settings.get("ai.model_cache", {}) or {}
    cache = {str(k): list(v) for k, v in raw.items() if isinstance(v, list)} if isinstance(raw, dict) else {}
    if "openrouter" not in cache:
        legacy = settings.get("ai.openrouter_cache", []) or []
        if isinstance(legacy, list) and legacy:
            cache["openrouter"] = list(legacy)
    return cache


def cached_models(settings, provider_id: str) -> list[dict]:  # noqa: ANN001
    return list(models_cache(settings).get(provider_id, []))


def build_client(settings, secrets, *, transport=None, provider_id: str | None = None) -> "ProviderClient":  # noqa: ANN001
    """The one place that turns settings + the vault into a ready client."""
    spec = get_provider(provider_id) if provider_id else current_provider(settings)
    return ProviderClient(
        lambda: secrets.get_key(spec.id),
        provider=spec.id,
        base_url=base_url_for(spec, settings),
        transport=transport,
        network=network_for(spec, settings),
    )


def network_for(provider: Provider, settings):  # noqa: ANN001
    """A local provider must never be sent through the machine's proxy."""
    from .net import options_from_settings

    options = options_from_settings(settings)
    if provider.local:
        return replace(options, mode="off")
    return options


class ProviderClient(OpenRouterClient):
    """Streaming client for three wire protocols.

    Inherits the transport plumbing (staged errors, proxy selection, retry) from
    :class:`OpenRouterClient` and overrides only what differs per vendor:
    headers, how the catalogue is read, and how a stream is shaped.
    """

    #: Tool calling is implemented for the OpenAI-compatible protocol only; the
    #: agent honestly refuses to promise it elsewhere.
    supports_tools = True

    def __init__(
        self,
        api_key_provider,  # noqa: ANN001
        *,
        provider: str = DEFAULT_PROVIDER,
        base_url: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        network: NetworkOptions | None = None,
    ) -> None:
        self.spec = get_provider(provider)
        self.supports_tools = self.spec.protocol == PROTOCOL_OPENAI
        super().__init__(
            api_key_provider,
            base_url=base_url or self.spec.base_url,
            timeout=timeout,
            transport=transport,
            network=network,
        )

    # ------------------------------------------------------------- plumbing
    def _headers(self) -> dict[str, str]:
        key = (self._api_key_provider() or "").strip()
        problem = key_problem(self.spec, key)
        if problem is not None:
            raise ConfigurationError(
                "The stored API key is not usable for this provider",
                message_key=problem,
                hint_key="settings.ai_key_hint",
            )
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.spec.protocol == PROTOCOL_ANTHROPIC:
            if key:
                headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
        elif self.spec.protocol == PROTOCOL_GEMINI:
            if key:
                headers["x-goog-api-key"] = key
        elif key:
            headers["Authorization"] = f"Bearer {key}"
        if self.spec.id == DEFAULT_PROVIDER:
            headers["HTTP-Referer"] = APP_REFERER
            headers["X-Title"] = APP_TITLE
        return headers

    def label(self) -> str:
        return self.spec.name

    # --------------------------------------------------------------- models
    def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        if not refresh and self._models_cache is not None and (time.time() - self._models_at) < 600:
            return list(self._models_cache)
        models = self._fetch_catalogue()
        if not models and self.spec.fallback_models:
            models = [
                ModelInfo(id=name, name=name, price_known=False)
                for name in self.spec.fallback_models
            ]
        self._models_cache = models
        self._models_at = time.time()
        logger.info("provider_models_loaded provider=%s count=%s", self.spec.id, len(models))
        return list(models)

    def _fetch_catalogue(self) -> list[ModelInfo]:
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                if self.spec.protocol == PROTOCOL_ANTHROPIC:
                    return self._anthropic_models()
                if self.spec.protocol == PROTOCOL_GEMINI:
                    return self._gemini_models()
                return self._openai_models()
            except Exception as exc:  # noqa: BLE001 - normalised below
                transient = isinstance(
                    exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
                )
                if attempt < attempts and transient:
                    logger.info(
                        "provider_models_retry provider=%s reason=%s",
                        self.spec.id,
                        type(exc).__name__,
                    )
                    time.sleep(0.6)
                    continue
                if self._is_missing_catalogue(exc):
                    # A custom endpoint often has no /models route. That is not
                    # a broken connection, so it must not be reported as one.
                    logger.info("provider_catalogue_absent provider=%s", self.spec.id)
                    return []
                raise self._wrap_transport_error(exc) from exc
        return []

    @staticmethod
    def _is_missing_catalogue(exc: Exception) -> bool:
        return isinstance(exc, ProviderError) and "HTTP 404" in (getattr(exc, "details", "") or "")

    def _openai_models(self) -> list[ModelInfo]:
        with self._client() as client:
            response = client.get("/models")
            self._raise_for_status(response)
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Malformed model catalogue", message_key="error.api_generic")
        models = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            model = self._parse_catalogue_row(row)
            if model is not None:
                models.append(model)
        models.sort(key=lambda item: (not item.is_free(), item.id))
        return models

    def _parse_catalogue_row(self, row: dict[str, Any]) -> ModelInfo | None:
        from .openrouter import parse_model

        model = parse_model(row)
        if not model.id:
            return None
        # Trust a price the row really carries; otherwise only a provider that
        # documents per-token pricing may claim the price is known.
        return replace(model, price_known=model.price_known or self.spec.publishes_prices)

    def _anthropic_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        after = ""
        for _page in range(4):
            params = {"limit": 1000}
            if after:
                params["after_id"] = after
            with self._client() as client:
                response = client.get("/models", params=params)
                self._raise_for_status(response)
                payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ProviderError("Malformed model catalogue", message_key="error.api_generic")
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                models.append(
                    ModelInfo(
                        id=str(row["id"]),
                        name=str(row.get("display_name") or row["id"]),
                        price_known=False,
                        supports_streaming=True,
                    )
                )
            if not payload.get("has_more") or not payload.get("last_id"):
                break
            after = str(payload.get("last_id"))
        models.sort(key=lambda item: item.id)
        return models

    def _gemini_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        token = ""
        for _page in range(6):
            params: dict[str, Any] = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            with self._client() as client:
                response = client.get("/models", params=params)
                self._raise_for_status(response)
                payload = response.json()
            rows = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise ProviderError("Malformed model catalogue", message_key="error.api_generic")
            for row in rows:
                if not isinstance(row, dict) or not row.get("name"):
                    continue
                methods = row.get("supportedGenerationMethods") or []
                if methods and "generateContent" not in methods:
                    continue  # embedding models cannot chat
                identifier = str(row["name"]).split("/")[-1]
                models.append(
                    ModelInfo(
                        id=identifier,
                        name=str(row.get("displayName") or identifier),
                        context_length=int(row.get("inputTokenLimit") or 0),
                        price_known=False,
                        supports_streaming=True,
                    )
                )
            token = str(payload.get("nextPageToken") or "")
            if not token:
                break
        models.sort(key=lambda item: item.id)
        return models

    # ------------------------------------------------------------- streaming
    def stream_chat(self, **kwargs: Any) -> ChatResult:
        if self.spec.protocol == PROTOCOL_ANTHROPIC:
            return self._stream_anthropic(**kwargs)
        if self.spec.protocol == PROTOCOL_GEMINI:
            return self._stream_gemini(**kwargs)
        return super().stream_chat(**kwargs)

    def _chat_guard(self, model: str) -> None:
        if not model or not str(model).strip():
            raise ValidationError("No model selected", message_key="error.no_model")

    def _stream_anthropic(
        self,
        *,
        model: str,
        messages,  # noqa: ANN001
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float | None = None,
        cancel: threading.Event | None = None,
        on_delta=None,  # noqa: ANN001
        on_reasoning=None,  # noqa: ANN001
        extra: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ChatResult:
        """Anthropic Messages API over SSE.

        The system prompt is a top-level field there, not a message, and
        ``temperature`` is bounded to 0–1. Tool calls are not sent: this build
        implements tool calling for the OpenAI-compatible protocol only, so the
        agent never claims a capability this path does not have.
        """
        self._chat_guard(model)
        rows = list(messages)
        system = "\n\n".join(
            str(row.get("content") or "") for row in rows if row.get("role") == "system"
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": row["role"], "content": row.get("content") or ""}
                for row in rows
                if row.get("role") in {"user", "assistant"}
            ],
            "max_tokens": int(max_tokens),
            "temperature": max(0.0, min(1.0, float(temperature))),
            "stream": True,
        }
        if system:
            payload["system"] = system
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if extra:
            payload.update(extra)

        stats = StreamStats(model_id=model)
        text_parts: list[str] = []
        cancel = cancel or threading.Event()
        started = time.perf_counter()
        first_at: float | None = None
        try:
            with self._client(stream=True) as client:
                with client.stream("POST", "/messages", json=payload) as response:
                    if not response.is_success:
                        response.read()
                        self._raise_for_status(response)
                    for line in response.iter_lines():
                        if cancel.is_set():
                            raise _cancelled()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        kind = str(event.get("type") or "")
                        if kind == "error":
                            message = str(
                                (event.get("error") or {}).get("message", "Provider error")
                            )
                            raise ProviderError(message, message_key="error.api_generic")
                        if kind == "message_start":
                            usage = (event.get("message") or {}).get("usage") or {}
                            stats.prompt_tokens = int(usage.get("input_tokens") or 0)
                            continue
                        if kind == "content_block_delta":
                            delta = event.get("delta") or {}
                            text = delta.get("text")
                            if text:
                                if first_at is None:
                                    first_at = time.perf_counter()
                                    stats.first_token_ms = int((first_at - started) * 1000)
                                text_parts.append(str(text))
                                stats.chunk_count += 1
                                if on_delta is not None:
                                    on_delta(str(text))
                            elif delta.get("thinking") and on_reasoning is not None:
                                on_reasoning(str(delta["thinking"]))
                            continue
                        if kind == "message_delta":
                            delta = event.get("delta") or {}
                            if delta.get("stop_reason"):
                                stats.finish_reason = str(delta["stop_reason"])
                            usage = event.get("usage") or {}
                            if usage.get("output_tokens"):
                                stats.completion_tokens = int(usage["output_tokens"])
                            continue
                        if kind == "message_stop":
                            break
        except _CancelledError:
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            return ChatResult(
                text="".join(text_parts), stats=stats, cancelled=True, model_id=model
            )
        except Exception as exc:  # noqa: BLE001 - normalised below
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            raise self._wrap_transport_error(exc) from exc

        stats.total_ms = int((time.perf_counter() - started) * 1000)
        stats.total_tokens = stats.prompt_tokens + stats.completion_tokens
        logger.info(
            "anthropic_stream_done model=%s total_ms=%s chunks=%s",
            model,
            stats.total_ms,
            stats.chunk_count,
        )
        return ChatResult(text="".join(text_parts), stats=stats, model_id=model)

    def _stream_gemini(
        self,
        *,
        model: str,
        messages,  # noqa: ANN001
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float | None = None,
        cancel: threading.Event | None = None,
        on_delta=None,  # noqa: ANN001
        on_reasoning=None,  # noqa: ANN001
        extra: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ChatResult:
        """Gemini ``streamGenerateContent`` (``alt=sse``)."""
        self._chat_guard(model)
        rows = list(messages)
        system = "\n\n".join(
            str(row.get("content") or "") for row in rows if row.get("role") == "system"
        )
        contents = [
            {
                "role": "model" if row.get("role") == "assistant" else "user",
                "parts": [{"text": str(row.get("content") or "")}],
            }
            for row in rows
            if row.get("role") in {"user", "assistant"}
        ]
        generation: dict[str, Any] = {
            "temperature": max(0.0, min(2.0, float(temperature))),
            "maxOutputTokens": int(max_tokens),
        }
        if top_p is not None:
            generation["topP"] = float(top_p)
        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if extra:
            payload.update(extra)

        identifier = model.split("/")[-1]
        stats = StreamStats(model_id=model)
        text_parts: list[str] = []
        cancel = cancel or threading.Event()
        started = time.perf_counter()
        first_at: float | None = None
        try:
            with self._client(stream=True) as client:
                with client.stream(
                    "POST",
                    f"/models/{identifier}:streamGenerateContent",
                    params={"alt": "sse"},
                    json=payload,
                ) as response:
                    if not response.is_success:
                        response.read()
                        self._raise_for_status(response)
                    for line in response.iter_lines():
                        if cancel.is_set():
                            raise _cancelled()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        events = parsed if isinstance(parsed, list) else [parsed]
                        for item in events:
                            if not isinstance(item, dict):
                                continue
                            feedback = item.get("promptFeedback") or {}
                            if feedback.get("blockReason"):
                                raise ProviderError(
                                    f"Gemini blocked the prompt: {feedback['blockReason']}",
                                    message_key="error.api_generic",
                                )
                            usage = item.get("usageMetadata") or {}
                            if usage.get("promptTokenCount"):
                                stats.prompt_tokens = int(usage["promptTokenCount"])
                            if usage.get("candidatesTokenCount"):
                                stats.completion_tokens = int(usage["candidatesTokenCount"])
                            for candidate in item.get("candidates") or []:
                                for part in (candidate.get("content") or {}).get("parts") or []:
                                    text = part.get("text")
                                    if not text:
                                        continue
                                    if first_at is None:
                                        first_at = time.perf_counter()
                                        stats.first_token_ms = int((first_at - started) * 1000)
                                    text_parts.append(str(text))
                                    stats.chunk_count += 1
                                    if on_delta is not None:
                                        on_delta(str(text))
                                if candidate.get("finishReason"):
                                    stats.finish_reason = str(candidate["finishReason"])
        except _CancelledError:
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            return ChatResult(
                text="".join(text_parts), stats=stats, cancelled=True, model_id=model
            )
        except Exception as exc:  # noqa: BLE001 - normalised below
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            raise self._wrap_transport_error(exc) from exc

        stats.total_ms = int((time.perf_counter() - started) * 1000)
        stats.total_tokens = stats.prompt_tokens + stats.completion_tokens
        logger.info(
            "gemini_stream_done model=%s total_ms=%s chunks=%s",
            model,
            stats.total_ms,
            stats.chunk_count,
        )
        return ChatResult(text="".join(text_parts), stats=stats, model_id=model)

    def describe(self) -> dict[str, Any]:
        info = self.spec.to_dict()
        info["base_url"] = self.base_url
        info["proxy"] = self.proxy_label()
        info["tools"] = self.supports_tools
        return info


class _CancelledError(CancelledProviderError):
    """Internal: cancellation raised inside a stream and returned as a result."""


def _cancelled() -> AppError:
    return _CancelledError("Cancelled", message_key="chat.cancelled")
