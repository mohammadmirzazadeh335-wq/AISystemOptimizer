"""System Doctor: a measured health report of the app and its workspace.

Checks run off the GUI thread (toolchain probing spawns subprocesses), and every
row shows the measured fact rather than a generic "healthy". Failures carry the
advice the fix needs, and the report can be copied as plain text — without any
secret material, which the doctor itself verifies.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import tr
from ...services.doctor import FAIL, OK, SKIP, WARN, HealthCheck, HealthReport, report_text, run_checks
from ...services.toolchains import registry as toolchain_registry
from ..theme import runtime
from ..widgets.charts import GaugeScore
from ..widgets.foundation import Badge, Dot
from .page_base import PageShell, ghost_button, hint_label, primary_button, run_async

logger = logging.getLogger(__name__)

GROUP_TONE = {"storage": "info", "security": "violet", "runtime": "accent", "interface": "success"}
STATUS_TONE = {OK: "success", WARN: "warning", FAIL: "danger", SKIP: "text_faint"}
STATUS_LABEL = {OK: "doctor.status_ok", WARN: "doctor.status_warn", FAIL: "doctor.status_fail", SKIP: "doctor.status_skip"}


class DoctorPage(PageShell):
    notify = Signal(str, str)
    open_settings = Signal()

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("doctor.title", "doctor.subtitle", icon_name="shield")
        self.context = context
        self.report: HealthReport | None = None
        self._running = False
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.hero_card, hero = self.card()
        row = QHBoxLayout()
        row.setSpacing(runtime.px(18))
        self.gauge = GaugeScore()
        self.gauge.setFixedWidth(runtime.px(230))
        row.addWidget(self.gauge)
        summary = QVBoxLayout()
        summary.setSpacing(runtime.px(5))
        title_row = QHBoxLayout()
        title_row.setSpacing(runtime.px(6))
        self.running_badge = Badge(tr("doctor.running"), "accent")
        self.running_badge.setVisible(False)
        title_row.addWidget(self.running_badge)
        title_row.addStretch(1)
        self.stamp_label = QLabel("")
        self.stamp_label.setProperty("role", "faint")
        title_row.addWidget(self.stamp_label)
        summary.addLayout(title_row)
        self.verdict_label = QLabel(tr("doctor.not_run"))
        self.verdict_label.setProperty("role", "display")
        summary.addWidget(self.verdict_label)
        self.verdict_hint = QLabel("")
        self.verdict_hint.setProperty("role", "muted")
        self.verdict_hint.setWordWrap(True)
        summary.addWidget(self.verdict_hint)
        counts = QHBoxLayout()
        counts.setSpacing(runtime.px(6))
        self.ok_badge = Badge("", "success")
        self.warn_badge = Badge("", "warning")
        self.fail_badge = Badge("", "danger")
        self.skip_badge = Badge("", "muted")
        for badge in (self.ok_badge, self.warn_badge, self.fail_badge, self.skip_badge):
            counts.addWidget(badge)
        counts.addStretch(1)
        summary.addLayout(counts)
        self.meta_label = QLabel("")
        self.meta_label.setProperty("role", "faint")
        self.meta_label.setWordWrap(True)
        summary.addWidget(self.meta_label)
        summary.addStretch(1)
        row.addLayout(summary, 1)
        hero.addLayout(row)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(6))
        self.run_button = primary_button(tr("doctor.run"), "refresh")
        self.run_button.clicked.connect(self.start_checks)
        actions.addWidget(self.run_button)
        self.copy_button = ghost_button(tr("doctor.copy"), "copy")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy)
        actions.addWidget(self.copy_button)
        self.settings_button = ghost_button(tr("doctor.open_settings"), "settings")
        self.settings_button.clicked.connect(self.open_settings)
        actions.addWidget(self.settings_button)
        actions.addStretch(1)
        self.add_widget(self._wrap(actions))

        self.groups_card, groups_layout = self.card("doctor.checks_title", "list-check")
        self.groups_hint = hint_label(tr("doctor.checks_hint"))
        groups_layout.addWidget(self.groups_hint)
        self.groups_box = QVBoxLayout()
        self.groups_box.setSpacing(runtime.px(10))
        groups_layout.addLayout(self.groups_box)

    def _wrap(self, layout) -> QWidget:  # noqa: ANN001
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        """Re-render the last report; PageShell.rebuild calls this."""
        if self.report is not None:
            self._apply_report(self.report)

    def start_checks(self) -> None:
        if self._running:
            return
        self._set_running(True)
        run_async(
            self,
            lambda: run_checks(
                paths=self.context.paths,
                settings=self.context.settings,
                db=self.context.db,
                secrets=self.context.secrets,
                toolchain_registry=toolchain_registry(),
            ),
            on_success=self._apply_report,
            on_error=self._failed,
        )

    def run_now(self) -> HealthReport:
        """Synchronous run used by tests and by the first paint on a slow host."""
        report = run_checks(
            paths=self.context.paths,
            settings=self.context.settings,
            db=self.context.db,
            secrets=self.context.secrets,
            toolchain_registry=toolchain_registry(),
        )
        self._apply_report(report)
        return report

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.running_badge.setVisible(running)
        self.run_button.setEnabled(not running)

    def _failed(self, exc: Exception) -> None:
        self._set_running(False)
        logger.warning("doctor_failed error=%s", exc)
        self.notify.emit(str(exc), "error")

    def _apply_report(self, report: HealthReport) -> None:
        self._set_running(False)
        self.report = report
        counts = report.counts
        self.gauge.set_score(report.score, report.verdict)
        tone = {"healthy": "success", "attention": "warning", "needs_care": "danger"}[report.verdict]
        self.verdict_label.setText(tr(f"doctor.verdict_{report.verdict}"))
        self.verdict_label.setStyleSheet(f"color: {runtime.theme().color(tone)};")
        self.stamp_label.setText(report.generated_at.replace("T", " ").replace("+00:00", " UTC"))
        self.verdict_hint.setText(tr(f"doctor.verdict_hint_{report.verdict}"))
        self.ok_badge.setText(tr("doctor.count_ok", count=counts[OK]))
        self.warn_badge.setText(tr("doctor.count_warn", count=counts[WARN]))
        self.fail_badge.setText(tr("doctor.count_fail", count=counts[FAIL]))
        self.skip_badge.setText(tr("doctor.count_skip", count=counts[SKIP]))
        self.meta_label.setText(
            tr("doctor.meta", checks=len(report.checks), ms=report.duration_ms, at=report.generated_at)
        )
        self.copy_button.setEnabled(True)
        self._fill_groups(report)

    def _fill_groups(self, report: HealthReport) -> None:
        while self.groups_box.count():
            item = self.groups_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for group in ("storage", "security", "runtime", "interface"):
            items = [check for check in report.checks if check.group == group]
            if not items:
                continue
            block = QWidget()
            layout = QVBoxLayout(block)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(runtime.px(3))
            header = QHBoxLayout()
            header.setSpacing(runtime.px(6))
            header.addWidget(Dot(GROUP_TONE[group], 7))
            title = QLabel(tr(f"doctor.group_{group}"))
            title.setProperty("role", "section")
            header.addWidget(title)
            header.addStretch(1)
            layout.addLayout(header)
            for check in items:
                layout.addWidget(self._check_row(check))
            self.groups_box.addWidget(block)

    def _check_row(self, check: HealthCheck) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, runtime.px(2), 0, runtime.px(2))
        layout.setSpacing(runtime.px(8))
        layout.addWidget(Dot(STATUS_TONE[check.status], 7))
        name = QLabel(tr(f"doctor.check_{check.key}"))
        name.setMinimumWidth(runtime.px(150))
        layout.addWidget(name)
        detail = QLabel(check.detail or "—")
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        layout.addWidget(detail, 1)
        if check.advice:
            advice = QLabel(check.advice)
            advice.setProperty("role", "faint")
            layout.addWidget(advice)
        elif check.fix_key:
            advice = QLabel(tr(check.fix_key))
            advice.setProperty("role", "faint")
            advice.setWordWrap(True)
            advice.setMaximumWidth(runtime.px(320))
            layout.addWidget(advice)
        timing = QLabel(f"{check.ms} ms")
        timing.setProperty("role", "faint")
        timing.setMinimumWidth(runtime.px(48))
        timing.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(timing)
        badge_tone = {"success": "success", "warning": "warning", "danger": "danger"}.get(
            STATUS_TONE[check.status], "muted"
        )
        badge = Badge(tr(STATUS_LABEL[check.status]), badge_tone)
        layout.addWidget(badge)
        return row

    # ----------------------------------------------------------------- actions
    def _copy(self) -> None:
        if self.report is None:
            return
        QGuiApplication.clipboard().setText(report_text(self.report, title=tr("doctor.report_title")))
        self.notify.emit(tr("doctor.copied"), "success")

    # ----------------------------------------------------------- page contract
    def retranslate(self) -> None:
        super().retranslate()
        self.run_button.setText(tr("doctor.run"))
        self.gauge.update()
        self.copy_button.setText(tr("doctor.copy"))
        self.settings_button.setText(tr("doctor.open_settings"))
        self.running_badge.setText(tr("doctor.running"))
        self.groups_hint.setText(tr("doctor.checks_hint"))
        if self.report is not None:
            self._apply_report(self.report)

    def rebuild(self) -> None:
        report = self.report
        super().rebuild()
        if report is not None:
            self.report = report
            self._apply_report(report)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self.report is None and not self._running:
            self.start_checks()


__all__ = ["DoctorPage"]
