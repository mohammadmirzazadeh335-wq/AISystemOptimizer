"""Endpoints — one page where *any* API can be added.

The API page starts from a provider and asks for its key. This page starts from
the other side: paste a base URL, say which protocol it speaks, optionally add a
key and a couple of model ids, and the endpoint becomes a first-class provider
that the chat, the agent and every studio can use.

Three protocols are real, not decorative: an OpenAI-compatible endpoint
(``/chat/completions`` with ``Authorization: Bearer``), Anthropic's Messages API
and Google's generative-language API. Anything else is not silently pretended —
the page says which of the three a URL has to speak.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...core.errors import AppError
from ...i18n import tr
from ...services.net import options_from_settings
from ...services.providers import (
    PROTOCOL_ANTHROPIC,
    PROTOCOL_GEMINI,
    PROTOCOL_OPENAI,
    PROVIDERS,
    Provider,
    ProviderClient,
    base_url_for,
    custom_endpoints,
    delete_custom_endpoint,
    get_provider,
    has_stored_key,
    save_custom_endpoint,
)
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import SelectField
from ..widgets.foundation import Badge
from .page_base import (
    PageShell,
    field_label,
    ghost_button,
    hint_label,
    primary_button,
    run_async,
    secondary_button,
)

logger = logging.getLogger(__name__)

PROTOCOL_KEYS = {
    PROTOCOL_OPENAI: "endpoints.protocol_openai",
    PROTOCOL_ANTHROPIC: "endpoints.protocol_anthropic",
    PROTOCOL_GEMINI: "endpoints.protocol_gemini",
}

#: A short, honest description of what each protocol implies on the wire.
PROTOCOL_HINTS = {
    PROTOCOL_OPENAI: "endpoints.hint_openai",
    PROTOCOL_ANTHROPIC: "endpoints.hint_anthropic",
    PROTOCOL_GEMINI: "endpoints.hint_gemini",
}


def _split_models(text: str) -> tuple[str, ...]:
    """``"a, b\\nc"`` → ``("a", "b", "c")``, order kept, blanks dropped."""
    pieces = text.replace("\n", ",").split(",")
    seen: list[str] = []
    for piece in pieces:
        name = piece.strip()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


class EndpointRow(QWidget):
    """One saved endpoint: what it is, whether it has a key, and what to do."""

    def __init__(self, page: EndpointsPage, provider: Provider) -> None:  # noqa: F821
        super().__init__()
        self._page = page
        self._provider = provider
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(10), runtime.px(7), runtime.px(10), runtime.px(7))
        layout.setSpacing(runtime.px(8))

        text = QVBoxLayout()
        text.setSpacing(runtime.px(1))
        name = QLabel(provider.name)
        name.setStyleSheet("font-weight: 600;")
        text.addWidget(name)
        address = QLabel(f"{provider.base_url}")
        address.setProperty("role", "mono")
        address.setProperty("mono", True)
        address.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(address)
        layout.addLayout(text, 1)

        layout.addWidget(Badge(tr(PROTOCOL_KEYS.get(provider.protocol, "endpoints.protocol_openai")), "neutral"))
        has_key = has_stored_key(provider, page.context.secrets)
        if has_key:
            layout.addWidget(Badge(tr("endpoints.key_set"), "success"))
        elif provider.key_required:
            layout.addWidget(Badge(tr("endpoints.key_missing"), "warning"))
        else:
            layout.addWidget(Badge(tr("endpoints.key_optional"), "neutral"))

        use = ghost_button(tr("endpoints.use"), "check")
        use.clicked.connect(lambda _=False, pid=provider.id: self._page.use_endpoint(pid))
        layout.addWidget(use)
        test = ghost_button(tr("endpoints.test"), "activity")
        test.clicked.connect(lambda _=False, pid=provider.id: self._page.test_endpoint(pid))
        layout.addWidget(test)
        remove = ghost_button(tr("endpoints.delete"), "trash")
        remove.clicked.connect(lambda _=False, pid=provider.id: self._page.delete_endpoint(pid))
        layout.addWidget(remove)


class EndpointsPage(PageShell):
    notify = Signal(str, str)
    #: Emitted after the endpoint list changes, so the API page can re-render.
    endpoints_changed = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("endpoints.title", "endpoints.subtitle", icon_name="plug")
        self.context = context
        self._busy = False
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._build_form()
        self._build_presets()
        self._build_saved()

    def _build_form(self) -> None:
        card, layout = self.card("endpoints.add_card", "plus")
        layout.addWidget(hint_label(tr("endpoints.add_hint")))

        grid = QVBoxLayout()
        grid.setSpacing(runtime.px(7))

        first = QHBoxLayout()
        first.setSpacing(runtime.px(8))
        name_col = QVBoxLayout()
        name_col.setSpacing(runtime.px(3))
        name_col.addWidget(field_label(tr("endpoints.name")))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("endpoints.name_placeholder"))
        self.name_input.setAccessibleName(tr("endpoints.name"))
        name_col.addWidget(self.name_input)
        first.addLayout(name_col, 1)

        protocol_col = QVBoxLayout()
        protocol_col.setSpacing(runtime.px(3))
        protocol_col.addWidget(field_label(tr("endpoints.protocol")))
        # "OpenAI-compatible" is the longest option and it must not elide to
        # "OpenAI-comp…" — the protocol is the whole point of this page.
        self.protocol_picker = SelectField(
            [(key, tr(label)) for key, label in PROTOCOL_KEYS.items()],
            placeholder=tr("endpoints.protocol"),
            compact=True,
            min_width=runtime.px(205),
        )
        self.protocol_picker.set_value(PROTOCOL_OPENAI)
        self.protocol_picker.value_changed.connect(self._on_protocol_changed)
        self.protocol_picker.setAccessibleName(tr("endpoints.protocol"))
        protocol_col.addWidget(self.protocol_picker)
        first.addLayout(protocol_col, 0)
        grid.addLayout(first)

        grid.addWidget(field_label(tr("endpoints.url")))
        self.url_input = QLineEdit()
        self.url_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.url_input.setPlaceholderText(tr("endpoints.url_placeholder"))
        self.url_input.setAccessibleName(tr("endpoints.url"))
        self.url_input.textChanged.connect(self._update_protocol_hint)
        grid.addWidget(self.url_input)

        self.protocol_hint = hint_label(tr(PROTOCOL_HINTS[PROTOCOL_OPENAI]))
        self.protocol_hint.setWordWrap(True)
        grid.addWidget(self.protocol_hint)

        second = QHBoxLayout()
        second.setSpacing(runtime.px(8))
        key_col = QVBoxLayout()
        key_col.setSpacing(runtime.px(3))
        key_col.addWidget(field_label(tr("endpoints.key")))
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText(tr("endpoints.key_placeholder"))
        self.key_input.setAccessibleName(tr("endpoints.key"))
        key_col.addWidget(self.key_input)
        second.addLayout(key_col, 1)

        models_col = QVBoxLayout()
        models_col.setSpacing(runtime.px(3))
        models_col.addWidget(field_label(tr("endpoints.models")))
        self.models_input = QLineEdit()
        self.models_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.models_input.setPlaceholderText(tr("endpoints.models_placeholder"))
        self.models_input.setAccessibleName(tr("endpoints.models"))
        models_col.addWidget(self.models_input)
        second.addLayout(models_col, 1)
        grid.addLayout(second)
        grid.addWidget(hint_label(tr("endpoints.models_hint")))
        layout.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(7))
        self.save_button = primary_button(tr("endpoints.save"), "check")
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)
        self.clear_button = secondary_button(tr("endpoints.clear"), "refresh")
        self.clear_button.clicked.connect(self._clear_form)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        self.test_button = secondary_button(tr("endpoints.test_saved"), "activity")
        self.test_button.clicked.connect(self._test_form)
        self.test_button.setEnabled(False)
        row.addWidget(self.test_button)
        layout.addLayout(row)
        self.status = hint_label("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _build_presets(self) -> None:
        """One click fills a known vendor; the free-form form stays the default.

        Typing ``https://api.arena.ai/v1`` from memory is exactly the kind of
        small friction that makes an "any API" page feel empty, so the vendors
        the app already knows are offered as starting points — the key is still
        the user's, and the address stays editable.
        """
        card, layout = self.card("endpoints.presets_card", "star")
        layout.addWidget(hint_label(tr("endpoints.presets_hint")))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(runtime.px(6))
        grid.setVerticalSpacing(runtime.px(6))
        known = [item for item in PROVIDERS if item.base_url and item.id != "custom"]
        for index, provider in enumerate(known):
            button = secondary_button(provider.name, "plus")
            button.setToolTip(provider.base_url)
            button.clicked.connect(lambda _=False, item=provider: self._use_preset(item))
            grid.addWidget(button, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addWidget(grid_host)

    def _use_preset(self, provider: Provider) -> None:
        self.name_input.setText(provider.name)
        self.url_input.setText(provider.base_url)
        self.protocol_picker.set_value(provider.protocol)
        self.models_input.clear()
        self._update_protocol_hint()
        self._set_status(tr("endpoints.preset_applied", name=provider.name))
        self.key_input.setFocus()

    def _build_saved(self) -> None:
        card, layout = self.card("endpoints.saved_card", "server")
        layout.addWidget(hint_label(tr("endpoints.saved_hint")))
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(runtime.px(5))
        layout.addWidget(self.list_host)

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        """Re-read the saved endpoints (called on every navigation)."""
        self._render_saved()

    def _render_saved(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        rows = [row for row in custom_endpoints(self.context.settings) if row.get("id")]
        if not rows:
            self.list_layout.addWidget(hint_label(tr("endpoints.empty")))
            return
        for row in rows:
            provider = get_provider(str(row.get("id")))
            frame = QWidget()
            frame.setProperty("panel", "row")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.addWidget(EndpointRow(self, provider))
            self.list_layout.addWidget(frame)

    def _on_protocol_changed(self, _value: str) -> None:
        self._update_protocol_hint()

    def _update_protocol_hint(self) -> None:
        protocol = self.protocol_picker.value or PROTOCOL_OPENAI
        key = PROTOCOL_HINTS.get(protocol, "endpoints.hint_openai")
        self.protocol_hint.setText(tr(key))
        self._update_test_state()

    def _update_test_state(self) -> None:
        self.test_button.setEnabled(bool(self.url_input.text().strip()) and not self._busy)

    # ------------------------------------------------------------------ actions
    def _set_status(self, text: str, tone: str = "") -> None:
        self.status.setText(text)
        self.status.setProperty("role", tone or "faint")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _clear_form(self) -> None:
        self.name_input.clear()
        self.url_input.clear()
        self.key_input.clear()
        self.models_input.clear()
        self.protocol_picker.set_value(PROTOCOL_OPENAI)
        self._set_status("")

    def _save(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self._set_status(tr("endpoints.url_required"), "danger")
            self.url_input.setFocus()
            return
        name = self.name_input.text().strip() or url
        models = _split_models(self.models_input.text())
        try:
            provider = save_custom_endpoint(
                self.context.settings,
                {
                    "name": name,
                    "base_url": url,
                    "protocol": self.protocol_picker.value or PROTOCOL_OPENAI,
                    "key_required": True,
                    "models": list(models),
                },
            )
        except AppError as exc:
            # The typed URL never reaches the log; only the translation key does.
            self._set_status(tr(exc.message_key or "endpoints.save_failed"), "danger")
            return
        key = self.key_input.text().strip()
        if key:
            try:
                self.context.secrets.set_key(provider.id, key)
            except Exception:  # noqa: BLE001 - the endpoint still exists without a key
                logger.exception("endpoint_key_store_failed")
                self._set_status(tr("endpoints.key_store_failed"), "danger")
            else:
                self.key_input.clear()
        self.context.settings.set("ai.provider", provider.id)
        self._set_status(tr("endpoints.saved", name=provider.name), "success")
        self.notify.emit(tr("endpoints.saved", name=provider.name), "success")
        self._render_saved()
        self._update_test_state()
        self.endpoints_changed.emit()

    def _client_for(self, provider: Provider) -> ProviderClient:
        return ProviderClient(
            lambda: self.context.secrets.get_key(provider.id),
            provider=provider.id,
            base_url=base_url_for(provider, self.context.settings),
            network=options_from_settings(self.context.settings),
        )

    def _test_form(self) -> None:
        """Prove the URL works before the user commits the endpoint."""
        url = self.url_input.text().strip()
        if not url:
            self._set_status(tr("endpoints.url_required"), "danger")
            return
        protocol = self.protocol_picker.value or PROTOCOL_OPENAI
        # Build a throw-away provider so the test uses exactly what is typed.
        probe = Provider(
            id="cx-probe",
            name=self.name_input.text().strip() or url,
            protocol=protocol,
            base_url=url.rstrip("/"),
            key_required=True,
            custom=True,
        )
        key = self.key_input.text().strip()
        client = ProviderClient(
            lambda: key,
            provider=probe.id,
            base_url=probe.base_url,
            network=options_from_settings(self.context.settings),
            spec=probe,
        )
        self._run_test(client, probe)

    def test_endpoint(self, provider_id: str) -> None:
        provider = get_provider(provider_id)
        self._run_test(self._client_for(provider), provider)

    def _run_test(self, client: ProviderClient, provider: Provider) -> None:
        if self._busy:
            return
        self._busy = True
        self._update_test_state()
        self._set_status(tr("endpoints.testing"))
        run_async(
            self,
            lambda: client.list_models(refresh=True),
            on_success=lambda models: self._on_test_ok(models, provider),
            on_error=self._on_test_error,
        )

    def _on_test_ok(self, models: object, provider: Provider) -> None:
        self._busy = False
        self._update_test_state()
        count = len(models) if isinstance(models, list) else 0
        if count:
            self._set_status(tr("endpoints.test_ok", name=provider.name, count=count), "success")
            if isinstance(models, list) and models:
                sample = ", ".join(model.id for model in models[:3])
                self._set_status(tr("endpoints.test_ok", name=provider.name, count=count) + f" · {sample}", "success")
        else:
            self._set_status(tr("endpoints.test_empty", name=provider.name), "warning")

    def _on_test_error(self, exc: Exception) -> None:
        self._busy = False
        self._update_test_state()
        code = getattr(exc, "code", "") or ""
        message = code or type(exc).__name__
        self._set_status(tr("endpoints.test_failed", error=message), "danger")

    def use_endpoint(self, provider_id: str) -> None:
        self.context.settings.set("ai.provider", provider_id)
        provider = get_provider(provider_id)
        self.notify.emit(tr("endpoints.now_active", name=provider.name), "success")
        self._render_saved()
        self.endpoints_changed.emit()

    def delete_endpoint(self, provider_id: str) -> None:
        provider = get_provider(provider_id)
        dialog = ConfirmDialog(
            self,
            tr("endpoints.delete_title"),
            tr("endpoints.delete_body", name=provider.name),
            confirm_text=tr("endpoints.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        try:
            removed = delete_custom_endpoint(self.context.settings, provider_id)
        except AppError:
            logger.exception("endpoint_delete_failed")
            self._set_status(tr("endpoints.delete_failed"), "danger")
            return
        if removed:
            try:
                self.context.secrets.delete(self.context.secrets.key_name(provider_id))
            except Exception:  # noqa: BLE001 - the row is gone either way
                logger.exception("endpoint_key_delete_failed")
            self._render_saved()
            self._set_status(tr("endpoints.deleted", name=provider.name), "success")
            self.notify.emit(tr("endpoints.deleted", name=provider.name), "success")
            self.endpoints_changed.emit()

    def retranslate(self) -> None:
        super().retranslate()
        self.name_input.setPlaceholderText(tr("endpoints.name_placeholder"))
        self.url_input.setPlaceholderText(tr("endpoints.url_placeholder"))
        self.key_input.setPlaceholderText(tr("endpoints.key_placeholder"))
        self.models_input.setPlaceholderText(tr("endpoints.models_placeholder"))
        self.protocol_picker.set_items([(key, tr(label)) for key, label in PROTOCOL_KEYS.items()])
        self.protocol_picker.set_value(self.protocol_picker.value or PROTOCOL_OPENAI)
        self.save_button.setText(tr("endpoints.save"))
        self.clear_button.setText(tr("endpoints.clear"))
        self.test_button.setText(tr("endpoints.test_saved"))
        self._update_protocol_hint()
        self._render_saved()

