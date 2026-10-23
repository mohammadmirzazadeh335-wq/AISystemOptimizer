"""Appearance Atelier: pick one colour, see it measured before it is applied.

The audit is not decoration: every ratio on this page is computed by
``ui.theme.colorlab`` from the colours the renderer will actually use. A
candidate accent that fails 4.5:1 on the surface is called out *before* the
user applies it, and applying it still keeps the five built-in accents one
click away.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QGuiApplication, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ..theme import colorlab, runtime
from ..theme.tokens import ACCENTS
from ..widgets.foundation import Badge, repolish
from .page_base import PageShell, ghost_button, hint_label, primary_button

logger = logging.getLogger(__name__)

BUILTIN_ORDER = ("azure", "violet", "teal", "amber", "rose")


class _Swatch(QFrame):
    """Clickable colour chip with its own caption."""

    clicked = Signal(str)

    def __init__(self, key: str, color: str, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("Swatch")
        self.setProperty("panel", "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(caption)
        # 64 px clipped the 9 px caption against the card border; the chip is
        # 30 px and the caption needs a real line of its own.
        self.setFixedSize(runtime.px(78), runtime.px(76))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(runtime.px(7), runtime.px(7), runtime.px(7), runtime.px(5))
        layout.setSpacing(runtime.px(5))
        self.chip = QFrame()
        self.chip.setObjectName("SwatchChip")
        self.chip.setFixedHeight(runtime.px(30))
        self.chip.setStyleSheet(
            f"QFrame#SwatchChip {{ background: {color}; border: none; border-radius: 6px; }}"
        )
        layout.addWidget(self.chip)
        self.caption = QLabel(caption)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setProperty("role", "faint")
        self.caption.setStyleSheet(f"font-size: {runtime.px(9)}px;")
        self.caption.setFixedHeight(runtime.px(14))
        layout.addWidget(self.caption)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class _Preview(QWidget):
    """A small, real widget tree painted with the candidate accent."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccentPreview")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(runtime.px(14), runtime.px(12), runtime.px(14), runtime.px(14))
        outer.setSpacing(runtime.px(9))

        head = QHBoxLayout()
        head.setSpacing(runtime.px(6))
        self.dot = QLabel("●")
        self.dot.setStyleSheet("font-size: 12px;")
        self.title = QLabel(tr("appearance.preview_title"))
        self.title.setProperty("role", "section")
        head.addWidget(self.dot)
        head.addWidget(self.title)
        head.addStretch(1)
        self.badge = Badge(tr("appearance.preview_badge"), "accent")
        head.addWidget(self.badge)
        outer.addLayout(head)

        self.bubble = QLabel(tr("appearance.preview_bubble"))
        self.bubble.setWordWrap(True)
        self.bubble.setContentsMargins(runtime.px(10), runtime.px(8), runtime.px(10), runtime.px(8))
        outer.addWidget(self.bubble)

        self.code = QLabel("def greet(name: str) -> str:")
        self.code.setFont(runtime.mono_font(11))
        self.code.setContentsMargins(runtime.px(10), runtime.px(7), runtime.px(10), runtime.px(7))
        outer.addWidget(self.code)

        buttons = QHBoxLayout()
        buttons.setSpacing(runtime.px(7))
        buttons.addStretch(1)
        self.secondary = QLabel(tr("appearance.preview_secondary"))
        self.secondary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.secondary.setContentsMargins(runtime.px(12), runtime.px(6), runtime.px(12), runtime.px(6))
        buttons.addWidget(self.secondary)
        self.primary = QLabel(tr("appearance.preview_primary"))
        self.primary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.primary.setContentsMargins(runtime.px(14), runtime.px(6), runtime.px(14), runtime.px(6))
        buttons.addWidget(self.primary)
        outer.addLayout(buttons)
        outer.addStretch(1)

    def apply_colors(self, *, accent: str, accent_soft: str, text: str, muted: str, surface: str, border: str) -> None:
        label_on_accent = colorlab.readable_on(accent)
        self.setStyleSheet(
            f"QWidget#AccentPreview {{ background: {surface}; border: 1px solid {border};"
            f" border-radius: 12px; }}"
        )
        self.dot.setStyleSheet(f"color: {accent}; font-size: 12px; border: none;")
        self.title.setStyleSheet(f"color: {text}; border: none; background: transparent;")
        self.bubble.setStyleSheet(
            f"background: {accent_soft}; color: {text}; border: none; border-radius: 8px;"
        )
        self.code.setStyleSheet(
            f"background: {colorlab.mix(surface, '#000000', 0.20)}; color: {muted};"
            " border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;"
        )
        self.primary.setStyleSheet(
            f"background: {accent}; color: {label_on_accent}; border: none;"
            " border-radius: 7px; font-weight: 600;"
        )
        self.secondary.setStyleSheet(
            f"background: transparent; color: {text}; border: 1px solid {border}; border-radius: 7px;"
        )


