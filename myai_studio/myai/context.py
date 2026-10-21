"""Composition root.

Builds the object graph once (paths → database → repositories → services) so
that both the desktop application and the test-suite can start from the same
well-defined state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .core.events import Events, SignalBus
from .core.logging import setup_logging
from .core.paths import AppPaths, get_paths
from .data import (
    ConversationRepository,
    Database,
    FolderRepository,
    MessageRepository,
    ProjectRepository,
    SettingRepository,
)
from .i18n import set_language
from .security.secrets import SecretStore
from .services.activity import ActivityService
from .services.chat import ChatService, build_chat_service
from .services.conversations import ConversationService
from .services.memory import MemoryService
from .services.outputs import OutputService
from .services.persona import PersonaService
from .services.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    paths: AppPaths
    bus: SignalBus
    db: Database
    settings: SettingsService
    conversations: ConversationService
    secrets: SecretStore
    activity: ActivityService
    memory: MemoryService
    persona: PersonaService
    outputs: OutputService
    chat: ChatService
    _booted: bool = field(default=False, repr=False)

    @property
    def home(self) -> Path:
        return self.paths.home

    def boot(self) -> "AppContext":
        if self._booted:
            return self
        settings = self.settings.load()
        set_language(settings.get("ui.language", "fa"))
        self.conversations.set_default_model(settings.get("ai.default_model", ""))
        self._booted = True
        self.bus.emit(Events.APP_STARTED, context=self)
        self.activity.record(key="phase1.ready", kind="app")
        logger.info(
            "app_booted home=%s theme=%s language=%s",
            self.home,
            settings.get("ui.theme"),
            settings.get("ui.language"),
        )
        return self

    def shutdown(self) -> None:
        try:
            self.bus.emit(Events.APP_SHUTDOWN)
        finally:
            self.db.close()
            logger.info("app_shutdown")


def build_context(home: str | Path | None = None, *, log: bool = True) -> AppContext:
    paths = get_paths(home)
    if log:
        setup_logging(paths.logs_dir)
    bus = SignalBus()
    db = Database(paths.db_file).initialize()
    settings = SettingsService(SettingRepository(db), bus)
    activity = ActivityService(bus)
    conversations = ConversationService(
        bus=bus,
        conversations=ConversationRepository(db),
        messages=MessageRepository(db),
        folders=FolderRepository(db),
        projects=ProjectRepository(db),
        activity=activity,
    )
    secrets = SecretStore(paths.secrets_file, paths.secret_key_file)
    memory = MemoryService(db, bus)
    persona = PersonaService(settings, paths, bus)
    outputs = OutputService(db, paths, bus)
    chat = build_chat_service(
        db=db,
        bus=bus,
        conversations=conversations,
        settings=settings,
        memory=memory,
        persona=persona,
        api_key_reader=secrets.get_api_key,
    )
    return AppContext(
        paths=paths,
        bus=bus,
        db=db,
        settings=settings,
        conversations=conversations,
        secrets=secrets,
        activity=activity,
        memory=memory,
        persona=persona,
        outputs=outputs,
        chat=chat,
    )
