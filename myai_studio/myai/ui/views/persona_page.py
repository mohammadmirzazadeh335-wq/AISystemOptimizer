"""Personality page — user profile file and assistant persona, stored apart.

Two visibly separate surfaces, matching the service split:

1. the **profile file** (Markdown on disk, owned by the user), and
2. the **assistant persona** (settings-backed instructions and style).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...core.errors import AppError
from ...i18n import tr
from ...services.persona import DETAIL_LEVELS, LANGUAGES, TONES
from ..theme import runtime
from ..widgets.fields import PillToggle, SelectField
from .page_base import (
    PageShell,
    auto_direction,
    field_label,
    ghost_button,
    hint_label,
    primary_button,
    secondary_button,
)

logger = logging.getLogger(__name__)

TONE_KEYS = {
    "precise": "persona.tone_precise",
    "friendly": "persona.tone_friendly",
    "formal": "persona.tone_formal",
    "concise": "persona.tone_concise",
}
DETAIL_KEYS = {
    "brief": "persona.detail_brief",
    "balanced": "persona.detail_balanced",
    "detailed": "persona.detail_detailed",
}
LANGUAGE_KEYS = {
    "auto": "persona.lang_auto",
    "fa": "persona.lang_fa",
    "en": "persona.lang_en",
}


class PersonaPage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("persona.title", "persona.subtitle", icon_name="user")
        self.context = context
        self._dirty = False
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self._build_profile_card()
        self._build_persona_card()
        self._build_separation_card()

    def _build_profile_card(self) -> None:
        card, layout = self.card("persona.profile_card", "file")
        layout.addWidget(hint_label(tr("persona.profile_hint")))
        path_row = QHBoxLayout()
        path_row.setSpacing(runtime.px(7))
        path_row.addWidget(field_label(tr("persona.profile_path")))
        self.path_label = QLabel(str(self.context.persona.profile_path))
        self.path_label.setProperty("role", "mono")
        self.path_label.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_row.addWidget(self.path_label, 1)
        layout.addLayout(path_row)

        self.profile_editor = QPlainTextEdit()
        self.profile_editor.setAccessibleName(tr("persona.profile_card"))
        self.profile_editor.setMinimumHeight(runtime.px(220))
        # Prose, not code: the UI font shapes Persian correctly, while a mono
        # fallback stretches the zero-width non-joiner into a visible gap.
        self.profile_editor.setFont(runtime.ui_font(12))
        auto_direction(self.profile_editor)
        self.profile_editor.textChanged.connect(self._mark_dirty)
        layout.addWidget(self.profile_editor)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(7))
        save = primary_button(tr("persona.save_profile"), "check")
        save.clicked.connect(self._save_profile)
        row.addWidget(save)
        reload_button = secondary_button(tr("persona.reload"), "refresh")
        reload_button.clicked.connect(self._reload_profile)
        row.addWidget(reload_button)
        choose = secondary_button(tr("persona.choose_file"), "folder")
        choose.clicked.connect(self._choose_file)
        row.addWidget(choose)
        row.addStretch(1)
        self.profile_status = QLabel("")
        self.profile_status.setProperty("role", "faint")
        row.addWidget(self.profile_status)
        layout.addLayout(row)

    def _build_persona_card(self) -> None:
        card, layout = self.card("persona.persona_card", "sparkles")
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(runtime.px(9))
        self.enabled_toggle = PillToggle("sparkles", tr("persona.enabled"))
        self.enabled_toggle.setAccessibleName(tr("persona.enabled"))
        self.enabled_toggle.toggled.connect(self._mark_dirty)
        toggle_row.addWidget(self.enabled_toggle)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        self.persona_editor = QPlainTextEdit()
        self.persona_editor.setAccessibleName(tr("persona.persona_card"))
        self.persona_editor.setFont(runtime.ui_font(12))
        self.persona_editor.setPlaceholderText(tr("persona.placeholder"))
        auto_direction(self.persona_editor)
        self.persona_editor.setMinimumHeight(runtime.px(110))
        self.persona_editor.textChanged.connect(self._mark_dirty)
        layout.addWidget(self.persona_editor)

        row = QHBoxLayout()
        row.setSpacing(runtime.px(12))
        self.tone_picker = SelectField([], placeholder=tr("persona.tone"))
        self.detail_picker = SelectField([], placeholder=tr("persona.detail"))
        self.language_picker = SelectField([], placeholder=tr("persona.language"))
        for key, picker in (
            ("persona.tone", self.tone_picker),
            ("persona.detail", self.detail_picker),
            ("persona.language", self.language_picker),
        ):
            column = QVBoxLayout()
            column.setSpacing(runtime.px(3))
            column.addWidget(field_label(tr(key)))
            column.addWidget(picker)
            row.addLayout(column)
        row.addStretch(1)
        layout.addLayout(row)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(7))
        save = primary_button(tr("persona.save"), "check")
        save.clicked.connect(self._save_persona)
        actions.addWidget(save)
        reset = ghost_button(tr("persona.reset"), "refresh")
        reset.clicked.connect(self._reset_persona)
        actions.addWidget(reset)
        actions.addStretch(1)
        self.persona_status = QLabel("")
        self.persona_status.setProperty("role", "faint")
        actions.addWidget(self.persona_status)
        layout.addLayout(actions)

    def _build_separation_card(self) -> None:
        card, layout = self.card("persona.separation_card", "shield")
        layout.addWidget(hint_label(tr("persona.separation_body")))
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "mono")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"font-size: {runtime.px(10)}px;")
        layout.addWidget(self.summary_label)

    # ------------------------------------------------------------------ state
    def refresh(self) -> None:
        self.profile_editor.blockSignals(True)
        self.profile_editor.setPlainText(self.context.persona.read_profile())
        self.profile_editor.blockSignals(False)
        config = self.context.persona.config()
        self.enabled_toggle.setChecked(config.enabled)
        self.persona_editor.blockSignals(True)
        self.persona_editor.setPlainText(config.text)
        self.persona_editor.blockSignals(False)
        self._fill_pickers(config.tone, config.detail, config.language)
        self._update_summary()
        self._dirty = False
        self.profile_status.setText("")
        self.persona_status.setText("")

    def _fill_pickers(self, tone: str = "", detail: str = "", language: str = "") -> None:
        self.tone_picker.set_items([(key, tr(TONE_KEYS[key])) for key in TONES])
        self.detail_picker.set_items([(key, tr(DETAIL_KEYS[key])) for key in DETAIL_LEVELS])
        self.language_picker.set_items([(key, tr(LANGUAGE_KEYS[key])) for key in LANGUAGES])
        if tone:
            self.tone_picker.set_value(tone)
        if detail:
            self.detail_picker.set_value(detail)
        if language:
            self.language_picker.set_value(language)

    def _update_summary(self) -> None:
        memory_usage = self.context.memory.usage()
        profile_chars = len(self.context.persona.read_profile())
        self.summary_label.setText(
            tr(
                "persona.separation_stats",
                profile_chars=profile_chars,
                memory=memory_usage.global_count + memory_usage.conversation_count,
            )
        )

    # ------------------------------------------------------------------ edits
    def _mark_dirty(self, *args) -> None:  # noqa: ANN002
        self._dirty = True
        self.profile_status.setText(tr("persona.unsaved"))
        self.persona_status.setText(tr("persona.unsaved"))

    def _save_profile(self) -> None:
        try:
            self.context.persona.write_profile(self.profile_editor.toPlainText())
        except (AppError, OSError) as exc:
            self.notify.emit(exc.message if isinstance(exc, AppError) else str(exc), "error")
            return
        self.profile_status.setText(tr("persona.saved"))
        self._update_summary()
        self.notify.emit(tr("persona.profile_saved_toast"), "success")

    def _reload_profile(self) -> None:
        self.profile_editor.blockSignals(True)
        self.profile_editor.setPlainText(self.context.persona.read_profile())
        self.profile_editor.blockSignals(False)
        self.profile_status.setText(tr("persona.reloaded"))
        self._update_summary()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("persona.choose_file"),
            str(self.context.paths.home),
            "Markdown (*.md *.txt);;All files (*)",
        )
        if not path:
            return
        try:
            text = self.context.persona.import_profile(Path(path))
        except (AppError, OSError) as exc:
            self.notify.emit(exc.message if isinstance(exc, AppError) else str(exc), "error")
            return
        self.profile_editor.blockSignals(True)
        self.profile_editor.setPlainText(text)
        self.profile_editor.blockSignals(False)
        self.profile_status.setText(tr("persona.imported"))
        self._update_summary()

    def _save_persona(self) -> None:
        try:
            self.context.persona.save(
                enabled=self.enabled_toggle.isChecked(),
                text=self.persona_editor.toPlainText(),
                tone=self.tone_picker.value or "precise",
                detail=self.detail_picker.value or "balanced",
                language=self.language_picker.value or "auto",
            )
        except AppError as exc:
            self.notify.emit(exc.message, "error")
            return
        self.persona_status.setText(tr("persona.saved"))
        self._update_summary()
        self.notify.emit(tr("persona.persona_saved_toast"), "success")

    def _reset_persona(self) -> None:
        self.enabled_toggle.setChecked(False)
        self.persona_editor.blockSignals(True)
        self.persona_editor.clear()
        self.persona_editor.blockSignals(False)
        self._fill_pickers("precise", "balanced", "auto")
        self.persona_status.setText(tr("persona.unsaved"))
        self._mark_dirty()

    def retranslate(self) -> None:
        super().retranslate()
        self._fill_pickers(
            self.tone_picker.value or "precise",
            self.detail_picker.value or "balanced",
            self.language_picker.value or "auto",
        )
        self.enabled_toggle.set_text(tr("persona.enabled"))
        self.persona_editor.setFont(runtime.ui_font(12))
        self.persona_editor.setPlaceholderText(tr("persona.placeholder"))
        auto_direction(self.persona_editor)
        self._update_summary()
