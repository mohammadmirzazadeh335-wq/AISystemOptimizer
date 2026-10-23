"""Usage & cost: what the last N days actually consumed, and what it cost.

Every number comes from the tokens the provider reported on each assistant
reply and the per-million prices of the cached model catalogue.  A model with
no cached price is counted in the token totals and explicitly marked as
unpriced — this page never invents a price to make a chart look complete.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...services.usage import CURRENCY, RANGES, UsageReport
from ..theme import runtime
from ..widgets.buttons import SegmentedControl
from ..widgets.charts import BarSeries, SegmentBar, Slice
from ..widgets.fields import FlowLayout
from ..widgets.foundation import Badge, EmptyState
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)


def money(value: float) -> str:
    if value <= 0:
        return "$0.00"
    if value < 0.01:
        return f"${value:.4f}"
    if value < 1:
        return f"${value:.3f}"
    return f"${value:,.2f}"


def compact(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 10_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:,}"


class UsagePage(PageShell):
    notify = Signal(str, str)
    open_chat = Signal()
    open_catalogue = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        self.context = context
        self.service = context.usage
        stored = int(context.settings.get("usage.range_days", 30) or 30)
        self.range_days = stored if stored in RANGES else 30
        self.report: UsageReport | None = None
        # The range switch and Refresh are too wide to sit beside the
        # explanation at 1.5x font scale: the subtitle wrapped into a column and
        # pushed the dashboard down the page.
        super().__init__("usage.title", "usage.subtitle", icon_name="chart", actions_below=True)
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.range_control = SegmentedControl(
            [(str(days), tr(f"usage.range_{days}")) for days in RANGES],
            current=str(self.range_days),
            compact=True,
        )
        self.range_control.changed.connect(self._range_changed)
        self.actions_row.addWidget(self.range_control)
        self.refresh_button = ghost_button(tr("usage.refresh"), "refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.actions_row.addWidget(self.refresh_button)
        self.actions_row.addStretch(1)

        # ------------------------------------------------------------- hero
        # Cost on top, the three counters underneath: side by side they needed
        # more width than a 1.5x font scale leaves on a 1440 px window, and the
        # last counter was clipped off the edge.
        self.hero_card, hero = self.card()
        cost_row = QVBoxLayout()
        cost_row.setSpacing(runtime.px(2))
        self.total_caption = hint_label(tr("usage.total_caption"))
        cost_row.addWidget(self.total_caption)
        self.cost_label = QLabel("$0.00")
        self.cost_label.setFont(runtime.ui_font(30, 700))
        self.cost_label.setProperty("role", "h1")
        cost_row.addWidget(self.cost_label)
        self.total_sub = QLabel("")
        self.total_sub.setProperty("role", "muted")
        self.total_sub.setWordWrap(True)
        cost_row.addWidget(self.total_sub)
        hero.addLayout(cost_row)

        stats = QHBoxLayout()
        stats.setSpacing(runtime.px(14))
        self.stats: dict[str, tuple[QLabel, QLabel]] = {}
        for index, key in enumerate(("requests", "tokens", "models")):
            if index:
                divider = QFrame()
                divider.setProperty("panel", "vdivider")
                divider.setFixedWidth(1)
                stats.addWidget(divider)
            block = QVBoxLayout()
            block.setSpacing(0)
            value = QLabel("—")
            value.setFont(runtime.ui_font(18, 650))
            value.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
            caption = hint_label(tr(f"usage.stat_{key}"))
            caption.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
            block.addWidget(value)
            block.addWidget(caption)
            wrapper = QWidget()
            wrapper.setLayout(block)
            wrapper.setMinimumWidth(runtime.px(58))
            stats.addWidget(wrapper)
            self.stats[key] = (value, caption)
        stats.addStretch(1)
        hero.addLayout(stats)

        self.budget_line = QHBoxLayout()
        self.budget_line.setSpacing(runtime.px(8))
        self.budget_bar = SegmentBar()
        self.budget_bar.setFixedHeight(runtime.px(8))
        self.budget_line.addWidget(self.budget_bar, 1)
        self.budget_state = QLabel("")
        self.budget_state.setProperty("role", "faint")
        self.budget_state.setWordWrap(True)
        self.budget_line.addWidget(self.budget_state)
        hero.addLayout(self.budget_line)

        self.price_note = hint_label(tr("usage.price_note"))
        self.price_note.setWordWrap(True)
        hero.addWidget(self.price_note)

        # ------------------------------------------------------------ empty
        empty_action = primary_button(tr("usage.open_chat"), "chat")
        empty_action.clicked.connect(self.open_chat)
        self.empty = EmptyState(
            tr("usage.empty_title"),
            tr("usage.empty_body"),
            "chart",
            action=empty_action,
        )
        self.empty_wrap = QWidget()
        empty_layout = QVBoxLayout(self.empty_wrap)
        empty_layout.setContentsMargins(0, runtime.px(28), 0, runtime.px(28))
        empty_layout.addWidget(self.empty)
        self.add_widget(self.empty_wrap)

        # ------------------------------------------------------------ chart
        self.chart_card, chart_layout = self.card("usage.daily_title", "activity")
        self.chart_hint = hint_label(tr("usage.daily_hint"))
        self.chart_hint.setWordWrap(True)
        chart_layout.addWidget(self.chart_hint)
        self.bars = BarSeries()
        chart_layout.addWidget(self.bars)

        # ------------------------------------------------------------ models
        # Rows, not a four-column table: at 1.5x font scale the table needed
        # more width than the shell leaves beside the sidebar and inspector.
        self.models_card, models_layout = self.card("usage.models_title", "layers")
        self.models_hint = hint_label(tr("usage.models_hint"))
        self.models_hint.setWordWrap(True)
        models_layout.addWidget(self.models_hint)
        self.models_head = QHBoxLayout()
        self.cost_col_label = hint_label(tr("usage.col_cost"))
        self.cost_col_label.setAlignment(Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)
        self.models_head.addStretch(1)
        self.models_head.addWidget(self.cost_col_label)
        models_layout.addLayout(self.models_head)
        self.models_list = QVBoxLayout()
        self.models_list.setSpacing(runtime.px(7))
        models_layout.addLayout(self.models_list)
        self.models_empty = hint_label(tr("usage.models_empty"))
        models_layout.addWidget(self.models_empty)

        # ------------------------------------------------------------ budget
        self.budget_card, budget_layout = self.card("usage.budget_title", "coins")
        self.budget_hint = hint_label(tr("usage.budget_hint"))
        self.budget_hint.setWordWrap(True)
        budget_layout.addWidget(self.budget_hint)
        # A wrapping row: the five controls side by side were wider than the
        # card at 1.25x font scale and forced a horizontal scrollbar.
        editor_host = QWidget()
        self.budget_flow = FlowLayout(editor_host, spacing=runtime.px(8))
        self.budget_edit = QLineEdit()
        self.budget_edit.setPlaceholderText("0.00")
        self.budget_edit.setMaximumWidth(runtime.px(130))
        self.budget_edit.setMinimumWidth(runtime.px(88))
        self.budget_edit.setValidator(QDoubleValidator(0.0, 1_000_000.0, 2, self))
        self.budget_edit.setAccessibleName(tr("usage.budget_title"))
        self.budget_flow.addWidget(self.budget_edit)
        self.currency_label = QLabel(CURRENCY)
        self.currency_label.setProperty("role", "faint")
        self.budget_flow.addWidget(self.currency_label)
        self.budget_save = primary_button(tr("usage.budget_save"), "check")
        self.budget_save.clicked.connect(self._save_budget)
        self.budget_flow.addWidget(self.budget_save)
        self.budget_clear = ghost_button(tr("usage.budget_clear"), "close")
        self.budget_clear.clicked.connect(lambda: self._write_budget(0.0))
        self.budget_flow.addWidget(self.budget_clear)
        self.catalogue_button = ghost_button(tr("usage.open_catalogue"), "server")
        self.catalogue_button.clicked.connect(self.open_catalogue)
        self.budget_flow.addWidget(self.catalogue_button)
        budget_layout.addWidget(editor_host)

    # ------------------------------------------------------------------- data
    def set_range(self, days: int) -> None:
        if days not in RANGES:
            return
        self.range_days = int(days)
        self.context.settings.set("usage.range_days", self.range_days)
        if hasattr(self, "range_control"):
            self.range_control.set_value(str(self.range_days), animate=False)
        self.refresh()

    def _range_changed(self, key: str) -> None:
        try:
            days = int(key)
        except ValueError:
            return
        if days != self.range_days:
            self.set_range(days)

    def refresh(self) -> None:
        try:
            report = self.service.report(self.range_days)
        except Exception:  # noqa: BLE001 - the page must never take the app down
            logger.exception("usage_report_failed")
            return
        self.report = report
        has_data = report.has_data
        self.empty_wrap.setVisible(not has_data)
        for card in (self.chart_card, self.models_card, self.budget_card):
            card.setVisible(has_data)
        self.cost_label.setText(money(report.cost))
        self.total_sub.setText(
            tr(
                "usage.total_sub",
                tokens=f"{report.tokens:,}",
                requests=report.requests,
                days=report.days,
            )
        )
        self.stats["requests"][0].setText(f"{report.requests:,}")
        self.stats["tokens"][0].setText(compact(report.tokens))
        self.stats["models"][0].setText(f"{len(report.models):,}")
        self._render_budget(report)
        if not has_data:
            self.bars.set_data([])
            self._render_models(report)
            return
        labels = [item.day.strftime("%m-%d") for item in report.slices]
        self.bars.set_data(
            list(zip(labels, [item.cost for item in report.slices], strict=True)),
            caption=money,
        )
        self._render_models(report)
        note_key = "usage.price_note" if report.priced else "usage.price_note_unpriced"
        self.price_note.setText(
            tr(note_key, models=report.unpriced_models, tokens=f"{report.unpriced_tokens:,}")
        )
        self.price_note.setProperty("role", "faint" if report.priced else "warning")
        self.price_note.style().unpolish(self.price_note)
        self.price_note.style().polish(self.price_note)

    # --------------------------------------------------------------- renderers
    def _render_models(self, report: UsageReport) -> None:
        while self.models_list.count():
            item = self.models_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        has_models = bool(report.models)
        self.models_empty.setVisible(not has_models)
        self.models_head.setEnabled(has_models)
        self.cost_col_label.setVisible(has_models)
        if not has_models:
            return
        for model in report.models[:8]:
            row = QFrame()
            row.setObjectName("UsageModelRow")
            row.setStyleSheet(
                f"QFrame#UsageModelRow {{ background: {runtime.theme().color('surface_2')};"
                f" border: 1px solid {runtime.theme().color('border')};"
                f" border-radius: {runtime.px(8)}px; }}"
            )
            layout = QHBoxLayout(row)
            layout.setContentsMargins(runtime.px(10), runtime.px(6), runtime.px(10), runtime.px(6))
            layout.setSpacing(runtime.px(8))
            text = QVBoxLayout()
            text.setSpacing(0)
            name_row = QHBoxLayout()
            name_row.setSpacing(runtime.px(6))
            name = QLabel(model.name)
            name.setProperty("role", "h3")
            name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            name.setToolTip(model.model_id)
            name_row.addWidget(name)
            if not model.priced:
                name_row.addWidget(Badge(tr("usage.unpriced"), "warning"))
            name_row.addStretch(1)
            text.addLayout(name_row)
            detail = QLabel(
                tr(
                    "usage.model_detail",
                    replies=model.requests,
                    tokens=f"{model.tokens:,}",
                )
            )
            detail.setProperty("role", "faint")
            detail.setWordWrap(True)
            text.addWidget(detail)
            layout.addLayout(text, 1)
            cost = QLabel(money(model.cost) if model.priced else "—")
            cost.setFont(runtime.ui_font(14, 650))
            cost.setAlignment(Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)
            cost.setProperty("role", "success" if model.priced else "faint")
            layout.addWidget(cost)
            self.models_list.addWidget(row)

    def _render_budget(self, report: UsageReport) -> None:
        if report.budget <= 0:
            self.budget_bar.setVisible(False)
            self.budget_state.setText(tr("usage.budget_unset"))
            self.budget_edit.setText("" if not self.budget_edit.hasFocus() else self.budget_edit.text())
            return
        self.budget_bar.setVisible(True)
        ratio = report.budget_ratio
        tone = "danger" if ratio >= 1 else ("warning" if ratio >= 0.8 else "accent")
        self.budget_bar.set_segments(
            [Slice(tr("usage.budget_used"), max(ratio, 0.001), runtime.theme().color(tone))]
        )
        percent = report.cost / report.budget * 100 if report.budget > 0 else 0.0
        # Only the percentage lives on the bar: "$2.54 of $4.00" reversed badly
        # in the bidirectional Persian layout, so the amounts moved to a tooltip.
        self.budget_state.setText(tr("usage.budget_state", percent=f"{percent:.0f}"))
        self.budget_state.setToolTip(
            tr(
                "usage.budget_tooltip",
                used=money(report.cost),
                budget=money(report.budget),
                percent=f"{percent:.0f}",
            )
        )
        if not self.budget_edit.hasFocus():
            self.budget_edit.setText(f"{report.budget:.2f}")

    # ---------------------------------------------------------------- actions
    def _save_budget(self) -> None:
        text = (self.budget_edit.text() or "").replace(",", ".").strip()
        try:
            value = float(text) if text else 0.0
        except ValueError:
            self.notify.emit(tr("usage.budget_invalid"), "warning")
            return
        self._write_budget(value)

    def _write_budget(self, value: float) -> None:
        try:
            stored = self.service.set_budget(value)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self.notify.emit(tr("usage.budget_saved", value=money(stored)), "success")
        self.refresh()

    # -------------------------------------------------------------- language
    def retranslate(self) -> None:
        super().retranslate()
        self.total_caption.setText(tr("usage.total_caption"))
        self.price_note.setText(tr("usage.price_note"))
        self.chart_hint.setText(tr("usage.daily_hint"))
        self.models_hint.setText(tr("usage.models_hint"))
        self.models_empty.setText(tr("usage.models_empty"))
        self.cost_col_label.setText(tr("usage.col_cost"))
        self.budget_hint.setText(tr("usage.budget_hint"))
        self.refresh_button.setText(tr("usage.refresh"))
        self.budget_save.setText(tr("usage.budget_save"))
        self.budget_clear.setText(tr("usage.budget_clear"))
        self.catalogue_button.setText(tr("usage.open_catalogue"))
        self.stats["requests"][1].setText(tr("usage.stat_requests"))
        self.stats["tokens"][1].setText(tr("usage.stat_tokens"))
        self.stats["models"][1].setText(tr("usage.stat_models"))
        self.empty.title_label.setText(tr("usage.empty_title"))
        self.empty.body_label.setText(tr("usage.empty_body"))
        self.range_control.set_items(
            [(str(days), tr(f"usage.range_{days}")) for days in RANGES]
        )
        if self.report is not None:
            self.refresh()
