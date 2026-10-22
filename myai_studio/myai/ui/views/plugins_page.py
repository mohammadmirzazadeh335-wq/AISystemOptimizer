"""Plugins page (Phase 5).

A plugin is a folder with a ``plugin.json`` manifest. This build loads **data
plugins** (prompt packs) only: nothing is executed, permissions are checked at
load time, and every plugin starts disabled. The page shows the folder that is
scanned, the exact validation error for a rejected manifest, and what enabling a
pack actually does to the prompt library.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.errors import AppError
from ...i18n import tn, tr
from ...services.plugins import PluginInfo
from ..theme import runtime
from ..widgets.buttons import ToggleSwitch
from ..widgets.dialogs import ConfirmDialog
from ..widgets.foundation import Badge, ElidedLabel
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)


class PluginRow(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, plugin: PluginInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.setProperty("panel", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(14), runtime.px(10), runtime.px(13), runtime.px(11))
        layout.setSpacing(runtime.px(5))

        head = QHBoxLayout()
        head.setSpacing(runtime.px(7))
        name = QLabel(plugin.name)
        name.setProperty("role", "section")
        head.addWidget(name)
        if plugin.version:
            head.addWidget(Badge(f"v{plugin.version}", "muted"))
        head.addWidget(Badge(plugin.kind or "?", "muted"))
        if plugin.supported:
            head.addWidget(
                Badge(
                    tr("plugins.enabled_badge") if plugin.enabled else tr("plugins.disabled_badge"),
                    "success" if plugin.enabled else "muted",
                )
            )
        else:
            head.addWidget(Badge(tr("plugins.unsupported"), "danger"))
        head.addStretch(1)
        self.toggle = ToggleSwitch(on=plugin.enabled)
        self.toggle.setAccessibleName(tr("plugins.toggle_label", name=plugin.name))
        self.toggle.setEnabled(plugin.supported)
        self.toggle.toggled.connect(lambda checked: self.toggled.emit(self.plugin.id, checked))
        head.addWidget(self.toggle)
        layout.addLayout(head)

        if plugin.description:
            description = QLabel(plugin.description)
            description.setProperty("role", "muted")
            description.setWordWrap(True)
            layout.addWidget(description)

        detail_bits = [tr("plugins.id_label", id=plugin.id)]
        if plugin.author:
            detail_bits.append(tr("plugins.author_label", author=plugin.author))
        if plugin.permissions:
            detail_bits.append(tr("plugins.permissions_label", list=", ".join(plugin.permissions)))
        if plugin.supported:
            detail_bits.append(tn("plugins.prompt_count", len(plugin.prompts)))
            if plugin.enabled:
                detail_bits.append(tn("plugins.imported_count", plugin.imported))
        meta = QLabel(" · ".join(detail_bits))
        meta.setProperty("role", "faint")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        path = ElidedLabel(str(plugin.path), pixel_size=10, weight=400, tone="faint")
        path.setToolTip(str(plugin.path))
        layout.addWidget(path)

        if not plugin.supported:
            reason = tr(plugin.error_key) if plugin.error_key else plugin.error
            error = QLabel(tr("plugins.rejected", reason=reason))
            error.setProperty("role", "danger")
            error.setWordWrap(True)
            layout.addWidget(error)


class PluginsPage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("plugins.title", "plugins.subtitle", icon_name="plug")
        self.context = context
        self.service = context.plugins
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        bar = QHBoxLayout()
        bar.setSpacing(runtime.px(8))
        self.folder_label = QLabel("")
        self.folder_label.setProperty("role", "faint")
        self.folder_label.setWordWrap(True)
        bar.addWidget(self.folder_label, 1)
        self.example_button = ghost_button(tr("plugins.example"), "plus")
        self.example_button.clicked.connect(self.write_example)
        bar.addWidget(self.example_button)
        self.reload_button = primary_button(tr("plugins.reload"), "refresh")
        self.reload_button.clicked.connect(self.refresh)
        bar.addWidget(self.reload_button)
        holder = QWidget()
        holder.setLayout(bar)
        self.add_widget(holder)

        self.notes = QWidget()
        notes_layout = QVBoxLayout(self.notes)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(runtime.px(4))
        for key in ("plugins.rule_data_only", "plugins.rule_disabled", "plugins.rule_permissions"):
            notes_layout.addWidget(hint_label(tr(key)))
        self.add_widget(self.notes)

        self.empty = QLabel("")
        self.empty.setProperty("role", "muted")
        self.empty.setWordWrap(True)
        self.add_widget(self.empty)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(runtime.px(8))
        self.list_layout.addStretch(1)
        self.add_widget(self.list_host)

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        self.folder_label.setText(tr("plugins.folder", path=str(self.service.folder)))
        self.service.ensure_folder()
        try:
            plugins = self.service.discover()
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            plugins = []
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for plugin in plugins:
            row = PluginRow(plugin)
            row.toggled.connect(self._toggle)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self.empty.setVisible(not plugins)
        self.empty.setText(tr("plugins.empty", path=str(self.service.folder)))

    # ---------------------------------------------------------------- actions
    def _toggle(self, plugin_id: str, enabled: bool) -> None:
        if not enabled:
            dialog = ConfirmDialog(
                self.window(),
                tr("plugins.disable_title"),
                tr("plugins.disable_body"),
                confirm_text=tr("plugins.disable_confirm"),
                cancel_text=tr("dialog.cancel"),
                danger=True,
                icon="alert",
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.refresh()
                return
        ok, imported, kept, error = self.service.set_enabled(plugin_id, enabled)
        self.refresh()
        if not ok:
            self.notify.emit(error or tr("plugins.failed"), "error")
            return
        if enabled:
            self.notify.emit(tr("plugins.enabled_toast", count=imported), "success")
        else:
            self.notify.emit(tr("plugins.disabled_toast", kept=kept), "info")

    def write_example(self) -> None:
        path = self.service.write_example()
        self.refresh()
        self.notify.emit(tr("plugins.example_created", path=str(path)), "success")

    # -------------------------------------------------------------- translate
    def retranslate(self) -> None:
        super().retranslate()
        self.example_button.setText(tr("plugins.example"))
        self.reload_button.setText(tr("plugins.reload"))
        self.empty.setText(tr("plugins.empty", path=str(self.service.folder)))
        self.refresh()
