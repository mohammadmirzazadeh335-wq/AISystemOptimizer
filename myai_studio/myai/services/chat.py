"""Chat orchestration: prompt assembly, streaming, persistence, statistics.

The service is deliberately thread-agnostic. :meth:`ChatService.send` is called
from a worker thread; it publishes fine-grained events on the signal bus which
the Qt bridge converts into UI signals on the GUI thread. Nothing here touches
a widget.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.errors import AppError, ValidationError
from ..core.events import Events, SignalBus
from ..core.timeutil import utcnow
from ..data.db import Database
from ..data.models import Conversation, Message
from .conversations import ConversationService
from .memory import MemoryService, estimate_tokens
from .net import options_from_settings
from .openrouter import ChatResult, ModelInfo, OpenRouterClient
from .persona import PersonaService
from .settings import SettingsService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .attachments import AttachmentRecord, AttachmentService

logger = logging.getLogger(__name__)

#: Fallback window when a model's context length is unknown. Used only for the
#: usage estimate and clearly labelled as an estimate in the UI.
DEFAULT_CONTEXT_WINDOW = 128_000
#: How many previous messages are sent verbatim.
DEFAULT_HISTORY_LIMIT = 40


@dataclass
class PromptDiagnostics:
    system_tokens: int = 0
    memory_tokens: int = 0
    history_tokens: int = 0
    total_tokens: int = 0
    history_messages: int = 0
    memory_items: int = 0
    estimated: bool = True
    context_window: int = 0
    usage_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_tokens": self.system_tokens,
            "memory_tokens": self.memory_tokens,
            "history_tokens": self.history_tokens,
            "total_tokens": self.total_tokens,
            "history_messages": self.history_messages,
            "memory_items": self.memory_items,
            "estimated": self.estimated,
            "context_window": self.context_window,
            "usage_ratio": round(self.usage_ratio, 4),
        }


@dataclass(frozen=True)
class PromptSegment:
    """One measured piece of the next request.

    ``category`` is a stable id (``system``, ``persona``, ``memory``,
    ``history``, ``attachment``); the page translates it. ``preview`` is the
    first line of the real content, trimmed — enough to recognise the segment
    without dumping the conversation into a chart tooltip.
    """

    category: str
    label: str
    chars: int
    tokens: int
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "chars": self.chars,
            "tokens": self.tokens,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class ContextMap:
    """Measured composition of the prompt that would be sent right now."""

    segments: tuple[PromptSegment, ...] = ()
    total_tokens: int = 0
    window: int = 0
    ratio: float = 0.0
    model_id: str = ""
    history_messages: int = 0
    memory_items: int = 0

    def by_category(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for segment in self.segments:
            totals[segment.category] = totals.get(segment.category, 0) + segment.tokens
        return totals

    def largest(self) -> PromptSegment | None:
        return max(self.segments, key=lambda segment: segment.tokens, default=None)


@dataclass
class SendOutcome:
    user_message: Message | None = None
    assistant_message: Message | None = None
    result: ChatResult | None = None
    diagnostics: PromptDiagnostics = field(default_factory=PromptDiagnostics)
    error: AppError | None = None
    cancelled: bool = False


class ChatService:
    def __init__(
        self,
        *,
        db: Database,
        bus: SignalBus,
        conversations: ConversationService,
        settings: SettingsService,
        memory: MemoryService,
        persona: PersonaService,
        attachments: "AttachmentService | None" = None,
        client_factory: Callable[[], OpenRouterClient] | None = None,
    ) -> None:
        self._db = db
        self._bus = bus
        self._conversations = conversations
        self._settings = settings
        self._memory = memory
        self._persona = persona
        self._attachments = attachments
        self._client_factory = client_factory or (lambda: OpenRouterClient(self._api_key))
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._active = False
        self._models: list[ModelInfo] = []

    # ------------------------------------------------------------------ state
    def _api_key(self) -> str | None:
        return None  # replaced by the context with a secret-store reader

    def set_api_key_reader(self, reader: Callable[[], str | None]) -> None:
        self._api_key = reader  # type: ignore[assignment]
        # The chat path must honour the same proxy as the API page, otherwise a
        # machine that needs one can list models but never stream a reply.
        self._client_factory = lambda: OpenRouterClient(
            reader,
            base_url=str(self._settings.get("ai.base_url") or "https://openrouter.ai/api/v1"),
            network=options_from_settings(self._settings),
        )

    def set_client_factory(self, factory: Callable[[], OpenRouterClient]) -> None:
        """Install the provider-aware factory built by the composition root.

        The client is rebuilt on every call so switching provider (or editing
        its URL) takes effect for the very next message, without a restart.
        """
        self._client_factory = factory

    def client(self) -> OpenRouterClient:
        return self._client_factory()

    @property
    def is_streaming(self) -> bool:
        return self._active

    def models(self) -> list[ModelInfo]:
        return list(self._models)

    def set_models(self, models: list[ModelInfo]) -> None:
        self._models = list(models)
        self._bus.emit(Events.MODELS_LOADED, models=list(models))

    def model_info(self, model_id: str) -> ModelInfo | None:
        for model in self._models:
            if model.id == model_id:
                return model
        return None

    def context_window(self, model_id: str) -> int:
        info = self.model_info(model_id)
        return info.context_length if info and info.context_length else DEFAULT_CONTEXT_WINDOW

    def cancel(self) -> None:
        """Ask the active stream to stop; safe to call from the UI thread."""
        self._cancel.set()

    # ----------------------------------------------------------------- prompt
    def build_messages(
        self,
        conversation: Conversation,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        attachments: list["AttachmentRecord"] | None = None,
    ) -> tuple[list[dict[str, str]], PromptDiagnostics]:
        base_block, persona_block, memory_block = self._system_blocks(conversation)
        system_blocks = [base_block]
        if persona_block:
            system_blocks.append(persona_block)
        if memory_block:
            system_blocks.append(memory_block)

        history = self._conversations.messages(conversation.id)
        trimmed = history[-history_limit:] if history_limit else history
        messages: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_blocks)}]
        last_index = len(trimmed) - 1
        for index, message in enumerate(trimmed):
            if message.role not in {"user", "assistant"}:
                continue
            if message.status == "error" or not (message.content or "").strip():
                continue
            content = message.content
            names = [
                str(item.get("name"))
                for item in ((message.meta or {}).get("attachments") or [])
                if item.get("name")
            ]
            # The current turn gets the full extracted text below; older turns
            # only keep a reminder so the context is not re-sent every time.
            if names and not (attachments and index == last_index):
                content = f"{content}\n\n[Attached files: {', '.join(names)}]"
            messages.append({"role": message.role, "content": content})

        if attachments:
            block = self._attachments.context_block(attachments) if self._attachments else ""
            if block:
                last = messages[-1] if len(messages) > 1 else None
                if last is None or last["role"] != "user":
                    messages.append({"role": "user", "content": block})
                else:
                    last["content"] = f"{last['content']}\n\n{block}".strip()

        window = self.context_window(conversation.model_id or str(self._settings.get("ai.default_model", "")))
        system_tokens = estimate_tokens(messages[0]["content"])
        memory_tokens = estimate_tokens(memory_block) if bool(self._settings.get("memory.enabled", True)) else 0
        history_tokens = sum(estimate_tokens(m["content"]) for m in messages[1:])
        total = system_tokens + history_tokens
        diagnostics = PromptDiagnostics(
            system_tokens=system_tokens,
            memory_tokens=memory_tokens,
            history_tokens=history_tokens,
            total_tokens=total,
            history_messages=len(messages) - 1,
            memory_items=len(self._memory.all_for_conversation(conversation.id))
            if bool(self._settings.get("memory.enabled", True))
            else 0,
            context_window=window,
            usage_ratio=min(1.0, total / window) if window else 0.0,
        )
        return messages, diagnostics

    def _system_blocks(self, conversation: Conversation) -> tuple[str, str, str]:
        """Base instruction, persona block and memory block, in send order."""
        base = (
            "You are MyAI Studio, a precise desktop assistant. "
            "Answer in the user's language unless instructed otherwise."
        )
        persona_block = self._persona.build_system_block()
        memory_block = ""
        if bool(self._settings.get("memory.enabled", True)):
            memory_block = self._memory.build_context_block(conversation.id)
        return base, persona_block or "", memory_block or ""

    def context_map(
        self,
        conversation: Conversation,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        max_history_segments: int = 40,
    ) -> ContextMap:
        """Measure what the next request would contain, segment by segment.

        This mirrors :meth:`build_messages` — same blocks, same filters, same
        trim — so the chart cannot drift away from what is actually sent.
        """
        base_block, persona_block, memory_block = self._system_blocks(conversation)
        segments: list[PromptSegment] = [
            PromptSegment("system", "", len(base_block), estimate_tokens(base_block), base_block[:80]),
        ]
        if persona_block:
            segments.append(
                PromptSegment("persona", "", len(persona_block), estimate_tokens(persona_block), persona_block[:80])
            )
        if memory_block:
            segments.append(
                PromptSegment("memory", "", len(memory_block), estimate_tokens(memory_block), memory_block[:80])
            )

        history = self._conversations.messages(conversation.id)
        trimmed = history[-history_limit:] if history_limit else history
        usable = [
            message
            for message in trimmed
            if message.role in {"user", "assistant"}
            and message.status != "error"
            and (message.content or "").strip()
        ]
        overflow = max(0, len(usable) - max_history_segments)
        for index, message in enumerate(usable):
            if index < overflow:
                continue
            text = message.content or ""
            attachments = [
                str(item.get("name"))
                for item in ((message.meta or {}).get("attachments") or [])
                if item.get("name")
            ]
            if attachments and index != len(usable) - 1:
                text = f"{text}\n\n[Attached files: {', '.join(attachments)}]"
            preview = text.strip().splitlines()[0][:90] if text.strip() else ""
            segments.append(
                PromptSegment(
                    "history",
                    f"{message.role} #{index + 1}",
                    len(text),
                    estimate_tokens(text),
                    preview,
                )
            )
        if overflow:
            hidden_chars = sum(len(message.content or "") for message in usable[:overflow])
            segments.append(
                PromptSegment(
                    "history",
                    f"older #{overflow}",
                    hidden_chars,
                    estimate_tokens("x" * hidden_chars),
                    "",
                )
            )

        model_id = conversation.model_id or str(self._settings.get("ai.default_model", ""))
        window = self.context_window(model_id)
        total = sum(segment.tokens for segment in segments)
        memory_items = (
            len(self._memory.all_for_conversation(conversation.id))
            if bool(self._settings.get("memory.enabled", True))
            else 0
        )
        return ContextMap(
            segments=tuple(segments),
            total_tokens=total,
            window=window,
            ratio=min(1.0, total / window) if window else 0.0,
            model_id=model_id,
            history_messages=len(usable),
            memory_items=memory_items,
        )

    def context_status(self, conversation: Conversation) -> dict[str, Any]:
        """Usage report for the inspector, kept separate from memory storage."""
        model_id = conversation.model_id or str(self._settings.get("ai.default_model", ""))
        window = self.context_window(model_id)
        report = self._memory.context_report(conversation.id, window=window)
        report["model_id"] = model_id
        report["warn_ratio"] = float(self._settings.get("ai.context_warn_ratio", 0.8))
        report["warning"] = report["ratio"] >= report["warn_ratio"]
        return report

    # ------------------------------------------------------------------- send
    def send(
        self,
        conversation_id: str,
        text: str,
        *,
        model_id: str = "",
        attachments: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_status: Callable[[str, dict], None] | None = None,
    ) -> SendOutcome:
        """Persist the user message, stream the reply and store the result.

        ``attachments`` are the UI chips (name + original path). They are read,
        copied and extracted here, on the caller's worker thread, so a large
        file never blocks the window. The extracted text is sent with this one
        message; the stored message keeps only the plain text and the chips.
        """
        content = (text or "").strip()
        prepared = self.prepare_attachments(attachments or [])
        if not content and not prepared:
            raise ValidationError("Message is empty", message_key="error.empty_message")
        conversation = self._conversations.get(conversation_id)
        chosen_model = (model_id or conversation.model_id or str(self._settings.get("ai.default_model", ""))).strip()
        if not chosen_model:
            raise ValidationError("No model selected", message_key="error.no_model")
        if conversation.model_id != chosen_model:
            conversation = self._conversations.set_model(conversation_id, chosen_model)

        with self._lock:
            if self._active:
                raise ValidationError("A response is already streaming", message_key="error.busy")
            self._active = True
            self._cancel.clear()

        outcome = SendOutcome()
        try:
            user_message = self._conversations.add_message(
                conversation_id,
                "user",
                content,
                meta={"attachments": [record.to_meta() for record in prepared]} if prepared else {},
            )
            outcome.user_message = user_message
            if prepared and self._attachments is not None:
                try:
                    self._attachments.remember(user_message.id, prepared)
                except Exception:  # noqa: BLE001 - a chip must not break a reply
                    logger.exception("attachment_rows_failed")
            messages, diagnostics = self.build_messages(conversation, attachments=prepared)
            outcome.diagnostics = diagnostics
            self._bus.emit(Events.STREAM_STARTED, conversation_id=conversation_id, diagnostics=diagnostics.to_dict())

            # A placeholder row makes the assistant bubble appear immediately.
            assistant = self._conversations.add_message(
                conversation_id,
                "assistant",
                "",
                model_id=chosen_model,
                status="streaming",
                meta={"started_at": utcnow().isoformat()},
            )
            outcome.assistant_message = assistant
            buffer: list[str] = []

            def handle_delta(fragment: str) -> None:
                buffer.append(fragment)
                if on_delta is not None:
                    on_delta(fragment)
                self._bus.emit(
                    Events.MESSAGE_DELTA,
                    conversation_id=conversation_id,
                    message_id=assistant.id,
                    delta=fragment,
                    text="".join(buffer),
                )

            client = self.client()
            result = client.stream_chat(
                model=chosen_model,
                messages=messages,
                temperature=float(self._settings.get("ai.temperature", 0.7)),
                max_tokens=int(self._settings.get("ai.max_tokens", 4096)),
                cancel=self._cancel,
                on_delta=handle_delta,
            )
            outcome.result = result
            outcome.cancelled = result.cancelled
            self._finalize(assistant.id, result, chosen_model, diagnostics)
            outcome.assistant_message = self._conversations.get_message(assistant.id)
            if on_status is not None:
                on_status("done", {"stats": result.stats.to_dict(), "cancelled": result.cancelled})
            self._bus.emit(
                Events.STREAM_FINISHED,
                conversation_id=conversation_id,
                message_id=assistant.id,
                stats=result.stats.to_dict(),
                cancelled=result.cancelled,
            )
        except AppError as exc:
            outcome.error = exc
            if outcome.assistant_message is not None:
                self._mark_failed(outcome.assistant_message.id, exc)
            self._bus.emit(Events.MESSAGE_FAILED, conversation_id=conversation_id, error=exc.to_dict())
            if on_status is not None:
                on_status("error", {"error": exc.to_dict()})
            logger.warning("chat_failed code=%s", exc.code)
        except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to the UI
            logger.exception("chat_unexpected_error")
            wrapped = AppError("Unexpected provider failure", message_key="error.api_generic",
                               details=type(exc).__name__, cause=exc)
            outcome.error = wrapped
            if outcome.assistant_message is not None:
                self._mark_failed(outcome.assistant_message.id, wrapped)
            self._bus.emit(Events.MESSAGE_FAILED, conversation_id=conversation_id, error=wrapped.to_dict())
            if on_status is not None:
                on_status("error", {"error": wrapped.to_dict()})
        finally:
            with self._lock:
                self._active = False
            self._cancel.clear()
        return outcome

    # -------------------------------------------------------------- attachments
    def prepare_attachments(self, attachments: list[dict]) -> list[AttachmentRecord]:
        """Ingest the UI chips; a bad file raises a translated error."""
        if not attachments:
            return []
        if self._attachments is None:
            raise ValidationError(
                "Attachments are not available in this build",
                message_key="attachments.unsupported",
            )
        records: list[AttachmentRecord] = []
        for item in attachments:
            path = item.get("path") if isinstance(item, dict) else None
            if not path:
                continue
            records.append(self._attachments.ingest(path))
        return records

    # ---------------------------------------------------------------- helpers
    def _finalize(
        self,
        message_id: str,
        result: ChatResult,
        model_id: str,
        diagnostics: PromptDiagnostics | None = None,
    ) -> None:
        with self._db.session() as session:
            row = session.get(Message, message_id)
            if row is None:
                return
            row.content = result.text
            row.status = "cancelled" if result.cancelled else "complete"
            row.model_id = model_id
            # Provider usage wins; otherwise fall back to the documented estimate
            # of the prompt that was actually sent.
            row.input_tokens = result.stats.prompt_tokens or (
                diagnostics.total_tokens if diagnostics else 0
            )
            row.output_tokens = result.stats.completion_tokens or estimate_tokens(result.text)
            meta = dict(row.meta or {})
            meta["stats"] = result.stats.to_dict()
            meta["estimated_usage"] = not bool(result.stats.total_tokens)
            row.meta = meta
            session.flush()
        conversation = None
        with self._db.session() as session:
            row = session.get(Message, message_id)
            if row is not None:
                conversation = session.get(Conversation, row.conversation_id)
        if conversation is not None:
            self._bus.emit(Events.MESSAGE_UPDATED, message_id=message_id, conversation=conversation)

    def _mark_failed(self, message_id: str, error: AppError) -> None:
        with self._db.session() as session:
            row = session.get(Message, message_id)
            if row is None:
                return
            row.status = "error"
            row.error = error.message
            if not row.content:
                row.content = ""
            meta = dict(row.meta or {})
            meta["error"] = error.to_dict()
            row.meta = meta
            session.flush()
        self._bus.emit(Events.MESSAGE_UPDATED, message_id=message_id)


def build_chat_service(
    *,
    db: Database,
    bus: SignalBus,
    conversations: ConversationService,
    settings: SettingsService,
    memory: MemoryService,
    persona: PersonaService,
    attachments: "AttachmentService | None" = None,
    api_key_reader: Callable[[], str | None],
) -> ChatService:
    service = ChatService(
        db=db,
        bus=bus,
        conversations=conversations,
        settings=settings,
        memory=memory,
        persona=persona,
        attachments=attachments,
    )
    service.set_api_key_reader(api_key_reader)
    return service
