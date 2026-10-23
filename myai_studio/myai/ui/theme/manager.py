"""Theme application: fonts, palette, stylesheet and layout direction.

Qt stylesheets have no variables, so the stylesheet is *generated* from the
design tokens.  Widgets never contain literal colours.
"""

from __future__ import annotations

import logging
import sys
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from ...core.paths import AppPaths
from ...i18n import is_rtl
from ...services.settings import SettingsService
from .icons import IconCache
from .tokens import METRICS, Theme, build_theme

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parents[3] / "assets"
FONT_FILES = [
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
    "Vazirmatn-Regular.ttf",
    "Vazirmatn-Medium.ttf",
    "Vazirmatn-SemiBold.ttf",
    "Vazirmatn-Bold.ttf",
]

MONO_FAMILIES = ["Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "DejaVu Sans Mono"]


def detect_system_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:  # pragma: no cover - older Qt
        pass
    if sys.platform.startswith("win"):
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except OSError:
            pass
    return True


#: Applications that have already been switched to the Fusion style. Calling
#: ``setStyle`` again re-polishes every live widget and is measurably slow, so it
#: runs once per process instead of once per manager.
_STYLED_APPS: "weakref.WeakSet[QApplication]" = weakref.WeakSet()

#: Last style signature applied to each application. Re-applying an identical
#: application stylesheet makes Qt re-polish every widget in the process — in a
#: test session with many windows that grows without bound — so an unchanged
#: look is a no-op.
_APPLIED_STYLE: "weakref.WeakKeyDictionary[QApplication, tuple]" = weakref.WeakKeyDictionary()


class ThemeManager(QObject):
    theme_changed = Signal(object)

    def __init__(self, app: QApplication, settings: SettingsService, paths: AppPaths) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._paths = paths
        self.icons = IconCache()
        self._fonts_loaded = False
        self._style_set = False
        self._theme: Theme | None = None
        self._scale = 1.0
        self._family = "Vazirmatn"
        self._mono = "DejaVu Sans Mono"
        settings.subscribe(self._on_settings_changed)

    # ------------------------------------------------------------------ public
    @property
    def theme(self) -> Theme:
        if self._theme is None:
            self.apply()
        assert self._theme is not None
        return self._theme

    @property
    def scale(self) -> float:
        return self._scale

    @property
    def font_family(self) -> str:
        return self._family

    @property
    def mono_family(self) -> str:
        return self._mono

    def apply(self, *, emit: bool = True) -> Theme:
        settings = self._settings
        self._load_fonts()
        language = settings.get("ui.language", "fa")
        theme_name = settings.get("ui.theme", "midnight")
        accent = settings.get("ui.accent", "azure")
        custom_accent = str(settings.get("ui.accent_custom", "") or "")
        self._scale = float(settings.get("ui.font_scale", 1.0) or 1.0)
        theme = build_theme(
            theme_name,
            accent,
            system_dark=detect_system_dark(),
            custom_accent=custom_accent,
        )

        if not self._style_set:
            if self._app not in _STYLED_APPS:
                self._app.setStyle("Fusion")
                _STYLED_APPS.add(self._app)
            self._style_set = True

        self._family = "Vazirmatn" if language == "fa" else "Inter"
        if self._family not in QFontDatabase.families():
            self._family = "Segoe UI" if sys.platform.startswith("win") else QFontDatabase.families()[0]
        mono_candidates = QFontDatabase.families()
        self._mono = next((f for f in MONO_FAMILIES if f in mono_candidates), "Monospace")

        direction = Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
        stylesheet = build_stylesheet(theme, self._scale, mono_family=self._mono, rtl=is_rtl())
        signature = (stylesheet, direction, self._family, self._scale)
        if _APPLIED_STYLE.get(self._app) != signature:
            self._app.setLayoutDirection(direction)
            self._apply_font()
            self._apply_palette(theme)
            self._app.setStyleSheet(stylesheet)
            _APPLIED_STYLE[self._app] = signature
        self.icons.update(theme.color("text"), theme.color("text_muted"), theme.color("accent"))
        self._theme = theme
        if emit:
            self.theme_changed.emit(theme)
        logger.info("theme_applied theme=%s accent=%s scale=%.2f dir=%s", theme.key, accent, self._scale, direction.name)
        return theme

    def color(self, token: str) -> str:
        return self.theme.color(token)

    # ------------------------------------------------------------------ internal
    def _apply_font(self) -> None:
        base_px = max(11, round(METRICS.base_font * self._scale))
        font = QFont(self._family)
        font.setPixelSize(base_px)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self._app.setFont(font)

    def _load_fonts(self) -> None:
        if self._fonts_loaded:
            return
        loaded = []
        for name in FONT_FILES:
            path = ASSETS / "fonts" / name
            if not path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id != -1:
                loaded.extend(QFontDatabase.applicationFontFamilies(font_id))
        self._fonts_loaded = True
        logger.info("fonts_loaded families=%s", ",".join(sorted(set(loaded))) or "none")

    def _apply_palette(self, theme: Theme) -> None:
        c = theme.color
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c("bg")))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(c("text")))
        palette.setColor(QPalette.ColorRole.Base, QColor(c("surface")))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c("surface_2")))
        palette.setColor(QPalette.ColorRole.Text, QColor(c("text")))
        palette.setColor(QPalette.ColorRole.Button, QColor(c("surface_2")))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c("text")))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c("accent")))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c("accent_contrast")))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c("surface_3")))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c("text")))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c("text_faint")))
        palette.setColor(QPalette.ColorRole.Link, QColor(c("accent")))
        palette.setColor(QPalette.ColorRole.Mid, QColor(c("border")))
        palette.setColor(QPalette.ColorRole.Dark, QColor(c("bg_soft")))
        palette.setColor(QPalette.ColorRole.Light, QColor(c("surface_3")))
        disabled = QColor(c("text_faint"))
        disabled.setAlpha(140)
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.HighlightedText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        self._app.setPalette(palette)

    def _on_settings_changed(self, changes: dict) -> None:
        relevant = {
            "ui.theme", "ui.accent", "ui.accent_custom", "ui.font_scale",
            "ui.language", "ui.density", "ui.reduce_motion",
        }
        if relevant & set(changes):
            self.apply()


