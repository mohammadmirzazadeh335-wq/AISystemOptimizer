"""Shared scaffold for the Phase 2 full-page surfaces.

Every page uses the same shell — a scrolling body with a headline, a short
explanation, and cards built from the same tokens as the rest of the app — so
the AI settings, memory, personality and output screens never look bolted on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..theme import runtime
from ..widgets.foundation import Badge

logger = logging.getLogger(__name__)


class PageShell(QWidget):

    """Headline + optional action area + vertically scrolling card column."""

    def __init__(
        self,
        title_key: str,
        subtitle_key: str = "",
        *,
        icon_name: str = "",
        scroll: bool = True,
        stretch: bool = True,
        actions_below: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title_key = title_key
        self._subtitle_key = subtitle_key
        self._stretch = stretch
        self.setAccessibleName(tr(title_key))
        self._icon_name = icon_name
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The window header already shows the page title, so the page itself
        # opens with the explanation and its actions instead of repeating a
        # headline two rows apart.
        header = QWidget()
        header.setObjectName("PageHeader")
        head_layout = QVBoxLayout(header) if actions_below else QHBoxLayout(header)
        head_layout.setContentsMargins(runtime.px(30), runtime.px(18), runtime.px(30), runtime.px(8))
        head_layout.setSpacing(runtime.px(10) if actions_below else runtime.px(12))
        self.lead = QLabel(tr(subtitle_key) if subtitle_key else "")
        self.lead.setProperty("role", "muted")
        self.lead.setWordWrap(True)
        self.lead.setMaximumWidth(runtime.px(820))
        self.lead.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        head_layout.addWidget(self.lead, 1)
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(runtime.px(8))
        if actions_below:
            # A row of five actions cannot live beside the explanation: at 1.5x
            # it wrapped into a column and pushed the workspace down the page.
            self.actions_row.setContentsMargins(0, 0, 0, 0)
            head_layout.addLayout(self.actions_row)
        else:
            head_layout.addLayout(self.actions_row, 0)
        outer.addWidget(header)

        margins = (runtime.px(22), runtime.px(4), runtime.px(22), runtime.px(28))
        if scroll:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            # Wrapped content normally fits, so the bar stays hidden; at 1.5x font
            # scale on a small window the card column is wider than the viewport,
            # and an unreachable right edge is worse than an honest scrollbar.
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            body = QWidget()
            self.body = QVBoxLayout(body)
            self.body.setContentsMargins(*margins)
            self.body.setSpacing(runtime.px(13))
            self.scroll.setWidget(body)
            outer.addWidget(self.scroll, 1)
        else:
            # Splitter-based pages (Code Studio) own their height; wrapping them
            # in a scroll area would trap the splitters inside a fixed canvas.
            self.scroll = None
            body = QWidget()
            self.body = QVBoxLayout(body)
            self.body.setContentsMargins(*margins)
            self.body.setSpacing(runtime.px(10))
            outer.addWidget(body, 1)
        if stretch:
            self.body.addStretch(1)

    # ------------------------------------------------------------------ cards
    def card(self, title_key: str = "", icon_name: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("panel", "card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(runtime.px(16), runtime.px(14), runtime.px(16), runtime.px(15))
        layout.setSpacing(runtime.px(9))
        if title_key:
            head = QHBoxLayout()
            head.setSpacing(runtime.px(7))
            if icon_name:
                icon_widget = QLabel()
                icon_widget.setPixmap(runtime.icons().px(icon_name, 14, "muted"))
                head.addWidget(icon_widget)
            label = QLabel(tr(title_key))
            label.setProperty("role", "section")
            head.addWidget(label)
            head.addStretch(1)
            layout.addLayout(head)
        self.body.insertWidget(self.body.count() - 1, card)
        return card, layout

    def add_widget(self, widget: QWidget) -> None:
        self.body.insertWidget(self.body.count() - 1, widget)

    def add_stretch(self) -> None:
        self.body.addStretch(1)

    def clear_actions(self) -> None:
        while self.actions_row.count():
            item = self.actions_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                _release(widget)

    def rebuild(self) -> None:
        """Recreate the body after a language or theme change.

        Rebuilding is preferred over a partial relabel here: these pages mix
        labels, hints, badges and menus, and a half-translated surface is worse
        than a brief rebuild.
        """
        self.clear_actions()
        self.clear_body()
        self._build()
        self.retranslate()
        if hasattr(self, "refresh"):
            self.refresh()  # type: ignore[attr-defined]

    def clear_body(self) -> None:
        keep = 1 if self._stretch else 0
        while self.body.count() > keep:
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                _release(widget)
            elif item.layout() is not None:
                _clear_layout(item.layout())

    def retranslate(self) -> None:
        self.setAccessibleName(tr(self._title_key))
        self.lead.setText(tr(self._subtitle_key) if self._subtitle_key else "")


def auto_direction(editor) -> None:  # noqa: ANN001
    """Let each paragraph pick its own base direction.

    Persian bullets and English code then both read correctly in the same file;
    forcing the widget direction breaks one language or the other.
    """
    option = editor.document().defaultTextOption()
    option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
    editor.document().setDefaultTextOption(option)


def _release(widget: QWidget) -> None:
    """Unparent and delete a widget without leaving dangling layout items."""
    layout = widget.layout()
    if layout is not None and hasattr(layout, "detach_items"):
        layout.detach_items()
    widget.setParent(None)
    widget.deleteLater()


def _clear_layout(layout: QLayout) -> None:
    if hasattr(layout, "detach_items"):
        layout.detach_items()  # type: ignore[attr-defined]
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            _release(widget)
        elif item.layout() is not None:
            _clear_layout(item.layout())


def page_margins() -> tuple[int, int, int, int]:
    return (runtime.px(30), runtime.px(4), runtime.px(30), runtime.px(28))


def secondary_button(text: str, icon_name: str = "") -> QWidget:
    """Token-styled secondary button (small)."""
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    button.setProperty("variant", "secondary")
    button.setProperty("buttonsize", "sm")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        button.setIcon(runtime.icons().get(icon_name, 13, "muted"))
    return button


def primary_button(text: str, icon_name: str = "") -> QWidget:
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    button.setProperty("variant", "primary")
    button.setProperty("buttonsize", "sm")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        button.setIcon(runtime.icons().get(icon_name, 13, "accent"))
    return button


def ghost_button(text: str, icon_name: str = "") -> QWidget:
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    button.setProperty("variant", "ghost")
    button.setProperty("buttonsize", "sm")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        button.setIcon(runtime.icons().get(icon_name, 13, "muted"))
    return button


def danger_button(text: str, icon_name: str = "") -> QWidget:
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(text)
    button.setProperty("variant", "danger")
    button.setProperty("buttonsize", "sm")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        button.setIcon(runtime.icons().get(icon_name, 13, "muted"))
    return button


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "faint")
    label.setStyleSheet(f"font-size: {runtime.px(10)}px; letter-spacing: 0.3px;")
    return label


def hint_label(text: str, *, tone: str = "faint") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", tone)
    label.setWordWrap(True)
    label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
    return label


def status_row(text: str = "", tone: str = "muted") -> tuple[QWidget, QLabel]:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(runtime.px(7))
    label = QLabel(text)
    label.setProperty("role", tone)
    label.setWordWrap(True)
    layout.addWidget(label, 1)
    return wrapper, label


def badge_row(*items: tuple[str, str]) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(runtime.px(6))
    for text, tone in items:
        layout.addWidget(Badge(text, tone))
    layout.addStretch(1)
    return wrapper


def run_async(
    owner: QWidget,
    work: Callable[[], object],
    *,
    on_success: Callable[[object], None],
    on_error: Callable[[Exception], None],
) -> None:
    """Run blocking work off the GUI thread and deliver the result back.

    Signals are emitted from a worker thread; Qt queues them onto the GUI
    thread, so callbacks may touch widgets safely. Keeping the worker alive on
    the owner prevents premature collection.
    """
    import threading

    from PySide6.QtCore import QObject, Signal

    class _Bridge(QObject):
        success = Signal(object)
        failure = Signal(object)

    bridge = _Bridge(owner)
    bridge.success.connect(on_success)
    bridge.failure.connect(on_error)
    keep = getattr(owner, "_async_bridges", None)
    if keep is None:
        keep = []
        owner._async_bridges = keep  # type: ignore[attr-defined]
    keep.append(bridge)

    def target() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            outcome, payload = "failure", exc
        else:
            outcome, payload = "success", result
        try:
            (bridge.failure if outcome == "failure" else bridge.success).emit(payload)
        except RuntimeError:
            # The page was destroyed while the request was still in flight
            # (a closed window, or a key deleted mid-call). The result has
            # nowhere to go; failing here would only print a thread traceback.
            logger.debug("async_result_dropped outcome=%s", outcome)
        finally:
            if bridge in keep:
                keep.remove(bridge)

    threading.Thread(target=target, name="myai-async", daemon=True).start()
