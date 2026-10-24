"""Top bar: context (title, model, status) and global actions."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...services.conversations import ConversationService
from ..theme import runtime
from ..theme.icons import icon
from ..widgets.buttons import IconButton, SegmentedControl
from ..widgets.fields import SelectField
from ..widgets.foundation import ElidedLabel
from ..widgets.painting import paint_event


class ContextRing(QWidget):
    clicked = Signal()

    def __init__(self, size: int = 32, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(runtime.px(size), runtime.px(size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(tr("chat.context_hint"))
        self._ratio = 0.0
        self._has_model = False

    def set_usage(self, ratio: float, has_model: bool) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self._has_model = has_model
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor(c("surface_3")), runtime.px(2.4)))
        painter.drawEllipse(rect)
        if self._ratio > 0:
            tone = c("warning") if self._ratio >= 0.8 else c("accent")
            pen = QPen(QColor(tone), runtime.px(2.4))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * self._ratio))
        painter.setFont(runtime.ui_font(8, 700))
        painter.setPen(QColor(c("text_muted") if self._has_model else c("text_faint")))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{round(self._ratio * 100)}")
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
class StatusPill(QWidget):
    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = "success"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._recalc()

    def _recalc(self) -> None:
        from PySide6.QtGui import QFontMetrics

        metrics = QFontMetrics(runtime.ui_font(10, 500))
        self.setFixedSize(metrics.horizontalAdvance(self._text) + runtime.px(30), runtime.px(24))

    def set_status(self, text: str, tone: str = "success", tooltip: str = "") -> None:
        self._text = text
        self._tone = tone
        self.setToolTip(tooltip)
        self._recalc()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("surface_2")))
        painter.drawRoundedRect(rect, runtime.px(12), runtime.px(12))
        tone = QColor(c(self._tone))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tone)
        painter.drawEllipse(QRectF(runtime.px(9), self.height() / 2 - runtime.px(3), runtime.px(6), runtime.px(6)))
        painter.setFont(runtime.ui_font(10, 500))
        painter.setPen(QColor(c("text_muted")))
        painter.drawText(
            self.rect().adjusted(runtime.px(19), 0, -runtime.px(8), 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect, runtime.px(12), runtime.px(12))
class Header(QFrame):
    inspector_toggled = Signal(bool)
    settings_requested = Signal()
    stop_requested = Signal()
    mode_changed = Signal(str)
    model_changed = Signal(str)
    new_chat_requested = Signal()
    rename_requested = Signal()
    export_requested = Signal()
    delete_requested = Signal()
    pin_requested = Signal()
    about_requested = Signal()
    data_folder_requested = Signal()
    search_requested = Signal()

    def __init__(self, service: ConversationService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", "header")
        self.setFixedHeight(runtime.px(64))
        self._service = service
        self._conversation = None
        self._generating = False
        self._connection = ("local", "", "")
        self._model_placeholder = ""
        self._build()
        self.set_conversation(None)

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(20), 0, runtime.px(14), 0)
        layout.setSpacing(runtime.px(10))

        title_wrap = QWidget()
        # ``Ignored`` lets the title give up width to the fixed-size controls
        # instead of squeezing the model chip below its own content.
        title_wrap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(runtime.px(1))
        self.title = ElidedLabel("", pixel_size=14, weight=600)
        self.title.setMinimumWidth(runtime.px(56))
        title_layout.addWidget(self.title)
        self.subtitle = ElidedLabel("", pixel_size=10, weight=400, tone="faint")
        self.subtitle.setMinimumWidth(runtime.px(56))
        title_layout.addWidget(self.subtitle)
        layout.addWidget(title_wrap, 1)

        self.model_chip = SelectField(
            [],
            placeholder=tr("header.no_model"),
            compact=True,
            empty_action=(tr("inspector.open_settings"), self.settings_requested.emit),
            searchable=True,
            search_placeholder=tr("picker.search"),
        )
        self.model_chip.value_changed.connect(self.model_changed)
        self.model_chip.setToolTip(tr("chat.model_hint"))
        layout.addWidget(self.model_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        self.status = StatusPill(tr("state.ready"))
        self.status.set_status(tr("nav.account"), "success", tr("nav.account_sub"))
        self.status.clicked.connect(self.settings_requested)
        layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)

        self.context_ring = ContextRing()
        self.context_ring.clicked.connect(lambda: self.inspector_toggled.emit(True))
        self.context_ring.setToolTip(tr("chat.context_hint"))
        layout.addWidget(self.context_ring, 0, Qt.AlignmentFlag.AlignVCenter)

        self.mode = SegmentedControl(
            [("chat", tr("header.chat")), ("agent", tr("header.agent"))],
            current="chat",
            compact=True,
        )
        self.mode.changed.connect(self.mode_changed)
        layout.addWidget(self.mode, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stop_button = IconButton("stop", tr("header.stop"), 32, icon_size=14, tone="danger")
        self.stop_button.setEnabled(False)
        self.stop_button.setToolTip(tr("header.stop"))
        self.stop_button.clicked.connect(self.stop_requested)
        layout.addWidget(self.stop_button)

        self.inspector_button = IconButton("panel-right", tr("header.inspector"), 32, icon_size=16, checkable=True)
        self.inspector_button.setChecked(True)
        self.inspector_button.clicked.connect(self.inspector_toggled)
        layout.addWidget(self.inspector_button)

        self.more_button = IconButton("more", tr("header.more"), 32, icon_size=17)
        self.more_button.clicked.connect(self._show_more)
        layout.addWidget(self.more_button)

        self._refresh_icons()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._apply_compact_layout(event.size().width())

    def _apply_compact_layout(self, width: int) -> None:
        """Drop secondary chrome before anything can overlap.

        At 1120 px with the inspector open the centre pane is ~470 px; the
        status pill and context ring are the least important items there, so
        they collapse first and the model chip keeps readable width.
        """
        compact = width < runtime.px(560)
        self.status.setVisible(not compact)
        self.context_ring.setVisible(not compact)
        if hasattr(self, "mode"):
            self.mode.setVisible(width >= runtime.px(430))
        self.subtitle.setVisible(width >= runtime.px(330))
        self.title.setMinimumWidth(runtime.px(56))

    def _refresh_icons(self) -> None:

        self.model_chip.update()

    # ------------------------------------------------------------------ state
    def set_conversation(self, conversation) -> None:  # noqa: ANN001
        self._conversation = conversation
        if conversation is None:
            self.title.setText(tr("chat.today_label"))
            self.subtitle.setText(f"{tr('header.offline')} · {tr('chat.local_mode')}")
            self.context_ring.set_usage(0.0, False)
            self.mode.set_value("chat", animate=False)
        else:
            display = conversation.title.strip() or tr("chat.untitled")
            self.title.setText(display)
            subtitle_parts = []
            if conversation.model_id:
                subtitle_parts.append(conversation.model_id)
            else:
                subtitle_parts.append(tr("header.no_model"))
            subtitle_parts.append(tr("nav.account"))
            self.subtitle.setText(" · ".join(subtitle_parts))
            self._update_context()
            self.mode.set_value(conversation.mode if conversation.mode in {"chat", "agent"} else "chat", animate=False)

    def _update_context(self) -> None:
        if self._conversation is None:
            self.context_ring.set_usage(0, False)
            return
        try:
            stats = self._service.stats(self._conversation.id)
        except Exception:
            stats = {"messages": 0, "input_tokens": 0, "output_tokens": 0}
        estimated = int(stats.get("input_tokens", 0)) + int(stats.get("output_tokens", 0))
        if not self._conversation.model_id:
            self.context_ring.set_usage(0, False)
            return
        window = 0
        self.context_ring.set_usage(estimated / window if window else 0.0, True)

    def set_model_choices(self, choices, current: str = "") -> None:
        self.model_chip.set_choices(choices, current)
        self.model_chip.set_placeholder(tr("header.model") if choices else tr("header.no_model"))

    def set_models(self, models: list[tuple[str, str]], current: str = "") -> None:
        self.model_chip.set_items(models)
        if current:
            self.model_chip.set_value(current)
        self.model_chip.set_placeholder(tr("header.no_model") if not models else tr("header.model"))

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.stop_button.setEnabled(generating)
        self.mode.setEnabled(not generating)
        self.inspector_button.setEnabled(True)
        self.model_chip.setEnabled(not generating)

    def set_section(self, title: str, subtitle: str = "") -> None:
        self._conversation = None
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.context_ring.set_usage(0, False)

    def set_mode(self, mode: str) -> None:
        self.mode.blockSignals(True)
        self.mode.set_value(mode, animate=True)
        self.mode.blockSignals(False)

    def set_inspector_open(self, open_state: bool) -> None:
        self.inspector_button.setChecked(open_state)

    def set_connection(self, state: str, text: str, tooltip: str = "") -> None:
        self._connection = (state, text, tooltip)
        tone = {"connected": "success", "local": "accent", "offline": "danger", "connecting": "warning"}.get(
            state, "accent"
        )
        self.status.set_status(text, tone, tooltip or text)

    def set_connection_key(self, state: str, key: str, tooltip_key: str = "") -> None:
        """Connect state declared with translation keys so language switches update it."""
        from ...i18n import tr as _tr

        self._connection_key = (state, key, tooltip_key)
        self.set_connection(state, _tr(key), _tr(tooltip_key) if tooltip_key else _tr(key))

    def _reapply_connection(self) -> None:
        key = getattr(self, "_connection_key", None)
        if key:
            self.set_connection_key(*key)
        else:
            self.set_connection(*self._connection)

    def set_context_usage(self, ratio: float, has_model: bool) -> None:
        self.context_ring.set_usage(ratio, has_model)

    # ------------------------------------------------------------------- menu
    def _show_more(self) -> None:
        c = runtime.theme().color
        menu = QMenu(self)
        menu.setLayoutDirection(self.layoutDirection())
        has_conversation = self._conversation is not None
        new_action = menu.addAction(icon("plus", c("text_muted"), 15), tr("nav.new_chat"))
        new_action.triggered.connect(self.new_chat_requested)
        menu.addSeparator()
        rename = menu.addAction(icon("edit", c("text_muted"), 15), tr("menu.rename"))
        rename.setEnabled(has_conversation)
        rename.triggered.connect(self.rename_requested)
        pin_text = tr("menu.unpin") if has_conversation and self._conversation.pinned else tr("menu.pin")
        pin = menu.addAction(icon("pin", c("text_muted"), 15), pin_text)
        pin.setEnabled(has_conversation)
        pin.triggered.connect(self.pin_requested)
        export = menu.addAction(icon("download", c("text_muted"), 15), tr("menu.export_md"))
        export.setEnabled(has_conversation)
        export.triggered.connect(self.export_requested)
        menu.addSeparator()
        search = menu.addAction(icon("search", c("text_muted"), 15), tr("nav.search"))
        search.triggered.connect(self.search_requested)
        settings = menu.addAction(icon("settings", c("text_muted"), 15), tr("menu.settings"))
        settings.triggered.connect(self.settings_requested)
        folder = menu.addAction(icon("folder", c("text_muted"), 15), tr("menu.open_folder"))
        folder.triggered.connect(self.data_folder_requested)
        about = menu.addAction(icon("info", c("text_muted"), 15), tr("menu.about"))
        about.triggered.connect(self.about_requested)
        menu.addSeparator()
        delete = menu.addAction(icon("trash", c("danger"), 15), tr("menu.delete"))
        delete.setEnabled(has_conversation)
        delete.triggered.connect(self.delete_requested)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    # ------------------------------------------------------------ i18n & theme
    def retranslate(self) -> None:
        self.model_chip.set_placeholder(tr("header.no_model"))
        self.model_chip._empty_action = (tr("inspector.open_settings"), self.settings_requested.emit)
        self.status.setToolTip(tr("nav.account_sub"))
        self._reapply_connection()
        self.stop_button.setToolTip(tr("header.stop"))
        self.inspector_button.setToolTip(tr("header.inspector"))
        self.more_button.setToolTip(tr("header.more"))
        self.mode.set_items([("chat", tr("header.chat")), ("agent", tr("header.agent"))])
        self._reapply_connection()
        self.set_conversation(self._conversation)

    def refresh_theme(self) -> None:
        self._refresh_icons()
        # Chips and the mode switcher paint with the current scale, so their
        # fixed sizes have to follow it too.
        for widget in (self.model_chip, self.mode):
            if hasattr(widget, "refresh_metrics"):
                widget.refresh_metrics()
        self.update()
