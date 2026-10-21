"""Chat and welcome surfaces.

The welcome screen is the product's front door; message rendering is the daily
workspace.  Both share the same tokens, motion language and typography.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QRect,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.timeutil import format_datetime, relative_time
from ...i18n import current_language, tr
from ...version import PHASE, VERSION
from ..brand import LogoMark
from ..theme import runtime
from ..theme.icons import draw as draw_icon
from ..theme.icons import icon
from ..widgets.buttons import IconButton
from ..widgets.foundation import Avatar, Badge, BusyIndicator, GradientHeadline
from ..widgets.markdown_view import MarkdownView
from ..widgets.painting import paint_event


class SuggestionCard(QAbstractButton):
    def __init__(self, icon_name: str, title: str, subtitle: str, prompt: str, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._icon = icon_name
        self._title = title
        self._subtitle = subtitle
        self.prompt = prompt
        self._hover = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(runtime.px(92))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        runtime.signals.changed.connect(lambda *_: self.update())

    def _set_hover(self, value) -> None:  # noqa: ANN001
        self._hover = float(value)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = runtime.px(14)
        base = QColor(c("surface"))
        hover_color = QColor(c("surface_2"))
        mix = (hover_color.red() - base.red(), hover_color.green() - base.green(), hover_color.blue() - base.blue())
        painter.setBrush(
            QColor(
                int(base.red() + mix[0] * self._hover),
                int(base.green() + mix[1] * self._hover),
                int(base.blue() + mix[2] * self._hover),
            )
        )
        border = QColor(c("border"))
        accent = QColor(c("accent"))
        border_color = QColor(
            int(border.red() + (accent.red() - border.red()) * self._hover * 0.65),
            int(border.green() + (accent.green() - border.green()) * self._hover * 0.65),
            int(border.blue() + (accent.blue() - border.blue()) * self._hover * 0.65),
        )
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect, radius, radius)

        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        pad = runtime.px(15)
        icon_size = runtime.px(30)
        ix = rect.right() - pad - icon_size if rtl else rect.left() + pad
        icon_circle = QRectF(ix, rect.top() + pad, icon_size, icon_size)
        soft = QColor(c("accent"))
        soft.setAlpha(26)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft)
        painter.drawEllipse(icon_circle)
        draw_icon(
            painter,
            self._icon,
            icon_circle.adjusted(runtime.px(8), runtime.px(8), -runtime.px(8), -runtime.px(8)),
            c("accent"),
            1.8,
        )
        arrow_size = runtime.px(14)
        ax = rect.left() + pad if rtl else rect.right() - pad - arrow_size
        draw_icon(
            painter,
            "arrow-up-right",
            QRectF(ax, rect.top() + pad + runtime.px(2), arrow_size, arrow_size),
            c("text_faint"),
            1.8,
        )
        text_left = pad
        text_right = rect.width() - pad
        if rtl:
            text_right -= icon_size + runtime.px(10)
        else:
            text_left += icon_size + runtime.px(10)
        painter.setFont(runtime.ui_font(12, 600))
        painter.setPen(QColor(c("text")))
        title_rect = QRect(int(text_left), int(rect.top() + pad), int(text_right - text_left), runtime.px(20))
        metrics = QFontMetrics(painter.font())
        painter.drawText(
            title_rect,
            (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(self._title, Qt.TextElideMode.ElideRight, title_rect.width()),
        )
        painter.setFont(runtime.ui_font(10))
        painter.setPen(QColor(c("text_faint")))
        sub_rect = QRect(
            int(text_left),
            int(rect.top() + pad + runtime.px(24)),
            int(text_right - text_left),
            runtime.px(30),
        )
        painter.drawText(
            sub_rect,
            (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            self._subtitle,
        )
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(c("ring")), 1))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
class TrustChip(QWidget):
    def __init__(self, icon_name: str, text: str, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._icon = icon_name
        self._text = text
        self.setFixedHeight(runtime.px(25))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._recalc()
        runtime.signals.changed.connect(lambda *_: self._recalc())

    def _recalc(self) -> None:
        """Chip width follows its text so a language switch never clips it."""
        metrics = QFontMetrics(runtime.ui_font(9, 500))
        self.setFixedWidth(metrics.horizontalAdvance(self._text) + runtime.px(32))
        self.updateGeometry()

    def set_text(self, text: str) -> None:
        self._text = text
        self._recalc()

    def text(self) -> str:
        return self._text

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(c("border")), 1))
        painter.setBrush(QColor(c("surface")))
        painter.drawRoundedRect(rect, runtime.px(9), runtime.px(9))
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        pad = runtime.px(9)
        icon_size = runtime.px(12)
        ix = rect.right() - pad - icon_size if rtl else rect.left() + pad
        draw_icon(
            painter,
            self._icon,
            QRectF(ix, (self.height() - icon_size) / 2, icon_size, icon_size),
            c("text_faint"),
            1.8,
        )
        painter.setFont(runtime.ui_font(9, 500))
        painter.setPen(QColor(c("text_faint")))
        painter.drawText(
            self.rect().adjusted(pad + icon_size + runtime.px(6), 0, -pad, 0),
            Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft),
            self._text,
        )
class WelcomePage(QWidget):
    prompt_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = _WelcomeContent()
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)
        self.cards: list[SuggestionCard] = []
        for index in range(1, 5):
            card = SuggestionCard(
                ["sparkles", "type", "code", "globe"][index - 1],
                tr(f"chat.suggestion_{index}_title"),
                tr(f"chat.suggestion_{index}_sub"),
                tr(f"chat.suggestion_{index}_prompt"),
            )
            card.clicked.connect(lambda _=False, c=card: self.prompt_chosen.emit(c.prompt))
            self.cards.append(card)
            self.content.add_card(card)
        self.content.reflow()
        self._faded = False

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        if not self._faded:
            self._faded = True
            self._fade_in()

    def _fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self.content)
        effect.setOpacity(0.0)
        self.content.setGraphicsEffect(effect)
        anim = QVariantAnimation(self)
        anim.setDuration(320)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _tick(value) -> None:  # noqa: ANN001
            effect.setOpacity(float(value))

        anim.valueChanged.connect(_tick)
        anim.finished.connect(lambda: self.content.setGraphicsEffect(None))
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def retranslate(self) -> None:
        for index, card in enumerate(self.cards, start=1):
            card._title = tr(f"chat.suggestion_{index}_title")
            card._subtitle = tr(f"chat.suggestion_{index}_sub")
            card.prompt = tr(f"chat.suggestion_{index}_prompt")
            card.update()
        self.content.retranslate()


class _WelcomeContent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WelcomeContent")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(40), runtime.px(46), runtime.px(40), runtime.px(30))
        layout.setSpacing(runtime.px(14))
        layout.addStretch(1)

        self.eyebrow_row = QHBoxLayout()
        self.eyebrow_row.setSpacing(runtime.px(7))
        self.eyebrow_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sparkle = QLabel()
        sparkle.setPixmap(runtime.icons().px("sparkles", 13, "accent"))
        self.eyebrow_row.addWidget(sparkle)
        self.eyebrow = QLabel(tr("chat.welcome_eyebrow"))
        self.eyebrow.setProperty("role", "eyebrow")
        self.eyebrow_row.addWidget(self.eyebrow)
        version_badge = Badge(f"v{VERSION} · {tr('placeholder.phase_badge', phase=PHASE)}", "outline")
        self._version_badge = version_badge
        self.eyebrow_row.addWidget(version_badge)
        layout.addLayout(self.eyebrow_row)

        self.headline = GradientHeadline(tr("chat.welcome_title"), 34)
        layout.addWidget(self.headline)

        self.subtitle = QLabel(tr("chat.welcome_sub"))
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setMaximumWidth(runtime.px(660))
        self.subtitle.setMinimumHeight(runtime.px(44))
        self.subtitle.setStyleSheet(f"font-size: {runtime.px(13)}px; line-height: 160%;")
        layout.addWidget(self.subtitle, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(runtime.px(8))

        self.grid = QGridLayout()
        self.grid.setSpacing(runtime.px(12))
        layout.addLayout(self.grid)
        layout.addSpacing(runtime.px(8))

        trust_row = QHBoxLayout()
        trust_row.setSpacing(runtime.px(7))
        trust_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._trust_chips = []
        for icon_name, key in (
            ("lock", "chat.trust_local"),
            ("shield", "chat.trust_secret"),
            ("terminal", "chat.trust_real"),
        ):
            chip = TrustChip(icon_name, tr(key))
            self._trust_chips.append((chip, key))
            trust_row.addWidget(chip)
        layout.addLayout(trust_row)
        layout.addStretch(1)
        self._cards: list[QWidget] = []

    @paint_event
    def paintEvent(self, painter: QPainter, event) -> None:  # noqa: ANN001  # noqa: ANN001
        c = runtime.theme().color
        w, h = self.width(), self.height()
        top = QColor(c("ambient_a"))
        top.setAlpha(48 if runtime.theme().is_dark else 70)
        bottom = QColor(c("ambient_b"))
        bottom.setAlpha(36 if runtime.theme().is_dark else 55)
        grad = QRadialGradient(w * 0.5, -h * 0.15, max(w, h) * 0.9)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad)
        grad2 = QRadialGradient(w * 0.85, h * 0.9, max(w, h) * 0.5)
        grad2.setColorAt(0.0, bottom)
        grad2.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad2)
    def add_card(self, card: QWidget) -> None:
        self._cards.append(card)

    def reflow(self) -> None:
        width = self.width()
        columns = 1 if width and width < runtime.px(720) else 2
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
        for index, card in enumerate(self._cards):
            row, col = divmod(index, columns)
            self.grid.addWidget(card, row, col)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self.reflow()

    def retranslate(self) -> None:
        self.eyebrow.setText(tr("chat.welcome_eyebrow"))
        self.headline.setText(tr("chat.welcome_title"))
        self.subtitle.setText(tr("chat.welcome_sub"))
        if hasattr(self, "_version_badge"):
            self._version_badge.setText(f"v{VERSION} · {tr('placeholder.phase_badge', phase=PHASE)}")
        for chip, key in getattr(self, "_trust_chips", []):
            chip.set_text(tr(key))


class NoticeCard(QFrame):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NoticeCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(runtime.px(12), runtime.px(9), runtime.px(12), runtime.px(9))
        layout.setSpacing(runtime.px(8))
        icon_label = QLabel()
        icon_label.setPixmap(runtime.icons().px("info", 14, "warning"))
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.setStyleSheet(
            f"QFrame#NoticeCard {{ background-color: {runtime.theme().color('warning_soft')};"
            f" border: 1px solid {runtime.theme().alpha('warning', 0.3)};"
            f" border-radius: {runtime.px(10)}px; }}"
            f" QLabel {{ color: {runtime.theme().color('warning')}; font-size: {runtime.px(11)}px; }}"
        )


class MessageCard(QWidget):
    delete_requested = Signal(str)
    export_requested = Signal(str, str)
    retry_requested = Signal(str)
    notify = Signal(str, str)

    def __init__(self, message, *, parent: QWidget | None = None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.message = message
        self._language = current_language()
        self._build()

    def _build(self) -> None:
        is_user = self.message.role == "user"
        row = QHBoxLayout(self)
        row.setContentsMargins(0, runtime.px(6), 0, runtime.px(6))
        row.setSpacing(runtime.px(11))

        avatar: QWidget
        if is_user:
            avatar = Avatar("ش" if self._language == "fa" else "Y", 26)
        else:
            avatar = LogoMark(26)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(runtime.px(5))

        header = QHBoxLayout()
        header.setSpacing(runtime.px(7))
        name = QLabel(tr("chat.you") if is_user else tr("chat.assistant"))
        name.setStyleSheet("font-weight: 600;")
        name.setProperty("role", "muted" if is_user else "accent")
        header.addWidget(name)
        if not is_user and self.message.model_id:
            header.addWidget(Badge(self.message.model_id.split("/")[-1][:28], "violet"))
        timestamp = QLabel(relative_time(self.message.created_at, self._language))
        timestamp.setProperty("role", "faint")
        timestamp.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        header.addWidget(timestamp)
        header.addStretch(1)
        if not is_user:
            copy_button = IconButton("copy", tr("chat.copy"), 24, icon_size=12)
            copy_button.clicked.connect(self._copy)
            header.addWidget(copy_button)
        more = IconButton("more", tr("chat.message_actions"), 24, icon_size=14)
        more.clicked.connect(self._menu)
        header.addWidget(more)
        content_layout.addLayout(header)

        if is_user:
            bubble = QFrame()
            bubble.setObjectName("UserBubble")
            bubble.setStyleSheet(
                f"QFrame#UserBubble {{ background-color: {runtime.theme().color('bubble_user')};"
                f" border: 1px solid {runtime.theme().alpha('accent', 0.22)};"
                f" border-radius: {runtime.px(13)}px; }}"
            )
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(runtime.px(13), runtime.px(9), runtime.px(13), runtime.px(9))
            text = QLabel(self.message.content)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setStyleSheet(f"font-size: {runtime.px(13)}px;")
            bubble_layout.addWidget(text)
            attachments = (self.message.meta or {}).get("attachments") or []
            if attachments:
                chips = QHBoxLayout()
                chips.setSpacing(runtime.px(5))
                for attachment in attachments:
                    badge = Badge(f"{attachment.get('name', 'file')}", "muted")
                    chips.addWidget(badge)
                chips.addStretch(1)
                bubble_layout.addLayout(chips)
            content_layout.addWidget(bubble)
        else:
            view = MarkdownView(text=self.message.content)
            content_layout.addWidget(view)
            if self.message.status in {"pending", "streaming"}:
                status_row = QHBoxLayout()
                status_row.setSpacing(runtime.px(6))
                indicator = BusyIndicator()
                indicator.start()
                status_row.addWidget(indicator)
                status_label = QLabel(tr("chat.generating"))
                status_label.setProperty("role", "faint")
                status_row.addWidget(status_label)
                status_row.addStretch(1)
                content_layout.addLayout(status_row)
            if self.message.status == "error" and self.message.error:
                error = QLabel(self.message.error)
                error.setWordWrap(True)
                error.setProperty("role", "danger")
                content_layout.addWidget(error)
        if is_user:
            row.addStretch(1)
            row.addWidget(content, 1)
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(content, 1)
            row.addStretch(0)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.message.content)
        self.notify.emit(tr("chat.copied"), "success")

    def _menu(self) -> None:
        menu = QMenu(self)
        menu.setLayoutDirection(self.layoutDirection())
        copy = menu.addAction(icon("copy", runtime.theme().color("text_muted"), 14), tr("chat.copy"))
        copy.triggered.connect(self._copy)
        if self.message.role == "assistant" and self.message.content:
            studio = menu.addAction(
                icon("code", runtime.theme().color("text_muted"), 14), tr("chat.save_to_studio")
            )
            studio.triggered.connect(
                lambda: self.export_requested.emit(self._draft_name(), self.message.content)
            )
        if self.message.status == "error":
            retry = menu.addAction(icon("refresh", runtime.theme().color("text_muted"), 14), tr("chat.retry"))
            retry.triggered.connect(lambda: self.retry_requested.emit(self.message.id))
        menu.addSeparator()
        delete = menu.addAction(icon("trash", runtime.theme().color("danger"), 14), tr("chat.delete"))
        delete.triggered.connect(lambda: self.delete_requested.emit(self.message.id))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _draft_name(self) -> str:
        model = (self.message.model_id or "output").split("/")[-1]
        stamp = self.message.created_at.strftime("%Y%m%d-%H%M") if self.message.created_at else "draft"
        return f"{model}-{stamp}.md"


class StreamingCard(QWidget):
    """Live assistant bubble used while a response streams in.

    It is deliberately separate from ``MessageCard``: the persisted row is
    rendered after the stream finishes, so partial text never needs to be
    written back to the database on every token.
    """

    def __init__(self, model_id: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._language = current_language()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, runtime.px(6), 0, runtime.px(6))
        row.setSpacing(runtime.px(11))
        avatar = LogoMark(26)
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

        content = QWidget()
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(5))
        header = QHBoxLayout()
        header.setSpacing(runtime.px(7))
        name = QLabel(tr("chat.assistant"))
        name.setStyleSheet("font-weight: 600;")
        name.setProperty("role", "accent")
        header.addWidget(name)
        if model_id:
            header.addWidget(Badge(model_id.split("/")[-1][:28], "violet"))
        header.addStretch(1)
        self.latency = QLabel("")
        self.latency.setProperty("role", "faint")
        self.latency.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        header.addWidget(self.latency)
        layout.addLayout(header)

        self.view = MarkdownView(text="")
        layout.addWidget(self.view)
        self.status_row = QWidget()
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(runtime.px(6))
        self.indicator = BusyIndicator()
        self.indicator.start()
        status_layout.addWidget(self.indicator)
        self.status_label = QLabel(tr("chat.generating"))
        self.status_label.setProperty("role", "faint")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch(1)
        layout.addWidget(self.status_row)
        row.addWidget(content, 1)
        row.addStretch(0)

    def set_text(self, text: str) -> None:
        self._text = text
        self.view.set_markdown(text)

    def text(self) -> str:
        return self._text

    def set_latency(self, text: str) -> None:
        self.latency.setText(text)

    def finish(self, *, cancelled: bool = False, error: str = "") -> None:
        self.indicator.stop()
        if error:
            self.status_label.setText(error)
            self.status_label.setProperty("role", "danger")
        elif cancelled:
            self.status_label.setText(tr("chat.cancelled"))
            self.status_label.setProperty("role", "faint")
        else:
            self.status_row.hide()

    def retranslate(self) -> None:
        self.status_label.setText(tr("chat.generating"))


class ChatView(QWidget):
    prompt_chosen = Signal(str)
    notify = Signal(str, str)
    message_delete_requested = Signal(str)
    message_export_requested = Signal(str, str)
    model_retry_requested = Signal(str)
    scroll_position_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conversation = None
        self._messages = []
        self._build()
        runtime.signals.changed.connect(lambda *_: self.update())

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.welcome = WelcomePage()
        self.welcome.prompt_chosen.connect(self.prompt_chosen)
        self.stack.addWidget(self.welcome)

        self.messages_host = QWidget()
        messages_layout = QVBoxLayout(self.messages_host)
        messages_layout.setContentsMargins(0, 0, 0, 0)
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_content = QWidget()
        self.messages_content_layout = QVBoxLayout(self.messages_content)
        self.messages_content_layout.setContentsMargins(runtime.px(34), runtime.px(22), runtime.px(34), runtime.px(26))
        self.messages_content_layout.setSpacing(runtime.px(6))
        self.messages_content_layout.addStretch(1)
        self.messages_scroll.setWidget(self.messages_content)
        messages_layout.addWidget(self.messages_scroll)
        self.stack.addWidget(self.messages_host)

        self.jump_button = IconButton("arrow-down", tr("chat.scroll_bottom"), 34, icon_size=16)
        self.jump_button.setParent(self.messages_scroll.viewport())
        self.jump_button.hide()
        self.jump_button.clicked.connect(self._jump_to_bottom)
        self.messages_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.stack.setCurrentWidget(self.welcome)

    # ------------------------------------------------------------------- data
    def show_welcome(self, conversation=None) -> None:  # noqa: ANN001
        self._conversation = conversation
        self.stack.setCurrentWidget(self.welcome)
        self.jump_button.hide()

    def show_conversation(self, conversation, messages) -> None:  # noqa: ANN001
        self._conversation = conversation
        self._messages = list(messages)
        if not messages:
            self.show_welcome(conversation)
            return
        self._render_messages()
        self.stack.setCurrentWidget(self.messages_host)
        QTimer.singleShot(0, self._jump_to_bottom)

    def _clear_messages(self) -> None:
        self._stream_card = None
        while self.messages_content_layout.count() > 1:
            item = self.messages_content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _render_messages(self) -> None:
        self._clear_messages()
        if not self._conversation:
            return
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, runtime.px(4), 0, runtime.px(10))
        line_left = QFrame()
        line_left.setProperty("panel", "divider")
        line_left.setFixedWidth(40)
        line_left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(line_left)
        stamp = QLabel(
            format_datetime(self._conversation.created_at, current_language())
        )
        stamp.setProperty("role", "faint")
        stamp.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        header_layout.addWidget(stamp)
        line_right = QFrame()
        line_right.setProperty("panel", "divider")
        line_right.setFixedWidth(40)
        line_right.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header_layout.addWidget(line_right)
        header_layout.addStretch(1)
        self.messages_content_layout.insertWidget(self.messages_content_layout.count() - 1, header)

        for message in self._messages:
            if message.role == "system":
                pill = QLabel(message.content)
                pill.setWordWrap(True)
                pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pill.setProperty("role", "faint")
                self.messages_content_layout.insertWidget(self.messages_content_layout.count() - 1, pill)
                continue
            card = MessageCard(message)
            card.delete_requested.connect(self.message_delete_requested)
            card.export_requested.connect(self.message_export_requested)
            card.retry_requested.connect(self.model_retry_requested)
            card.notify.connect(self.notify)
            self.messages_content_layout.insertWidget(self.messages_content_layout.count() - 1, card)

        if not self._conversation.model_id:
            notice = NoticeCard(tr("chat.phase_lock_hint"))
            self.messages_content_layout.insertWidget(self.messages_content_layout.count() - 1, notice)
        self.messages_content.updateGeometry()

    def refresh_messages(self) -> None:
        if self._conversation is not None:
            self._render_messages()

    def set_conversation(self, conversation) -> None:  # noqa: ANN001
        self._conversation = conversation


    # --------------------------------------------------------------- streaming
    def begin_stream(self, model_id: str = "") -> None:
        """Show a live assistant bubble (creating the transcript area if needed)."""
        self.end_stream(silent=True)
        self.stack.setCurrentWidget(self.messages_host)
        self._stream_card = StreamingCard(model_id)
        self.messages_content_layout.insertWidget(
            self.messages_content_layout.count() - 1, self._stream_card
        )
        QTimer.singleShot(0, self._jump_to_bottom)

    def append_stream(self, text: str) -> None:
        card = getattr(self, "_stream_card", None)
        if card is None:
            return
        card.set_text(text)
        bar = self.messages_scroll.verticalScrollBar()
        if bar.value() >= bar.maximum() - runtime.px(80):
            QTimer.singleShot(0, self._jump_to_bottom)

    def set_stream_latency(self, text: str) -> None:
        card = getattr(self, "_stream_card", None)
        if card is not None:
            card.set_latency(text)

    def end_stream(self, *, cancelled: bool = False, error: str = "", silent: bool = False) -> str:
        card = getattr(self, "_stream_card", None)
        text = ""
        if card is not None:
            text = card.text()
            if not silent:
                card.finish(cancelled=cancelled, error=error)
                QTimer.singleShot(90, lambda: self._drop_stream_card(card))
            else:
                self._drop_stream_card(card)
            self._stream_card = None
        return text

    def _drop_stream_card(self, card: "StreamingCard") -> None:
        # The card can already be gone: re-rendering the transcript clears all
        # children, and a queued deletion may fire after that.
        try:
            if card.parent() is None:
                return
            card.setParent(None)
            card.deleteLater()
        except RuntimeError:
            return

    @property
    def is_streaming(self) -> bool:
        return getattr(self, "_stream_card", None) is not None

    # ----------------------------------------------------------------- scroll
    def _jump_to_bottom(self) -> None:
        bar = self.messages_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll(self, value: int) -> None:
        bar = self.messages_scroll.verticalScrollBar()
        near_bottom = value >= bar.maximum() - runtime.px(60)
        self.jump_button.setVisible(not near_bottom and bar.maximum() > 0)
        self.scroll_position_changed.emit(near_bottom)
        self._position_jump_button()

    def _position_jump_button(self) -> None:
        viewport = self.messages_scroll.viewport()
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = runtime.px(18) if rtl else viewport.width() - self.jump_button.width() - runtime.px(18)
        y = viewport.height() - self.jump_button.height() - runtime.px(14)
        self.jump_button.move(x, y)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._position_jump_button()

    # ------------------------------------------------------------ i18n / theme
    def refresh_theme(self) -> None:
        if self._messages:
            self._render_messages()
        self.welcome.content.update()
        self.update()

    def retranslate(self) -> None:
        self.welcome.retranslate()
        card = getattr(self, "_stream_card", None)
        if card is not None:
            card.retranslate()
        self.jump_button.setToolTip(tr("chat.scroll_bottom"))
        if self._messages:
            self._render_messages()
