"""Settings: a real control surface, not a demo.

Every visible control writes to the validated settings registry; appearance and
language changes apply instantly.  Controls that belong to later phases are
disabled and labelled with their phase instead of being decorative.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.paths import AppPaths
from ...core.timeutil import format_bytes, format_datetime
from ...data.db import Database
from ...i18n import current_language, tr
from ...security.secrets import SecretStore
from ...services.backup import BackupService
from ...services.settings import SettingsService
from ...version import APP_NAME, BUILD_CHANNEL, PHASE, VERSION
from ..brand import LogoMark
from ..theme import ACCENTS, runtime
from ..theme.manager import ThemeManager
from ..widgets.buttons import AccentSwatch, NavButton, ThemePreview
from ..widgets.dialogs import ModalDialog
from ..widgets.fields import LanguageCard, SelectField, SettingRow, SliderRow, toggle_row
from ..widgets.foundation import Badge, IconCircle, Kbd

CATEGORIES = [
    ("general", "settings", "settings.cat_general", ""),
    ("appearance", "palette", "settings.cat_appearance", ""),
    ("language", "type", "settings.cat_language", ""),
    ("ai", "sparkles", "settings.cat_ai", "2"),
    ("memory", "database", "settings.cat_memory", "2"),
    ("agent", "wrench", "settings.cat_agent", ""),
    ("data", "hard-drive", "settings.cat_data", ""),
    ("shortcuts", "command", "settings.cat_shortcuts", ""),
    ("about", "info", "settings.cat_about", ""),
]


class SettingsDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget,
        settings: SettingsService,
        theme_manager: ThemeManager,
        paths: AppPaths,
        db: Database,
        secrets: SecretStore,
        backup: BackupService,
        initial: str = "general",
    ) -> None:
        super().__init__(parent, tr("settings.title"), tr("settings.subtitle"), width=920)
        self._settings = settings
        self._theme = theme_manager
        self._paths = paths
        self._db = db
        self._secrets = secrets
        self._backup = backup
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, NavButton] = {}
        self._current = "general"
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(120)
        self._scale_timer.timeout.connect(self._apply_scale)
        self._pending_scale = 1.0
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.status.setText(""))
        self.set_fixed_size(runtime.px(980), runtime.px(700))
        self._build_layout()
        self._select(initial if initial in {item[0] for item in CATEGORIES} else "general")
        self._unsubscribe = settings.subscribe(self._on_settings_changed)

    # ------------------------------------------------------------------ layout
    def _build_layout(self) -> None:
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        nav_frame = QFrame()
        nav_frame.setObjectName("SettingsNav")
        side = "left" if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else "right"
        nav_frame.setStyleSheet(
            f"QFrame#SettingsNav {{ background: {runtime.theme().color('surface_2')};"
            f" border-{side}: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(12)}px; }}"
        )
        nav_frame.setFixedWidth(runtime.px(248))
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(runtime.px(12), runtime.px(12), runtime.px(12), runtime.px(12))
        nav_layout.setSpacing(runtime.px(3))
        for key, icon_name, label_key, phase in CATEGORIES:
            button = NavButton(tr(label_key), icon_name, badge=str(phase) if phase else "")
            if phase:
                button.setToolTip(tr("settings.available_phase", phase=phase))
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, k=key: self._select(k))
            nav_layout.addWidget(button)
            self._nav_buttons[key] = button
        nav_layout.addStretch(1)
        hint = QLabel(tr("settings.subtitle"))
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: {runtime.px(9)}px; padding: {runtime.px(6)}px;")
        nav_layout.addWidget(hint)
        content_layout.addWidget(nav_frame)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(runtime.px(24), runtime.px(16), runtime.px(24), runtime.px(12))
        right_layout.setSpacing(runtime.px(10))
        self.page_title = QLabel("")
        self.page_title.setProperty("role", "h2")
        right_layout.addWidget(self.page_title)
        self.page_subtitle = QLabel("")
        self.page_subtitle.setProperty("role", "muted")
        self.page_subtitle.setWordWrap(True)
        right_layout.addWidget(self.page_subtitle)
        self.page_stack = QStackedWidget()
        right_layout.addWidget(self.page_stack, 1)
        content_layout.addWidget(right, 1)
        self.body.addWidget(content, 1)

        footer = QHBoxLayout()
        footer.setSpacing(runtime.px(8))
        self.status = QLabel("")
        self.status.setProperty("role", "success")
        footer.addWidget(self.status)
        footer.addStretch(1)
        # NOTE: never name a widget attribute ``done``/``accept``/``reject`` on
        # a QDialog: Qt calls those virtual methods and would find the widget.
        self.close_button = QPushButton(tr("dialog.close"))
        self.close_button.setProperty("variant", "primary")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        self.footer.addLayout(footer)

    # --------------------------------------------------------------- category
    def _select(self, key: str) -> None:
        self._current = key
        for nav_key, button in self._nav_buttons.items():
            button.setChecked(nav_key == key)
        meta = next((item for item in CATEGORIES if item[0] == key), CATEGORIES[0])
        self.page_title.setText(tr(meta[2]))
        self.page_subtitle.setText(tr(f"settings.{key}_subtitle"))
        if key not in self._pages:
            self._pages[key] = self._build_page(key)
            self.page_stack.addWidget(self._pages[key])
        self.page_stack.setCurrentWidget(self._pages[key])

    def _rebuild_pages(self) -> None:
        current = self._current
        while self.page_stack.count():
            item = self.page_stack.widget(0)
            self.page_stack.removeWidget(item)
            item.deleteLater()
        self._pages.clear()
        self._select(current)

    def _build_page(self, key: str) -> QWidget:
        builder: Callable[[], QWidget] = {
            "general": self._page_general,
            "appearance": self._page_appearance,
            "language": self._page_language,
            "ai": self._page_ai,
            "memory": self._page_memory,
            "agent": self._page_agent,
            "data": self._page_data,
            "shortcuts": self._page_shortcuts,
            "about": self._page_about,
        }[key]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = builder()
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, runtime.px(6), runtime.px(12), runtime.px(10))
        layout.setSpacing(runtime.px(9))
        layout.addWidget(inner)
        layout.addStretch(1)
        scroll.setWidget(wrap)
        return scroll

    def _column(self) -> tuple[QWidget, QVBoxLayout]:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(9))
        return widget, layout

    def _flash(self, text: str, tone: str = "success") -> None:
        self.status.setText(text)
        self.status.setProperty("role", tone)
        from ..widgets.foundation import repolish

        repolish(self.status)
        self._status_timer.start(3200)

    # ------------------------------------------------------------------ pages
    def _page_general(self) -> QWidget:
        widget, layout = self._column()
        layout.addWidget(
            toggle_row(
                tr("settings.confirm_delete"),
                tr("settings.confirm_delete_hint"),
                bool(self._settings.get("ui.confirm_delete")),
                lambda value: self._write("ui.confirm_delete", value),
            )
        )
        layout.addWidget(
            toggle_row(
                tr("settings.autosave"),
                tr("settings.autosave_hint"),
                bool(self._settings.get("ui.editor_autosave")),
                lambda value: self._write("ui.editor_autosave", value),
                badge_text=tr("settings.available_phase", phase=3),
            )
        )
        start = SelectField(
            [("chat", tr("settings.start_new")), ("last", tr("settings.start_last"))],
            placeholder=tr("settings.start_view"),
        )
        start.set_value(str(self._settings.get("ui.start_view", "chat")))
        start.value_changed.connect(lambda value: self._write("ui.start_view", value))
        layout.addWidget(
            SettingRow(
                tr("settings.start_view"),
                tr("settings.start_view_hint"),
                start,
            )
        )
        layout.addSpacing(runtime.px(4))
        reset = QPushButton(tr("settings.restore_defaults"))
        reset.setProperty("variant", "ghost")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset_defaults)
        layout.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        return widget

    def _page_appearance(self) -> QWidget:
        widget, layout = self._column()
        layout.addWidget(self._label(tr("settings.theme")))
        grid = QGridLayout()
        grid.setSpacing(runtime.px(8))
        current_theme = str(self._settings.get("ui.theme", "midnight"))
        self.theme_previews: dict[str, ThemePreview] = {}
        for index, (key, label_key) in enumerate(
            [
                ("midnight", "settings.theme_dark"),
                ("dawn", "settings.theme_light"),
                ("aurora", "settings.theme_midnight"),
                ("system", "settings.theme_system"),
            ]
        ):
            preview = ThemePreview(key, tr(label_key))
            preview.setChecked(key == current_theme)
            preview.clicked.connect(lambda _=False, k=key: self._choose_theme(k))
            grid.addWidget(preview, index // 2, index % 2)
            self.theme_previews[key] = preview
        layout.addLayout(grid)

        layout.addWidget(self._label(tr("settings.accent")))
        accent_row = QHBoxLayout()
        accent_row.setSpacing(runtime.px(8))
        self.accent_swatches: dict[str, AccentSwatch] = {}
        current_accent = str(self._settings.get("ui.accent", "azure"))
        for key in ACCENTS:
            swatch = AccentSwatch(key)
            swatch.setChecked(key == current_accent)
            swatch.clicked.connect(lambda _=False, k=key: self._choose_accent(k))
            accent_row.addWidget(swatch)
            self.accent_swatches[key] = swatch
        accent_row.addStretch(1)
        layout.addLayout(accent_row)
        accent_hint = QLabel(tr("settings.accent_hint"))
        accent_hint.setProperty("role", "faint")
        accent_hint.setWordWrap(True)
        layout.addWidget(accent_hint)

        self.slider = SliderRow(0.85, 1.40, float(self._settings.get("ui.font_scale", 1.0)), 0.05)
        self.slider.value_changed.connect(self._queue_scale)
        layout.addWidget(SettingRow(tr("settings.font_scale"), tr("settings.scale_hint"), self.slider))
        preview = QLabel(tr("settings.language_preview_text"))
        preview.setWordWrap(True)
        preview.setObjectName("FontScalePreview")
        preview.setStyleSheet(
            f"background: {runtime.theme().color('surface_2')}; border-radius: {runtime.px(9)}px;"
            f" padding: {runtime.px(10)}px; font-size: {round(15 * self._scale())}px;"
        )
        layout.addWidget(preview)
        layout.addWidget(
            toggle_row(
                tr("settings.reduce_motion"),
                tr("settings.reduce_motion_hint"),
                bool(self._settings.get("ui.reduce_motion")),
                lambda value: self._write("ui.reduce_motion", value),
            )
        )
        return widget

    def _page_language(self) -> QWidget:
        widget, layout = self._column()
        row = QHBoxLayout()
        row.setSpacing(runtime.px(8))
        current = str(self._settings.get("ui.language", "fa"))
        fa = LanguageCard("fa", "فارسی", tr("settings.language_persian"), tr("settings.language_preview_text"))
        fa.setChecked(current == "fa")
        fa.clicked.connect(lambda: self._choose_language("fa"))
        row.addWidget(fa)
        en = LanguageCard("en", "English", tr("settings.language_english"), tr("settings.language_preview_text"))
        en.setChecked(current == "en")
        en.clicked.connect(lambda: self._choose_language("en"))
        row.addWidget(en)
        layout.addLayout(row)
        hint = QLabel(tr("settings.language_hint"))
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(self._label(tr("settings.language_preview")))
        preview = QFrame()
        preview.setProperty("panel", "card")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(runtime.px(16), runtime.px(14), runtime.px(16), runtime.px(14))
        title = QLabel(tr("chat.welcome_title"))
        title.setProperty("role", "h2")
        preview_layout.addWidget(title)
        body = QLabel(tr("chat.welcome_sub"))
        body.setProperty("role", "muted")
        body.setWordWrap(True)
        preview_layout.addWidget(body)
        layout.addWidget(preview)
        return widget

    def _locked_page(self, phase: int, title: str, body: str, items: list[tuple[str, str]]) -> QWidget:
        widget, layout = self._column()
        card = QFrame()
        card.setProperty("panel", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(runtime.px(20), runtime.px(18), runtime.px(20), runtime.px(18))
        card_layout.setSpacing(runtime.px(9))
        head = QHBoxLayout()
        head.addWidget(IconCircle("lock", "warning", 38))
        title_label = QLabel(title)
        title_label.setProperty("role", "h2")
        head.addWidget(title_label)
        head.addStretch(1)
        head.addWidget(Badge(tr("settings.available_phase", phase=phase), "warning"))
        card_layout.addLayout(head)
        description = QLabel(body)
        description.setProperty("role", "muted")
        description.setWordWrap(True)
        card_layout.addWidget(description)
        for icon_name, text in items:
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(runtime.icons().px(icon_name, 14, "muted"))
            row.addWidget(icon_label)
            label = QLabel(text)
            label.setProperty("role", "muted")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            card_layout.addLayout(row)
        layout.addWidget(card)
        return widget

    def _page_ai(self) -> QWidget:
        widget, layout = self._column()
        card = QFrame()
        card.setProperty("panel", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(runtime.px(18), runtime.px(16), runtime.px(18), runtime.px(16))
        card_layout.setSpacing(runtime.px(10))
        head = QHBoxLayout()
        title = QLabel(tr("settings.provider"))
        title.setProperty("role", "h3")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(Badge(tr("settings.available_phase", phase=2), "warning"))
        card_layout.addLayout(head)
        key_row = QHBoxLayout()
        key_input = QLineEdit()
        key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_input.setPlaceholderText("sk-or-v1-…")
        key_input.setEnabled(False)
        key_row.addWidget(key_input, 1)
        save = QPushButton(tr("settings.save_key"))
        save.setEnabled(False)
        key_row.addWidget(save)
        card_layout.addLayout(key_row)
        hint = QLabel(tr("settings.api_key_hint"))
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)
        stored = QLabel(
            f"{tr('inspector.configured')}: {self._secrets.status()['count']} · {self._secrets.status()['backend']}"
        )
        stored.setProperty("role", "faint")
        card_layout.addWidget(stored)
        layout.addWidget(card)
        layout.addWidget(
            self._locked_page(
                2,
                tr("settings.models"),
                tr("chat.offline_hint"),
                [
                    ("key", "Encrypted key storage is ready (DPAPI / Fernet)."),
                    ("refresh", "Live model catalogue and capability detection."),
                    ("activity", "Streaming, cancellation and token statistics."),
                ],
            )
        )
        return widget

    def _page_memory(self) -> QWidget:
        return self._locked_page(
            2,
            tr("settings.memory_enabled"),
            tr("inspector.no_memory_hint"),
            [
                ("database", "Global and per-conversation memory with summaries."),
                ("search", "Search, edit and export what the assistant remembers."),
                ("shield", "Explicit control over what may be written to memory."),
            ],
        )

    def _page_agent(self) -> QWidget:
        from ...services.tools import ToolContext, registry

        widget, layout = self._column()

        # 1. Gates -------------------------------------------------------
        card = QFrame()
        card.setProperty("panel", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(runtime.px(6), runtime.px(6), runtime.px(6), runtime.px(6))
        card_layout.setSpacing(runtime.px(2))
        head = QHBoxLayout()
        head.setContentsMargins(runtime.px(10), runtime.px(6), runtime.px(10), runtime.px(4))
        title = QLabel(tr("settings.agent_permissions"))
        title.setProperty("role", "h3")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(Badge(tr("settings.done_phase", phase=4), "success"))
        card_layout.addLayout(head)
        card_layout.addWidget(
            toggle_row(
                tr("settings.agent_confirm"),
                tr("settings.agent_confirm_hint"),
                bool(self._settings.get("agent.require_confirmation", True)),
                lambda value: self._write("agent.require_confirmation", bool(value)),
            )
        )
        card_layout.addWidget(
            toggle_row(
                tr("settings.agent_network"),
                tr("settings.agent_network_hint"),
                bool(self._settings.get("agent.allow_network", False)),
                self._set_agent_network,
            )
        )
        steps = SelectField(
            [("4", "4"), ("8", "8"), ("12", "12"), ("20", "20"), ("50", "50")],
            placeholder="12",
            compact=True,
        )
        steps.set_value(str(int(self._settings.get("agent.max_steps", 12) or 12)))
        steps.value_changed.connect(lambda value: self._write("agent.max_steps", int(value)))
        card_layout.addWidget(
            SettingRow(tr("settings.agent_steps"), tr("settings.agent_steps_hint"), steps)
        )
        layout.addWidget(card)

        # 2. Network credentials ----------------------------------------
        cred_card = QFrame()
        cred_card.setProperty("panel", "card")
        cred_layout = QVBoxLayout(cred_card)
        cred_layout.setContentsMargins(runtime.px(16), runtime.px(14), runtime.px(16), runtime.px(14))
        cred_layout.setSpacing(runtime.px(8))

        search_title = QLabel(tr("settings.agent_search_url"))
        search_title.setProperty("role", "h3")
        cred_layout.addWidget(search_title)
        search_row = QHBoxLayout()
        search_row.setSpacing(runtime.px(8))
        self.agent_search_input = QLineEdit()
        self.agent_search_input.setPlaceholderText("https://searx.example/search")
        self.agent_search_input.setText(str(self._settings.get("web.search_url", "") or ""))
        self.agent_search_input.setClearButtonEnabled(True)
        search_row.addWidget(self.agent_search_input, 1)
        save_search = QPushButton(tr("settings.agent_save"))
        save_search.setProperty("variant", "secondary")
        save_search.setProperty("buttonsize", "sm")
        save_search.clicked.connect(
            lambda: self._write("web.search_url", self.agent_search_input.text().strip())
        )
        search_row.addWidget(save_search)
        cred_layout.addLayout(search_row)
        search_hint = QLabel(tr("settings.agent_search_url_hint"))
        search_hint.setProperty("role", "faint")
        search_hint.setWordWrap(True)
        cred_layout.addWidget(search_hint)

        token_title = QLabel(tr("settings.agent_github_token"))
        token_title.setProperty("role", "h3")
        cred_layout.addWidget(token_title)
        token_row = QHBoxLayout()
        token_row.setSpacing(runtime.px(8))
        self.agent_token_input = QLineEdit()
        self.agent_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.agent_token_input.setPlaceholderText("ghp_…")
        token_row.addWidget(self.agent_token_input, 1)
        save_token = QPushButton(tr("settings.agent_save"))
        save_token.setProperty("variant", "secondary")
        save_token.setProperty("buttonsize", "sm")
        save_token.clicked.connect(self._save_github_token)
        token_row.addWidget(save_token)
        clear_token = QPushButton(tr("settings.agent_clear_token"))
        clear_token.setProperty("variant", "ghost")
        clear_token.setProperty("buttonsize", "sm")
        clear_token.clicked.connect(self._clear_github_token)
        token_row.addWidget(clear_token)
        cred_layout.addLayout(token_row)
        self.agent_token_state = QLabel("")
        self.agent_token_state.setProperty("role", "faint")
        cred_layout.addWidget(self.agent_token_state)
        token_hint = QLabel(tr("settings.agent_github_token_hint"))
        token_hint.setProperty("role", "faint")
        token_hint.setWordWrap(True)
        cred_layout.addWidget(token_hint)
        layout.addWidget(cred_card)

        # 3. What actually works on this machine -------------------------
        avail_card = QFrame()
        avail_card.setProperty("panel", "card")
        avail_layout = QVBoxLayout(avail_card)
        avail_layout.setContentsMargins(runtime.px(16), runtime.px(14), runtime.px(16), runtime.px(14))
        avail_layout.setSpacing(runtime.px(7))
        avail_head = QHBoxLayout()
        avail_title = QLabel(tr("settings.agent_availability"))
        avail_title.setProperty("role", "h3")
        avail_head.addWidget(avail_title)
        avail_head.addStretch(1)
        avail_layout.addLayout(avail_head)
        avail_hint = QLabel(tr("settings.agent_availability_hint"))
        avail_hint.setProperty("role", "faint")
        avail_hint.setWordWrap(True)
        avail_layout.addWidget(avail_hint)

        from ...i18n import tr as translate

        context = ToolContext(settings=self._settings, secrets=self._secrets)
        for spec in registry().specs():
            found = spec.reason_key(context)
            if found is None:
                reason = None
            else:
                reason_key, params = found
                template = translate(reason_key)
                try:
                    reason = template.format(**params) if params else template
                except (KeyError, IndexError):
                    reason = template
            row = QHBoxLayout()
            row.setSpacing(runtime.px(8))
            icon = QLabel()
            icon.setPixmap(runtime.icons().px("check" if reason is None else "lock", 12,
                                             "accent" if reason is None else "muted"))
            row.addWidget(icon)
            name = QLabel(tr(spec.label_key) if spec.label_key else spec.id)
            name.setProperty("role", "muted")
            row.addWidget(name)
            if reason is None:
                row.addStretch(1)
                row.addWidget(Badge(tr("settings.agent_ready"), "success"))
            else:
                detail = QLabel(reason)
                detail.setProperty("role", "faint")
                detail.setWordWrap(True)
                row.addWidget(detail, 1)
                row.addWidget(Badge(tr("settings.agent_unavailable"), "muted"))
            avail_layout.addLayout(row)
        layout.addWidget(avail_card)
        self._refresh_github_state()
        return widget

    # ------------------------------------------------------- agent helpers
    def _set_agent_network(self, value: bool) -> None:
        self._write("agent.allow_network", bool(value))
        if value and not str(self._settings.get("web.search_url", "") or "").strip():
            self._flash(tr("settings.agent_network_still_blocked"), "warning")

    def _save_github_token(self) -> None:
        token = self.agent_token_input.text().strip()
        if not token:
            self._flash(tr("settings.agent_token_empty"), "warning")
            return
        try:
            self._secrets.set("github_token", token)
        except Exception as exc:  # noqa: BLE001
            self._flash(str(exc), "danger")
            return
        self.agent_token_input.clear()
        self._refresh_github_state()
        self._flash(tr("settings.agent_token_saved"), "success")

    def _clear_github_token(self) -> None:
        removed = self._secrets.delete("github_token")
        self._refresh_github_state()
        self._flash(
            tr("settings.agent_token_removed") if removed else tr("settings.agent_token_absent"),
            "success" if removed else "warning",
        )

    def _refresh_github_state(self) -> None:
        stored = self._secrets.has("github_token")
        self.agent_token_state.setText(
            tr("settings.agent_token_stored") if stored else tr("settings.agent_token_missing")
        )
        self.agent_token_state.setProperty("role", "success" if stored else "faint")

    def _page_data(self) -> QWidget:
        widget, layout = self._column()
        path_row = QFrame()
        path_row.setObjectName("SettingRow")
        path_layout = QVBoxLayout(path_row)
        path_layout.setContentsMargins(runtime.px(14), runtime.px(11), runtime.px(12), runtime.px(11))
        path_layout.setSpacing(runtime.px(6))
        head = QHBoxLayout()
        title = QLabel(tr("settings.open_data_folder"))
        title.setProperty("role", "h3")
        head.addWidget(title)
        head.addStretch(1)
        open_button = QPushButton(tr("settings.open"))
        open_button.setProperty("variant", "secondary")
        open_button.setProperty("buttonsize", "sm")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._open_data_folder)
        head.addWidget(open_button)
        path_layout.addLayout(head)
        path_label = QLabel(str(self._paths.home))
        path_label.setProperty("role", "mono")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_layout.addWidget(path_label)
        layout.addWidget(path_row)

        stats = QFrame()
        stats.setProperty("panel", "card")
        stats_layout = QVBoxLayout(stats)
        stats_layout.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(12))
        counts = self._db.counts()
        for label, value in [
            (tr("inspector.database"), f"{format_bytes(self._db.file_size())} · v{self._db.schema_version()}"),
            (tr("nav.chats"), str(counts.get("conversations", 0))),
            (tr("inspector.messages"), str(counts.get("messages", 0))),
        ]:
            row = QHBoxLayout()
            key = QLabel(label)
            key.setProperty("role", "faint")
            row.addWidget(key)
            row.addStretch(1)
            val = QLabel(value)
            val.setProperty("role", "mono")
            row.addWidget(val)
            stats_layout.addLayout(row)
        layout.addWidget(stats)

        backup_card = QFrame()
        backup_card.setProperty("panel", "card")
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(runtime.px(14), runtime.px(13), runtime.px(14), runtime.px(13))
        backup_layout.setSpacing(runtime.px(8))
        head = QHBoxLayout()
        title = QLabel(tr("settings.backup_now"))
        title.setProperty("role", "h3")
        head.addWidget(title)
        head.addStretch(1)
        self.backup_button = QPushButton(tr("settings.backup_now"))
        self.backup_button.setProperty("variant", "secondary")
        self.backup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.backup_button.clicked.connect(self._create_backup)
        head.addWidget(self.backup_button)
        backup_layout.addLayout(head)
        hint = QLabel(tr("settings.data_hint"))
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        backup_layout.addWidget(hint)
        self.backups_list = QVBoxLayout()
        self.backups_list.setSpacing(runtime.px(5))
        backup_layout.addLayout(self.backups_list)
        restore_row = QHBoxLayout()
        self.restore_button = QPushButton(tr("settings.restore"))
        self.restore_button.setEnabled(False)
        self.restore_button.setToolTip(tr("settings.available_phase", phase=5))
        restore_row.addWidget(self.restore_button)
        restore_row.addWidget(Badge(tr("settings.available_phase", phase=5), "outline"))
        restore_row.addStretch(1)
        retention = SelectField(
            [("5", "5"), ("10", "10"), ("20", "20")],
            placeholder="10",
            compact=True,
        )
        retention.set_value(str(self._settings.get("data.backups_to_keep", 10)))
        retention.value_changed.connect(lambda value: self._write("data.backups_to_keep", int(value)))
        restore_row.addWidget(QLabel(tr("settings.backup_keep")))
        restore_row.addWidget(retention)
        backup_layout.addLayout(restore_row)
        layout.addWidget(backup_card)
        self._refresh_backups()
        return widget

    def _page_shortcuts(self) -> QWidget:
        widget, layout = self._column()
        rows = [
            ("Ctrl+N", "settings.shortcut_new_chat"),
            ("Ctrl+K", "settings.shortcut_search"),
            ("Ctrl+Shift+C", "settings.shortcut_code"),
            ("Esc", "settings.shortcut_stop"),
            ("Ctrl+,", "settings.shortcut_settings"),
        ]
        card = QFrame()
        card.setProperty("panel", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(12))
        card_layout.setSpacing(runtime.px(9))
        for shortcut, key in rows:
            row = QHBoxLayout()
            label = QLabel(tr(key))
            label.setProperty("role", "muted")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(Kbd(shortcut))
            card_layout.addLayout(row)
        layout.addWidget(card)
        hint = QLabel(tr("settings.shortcuts_hint"))
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return widget

    def _page_about(self) -> QWidget:
        widget, layout = self._column()
        hero = QFrame()
        hero.setProperty("panel", "card")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(runtime.px(18), runtime.px(16), runtime.px(18), runtime.px(16))
        hero_layout.setSpacing(runtime.px(14))
        hero_layout.addWidget(LogoMark(48))
        text_wrap = QVBoxLayout()
        text_wrap.setSpacing(runtime.px(2))
        name = QLabel(APP_NAME)
        name.setProperty("role", "h2")
        text_wrap.addWidget(name)
        tagline = QLabel(tr("dialog.about_body"))
        tagline.setProperty("role", "muted")
        tagline.setWordWrap(True)
        text_wrap.addWidget(tagline)
        hero_layout.addLayout(text_wrap, 1)
        layout.addWidget(hero)

        info = QFrame()
        info.setProperty("panel", "card")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(12))
        info_layout.setSpacing(runtime.px(6))
        from PySide6 import QtCore

        rows = [
            (tr("settings.about_version"), VERSION),
            (tr("settings.about_phase"), f"{tr('placeholder.phase_badge', phase=PHASE)} · {BUILD_CHANNEL}"),
            (tr("settings.about_python"), f"{platform.python_version()}"),
            (tr("settings.about_qt"), QtCore.qVersion()),
            (tr("settings.about_database"), f"SQLite · schema v{self._db.schema_version()}"),
            (tr("settings.about_licenses"), "Inter (OFL), Vazirmatn (OFL), Qt (LGPLv3)"),
        ]
        for label_text, value in rows:
            row = QHBoxLayout()
            key = QLabel(label_text)
            key.setProperty("role", "faint")
            row.addWidget(key)
            row.addStretch(1)
            val = QLabel(value)
            val.setProperty("role", "mono")
            val.setWordWrap(True)
            row.addWidget(val, 0)
            info_layout.addLayout(row)
        layout.addWidget(info)
        note = QLabel(tr("settings.about_help"))
        note.setProperty("role", "faint")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        copy = QPushButton(tr("error.report"))
        copy.setProperty("variant", "secondary")
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.clicked.connect(self._copy_diagnostics)
        buttons.addWidget(copy)
        logs = QPushButton(tr("settings.open_logs"))
        logs.setProperty("variant", "ghost")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._paths.logs_dir))))
        buttons.addWidget(logs)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    # ----------------------------------------------------------------- actions
    def _write(self, key: str, value) -> None:  # noqa: ANN001
        try:
            self._settings.set(key, value)
            self._flash(tr("settings.saved"))
        except Exception as exc:  # noqa: BLE001
            self._flash(str(exc), "danger")

    def _choose_theme(self, key: str) -> None:
        for theme_key, preview in self.theme_previews.items():
            preview.setChecked(theme_key == key)
            preview.update()
        self._write("ui.theme", key)

    def _choose_accent(self, key: str) -> None:
        for accent_key, swatch in self.accent_swatches.items():
            swatch.setChecked(accent_key == key)
            swatch.update()
        self._write("ui.accent", key)

    def _choose_language(self, code: str) -> None:
        self._write("ui.language", code)

    def _queue_scale(self, value: float) -> None:
        self._pending_scale = round(value, 2)
        self._scale_timer.start()

    def _apply_scale(self) -> None:
        self._write("ui.font_scale", self._pending_scale)
        QTimer.singleShot(0, self._rebuild_pages)

    def _reset_defaults(self) -> None:
        self._settings.reset_all()
        self._flash(tr("settings.saved"))
        self.retranslate()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._paths.home)))

    def _create_backup(self) -> None:
        self.backup_button.setEnabled(False)
        self.backup_button.setText(tr("state.loading"))
        QGuiApplication.processEvents()
        try:
            info = self._backup.create_backup()
            self._flash(tr("settings.backup_done", name=info.display_name), "success")
            self._refresh_backups()
        except Exception as exc:  # noqa: BLE001
            self._flash(str(exc), "danger")
        finally:
            self.backup_button.setEnabled(True)
            self.backup_button.setText(tr("settings.backup_now"))

    def _refresh_backups(self) -> None:
        while self.backups_list.count():
            item = self.backups_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        backups = self._backup.list_backups()
        if not backups:
            empty = QLabel(tr("settings.no_backups"))
            empty.setProperty("role", "faint")
            self.backups_list.addWidget(empty)
            return
        for info in backups[:4]:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            name = QLabel(info.display_name)
            name.setProperty("role", "mono")
            row_layout.addWidget(name, 1)
            meta = QLabel(f"{format_datetime(info.created_at, current_language())} · {format_bytes(info.size_bytes)}")
            meta.setProperty("role", "faint")
            row_layout.addWidget(meta)
            self.backups_list.addWidget(row)

    def _copy_diagnostics(self) -> None:
        from PySide6 import QtCore

        text = (
            f"{APP_NAME} {VERSION} · phase {PHASE}\n"
            f"Python {platform.python_version()} · Qt {QtCore.qVersion()} · {sys.platform}\n"
            f"Database schema v{self._db.schema_version()} · {self._paths.db_file}\n"
            f"Logs: {self._paths.logs_dir}"
        )
        QGuiApplication.clipboard().setText(text)
        self._flash(tr("toast.copied"), "success")

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    def _scale(self) -> float:
        return float(runtime.scale())

    # ------------------------------------------------------------------- i18n
    def _on_settings_changed(self, changes: dict) -> None:
        if "ui.language" in changes:
            self.retranslate()
        elif {"ui.theme", "ui.accent"} & set(changes):
            QTimer.singleShot(0, self._rebuild_pages)
        elif "ui.font_scale" in changes:
            QTimer.singleShot(0, self._rebuild_pages)

    def retranslate(self) -> None:
        self.title_label.setText(tr("settings.title"))
        self.subtitle_label.setText(tr("settings.subtitle"))
        self.close_button.setText(tr("dialog.close"))
        for key, _icon, label_key, _phase in CATEGORIES:
            button = self._nav_buttons[key]
            button.set_text(tr(label_key))
        self._pages.clear()
        while self.page_stack.count():
            item = self.page_stack.widget(0)
            self.page_stack.removeWidget(item)
            item.deleteLater()
        self._select(self._current)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        try:
            self._unsubscribe()
        except Exception:
            pass
        super().closeEvent(event)

    def accept(self) -> None:
        try:
            self._unsubscribe()
        except Exception:
            pass
        super().accept()

    def reject(self) -> None:
        try:
            self._unsubscribe()
        except Exception:
            pass
        super().reject()
