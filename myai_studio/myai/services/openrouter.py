"""OpenRouter client.

Design rules:

* The client owns **no** Qt code and no UI state: it can be unit-tested with a
  fake transport and reused from a worker thread.
* Every provider failure is mapped onto one of the typed errors in
  :mod:`myai.core.errors` so the UI can show a translated, actionable message
  instead of a stack trace.
* Streaming is line-based SSE parsing over ``httpx``; cancellation is a
  ``threading.Event`` that is checked between chunks and closes the response.

The sandbox used to develop this cannot reach ``openrouter.ai``; the transport
is therefore injectable and the test-suite drives the real code paths with
``httpx.MockTransport``.  Live-network behaviour is reported separately and is
never claimed as tested.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..core.errors import (
    AppError,
    AuthenticationError,
    ConfigurationError,
    InsufficientCreditError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ValidationError,
)
from .net import NetworkOptions, client_kwargs, mask_proxy, options_timeout, probe

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
APP_REFERER = "https://github.com/mohammadmirzazadeh335-wq/AISystemOptimizer"
APP_TITLE = "MyAI Studio Ultimate"


class TimeoutProviderError(ProviderError):
    code = "provider.timeout"


class CancelledProviderError(AppError):
    code = "provider.cancelled"


# --------------------------------------------------------------------- models
@dataclass(frozen=True)
class ModelInfo:
    """A single entry of the OpenRouter catalogue, normalised."""

    id: str
    name: str
    context_length: int = 0
    prompt_price: float = 0.0          # USD per 1M prompt tokens
    completion_price: float = 0.0      # USD per 1M completion tokens
    supports_tools: bool = False
    supports_vision: bool = False
    supports_streaming: bool = True
    modality: str = "text"
    #: False when the catalogue carries no prices at all (Anthropic, Gemini and
    #: plain OpenAI-compatible endpoints do not publish them). Without this the
    #: UI would read "no price" as "free" and show a green Free badge on a
    #: paid model.
    price_known: bool = True

    @property
    def label(self) -> str:
        return self.name or self.id

    @property
    def vendor(self) -> str:
        return self.id.split("/")[0] if "/" in self.id else ""

    def context_label(self) -> str:
        if not self.context_length:
            return ""
        if self.context_length >= 1000:
            return f"{self.context_length // 1000}k"
        return str(self.context_length)

    def is_free(self) -> bool:
        return (
            self.price_known
            and self.prompt_price == 0
            and self.completion_price == 0
        )


def parse_model(payload: dict[str, Any]) -> ModelInfo:
    """Normalise one catalogue entry.

    Only fields present in the payload are trusted; capability flags are read
    from ``supported_parameters`` / ``architecture`` and never guessed, except
    that streaming defaults to True because every OpenRouter chat model streams.
    """
    architecture = payload.get("architecture") or {}
    pricing = payload.get("pricing") or {}
    params = payload.get("supported_parameters") or []

    def price(key: str) -> float:
        try:
            return float(pricing.get(key, 0) or 0) * 1_000_000
        except (TypeError, ValueError):
            return 0.0

    modality = str(architecture.get("modality") or "text")
    inputs = architecture.get("input_modalities") or []
    return ModelInfo(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        context_length=int(payload.get("context_length") or 0),
        prompt_price=price("prompt"),
        completion_price=price("completion"),
        supports_tools="tools" in params or "tool_choice" in params,
        supports_vision="image" in inputs or modality in {"multimodal", "image->text"},
        supports_streaming=True,
        modality=modality,
    )


# -------------------------------------------------------------------- results
@dataclass
class StreamStats:
    """Measured timings and token usage for one completion."""

    first_token_ms: int = 0
    total_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    chunk_count: int = 0
    model_id: str = ""

    @property
    def tokens_per_second(self) -> float:
        if not self.total_ms or not self.completion_tokens:
            return 0.0
        return self.completion_tokens / (self.total_ms / 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_token_ms": self.first_token_ms,
            "total_ms": self.total_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "chunk_count": self.chunk_count,
            "tokens_per_second": round(self.tokens_per_second, 2),
            "model_id": self.model_id,
        }


@dataclass
class ToolCall:
    """One function call requested by the model."""

    id: str
    name: str
    arguments: str = ""

    def parsed(self) -> dict[str, Any]:
        """Arguments as a dict; malformed JSON is surfaced, never guessed."""
        try:
            data = json.loads(self.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"Tool arguments are not valid JSON: {exc.msg}",
                message_key="agent.bad_arguments",
            ) from exc
        if not isinstance(data, dict):
            raise ValidationError(
                "Tool arguments must be a JSON object",
                message_key="agent.bad_arguments",
            )
        return data

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class ChatResult:
    text: str = ""
    stats: StreamStats = field(default_factory=StreamStats)
    cancelled: bool = False
    model_id: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "stats": self.stats.to_dict(), "cancelled": self.cancelled,
                "model_id": self.model_id,
                "tool_calls": [call.to_dict() for call in self.tool_calls]}


@dataclass
class ConnectionTest:
    ok: bool
    latency_ms: int
    model_count: int = 0
    message: str = ""
    error_code: str = ""
    proxy: str = ""
    stage: str = ""


def model_to_dict(model: ModelInfo) -> dict:
    """Serialise a catalogue entry for the on-disk cache."""
    return {
        "id": model.id,
        "name": model.name,
        "context_length": model.context_length,
        "prompt_price": model.prompt_price,
        "completion_price": model.completion_price,
        "supports_tools": model.supports_tools,
        "supports_vision": model.supports_vision,
        "supports_streaming": model.supports_streaming,
        "modality": model.modality,
        "price_known": model.price_known,
    }


def model_from_dict(data: dict) -> ModelInfo | None:
    """Rebuild a cached entry, ignoring anything malformed."""
    if not isinstance(data, dict) or not data.get("id"):
        return None
    try:
        return ModelInfo(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            context_length=int(data.get("context_length") or 0),
            prompt_price=float(data.get("prompt_price") or 0.0),
            completion_price=float(data.get("completion_price") or 0.0),
            supports_tools=bool(data.get("supports_tools")),
            supports_vision=bool(data.get("supports_vision")),
            supports_streaming=bool(data.get("supports_streaming", True)),
            modality=str(data.get("modality") or "text"),
            # Older caches predate the flag and came from OpenRouter, which does
            # publish prices, so the default is honest for them.
            price_known=bool(data.get("price_known", True)),
        )
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------- client
#: OpenRouter keys look like ``sk-or-v1-<64 hex>``. The app checks only what it
#: can know offline: the prefix, printable characters and no embedded newline.
#: Anything else is the server's verdict, and pretending otherwise would block a
#: valid key or accept a header-injection attempt.
API_KEY_PREFIX = "sk-or-"
API_KEY_MAX = 200


def api_key_problem(value: str | None) -> str | None:
    """Return a translation key describing a malformed key, or ``None``.

    This runs before any request is built, so a key with ``\r\n`` can never be
    spliced into the ``Authorization`` header.
    """
    key = (value or "").strip()
    if not key:
        return "error.api_key_missing"
    if not key.startswith(API_KEY_PREFIX):
        return "api.key_format"
    if len(key) > API_KEY_MAX:
        return "api.key_too_long"
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in key):
        return "api.key_invalid_chars"
    return None


def validate_api_key(value: str | None) -> str:
    """Return the cleaned key or raise :class:`ConfigurationError`."""
    problem = api_key_problem(value)
    if problem is not None:
        raise ConfigurationError(
            "The stored OpenRouter API key is not usable",
            message_key=problem,
            hint_key="settings.ai_key_hint",
        )
    return (value or "").strip()


class OpenRouterClient:
    """Thin, synchronous OpenRouter client with streaming support."""

    def __init__(
        self,
        api_key_provider: Callable[[], str | None],
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        network: NetworkOptions | None = None,
    ) -> None:
        self._api_key_provider = api_key_provider
        self.network = network or NetworkOptions()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._transport = transport
        self._models_cache: list[ModelInfo] | None = None
        self._models_at: float = 0.0

    # ------------------------------------------------------------- plumbing
    def _headers(self) -> dict[str, str]:
        key = validate_api_key(self._api_key_provider())
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": APP_REFERER,
            "X-Title": APP_TITLE,
            "Accept": "application/json",
        }

    def _client(self, *, stream: bool = False) -> httpx.Client:
        """Build a client that reaches the network the way this machine does.

        ``trust_env`` is handled by :mod:`myai.services.net` rather than httpx:
        the resolver reads environment variables **and** the Windows/macOS
        system settings in a defined order, then passes one explicit proxy.
        """
        try:
            network_kwargs = client_kwargs(self.network)
        except (ValueError, RuntimeError) as exc:
            raise ConfigurationError(
                str(exc), message_key="error.proxy_invalid", hint_key="api.proxy_hint"
            ) from exc
        options = dict(network_kwargs)
        if self._transport is not None:
            options["transport"] = self._transport
        if not options.get("proxy"):
            options["timeout"] = options_timeout(self.network)
        return httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            headers=self._headers(),
            **options,
        )

    def proxy_label(self) -> str:
        """Masked proxy for display; never includes credentials."""
        try:
            return mask_proxy(str(client_kwargs(self.network).get("proxy") or ""))
        except (ValueError, RuntimeError):
            return ""

    def diagnose(self) -> object:
        """Staged DNS/TCP/TLS/HTTP probe used by the API page."""
        return probe(self.base_url, self.network)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        status = response.status_code
        detail = ""
        try:
            payload = response.json()
            detail = (
                (payload.get("error") or {}).get("message")
                if isinstance(payload, dict)
                else ""
            ) or ""
        except Exception:
            detail = response.text[:300]
        detail = detail.strip()
        logger.warning("openrouter_http_error status=%s detail=%s", status, detail[:200])
        if status in (401, 403):
            raise AuthenticationError(
                detail or "Invalid API key",
                message_key="error.api_auth",
                hint_key="settings.ai_key_hint",
                details=f"HTTP {status}",
            )
        if status == 402:
            raise InsufficientCreditError(
                detail or "Insufficient credits",
                message_key="error.api_credit",
                details="HTTP 402",
            )
        if status == 429:
            raise RateLimitError(
                detail or "Rate limited",
                message_key="error.api_rate",
                details="HTTP 429",
            )
        if status == 404:
            raise ProviderError(
                detail or "Model or endpoint not found",
                message_key="error.api_model",
                details="HTTP 404",
            )
        if status >= 500:
            raise ProviderError(
                detail or "Provider unavailable",
                message_key="error.api_server",
                details=f"HTTP {status}",
            )
        raise ProviderError(
            detail or "Request rejected",
            message_key="error.api_generic",
            details=f"HTTP {status}",
        )

    def _wrap_transport_error(self, exc: Exception) -> AppError:
        """Map a transport failure onto an error the UI can explain.

        ``ConnectTimeout`` and ``ConnectError`` are separated from a read
        timeout on purpose: the first two are almost always the local network
        (a missing proxy on a filtered connection), while the third means the
        request was already on its way.
        """
        if isinstance(exc, AppError):
            return exc
        proxy = self.proxy_label()
        # httpx folds a TLS failure into ConnectError; the text is the only
        # place the real stage survives, so classify from it.
        text = str(exc)
        lowered = text.lower()
        if isinstance(exc, httpx.ConnectError) and ("tls" in lowered or "ssl" in lowered):
            stage = "tls"
        elif isinstance(exc, httpx.ConnectError):
            stage = "tcp"
        else:
            stage = type(exc).__name__
        detail = f"{type(exc).__name__}: {text[:160]}" if text else type(exc).__name__
        context = {"proxy": proxy or "direct", "stage": stage}
        if isinstance(exc, httpx.ConnectTimeout):
            return TimeoutProviderError(
                "Could not open a connection to the provider in time",
                message_key="error.api_connect_timeout",
                hint_key="api.proxy_hint",
                details=f"{detail} · proxy={proxy or 'direct'}",
                context=context,
                cause=exc,
            )
        if isinstance(exc, httpx.TimeoutException):
            return TimeoutProviderError(
                "The provider did not answer in time",
                message_key="error.api_timeout",
                details=f"{detail} · proxy={proxy or 'direct'}",
                context=context,
                cause=exc,
            )
        return NetworkError(
            f"Could not reach the provider ({type(exc).__name__})",
            message_key="error.api_network",
            hint_key="api.proxy_hint",
            details=f"{detail} · proxy={proxy or 'direct'}",
            context=context,
            cause=exc,
        )

    # ---------------------------------------------------------------- models
    def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        """Return the catalogue, cached for 10 minutes."""
        if not refresh and self._models_cache is not None and (time.time() - self._models_at) < 600:
            return list(self._models_cache)
        # One retry: a proxy that just came up (or a flaky Wi-Fi hop) makes the
        # first attempt fail while the second succeeds, and GET /models is
        # idempotent, so retrying cannot double-charge anything.
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                with self._client() as client:
                    response = client.get("/models")
                    self._raise_for_status(response)
                    payload = response.json()
                break
            except Exception as exc:  # noqa: BLE001 - normalised below
                transient = isinstance(
                    exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
                )
                if attempt < attempts and transient:
                    logger.info("openrouter_models_retry attempt=%s reason=%s", attempt, type(exc).__name__)
                    time.sleep(0.6)
                    continue
                raise self._wrap_transport_error(exc) from exc
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Malformed model catalogue", message_key="error.api_generic")
        models = [parse_model(row) for row in rows if isinstance(row, dict) and row.get("id")]
        models.sort(key=lambda m: (not m.id.endswith(":free"), m.id))
        self._models_cache = models
        self._models_at = time.time()
        logger.info("openrouter_models_loaded count=%s", len(models))
        return list(models)

    def cached_models(self) -> list[ModelInfo]:
        return list(self._models_cache or [])

    def test_connection(self) -> ConnectionTest:
        """Cheap, explicit connectivity + auth check used by the settings page."""
        started = time.perf_counter()
        proxy = self.proxy_label()
        stage = ""
        try:
            models = self.list_models(refresh=True)
        except AppError as exc:
            stage = str(exc.context.get("stage", "") or "")
            return ConnectionTest(
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                message=exc.message,
                error_code=exc.code,
                proxy=proxy,
                stage=stage,
            )
        return ConnectionTest(
            ok=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model_count=len(models),
            message=f"{len(models)} models available",
            proxy=proxy,
        )

    # ---------------------------------------------------------------- streaming
    def stream_chat(
        self,
        *,
        model: str,
        messages: Iterable[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float | None = None,
        cancel: threading.Event | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        extra: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ChatResult:
        """Stream a chat completion.

        ``on_delta`` is called for every content fragment from the worker thread;
        the caller is responsible for marshalling to the UI thread.
        """
        if not model or not str(model).strip():
            raise ValidationError("No model selected", message_key="error.no_model")
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if tools:
            payload["tools"] = list(tools)
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if extra:
            payload.update(extra)

        stats = StreamStats(model_id=model)
        text_parts: list[str] = []
        calls: dict[int, ToolCall] = {}
        cancel = cancel or threading.Event()
        started = time.perf_counter()
        first_at: float | None = None

        try:
            with self._client(stream=True) as client:
                with client.stream("POST", "/chat/completions", json=payload) as response:
                    if not response.is_success:
                        response.read()
                        self._raise_for_status(response)
                    for line in response.iter_lines():
                        if cancel.is_set():
                            raise CancelledProviderError("Cancelled", message_key="chat.cancelled")
                        if not line:
                            continue
                        if line.startswith(":"):
                            continue  # comment / keep-alive
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if "error" in event and event["error"]:
                            message = str((event.get("error") or {}).get("message", "Provider error"))
                            raise ProviderError(message, message_key="error.api_generic")
                        choice = (event.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            if first_at is None:
                                first_at = time.perf_counter()
                                stats.first_token_ms = int((first_at - started) * 1000)
                            text_parts.append(content)
                            stats.chunk_count += 1
                            if on_delta is not None:
                                on_delta(content)
                        for raw in delta.get("tool_calls") or []:
                            if not isinstance(raw, dict):
                                continue
                            index = int(raw.get("index") or 0)
                            call = calls.setdefault(index, ToolCall(id="", name=""))
                            if raw.get("id"):
                                call.id = str(raw["id"])
                            function = raw.get("function") or {}
                            if function.get("name"):
                                call.name = str(function["name"])
                            if function.get("arguments"):
                                call.arguments += str(function["arguments"])
                        reasoning = delta.get("reasoning")
                        if reasoning and on_reasoning is not None:
                            on_reasoning(reasoning)
                        finish = choice.get("finish_reason")
                        if finish:
                            stats.finish_reason = str(finish)
                        usage = event.get("usage")
                        if isinstance(usage, dict):
                            stats.prompt_tokens = int(usage.get("prompt_tokens") or stats.prompt_tokens)
                            stats.completion_tokens = int(
                                usage.get("completion_tokens") or stats.completion_tokens
                            )
                            stats.total_tokens = int(usage.get("total_tokens") or stats.total_tokens)
        except CancelledProviderError:
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            logger.info("openrouter_cancelled model=%s chunks=%s", model, stats.chunk_count)
            return ChatResult(
                text="".join(text_parts),
                stats=stats,
                cancelled=True,
                model_id=model,
                tool_calls=[calls[index] for index in sorted(calls)],
            )
        except Exception as exc:  # noqa: BLE001
            stats.total_ms = int((time.perf_counter() - started) * 1000)
            raise self._wrap_transport_error(exc) from exc

        stats.total_ms = int((time.perf_counter() - started) * 1000)
        if not stats.total_tokens:
            # Some providers only report usage for non-streaming calls; keep the
            # fact that this is an estimate rather than inventing precision.
            stats.total_tokens = stats.prompt_tokens + stats.completion_tokens
        logger.info(
            "openrouter_stream_done model=%s first_ms=%s total_ms=%s chunks=%s",
            model, stats.first_token_ms, stats.total_ms, stats.chunk_count,
        )
        return ChatResult(
            text="".join(text_parts),
            stats=stats,
            model_id=model,
            tool_calls=[calls[index] for index in sorted(calls)],
        )
