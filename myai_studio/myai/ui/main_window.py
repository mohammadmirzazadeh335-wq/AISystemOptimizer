"""The application shell.

Layout: sidebar · (header · workspace · composer) · inspector
State shared by the views lives here; every mutation goes through services.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QEasingCurve, QObject, QParallelAnimationGroup, QPropertyAnimation, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..context import AppContext
from ..core.errors import AppError
from ..core.markdown import plain_text
from ..core.paths import default_projects_dir
from ..data.models import Conversation
from ..i18n import tr
from ..services.backup import BackupService
from ..services.openrouter import ModelInfo, model_from_dict, model_to_dict
from ..version import APP_NAME
from .brand import app_icon
from .bridge import QtBridge
from .theme import runtime
from .theme.manager import ThemeManager
from .views.agent_page import AgentPage
from .views.api_page import ApiPage
from .views.appearance_page import AppearancePage
from .views.atlas_page import AtlasPage
from .views.chat_view import ChatView
from .views.code_page import CodePage
from .views.composer import Composer, human_size
from .views.context_page import ContextPage
from .views.doctor_page import DoctorPage
from .views.header import Header
from .views.inspector import Inspector
from .views.media_page import ImagesPage, VideoPage
from .views.memory_page import MemoryPage
from .views.output_page import OutputPage
from .views.performance_page import PerformancePage
from .views.persona_page import PersonaPage
from .views.plugins_page import PluginsPage
from .views.prompts_page import PromptsPage
from .views.review_page import ReviewPage
from .views.settings_dialog import SettingsDialog
from .views.sidebar import Sidebar
from .views.tasks_page import TasksPage
from .views.usage_page import UsagePage
from .views.web_page import WebPageView
from .widgets.dialogs import ConfirmDialog, PreviewDialog, PromptDialog
from .widgets.feedback import ToastManager
from .widgets.global_search import GlobalSearchDialog
from .widgets.palette import CommandPalette, PaletteAction

logger = logging.getLogger(__name__)

AI_ROUTES = {
    "api", "memory", "persona", "studio", "code", "agent",
    "prompts", "tasks", "performance", "images", "video", "web", "plugins",
    "review", "atlas", "context", "appearance", "doctor", "usage",
}
#: One source of truth for a page's header/window title (route -> title, subtitle).
PAGE_TITLES = {
    "api": ("api.title", "api.subtitle"),
    "memory": ("memory.title", "memory.subtitle"),
    "persona": ("persona.title", "persona.subtitle"),
    "studio": ("studio.title", "studio.subtitle"),
    "code": ("code.title", "code.subtitle"),
    "agent": ("agent.title", "agent.subtitle"),
    "prompts": ("prompts.title", "prompts.subtitle"),
    "tasks": ("tasks.title", "tasks.subtitle"),
    "performance": ("performance.title", "performance.subtitle"),
    "images": ("images.title", "images.subtitle"),
    "video": ("video.title", "video.subtitle"),
    "web": ("web.title", "web.subtitle"),
    "plugins": ("plugins.title", "plugins.subtitle"),
    "review": ("review.title", "review.subtitle"),
    "atlas": ("atlas.title", "atlas.subtitle"),
    "context": ("context.title", "context.subtitle"),
    "appearance": ("appearance.title", "appearance.subtitle"),
    "doctor": ("doctor.title", "doctor.subtitle"),
    "usage": ("usage.title", "usage.subtitle"),
}


class _StreamBridge(QObject):
    """Delivers worker-thread chat events to the GUI thread."""

    delta = Signal(str)
    status = Signal(str, dict)
    finished = Signal(object)
    failed = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, theme_manager: ThemeManager) -> None:
        super().__init__()
        self.context = context
        self._theme_manager = theme_manager
        self._current: Conversation | None = None
        self._current_route = "chat"
        self._generating = False
        self._closing = False
        self._stream_text = ""
        self._stream_bridge: _StreamBridge | None = None
        self._pages: dict[str, QWidget] = {}
        self._ai_models: list[ModelInfo] = []
        self.backup = BackupService(context.paths, context.db, context.settings)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setObjectName("MainWindow")
        self.setMinimumSize(runtime.px(1120), runtime.px(720))
        self._build()
        self.bridge = QtBridge(context.bus)
        self._wire()
        self._restore_state()
        self._bootstrap_models()
        self._apply_route_visibility("chat")
        self._update_window_title()
        self._fade_in()

    # ------------------------------------------------------------------- build
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = Sidebar(self.context.conversations)
        layout.addWidget(self.sidebar)

        center = QWidget()
        center.setObjectName("CenterPane")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.header = Header(self.context.conversations)
        self.header.set_connection_key("local", "header.local_mode", "nav.account_sub")
        center_layout.addWidget(self.header)

        self.stack = QStackedWidget()
        self.chat_view = ChatView()
        self.stack.addWidget(self.chat_view)
        self._build_pages()
        center_layout.addWidget(self.stack, 1)

        self.composer = Composer()
        center_layout.addWidget(self.composer)
        layout.addWidget(center, 1)

        self.inspector = Inspector(
            self.context.conversations,
            self.context.db,
            self.context.secrets,
            self.context.paths,
            activity_provider=self.context.activity.recent,
            memory_service=self.context.memory,
            chat_service=self.context.chat,
        )
        layout.addWidget(self.inspector)

        self.toasts = ToastManager(self, bottom_margin=146)
        self._shortcuts()

    def _build_pages(self) -> None:
        self.api_page = ApiPage(self.context)
        self.memory_page = MemoryPage(self.context)
        self.persona_page = PersonaPage(self.context)
        self.studio_page = OutputPage(self.context)
        self.code_page = CodePage(self.context)
        self.agent_page = AgentPage(self.context)
        self.prompts_page = PromptsPage(self.context)
        self.tasks_page = TasksPage(self.context)
        self.performance_page = PerformancePage(self.context)
        self.images_page = ImagesPage(self.context)
        self.video_page = VideoPage(self.context)
        self.web_page = WebPageView(self.context)
        self.plugins_page = PluginsPage(self.context)
        self.review_page = ReviewPage(self.context)
        self.atlas_page = AtlasPage(self.context)
        self.context_page = ContextPage(self.context)
        self.appearance_page = AppearancePage(self.context)
        self.doctor_page = DoctorPage(self.context)
        self.usage_page = UsagePage(self.context)
        self._pages = {
            "api": self.api_page,
            "memory": self.memory_page,
            "persona": self.persona_page,
            "studio": self.studio_page,
            "code": self.code_page,
            "agent": self.agent_page,
            "prompts": self.prompts_page,
            "tasks": self.tasks_page,
            "performance": self.performance_page,
            "images": self.images_page,
            "video": self.video_page,
            "web": self.web_page,
            "plugins": self.plugins_page,
            "review": self.review_page,
            "atlas": self.atlas_page,
            "context": self.context_page,
            "appearance": self.appearance_page,
            "doctor": self.doctor_page,
            "usage": self.usage_page,
        }
        for page in self._pages.values():
            self.stack.addWidget(page)
        self.api_page.notify.connect(self._show_toast)
        self.api_page.model_selected.connect(self._on_api_model_selected)
        self.api_page.models_updated.connect(self._on_models_loaded)
        self.memory_page.notify.connect(self._show_toast)
        self.persona_page.notify.connect(self._show_toast)
        self.studio_page.notify.connect(self._show_toast)
        self.code_page.notify.connect(self._show_toast)
        self.agent_page.notify.connect(self._show_toast)
        self.agent_page.open_api_page.connect(lambda: self._navigate("api"))
        for page in (
            self.prompts_page, self.tasks_page, self.performance_page,
            self.images_page, self.video_page, self.web_page, self.plugins_page,
            self.review_page, self.atlas_page, self.context_page,
            self.appearance_page, self.doctor_page, self.usage_page,
        ):
            page.notify.connect(self._show_toast)
        self.review_page.open_code.connect(lambda: self._navigate("code"))
        self.atlas_page.open_code.connect(lambda: self._navigate("code"))
        self.atlas_page.open_file.connect(self._open_in_code)
        self.context_page.open_chat.connect(lambda: self._navigate("chat"))
        self.context_page.open_settings.connect(self.open_settings)
        self.doctor_page.open_settings.connect(self.open_settings)
        self.usage_page.open_chat.connect(lambda: self._navigate("chat"))
        self.usage_page.open_catalogue.connect(lambda: self._navigate("api"))
        self.prompts_page.use_prompt.connect(self._use_prompt)

    def _shortcuts(self) -> None:
        self.shortcut_new = QShortcut(QKeySequence("Ctrl+N"), self)
        self.shortcut_new.activated.connect(self.new_chat)
        self.shortcut_search = QShortcut(QKeySequence("Ctrl+K"), self)
        self.shortcut_search.activated.connect(self.sidebar.focus_search)
        self.shortcut_search_all = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self.shortcut_search_all.activated.connect(self.open_global_search)
        self.shortcut_palette = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self.shortcut_palette.activated.connect(self.open_palette)
        self.shortcut_code = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        self.shortcut_code.activated.connect(lambda: self._navigate("code"))
        self.shortcut_settings = QShortcut(QKeySequence("Ctrl+,"), self)
        self.shortcut_settings.activated.connect(self.open_settings)
        self.shortcut_stop = QShortcut(QKeySequence("Esc"), self)
        self.shortcut_stop.activated.connect(self._stop_generation)

    # -------------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.sidebar.new_chat_requested.connect(self.new_chat)
        self.sidebar.conversation_selected.connect(self.open_conversation)
        self.sidebar.library_requested.connect(self._navigate)
        self.sidebar.settings_requested.connect(self.open_settings)
        self.sidebar.collapsed_changed.connect(self._on_sidebar_collapsed)
        self.sidebar.width_committed.connect(self._on_sidebar_width)
        self.sidebar.notify.connect(self._show_toast)

        self.header.settings_requested.connect(self.open_settings)
        self.header.stop_requested.connect(self._stop_generation)
        self.header.mode_changed.connect(self._on_mode_changed)
        self.header.model_changed.connect(self._on_model_changed)
        self.header.new_chat_requested.connect(self.new_chat)
        self.header.rename_requested.connect(self._rename_current)
        self.header.export_requested.connect(self._export_current)
        self.header.delete_requested.connect(self._delete_current)
        self.header.pin_requested.connect(self._toggle_pin_current)
        self.header.about_requested.connect(lambda: self.open_settings("about"))
        self.header.data_folder_requested.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.context.home)))
        )
        self.header.search_requested.connect(self.sidebar.focus_search)
        self.header.inspector_toggled.connect(self.set_inspector_visible)

        self.inspector.close_requested.connect(lambda: self.set_inspector_visible(False))
        self.inspector.memory_requested.connect(self._open_memory_for_current)
        self.inspector.connect_requested.connect(lambda: self._show_ai_page("api"))
        self.inspector.settings_requested.connect(lambda: self.open_settings("ai"))

        self.composer.send_requested.connect(self._handle_send)
        self.composer.stop_requested.connect(self._stop_generation)
        self.composer.settings_requested.connect(lambda: self.open_settings("ai"))
        self.composer.prompt_library_requested.connect(lambda: self._navigate("prompts"))
        self.composer.notify.connect(self._show_toast)
        self.composer.preview_requested.connect(self._preview_attachment)
        self.composer.agent_mode_requested.connect(lambda: self._navigate("agent"))

        self.chat_view.prompt_chosen.connect(self._use_suggestion)
        self.chat_view.notify.connect(self._show_toast)
        self.chat_view.message_delete_requested.connect(self._delete_message)
        self.chat_view.message_export_requested.connect(self._draft_message_in_studio)
        self.chat_view.model_retry_requested.connect(self._retry_last)

        self.bridge.conversations_changed.connect(self._on_conversations_changed)
        self.bridge.conversation_deleted.connect(self._on_conversation_deleted)
        self.bridge.conversation_selected.connect(self._on_conversation_selected)
        self.bridge.activity.connect(lambda _item: self.inspector.refresh_activity())
        self.bridge.toast.connect(self._show_toast)

        self.context.settings.subscribe(self._on_settings_changed)
        self._theme_manager.theme_changed.connect(self._on_theme_changed)
        self.sidebar.refresh()

    # ------------------------------------------------------------------- state
    def _restore_state(self) -> None:
        settings = self.context.settings
        width = int(settings.get("ui.window_width", 1440))
        height = int(settings.get("ui.window_height", 900))
        self.resize(runtime.px(width), runtime.px(height))
        self.sidebar.set_preferred_width(int(settings.get("ui.sidebar_width", 288)))
        if bool(settings.get("ui.sidebar_collapsed", False)):
            self.sidebar.set_collapsed(True, animate=False)
        inspector_open = bool(settings.get("ui.inspector_open", True))
        self.inspector.setVisible(inspector_open)
        self.header.set_inspector_open(inspector_open)
        last = settings.get("ui.start_view", "chat")
        if last == "last":
            conversations = self.context.conversations.list()
            if conversations:
                QTimer.singleShot(0, lambda: self.open_conversation(conversations[0].id))
                return
        QTimer.singleShot(0, self._show_welcome)

    def _show_welcome(self, *, navigate: bool = True) -> None:
        self._current = None
        if navigate:
            self._current_route = "chat"
            self.sidebar.sync_selection(None)
            self.stack.setCurrentWidget(self.chat_view)
            self.composer.show()
            self.header.set_mode("chat")
        self.chat_view.show_welcome(None)
        self.header.set_conversation(None)
        self.composer.set_notice_visibility(False)
        self._apply_models_to_ui()
        self.inspector.set_conversation(None, [])
        self._update_window_title()
        QTimer.singleShot(90, self.composer.focus_input)

    def new_chat(self) -> None:
        if self._generating:
            self._show_toast(tr("chat.stop"), "warning")
            return
        self._current = None
        self._current_route = "chat"
        self.sidebar.sync_selection(None)
        self.stack.setCurrentWidget(self.chat_view)
        self.composer.show()
        self.composer.set_notice_visibility(False)
        self.chat_view.show_welcome(None)
        self.header.set_conversation(None)
        self.header.set_mode("chat")
        self.inspector.set_conversation(None, [])
        self._update_window_title()
        self.composer.focus_input()

    def open_conversation(self, conversation_id: str) -> None:
        try:
            conversation = self.context.conversations.get(conversation_id)
            messages = self.context.conversations.messages(conversation_id)
        except AppError:
            self._show_welcome()
            return
        self._current = conversation
        self._current_route = "chat"
        self.sidebar.sync_selection(conversation.id)
        self.stack.setCurrentWidget(self.chat_view)
        self.composer.show()
        self.header.set_conversation(conversation)
        self.header.set_mode(conversation.mode if conversation.mode in {"chat", "agent"} else "chat")
        self.header.set_inspector_open(self.inspector.isVisible())
        self.chat_view.show_conversation(conversation, messages)
        self._apply_models_to_ui()
        self.composer.set_model_ready(bool(conversation.model_id))
        self.composer.set_notice_visibility(not messages and not conversation.model_id)
        self.inspector.set_conversation(conversation, messages)
        self._refresh_context_usage()
        self._update_window_title()

    # -------------------------------------------------------------- navigation
    def _navigate(self, route: str) -> None:
        if route == "settings":
            self.open_settings()
            return
        if route in AI_ROUTES:
            self._show_ai_page(route)
            return
        # Phase 5 closed the last placeholder: every library route is a real page,
        # so an unknown name is a no-op instead of a "coming soon" screen.
        logger.debug("unknown_route route=%s", route)

    def _show_ai_page(self, route: str) -> None:
        page = self._pages.get(route)
        if page is None:
            return
        self._current_route = route
        self.sidebar.set_active(route)
        self.stack.setCurrentWidget(page)
        self.composer.hide()
        self.toasts.set_bottom_margin(30)
        # The page prints its own explanation under the header, so the header
        # carries only the title (a second copy read as a rendering bug).
        title_key, _subtitle_key = PAGE_TITLES[route]
        self.header.set_section(tr(title_key))
        # The pill has to match the page: it said "Chat" on every agent shot in
        # Phase 4, which was wrong. Library pages keep Chat as their return path.
        self.header.set_mode("agent" if route == "agent" else "chat")
        self.header.set_inspector_open(self.inspector.isVisible())
        self.inspector.set_conversation(None, [])
        self._update_window_title()
        if route == "memory":
            self.memory_page.set_context(self._current.id if self._current else None)
        elif route in {"review", "atlas"}:
            page = self._pages[route]
            page.set_project(self.code_page.project)
        elif route == "context":
            self.context_page.set_conversation(self._current)
        elif route == "doctor":
            self.doctor_page.refresh()
        elif route == "persona":
            self.persona_page.refresh()
        elif route == "api":
            self.api_page.refresh()
        elif route == "studio":
            self.studio_page.refresh()
        elif route == "agent":
            self.agent_page.refresh()
        elif route == "code":
            self.code_page.refresh()
        else:  # prompts, tasks, performance, images, video, web, plugins
            page.refresh()

    def _open_memory_for_current(self) -> None:
        self._show_ai_page("memory")

    def _open_studio_for_current(self) -> None:
        self._show_ai_page("studio")

    def open_studio(self, output_id: str | None = None) -> None:
        self._show_ai_page("studio")
        self.studio_page.open_output(output_id)

    def draft_in_studio(self, name: str, content: str, kind: str = "code") -> None:
        self._show_ai_page("studio")
        self.studio_page.open_draft(name, content, kind=kind)
        self._show_toast(tr("studio.draft_created", name=name), "success")

    def _use_prompt(self, body: str, title: str) -> None:
        """Hand a library prompt to the composer and go back to the chat."""
        self._go_chat()
        self.composer.set_text(body)
        self._show_toast(tr("prompts.used_toast", title=title), "success")

    def _go_chat(self) -> None:
        self._current_route = "chat"
        self.toasts.set_bottom_margin(146)
        self.sidebar.sync_selection(self._current.id if self._current else None)
        self.stack.setCurrentWidget(self.chat_view)
        self.composer.show()
        if self._current is not None:
            self.open_conversation(self._current.id)
        else:
            self._show_welcome()
        self._update_window_title()

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "agent":
            self._navigate("agent")
        else:
            self._go_chat()

    def _on_model_changed(self, model_id: str) -> None:
        if not model_id:
            return
        try:
            self.context.settings.set("ai.default_model", model_id)
            if self._current is not None:
                self.context.conversations.set_model(self._current.id, model_id)
                self.open_conversation(self._current.id)
        except AppError as exc:
            self._show_toast(str(exc), "error")
            return
        self.composer.set_models(
            [(m.id, m.name or m.id) for m in self._ai_models], model_id
        )
        self._refresh_context_usage()

    def _use_suggestion(self, prompt: str) -> None:
        self.composer.set_text(prompt)
        self.composer.focus_input()

    # ------------------------------------------------------------ global search
    def open_global_search(self) -> None:
        dialog = GlobalSearchDialog(
            self,
            self.context.search,
            self._open_search_hit,
            project=self.code_page.project,
            conversation_id=self._current.id if self._current is not None else None,
        )
        dialog.exec()

    def _open_search_hit(self, hit, query: str = "") -> None:  # noqa: ANN001
        if hit.source in {"conversation", "message"}:
            conversation_id = (
                hit.ref if hit.source == "conversation" else hit.extra.get("conversation_id", "")
            )
            if conversation_id:
                self.open_conversation(conversation_id)
            return
        if hit.source == "file":
            self._open_in_code(hit.ref)
            return
        routes = {"prompt": "prompts", "memory": "memory", "output": "studio", "task": "tasks"}
        route = routes.get(hit.source)
        if route is None:
            return
        self._navigate(route)
        page = self._pages.get(route)
        search = getattr(page, "search", None)
        if query and search is not None and hasattr(search, "set_text"):
            search.set_text(query)

    # ----------------------------------------------------------------- palette
    def _palette_actions(self) -> list[PaletteAction]:
        actions: list[PaletteAction] = [
            PaletteAction(
                id="chat.new",
                title=tr("nav.new_chat"),
                hint="Ctrl+N",
                icon="plus",
                keywords=("new", "chat", "conversation"),
                run=self.new_chat,
            ),
            PaletteAction(
                id="chat.search",
                title=tr("settings.shortcut_search"),
                hint="Ctrl+K",
                icon="search",
                keywords=("find", "conversation"),
                run=self.sidebar.focus_search,
            ),
            PaletteAction(
                id="search.everything",
                title=tr("palette.search_all"),
                hint="Ctrl+Shift+F",
                icon="search",
                keywords=("find", "everything", "prompt", "file", "memory"),
                run=self.open_global_search,
            ),
        ]
        route_icons = {key: icon for key, icon, _label in Sidebar.LIBRARY}
        route_icons.update({key: icon for key, icon, _label in Sidebar.LAB})
        route_icons.update({key: icon for key, icon, _label in Sidebar.AI_PAGES})
        for route in PAGE_TITLES:
            title_key, subtitle_key = PAGE_TITLES[route]
            actions.append(
                PaletteAction(
                    id=f"go.{route}",
                    title=tr(title_key),
                    hint=tr(subtitle_key),
                    icon=route_icons.get(route, "arrow-right"),
                    keywords=(route,),
                    run=lambda r=route: self._navigate(r),
                )
            )
        actions.extend(
            [
                PaletteAction(
                    id="settings.open",
                    title=tr("nav.settings"),
                    hint="Ctrl+,",
                    icon="sliders",
                    keywords=("preferences", "theme", "language"),
                    run=self.open_settings,
                ),
                PaletteAction(
                    id="theme.cycle",
                    title=tr("palette.cycle_theme"),
                    hint=tr("palette.cycle_theme_hint"),
                    icon="moon",
                    keywords=("dark", "light", "appearance"),
                    run=self.cycle_theme,
                ),
                PaletteAction(
                    id="chat.attach",
                    title=tr("composer.attach_files"),
                    hint=tr("palette.attach_hint"),
                    icon="attach",
                    keywords=("file", "upload", "document"),
                    run=lambda: self.composer.pick_files(),
                ),
                PaletteAction(
                    id="data.folder",
                    title=tr("palette.open_data_folder"),
                    hint=str(self.context.home),
                    icon="folder",
                    keywords=("workspace", "explorer", "files"),
                    run=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.context.home))),
                ),
            ]
        )
        return actions

    def open_palette(self) -> None:
        """Ctrl+Shift+P: run any navigation or window action from the keyboard."""
        dialog = CommandPalette(self, self._palette_actions())
        dialog.exec()

    def cycle_theme(self) -> None:
        order = ["midnight", "dawn", "aurora", "system"]
        current = str(self.context.settings.get("ui.theme", "midnight"))
        try:
            following = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            following = "midnight"
        self.context.settings.set("ui.theme", following)
        theme = self._theme_manager.apply()
        self._show_toast(tr("palette.theme_toast", theme=tr(theme.name_key)), "info")

    # ------------------------------------------------------------------- send
    def _handle_send(self, text: str, attachments: list) -> None:
        if self._generating:
            self._show_toast(tr("chat.busy"), "warning")
            return
        try:
            conversation = self._current
            title = plain_text(text, 58) or self._attachment_title(attachments) or tr("chat.untitled")
            if conversation is None:
                conversation = self.context.conversations.create(title=title, select=False)
            elif not conversation.title.strip():
                conversation = self.context.conversations.rename(conversation.id, title)
            model_id = conversation.model_id or str(self.context.settings.get("ai.default_model", ""))
            self.composer.mark_sent()
            if not model_id:
                self.context.conversations.add_message(
                    conversation.id,
                    "user",
                    text,
                    model_id="",
                    meta={"attachments": attachments},
                )
                self.open_conversation(conversation.id)
                self.context.activity.record(key="chat.message_saved", kind="chat")
                self._show_toast(tr("chat.saved_local"), "info")
                return
            if not self.context.secrets.has_api_key():
                self.context.conversations.add_message(
                    conversation.id, "user", text, model_id=model_id,
                    meta={"attachments": attachments},
                )
                self.open_conversation(conversation.id)
                self._show_toast(tr("chat.needs_key"), "warning")
                return
            self._start_stream(conversation, text, model_id, attachments)
        except Exception as exc:  # noqa: BLE001
            logger.exception("send_failed")
            self.composer.restore_draft(text)
            message = exc.message if isinstance(exc, AppError) else tr("toast.error")
            self._show_toast(message, "error")

    @staticmethod
    def _attachment_title(attachments: list) -> str:
        """Name an attachment-only conversation after its first file."""
        for item in attachments or []:
            name = str(item.get("name", "")).strip()
            if name:
                return name
        return ""

    def _preview_attachment(self, path: str) -> None:
        """Show the extracted text of a file before/after sending it."""
        if not path:
            return
        try:
            record = self.context.attachments.ingest(path)
            text = record.text or self.context.attachments.preview(record)
        except AppError as exc:
            self._show_toast(self._explain_error(exc), "error")
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("attachment_preview_failed")
            self._show_toast(str(exc), "error")
            return
        dialog = PreviewDialog(
            self,
            title=record.name,
            subtitle=tr(
                "composer.preview_meta",
                size=human_size(record.size),
                chars=record.chars,
                kind=record.kind,
            ),
            text=text,
        )
        dialog.exec()

    def _start_stream(
        self, conversation: Conversation, text: str, model_id: str, attachments: list | None = None
    ) -> None:
        self._stream_text = ""
        self._stream_started = False
        self._stream_t0 = time.monotonic()
        self.open_conversation(conversation.id)
        self.set_generating(True)
        self.chat_view.begin_stream(model_id)
        self.context.activity.record(key="chat.stream_started", kind="chat")

        bridge = _StreamBridge(self)
        bridge.delta.connect(self._on_stream_delta)
        bridge.status.connect(self._on_stream_status)
        bridge.finished.connect(self._on_stream_finished)
        bridge.failed.connect(self._on_stream_failed)
        self._stream_bridge = bridge
        conversation_id = conversation.id

        def worker() -> None:
            try:
                outcome = self.context.chat.send(
                    conversation_id,
                    text,
                    model_id=model_id,
                    attachments=attachments or [],
                    on_delta=bridge.delta.emit,
                    on_status=bridge.status.emit,
                )
            except Exception as exc:  # noqa: BLE001 - reported on the GUI thread
                bridge.failed.emit(exc)
            else:
                bridge.finished.emit(outcome)

        threading.Thread(target=worker, name="myai-chat", daemon=True).start()

    def _on_stream_delta(self, fragment: str) -> None:
        self._stream_text += fragment
        self.chat_view.append_stream(self._stream_text)
        if not getattr(self, "_stream_started", False):
            self._stream_started = True
            elapsed = int((time.monotonic() - getattr(self, "_stream_t0", time.monotonic())) * 1000)
            self.chat_view.set_stream_latency(tr("chat.first_token", ms=elapsed))

    def _on_stream_status(self, status: str, payload: dict) -> None:
        if status != "done":
            return
        stats = payload.get("stats") or {}
        if stats:
            self.chat_view.set_stream_latency(
                tr(
                    "chat.stream_stats",
                    first=stats.get("first_token_ms", 0),
                    total=stats.get("total_ms", 0),
                )
            )

    def _on_stream_finished(self, outcome: object) -> None:
        self.set_generating(False)
        error = getattr(outcome, "error", None)
        cancelled = bool(getattr(outcome, "cancelled", False))
        if error is not None:
            self.chat_view.end_stream(error=error.message)
            self._show_toast(self._explain_error(error), "error")
        elif cancelled:
            self.chat_view.end_stream(cancelled=True)
            self._show_toast(tr("chat.stopped"), "info")
        else:
            self.chat_view.end_stream()
            self.context.activity.record(key="chat.stream_finished", kind="chat")
        if self._current is not None:
            self.open_conversation(self._current.id)
        self._refresh_context_usage()
        self._stream_bridge = None

    def _on_stream_failed(self, exc: object) -> None:
        self.set_generating(False)
        message = self._explain_error(exc) if isinstance(exc, AppError) else str(exc)
        self.chat_view.end_stream(error=message)
        self._show_toast(message, "error")
        logger.error("chat_worker_crashed: %s", exc)
        if self._current is not None:
            self.open_conversation(self._current.id)
        self._stream_bridge = None

    def _explain_error(self, error: AppError) -> str:
        key = getattr(error, "message_key", "") or ""
        if key and key != "error.api_generic":
            translated = tr(key)
            if translated and translated != key:
                return f"{translated} — {error.message}"
        return error.message

    def _draft_message_in_studio(self, name: str, content: str) -> None:
        kind = "markdown" if name.endswith((".md", ".markdown")) else "text"
        self.draft_in_studio(name, content, kind=kind)

    def _retry_last(self, message_id: str) -> None:
        """Re-send the most recent user turn after a failed reply."""
        if self._current is None or self._generating:
            return
        messages = self.context.conversations.messages(self._current.id)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if last_user is None:
            return
        # ``ChatService.send`` appends the user turn again, so the previous pair
        # is removed first; otherwise a retry would duplicate the question.
        for stale in {message_id, last_user.id}:
            try:
                self.context.conversations.delete_message(stale)
            except AppError:
                pass
        model_id = self._current.model_id or str(self.context.settings.get("ai.default_model", ""))
        self._start_stream(self._current, last_user.content, model_id)

    def _delete_message(self, message_id: str) -> None:
        if not self._current:
            return
        try:
            self.context.conversations.delete_message(message_id)
            self.open_conversation(self._current.id)
        except AppError as exc:
            self._show_toast(str(exc), "error")

    def _stop_generation(self) -> None:
        if self._generating:
            self.context.chat.cancel()
            self.composer.set_generating(False)
            self._show_toast(tr("chat.cancelling"), "info")

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.header.set_generating(generating)
        self.composer.set_generating(generating)

    # ----------------------------------------------------------------- models
    def _bootstrap_models(self) -> None:
        cached = self.context.settings.get("ai.openrouter_cache", []) or []
        models: list[ModelInfo] = []
        if isinstance(cached, list):
            for item in cached:
                model = model_from_dict(item) if isinstance(item, dict) else None
                if model is not None:
                    models.append(model)
        self._ai_models = models
        self.context.chat.set_models(models)
        self.api_page.set_models(models)
        self._apply_models_to_ui()
        if self.context.secrets.has_api_key():
            QTimer.singleShot(350, self._fetch_models_async)

    def _fetch_models_async(self) -> None:
        client = self.api_page.client()
        from .views.page_base import run_async

        run_async(
            self,
            lambda: client.list_models(),
            on_success=self._on_models_loaded,
            on_error=lambda exc: logger.info("model_sync_failed: %s", exc),
        )

    def _on_models_loaded(self, models: object) -> None:
        if not isinstance(models, list):
            return
        self._ai_models = list(models)
        self.context.chat.set_models(self._ai_models)
        self.api_page.set_models(self._ai_models)
        try:
            self.context.settings.set(
                "ai.openrouter_cache", [model_to_dict(model) for model in self._ai_models]
            )
        except AppError:
            logger.exception("model_cache_write_failed")
        self._apply_models_to_ui()

    def _apply_models_to_ui(self) -> None:
        items = [(model.id, model.name or model.id) for model in self._ai_models]
        default = str(self.context.settings.get("ai.default_model", ""))
        current = (
            self._current.model_id
            if self._current is not None and self._current.model_id
            else default
        )
        self.header.set_models(items, current)
        self.composer.set_models(items, current)
        if self._current is not None:
            self._refresh_context_usage()

    def _on_api_model_selected(self, model_id: str) -> None:
        if not model_id:
            return
        self.context.settings.set("ai.default_model", model_id)
        self.api_page.set_default_model(model_id)
        try:
            if self._current is not None:
                self.context.conversations.set_model(self._current.id, model_id)
                self.open_conversation(self._current.id)
        except AppError as exc:
            self._show_toast(str(exc), "error")
            return
        self._apply_models_to_ui()
        self._show_toast(tr("api.default_saved", model=model_id), "success")

    def _refresh_context_usage(self) -> None:
        if self._current is None or not self._current.model_id:
            self.header.set_context_usage(0.0, False)
            return
        try:
            status = self.context.chat.context_status(self._current)
        except Exception:
            logger.exception("context_status_failed")
            return
        self.header.set_context_usage(float(status.get("ratio", 0.0)), True)
        self.inspector.update_messages(self.context.conversations.messages(self._current.id))

    # ---------------------------------------------------------- conversation ops
    def _rename_current(self) -> None:
        if not self._current:
            return
        dialog = PromptDialog(
            self,
            tr("dialog.rename_chat"),
            tr("dialog.name"),
            value=self._current.title,
            confirm_text=tr("dialog.save"),
            cancel_text=tr("dialog.cancel"),
            required_text=tr("dialog.required"),
        )
        if dialog.exec():
            try:
                conversation = self.context.conversations.rename(self._current.id, dialog.value())
                self.open_conversation(conversation.id)
            except AppError as exc:
                self._show_toast(str(exc), "error")

    def _export_current(self) -> None:
        if not self._current:
            return
        suggested = f"{(self._current.title or 'conversation').strip()}.md".replace("/", "-")
        default_path = str(default_projects_dir() / suggested)
        path, _ = QFileDialog.getSaveFileName(self, tr("menu.export_md"), default_path, "Markdown (*.md)")
        if not path:
            return
        try:
            self.context.conversations.export_markdown(self._current.id, path)
            self._show_toast(tr("dialog.export_done", path=path), "success")
        except AppError as exc:
            self._show_toast(str(exc), "error")
        except Exception as exc:  # noqa: BLE001
            self._show_toast(tr("dialog.export_failed", error=str(exc)), "error")

    def _delete_current(self) -> None:
        if not self._current:
            return
        confirm = bool(self.context.settings.get("ui.confirm_delete", True))
        if confirm:
            dialog = ConfirmDialog(
                self,
                tr("dialog.delete_chat_title"),
                tr("dialog.delete_chat_body", title=self._current.title or tr("chat.untitled")),
                confirm_text=tr("dialog.delete"),
                cancel_text=tr("dialog.cancel"),
                danger=True,
                icon="trash",
            )
            if not dialog.exec():
                return
        self.context.conversations.delete(self._current.id)
        self.new_chat()

    def _toggle_pin_current(self) -> None:
        if not self._current:
            return
        try:
            updated = self.context.conversations.set_pinned(self._current.id, not self._current.pinned)
            self._current = updated
            self.open_conversation(updated.id)
            self._show_toast(tr("chat.pinned") if updated.pinned else tr("chat.unpinned"), "success")
        except AppError as exc:
            self._show_toast(str(exc), "error")

    # -------------------------------------------------------------- inspector
    def set_inspector_visible(self, visible: bool) -> None:
        if visible == self.inspector.isVisible() and visible:
            self.header.set_inspector_open(True)
            return
        self.header.set_inspector_open(visible)
        self.context.settings.set("ui.inspector_open", visible)
        width = runtime.px(360)
        current = 0 if not self.inspector.isVisible() else self.inspector.width()
        if visible:
            self.inspector.show()
            self.inspector.setMinimumWidth(0)
            self.inspector.setMaximumWidth(0)
            start, end = 0, width
        else:
            start, end = current, 0
        group = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self.inspector, prop, group)
            animation.setDuration(200)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(start)
            animation.setEndValue(end)
            group.addAnimation(animation)
        if not visible:
            group.finished.connect(self.inspector.hide)
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

    # --------------------------------------------------------------- settings
    def open_settings(self, initial: str = "general") -> None:
        dialog = SettingsDialog(
            self,
            self.context.settings,
            self._theme_manager,
            self.context.paths,
            self.context.db,
            self.context.secrets,
            self.backup,
            initial=initial,
        )
        target = {"route": ""}
        dialog.navigate.connect(lambda route: target.update(route=route))
        dialog.exec()
        if target["route"]:
            self._navigate(target["route"])
        self._retranslate()
        if self._current_route == "chat":
            if self._current:
                self.open_conversation(self._current.id)
            else:
                self._show_welcome(navigate=False)

    def _on_settings_changed(self, changes: dict) -> None:
        if "ui.language" in changes:
            self._retranslate()
        if "ui.sidebar_width" in changes:
            self.sidebar.set_preferred_width(int(changes["ui.sidebar_width"]))
        if "ui.start_view" in changes:
            pass

    def _on_theme_changed(self, theme) -> None:  # noqa: ANN001
        self.header.setFixedHeight(runtime.px(64))
        self.sidebar.set_preferred_width(int(self.context.settings.get("ui.sidebar_width", 288)))
        self.inspector.setFixedWidth(runtime.px(360))
        self.sidebar.refresh_theme()
        self.header.refresh_theme()
        self.composer.refresh_theme()
        self.inspector.refresh_theme()
        self.chat_view.refresh_theme()
        if self._current_route in AI_ROUTES:
            page = self._pages.get(self._current_route)
            if page is not None:
                if hasattr(page, "rebuild"):
                    page.rebuild()
                elif hasattr(page, "refresh_theme"):
                    page.refresh_theme()
        self.setWindowIcon(app_icon())
        self.update()

    def _retranslate(self) -> None:
        self.sidebar.retranslate()
        self.header.retranslate()
        self.composer.retranslate()
        self.chat_view.retranslate()
        self.inspector.retranslate()
        for page in self._pages.values():
            if hasattr(page, "rebuild"):
                page.rebuild()
            elif hasattr(page, "retranslate"):
                page.retranslate()
        if self._current_route == "chat":
            if self._current is not None:
                self.open_conversation(self._current.id)
            else:
                self.header.set_conversation(None)
        elif self._current_route in AI_ROUTES:
            title_key, _subtitle_key = PAGE_TITLES[self._current_route]
            self.header.set_section(tr(title_key))
        self._update_window_title()

    # -------------------------------------------------------------- reactions
    def _on_conversations_changed(self) -> None:
        self.sidebar.refresh()
        if self._current is not None:
            try:
                conversation = self.context.conversations.get(self._current.id)
            except AppError:
                self._show_welcome()
                return
            self._current = conversation
            self.header.set_conversation(conversation)
            self.header.set_context_usage(0.0, bool(conversation.model_id))

    def _on_conversation_deleted(self, conversation_id: str) -> None:
        self.sidebar.refresh()
        if self._current and self._current.id == conversation_id:
            self.new_chat()

    def _on_conversation_selected(self, conversation_id: str) -> None:
        if self._current and self._current.id == conversation_id and self._current_route == "chat":
            return
        if self._current_route == "chat" or self.stack.currentWidget() is self.chat_view:
            self.open_conversation(conversation_id)

    def _on_sidebar_collapsed(self, collapsed: bool) -> None:
        self.context.settings.set("ui.sidebar_collapsed", collapsed)

    def _on_sidebar_width(self, logical_width: int) -> None:
        self.context.settings.set("ui.sidebar_width", max(240, min(420, int(logical_width))))

    def _apply_route_visibility(self, route: str) -> None:
        if route == "chat":
            self.stack.setCurrentWidget(self.chat_view)
            self.composer.show()
            self.toasts.set_bottom_margin(146)
        elif route in AI_ROUTES and route in self._pages:
            self.stack.setCurrentWidget(self._pages[route])
            self.composer.hide()
        else:
            self.stack.setCurrentWidget(self.chat_view)
            self.composer.show()

    def _open_in_code(self, relative: str) -> None:
        """Open a file chosen on the atlas in Code Studio, with the project."""
        project = self.code_page.project
        self._navigate("code")
        if self.code_page.project is None and project is not None:
            self.code_page.set_project(project)
        try:
            self.code_page.open_file(relative)
        except Exception:  # noqa: BLE001 - the page reports its own errors
            logger.exception("atlas_open_failed path=%s", relative)

    def _show_toast(self, message: str, level: str = "info") -> None:
        if not message:
            return
        normalized = level if level in {"info", "success", "warning", "error"} else "info"
        self.toasts.show(message, normalized)

    def _update_window_title(self) -> None:
        if self._current_route != "chat":
            if self._current_route in AI_ROUTES:
                key = PAGE_TITLES[self._current_route][0]
                self.setWindowTitle(f"{tr(key)} — {APP_NAME}")
                return
        if self._current is not None:
            title = self._current.title.strip() or tr("chat.untitled")
            self.setWindowTitle(f"{title} — {APP_NAME}")
        else:
            self.setWindowTitle(APP_NAME)

    def _fade_in(self) -> None:
        if bool(self.context.settings.get("ui.reduce_motion", False)):
            return
        if QApplication.platformName() == "offscreen":
            return
        try:
            self.setWindowOpacity(0.0)
            animation = QPropertyAnimation(self, b"windowOpacity", self)
            animation.setDuration(240)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        except Exception:  # pragma: no cover - platform opacity support
            self.setWindowOpacity(1.0)

    # ------------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: ANN001
        if not self._closing:
            self._closing = True
            if not self.isMaximized() and not self.isFullScreen():
                size = self.size()
                scale = max(runtime.scale(), 0.01)
                width = min(6000, max(1120, int(size.width() / scale)))
                height = min(4000, max(720, int(size.height() / scale)))
                try:
                    self.context.settings.update(
                        {"ui.window_width": width, "ui.window_height": height}
                    )
                except Exception:
                    logger.exception("window_state_save_failed")
            for page in (self.code_page, self.agent_page, self.studio_page):
                shutdown = getattr(page, "shutdown", None)
                if callable(shutdown):
                    try:
                        shutdown()
                    except Exception:  # pragma: no cover - closing must never fail
                        logger.exception("page_shutdown_failed page=%s", type(page).__name__)
            self.context.shutdown()
        super().closeEvent(event)
