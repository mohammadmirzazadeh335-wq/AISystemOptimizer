"""Agent Mode — a live timeline of real, approved tool calls.

The page never decides what the agent may do: the service validates arguments,
the registry enforces the risk gates, and this page only renders what happened
and asks the user for approval before a write, an execution or a network call.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import AppError
from ...i18n import tr
from ...services.agent import MAX_STEPS_RANGE, AgentRun, AgentStep
from ...services.projects import Project, ProjectService
from ...services.providers import cached_models, current_provider, has_key
from ...services.runner import Runner
from ...services.tools import (
    EXECUTE,
    NETWORK,
    READ,
    SENSITIVE,
    WRITE,
    ToolContext,
    ToolRegistry,
    ToolSpec,
)
from ..theme import runtime
from ..widgets.dialogs import ConfirmDialog
from ..widgets.fields import FlowLayout, SelectField
from ..widgets.foundation import Badge, ElidedLabel
from .page_base import PageShell, ghost_button, primary_button, secondary_button

RISK_TONE = {
    READ: "muted",
    WRITE: "warning",
    EXECUTE: "violet",
    NETWORK: "accent",
}
RISK_KEY = {
    READ: "agent.risk_read",
    WRITE: "agent.risk_write",
    EXECUTE: "agent.risk_execute",
    NETWORK: "agent.risk_network",
}
STEP_ICON = {
    "thinking": "sparkles",
    "tool": "wrench",
    "denied": "shield",
    "error": "alert",
    "final": "check",
}
STEP_TONE = {
    "thinking": "muted",
    "tool": "success",
    "denied": "warning",
    "error": "danger",
    "final": "accent",
}


class _ClickFrame(QFrame):
    """A frame that reports a left click (run-history rows)."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


