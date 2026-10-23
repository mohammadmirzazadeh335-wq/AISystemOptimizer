"""Context Map: what the next request is actually made of.

The numbers come from ``ChatService.context_map``, which mirrors the real
prompt builder block by block. The donut is therefore a measurement, not an
estimate of a guess: if the memory block grows, the chart grows with it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import tr
from ...services.chat import ContextMap, PromptSegment
from ..theme import runtime
from ..widgets.charts import DonutChart, SegmentBar, Slice
from ..widgets.foundation import Badge, Dot, EmptyState
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)

CATEGORY_TONE = {
    "system": "accent",
    "persona": "violet",
    "memory": "success",
    "history": "info",
    "attachment": "warning",
}


class ContextPage(PageShell):
    notify = Signal(str, str)
    open_chat = Signal()
    open_settings = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("context.title", "context.subtitle", icon_name="layers")
        self.context = context
        self.conversation = None
        self.report: ContextMap | None = None
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.hero_card, hero = self.card()
        hero_row = QHBoxLayout()
        hero_row.setSpacing(runtime.px(18))
        self.donut = DonutChart()
        self.donut.setFixedWidth(runtime.px(230))
        hero_row.addWidget(self.donut)
        numbers = QVBoxLayout()
        numbers.setSpacing(runtime.px(4))
        title_row = QHBoxLayout()
        title_row.setSpacing(runtime.px(6))
        self.model_badge = Badge("", "accent")
        title_row.addWidget(self.model_badge)
        self.state_badge = Badge("", "muted")
        title_row.addWidget(self.state_badge)
        title_row.addStretch(1)
        numbers.addLayout(title_row)
        self.used_label = QLabel("—")
        self.used_label.setProperty("role", "display")
        numbers.addWidget(self.used_label)
        self.used_caption = QLabel("")
        self.used_caption.setProperty("role", "muted")
        self.used_caption.setWordWrap(True)
        numbers.addWidget(self.used_caption)
        self.bar = SegmentBar()
        numbers.addWidget(self.bar)
        self.advice_label = QLabel("")
        self.advice_label.setWordWrap(True)
        self.advice_label.setProperty("role", "muted")
        numbers.addWidget(self.advice_label)
        facts = QHBoxLayout()
        facts.setSpacing(runtime.px(14))
        self.messages_fact = self._fact(tr("context.messages"))
        self.memory_fact = self._fact(tr("context.memory_items"))
        self.remaining_fact = self._fact(tr("context.remaining"))
        self._captions = {
            "messages": self.messages_fact[2],
            "memory": self.memory_fact[2],
            "remaining": self.remaining_fact[2],
        }
        for fact in (self.messages_fact, self.memory_fact, self.remaining_fact):
            facts.addWidget(fact[0])
        facts.addStretch(1)
        numbers.addLayout(facts)
        numbers.addStretch(1)
        hero_row.addLayout(numbers, 1)
        hero.addLayout(hero_row)

        self.segment_card, segment_layout = self.card("context.breakdown_title", "layers")
        self.category_bar = SegmentBar()
        segment_layout.addWidget(self.category_bar)
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(runtime.px(6))
        segment_layout.addLayout(self.rows_box)

        self.largest_card, largest_layout = self.card("context.largest_title", "activity")
        self.largest_hint = hint_label(tr("context.largest_hint"))
        largest_layout.addWidget(self.largest_hint)
        self.largest_box = QVBoxLayout()
        self.largest_box.setSpacing(runtime.px(5))
        largest_layout.addLayout(self.largest_box)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(6))
        self.refresh_button = ghost_button(tr("context.refresh"), "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.memory_button = ghost_button(tr("context.open_memory"), "database")
        self.memory_button.clicked.connect(self.open_settings)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.memory_button)
        actions.addStretch(1)
        self.chat_button = primary_button(tr("context.back_to_chat"), "chat")
        self.chat_button.clicked.connect(self.open_chat)
        actions.addWidget(self.chat_button)
        self.actions_wrap = self._wrap(actions)
        self.add_widget(self.actions_wrap)

        self.empty = EmptyState(
            tr("context.empty_title"),
            tr("context.empty_body"),
            "layers",
            action=self._empty_action(),
        )
        self.empty_wrap = self._wrap_center(self.empty)
        self.add_widget(self.empty_wrap)

    def _fact(self, caption: str) -> tuple[QWidget, QLabel, QLabel]:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        value = QLabel("—")
        value.setProperty("role", "h3")
        layout.addWidget(value)
        label = QLabel(caption)
        label.setProperty("role", "faint")
        label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        layout.addWidget(label)
        return wrapper, value, label

    def _wrap(self, layout) -> QWidget:  # noqa: ANN001
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _wrap_center(self, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addStretch(1)
        layout.addWidget(widget)
        layout.addStretch(1)
        return wrapper

    def _empty_action(self) -> QWidget:
        button = primary_button(tr("context.back_to_chat"), "chat")
        button.clicked.connect(self.open_chat)
        return button

    # ------------------------------------------------------------------- data
    def set_conversation(self, conversation) -> None:  # noqa: ANN001
        self.conversation = conversation
        self.refresh()

    def refresh(self) -> None:  # noqa: D401 - page contract
        if self.conversation is None:
            self.report = None
            self._show_empty(True)
            return
        try:
            report = self.context.chat.context_map(self.conversation)
        except Exception as exc:  # noqa: BLE001 - a deleted conversation is a message
            logger.info("context_map_failed error=%s", exc)
            self.report = None
            self._show_empty(True)
            return
        self._show_empty(False)
        self.report = report
        totals = report.by_category()
        slices = [
            Slice(tr(f"context.category_{category}"), total, runtime.theme().color(CATEGORY_TONE[category]))
            for category, total in sorted(totals.items(), key=lambda item: -item[1])
        ]
        percent = round(report.ratio * 100)
        # Below one percent, "0%" next to a nearly empty ring is honest only if
        # it keeps a decimal: 165 tokens out of 128,000 is 0.1%, not nothing.
        shown = f"{percent}%" if percent >= 1 or report.ratio <= 0 else f"{report.ratio * 100:.1f}%"
        self.donut.set_data(
            slices,
            shown,
            tr("context.of_window", window=f"{report.window:,}") if report.window else tr("context.no_window"),
            fill=report.ratio,
        )
        self.model_badge.setText(report.model_id or tr("context.no_model"))
        warn_ratio = float(self.context.settings.get("ai.context_warn_ratio", 0.8) or 0.8)
        if percent >= round(warn_ratio * 100):
            self.state_badge.setText(tr("context.state_high"))
            self.state_badge.set_tone("warning")
        else:
            self.state_badge.setText(tr("context.state_ok"))
            self.state_badge.set_tone("success")
        self.used_label.setText(tr("context.used", tokens=f"{report.total_tokens:,}"))
        self.used_caption.setText(
            tr(
                "context.used_caption",
                messages=report.history_messages,
                window=f"{report.window:,}" if report.window else "—",
            )
        )
        self.bar.set_segments(slices)
        self.remaining_fact[1].setText(
            f"{max(0, report.window - report.total_tokens):,}" if report.window else "—"
        )
        self.messages_fact[1].setText(str(report.history_messages))
        self.memory_fact[1].setText(str(report.memory_items))
        self.advice_label.setText(tr("context.advice_high") if percent >= round(warn_ratio * 100) else tr("context.advice_ok"))

        self.category_bar.set_segments(slices)
        self._fill_rows(totals, report)
        self._fill_largest(report)

    def _show_empty(self, empty: bool) -> None:
        for card in (self.hero_card, self.segment_card, self.largest_card, self.actions_wrap):
            card.setVisible(not empty)
        self.empty_wrap.setVisible(empty)

    def _clear_layout(self, layout) -> None:  # noqa: ANN001
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _fill_rows(self, totals: dict[str, int], report: ContextMap) -> None:
        self._clear_layout(self.rows_box)
        total = max(1, report.total_tokens)
        for category, value in sorted(totals.items(), key=lambda item: -item[1]):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(runtime.px(8))
            layout.addWidget(Dot(CATEGORY_TONE[category], 8))
            label = QLabel(tr(f"context.category_{category}"))
            label.setMinimumWidth(runtime.px(120))
            layout.addWidget(label)
            count = sum(1 for segment in report.segments if segment.category == category)
            caption = QLabel(tr("context.segments", count=count))
            caption.setProperty("role", "faint")
            caption.setStyleSheet(f"font-size: {runtime.px(10)}px;")
            layout.addWidget(caption)
            layout.addStretch(1)
            share = QLabel(f"{round(value / total * 100)}%")
            share.setProperty("role", "muted")
            share.setMinimumWidth(runtime.px(38))
            share.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(share)
            tokens = QLabel(f"{value:,}")
            tokens.setProperty("role", "mono")
            tokens.setMinimumWidth(runtime.px(70))
            tokens.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(tokens)
            self.rows_box.addWidget(row)

    def _fill_largest(self, report: ContextMap) -> None:
        self._clear_layout(self.largest_box)
        largest = sorted(report.segments, key=lambda segment: -segment.tokens)[:5]
        if not largest:
            self.largest_hint.setText(tr("context.largest_empty"))
            return
        self.largest_hint.setText(tr("context.largest_hint"))
        for segment in largest:
            self.largest_box.addWidget(self._segment_row(segment, report))

    def _segment_row(self, segment: PromptSegment, report: ContextMap) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(8))
        tone = CATEGORY_TONE.get(segment.category, "muted")
        layout.addWidget(Dot(tone, 7))
        name = QLabel(tr(f"context.category_{segment.category}"))
        name.setMinimumWidth(runtime.px(92))
        layout.addWidget(name)
        detail = QLabel(segment.label or segment.preview or "—")
        detail.setProperty("role", "faint")
        detail.setToolTip(segment.preview)
        detail.setWordWrap(False)
        layout.addWidget(detail, 1)
        tokens = QLabel(f"{segment.tokens:,}")
        tokens.setProperty("role", "mono")
        tokens.setMinimumWidth(runtime.px(64))
        tokens.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(tokens)
        return row

    # ----------------------------------------------------------- page contract
    def retranslate(self) -> None:
        super().retranslate()
        self.refresh_button.setText(tr("context.refresh"))
        self.memory_button.setText(tr("context.open_memory"))
        self.chat_button.setText(tr("context.back_to_chat"))
        self._captions["messages"].setText(tr("context.messages"))
        self._captions["memory"].setText(tr("context.memory_items"))
        self._captions["remaining"].setText(tr("context.remaining"))

    def rebuild(self) -> None:
        super().rebuild()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self.report is not None:
            self.refresh()


__all__ = ["ContextPage"]