# --------------------------------------------------------------------------- stylesheet
def build_stylesheet(
    theme: Theme, scale: float = 1.0, mono_family: str = "DejaVu Sans Mono", rtl: bool = False
) -> str:
    c = theme.color
    fs = lambda n: max(9, round(n * scale))  # noqa: E731
    side_a = "left" if rtl else "right"
    side_b = "right" if rtl else "left"

    return f"""
/* ---------------------------------------------------------------- base */
* {{ outline: none; }}
QWidget {{
    color: {c('text')};
    font-size: {fs(13)}px;
}}
QMainWindow, QDialog {{ background-color: {c('bg')}; }}
QWidget#AppRoot {{ background-color: {c('bg')}; }}
QWidget#Transparent, QWidget#Transparent > QWidget {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {c('text_muted')}; }}
QLabel[role="faint"] {{ color: {c('text_faint')}; }}
QLabel[role="accent"] {{ color: {c('accent')}; }}
QLabel[role="success"] {{ color: {c('success')}; }}
QLabel[role="warning"] {{ color: {c('warning')}; }}
QLabel[role="danger"] {{ color: {c('danger')}; }}
QLabel[role="h1"] {{ font-size: {fs(26)}px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: {fs(19)}px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: {fs(15)}px; font-weight: 600; }}
QLabel[role="section"] {{
    font-size: {fs(10)}px; font-weight: 700; color: {c('text_faint')};
    padding: 2px 0px;
}}
QLabel[role="eyebrow"] {{
    font-size: {fs(10)}px; font-weight: 700; color: {c('accent')};
}}
QLabel[role="mono"] {{ font-family: "{mono_family}"; font-size: {fs(11)}px; color: {c('text_muted')}; }}

QLabel[badge] {{
    border-radius: {max(6, round(7 * scale))}px;
    padding: {max(2, round(2 * scale))}px {max(6, round(8 * scale))}px;
    font-size: {fs(10)}px;
    font-weight: 600;
}}
QLabel[badge="accent"] {{ background: {c('accent_soft')}; color: {c('accent')}; }}
QLabel[badge="violet"] {{ background: {c('violet_soft')}; color: {c('violet')}; }}
QLabel[badge="success"] {{ background: {c('success_soft')}; color: {c('success')}; }}
QLabel[badge="warning"] {{ background: {c('warning_soft')}; color: {c('warning')}; }}
QLabel[badge="danger"] {{ background: {c('danger_soft')}; color: {c('danger')}; }}
QLabel[badge="muted"] {{ background: {c('surface_3')}; color: {c('text_muted')}; }}
QLabel[badge="outline"] {{
    background: transparent; color: {c('text_muted')}; border: 1px solid {c('border_strong')};
}}

/* --------------------------------------------------------------- surfaces */
QFrame[panel="sidebar"] {{
    background-color: {c('sidebar')};
    border-{side_a}: 1px solid {c('border')};
}}
QFrame[panel="header"] {{
    background-color: {c('bg')};
    border-bottom: 1px solid {c('border')};
}}
QFrame[panel="inspector"] {{
    background-color: {c('bg_soft')};
    border-{side_b}: 1px solid {c('border')};
}}
QFrame[panel="card"] {{
    background-color: {c('surface')};
    border: 1px solid {c('border')};
    border-radius: {round(14 * scale)}px;
}}
QFrame[panel="card-emphasis"] {{
    background-color: {c('surface_2')};
    border: 1px solid {c('accent_soft')};
}}
QFrame[panel="composer"] {{
    background-color: {c('composer')};
    border: 1px solid {c('border_strong')};
    border-radius: {round(18 * scale)}px;
}}
QFrame[panel="composer"][focused="true"] {{
    border: 1px solid {c('accent')};
    background-color: {c('surface')};
}}
QFrame[panel="chip"] {{
    background-color: {c('surface_3')};
    border: 1px solid {c('border')};
    border-radius: {round(9 * scale)}px;
}}
QFrame[panel="divider"] {{ background-color: {c('border')}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[panel="vdivider"] {{ background-color: {c('border')}; max-width: 1px; min-width: 1px; border: none; }}
QFrame[panel="toast"] {{
    background-color: {c('surface_2')};
    border: 1px solid {c('border_strong')};
    border-radius: {round(12 * scale)}px;
}}

/* ---------------------------------------------------------------- buttons */
QPushButton {{
    background-color: transparent;
    color: {c('text')};
    border: 1px solid {c('border')};
    border-radius: {round(9 * scale)}px;
    padding: {round(7 * scale)}px {round(13 * scale)}px;
    font-weight: 500;
}}
QPushButton:hover {{ background-color: {c('surface_2')}; border-color: {c('border_strong')}; }}
QPushButton:pressed {{ background-color: {c('surface_3')}; }}
QPushButton:focus {{ border: 1px solid {c('ring')}; }}
QPushButton:disabled {{ color: {c('text_faint')}; border-color: {c('border')}; background-color: transparent; }}

QPushButton[variant="primary"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c('accent_hover')}, stop:1 {c('accent')});
    color: {c('accent_contrast')};
    border: 1px solid {c('accent_hover')};
    font-weight: 600;
    padding: {round(9 * scale)}px {round(16 * scale)}px;
}}
QPushButton[variant="primary"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {c('accent')}, stop:1 {c('accent_hover')});
    border-color: {c('accent_hover')};
}}
QPushButton[variant="primary"]:pressed {{ background-color: {c('accent_pressed')}; }}
QPushButton[variant="primary"]:focus {{ border: 1px solid {c('ring')}; }}
QPushButton[variant="primary"]:disabled {{
    background-color: {c('surface_3')}; color: {c('text_faint')}; border-color: {c('border')};
}}

QPushButton[variant="secondary"] {{ background-color: {c('surface_2')}; border: 1px solid {c('border_strong')}; }}
QPushButton[variant="secondary"]:hover {{ background-color: {c('surface_3')}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {c('text_muted')}; }}
QPushButton[variant="ghost"]:hover {{ background: {c('surface_2')}; color: {c('text')}; }}
QPushButton[variant="danger"] {{ background: {c('danger_soft')}; color: {c('danger')}; border: 1px solid {c('danger')}; }}
QPushButton[variant="danger"]:hover {{ background: {c('danger')}; color: {c('accent_contrast')}; }}
QPushButton[variant="link"] {{ border: none; background: transparent; color: {c('accent')}; padding: 2px 4px; }}
QPushButton[variant="link"]:hover {{ color: {c('accent_hover')}; background: transparent; }}
QPushButton[buttonsize="sm"] {{ padding: {round(4 * scale)}px {round(9 * scale)}px; font-size: {fs(12)}px; }}
QPushButton[buttonsize="lg"] {{ padding: {round(11 * scale)}px {round(20 * scale)}px; font-size: {fs(14)}px; }}

QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: {round(9 * scale)}px; padding: {round(5 * scale)}px;
}}
QToolButton:hover {{ background-color: {c('surface_2')}; }}
QToolButton:pressed {{ background-color: {c('surface_3')}; }}
QToolButton:focus {{ border: 1px solid {c('ring')}; }}
QToolButton:disabled {{ color: {c('text_faint')}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}

/* ----------------------------------------------------------------- inputs */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {c('surface_2')};
    color: {c('text')};
    border: 1px solid {c('border')};
    border-radius: {round(9 * scale)}px;
    padding: {round(7 * scale)}px {round(10 * scale)}px;
    selection-background-color: {c('accent')};
    selection-color: {c('accent_contrast')};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {c('border_strong')}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {c('accent')}; background-color: {c('surface')};
}}
QLineEdit:disabled, QTextEdit:disabled {{ color: {c('text_faint')}; background-color: {c('surface')}; }}
QLineEdit#SearchInput {{ background: transparent; border: none; padding: 0px; font-size: {fs(12)}px; }}
QTextEdit#ComposerInput {{
    background: transparent; border: none; padding: 2px;
    selection-background-color: {c('accent')}; selection-color: {c('accent_contrast')};
}}
QTextEdit#ComposerInput:focus {{ border: none; background: transparent; }}
QLineEdit#InlineRename {{ background: {c('surface_2')}; border: 1px solid {c('accent')}; padding: 4px 8px; }}

/* ------------------------------------------------------------------ menus */
QMenu {{
    background-color: {c('surface')};
    border: 1px solid {c('border_strong')};
    border-radius: {round(11 * scale)}px;
    padding: {round(6 * scale)}px;
}}
QMenu::item {{
    background: transparent;
    color: {c('text')};
    padding: {round(7 * scale)}px {round(12 * scale)}px;
    border-radius: {round(7 * scale)}px;
    font-size: {fs(12)}px;
}}
QMenu::item:selected {{ background-color: {c('accent_soft')}; }}
QMenu::item:disabled {{ color: {c('text_faint')}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {c('border')}; margin: {round(5 * scale)}px {round(8 * scale)}px; }}
QMenu::icon {{ padding-left: {round(6 * scale)}px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 8px; }}

QToolTip {{
    background-color: {c('surface_3')};
    color: {c('text')};
    border: 1px solid {c('border_strong')};
    border-radius: {round(8 * scale)}px;
    padding: {round(5 * scale)}px {round(8 * scale)}px;
    font-size: {fs(11)}px;
}}

/* -------------------------------------------------------------- scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 2px 2px 0px; }}
QScrollBar::handle:vertical {{
    background: {c('scrollbar')}; min-height: 32px; border-radius: 4px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {c('scrollbar_hover')}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px 2px 2px 2px; }}
QScrollBar::handle:horizontal {{
    background: {c('scrollbar')}; min-width: 32px; border-radius: 4px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c('scrollbar_hover')}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ------------------------------------------------------------------ sliders */
QSlider {{ min-height: 26px; background: transparent; }}
QSlider::groove:horizontal {{
    height: 8px; border-radius: 4px; background: {c('surface_3')};
    border: 1px solid {c('border')};
}}
/* The hue axis is a real rainbow, so the track shows one. */
QSlider#HueSlider::groove:horizontal {{
    height: 8px; border-radius: 4px; border: 1px solid {c('border')};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff4d4d, stop:0.17 #ffd24d, stop:0.33 #7bff4d, stop:0.5 #4dffd2,
        stop:0.66 #4d9dff, stop:0.83 #b44dff, stop:1 #ff4d9d);
}}
QSlider#HueSlider::sub-page:horizontal {{ background: transparent; }}
QSlider#HueSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    background: {c('surface')}; border: 2px solid {c('text')};
}}
QSlider::sub-page:horizontal {{
    height: 8px; border-radius: 4px; background: {c('accent_soft')};
}}
QSlider::add-page:horizontal {{
    height: 8px; border-radius: 4px; background: transparent;
}}
QSlider::handle:horizontal {{
    width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
    background: {c('accent')}; border: 2px solid {c('bg')};
}}
QSlider::handle:horizontal:hover {{ background: {c('accent_hover')}; }}
QSlider::handle:horizontal:disabled {{ background: {c('border_strong')}; }}
QSlider::groove:vertical {{ width: 6px; border-radius: 3px; background: {c('surface_3')}; }}
QSlider::handle:vertical {{
    height: 14px; margin: 0 -5px; border-radius: 7px;
    background: {c('accent')}; border: 2px solid {c('surface')};
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}

/* ----------------------------------------------------------------- progress */
QProgressBar {{
    background-color: {c('surface_3')};
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 3px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c('accent')}, stop:1 {c('violet')});
}}

/* ------------------------------------------------------------------ misc */
QCheckBox, QRadioButton {{ color: {c('text')}; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QComboBox {{
    background-color: {c('surface_2')}; border: 1px solid {c('border')};
    border-radius: {round(9 * scale)}px; padding: {round(6 * scale)}px {round(9 * scale)}px;
}}
QComboBox:hover {{ border-color: {c('border_strong')}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c('surface')}; border: 1px solid {c('border_strong')};
    selection-background-color: {c('accent_soft')}; color: {c('text')};
    outline: none; padding: 4px;
}}
QHeaderView::section {{ background: {c('surface_2')}; color: {c('text_muted')}; border: none; padding: 6px; }}
QTableView, QTreeView, QListView {{
    background: transparent; border: none;
    selection-background-color: {c('accent_soft')};
    selection-color: {c('text')};
}}
QSplitter::handle {{ background: transparent; width: 1px; }}
QTextBrowser {{ background: transparent; border: none; }}

/* ------------------------------------------------------------ composites */
QFrame#SearchBox {{
    background-color: {c('surface_2')};
    border: 1px solid {c('border')};
    border-radius: {round(10 * scale)}px;
}}
QFrame#SearchBox[focused="true"] {{ border: 1px solid {c('accent')}; background-color: {c('surface')}; }}
QFrame#SearchBox:hover {{ border-color: {c('border_strong')}; }}

QFrame#AttachmentChip {{
    background-color: {c('surface_2')};
    border: 1px solid {c('border')};
    border-radius: {round(8 * scale)}px;
}}

QFrame#SettingRow {{
    background-color: {c('surface_2')};
    border: 1px solid {c('border')};
    border-radius: {round(12 * scale)}px;
}}
QFrame#SettingRow:hover {{ border-color: {c('border_strong')}; }}

QFrame#PhaseCard {{
    background-color: {c('surface')};
    border: 1px solid {c('border')};
    border-radius: {round(16 * scale)}px;
}}

QSlider::groove:horizontal {{
    height: 4px; background: {c('surface_3')}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c('accent')}, stop:1 {c('violet')});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0;
    background: {c('surface')}; border: 2px solid {c('accent')}; border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-color: {c('accent_hover')}; }}
QSlider::handle:horizontal:focus {{ border-color: {c('ring')}; }}

QProgressBar[thin="true"] {{ max-height: 4px; min-height: 4px; border-radius: 2px; }}
QToolBar {{ background: transparent; border: none; }}
QStatusBar {{ background: transparent; }}
"""

