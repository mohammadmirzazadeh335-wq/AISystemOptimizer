"""The conversation navigator.

A custom model/delegate keeps the list fast and lets every row carry the
product's typography, hover states and folder grouping instead of looking like
a stock list widget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QEasingCurve,
    QModelIndex,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ...core.timeutil import relative_time
from ...i18n import tr
from ...services.conversations import ConversationService
from ..brand import LogoMark, Wordmark
from ..theme import runtime
from ..theme.icons import draw as draw_icon
from ..theme.icons import icon
from ..widgets.buttons import IconButton, NavButton
from ..widgets.dialogs import ConfirmDialog, PromptDialog
from ..widgets.feedback import Skeleton
from ..widgets.fields import SearchField
from ..widgets.foundation import EmptyState
from ..widgets.painting import paint_event

logger = logging.getLogger(__name__)

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass
class Row:
    kind: str  # "header" or "conversation"
    label: str = ""
    count: int = 0
    conversation_id: str = ""
    title: str = ""
    preview: str = ""
    time_text: str = ""
    pinned: bool = False
    color: str = ""
    has_messages: bool = True


class ConversationListModel(QAbstractListModel):
    def __init__(self, service: ConversationService) -> None:
        super().__init__()
        self._service = service
        self._rows: list[Row] = []
        self._language = "fa"

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == KIND_ROLE:
            return row.kind
        if role == ROW_ROLE:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return row.title if row.kind == "conversation" else row.label
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return row.title or row.label
        return None

    def refresh(self, search: str = "") -> None:
        language = runtime_language()
        self._language = language
        self.beginResetModel()
        self._rows = self._build_rows(search)
        self.endResetModel()

    def _build_rows(self, search: str) -> list[Row]:
        conversations = self._service.summaries(search=search)
        folders = self._service.folders()
        language = runtime_language()
        rows: list[Row] = []
        if search.strip():
            for conversation in conversations:
                rows.append(self._row_for(conversation, language))
            return rows
        pinned = [c for c in conversations if c.pinned]
        if pinned:
            rows.append(Row("header", label=tr("nav.pinned"), count=len(pinned)))
            rows.extend(self._row_for(c, language) for c in pinned)
        for folder in folders:
            group = [c for c in conversations if c.folder_id == folder.id and not c.pinned]
            if not group:
                continue
            rows.append(Row("header", label=folder.name, count=len(group), color=folder.color))
            rows.extend(self._row_for(c, language) for c in group)
        unfiled = [c for c in conversations if not c.folder_id and not c.pinned]
        if unfiled:
            if pinned or folders:
                rows.append(Row("header", label=tr("nav.recent"), count=len(unfiled)))
            rows.extend(self._row_for(c, language) for c in unfiled)
        return rows

    @staticmethod
    def _row_for(summary, language: str) -> Row:  # noqa: ANN001
        title = summary.display_title
        preview = summary.preview.strip()
        return Row(
            kind="conversation",
            conversation_id=summary.id,
            title=title,
            preview=preview,
            time_text=relative_time(summary.updated_at, language),
            pinned=summary.pinned,
            has_messages=summary.message_count > 0,
        )

    def row(self, index: QModelIndex) -> Row | None:
        if index.isValid() and 0 <= index.row() < len(self._rows):
            return self._rows[index.row()]
        return None

    def index_for_conversation(self, conversation_id: str) -> int:
        for row_index, row in enumerate(self._rows):
            if row.kind == "conversation" and row.conversation_id == conversation_id:
                return row_index
        return -1


def runtime_language() -> str:
    from ...i18n import current_language

    return current_language()


class ConversationDelegate(QStyledItemDelegate):
    HEADER_HEIGHT = 30
    ROW_HEIGHT = 60

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001
        row: Row = index.data(ROW_ROLE)
        height = self.HEADER_HEIGHT if row and row.kind == "header" else self.ROW_HEIGHT
        return QSize(option.rect.width(), runtime.px(height))

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        row: Row = index.data(ROW_ROLE)
        if row is None:
            return
        c = runtime.theme().color
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if row.kind == "header":
            painter.setFont(runtime.ui_font(9, 700))
            painter.setPen(QColor(c("text_faint")))
            pad = runtime.px(12)
            icon_size = runtime.px(11)
            marker_x = (rect.right() - pad - icon_size) if not rtl else (rect.left() + pad)
            marker_y = rect.center().y() - icon_size // 2 + runtime.px(2)
            marker = QRect(marker_x, marker_y, icon_size, icon_size)
            if row.color:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(row.color))
                painter.drawEllipse(marker.adjusted(1, 1, -1, -1))
            else:
                draw_icon(
                    painter,
                    "pin" if row.label == tr("nav.pinned") else "folder",
                    marker,
                    c("text_faint"),
                    1.8,
                )
            count_width = runtime.px(22) if row.count else 0
            if rtl:
                text_left = pad + icon_size + runtime.px(7)
                text_width = rect.width() - text_left - pad - count_width
                text_rect = QRect(rect.left() + text_left, rect.top(), max(10, text_width), rect.height())
                align = Qt.AlignmentFlag.AlignRight
                count_rect = QRect(rect.left() + pad, rect.top(), count_width, rect.height())
            else:
                text_left = pad + icon_size + runtime.px(7)
                text_width = rect.width() - text_left - pad - count_width
                text_rect = QRect(rect.left() + text_left, rect.top(), max(10, text_width), rect.height())
                align = Qt.AlignmentFlag.AlignLeft
                count_rect = QRect(rect.right() - pad - count_width, rect.top(), count_width, rect.height())
            metrics = QFontMetrics(painter.font())
            label = metrics.elidedText(row.label, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, align | Qt.AlignmentFlag.AlignVCenter, label)
            if row.count:
                painter.setFont(runtime.ui_font(9, 500))
                painter.setPen(QColor(c("text_faint")))
                painter.drawText(count_rect, Qt.AlignmentFlag.AlignCenter, str(row.count))
            painter.restore()
            return

        body = rect.adjusted(runtime.px(4), runtime.px(2), -runtime.px(4), -runtime.px(2))
        if selected:
            painter.setPen(QPen(QColor(runtime.theme().alpha("accent", 0.30)), 1))
            painter.setBrush(QColor(c("nav_active")))
            painter.drawRoundedRect(body, runtime.px(10), runtime.px(10))
            body.right() - runtime.px(2) if rtl else body.left() + runtime.px(1)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c("accent")))
            painter.drawRoundedRect(
                QRect(
                    body.right() - runtime.px(3) if rtl else body.left() + runtime.px(1),
                    body.center().y() - runtime.px(9),
                    runtime.px(2),
                    runtime.px(18),
                ),
                runtime.px(1),
                runtime.px(1),
            )
        elif hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c("nav_hover")))
            painter.drawRoundedRect(body, runtime.px(10), runtime.px(10))

        pad = runtime.px(11)
        text_area = body.adjusted(pad, runtime.px(7), -pad, -runtime.px(7))
        painter.setFont(runtime.ui_font(9, 400))
        time_metrics = QFontMetrics(painter.font())
        time_width = time_metrics.horizontalAdvance(row.time_text) + runtime.px(6) if row.time_text else 0
        pin_width = runtime.px(16) if row.pinned else 0

        painter.setFont(runtime.ui_font(12, 500))
        painter.setPen(QColor(c("text") if selected or hover else c("text_muted")))
        metrics = QFontMetrics(painter.font())
        title_width = text_area.width() - time_width - pin_width - runtime.px(4)
        title = metrics.elidedText(row.title, Qt.TextElideMode.ElideRight, max(20, title_width))
        align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        title_rect = QRect(
            text_area.left() + (pin_width if rtl else 0),
            text_area.top(),
            max(20, title_width),
            runtime.px(18),
        )
        painter.drawText(title_rect, align | Qt.AlignmentFlag.AlignVCenter, title)

        if row.pinned:
            pin_size = runtime.px(11)
            pin_x = text_area.left() if rtl else text_area.left() + title_width + runtime.px(3)
            draw_icon(
                painter,
                "pin",
                QRect(pin_x, text_area.top() + runtime.px(3), pin_size, pin_size),
                c("accent"),
                1.8,
            )

        painter.setFont(runtime.ui_font(10, 400))
        painter.setPen(QColor(c("text_faint")))
        preview = row.preview or ""
        preview_metrics = QFontMetrics(painter.font())
        preview = preview_metrics.elidedText(preview, Qt.TextElideMode.ElideRight, text_area.width())
        painter.drawText(
            QRect(text_area.left(), text_area.top() + runtime.px(19), text_area.width(), runtime.px(16)),
            align | Qt.AlignmentFlag.AlignVCenter,
            preview,
        )

        time_rect = QRect(
            text_area.left() if rtl else text_area.right() - time_width,
            text_area.top(),
            max(time_width, runtime.px(1)),
            runtime.px(16),
        )
        painter.setFont(runtime.ui_font(9, 400))
        painter.setPen(QColor(c("text_faint")))
        painter.drawText(
            time_rect,
            (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter,
            row.time_text,
        )
        painter.restore()


class SidebarResizeGrip(QWidget):
    width_committed = Signal(int)

    def __init__(self, sidebar: "Sidebar") -> None:
        super().__init__(sidebar)
        self._sidebar = sidebar
        self._dragging = False
        self._start_x = 0
        self._start_width = 0
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setFixedWidth(runtime.px(6))
        self.setToolTip(tr("nav.collapse"))
        self._hover = False
        self.setMouseTracking(True)

    def reposition(self) -> None:
        if not self._sidebar.is_collapsed:
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            x = 0 if rtl else self._sidebar.width() - self.width()
            self.setGeometry(x, 0, self.width(), self._sidebar.height())
            self.raise_()

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_x = int(event.globalPosition().x())
            self._start_width = self._sidebar.width()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        if not self._dragging:
            return
        delta = int(event.globalPosition().x()) - self._start_x
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            delta = -delta
        width = max(runtime.px(240), min(runtime.px(420), self._start_width + delta))
        self._sidebar.set_manual_width(width)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if self._dragging:
            self._dragging = False
            self.width_committed.emit(self._sidebar.logical_width)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        if not self._hover:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(runtime.theme().color("accent"))
        color.setAlpha(120)
        painter.setBrush(color)
        x = self.width() // 2 - runtime.px(1)
        painter.drawRoundedRect(x, self.height() // 2 - runtime.px(16), runtime.px(2), runtime.px(32), 1, 1)
class Sidebar(QFrame):
    new_chat_requested = Signal()
    conversation_selected = Signal(str)
    library_requested = Signal(str)
    settings_requested = Signal()
    collapsed_changed = Signal(bool)
    width_committed = Signal(int)
    notify = Signal(str, str)

    AI_PAGES = [
        ("api", "key", "nav.api"),
        ("memory", "database", "nav.memory"),
        ("persona", "user", "nav.persona"),
        ("studio", "code", "nav.studio"),
    ]

    LIBRARY = [
        ("agent", "sparkles", "nav.agent"),
        ("code", "code", "nav.code"),
        ("images", "image", "nav.images"),
        ("web", "globe", "nav.web"),
        ("prompts", "book", "nav.prompts"),
        ("tasks", "list-check", "nav.tasks"),
        ("performance", "gauge", "nav.performance"),
    ]

    def __init__(self, service: ConversationService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setProperty("panel", "sidebar")
        self._service = service
        self._collapsed = False
        self._active_route = "chat"
        self._expanded_width_px = runtime.px(288)
        self._loading_timer = QTimer(self)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(140)
        self._search_timer.timeout.connect(self.refresh)
        self._setup_ui()
        self._apply_width(self._expanded_width_px)
        self._refresh_new_chat_icon()
        self._update_collapse_icon()
        self._search_timer.stop()

    # ------------------------------------------------------------------- build
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(runtime.px(12), runtime.px(12), runtime.px(12), runtime.px(12))
        outer.setSpacing(runtime.px(4))

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(runtime.px(4), 0, runtime.px(2), 0)
        brand_row.setSpacing(runtime.px(9))
        self.logo = LogoMark(32)
        brand_row.addWidget(self.logo)
        self.wordmark = Wordmark()
        brand_row.addWidget(self.wordmark, 1)
        self.collapse_button = IconButton("panel-left", tr("nav.collapse"), 30, icon_size=15)
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        brand_row.addWidget(self.collapse_button)
        outer.addLayout(brand_row)
        outer.addSpacing(runtime.px(8))

        self.new_chat_button = QPushButton(tr("nav.new_chat"))
        self.new_chat_button.setProperty("variant", "primary")
        self.new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_button.setMinimumHeight(runtime.px(38))
        self.new_chat_button.setToolTip(tr("nav.new_chat_hint"))
        self.new_chat_button.clicked.connect(self.new_chat_requested)
        outer.addWidget(self.new_chat_button)

        self.search = SearchField(tr("nav.search"))
        self.search.text_changed.connect(lambda _: self._search_timer.start())
        self.search_button = IconButton("search", tr("nav.search"), 30, icon_size=16)
        self.search_button.clicked.connect(self._expand_and_search)
        self.search_button.hide()
        outer.addWidget(self.search)
        outer.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignHCenter)

        chats_header = QHBoxLayout()
        chats_header.setContentsMargins(runtime.px(8), runtime.px(8), 0, 0)
        self.chats_label = QLabel(tr("nav.chats"))
        self.chats_label.setProperty("role", "section")
        chats_header.addWidget(self.chats_label)
        chats_header.addStretch(1)
        self.folder_button = IconButton("folder-plus", tr("nav.new_folder"), 26, icon_size=14)
        self.folder_button.clicked.connect(self._new_folder)
        chats_header.addWidget(self.folder_button)
        outer.addLayout(chats_header)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.list_view = QListView()
        self.list_view.setObjectName("ConversationList")
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setMouseTracking(True)
        self.list_view.setUniformItemSizes(False)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.setStyleSheet("background: transparent; border: none;")
        self.list_view.setSpacing(0)
        self.model = ConversationListModel(self._service)
        self.delegate = ConversationDelegate(self.list_view)
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.list_view.customContextMenuRequested.connect(self._conversation_menu)
        self.list_view.clicked.connect(self._on_click)
        self.list_view.activated.connect(self._on_click)
        self._stack.addWidget(self.list_view)

        self.empty_state = EmptyState(
            tr("nav.no_chats"),
            tr("nav.no_chats_hint"),
            "chat",
            compact=True,
        )
        self._stack.addWidget(self.empty_state)

        skeleton_page = QWidget()
        skeleton_layout = QVBoxLayout(skeleton_page)
        skeleton_layout.setContentsMargins(runtime.px(8), runtime.px(10), runtime.px(8), runtime.px(8))
        skeleton_layout.setSpacing(runtime.px(10))
        for index in range(5):
            skeleton = Skeleton(height=12, radius=6)
            skeleton_layout.addWidget(skeleton)
            if index == 0:
                skeleton_layout.addSpacing(runtime.px(18))
        skeleton_layout.addStretch(1)
        self._stack.addWidget(skeleton_page)
        self._stack.setCurrentWidget(skeleton_page)
        self._loading_timer.timeout.connect(self._initial_load)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.start(160)
        outer.addWidget(self._stack, 1)

        divider = QFrame()
        divider.setProperty("panel", "divider")
        outer.addWidget(divider)
        self.library_label = QLabel(tr("nav.library"))
        self.library_label.setProperty("role", "section")
        self.library_label.setContentsMargins(runtime.px(8), runtime.px(4), 0, runtime.px(2))
        outer.addWidget(self.library_label)

        self.nav_buttons: dict[str, NavButton] = {}
        for key, icon_name, label_key in self.LIBRARY:
            button = NavButton(tr(label_key), icon_name)
            button.clicked.connect(lambda _=False, k=key: self._activate_route(k))
            self.nav_buttons[key] = button
            outer.addWidget(button)

        self.ai_label = QLabel(tr("nav.ai_section"))
        self.ai_label.setProperty("role", "section")
        self.ai_label.setContentsMargins(runtime.px(8), runtime.px(6), 0, runtime.px(2))
        outer.addWidget(self.ai_label)
        for key, icon_name, label_key in self.AI_PAGES:
            button = NavButton(tr(label_key), icon_name)
            button.clicked.connect(lambda _=False, k=key: self._activate_route(k))
            self.nav_buttons[key] = button
            outer.addWidget(button)

        outer.addStretch(0)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, runtime.px(4), 0, 0)
        bottom.setSpacing(runtime.px(6))
        self.settings_button = NavButton(tr("nav.settings"), "settings")
        self.settings_button.clicked.connect(self.settings_requested)
        self.settings_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bottom.addWidget(self.settings_button, 1)
        outer.addLayout(bottom)

        self.account = QFrame()
        self.account.setObjectName("AccountCard")
        self.account.setStyleSheet(
            f"QFrame#AccountCard {{ background-color: {runtime.theme().color('surface')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(11)}px; }}"
        )
        account_layout = QHBoxLayout(self.account)
        account_layout.setContentsMargins(runtime.px(8), runtime.px(7), runtime.px(8), runtime.px(7))
        account_layout.setSpacing(runtime.px(8))
        self.account_avatar = LogoMark(26)
        account_layout.addWidget(self.account_avatar)
        account_text = QVBoxLayout()
        account_text.setSpacing(0)
        self.account_title = QLabel(tr("nav.account"))
        self.account_title.setStyleSheet("font-weight: 600;")
        self.account_sub = QLabel(tr("nav.account_sub"))
        self.account_sub.setProperty("role", "faint")
        self.account_sub.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        account_text.addWidget(self.account_title)
        account_text.addWidget(self.account_sub)
        account_layout.addLayout(account_text, 1)
        self.connection_dot = QLabel()
        self.connection_dot.setPixmap(runtime.icons().px("check", 13, "accent"))
        account_layout.addWidget(self.connection_dot)
        outer.addWidget(self.account)

        self.grip = SidebarResizeGrip(self)
        self.grip.width_committed.connect(self.width_committed)
        self.grip.show()

    # ------------------------------------------------------------------ actions
    def _initial_load(self) -> None:
        self._stack.setCurrentWidget(self.list_view)
        self.refresh()
        self.select_current(None)

    def refresh(self) -> None:
        self.model.refresh(self.search.text())
        rows = self.model.rowCount()
        if rows == 0:
            if self.search.text().strip():
                self.empty_state.title_label.setText(tr("nav.no_results"))
                self.empty_state.body_label.setText(tr("nav.no_results_hint"))
            else:
                self.empty_state.title_label.setText(tr("nav.no_chats"))
                self.empty_state.body_label.setText(tr("nav.no_chats_hint"))
            self._stack.setCurrentWidget(self.empty_state)
        else:
            self._stack.setCurrentWidget(self.list_view)

    def select_conversation(self, conversation_id: str) -> None:
        self._active_route = "chat"
        self._clear_library_checks()
        index = self.model.index_for_conversation(conversation_id)
        if index >= 0:
            model_index = self.model.index(index, 0)
            self.list_view.setCurrentIndex(model_index)
            self.list_view.scrollTo(model_index, QAbstractItemView.ScrollHint.EnsureVisible)
        self.conversation_selected.emit(conversation_id)

    def sync_selection(self, conversation_id: str | None) -> None:
        self._active_route = "chat"
        self._clear_library_checks()
        self.select_current(conversation_id)

    def select_current(self, conversation_id: str | None) -> None:
        if not conversation_id:
            self.list_view.clearSelection()
            return
        index = self.model.index_for_conversation(conversation_id)
        if index >= 0:
            self.list_view.setCurrentIndex(self.model.index(index, 0))

    def _on_click(self, index: QModelIndex) -> None:
        row = self.model.row(index)
        if row and row.kind == "conversation":
            self._active_route = "chat"
            self._clear_library_checks()
            self.conversation_selected.emit(row.conversation_id)

    def _activate_route(self, key: str) -> None:
        self._active_route = key
        self._clear_library_checks()
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        self.library_requested.emit(key)

    def _clear_library_checks(self) -> None:
        for button in self.nav_buttons.values():
            button.setChecked(False)

    def set_active(self, route: str) -> None:
        self._active_route = route
        self._clear_library_checks()
        if route in self.nav_buttons:
            self.nav_buttons[route].setChecked(True)
        self.list_view.clearSelection()

    def focus_search(self) -> None:
        if self._collapsed:
            self.set_collapsed(False)
        self.search.focus()

    def _expand_and_search(self) -> None:
        self.set_collapsed(False)
        QTimer.singleShot(240, self.search.focus)

    # ------------------------------------------------------------------ folders
    def _new_folder(self) -> None:
        dialog = PromptDialog(
            self.window(),
            tr("dialog.new_folder"),
            tr("nav.folder_name"),
            confirm_text=tr("dialog.create"),
            cancel_text=tr("dialog.cancel"),
            required_text=tr("dialog.required"),
        )
        if dialog.exec():
            self._service.create_folder(dialog.value())
            self.refresh()
            self.notify.emit(tr("toast.saved"), "success")

    def _rename_conversation(self, row: Row) -> None:
        dialog = PromptDialog(
            self.window(),
            tr("dialog.rename_chat"),
            tr("dialog.name"),
            value=row.title,
            confirm_text=tr("dialog.save"),
            cancel_text=tr("dialog.cancel"),
            required_text=tr("dialog.required"),
        )
        if dialog.exec():
            self._service.rename(row.conversation_id, dialog.value())
            self.refresh()

    def _delete_conversation(self, row: Row) -> None:
        dialog = ConfirmDialog(
            self.window(),
            tr("dialog.delete_chat_title"),
            tr("dialog.delete_chat_body", title=row.title),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="trash",
        )
        if dialog.exec():
            self._service.delete(row.conversation_id)
            self.refresh()
            self.notify.emit(tr("chat.deleted"), "success")

    def _export_conversation(self, row: Row) -> None:
        from PySide6.QtWidgets import QFileDialog

        from ...core.paths import default_projects_dir

        suggested = f"{row.title.strip() or 'conversation'}.md".replace("/", "-")
        default_path = str(default_projects_dir() / suggested)
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("menu.export_md"), default_path, "Markdown (*.md)")
        if not path:
            return
        try:
            self._service.export_markdown(row.conversation_id, path)
            self.notify.emit(tr("dialog.export_done", path=path), "success")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")

    def _conversation_menu(self, position) -> None:  # noqa: ANN001
        index = self.list_view.indexAt(position)
        row = self.model.row(index) if index.isValid() else None
        menu = QMenu(self)
        menu.setLayoutDirection(self.layoutDirection())
        if row is None:
            new_action = menu.addAction(icon("plus", runtime.theme().color("text_muted"), 15), tr("nav.new_chat"))
            new_action.triggered.connect(self.new_chat_requested)
            menu.addSeparator()
            folder_action = menu.addAction(icon("folder-plus", runtime.theme().color("text_muted"), 15), tr("nav.new_folder"))
            folder_action.triggered.connect(self._new_folder)
        elif row.kind == "header":
            if row.label in {tr("nav.pinned"), tr("nav.recent")}:
                return
            folder = next((f for f in self._service.folders() if f.name == row.label), None)
            if folder:
                rename = menu.addAction(icon("edit", runtime.theme().color("text_muted"), 15), tr("dialog.rename"))
                rename.triggered.connect(lambda: self._rename_folder(folder.id, folder.name))
                delete = menu.addAction(icon("trash", runtime.theme().color("danger"), 15), tr("menu.delete"))
                delete.triggered.connect(lambda: self._delete_folder(folder.id))
        else:
            rename = menu.addAction(icon("edit", runtime.theme().color("text_muted"), 15), tr("menu.rename"))
            rename.triggered.connect(lambda: self._rename_conversation(row))
            pin_text = tr("menu.unpin") if row.pinned else tr("menu.pin")
            pin = menu.addAction(icon("pin", runtime.theme().color("text_muted"), 15), pin_text)
            pin.triggered.connect(lambda: self._toggle_pin(row))
            folders = self._service.folders()
            if folders:
                submenu = menu.addMenu(icon("folder", runtime.theme().color("text_muted"), 15), tr("menu.move_folder"))
                submenu.setLayoutDirection(self.layoutDirection())
                for folder in folders:
                    action = submenu.addAction(folder.name)
                    action.triggered.connect(
                        lambda _=False, f=folder: self._move_to_folder(row, f.id)
                    )
                if row and self._folder_of(row):
                    clear = submenu.addAction(tr("nav.chats"))
                    clear.triggered.connect(lambda: self._move_to_folder(row, None))
            menu.addSeparator()
            export = menu.addAction(icon("download", runtime.theme().color("text_muted"), 15), tr("menu.export_md"))
            export.triggered.connect(lambda: self._export_conversation(row))
            menu.addSeparator()
            delete = menu.addAction(icon("trash", runtime.theme().color("danger"), 15), tr("menu.delete"))
            delete.triggered.connect(lambda: self._delete_conversation(row))
        menu.exec(self.list_view.viewport().mapToGlobal(position))

    def _folder_of(self, row: Row) -> str | None:
        conversation = self._service.get(row.conversation_id)
        return conversation.folder_id

    def _toggle_pin(self, row: Row) -> None:
        self._service.set_pinned(row.conversation_id, not row.pinned)
        self.refresh()

    def _move_to_folder(self, row: Row, folder_id: str | None) -> None:
        self._service.move_to_folder(row.conversation_id, folder_id)
        self.refresh()

    def _rename_folder(self, folder_id: str, current: str) -> None:
        dialog = PromptDialog(
            self.window(),
            tr("dialog.rename"),
            tr("nav.folder_name"),
            value=current,
            confirm_text=tr("dialog.save"),
            cancel_text=tr("dialog.cancel"),
            required_text=tr("dialog.required"),
        )
        if dialog.exec():
            self._service.rename_folder(folder_id, dialog.value())
            self.refresh()

    def _delete_folder(self, folder_id: str) -> None:
        dialog = ConfirmDialog(
            self.window(),
            tr("dialog.delete_folder_title"),
            tr("dialog.delete_folder_body"),
            confirm_text=tr("dialog.delete"),
            cancel_text=tr("dialog.cancel"),
            danger=True,
            icon="folder",
        )
        if dialog.exec():
            self._service.delete_folder(folder_id)
            self.refresh()

    # ----------------------------------------------------------------- collapse
    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def _apply_width(self, width: int) -> None:
        width = int(width)
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.grip.reposition()

    def set_manual_width(self, width_px: int) -> None:
        if self._collapsed:
            return
        width_px = max(runtime.px(240), min(runtime.px(420), int(width_px)))
        self._expanded_width_px = width_px
        self._apply_width(width_px)
        self.updateGeometry()

    def set_preferred_width(self, logical_width: int) -> None:
        self._expanded_width_px = max(runtime.px(240), min(runtime.px(420), runtime.px(logical_width)))
        self._apply_width(self._expanded_width_px)

    @property
    def logical_width(self) -> int:
        return round(self.width() / max(runtime.scale(), 0.01))

    def set_collapsed(self, collapsed: bool, *, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_collapsed_visibility(collapsed)
        # Wide enough for the icon buttons plus their own margins; too narrow and
        # Qt clips the centred icons into vertical slices.
        target = runtime.px(88) if collapsed else self._expanded_width_px
        if animate:
            group = QParallelAnimationGroup(self)
            for prop in (b"minimumWidth", b"maximumWidth"):
                anim = QPropertyAnimation(self, prop, group)
                anim.setDuration(210)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.setStartValue(self.width())
                anim.setEndValue(int(target))
                group.addAnimation(anim)
            group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
        else:
            self._apply_width(int(target))
        self.collapsed_changed.emit(collapsed)
        self.grip.setVisible(not collapsed)
        QTimer.singleShot(230, self.grip.reposition)
        self._update_collapse_icon()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _update_collapse_icon(self) -> None:
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        if self._collapsed:
            self.collapse_button.set_icon_name("panel-right" if not rtl else "panel-left")
            self.collapse_button.setToolTip(tr("nav.expand"))
        else:
            self.collapse_button.set_icon_name("panel-left" if not rtl else "panel-right")
            self.collapse_button.setToolTip(tr("nav.collapse"))

    def _apply_collapsed_visibility(self, collapsed: bool) -> None:
        self.wordmark.setVisible(not collapsed)
        self.search.setVisible(not collapsed)
        self.search_button.setVisible(collapsed)
        self.chats_label.setVisible(not collapsed)
        self.folder_button.setVisible(not collapsed)
        self.library_label.setVisible(not collapsed)
        self.ai_label.setVisible(not collapsed)
        for button in self.nav_buttons.values():
            button.set_collapsed(collapsed)
        self.settings_button.set_collapsed(collapsed)
        self.account_sub.setVisible(not collapsed)
        self.account_title.setVisible(not collapsed)
        self.account_avatar.setVisible(not collapsed)
        self.account_title.setVisible(not collapsed)
        self.account.setStyleSheet(
            f"QFrame#AccountCard {{ background-color: {runtime.theme().color('surface')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(11)}px; }}"
        )
        if collapsed:
            self._stack.hide()
            self.chats_label.hide()
            self.search.hide()
            self.new_chat_button.setText("")
            self.new_chat_button.setFixedWidth(runtime.px(40))
            self.new_chat_button.setFixedHeight(runtime.px(40))
        else:
            self._stack.show()
            self.chats_label.show()
            self.new_chat_button.setText(tr("nav.new_chat"))
            self.new_chat_button.setMinimumWidth(0)
            self.new_chat_button.setMaximumWidth(16777215)
            self.new_chat_button.setMinimumHeight(runtime.px(38))
            self.new_chat_button.setMaximumHeight(16777215)
        self._refresh_new_chat_icon()
        self._update_collapse_icon()

    def _refresh_new_chat_icon(self) -> None:
        color = runtime.theme().color("accent_contrast")
        self.new_chat_button.setIcon(icon("plus", color, 15, 2.2))
        self.new_chat_button.setIconSize(QSize(runtime.px(15), runtime.px(15)))

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.grip.reposition()

    # --------------------------------------------------------------- themes/i18n
    def refresh_theme(self) -> None:
        self.account.setStyleSheet(
            f"QFrame#AccountCard {{ background-color: {runtime.theme().color('surface')};"
            f" border: 1px solid {runtime.theme().color('border')};"
            f" border-radius: {runtime.px(11)}px; }}"
        )
        self._refresh_new_chat_icon()
        self.update()

    def retranslate(self) -> None:
        self.collapse_button.setToolTip(tr("nav.collapse") if not self._collapsed else tr("nav.expand"))
        self.new_chat_button.setText(tr("nav.new_chat") if not self._collapsed else "")
        self.new_chat_button.setToolTip(tr("nav.new_chat_hint"))
        self.search.set_placeholder(tr("nav.search"))
        self.search_button.setToolTip(tr("nav.search"))
        self.chats_label.setText(tr("nav.chats"))
        self.folder_button.setToolTip(tr("nav.new_folder"))
        self.library_label.setText(tr("nav.library"))
        self.ai_label.setText(tr("nav.ai_section"))
        for key, _icon, label_key in self.LIBRARY + self.AI_PAGES:
            button = self.nav_buttons.get(key)
            if button is not None:
                button.set_text(tr(label_key))
        self.settings_button.set_text(tr("nav.settings"))
        self.account_title.setText(tr("nav.account"))
        self.account_sub.setText(tr("nav.account_sub"))
        self.empty_state.title_label.setText(tr("nav.no_chats"))
        self.empty_state.body_label.setText(tr("nav.no_chats_hint"))
        self.refresh()
