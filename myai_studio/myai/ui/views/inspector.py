"""Contextual inspector: model, context budget, storage, health and activity.

Everything shown here is read from real local state.  When data does not exist
yet (memory, tool runs) the panel says so and names the phase that will add it
instead of displaying fabricated numbers.
"""

from __future__ import annotations

import platform
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.paths import AppPaths
from ...core.timeutil import format_bytes, format_datetime, relative_time
from ...i18n import current_language, tn, tr
from ...security.secrets import SecretStore
from ...services.conversations import ConversationService
from ...version import VERSION
from ..theme import runtime
from ..widgets.buttons import IconButton
from ..widgets.feedback import DonutMeter
from ..widgets.foundation import Badge


class InfoRow(QWidget):
    def __init__(self, label: str, value: str = "", *, mono: bool = False, tone: str = "", parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(8))
        self.label = QLabel(label)
        self.label.setProperty("role", "faint")
        self.label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        self.label.setMinimumWidth(0)
        layout.addWidget(self.label, 1)
        layout.addStretch(1)
        self.value = QLabel(value)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if mono:
            self.value.setProperty("role", "mono")
        if tone:
            self.value.setProperty("role", tone)
        self.value.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        self.value.setMinimumWidth(0)
        layout.addWidget(self.value, 0)