@dataclass
class ApprovalRequest:
    """One tool call waiting for the user's answer (worker → GUI thread)."""

    tool: ToolSpec
    arguments: dict
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False

    def describe(self) -> str:
        try:
            payload = json.dumps(self.arguments, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            payload = str(self.arguments)
        return payload[:1200]


class _AgentBridge(QObject):
    step = Signal(object)
    delta = Signal(str)
    finished = Signal(object)
    approval = Signal(object)


class AgentPage(PageShell):
    notify = Signal(str, str)
    open_api_page = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__(
            "agent.title",
            "agent.subtitle",
            icon_name="sparkles",
            scroll=False,
            stretch=False,
            actions_below=True,
        )
        self.context = context
        self.agent = context.agent
        self.registry: ToolRegistry = self.agent.tools
        self.projects = ProjectService(context.paths, context.settings, history=getattr(context, "history", None))
        self.runner = Runner()
        self.project: Project | None = None
        self._models: list[dict] = []
        self._recent: list[tuple[str, str]] = []
        self._run: AgentRun | None = None
        self._thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._pending: ApprovalRequest | None = None
        self._closing = False
        self._bridge = _AgentBridge(self)
        self._bridge.step.connect(self._on_step)
        self._bridge.delta.connect(self._on_delta)
        self._bridge.finished.connect(self._on_finished)
        self._bridge.approval.connect(self._on_approval)
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.actions_flow = FlowLayout(spacing=runtime.px(7))
        host = QWidget()
        host.setLayout(self.actions_flow)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.actions_row.addWidget(host, 1)

        self.project_select = SelectField([], placeholder=tr("agent.no_project"), icon_name="folder")
        self.project_select.value_changed.connect(self._on_project_selected)
        self.actions_flow.addWidget(self.project_select)
        self.model_select = SelectField([], placeholder=tr("agent.no_model"), icon_name="cpu")
        self.model_select.value_changed.connect(self._on_model_selected)
        self.actions_flow.addWidget(self.model_select)
        self.api_button = secondary_button(tr("agent.open_api"), "key")
        self.api_button.clicked.connect(self.open_api_page.emit)
        self.actions_flow.addWidget(self.api_button)
        self.stop_button = secondary_button(tr("agent.stop"), "stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.actions_flow.addWidget(self.stop_button)

        self._left_panel = self._build_side_panel()
        self._right_panel = self._build_work_panel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(runtime.px(9))
        splitter.addWidget(self._left_panel)
        splitter.addWidget(self._right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([runtime.px(330), runtime.px(880)])
        splitter.setMinimumWidth(runtime.px(320))
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.splitter = splitter
        # In a small window the two panes cannot both fit; the workspace then
        # scrolls as a whole instead of letting cards overlap each other.
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workspace_scroll.setWidget(splitter)
        self.add_widget(self.workspace_scroll)
        self.body.setStretchFactor(self.workspace_scroll, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if not hasattr(self, "splitter"):
            return
        narrow = self.width() < runtime.px(680)
        orientation = Qt.Orientation.Vertical if narrow else Qt.Orientation.Horizontal
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            if narrow:
                self.splitter.setSizes([runtime.px(360), runtime.px(520)])
            else:
                self.splitter.setSizes([runtime.px(330), runtime.px(880)])
        # While stacked, the panes keep their real heights and the workspace
        # scrolls; side by side, the splitter owns the full viewport height.
        self.splitter.setMinimumHeight(runtime.px(900) if narrow else 0)

    def _build_side_panel(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(10))
        layout.addWidget(self._build_tools_card(), 3)
        layout.addWidget(self._build_runs_card(), 2)
        return holder

    def _build_tools_card(self) -> QWidget:
        card, layout = self.card("agent.tools", "wrench")
        header = QHBoxLayout()
        header.setSpacing(runtime.px(6))
        self.tools_count = QLabel("")
        self.tools_count.setProperty("role", "faint")
        header.addWidget(self.tools_count, 1)
        self.refresh_tools_button = ghost_button("", "refresh")
        self.refresh_tools_button.setAccessibleName(tr("agent.tools_refresh"))
        self.refresh_tools_button.setToolTip(tr("agent.tools_refresh"))
        self.refresh_tools_button.clicked.connect(self.refresh_tools)
        header.addWidget(self.refresh_tools_button)
        layout.addLayout(header)

        # Twelve tools with wrapped reasons do not fit a fixed card. Rows stay
        # one line each (uniform height, scrollable) and the selected tool's
        # description and availability reason appear in one shared label below.
        tools_scroll = QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # A hidden "as needed" bar made five of twelve tools look like the whole
        # list; keep a slim, always-visible track so the card cannot be misread.
        tools_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        tools_scroll.setMinimumHeight(runtime.px(150))
        tools_canvas = QWidget()
        self.tools_box = QVBoxLayout(tools_canvas)
        self.tools_box.setContentsMargins(0, 0, runtime.px(4), 0)
        self.tools_box.setSpacing(runtime.px(3))
        # The rows have fixed heights; the layout minimum must drive the canvas,
        # otherwise the scroll area clips the last tools with no scrollbar.
        self.tools_box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.tools_box.addStretch(1)
        tools_scroll.setWidget(tools_canvas)
        self.tools_scroll = tools_scroll
        self.tools_canvas = tools_canvas
        layout.addWidget(tools_scroll, 1)


        self.confirm_toggle = QCheckBox(tr("agent.require_confirmation"))
        self.confirm_toggle.setChecked(bool(self.context.settings.get("agent.require_confirmation", True)))
        self.confirm_toggle.toggled.connect(
            lambda checked: self.context.settings.update({"agent.require_confirmation": bool(checked)})
        )
        layout.addWidget(self.confirm_toggle)
        self.network_toggle = QCheckBox(tr("agent.allow_network"))
        self.network_toggle.setChecked(bool(self.context.settings.get("agent.allow_network", False)))
        self.network_toggle.toggled.connect(self._on_network_toggled)
        layout.addWidget(self.network_toggle)
        steps_row = QHBoxLayout()
        steps_row.setSpacing(runtime.px(6))
        steps_label = QLabel(tr("agent.max_steps"))
        steps_label.setProperty("role", "faint")
        steps_row.addWidget(steps_label, 1)
        self.steps_select = SelectField(
            [("4", "4"), ("8", "8"), ("12", "12"), ("20", "20"), (str(MAX_STEPS_RANGE[1]), "50")],
            placeholder="12",
            compact=True,
        )
        self.steps_select.set_value(str(int(self.context.settings.get("agent.max_steps", 12) or 12)))
        self.steps_select.value_changed.connect(
            lambda value: self.context.settings.update({"agent.max_steps": int(value)})
        )
        steps_row.addWidget(self.steps_select, 0)
        layout.addLayout(steps_row)
        return card

    def _build_runs_card(self) -> QWidget:
        card, layout = self.card("agent.runs", "activity")
        self.runs_box = QVBoxLayout()
        self.runs_box.setSpacing(runtime.px(5))
        layout.addLayout(self.runs_box)
        self.runs_empty = QLabel(tr("agent.runs_empty"))
        self.runs_empty.setProperty("role", "faint")
        self.runs_empty.setWordWrap(True)
        layout.addWidget(self.runs_empty)
        layout.addStretch(1)
        return card

    def _build_work_panel(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(runtime.px(10))
        layout.addWidget(self._build_task_card(), 0)
        layout.addWidget(self._build_timeline_card(), 1)
        return holder

    def _build_task_card(self) -> QWidget:
        card = QFrame()
        card.setProperty("panel", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(runtime.px(16), runtime.px(13), runtime.px(16), runtime.px(13))
        layout.setSpacing(runtime.px(7))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(8))
        title = QLabel(tr("agent.task"))
        title.setProperty("role", "section")
        head.addWidget(title)
        head.addStretch(1)
        self.project_badge = Badge(tr("agent.no_project"), "muted")
        self.model_badge = Badge(tr("agent.model_tools_unknown"), "muted")
        # Badges wrap under the title when the pane is narrow (small window,
        # high font scale) instead of being cut in half.
        self.task_badges = FlowLayout(spacing=runtime.px(6))
        self.task_badges.addWidget(self.project_badge)
        self.task_badges.addWidget(self.model_badge)
        badge_host = QWidget()
        badge_host.setLayout(self.task_badges)
        badge_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(badge_host)
        layout.addLayout(head)

        self.task_edit = QPlainTextEdit()
        self.task_edit.setObjectName("AgentTask")
        self.task_edit.setPlaceholderText(tr("agent.task_hint"))
        self.task_edit.setAccessibleName(tr("agent.task"))
        self.task_edit.setFixedHeight(runtime.px(74))
        layout.addWidget(self.task_edit)

        footer = QHBoxLayout()
        footer.setSpacing(runtime.px(8))
        self.run_hint = QLabel(tr("agent.run_hint"))
        self.run_hint.setProperty("role", "faint")
        self.run_hint.setWordWrap(True)
        self.run_hint.setMinimumWidth(0)
        self.run_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.run_hint, 1)
        self.run_button = primary_button(tr("agent.run"), "play")
        self.run_button.setShortcut("Ctrl+Return")
        self.run_button.clicked.connect(self.start)
        footer.addWidget(self.run_button, 0)
        layout.addLayout(footer)
        return card

    def _build_timeline_card(self) -> QWidget:
        card = QFrame()
        card.setProperty("panel", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(12))
        layout.setSpacing(runtime.px(7))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(8))
        title = QLabel(tr("agent.timeline"))
        title.setProperty("role", "section")
        head.addWidget(title)
        head.addStretch(1)
        self.status_badge = Badge(tr("agent.status_idle"), "muted")
        head.addWidget(self.status_badge)
        layout.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        self.timeline = QVBoxLayout(canvas)
        self.timeline.setContentsMargins(0, 0, runtime.px(4), 0)
        self.timeline.setSpacing(runtime.px(7))
        self.empty_state = QLabel(tr("agent.empty_timeline"))
        self.empty_state.setProperty("role", "faint")
        self.empty_state.setWordWrap(True)
        self.timeline.addWidget(self.empty_state)
        self.timeline.addStretch(1)
        self.scroll.setWidget(canvas)
        layout.addWidget(self.scroll, 1)

        self.live_label = QLabel("")
        self.live_label.setProperty("role", "mono")
        self.live_label.setWordWrap(True)
        self.live_label.setMaximumHeight(runtime.px(54))
        self.live_label.setVisible(False)
        layout.addWidget(self.live_label)
        return card

    # -------------------------------------------------------------- lifecycle
    def retranslate(self) -> None:
        super().retranslate()
        self.project_select.set_placeholder(tr("agent.no_project"))
        self.model_select.set_placeholder(tr("agent.no_model"))
        self.api_button.setText(tr("agent.open_api"))
        self.stop_button.setText(tr("agent.stop"))
        self.task_edit.setPlaceholderText(tr("agent.task_hint"))
        self.run_button.setText(tr("agent.run"))
        self.run_hint.setText(tr("agent.run_hint"))
        self.confirm_toggle.setText(tr("agent.require_confirmation"))
        self.network_toggle.setText(tr("agent.allow_network"))
        self.runs_empty.setText(tr("agent.runs_empty"))
        self.empty_state.setText(tr("agent.empty_timeline"))
        self.refresh_tools()
        self._refresh_badges()
        self._refresh_runs()

    def rebuild(self) -> None:
        """Recreate the widgets after a language/theme change without losing state."""
        task = self.task_edit.toPlainText()
        run = self._run
        super().rebuild()
        self.task_edit.setPlainText(task)
        if run is not None and run.steps:
            self._clear_timeline()
            for step in run.steps:
                self._render_step(step)
            self._run = run
            self.status_badge.setText(tr(f"agent.status_{run.status}"))
            self.status_badge.set_tone(self._status_tone(run.status))
        self._update_controls()

    def refresh(self) -> None:
        self._load_models()
        self._load_projects()
        self.refresh_tools()
        self._refresh_runs()
        self._refresh_badges()
        self._update_controls()

    def shutdown(self) -> None:
        self._closing = True
        self.stop()
        pending = self._pending
        if pending is not None:
            pending.approved = False
            pending.event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.5)

    # ---------------------------------------------------------------- models
    def _provider_ready(self) -> bool:
        """Ready to run: the selected provider has whatever it needs."""
        provider = current_provider(self.context.settings)
        if not has_key(provider, self.context.secrets):
            return False
        # Tool calling is implemented for OpenAI-compatible endpoints only.
        return provider.protocol == "openai"

    def _load_models(self) -> None:
        provider = current_provider(self.context.settings)
        cache = cached_models(self.context.settings, provider.id)
        models = [item for item in cache if isinstance(item, dict) and item.get("id")]
        models.sort(key=lambda item: (not bool(item.get("supports_tools")), str(item.get("name") or item["id"])))
        self._models = models
        items = [
            (str(item["id"]), str(item.get("name") or item["id"]))
            for item in models
            if item.get("supports_tools")
        ]
        default = str(self.context.settings.get("ai.default_model", "") or "")
        if not items and default:
            items = [(default, default)]
        self.model_select.set_items(items)
        if not any(value == default for value, _label in items) and items:
            default = items[0][0]
            self.context.settings.update({"ai.default_model": default})
        self.model_select.set_value(default)
        self._refresh_badges()

    def _on_model_selected(self, value: str) -> None:
        if value:
            self.context.settings.update({"ai.default_model": value})
            self._refresh_badges()

    def _model_supports_tools(self) -> bool | None:
        model_id = self.model_select.value
        for item in self._models:
            if str(item.get("id")) == model_id:
                return bool(item.get("supports_tools"))
        return None

    # -------------------------------------------------------------- projects
    def _load_projects(self) -> None:
        values: list[tuple[str, str]] = []
        seen: set[str] = set()
        candidates = [self.context.settings.get("code.last_project", "")]
        candidates += list(self.context.settings.get("code.recent_projects", []) or [])
        for raw in candidates:
            if isinstance(raw, dict):
                text = str(raw.get("path") or "").strip()
                name = str(raw.get("name") or "").strip()
            else:
                text = str(raw or "").strip()
                name = ""
            if not text or text in seen:
                continue
            path = Path(text)
            if not path.is_dir():
                continue
            seen.add(text)
            values.append((text, name or path.name))
        self._recent = values
        self.project_select.set_items(values)
        current = str(self.project.root) if self.project is not None else (values[0][0] if values else "")
        self.project_select.set_value(current)
        if self.project is None and current:
            self._set_project(Path(current), announce=False)
        self.project_badge.setText(self.project.name if self.project else tr("agent.no_project"))
        self.project_badge.set_tone("muted" if self.project is None else "outline")
        self._refresh_badges()

    def _on_project_selected(self, value: str) -> None:
        if value:
            self._set_project(Path(value))

    def _set_project(self, path: Path, announce: bool = True) -> None:
        try:
            project = self.projects.open_folder(path)
        except AppError as exc:
            self._toast(exc.message, "warning")
            return
        self.project = project
        self.project_label_hint = project.name
        self.context.settings.update({"code.last_project": str(project.root)})
        self.project_badge.setText(project.name)
        self.project_badge.set_tone("outline")
        if announce:
            self._toast(tr("agent.project_ready").format(name=project.name))
        self.refresh_tools()

    # ----------------------------------------------------------------- tools
    def _reason_text(self, spec: ToolSpec, context: ToolContext) -> str | None:
        found = spec.reason_key(context)
        if found is None:
            return None
        key, params = found
        template = tr(key)
        try:
            return template.format(**params) if params else template
        except (KeyError, IndexError):
            return template

    def refresh_tools(self) -> None:
        while self.tools_box.count() > 1:  # keep the stretch item
            item = self.tools_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        context = self._tool_context()
        available = 0
        self._tool_rows = {}
        for spec in self.registry.specs():
            reason = self._reason_text(spec, context)
            row = QFrame()
            row.setProperty("panel", "chip")
            row.setFixedHeight(runtime.px(44))
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(runtime.px(8), runtime.px(4), runtime.px(8), runtime.px(4))
            row_layout.setSpacing(0)
            head = QHBoxLayout()
            head.setSpacing(runtime.px(5))
            icon = QLabel()
            icon.setPixmap(runtime.icons().px("wrench" if reason is None else "lock", 11,
                                             "accent" if reason is None else "muted"))
            head.addWidget(icon)
            name = QLabel(tr(spec.label_key) if spec.label_key else spec.id)
            name.setProperty("role", "muted")
            head.addWidget(name, 1)
            row_layout.addLayout(head)
            if reason is None:
                available += 1
            state_text = tr("settings.agent_ready") if reason is None else (
                f"{tr('settings.agent_unavailable')} — {reason}"
            )
            meta_text = f"{tr(RISK_KEY[spec.risk])} · {state_text}"
            meta = ElidedLabel(meta_text, pixel_size=11, weight=400, tone="faint")
            meta.setFixedHeight(runtime.px(16))
            meta.setToolTip(meta_text)
            row_layout.addWidget(meta)
            row.setToolTip(f"{spec.description}\n\n{meta_text}")
            self.tools_box.insertWidget(self.tools_box.count() - 1, row)
            self._tool_rows[spec.id] = row
        total = len(self.registry.specs())
        self.tools_count.setText(tr("agent.tools_count", ready=available, total=total))
        # The canvas was sized when the list was empty; grow its minimum to the
        # real row stack so the scroll area scrolls instead of squeezing rows.
        self.tools_box.activate()
        self.tools_canvas.setMinimumHeight(self.tools_box.minimumSize().height())

    def _tool_context(self) -> ToolContext:
        return ToolContext(
            projects=self.projects,
            project=self.project,
            runner=self.runner,
            memory=self.context.memory,
            outputs=self.context.outputs,
            settings=self.context.settings,
            secrets=self.context.secrets,
            conversation_id=None,
            web=self.context.web,
            paths=self.context.paths,
        )

    def _on_network_toggled(self, checked: bool) -> None:
        self.context.settings.update({"agent.allow_network": bool(checked)})
        self.refresh_tools()
        if checked:
            context = self._tool_context()
            blocked = [(spec.id, reason) for spec, reason in self.registry.unavailable(context)
                       if spec.risk == NETWORK]
            if blocked:
                self._toast(tr("agent.network_still_blocked"), "warning")

    # ------------------------------------------------------------------ runs
    def _refresh_badges(self) -> None:
        supports = self._model_supports_tools()
        if supports is True:
            self.model_badge.setText(tr("agent.model_tools_yes"))
            self.model_badge.set_tone("success")
        elif supports is False:
            self.model_badge.setText(tr("agent.model_tools_no"))
            self.model_badge.set_tone("warning")
        else:
            self.model_badge.setText(tr("agent.model_tools_unknown"))
            self.model_badge.set_tone("muted")
        if not self._provider_ready():
            self.model_badge.setToolTip(tr("agent.need_key"))

    def _refresh_runs(self) -> None:
        while self.runs_box.count():
            item = self.runs_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        runs = self.agent.history()
        self.runs_empty.setVisible(not runs)
        for run in runs:
            row = _ClickFrame()
            row.setProperty("panel", "chip")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(runtime.px(9), runtime.px(6), runtime.px(9), runtime.px(6))
            row_layout.setSpacing(runtime.px(2))
            head = QHBoxLayout()
            head.setSpacing(runtime.px(6))
            task = QLabel(run.task or "—")
            task.setProperty("role", "muted")
            task.setWordWrap(True)  # the whole goal stays readable, never clipped
            head.addWidget(task, 1)
            head.addWidget(Badge(tr(f"agent.status_{run.status}"), self._status_tone(run.status)))
            row_layout.addLayout(head)
            key = "agent.run_meta_one" if run.tool_count == 1 else "agent.run_meta"
            meta = QLabel(
                tr(key).format(tools=run.tool_count, seconds=max(1, run.duration_ms // 1000))
            )
            meta.setProperty("role", "faint")
            row_layout.addWidget(meta)
            row.clicked.connect(lambda r=run: self._show_run(r))
            self.runs_box.addWidget(row)

    @staticmethod
    def _status_tone(status: str) -> str:
        return {
            "ok": "success",
            "running": "warning",
            "cancelled": "warning",
            "limit": "violet",
            "error": "danger",
        }.get(status, "muted")

    def _show_run(self, run: AgentRun) -> None:
        self._run = run
        self._clear_timeline()
        for step in run.steps:
            self._render_step(step)
        self.status_badge.setText(tr(f"agent.status_{run.status}"))
        self.status_badge.set_tone(self._status_tone(run.status))
        self._update_controls()

    # ------------------------------------------------------------- timeline
    def _clear_timeline(self) -> None:
        self.timeline.removeWidget(self.empty_state)
        while self.timeline.count() > 1:  # keep the stretch at the end
            item = self.timeline.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.setParent(None)
            widget.deleteLater()
        self.timeline.insertWidget(0, self.empty_state)
        self.empty_state.setVisible(True)
        self.live_label.setText("")
        self.live_label.setVisible(False)

    def _render_step(self, step: AgentStep) -> None:
        self.empty_state.setVisible(False)
        card = QFrame()
        card.setProperty("panel", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(runtime.px(12), runtime.px(9), runtime.px(12), runtime.px(10))
        layout.setSpacing(runtime.px(5))
        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        icon = QLabel()
        icon.setPixmap(runtime.icons().px(STEP_ICON.get(step.kind, "sparkles"), 13,
                                         "accent" if step.kind in {"final", "tool"} else "muted"))
        head.addWidget(icon)
        title = QLabel(self._step_title(step))
        title.setProperty("role", "section")
        head.addWidget(title, 1)
        if step.tool is not None:
            head.addWidget(Badge(tr(RISK_KEY.get(step.tool.risk, "agent.risk_read")),
                                 RISK_TONE.get(step.tool.risk, "muted")))
            head.addWidget(Badge(tr(f"agent.tool_state_{self._tool_state(step)}"),
                                 STEP_TONE.get(step.kind, "muted")))
        else:
            head.addWidget(Badge(tr(f"agent.kind_{step.kind}"), STEP_TONE.get(step.kind, "muted")))
        layout.addLayout(head)

        if step.tool is not None and step.tool.arguments:
            args = QLabel(self._format_arguments(step.tool.arguments))
            args.setProperty("role", "mono")
            args.setWordWrap(True)
            layout.addWidget(args)
        body_text = step.text if step.kind in {"thinking", "final", "error", "denied"} else ""
        if step.tool is not None and step.tool.output:
            body_text = step.tool.output
        if step.tool is not None and step.tool.error and not step.tool.output:
            body_text = step.tool.error
        if body_text:
            body = QLabel(self._compact(body_text))
            body.setProperty("role", "muted" if step.kind != "error" else "danger")
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(body)
        if step.tool is not None:
            meta = QLabel(tr("agent.tool_meta").format(ms=step.tool.duration_ms))
            meta.setProperty("role", "faint")
            layout.addWidget(meta)
        self.timeline.insertWidget(self.timeline.count() - 1, card)

    def _step_title(self, step: AgentStep) -> str:
        if step.tool is not None:
            spec = self.registry.get(step.tool.tool_id)
            label = tr(spec.label_key) if spec is not None and spec.label_key else step.tool.tool_id
            return label
        return tr(f"agent.kind_{step.kind}")

    @staticmethod
    def _tool_state(step: AgentStep) -> str:
        tool = step.tool
        if tool is None:
            return "done"
        if tool.approved is False:
            return "denied"
        if tool.ok:
            return "done"
        return "failed"

    @staticmethod
    def _format_arguments(arguments: dict) -> str:
        parts = []
        for key, value in arguments.items():
            text = str(value).replace("\n", " ⏎ ")
            if len(text) > 90:
                text = text[:90] + "…"
            parts.append(f"{key}={text}")
        return " · ".join(parts)

    @staticmethod
    def _compact(text: str, limit: int = 900) -> str:
        clean = text.strip()
        return clean if len(clean) <= limit else clean[:limit] + "…"

    # ------------------------------------------------------------------ run
    def _update_controls(self) -> None:
        running = self._thread is not None and self._thread.is_alive()
        ready = self._provider_ready()
        can_run = bool(self.task_edit.toPlainText().strip()) and bool(self.model_select.value) and ready
        self.run_button.setEnabled(can_run and not running)
        self.stop_button.setEnabled(running)
        self.task_edit.setReadOnly(running)
        self.model_select.setEnabled(not running)
        self.project_select.setEnabled(not running)
        self.refresh_tools_button.setEnabled(not running)
        if not ready:
            hint = tr("agent.need_key")
        elif not self.model_select.value:
            hint = tr("agent.need_model")
        elif self._model_supports_tools() is False:
            hint = tr("agent.model_no_tools")
        elif self.project is None and any(
            spec.requires_project for spec in self.registry.specs()
        ):
            hint = tr("agent.need_project")
        else:
            hint = tr("agent.run_hint")
        self.run_hint.setText(hint)

    def start(self) -> None:
        task = self.task_edit.toPlainText().strip()
        model_id = self.model_select.value
        if not task:
            self._toast(tr("agent.need_task"), "warning")
            return
        if not model_id:
            self._toast(tr("agent.need_model"), "warning")
            return
        if not self._provider_ready():
            self._toast(tr("agent.need_key"), "warning")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._cancel_event = threading.Event()
        self._clear_timeline()
        self.status_badge.setText(tr("agent.status_running"))
        self.status_badge.set_tone("warning")
        context = self._tool_context()
        context.cancel = self._cancel_event
        self._run = None
        self._set_busy(True)
        task_text = task
        thread = threading.Thread(
            target=self._work, args=(task_text, model_id, context, self._cancel_event),
            name="myai-agent", daemon=True,
        )
        self._thread = thread
        thread.start()
        self._update_controls()

    def _work(self, task: str, model_id: str, context: ToolContext,
              cancel: threading.Event) -> None:  # noqa: ANN001
        bridge = self._bridge
        try:
            run = self.agent.run(
                task,
                model_id=model_id,
                context=context,
                confirm=self._confirm,
                cancel=cancel,
                on_step=lambda step: bridge.step.emit(step),
                on_delta=lambda text: bridge.delta.emit(text),
                project=str(self.project.root) if self.project is not None else "",
            )
        except AppError as exc:
            run = AgentRun(
                id="", task=task, model_id=model_id, status="error", error=exc.to_dict(),
                final_text="",
            )
            bridge.step.emit(AgentStep(index=1, kind="error", text=exc.message))
        except Exception as exc:  # noqa: BLE001 - the GUI must survive anything
            run = AgentRun(
                id="", task=task, model_id=model_id, status="error",
                error={"code": "agent.error", "message": "Unexpected failure",
                       "details": type(exc).__name__},
            )
        bridge.finished.emit(run)

    def _confirm(self, tool: ToolSpec, arguments: dict) -> bool:
        """Called on the worker thread; the dialog is shown on the GUI thread."""
        request = ApprovalRequest(tool=tool, arguments=arguments)
        if self._closing:
            return False
        self._pending = request
        self._bridge.approval.emit(request)
        if not request.event.wait(timeout=300):
            return False
        return request.approved

    def _on_approval(self, request: ApprovalRequest) -> None:
        if self._closing or not self.isVisible():
            request.approved = False
            request.event.set()
            return
        title = tr("agent.approve_title")
        message = tr("agent.approve_body").format(
            tool=tr(request.tool.label_key) if request.tool.label_key else request.tool.id,
            arguments=request.describe(),
        )
        dialog = ConfirmDialog(
            self.window(),
            title,
            message,
            confirm_text=tr("agent.approve"),
            cancel_text=tr("agent.deny"),
            danger=request.tool.risk in SENSITIVE,
            icon="shield",
        )
        approved = dialog.exec() == ConfirmDialog.DialogCode.Accepted
        request.approved = approved
        request.event.set()
        self._pending = None
        if not approved:
            self._toast(tr("agent.denied_toast").format(tool=request.tool.id), "warning")

    def stop(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.status_badge.setText(tr("agent.status_stopping"))
            self.status_badge.set_tone("warning")
        pending = self._pending
        if pending is not None:
            pending.approved = False
            pending.event.set()

    def _set_busy(self, busy: bool) -> None:
        self.stop_button.setEnabled(busy)
        self.run_button.setEnabled(not busy)
        self.task_edit.setReadOnly(busy)

    def _on_step(self, step: AgentStep) -> None:
        self._render_step(step)
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        if step.kind == "final":
            self.status_badge.setText(tr("agent.status_ok"))
            self.status_badge.set_tone("success")

    def _on_delta(self, text: str) -> None:
        if not text:
            return
        current = self.live_label.text() + text
        self.live_label.setText(current[-600:])
        self.live_label.setVisible(True)

    def _on_finished(self, run: AgentRun) -> None:
        self._thread = None
        self._cancel_event = None
        self._pending = None
        self._set_busy(False)
        self._run = run
        self.live_label.setVisible(False)
        self.status_badge.setText(tr(f"agent.status_{run.status}"))
        self.status_badge.set_tone(self._status_tone(run.status))
        if run.status == "ok" and not any(step.kind == "final" for step in run.steps):
            self._render_step(AgentStep(index=len(run.steps) + 1, kind="final",
                                        text=run.final_text))
        if run.status == "ok":
            self._toast(tr("agent.done_ok").format(tools=run.tool_count), "success")
        elif run.status == "limit":
            self._toast(tr("agent.done_limit"), "warning")
        elif run.status == "error" and run.error:
            self._toast(tr("agent.done_error").format(message=run.error.get("message", "")), "error")
        elif run.status == "cancelled":
            self._toast(tr("agent.done_cancelled"), "info")
        self._refresh_runs()
        self._update_controls()
        if self._run is not None:
            self.status_badge.setToolTip(
                tr("agent.run_footer").format(seconds=max(1, run.duration_ms // 1000),
                                              tokens=run.usage.get("total_tokens", 0))
            )

    def _toast(self, message: str, tone: str = "success") -> None:
        if message:
            self.notify.emit(message, tone)
