"""OpenRouter connection page.

Everything on this screen talks to the real service through
:class:`myai.services.openrouter.OpenRouterClient`. When the network is
unavailable the page says so explicitly and keeps the key stored locally; it
never shows a fabricated model list or a fake "connected" state.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...i18n import tn, tr
from ...services.openrouter import ConnectionTest, ModelInfo, OpenRouterClient
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import SelectField
from ..widgets.foundation import Badge
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

    def __init__(self, model: ModelInfo, current: str, parent: QWidget | None = None) -> None:
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
        if model.is_free():
            return "$0"
        if not model.prompt_price and not model.completion_price:
            return "—"
        return f"${model.prompt_price:g} / ${model.completion_price:g}"


class ApiPage(PageShell):
    """Key management, connection test, live catalogue and sampling defaults."""

    model_selected = Signal(str)
    models_updated = Signal(list)
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("api.title", "api.subtitle", icon_name="key")
        self.context = context
        self._models: list[ModelInfo] = []
        self._busy = False
        self._filter = ""
        self._build()
        runtime.signals.changed.connect(lambda *_: self._restyle())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._build_key_card()
        self._build_test_card()
        self._build_catalogue_card()
        self._build_sampling_card()
        self._refresh_key_state()

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
        layout.addWidget(field_label(tr("api.key_label")))
        layout.addWidget(self.key_input)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(7))
        self.save_key = primary_button(tr("api.save_key"), "lock")
        self.save_key.clicked.connect(self._save_key)
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
        card, layout = self.card("api.test_card", "activity")
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

    def _build_catalogue_card(self) -> None:
        card, layout = self.card("api.models_card", "layers")
        top = QHBoxLayout()
        top.setSpacing(runtime.px(8))
        self.model_count = QLabel(tr("api.models_none"))
        self.model_count.setProperty("role", "muted")
        top.addWidget(self.model_count, 1)
        self.search = QLineEdit()
        self.search.setAccessibleName(tr("api.search_models"))
        self.search.setPlaceholderText(tr("api.search_models"))
        self.search.setFixedWidth(runtime.px(240))
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
        self.default_picker = SelectField([], placeholder=tr("api.no_default"))
        self.default_picker.value_changed.connect(self._choose_default)
        self.default_row.addWidget(self.default_picker)
        self.default_row.addStretch(1)

    def _build_sampling_card(self) -> None:
        card, layout = self.card("api.sampling_card", "sliders")
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
        has_key = self.context.secrets.has_api_key()
        masked = self._masked_key()
        if has_key:
            self.key_state.setText(tr("api.key_stored", key=masked))
            self.key_state.setProperty("role", "success")
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
        self.key_badge_layout.addWidget(
            Badge(tr("api.configured"), "success") if has_key else Badge(tr("api.not_configured"), "warning")
        )
        self.delete_key.setEnabled(has_key)
        if hasattr(self, "test_button"):
            self.test_button.setEnabled(has_key)
        self.key_input.clear()
        self.key_input.setPlaceholderText(masked if has_key else "sk-or-v1-…")
        self.save_key.setText(tr("api.replace_key") if has_key else tr("api.save_key"))
        if has_key:
            self.show_key.setEnabled(True)
        else:
            self.show_key.setEnabled(False)
            self.show_key.setChecked(False)

    def _masked_key(self) -> str:
        value = self.context.secrets.get_api_key() or ""
        if len(value) <= 10:
            return "•" * len(value)
        return f"{value[:7]}…{value[-4:]}"

    def _toggle_visibility(self, visible: bool) -> None:
        self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.show_key.setText(tr("api.hide_key") if visible else tr("api.show_key"))

    def _save_key(self) -> None:
        value = self.key_input.text().strip()
        if not value:
            self._set_key_error(tr("api.key_empty"))
            return
        if not value.startswith("sk-or-"):
            self._set_key_error(tr("api.key_format"))
            return
        try:
            self.context.secrets.set_api_key(value)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            logger.exception("secret_store_failed")
            self._set_key_error(tr("api.key_store_failed", error=str(exc)))
            return
        self._set_key_error("")
        self._refresh_key_state()
        self.context.activity.record(key="api.key_saved", kind="settings")
        self.notify.emit(tr("api.key_saved_toast"), "success")
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
        self.context.secrets.set_api_key("")
        self._models = []
        self._render_models()
        self._refresh_key_state()
        self.notify.emit(tr("api.key_deleted_toast"), "info")

    # --------------------------------------------------------------- network
    def client(self) -> OpenRouterClient:
        return OpenRouterClient(
            self.context.secrets.get_api_key,
            base_url=str(self.context.settings.get("ai.base_url", "https://openrouter.ai/api/v1")),
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
                tr("api.test_ok", ms=result.latency_ms, count=result.model_count)
            )
            self.test_result.setProperty("role", "success")
            self.context.activity.record(key="api.connected", kind="settings")
            self._load_models(refresh=True)
        else:
            self.test_result.setText(tr("api.test_failed", error=result.message))
            self.test_result.setProperty("role", "danger")
        self._restyle()

    def _on_test_error(self, exc: Exception) -> None:
        self._busy = False
        self.test_button.setEnabled(self.context.secrets.has_api_key())
        message = exc.message if isinstance(exc, AppError) else str(exc)
        self.test_result.setText(tr("api.test_failed", error=message))
        self.test_result.setProperty("role", "danger")
        self._restyle()

    def _load_models(self, *, refresh: bool = False) -> None:
        if not self.context.secrets.has_api_key():
            self.model_count.setText(tr("api.models_need_key"))
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
        self._render_models()
        self.models_updated.emit(self._models)
        if self._models:
            self.notify.emit(tn("api.models_loaded", len(self._models)), "success")

    def _on_models_error(self, exc: Exception) -> None:
        self.refresh_button.setEnabled(True)
        message = exc.message if isinstance(exc, AppError) else str(exc)
        code = getattr(exc, "code", "")
        self.model_count.setText(tr("api.models_error", error=message))
        self.model_count.setProperty("role", "danger")
        self.model_count.style().unpolish(self.model_count)
        self.model_count.style().polish(self.model_count)
        self.notify.emit(self._explain(code, message), "error")

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

    def _render_models(self) -> None:
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        current = str(self.context.settings.get("ai.default_model", ""))
        visible = [
            model
            for model in self._models
            if not self._filter
            or self._filter in model.id.casefold()
            or self._filter in (model.name or "").casefold()
        ]
        for model in visible[:60]:
            row = ModelRow(model, current)
            row.chosen.connect(self.model_selected)
            self.models_layout.addWidget(row)
        self.models_empty.setVisible(not self._models or not visible)
        if self._models:
            self.models_empty.setText(tr("api.models_no_match") if not visible else "")
            self.model_count.setText(
                tr("api.models_loaded_short", count=len(self._models), shown=len(visible))
            )
        items = [(model.id, model.id) for model in self._models]
        self.default_picker.set_items(items)
        if current:
            self.default_picker.set_value(current)
        self.default_picker.set_placeholder(tr("api.no_default"))

    def _choose_default(self, model_id: str) -> None:
        if model_id:
            self.model_selected.emit(model_id)

    def set_default_model(self, model_id: str) -> None:
        items = [(model.id, model.id) for model in self._models]
        self.default_picker.set_items(items)
        self.default_picker.set_value(model_id)
        self._render_models()

    def set_models(self, models: list[ModelInfo]) -> None:
        self._models = list(models)
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

    def retranslate(self) -> None:
        super().retranslate()
        if self._models:
            self._render_models()
        self._refresh_key_state()
        self.default_label.setText(tr("api.default_model"))
        self.endpoint_label.setText(tr("api.base_url"))
        if hasattr(self, "network_note"):
            self.network_note.setText(tr("api.test_network_note"))
        self.test_result.setText(tr("api.test_idle") if not self._busy else tr("api.testing"))
        self.sampling_status.hide()

    def refresh(self) -> None:
        self._refresh_key_state()
        self.endpoint_value.setText(str(self.context.settings.get("ai.base_url", "")))
        if not self._models and self.context.secrets.has_api_key():
            self._load_models()
        else:
            self._render_models()
