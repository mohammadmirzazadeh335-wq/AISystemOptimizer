"""OpenRouter connection page.

Everything on this screen talks to the real service through
:class:`myai.services.openrouter.OpenRouterClient`. When the network is
unavailable the page says so explicitly and keeps the key stored locally; it
never shows a fabricated model list or a fake "connected" state.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...i18n import has_key, tn, tr
from ...services.net import (
    NetworkOptions,
    NetworkProbe,
    normalize_proxy,
    options_from_settings,
    resolve_proxy,
)
from ...services.openrouter import (
    ConnectionTest,
    ModelInfo,
    model_from_dict,
    model_to_dict,
)
from ...services.providers import (
    Provider,
    ProviderClient,
    all_providers,
    base_url_for,
    cached_models,
    current_provider,
    custom_endpoints,
    delete_custom_endpoint,
    get_provider,
    has_stored_key,
    key_problem,
    model_id_problem,
    models_cache,
    normalize_base_url,
    save_base_url,
    save_custom_endpoint,
)
from ...services.providers import (
    has_key as provider_has_key,
)
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import FlowLayout, SelectField
from ..widgets.foundation import Badge
from ..widgets.model_picker import Choice, model_tags
from .page_base import (
    PageShell,
    danger_button,
    field_label,
    ghost_button,
    hint_label,
    primary_button,
    run_async,
    secondary_button,
)

logger = logging.getLogger(__name__)


class ModelRow(QFrame):
    chosen = Signal(str)

    def __init__(
        self,
        model: ModelInfo,
        current: str,
        parent: QWidget | None = None,
        manual: bool = False,
    ) -> None:
        super().__init__(parent)
        self.model = model
        self.setObjectName("ModelRow")
        self.setProperty("panel", "row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(11), runtime.px(8), runtime.px(11), runtime.px(8))
        layout.setSpacing(runtime.px(9))

        text_col = QVBoxLayout()
        text_col.setSpacing(runtime.px(1))
        name = QLabel(model.name or model.id)
        name.setStyleSheet("font-weight: 600;")
        text_col.addWidget(name)
        meta = QLabel(model.id)
        meta.setProperty("role", "faint")
        meta.setProperty("mono", True)
        meta.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        text_col.addWidget(meta)
        layout.addLayout(text_col, 1)

        badges = QHBoxLayout()
        badges.setSpacing(runtime.px(5))
        if manual:
            # A row the user typed is not a provider claim; say so on the row.
            typed = Badge(tr("api.model_id_manual_badge"), "warning")
            typed.setToolTip(tr("api.model_id_complexity", model=model.id))
            badges.addWidget(typed)
        if model.context_length:
            badges.addWidget(Badge(model.context_label(), "outline"))
        if model.is_free():
            badges.addWidget(Badge(tr("api.free"), "success"))
        if model.supports_tools:
            badges.addWidget(Badge(tr("api.tools"), "violet"))
        if model.supports_vision:
            badges.addWidget(Badge(tr("api.vision"), "accent"))
        layout.addLayout(badges)

        price = QLabel(self._price_text(model))
        price.setProperty("role", "faint")
        price.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        price.setMinimumWidth(runtime.px(78))
        price.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(price)

        choose = ghost_button(tr("api.use"), "check")
        choose.setEnabled(model.id != current)
        choose.clicked.connect(lambda: self.chosen.emit(self.model.id))
        layout.addWidget(choose)

        self.setStyleSheet(
            f"QFrame#ModelRow {{ background-color: {runtime.theme().alpha('surface_2', 0.55)};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(9)}px; }}"
        )

    @staticmethod
    def _price_text(model: ModelInfo) -> str:
        state = model.price_state()
        if state == "free":
            return tr("api.free")
        if state == "paid":
            if not model.prompt_price and not model.completion_price:
                return tr("api.paid")
            return f"${model.prompt_price:g} / ${model.completion_price:g}"
        # The catalogue published no price. Saying "free" here would be a lie;
        # saying "paid" would be a guess.
        return tr("api.price_unknown")


class ApiPage(PageShell):
    """Key management, connection test, live catalogue and sampling defaults."""

    model_selected = Signal(str)
    models_updated = Signal(list)
    notify = Signal(str, str)
    provider_changed = Signal(str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("api.title", "api.subtitle", icon_name="key")
        self.context = context
        self._models: list[ModelInfo] = []
        self._busy = False
        self._filter = ""
        self._choices: list = []
        self._manual_models: dict[str, ModelInfo] = {}
        self.provider: Provider = current_provider(context.settings)
        self._build()
        runtime.signals.changed.connect(lambda *_: self._restyle())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._build_provider_card()
        self._build_custom_card()
        self._build_key_card()
        self._build_test_card()
        self._build_network_card()
        self._build_catalogue_card()
        self._build_sampling_card()
        self._refresh_key_state()
        self._sync_provider_fields()

    # --------------------------------------------------------------- provider
    def _build_provider_card(self) -> None:
        """Which service answers, and at which address.

        Before 0.9 the endpoint was a constant: OpenRouter or nothing. The
        selector is the whole feature, so it sits above the key and states what
        the choice implies (key needed / local / custom URL).
        """
        card, layout = self.card("api.provider_card", "layers")
        self.provider_hint = hint_label(tr("api.provider_hint"))
        self.provider_hint.setWordWrap(True)
        layout.addWidget(self.provider_hint)

        host = QWidget()
        row = FlowLayout(host, spacing=runtime.px(8))
        layout.addWidget(host)
        self.provider_label = field_label(tr("api.provider_label"))
        row.addWidget(self.provider_label)
        self.provider_select = SelectField(
            self._provider_items(),
            placeholder=tr("api.provider_none"),
            icon_name="layers",
            searchable=True,
            search_placeholder=tr("picker.provider_search"),
        )
        self.provider_select.set_value(self.provider.id)
        self.provider_select.value_changed.connect(self._on_provider_selected)
        row.addWidget(self.provider_select)
        self.provider_badge_holder = QWidget()
        self.provider_badge_layout = QHBoxLayout(self.provider_badge_holder)
        self.provider_badge_layout.setContentsMargins(0, 0, 0, 0)
        self.provider_badge_layout.addWidget(Badge(tr("api.key_required_badge"), "warning"))
        row.addWidget(self.provider_badge_holder)
        layout.addWidget(host)

        self.provider_note = hint_label("")
        self.provider_note.setWordWrap(True)
        layout.addWidget(self.provider_note)

        url_host = QWidget()
        url_row = FlowLayout(url_host, spacing=runtime.px(8))
        layout.addWidget(url_host)
        self.base_url_label = field_label(tr("api.base_url"))
        url_row.addWidget(self.base_url_label)
        self.base_url_input = QLineEdit()
        self.base_url_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.base_url_input.setPlaceholderText("https://…")
        self.base_url_input.setAccessibleName(tr("api.base_url"))
        self.base_url_input.setMinimumWidth(runtime.px(260))
        self.base_url_input.setMaximumWidth(runtime.px(520))
        self.base_url_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.base_url_input.textChanged.connect(lambda _text: self._sync_base_url_state())
        url_row.addWidget(self.base_url_input)
        self.base_url_save = primary_button(tr("api.save_url"), "check")
        self.base_url_save.clicked.connect(self._save_base_url)
        url_row.addWidget(self.base_url_save)
        layout.addWidget(url_host)
        self.base_url_hint = hint_label(tr("api.base_url_hint"))
        self.base_url_hint.setWordWrap(True)
        layout.addWidget(self.base_url_hint)

    def _provider_badge(self) -> None:
        while self.provider_badge_layout.count():
            item = self.provider_badge_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        if self.provider.local:
            self.provider_badge_layout.addWidget(Badge(tr("api.key_local_badge"), "muted"))
        elif self.provider.key_required:
            self.provider_badge_layout.addWidget(Badge(tr("api.key_required_badge"), "warning"))
        else:
            self.provider_badge_layout.addWidget(Badge(tr("api.key_local_badge"), "muted"))

    def _sync_provider_fields(self) -> None:
        """Everything on the page follows the selected provider."""
        self.provider = current_provider(self.context.settings)
        self.provider_select.set_value(self.provider.id)
        if self.provider.note_key:
            self.provider_note.setText(tr(self.provider.note_key))
        elif self.provider.custom:
            self.provider_note.setText(tr("api.custom_note", name=self.provider.name))
        else:
            self.provider_note.setText("")
        self._provider_badge()
        url = base_url_for(self.provider, self.context.settings)
        if self.base_url_input.text().strip() != url:
            self.base_url_input.setText(url)
            # A QLineEdit shows the text around the cursor; a long URL set
            # programmatically left the field scrolled to its tail ("erative…"),
            # which reads like a corrupted address. Show the host from the start.
            self.base_url_input.setCursorPosition(0)
        self.base_url_input.setPlaceholderText(self.provider.base_url or "https://…")
        self._sync_base_url_state()
        self.endpoint_value.setText(url)
        self.key_input.setPlaceholderText(self.provider.key_hint or "…")

    def _sync_base_url_state(self) -> None:
        saved = base_url_for(self.provider, self.context.settings)
        typed = self.base_url_input.text().strip().rstrip("/")
        self.base_url_save.setEnabled(typed != saved)
        try:
            normalize_base_url(typed, provider=self.provider)
            valid = True
            error = ""
        except Exception as exc:  # noqa: BLE001 - the message is the point
            valid = False
            error = self._localized_error(exc) if isinstance(exc, AppError) else str(exc)
        self.base_url_input.setToolTip(error)
        self.base_url_hint.setText(tr("api.base_url_hint") if valid or not typed else error)

    def _on_provider_selected(self, provider_id: str) -> None:
        if not provider_id or provider_id == self.provider.id:
            return
        try:
            self.context.settings.update({"ai.provider": provider_id})
        except AppError as exc:
            self.notify.emit(self._localized_error(exc), "error")
            return
        self.provider = current_provider(self.context.settings)
        self._filter = ""
        # A model id typed for the previous service is meaningless for this one;
        # keeping it would offer a row that cannot answer.
        self._manual_models.clear()
        self.search.setText("")
        self._sync_provider_fields()
        self._refresh_key_state()
        self._models = []
        self._render_models()
        self.models_updated.emit([])
        self.provider_changed.emit(self.provider.id)
        self.notify.emit(tr("api.provider_saved", name=self._provider_name()), "success")
        if provider_has_key(self.provider, self.context.secrets):
            self._load_models(refresh=True)
        elif self.provider.local:
            self._load_models(refresh=True)

    def _provider_name(self) -> str:
        key = f"provider.{self.provider.id}"
        return tr(key) if has_key(key) else self.provider.name

    def _save_base_url(self) -> None:
        try:
            clean = save_base_url(
                self.context.settings, self.provider, self.base_url_input.text()
            )
        except AppError as exc:
            self.notify.emit(self._localized_error(exc), "error")
            return
        self.base_url_input.setText(clean)
        self.base_url_input.setCursorPosition(0)
        self.endpoint_value.setText(clean)
        self._sync_base_url_state()
        self.notify.emit(tr("api.url_saved", name=self._provider_name()), "success")
        self.provider_changed.emit(self.provider.id)

    def _provider_items(self) -> list[tuple[str, str]]:
        return [
            (
                item.id,
                tr(f"provider.{item.id}") if has_key(f"provider.{item.id}") else item.name,
            )
            for item in all_providers()
        ]

    def _refresh_provider_select(self) -> None:
        """Rebuild the selector after an endpoint was added or removed."""
        self.provider_select.set_items(self._provider_items())
        self.provider_select.set_value(self.provider.id)

    def _build_custom_card(self) -> None:
        """Add any endpoint by address — the built-in list is a shortcut, not a cage.

        A relay that speaks the OpenAI wire protocol is configured with three
        facts: a name, a base URL and whether it wants a key. Everything else in
        the app (chat, agent, catalogue, usage) already follows the selected
        provider, so one saved endpoint is a first-class service here.
        """
        card, layout = self.card("api.custom_card", "plug")
        hint = hint_label(tr("api.custom_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        host = QWidget()
        row = FlowLayout(host, spacing=runtime.px(8))
        layout.addWidget(host)
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText(tr("api.custom_name_placeholder"))
        self.custom_name.setAccessibleName(tr("api.custom_name"))
        self.custom_name.setMinimumWidth(runtime.px(150))
        self.custom_name.setMaximumWidth(runtime.px(240))
        row.addWidget(self.custom_name)

        self.custom_url = QLineEdit()
        self.custom_url.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.custom_url.setPlaceholderText(tr("api.custom_url_placeholder"))
        self.custom_url.setAccessibleName(tr("api.custom_url"))
        self.custom_url.setMinimumWidth(runtime.px(240))
        self.custom_url.setMaximumWidth(runtime.px(430))
        self.custom_url.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self.custom_url)

        self.custom_protocol = SelectField(
            [
                ("openai", tr("api.protocol_openai")),
                ("anthropic", tr("api.protocol_anthropic")),
                ("gemini", tr("api.protocol_gemini")),
            ],
            placeholder=tr("api.protocol_openai"),
        )
        self.custom_protocol.set_value("openai")
        row.addWidget(self.custom_protocol)

        self.custom_key_required = QCheckBox(tr("api.custom_key_required"))
        self.custom_key_required.setChecked(True)
        row.addWidget(self.custom_key_required)

        self.custom_add = primary_button(tr("api.custom_add"), "plus")
        self.custom_add.clicked.connect(self._save_custom_endpoint)
        row.addWidget(self.custom_add)
        layout.addWidget(host)

        self.custom_message = hint_label("")
        self.custom_message.setWordWrap(True)
        layout.addWidget(self.custom_message)

        self.custom_list_host = QWidget()
        self.custom_list = QVBoxLayout(self.custom_list_host)
        self.custom_list.setContentsMargins(0, 0, 0, 0)
        self.custom_list.setSpacing(runtime.px(6))
        layout.addWidget(self.custom_list_host)
        self._render_custom_endpoints()

    def _render_custom_endpoints(self) -> None:
        while self.custom_list.count():
            item = self.custom_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        rows = [row for row in custom_endpoints(self.context.settings) if row.get("id")]
        if not rows:
            empty = hint_label(tr("api.custom_empty"))
            empty.setWordWrap(True)
            self.custom_list.addWidget(empty)
            return
        for row in rows:
            provider = get_provider(str(row.get("id")))
            frame = QFrame()
            frame.setProperty("panel", "row")
            line = QHBoxLayout(frame)
            line.setContentsMargins(runtime.px(10), runtime.px(6), runtime.px(10), runtime.px(6))
            line.setSpacing(runtime.px(8))
            name = QLabel(provider.name)
            name.setStyleSheet("font-weight: 600;")
            line.addWidget(name)
            address = QLabel(f"{provider.base_url} · {provider.protocol}")
            address.setProperty("role", "faint")
            address.setProperty("mono", True)
            address.setStyleSheet(f"font-size: {runtime.px(9)}px;")
            line.addWidget(address, 1)
            if provider.id == self.provider.id:
                line.addWidget(Badge(tr("api.custom_active"), "success"))
            use = ghost_button(tr("api.custom_use"), "check")
            use.clicked.connect(lambda _=False, pid=provider.id: self._use_custom(pid))
            line.addWidget(use)
            remove = ghost_button(tr("api.custom_delete"), "trash")
            remove.clicked.connect(lambda _=False, pid=provider.id: self._delete_custom(pid))
            line.addWidget(remove)
            self.custom_list.addWidget(frame)

    def _save_custom_endpoint(self) -> None:
        name = self.custom_name.text().strip() or self.custom_url.text().strip()
        url = self.custom_url.text().strip()
        if not url:
            self._set_custom_message(tr("api.base_url_required"), danger=True)
            self.custom_url.setFocus()
            return
        try:
            provider = save_custom_endpoint(
                self.context.settings,
                {
                    "name": name,
                    "base_url": url,
                    "protocol": self.custom_protocol.value or "openai",
                    "key_required": self.custom_key_required.isChecked(),
                },
            )
        except AppError as exc:
            # The user's own text (a URL, a name) is not echoed into a log; the
            # error's translation key is enough and stays localised.
            self._set_custom_message(tr(exc.message_key or "error.settings"), danger=True)
            return
        self.provider = provider
        self._refresh_provider_select()
        self.custom_name.clear()
        self.custom_url.clear()
        self.custom_message.setText("")
        self._render_custom_endpoints()
        self._sync_provider_fields()
        self._refresh_key_state()
        self.provider_changed.emit(provider.id)
        self.notify.emit(tr("api.custom_saved", name=provider.name), "success")

    def _use_custom(self, provider_id: str) -> None:
        self.context.settings.set("ai.provider", provider_id)
        self.provider = get_provider(provider_id)
        self._refresh_provider_select()
        self._render_custom_endpoints()
        self._sync_provider_fields()
        self._refresh_key_state()
        self.provider_changed.emit(provider_id)

    def _delete_custom(self, provider_id: str) -> None:
        provider = get_provider(provider_id)
        dialog = ConfirmDialog(
            self,
            tr("api.custom_delete_title"),
            tr("api.custom_delete_body", name=provider.name),
            confirm_text=tr("api.custom_delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        try:
            self.context.secrets.delete(self.context.secrets.key_name(provider_id))
        except Exception:  # noqa: BLE001 - a missing key is not a failure here
            logger.debug("custom_endpoint_key_delete_failed", exc_info=True)
        delete_custom_endpoint(self.context.settings, provider_id)
        if self.provider.id == provider_id:
            self.provider = current_provider(self.context.settings)
        self._refresh_provider_select()
        self._render_custom_endpoints()
        self._sync_provider_fields()
        self._refresh_key_state()
        self.provider_changed.emit(self.provider.id)
        self.notify.emit(tr("api.custom_deleted", name=provider.name), "info")

    def _set_custom_message(self, text: str, *, danger: bool = False) -> None:
        self.custom_message.setText(text)
        self.custom_message.setProperty("role", "danger" if danger else "faint")
        self.custom_message.style().unpolish(self.custom_message)
        self.custom_message.style().polish(self.custom_message)

    def _build_key_card(self) -> None:
        card, layout = self.card("api.key_card", "lock")
        self.key_state = QLabel()
        self.key_state.setWordWrap(True)
        self.key_state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.key_state)

        self.key_input = QLineEdit()
        self.key_input.setAccessibleName(tr("api.key_label"))
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.key_input.setPlaceholderText("sk-or-v1-…")
        self.key_input.setMinimumHeight(runtime.px(34))
        self.key_label = field_label(tr("api.key_label"))
        layout.addWidget(self.key_label)
        layout.addWidget(self.key_input)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(7))
        self.save_key = primary_button(tr("api.save_key"), "lock")
        # A key that is not typed cannot be saved; keeping the button live only
        # produced an error message after a pointless click.
        self.save_key.setEnabled(False)
        self.save_key.clicked.connect(self._save_key)
        self.key_input.textChanged.connect(self._sync_key_button)
        row.addWidget(self.save_key)
        self.show_key = ghost_button(tr("api.show_key"), "eye")
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(self._toggle_visibility)
        row.addWidget(self.show_key)
        self.delete_key = danger_button(tr("api.delete_key"), "trash")
        self.delete_key.clicked.connect(self._delete_key)
        row.addWidget(self.delete_key)
        row.addStretch(1)
        self.key_badge_holder = QWidget()
        self.key_badge_layout = QHBoxLayout(self.key_badge_holder)
        self.key_badge_layout.setContentsMargins(0, 0, 0, 0)
        self.key_badge_layout.addWidget(Badge(tr("api.not_configured"), "warning"))
        row.addWidget(self.key_badge_holder)
        layout.addLayout(row)
        layout.addWidget(hint_label(tr("api.key_hint")))
        self.key_error = QLabel("")
        self.key_error.setProperty("role", "danger")
        self.key_error.setWordWrap(True)
        self.key_error.hide()
        layout.addWidget(self.key_error)

    def _build_test_card(self) -> None:
        card, layout = self.collapsible_card(
            "api.test_card", "activity", key="api.card.test", open_by_default=False
        )
        layout.addWidget(hint_label(tr("api.test_hint")))
        self.network_note = hint_label(tr("api.test_network_note"))
        layout.addWidget(self.network_note)
        row = QHBoxLayout()
        row.setSpacing(runtime.px(8))
        self.test_button = secondary_button(tr("api.run_test"), "plug")
        self.test_button.clicked.connect(self._test_connection)
        row.addWidget(self.test_button)
        self.test_result = QLabel(tr("api.test_idle"))
        self.test_result.setProperty("role", "faint")
        self.test_result.setWordWrap(True)
        row.addWidget(self.test_result, 1)
        layout.addLayout(row)

        self.endpoint_row = QHBoxLayout()
        self.endpoint_row.setSpacing(runtime.px(7))
        layout.addLayout(self.endpoint_row)
        self.endpoint_label = field_label(tr("api.base_url"))
        self.endpoint_row.addWidget(self.endpoint_label)
        self.endpoint_value = QLabel(str(self.context.settings.get("ai.base_url", "")))
        self.endpoint_value.setProperty("role", "mono")
        self.endpoint_value.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        self.endpoint_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.endpoint_row.addWidget(self.endpoint_value, 1)

    def _proxy_select(self) -> SelectField:
        """(value, label) — the widget stores the value on the left."""
        return SelectField(
            [
                ("system", tr("api.proxy_system")),
                ("manual", tr("api.proxy_manual")),
                ("off", tr("api.proxy_off")),
            ],
            placeholder=tr("api.proxy_mode"),
        )

    def _network_options(self) -> NetworkOptions:
        """Saved values — what the client actually uses."""
        return options_from_settings(self.context.settings)

    def _preview_options(self) -> NetworkOptions:
        """Saved values overlaid with what is typed right now.

        The status line must answer "what happens if I save this", not only
        "what was saved last time"; otherwise typing an address looks ignored.
        """
        saved = options_from_settings(self.context.settings)
        return replace(
            saved,
            mode=self.proxy_mode.value or saved.mode,
            manual_proxy=self.proxy_url.text().strip(),
        )

    def _build_network_card(self) -> None:
        """Proxy/VPN settings — the usual reason a key works for nobody."""
        card, layout = self.collapsible_card(
            "api.network_card", "globe", key="api.card.network", open_by_default=False
        )
        self.proxy_hint = hint_label(tr("api.proxy_hint"))
        self.proxy_hint.setWordWrap(True)
        layout.addWidget(self.proxy_hint)

        # A flow layout, not a row: three controls plus an address field are
        # wider than the page at 1.25x and would clip the last button.
        self.proxy_host = QWidget()
        self.proxy_row = FlowLayout(self.proxy_host, spacing=runtime.px(8))
        layout.addWidget(self.proxy_host)

        self.proxy_mode_label = field_label(tr("api.proxy_mode"))
        self.proxy_row.addWidget(self.proxy_mode_label)
        self.proxy_mode = self._proxy_select()
        self.proxy_mode.set_value(str(self.context.settings.get("network.proxy_mode", "system")))
        self.proxy_mode.value_changed.connect(self._on_proxy_mode)
        self.proxy_row.addWidget(self.proxy_mode)

        self.proxy_url_label = field_label(tr("api.proxy_url"))
        self.proxy_row.addWidget(self.proxy_url_label)
        self.proxy_url = QLineEdit(str(self.context.settings.get("network.proxy_url", "")))
        self.proxy_url.setPlaceholderText("http://127.0.0.1:10809")
        self.proxy_url.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.proxy_url.setAccessibleName(tr("api.proxy_url"))
        self.proxy_url.setFixedWidth(runtime.px(210))
        self.proxy_url.textChanged.connect(lambda _text: self._sync_proxy_fields())
        self.proxy_row.addWidget(self.proxy_url)

        self.proxy_save = primary_button(tr("api.proxy_save"), "check")
        self.proxy_save.clicked.connect(self._save_proxy)
        self.proxy_row.addWidget(self.proxy_save)
        self.proxy_check = secondary_button(tr("api.probe"), "activity")
        self.proxy_check.clicked.connect(self._probe_network)
        self.proxy_row.addWidget(self.proxy_check)

        self.proxy_state = QLabel("")
        self.proxy_state.setProperty("role", "faint")
        self.proxy_state.setWordWrap(True)
        layout.addWidget(self.proxy_state)
        self._sync_proxy_fields()

    def _on_proxy_mode(self, mode: str) -> None:
        if mode == "manual":
            self.proxy_url.setEnabled(True)
            if not self.proxy_url.text().strip():
                self.proxy_url.setFocus()
        else:
            self.proxy_url.setEnabled(False)
        self._sync_proxy_fields()

    def _load_proxy_fields(self) -> None:
        """Pull the saved network settings back into the widgets."""
        mode = str(self.context.settings.get("network.proxy_mode", "system") or "system")
        url = str(self.context.settings.get("network.proxy_url", "") or "")
        self.proxy_mode.set_value(mode)
        if self.proxy_url.text().strip() != url:
            self.proxy_url.setText(url)
        self.proxy_url.setEnabled(mode == "manual")
        self._sync_proxy_fields()

    def _sync_proxy_fields(self) -> None:
        """Show the proxy that would actually be used right now."""
        mode = self.proxy_mode.value or "system"
        try:
            choice = resolve_proxy(self._preview_options())
        except ValueError as exc:
            self.proxy_state.setText(tr("api.proxy_bad", error=str(exc)))
            self.proxy_state.setProperty("role", "danger")
            self.proxy_state.style().unpolish(self.proxy_state)
            self.proxy_state.style().polish(self.proxy_state)
            return
        self.proxy_state.setProperty("role", "faint")
        self.proxy_state.style().unpolish(self.proxy_state)
        self.proxy_state.style().polish(self.proxy_state)
        if choice.url:
            self.proxy_state.setText(
                tr("api.proxy_active", proxy=choice.label)
            )
        else:
            self.proxy_state.setText(
                tr("api.proxy_direct") if mode != "manual" else tr("api.proxy_manual_empty")
            )

    def _save_proxy(self) -> None:
        mode = self.proxy_mode.value or "system"
        raw = self.proxy_url.text().strip()
        if mode == "manual":
            try:
                raw = normalize_proxy(raw)
            except ValueError as exc:
                self.notify.emit(tr("api.proxy_bad", error=str(exc)), "error")
                return
            if not raw:
                self.notify.emit(tr("api.proxy_bad", error=tr("api.proxy_manual_empty")), "warning")
                return
        try:
            self.context.settings.update(
                {"network.proxy_mode": mode, "network.proxy_url": raw}
            )
        except AppError as exc:
            self.notify.emit(self._localized_error(exc), "error")
            return
        self.proxy_url.setText(str(self.context.settings.get("network.proxy_url", "")))
        self._sync_proxy_fields()
        self.notify.emit(tr("api.proxy_saved"), "success")

    def _probe_network(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.proxy_check.setEnabled(False)
        self.proxy_state.setText(tr("api.probing"))
        client = self.client()
        run_async(
            self,
            client.diagnose,
            on_success=self._on_probe_done,
            on_error=self._on_probe_error,
        )

    def _on_probe_done(self, result: object) -> None:
        self._busy = False
        self.proxy_check.setEnabled(True)
        assert isinstance(result, NetworkProbe)
        if result.ok:
            self.proxy_state.setText(
                tr("api.probe_ok", ms=result.elapsed_ms, detail=result.detail)
            )
            self.proxy_state.setProperty("role", "success")
        else:
            self.proxy_state.setText(
                tr(
                    "api.probe_failed",
                    stage=tr(f"api.stage_{result.stage.replace('-', '_')}"),
                    detail=result.detail,
                )
            )
            self.proxy_state.setProperty("role", "danger")
        self._restyle()

    def _on_probe_error(self, exc: Exception) -> None:
        self._busy = False
        self.proxy_check.setEnabled(True)
        self.proxy_state.setText(self._localized_error(exc))
        self.proxy_state.setProperty("role", "danger")
        self._restyle()

    def _localized_error(self, exc: Exception) -> str:
        """Translated sentence plus the technical detail, never a raw English line alone."""
        if not isinstance(exc, AppError):
            return str(exc)
        key = getattr(exc, "message_key", None)
        text = tr(key) if key and has_key(key) else exc.message
        details = (exc.details or "").strip()
        return f"{text} · {details}" if details else text

    def _build_catalogue_card(self) -> None:
        card, layout = self.card("api.models_card", "layers")
        top = QHBoxLayout()
        top.setSpacing(runtime.px(8))
        self.model_count = QLabel(tr("api.models_none"))
        self.model_count.setProperty("role", "muted")
        # The status line carries drag-and-drop file names and model counts; at
        # 1.5x it must wrap or shrink instead of pushing the search box and the
        # refresh button past the right edge.
        self.model_count.setWordWrap(True)
        self.model_count.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.model_count.setMinimumWidth(runtime.px(120))
        top.addWidget(self.model_count, 1)
        self.search = QLineEdit()
        self.search.setAccessibleName(tr("api.search_models"))
        self.search.setPlaceholderText(tr("api.search_models"))
        self.search.setMinimumWidth(runtime.px(110))
        self.search.setMaximumWidth(runtime.px(240))
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search.textChanged.connect(self._on_filter)
        top.addWidget(self.search)
        self.refresh_button = secondary_button(tr("api.refresh"), "refresh")
        self.refresh_button.clicked.connect(lambda: self._load_models(refresh=True))
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.models_host = QWidget()
        self.models_layout = QVBoxLayout(self.models_host)
        self.models_layout.setContentsMargins(0, 0, 0, 0)
        self.models_layout.setSpacing(runtime.px(6))
        layout.addWidget(self.models_host)
        self.models_empty = QLabel(tr("api.models_help"))
        self.models_empty.setProperty("role", "faint")
        self.models_empty.setWordWrap(True)
        layout.addWidget(self.models_empty)

        self.default_row = QHBoxLayout()
        self.default_row.setSpacing(runtime.px(8))
        layout.addLayout(self.default_row)
        self.default_label = field_label(tr("api.default_model"))
        self.default_row.addWidget(self.default_label)
        self.default_picker = SelectField(
            [],
            placeholder=tr("api.no_default"),
            searchable=True,
            search_placeholder=tr("picker.search"),
        )
        self.default_picker.value_changed.connect(self._choose_default)
        self.default_row.addWidget(self.default_picker)
        self.default_row.addStretch(1)

        # Some endpoints publish no usable catalogue (a reseller gateway, a
        # self-hosted proxy, or a /models route behind a path the app cannot
        # guess). Without a way to type the id, such a provider could be
        # configured but never used, so this row is always available.
        self.model_id_host = QWidget()
        self.model_id_row = FlowLayout(self.model_id_host, spacing=runtime.px(8))
        layout.addWidget(self.model_id_host)
        self.model_id_label = field_label(tr("api.model_id"))
        self.model_id_row.addWidget(self.model_id_label)
        self.model_id_input = QLineEdit()
        self.model_id_input.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        # An id is always Latin; left alignment keeps the caret where the text is.
        self.model_id_input.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.model_id_input.setPlaceholderText(tr("api.model_id_placeholder"))
        self.model_id_input.setAccessibleName(tr("api.model_id"))
        self.model_id_input.setMinimumWidth(runtime.px(220))
        self.model_id_input.setMaximumWidth(runtime.px(360))
        self.model_id_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_id_input.returnPressed.connect(self._use_typed_model)
        self.model_id_row.addWidget(self.model_id_input)
        self.model_id_button = secondary_button(tr("api.use_model"), "check")
        self.model_id_button.clicked.connect(self._use_typed_model)
        self.model_id_row.addWidget(self.model_id_button)
        self.model_id_hint = hint_label(tr("api.model_id_hint"))
        self.model_id_hint.setWordWrap(True)
        layout.addWidget(self.model_id_hint)

    def _use_typed_model(self) -> None:
        """Accept a model id typed by hand and make it the default."""
        typed = self.model_id_input.text().strip()
        problem = model_id_problem(typed)
        if problem is not None:
            self.model_id_hint.setText(tr(problem))
            self.model_id_hint.setProperty("role", "danger")
            self.model_id_hint.style().unpolish(self.model_id_hint)
            self.model_id_hint.style().polish(self.model_id_hint)
            return
        self.model_id_hint.setText(tr("api.model_id_hint"))
        self.model_id_hint.setProperty("role", "faint")
        self.model_id_hint.style().unpolish(self.model_id_hint)
        self.model_id_hint.style().polish(self.model_id_hint)
        # Keep it in this page's own picker even if the catalogue never
        # mentions it, so reopening the popup still offers what is in use.
        if all(model.id != typed for model in self._models):
            self._manual_models[typed] = ModelInfo(id=typed, name=typed, price_known=False)
            self._render_models()
        self.model_selected.emit(typed)
        self.model_id_input.clear()

    def _build_sampling_card(self) -> None:
        card, layout = self.collapsible_card(
            "api.sampling_card", "sliders", key="api.card.sampling", open_by_default=False
        )
        row = QHBoxLayout()
        row.setSpacing(runtime.px(14))
        self.temperature = QLineEdit(str(self.context.settings.get("ai.temperature", 0.7)))
        self.temperature.setFixedWidth(runtime.px(90))
        self.max_tokens = QLineEdit(str(self.context.settings.get("ai.max_tokens", 4096)))
        self.max_tokens.setFixedWidth(runtime.px(110))
        for label_key, field in (("api.temperature", self.temperature), ("api.max_tokens", self.max_tokens)):
            col = QVBoxLayout()
            col.setSpacing(runtime.px(3))
            col.addWidget(field_label(tr(label_key)))
            col.addWidget(field)
            row.addLayout(col)
        row.addStretch(1)
        save = primary_button(tr("api.save_defaults"), "check")
        save.clicked.connect(self._save_sampling)
        row.addWidget(save)
        layout.addLayout(row)
        layout.addWidget(hint_label(tr("api.sampling_hint")))
        self.sampling_status = QLabel("")
        self.sampling_status.setProperty("role", "success")
        self.sampling_status.hide()
        layout.addWidget(self.sampling_status)

    # ------------------------------------------------------------------- key
    def _refresh_key_state(self) -> None:
        ready = provider_has_key(self.provider, self.context.secrets)
        stored = has_stored_key(self.provider, self.context.secrets)
        masked = self._masked_key()
        self.key_label.setText(f"{tr('api.key_label')} — {self._provider_name()}")
        self.key_input.setPlaceholderText(self.provider.key_hint or "…")
        if stored:
            self.key_state.setText(tr("api.key_stored", key=masked))
            self.key_state.setProperty("role", "success")
        elif ready:
            # Usable without a key (a local server or an open gateway). Saying
            # "a key is stored: ''" here would be a lie.
            self.key_state.setText(tr("api.key_not_required"))
            self.key_state.setProperty("role", "muted")
        else:
            self.key_state.setText(tr("api.key_missing"))
            self.key_state.setProperty("role", "warning")
        self.key_state.style().unpolish(self.key_state)
        self.key_state.style().polish(self.key_state)
        while self.key_badge_layout.count():
            item = self.key_badge_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        if stored:
            self.key_badge_layout.addWidget(Badge(tr("api.configured"), "success"))
        elif ready:
            self.key_badge_layout.addWidget(Badge(tr("api.key_local_badge"), "muted"))
        else:
            self.key_badge_layout.addWidget(Badge(tr("api.not_configured"), "warning"))
        self.delete_key.setEnabled(
            bool(self.context.secrets.get_key(self.provider.id))
        )
        if hasattr(self, "test_button"):
            self.test_button.setEnabled(ready)
        self.key_input.clear()
        self._sync_key_button()
        self.key_input.setPlaceholderText(masked if stored else (self.provider.key_hint or "…"))
        self.save_key.setText(tr("api.replace_key") if stored else tr("api.save_key"))
        self.show_key.setEnabled(stored)
        if not stored:
            self.show_key.setChecked(False)

    def _masked_key(self) -> str:
        value = self.context.secrets.get_key(self.provider.id) or ""
        if len(value) <= 10:
            return "•" * len(value)
        return f"{value[:7]}…{value[-4:]}"

    def _toggle_visibility(self, visible: bool) -> None:
        self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.show_key.setText(tr("api.hide_key") if visible else tr("api.show_key"))

    def _sync_key_button(self) -> None:
        self.save_key.setEnabled(bool(self.key_input.text().strip()))

    def _save_key(self) -> None:
        value = self.key_input.text().strip()
        if not value:
            self._set_key_error(tr("api.key_empty"))
            return
        problem = key_problem(self.provider, value)
        if problem is not None:
            # The message never echoes the key back into the window or the log.
            # "wrong format" is the only check that depends on the provider's
            # prefix, so the sentence names it (sk-or-, sk-ant-, …).
            if problem == "api.key_format" and self.provider.key_prefix:
                self._set_key_error(tr("api.key_format_prefix", name=self._provider_name(), prefix=self.provider.key_prefix))
            else:
                self._set_key_error(tr(problem))
            return
        try:
            self.context.secrets.set_key(self.provider.id, value)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            logger.exception("secret_store_failed")
            self._set_key_error(tr("api.key_store_failed", error=str(exc)))
            return
        self._set_key_error("")
        self._refresh_key_state()
        self.context.activity.record(key="api.key_saved", kind="settings")
        self.notify.emit(tr("api.provider_key_saved", name=self._provider_name()), "success")
        # A stored key is not a verified key: fetch the catalogue to prove it.
        self._load_models(refresh=True)

    def _set_key_error(self, message: str) -> None:
        self.key_error.setText(message)
        self.key_error.setVisible(bool(message))

    def _delete_key(self) -> None:
        dialog = ConfirmDialog(
            self,
            tr("api.delete_title"),
            tr("api.delete_body"),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if not dialog.exec():
            return
        self.context.secrets.set_key(self.provider.id, "")
        self._models = []
        self._render_models()
        self._refresh_key_state()
        self.notify.emit(tr("api.key_deleted_toast"), "info")

    # --------------------------------------------------------------- network
    def client(self) -> ProviderClient:
        """A client for the selected provider, with that provider's own key."""
        return ProviderClient(
            lambda: self.context.secrets.get_key(self.provider.id),
            provider=self.provider.id,
            base_url=base_url_for(self.provider, self.context.settings),
            network=self._network_options(),
        )

    def _test_connection(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.test_button.setEnabled(False)
        self.test_result.setText(tr("api.testing"))
        self.test_result.setProperty("role", "muted")
        client = self.client()
        run_async(
            self,
            client.test_connection,
            on_success=self._on_test_done,
            on_error=self._on_test_error,
        )

    def _on_test_done(self, result: object) -> None:
        self._busy = False
        self.test_button.setEnabled(self.context.secrets.has_api_key())
        assert isinstance(result, ConnectionTest)
        if result.ok:
            self.test_result.setText(
                tr(
                    "api.provider_test_ok",
                    name=self._provider_name(),
                    ms=result.latency_ms,
                    count=result.model_count,
                )
            )
            self.test_result.setProperty("role", "success")
            self.context.activity.record(key="api.connected", kind="settings")
            self._load_models(refresh=True)
        else:
            self.test_result.setText(
                tr(
                    "api.test_failed",
                    error=self._localized_error_code(result.error_code, result.message),
                )
            )
            self.test_result.setToolTip(
                f"{result.message} · {result.stage or 'unknown'} · "
                f"{result.proxy or tr('api.proxy_none_short')}"
            )
            self.test_result.setProperty("role", "danger")
        self._restyle()

    def _localized_error_code(self, code: str, message: str) -> str:
        """Prefer the translated sentence for a known error code."""
        key = {
            "provider.timeout": "error.api_timeout",
            "provider.auth": "error.api_auth",
            "provider.credit": "error.api_credit",
            "provider.rate_limit": "error.api_rate",
            "network": "error.api_network",
            "network.unreachable": "error.api_network",
        }.get(code)
        if key and has_key(key):
            return tr(key)
        return message

    def _on_test_error(self, exc: Exception) -> None:
        self._busy = False
        self.test_button.setEnabled(self.context.secrets.has_api_key())
        message = self._localized_error(exc)
        self.test_result.setText(tr("api.test_failed", error=message))
        self.test_result.setToolTip(str(exc))
        self.test_result.setProperty("role", "danger")
        self._restyle()

    def _load_models(self, *, refresh: bool = False) -> None:
        if not provider_has_key(self.provider, self.context.secrets):
            self.model_count.setText(
                tr("api.models_need_key") if self.provider.key_required else tr("api.models_none")
            )
            return
        self.refresh_button.setEnabled(False)
        self.model_count.setText(tr("api.models_loading"))
        client = self.client()
        run_async(
            self,
            lambda: client.list_models(refresh=refresh),
            on_success=self._on_models,
            on_error=self._on_models_error,
        )

    def _on_models(self, models: object) -> None:
        self.refresh_button.setEnabled(True)
        assert isinstance(models, list)
        self._models = list(models)
        self.context.chat.set_models(self._models)
        self.context.settings.set("ai.last_model_sync", datetime.now().isoformat(timespec="seconds"))
        try:
            cache = models_cache(self.context.settings)
            cache[self.provider.id] = [model_to_dict(model) for model in self._models]
            self.context.settings.update({"ai.model_cache": cache})
        except AppError:
            logger.exception("model_cache_write_failed")
        self._render_models()
        self.models_updated.emit(self._models)
        if self._models:
            self.notify.emit(tn("api.models_loaded", len(self._models)), "success")

    def _on_models_error(self, exc: Exception) -> None:
        self.refresh_button.setEnabled(True)
        message = self._localized_error(exc)
        code = getattr(exc, "code", "")
        self.model_count.setText(tr("api.models_error", error=message))
        self.model_count.setToolTip(str(exc))
        self.model_count.setProperty("role", "danger")
        self.model_count.style().unpolish(self.model_count)
        self.model_count.style().polish(self.model_count)
        self.notify.emit(self._explain(code, str(exc)), "error")

    def _explain(self, code: str, message: str) -> str:
        mapping = {
            "provider.auth": "api.err_auth",
            "provider.credit": "api.err_credit",
            "provider.rate_limit": "api.err_rate",
            "provider.timeout": "api.err_timeout",
            "network": "api.err_network",
            "network.unreachable": "api.err_network",
        }
        key = mapping.get(code)
        return tr(key, error=message) if key else message

    # -------------------------------------------------------------- catalogue
    def _on_filter(self, text: str) -> None:
        self._filter = text.strip().casefold()
        self._render_models()

    def _all_models(self) -> list[ModelInfo]:
        """Catalogue plus any id typed by hand that the catalogue omits."""
        listed = {model.id for model in self._models}
        return [*self._models, *(model for key, model in self._manual_models.items() if key not in listed)]

    def _render_models(self) -> None:
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        current = str(self.context.settings.get("ai.default_model", ""))
        listed = {model.id for model in self._models}
        visible = [
            model
            for model in self._all_models()
            if not self._filter
            or self._filter in model.id.casefold()
            or self._filter in (model.name or "").casefold()
        ]
        for model in visible[:60]:
            row = ModelRow(
                model, current, manual=model.id in self._manual_models and model.id not in listed
            )
            row.chosen.connect(self.model_selected)
            self.models_layout.addWidget(row)
        everything = self._all_models()
        self.models_empty.setVisible(not everything or not visible)
        if everything:
            self.models_empty.setText(tr("api.models_no_match") if not visible else "")
            self.model_count.setText(
                tn("api.models_loaded_short", len(everything), shown=len(visible))
            )
        elif self.provider.id == "custom":
            self.models_empty.setText(tr("api.custom_models_note"))
        items = [(model.id, model.id) for model in self._all_models()]
        self.default_picker.set_items(items)
        if current:
            self.default_picker.set_value(current)
        self.default_picker.set_placeholder(tr("api.no_default"))
        choices = [
            Choice(
                model.id,
                model.name or model.id,
                detail=model.id,
                tags=model_tags(
                    model.context_length,
                    free=model.is_free(),
                    paid=model.is_paid(),
                    tools=model.supports_tools,
                    vision=model.supports_vision,
                ),
            )
            for model in visible[:400]
        ]
        self._choices = choices
        self.default_picker.set_choices(choices, current)

    def _choose_default(self, model_id: str) -> None:
        if model_id:
            self.model_selected.emit(model_id)

    def set_default_model(self, model_id: str) -> None:
        if model_id and model_id not in {model.id for model in self._models}:
            # A model chosen by hand must stay visible; otherwise the picker
            # shows "no model" while the app is happily using that id.
            self._manual_models[model_id] = ModelInfo(
                id=model_id, name=model_id, price_known=False
            )
        items = [(model.id, model.id) for model in self._all_models()]
        self.default_picker.set_items(items)
        self.default_picker.set_value(model_id)
        self._render_models()

    def set_models(self, models: list[ModelInfo]) -> None:
        self._models = list(models)
        self._render_models()

    def load_cached_models(self) -> None:
        """Show the cached catalogue for the selected provider immediately."""
        rows = cached_models(self.context.settings, self.provider.id)
        models: list[ModelInfo] = []
        for item in rows:
            model = model_from_dict(item) if isinstance(item, dict) else None
            if model is not None:
                models.append(model)
        if models:
            self._models = models
            self._render_models()

    # ---------------------------------------------------------------- sampling
    def _save_sampling(self) -> None:
        try:
            temperature = float(self.temperature.text().replace(",", "."))
            max_tokens = int(self.max_tokens.text() or 0)
            self.context.settings.update({"ai.temperature": temperature, "ai.max_tokens": max_tokens})
        except (ValueError, AppError) as exc:
            message = exc.message if isinstance(exc, AppError) else tr("api.invalid_number")
            self.sampling_status.setText(message)
            self.sampling_status.setProperty("role", "danger")
            self.sampling_status.show()
            return
        self.sampling_status.setText(tr("api.saved"))
        self.sampling_status.setProperty("role", "success")
        self.sampling_status.show()

    # --------------------------------------------------------------- visuals
    def _restyle(self) -> None:
        for label in self.findChildren(QLabel):
            label.style().unpolish(label)
            label.style().polish(label)

    def window_context(self, key: str, default: bool) -> bool:  # noqa: D102 - see PageShell
        stored = self.context.settings.get("ui.cards_open", {}) or {}
        if isinstance(stored, dict) and key in stored:
            return bool(stored[key])
        return default

    def remember_collapsed(self, key: str, is_open: bool) -> None:  # noqa: D102
        stored = self.context.settings.get("ui.cards_open", {}) or {}
        stored = dict(stored) if isinstance(stored, dict) else {}
        if stored.get(key) == is_open:
            return
        stored[key] = is_open
        self.context.settings.set("ui.cards_open", stored)

    def retranslate(self) -> None:
        super().retranslate()
        if self._models:
            self._render_models()
        self._refresh_key_state()
        self.default_label.setText(tr("api.default_model"))
        self.endpoint_label.setText(tr("api.base_url"))
        self.provider_label.setText(tr("api.provider_label"))
        self.base_url_label.setText(tr("api.base_url"))
        self.base_url_save.setText(tr("api.save_url"))
        self.model_id_label.setText(tr("api.model_id"))
        self.model_id_button.setText(tr("api.use_model"))
        self.model_id_input.setPlaceholderText(tr("api.model_id_placeholder"))
        self.model_id_hint.setText(tr("api.model_id_hint"))
        self.base_url_hint.setText(tr("api.base_url_hint"))
        self.provider_hint.setText(tr("api.provider_hint"))
        self.custom_name.setPlaceholderText(tr("api.custom_name_placeholder"))
        self.custom_url.setPlaceholderText(tr("api.custom_url_placeholder"))
        self.custom_add.setText(tr("api.custom_add"))
        self.custom_key_required.setText(tr("api.custom_key_required"))
        self.custom_protocol.set_items(
            [
                ("openai", tr("api.protocol_openai")),
                ("anthropic", tr("api.protocol_anthropic")),
                ("gemini", tr("api.protocol_gemini")),
            ]
        )
        self._render_custom_endpoints()
        self.provider_select.set_items(
            [
                (item.id, tr(f"provider.{item.id}") if has_key(f"provider.{item.id}") else item.name)
                for item in all_providers()
            ]
        )
        self._sync_provider_fields()
        self._refresh_key_state()
        self.proxy_mode.set_items(
            [
                ("system", tr("api.proxy_system")),
                ("manual", tr("api.proxy_manual")),
                ("off", tr("api.proxy_off")),
            ]
        )
        for widget, key in (
            (self.proxy_mode_label, "api.proxy_mode"),
            (self.proxy_url_label, "api.proxy_url"),
            (self.proxy_save, "api.proxy_save"),
            (self.proxy_check, "api.probe"),
            (self.proxy_hint, "api.proxy_hint"),
        ):
            widget.setText(tr(key))
        self._sync_proxy_fields()
        if hasattr(self, "network_note"):
            self.network_note.setText(tr("api.test_network_note"))
        self.test_result.setText(tr("api.test_idle") if not self._busy else tr("api.testing"))
        self.sampling_status.hide()

    def refresh(self) -> None:
        self._sync_provider_fields()
        self._refresh_key_state()
        self._load_proxy_fields()
        if not self._models:
            self.load_cached_models()
        if not self._models and provider_has_key(self.provider, self.context.secrets):
            self._load_models()
        else:
            self._render_models()
