"""Thread-safe bridge between the Qt-free service layer and widgets.

Services publish on the :class:`SignalBus`; this QObject converts those events
into Qt signals.  When a service runs on a worker thread, Qt's queued
connections deliver the signal on the GUI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.events import Events, SignalBus


class QtBridge(QObject):
    conversations_changed = Signal()
    conversation_selected = Signal(str)
    conversation_deleted = Signal(str)
    message_created = Signal(object)
    activity = Signal(object)
    toast = Signal(str, str)

    def __init__(self, bus: SignalBus) -> None:
        super().__init__()
        self._bus = bus
        bus.subscribe(Events.CONVERSATION_CREATED, self._conversations_changed)
        bus.subscribe(Events.CONVERSATION_UPDATED, self._conversations_changed)
        bus.subscribe(Events.CONVERSATION_DELETED, self._conversation_deleted)
        bus.subscribe(Events.CONVERSATION_SELECTED, self._conversation_selected)
        bus.subscribe(Events.MESSAGE_CREATED, self._message_created)
        bus.subscribe(Events.ACTIVITY, self._activity)
        bus.subscribe(Events.TOAST, self._toast)

    def _conversations_changed(self, **payload) -> None:  # noqa: ANN003
        self.conversations_changed.emit()

    def _conversation_selected(self, conversation_id: str, **payload) -> None:  # noqa: ANN003
        self.conversation_selected.emit(conversation_id)

    def _conversation_deleted(self, conversation_id: str, **payload) -> None:  # noqa: ANN003
        self.conversation_deleted.emit(conversation_id)

    def _message_created(self, message, **payload) -> None:  # noqa: ANN001
        self.message_created.emit(message)

    def _activity(self, item, **payload) -> None:  # noqa: ANN001
        self.activity.emit(item)

    def _toast(self, message: str, level: str = "info", **payload) -> None:  # noqa: ANN003
        self.toast.emit(message, level)