class Inspector(QFrame):
    close_requested = Signal()
    settings_requested = Signal()

    memory_requested = Signal()
    connect_requested = Signal()

    def __init__(
        self,
        service: ConversationService,
        db,
        secrets: SecretStore,
        paths: AppPaths,
        activity_provider: Callable[[int], list] | None = None,
        parent: QWidget | None = None,
        *,
        memory_service=None,
        chat_service=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("panel", "inspector")
        self.setFixedWidth(runtime.px(360))
        self._service = service
        self._db = db
        self._secrets = secrets
        self._paths = paths
        self._activity_provider = activity_provider
        self._memory = memory_service
        self._chat = chat_service
        self._conversation = None
        self._messages = []
        self._health_cache: dict[str, str] = {}
        self._build_shell()
        self._populate()

    def _build_shell(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(runtime.px(16), runtime.px(13), runtime.px(10), runtime.px(11))
        header_layout.setSpacing(runtime.px(8))
        self.title_label = QLabel(tr("inspector.title"))
        self.title_label.setProperty("role", "h3")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self.close_button = IconButton("close", tr("dialog.close"), 26, icon_size=13)
        self.close_button.clicked.connect(self.close_requested)
        header_layout.addWidget(self.close_button)
        layout.addWidget(header)
        line = QFrame()
        line.setProperty("panel", "divider")
        layout.addWidget(line)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(16))
        self.body_layout.setSpacing(runtime.px(11))
        # Shrinkable cards collapse to ~zero height on a short window instead of
        # scrolling; pinning the layout minimum makes the scroll area scroll.
        self.body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------ public
    def set_conversation(self, conversation, messages=None) -> None:  # noqa: ANN001
        self._conversation = conversation
        self._messages = list(messages or [])
        self._populate()

    def update_messages(self, messages) -> None:  # noqa: ANN001
        self._messages = list(messages or [])
        self._populate()

    def refresh_activity(self) -> None:
        self._populate()

    def refresh_theme(self) -> None:
        self._populate()

    # ------------------------------------------------------------------ build
    def _card(self, title_key: str, icon_name: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("panel", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(runtime.px(12), runtime.px(11), runtime.px(12), runtime.px(11))
        layout.setSpacing(runtime.px(7))
        if title_key:
            head = QHBoxLayout()
            head.setSpacing(runtime.px(6))
            if icon_name:
                icon_widget = QLabel()
                icon_widget.setPixmap(runtime.icons().px(icon_name, 13, "muted"))
                head.addWidget(icon_widget)
            label = QLabel(tr(title_key))
            label.setProperty("role", "section")
            head.addWidget(label)
            head.addStretch(1)
            layout.addLayout(head)
        return card, layout

    def _populate(self) -> None:
        while self.body_layout.count() > 1:
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._add_model_card()
        self._add_context_card()
        self._add_session_card()
        self._add_health_card()
        self._add_activity_card()
        self._add_files_card()
        self._add_memory_card()
        self._add_footer()
        self.body_layout.addStretch(1)

    def _insert(self, widget: QWidget) -> None:
        self.body_layout.insertWidget(self.body_layout.count() - 1, widget)

    def _add_model_card(self) -> None:
        card, layout = self._card("inspector.model", "sparkles")
        model_id = getattr(self._conversation, "model_id", "") if self._conversation else ""
        if model_id:
            row = QHBoxLayout()
            name = QLabel(model_id.split("/")[-1])
            name.setProperty("role", "h3")
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(Badge(tr("state.ready"), "success"))
            layout.addLayout(row)
            layout.addWidget(self._info("inspector.provider", "OpenRouter"))
            self._insert(card)
            return
        empty = QLabel(tr("inspector.no_model"))
        empty.setProperty("role", "muted")
        empty.setWordWrap(True)
        layout.addWidget(empty)
        hint = QLabel(tr("inspector.no_model_hint"))
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(Badge(tr("inspector.no_model_badge"), "warning"))
        row.addStretch(1)
        configure = QPushButton(tr("inspector.connect_model"))
        configure.setProperty("variant", "secondary")
        configure.setProperty("buttonsize", "sm")
        configure.setCursor(Qt.CursorShape.PointingHandCursor)
        configure.clicked.connect(self.connect_requested)
        row.addWidget(configure)
        layout.addLayout(row)
        self._insert(card)

    def _info(self, label_key: str, value: str, *, mono: bool = False, tone: str = "") -> QWidget:
        return InfoRow(tr(label_key), value, mono=mono, tone=tone)

    def _add_context_card(self) -> None:
        card, layout = self._card("inspector.context", "cpu")
        content = QHBoxLayout()
        content.setSpacing(runtime.px(13))
        donut = DonutMeter(78, center_text="—")
        content.addWidget(donut, 0, Qt.AlignmentFlag.AlignTop)
        stats = self._service.stats(self._conversation.id) if self._conversation else {
            "messages": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "by_role": {},
        }
        right = QVBoxLayout()
        right.setSpacing(runtime.px(6))
        status = self._context_status()
        if status is not None:
            ratio = float(status.get("ratio", 0.0))
            window = int(status.get("window", 0))
            total = int(status.get("total_tokens", 0))
            donut.set_value(min(0.999, ratio), animate=True, center_text=f"{round(ratio * 100)}%")
            right.addWidget(self._info("inspector.messages", str(stats.get("messages", len(self._messages)))))
            right.addWidget(InfoRow(tr("inspector.context"), tr("inspector.context_estimate",
                                                                used=f"{total:,}", total=f"{window // 1000}k")))
            right.addWidget(InfoRow(tr("inspector.context_memory"), f"≈{int(status.get('memory_tokens', 0)):,}"))
            right.addWidget(InfoRow(tr("inspector.context_history"), f"≈{int(status.get('history_tokens', 0)):,}"))
            if status.get("warning"):
                warning = QLabel(tr("inspector.context_warning", percent=round(ratio * 100)))
                warning.setWordWrap(True)
                warning.setProperty("role", "warning")
                warning.setStyleSheet(f"font-size: {runtime.px(10)}px;")
                right.addWidget(warning)
            content.addLayout(right, 1)
            layout.addLayout(content)
            self._insert(card)
            return
        donut.set_value(0.0, animate=False, center_text="—")
        right.addWidget(self._info("inspector.messages", str(stats.get("messages", len(self._messages)))))
        right.addWidget(InfoRow(tr("inspector.context"), "—"))
        right.addStretch(1)
        content.addLayout(right, 1)
        layout.addLayout(content)
        self._insert(card)

    def _context_status(self) -> dict | None:
        if self._conversation is None or self._chat is None:
            return None
        if not getattr(self._conversation, "model_id", ""):
            return None
        try:
            return self._chat.context_status(self._conversation)
        except Exception:
            return None

    def _add_session_card(self) -> None:
        card, layout = self._card("inspector.session", "file")
        if self._conversation is None:
            empty = QLabel(tr("inspector.no_session"))
            empty.setProperty("role", "muted")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            self._insert(card)
            return
        language = current_language()
        layout.addWidget(self._info("inspector.created", format_datetime(self._conversation.created_at, language)))
        layout.addWidget(self._info("inspector.updated", format_datetime(self._conversation.updated_at, language)))
        layout.addWidget(self._info("inspector.messages", str(getattr(self._conversation, "message_count", 0))))
        layout.addWidget(self._info("inspector.storage", format_bytes(self._db.file_size()), mono=True))
        self._insert(card)

    def _add_health_card(self) -> None:
        card, layout = self._card("inspector.health", "shield")
        try:
            integrity = self._db.integrity_check()
        except Exception:
            integrity = "error"
        rows = [
            (tr("inspector.database"), "OK" if integrity == "ok" else integrity, integrity == "ok"),
            (tr("inspector.schema"), f"v{self._db.schema_version()}", True),
            (tr("inspector.secrets"), "DPAPI" if self._secrets.backend == "dpapi" else "FERNET", True),
            (tr("inspector.logs"), "JSONL", True),
        ]
        for label, value, ok in rows:
            row = QHBoxLayout()
            dot = QLabel()
            dot.setPixmap(runtime.icons().px("check" if ok else "alert", 12, "success" if ok else "danger"))
            row.addWidget(dot)
            name = QLabel(label)
            name.setProperty("role", "faint")
            name.setStyleSheet(f"font-size: {runtime.px(10)}px;")
            row.addWidget(name)
            row.addStretch(1)
            value_label = QLabel(value)
            value_label.setProperty("role", "mono")
            value_label.setStyleSheet(f"font-size: {runtime.px(9)}px;")
            row.addWidget(value_label)
            layout.addLayout(row)
        open_logs = QPushButton(tr("settings.open_logs"))
        open_logs.setProperty("variant", "ghost")
        open_logs.setProperty("buttonsize", "sm")
        open_logs.setCursor(Qt.CursorShape.PointingHandCursor)
        open_logs.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._paths.logs_dir)))
        )
        layout.addWidget(open_logs, 0, Qt.AlignmentFlag.AlignLeft)
        self._insert(card)

    def _add_activity_card(self) -> None:
        card, layout = self._card("inspector.activity", "activity")
        items = self._activity_provider(6) if self._activity_provider else []
        if not items:
            empty = QLabel(tr("inspector.no_activity"))
            empty.setProperty("role", "muted")
            layout.addWidget(empty)
            hint = QLabel(tr("inspector.no_activity_hint"))
            hint.setProperty("role", "faint")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"font-size: {runtime.px(10)}px;")
            layout.addWidget(hint)
        else:
            for item in items[:6]:
                row = QHBoxLayout()
                row.setSpacing(runtime.px(7))
                dot_color = {
                    "success": "success",
                    "warning": "warning",
                    "error": "danger",
                }.get(getattr(item, "level", "info"), "accent")
                dot = QLabel()
                dot.setPixmap(runtime.icons().px("check", 10, dot_color))
                row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                text = QLabel(item.display() if hasattr(item, "display") else item.text)
                text.setWordWrap(True)
                text.setStyleSheet(f"font-size: {runtime.px(10)}px;")
                row.addWidget(text, 1)
                stamp = QLabel(relative_time(item.at, current_language()))
                stamp.setProperty("role", "faint")
                stamp.setStyleSheet(f"font-size: {runtime.px(9)}px;")
                row.addWidget(stamp, 0, Qt.AlignmentFlag.AlignTop)
                layout.addLayout(row)
        self._insert(card)

    def _add_files_card(self) -> None:
        card, layout = self._card("inspector.files", "file")
        attachments = []
        for message in self._messages:
            for attachment in (message.meta or {}).get("attachments") or []:
                attachments.append(attachment)
        if not attachments:
            empty = QLabel(tr("inspector.no_files"))
            empty.setProperty("role", "muted")
            layout.addWidget(empty)
            hint = QLabel(tr("inspector.no_files_hint"))
            hint.setProperty("role", "faint")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"font-size: {runtime.px(10)}px;")
            layout.addWidget(hint)
        else:
            for attachment in attachments[:8]:
                row = QHBoxLayout()
                icon_label_widget = QLabel()
                icon_label_widget.setPixmap(
                    runtime.icons().px(
                        "image" if attachment.get("kind") == "image" else "file", 12, "muted"
                    )
                )
                row.addWidget(icon_label_widget)
                name = QLabel(str(attachment.get("name", "")))
                name.setProperty("role", "mono")
                name.setStyleSheet(f"font-size: {runtime.px(9)}px;")
                row.addWidget(name, 1)
                size = QLabel(format_bytes(attachment.get("size", 0)))
                size.setProperty("role", "faint")
                size.setStyleSheet(f"font-size: {runtime.px(9)}px;")
                row.addWidget(size)
                layout.addLayout(row)
        self._insert(card)

    def _add_memory_card(self) -> None:
        card, layout = self._card("inspector.memory", "database")
        if self._memory is None:
            empty = QLabel(tr("inspector.no_memory"))
            empty.setProperty("role", "muted")
            layout.addWidget(empty)
            self._insert(card)
            return
        conversation_id = getattr(self._conversation, "id", None) if self._conversation else None
        try:
            usage = self._memory.usage(conversation_id)
            entries = self._memory.all_for_conversation(conversation_id)
        except Exception:
            usage = None
            entries = []
        head = QHBoxLayout()
        label = QLabel(tn("inspector.memory_injected", len(entries)))
        label.setProperty("role", "muted")
        label.setWordWrap(True)
        head.addWidget(label, 1)
        head.addWidget(Badge(tr("inspector.memory_global", count=usage.global_count if usage else 0), "outline"))
        if conversation_id and usage and usage.conversation_count:
            head.addWidget(Badge(tr("inspector.memory_chat", count=usage.conversation_count), "accent"))
        layout.addLayout(head)
        if not entries:
            hint = QLabel(tr("inspector.no_memory_hint"))
            hint.setProperty("role", "faint")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"font-size: {runtime.px(10)}px;")
            layout.addWidget(hint)
        else:
            for entry in entries[:3]:
                row = QLabel("• " + entry.content[:90] + ("…" if len(entry.content) > 90 else ""))
                row.setWordWrap(True)
                row.setProperty("role", "faint")
                row.setStyleSheet(f"font-size: {runtime.px(10)}px;")
                layout.addWidget(row)
            if usage is not None:
                layout.addWidget(
                    InfoRow(tr("inspector.memory_storage"), f"{usage.storage_bytes:,} B")
                )
        manage = QPushButton(tr("inspector.manage_memory"))
        manage.setProperty("variant", "ghost")
        manage.setProperty("buttonsize", "sm")
        manage.setCursor(Qt.CursorShape.PointingHandCursor)
        manage.clicked.connect(self.memory_requested)
        layout.addWidget(manage, 0, Qt.AlignmentFlag.AlignLeft)
        self._insert(card)

    def _add_footer(self) -> None:
        footer = QWidget()
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(runtime.px(2), runtime.px(4), runtime.px(2), 0)
        layout.setSpacing(runtime.px(3))
        from PySide6 import QtCore

        version = QLabel(f"MyAI Studio Ultimate v{VERSION} · Qt {QtCore.qVersion()} · Python {platform.python_version()}")
        version.setProperty("role", "faint")
        version.setWordWrap(True)
        version.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        layout.addWidget(version)
        schema = QLabel(f"SQLite schema v{self._db.schema_version()} · {self._db.path.name}")
        schema.setProperty("role", "faint")
        schema.setWordWrap(True)
        schema.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        layout.addWidget(schema)
        self._insert(footer)

    # ----------------------------------------------------------------- events
    def retranslate(self) -> None:
        """Re-label static chrome, then rebuild the cards (they are generated)."""
        if hasattr(self, "title_label"):
            self.title_label.setText(tr("inspector.title"))
        if hasattr(self, "close_button"):
            self.close_button.setToolTip(tr("dialog.close"))
        self._populate()