class AppearancePage(PageShell):
    notify = Signal(str, str)

    def __init__(self, context) -> None:  # noqa: ANN001
        super().__init__("appearance.title", "appearance.subtitle", icon_name="palette")
        self.context = context
        self._candidate = self._initial_candidate()
        self._accent_key = str(context.settings.get("ui.accent", "azure") or "azure")
        self._hsv_locked = False
        self._build()
        self.retranslate()
        self.refresh()

    # ------------------------------------------------------------------ state
    def _initial_candidate(self) -> str:
        accent = str(self.context.settings.get("ui.accent", "azure") or "azure")
        if accent == "custom":
            value = colorlab.normalize(str(self.context.settings.get("ui.accent_custom", "") or ""))
            if value:
                return value
        theme = runtime.theme()
        return colorlab.normalize(theme.color("accent")) or "#2563eb"

    def candidate(self) -> str:
        return self._candidate

    def set_candidate(self, value: str, *, accent_key: str = "custom") -> None:
        normalised = colorlab.normalize(value)
        if not normalised:
            return
        self._candidate = normalised
        self._accent_key = accent_key
        self._hsv_locked = True
        hue, saturation, brightness = colorlab.hex_to_hsv(normalised)
        self.hue_slider.setValue(int(hue))
        self.saturation_slider.setValue(int(round(saturation)))
        self.brightness_slider.setValue(int(round(brightness)))
        self._hsv_locked = False
        self.hex_edit.setText(normalised)
        self._refresh_preview()
        self._refresh_swatches()
        self._refresh_audit()
        self._update_state()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        swatch_card, swatch_layout = self.card("appearance.palette_title", "palette")
        self.swatch_hint = hint_label(tr("appearance.palette_hint"))
        swatch_layout.addWidget(self.swatch_hint)
        grid = QGridLayout()
        grid.setSpacing(runtime.px(8))
        self.swatches: dict[str, _Swatch] = {}
        for index, key in enumerate(BUILTIN_ORDER):
            frame = self._swatch(key, self._builtin_color(key), key)
            grid.addWidget(frame, 0, index)
            self.swatches[key] = frame
        self.custom_swatch = self._swatch("custom", self._candidate, "custom")
        grid.addWidget(self.custom_swatch, 0, len(BUILTIN_ORDER))
        self.swatches["custom"] = self.custom_swatch
        swatch_layout.addLayout(grid)

        sliders = QGridLayout()
        sliders.setHorizontalSpacing(runtime.px(10))
        sliders.setVerticalSpacing(runtime.px(6))
        sliders.setColumnStretch(1, 1)
        sliders.setColumnMinimumWidth(1, runtime.px(220))
        self.hue_slider = self._slider(0, 359, "appearance.hue")
        self.hue_slider.setObjectName("HueSlider")
        self.saturation_slider = self._slider(0, 100, "appearance.saturation")
        self.brightness_slider = self._slider(0, 100, "appearance.brightness")
        for row, (slider, label) in enumerate(
            (
                (self.hue_slider, "appearance.hue"),
                (self.saturation_slider, "appearance.saturation"),
                (self.brightness_slider, "appearance.brightness"),
            )
        ):
            caption = QLabel(tr(label))
            caption.setProperty("role", "faint")
            caption.setMinimumWidth(runtime.px(86))
            sliders.addWidget(caption, row, 0)
            sliders.addWidget(slider, row, 1)
        swatch_layout.addLayout(sliders)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(runtime.px(8))
        hex_row.addWidget(hint_label(tr("appearance.hex"), tone="faint"))
        self.hex_edit = QLineEdit(self._candidate)
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(runtime.px(110))
        self.hex_edit.setAccessibleName(tr("appearance.hex"))
        validator = QRegularExpressionValidator(QRegularExpression(r"^#[0-9a-fA-F]{6}$"), self)
        self.hex_edit.setValidator(validator)
        self.hex_edit.editingFinished.connect(self._hex_committed)
        hex_row.addWidget(self.hex_edit)
        self.copy_button = ghost_button(tr("appearance.copy_hex"), "copy")
        self.copy_button.clicked.connect(self._copy_hex)
        hex_row.addWidget(self.copy_button)
        hex_row.addStretch(1)
        swatch_layout.addLayout(hex_row)

        preview_card, preview_layout = self.card("appearance.preview_card", "eye")
        self.preview = _Preview()
        preview_layout.addWidget(self.preview)
        self.preview_note = hint_label(tr("appearance.preview_note"))
        preview_layout.addWidget(self.preview_note)

        audit_card, audit_layout = self.card("appearance.audit_title", "shield")
        self.audit_hint = hint_label(tr("appearance.audit_hint"))
        audit_layout.addWidget(self.audit_hint)
        self.audit_grid = QGridLayout()
        self.audit_grid.setHorizontalSpacing(runtime.px(10))
        self.audit_grid.setVerticalSpacing(runtime.px(4))
        audit_layout.addLayout(self.audit_grid)
        self.audit_summary = QLabel("")
        self.audit_summary.setWordWrap(True)
        self.audit_summary.setProperty("role", "muted")
        audit_layout.addWidget(self.audit_summary)

        actions = QHBoxLayout()
        actions.setSpacing(runtime.px(6))
        self.state_label = QLabel("")
        self.state_label.setProperty("role", "faint")
        actions.addWidget(self.state_label)
        actions.addStretch(1)
        self.reset_button = ghost_button(tr("appearance.reset"), "refresh")
        self.reset_button.clicked.connect(self.reset)
        actions.addWidget(self.reset_button)
        self.apply_button = primary_button(tr("appearance.apply"), "check")
        self.apply_button.clicked.connect(self.apply_candidate)
        actions.addWidget(self.apply_button)
        container = QWidget()
        container.setLayout(actions)
        self.add_widget(container)

    def _swatch(self, key: str, color: str, label_key: str) -> _Swatch:
        frame = _Swatch(key, color, tr(f"appearance.accent_{label_key}"))
        frame.clicked.connect(self._swatch_clicked)
        return frame

    def _builtin_color(self, key: str) -> str:
        mode = "dark" if runtime.theme().is_dark else "light"
        return ACCENTS[key][mode]

    def _slider(self, low: int, high: int, name: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setMinimumHeight(runtime.px(24))
        slider.setMinimumWidth(runtime.px(220))
        slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        slider.setAccessibleName(tr(name))
        slider.valueChanged.connect(self._slider_changed)
        return slider

    # ------------------------------------------------------------------ events
    def _swatch_clicked(self, key: str) -> None:
        if key == "custom":
            self.set_candidate(self._candidate, accent_key="custom")
        else:
            self.set_candidate(self._builtin_color(key), accent_key=key)

    def _slider_changed(self, _value: int) -> None:
        if self._hsv_locked:
            return
        color = colorlab.hsv_hex(
            self.hue_slider.value(), self.saturation_slider.value(), self.brightness_slider.value()
        )
        self._candidate = color
        self._accent_key = "custom"
        self.hex_edit.setText(color)
        self._refresh_preview()
        self._refresh_swatches()
        self._refresh_audit()
        self._update_state()

    def _hex_committed(self) -> None:
        value = colorlab.normalize(self.hex_edit.text())
        if not value:
            self.hex_edit.setText(self._candidate)
            return
        if value != self._candidate:
            self.set_candidate(value, accent_key="custom")

    def _copy_hex(self) -> None:
        QGuiApplication.clipboard().setText(self._candidate)
        self.notify.emit(tr("appearance.copied", hex=self._candidate), "success")

    def apply_candidate(self) -> None:
        settings = self.context.settings
        try:
            if self._accent_key == "custom":
                settings.set("ui.accent_custom", self._candidate)
                settings.set("ui.accent", "custom")
            else:
                settings.set("ui.accent", self._accent_key)
        except Exception as exc:  # noqa: BLE001 - validation error is user-facing
            self.notify.emit(str(exc), "error")
            return
        self.notify.emit(tr("appearance.applied", hex=self._candidate), "success")

    def reset(self) -> None:
        try:
            self.context.settings.set("ui.accent_custom", "")
            self.context.settings.set("ui.accent", "azure")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            return
        self._accent_key = "azure"
        self.set_candidate(self._builtin_color("azure"), accent_key="azure")
        self.notify.emit(tr("appearance.reset_done"), "info")

    # ------------------------------------------------------------------ paints
    def refresh(self) -> None:
        """Re-render the page from the saved settings (also the rebuild hook)."""
        if self._accent_key != "custom":
            self._candidate = self._initial_candidate()
        self._sync_sliders()
        self._refresh_preview()
        self._refresh_swatches()
        self._refresh_audit()
        self._update_state()

    def _sync_sliders(self) -> None:
        hue, saturation, brightness = colorlab.hex_to_hsv(self._candidate)
        self._hsv_locked = True
        self.hue_slider.setValue(int(round(hue)) % 360)
        self.saturation_slider.setValue(int(round(saturation)))
        self.brightness_slider.setValue(int(round(brightness)))
        self._hsv_locked = False
        self.hex_edit.setText(self._candidate)

    def _refresh_preview(self) -> None:
        theme = runtime.theme()
        mode = "light" if not theme.is_dark else "dark"
        ramp = colorlab.accent_ramp(self._candidate, mode=mode, surface=theme.color("surface"))
        accent = ramp["base"]
        soft = colorlab.mix(theme.color("surface"), accent, 0.16 if theme.is_dark else 0.12)
        self.preview.apply_colors(
            accent=accent,
            accent_soft=soft,
            text=theme.color("text"),
            muted=theme.color("text_muted"),
            surface=theme.color("surface_2"),
            border=theme.color("border"),
        )

    def _refresh_swatches(self) -> None:
        for key, frame in self.swatches.items():
            selected = key == self._accent_key
            # Scoped to the swatch itself: an unscoped ``QFrame`` selector also
            # drew a border around the colour chip and the caption underneath.
            frame.setStyleSheet(
                "QFrame#Swatch { border: 2px solid %s; border-radius: 10px; background: transparent; }"
                % (runtime.theme().color("accent") if selected else "transparent")
            )
        self.custom_swatch.chip.setStyleSheet(
            f"QFrame#SwatchChip {{ background: {self._candidate}; border: none; border-radius: 6px; }}"
        )

    def _audit_entries(self) -> list[dict]:
        theme = runtime.theme()
        mode = "light" if not theme.is_dark else "dark"
        ramp = colorlab.accent_ramp(self._candidate, mode=mode, surface=theme.color("surface"))
        accent = ramp["base"]
        label_on_accent = colorlab.readable_on(accent)
        colors = dict(theme.colors)
        # The candidate accent is not in the theme yet; measure it directly.
        colors["accent"] = accent
        colors["accent_button_text"] = label_on_accent
        pairs = [
            ("appearance.audit_body", "text", "surface"),
            ("appearance.audit_muted", "text_muted", "surface"),
            ("appearance.audit_accent_text", "accent", "surface"),
            ("appearance.audit_accent_button", "accent_button_text", "accent"),
            ("appearance.audit_success", "success", "surface"),
            ("appearance.audit_warning", "warning", "surface"),
            ("appearance.audit_danger", "danger", "surface"),
        ]
        return colorlab.audit_pairs(colors, pairs)

    def _refresh_audit(self) -> None:
        while self.audit_grid.count():
            item = self.audit_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        entries = self._audit_entries()
        failures = 0
        for row, entry in enumerate(entries):
            label = QLabel(tr(entry["label"]))
            label.setProperty("role", "muted")
            self.audit_grid.addWidget(label, row, 0)
            sample = QLabel("Aa")
            sample.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sample.setFixedSize(runtime.px(34), runtime.px(22))
            sample.setStyleSheet(
                f"background: {entry['background']}; color: {entry['foreground']};"
                " border-radius: 5px; font-weight: 600;"
            )
            self.audit_grid.addWidget(sample, row, 1)
            ratio = QLabel(f"{entry['ratio']:.2f}:1")
            ratio.setProperty("role", "mono")
            ratio.setMinimumWidth(runtime.px(64))
            self.audit_grid.addWidget(ratio, row, 2)
            passed = entry["passes"]
            if not passed:
                failures += 1
            level_text = {
                "AAA": "AAA", "AA": "AA", "AA-large": "AA L", "large-only": "LARGE", "fail": "FAIL",
            }.get(entry["level"], "FAIL")
            badge = Badge(level_text, "success" if passed else "danger")
            self.audit_grid.addWidget(badge, row, 3)
        if failures:
            self.audit_summary.setProperty("role", "warning")
            self.audit_summary.setText(tr("appearance.audit_failures", count=failures))
        else:
            self.audit_summary.setProperty("role", "success")
            self.audit_summary.setText(tr("appearance.audit_ok"))
        repolish(self.audit_summary)

    def _update_state(self) -> None:
        theme = runtime.theme()
        applied = str(self.context.settings.get("ui.accent", "azure"))
        current = colorlab.normalize(theme.color("accent"))
        same = self._candidate == current and (
            (self._accent_key == applied)
            or (self._accent_key == "custom" and applied == "custom")
        )
        self.state_label.setText(
            tr("appearance.state_applied") if same else tr("appearance.state_preview")
        )
        self.apply_button.setEnabled(not same)
        self.apply_button.setToolTip("" if not same else tr("appearance.state_applied"))

    # ----------------------------------------------------------- page contract
    def rebuild(self) -> None:
        candidate = self._candidate
        key = self._accent_key
        super().rebuild()
        self._candidate = candidate
        self._accent_key = key
        self.refresh()

    def retranslate(self) -> None:
        super().retranslate()
        self.swatch_hint.setText(tr("appearance.palette_hint"))
        self.audit_hint.setText(tr("appearance.audit_hint"))
        self.preview_note.setText(tr("appearance.preview_note"))
        self.copy_button.setText(tr("appearance.copy_hex"))
        self.apply_button.setText(tr("appearance.apply"))
        self.reset_button.setText(tr("appearance.reset"))
        self.hex_edit.setAccessibleName(tr("appearance.hex"))
        for key, frame in self.swatches.items():
            frame.caption.setText(tr(f"appearance.accent_{key}"))
            frame.setToolTip(tr(f"appearance.accent_{key}"))
        self.preview.title.setText(tr("appearance.preview_title"))
        self.preview.bubble.setText(tr("appearance.preview_bubble"))
        self.preview.primary.setText(tr("appearance.preview_primary"))
        self.preview.secondary.setText(tr("appearance.preview_secondary"))
        self.preview.badge.setText(tr("appearance.preview_badge"))


__all__ = ["AppearancePage"]
