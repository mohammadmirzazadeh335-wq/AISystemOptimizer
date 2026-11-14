"""Application theming: light/dark palettes, Persian font, true RTL layout.

The stylesheet is a plain string with ``@token`` placeholders. Keeping it a
template (instead of an f-string) means Qt's own ``{ }`` blocks stay untouched
and a palette change is a pure token substitution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LIGHT = {
    "bg": "#eef1f7",
    "surface": "#ffffff",
    "surface_alt": "#f7f9fc",
    "surface_hover": "#eff4fb",
    "border": "#d9e0ea",
    "border_strong": "#c3ccd9",
    "text": "#101828",
    "text_soft": "#344054",
    "muted": "#667085",
    "primary": "#2563eb",
    "primary_hover": "#1d4ed8",
    "primary_pressed": "#1e40af",
    "primary_soft": "#e6efff",
    "primary_text": "#ffffff",
    "sidebar": "#0f172a",
    "sidebar_text": "#c9d4e5",
    "sidebar_muted": "#7d8ba1",
    "sidebar_hover": "#1b2740",
    "sidebar_active": "#2563eb",
    "success": "#067647",
    "success_soft": "#e7f6ee",
    "warning": "#b54708",
    "warning_soft": "#fdf3e7",
    "danger": "#b42318",
    "danger_soft": "#fdeceb",
    "info": "#175cd3",
    "header": "#ffffff",
    "selection": "#dbe7ff",
    "row_alt": "#fafbfe",
    "shadow": "rgba(16, 24, 40, 0.08)",
    "chart": "#2563eb",
    "chart_alt": "#93b4f7",
}

DARK = {
    "bg": "#0b1220",
    "surface": "#131c2e",
    "surface_alt": "#182338",
    "surface_hover": "#1d2942",
    "border": "#26334d",
    "border_strong": "#33415c",
    "text": "#e8edf7",
    "text_soft": "#c7d2e4",
    "muted": "#93a1b8",
    "primary": "#4f8cf7",
    "primary_hover": "#6ba0f8",
    "primary_pressed": "#3a76e0",
    "primary_soft": "#1c2c4a",
    "primary_text": "#04101f",
    "sidebar": "#080e19",
    "sidebar_text": "#c2cee1",
    "sidebar_muted": "#7b89a1",
    "sidebar_hover": "#16213a",
    "sidebar_active": "#4f8cf7",
    "success": "#4ade80",
    "success_soft": "#12301f",
    "warning": "#fbbf24",
    "warning_soft": "#33270c",
    "danger": "#f87171",
    "danger_soft": "#3a1516",
    "info": "#7dd3fc",
    "header": "#131c2e",
    "selection": "#1e3358",
    "row_alt": "#162034",
    "shadow": "rgba(0, 0, 0, 0.45)",
    "chart": "#4f8cf7",
    "chart_alt": "#2a4a80",
}

PALETTES = {"light": LIGHT, "dark": DARK}


def palette_for(theme: str) -> dict[str, str]:
    return PALETTES.get((theme or "light").lower(), LIGHT)


QSS_TEMPLATE = """
* {
    font-family: @font_family;
    font-size: @font_sizept;
    outline: none;
}
QWidget {
    background-color: @bg;
    color: @text;
}
QMainWindow, QDialog {
    background-color: @bg;
}
QToolTip {
    background-color: @text;
    color: @surface;
    border: none;
    padding: 6px 10px;
    border-radius: 6px;
}
QLabel {
    background: transparent;
    color: @text;
}
QLabel[muted="true"] { color: @muted; }
QLabel#PageTitle { font-size: @titlept; font-weight: 700; color: @text; }
QLabel#PageSubtitle { color: @muted; }
QLabel#SectionTitle { font-size: @sectionpt; font-weight: 700; color: @text; }
QLabel#CardTitle { color: @muted; font-weight: 600; }
QLabel#KpiValue { font-size: @kpipt; font-weight: 700; color: @text; }
QLabel#KpiHint { color: @muted; }
QLabel#FieldLabel { color: @text_soft; font-weight: 600; }
QLabel#ErrorText { color: @danger; }
QLabel#HintText { color: @muted; font-size: @smallpt; }
QLabel#BrandTitle { color: #ffffff; font-size: @brandpt; font-weight: 700; }
QLabel#BrandSubtitle { color: @sidebar_muted; }

QFrame#Card, QWidget#Card {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 12px;
}
QFrame#CardFlat {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 10px;
}
QFrame#Divider { background-color: @border; border: none; max-height: 1px; }
QFrame#Sidebar {
    background-color: @sidebar;
    border: none;
}
QFrame#TopBar {
    background-color: @header;
    border: none;
    border-bottom: 1px solid @border;
}
QFrame#LoginCard {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 16px;
}
QFrame#LoginSide {
    background-color: @sidebar;
    border-top-left-radius: 16px;
    border-bottom-left-radius: 16px;
}

QPushButton {
    background-color: @surface;
    color: @text_soft;
    border: 1px solid @border_strong;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover { background-color: @surface_hover; }
QPushButton:pressed { background-color: @primary_soft; }
QPushButton:disabled { color: @muted; background-color: @surface_alt; border-color: @border; }
QPushButton[variant="primary"] {
    background-color: @primary;
    color: @primary_text;
    border: 1px solid @primary;
}
QPushButton[variant="primary"]:hover { background-color: @primary_hover; border-color: @primary_hover; }
QPushButton[variant="primary"]:pressed { background-color: @primary_pressed; }
QPushButton[variant="primary"]:disabled { background-color: @border; border-color: @border; color: @muted; }
QPushButton[variant="danger"] {
    background-color: transparent;
    color: @danger;
    border: 1px solid @danger;
}
QPushButton[variant="danger"]:hover { background-color: @danger_soft; }
QPushButton[variant="ghost"] {
    background-color: transparent;
    border: 1px solid transparent;
    color: @text_soft;
    padding: 5px 8px;
}
QPushButton[variant="ghost"]:hover { background-color: @surface_hover; }
QPushButton[variant="link"] {
    background: transparent;
    border: none;
    color: @primary;
    padding: 2px 4px;
    font-weight: 600;
}
QPushButton[variant="link"]:hover { color: @primary_hover; text-decoration: underline; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QDateEdit {
    background-color: @surface;
    color: @text;
    border: 1px solid @border_strong;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: @primary;
    selection-color: @primary_text;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus {
    border: 1px solid @primary;
    background-color: @surface;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
    background-color: @surface_alt;
    color: @muted;
}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border: 1px solid @danger; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center left;
    width: 22px;
    border: none;
}
QComboBox::down-arrow {
    image: url("@icons/chevron-down.svg");
    width: 10px;
    height: 10px;
}
QSpinBox::up-button, QDateEdit::up-button {
    subcontrol-origin: border;
    subcontrol-position: top left;
    width: 18px;
    border: none;
    background: transparent;
    margin: 2px 4px 0 0;
}
QSpinBox::down-button, QDateEdit::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom left;
    width: 18px;
    border: none;
    background: transparent;
    margin: 0 4px 2px 0;
}
QSpinBox::up-arrow, QDateEdit::up-arrow {
    image: url("@icons/chevron-up.svg");
    width: 8px;
    height: 8px;
}
QSpinBox::down-arrow, QDateEdit::down-arrow {
    image: url("@icons/chevron-down.svg");
    width: 8px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background-color: @surface;
    border: 1px solid @border;
    selection-background-color: @selection;
    selection-color: @text;
    outline: none;
}
QCheckBox, QRadioButton { background: transparent; color: @text_soft; spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked {
    border: 1px solid @border_strong;
    background: @surface;
    border-radius: 4px;
}
QCheckBox::indicator:checked {
    border: 1px solid @primary;
    background: @primary;
    border-radius: 4px;
    image: url("@icons/check.svg");
}
QRadioButton::indicator:unchecked {
    border: 1px solid @border_strong;
    background: @surface;
    border-radius: 8px;
}
QRadioButton::indicator:checked {
    border: 1px solid @primary;
    background: @primary;
    border-radius: 8px;
    image: url("@icons/dot.svg");
}
QCheckBox:disabled { color: @muted; }

QTableView {
    background-color: @surface;
    alternate-background-color: @row_alt;
    border: 1px solid @border;
    border-radius: 10px;
    gridline-color: @border;
    selection-background-color: @selection;
    selection-color: @text;
}
QTableView::item { padding: 6px 8px; border: none; }
QTableView::item:selected { background-color: @selection; color: @text; }
QHeaderView::section {
    background-color: @surface_alt;
    color: @muted;
    border: none;
    border-bottom: 1px solid @border;
    padding: 8px;
    font-weight: 700;
}
QTableCornerButton::section { background-color: @surface_alt; border: none; }

QListWidget#NavList {
    background-color: @sidebar;
    border: none;
    outline: none;
}
QListWidget#NavList::item {
    color: @sidebar_text;
    padding: 9px 14px;
    border-radius: 8px;
    margin: 2px 8px;
}
QListWidget#NavList::item:hover { background-color: @sidebar_hover; }
QListWidget#NavList::item:selected {
    background-color: @sidebar_active;
    color: #ffffff;
    font-weight: 700;
}
QListWidget#NavList::item:disabled { color: @sidebar_muted; }
QListWidget#NavList QScrollBar:vertical { background: transparent; width: 6px; margin: 0; }
QListWidget#NavList QScrollBar::handle:vertical {
    background: @sidebar_hover;
    border-radius: 3px;
    min-height: 24px;
}
QListWidget#NavList QScrollBar::handle:vertical:hover { background: @sidebar_muted; }

QListWidget {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 10px;
    outline: none;
}
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:selected { background-color: @selection; color: @text; }

QTabWidget::pane {
    border: 1px solid @border;
    border-radius: 10px;
    background-color: @surface;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: @muted;
    padding: 8px 16px;
    margin-left: 2px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}
QTabBar::tab:selected { color: @primary; border-bottom: 2px solid @primary; }
QTabBar::tab:hover { color: @text; }

QGroupBox {
    background-color: transparent;
    border: 1px solid @border;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 700;
    color: @text_soft;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }

QMenuBar { background-color: @header; color: @text_soft; border-bottom: 1px solid @border; }
QMenuBar::item { padding: 6px 12px; background: transparent; }
QMenuBar::item:selected { background-color: @primary_soft; color: @text; border-radius: 6px; }
QMenu {
    background-color: @surface;
    border: 1px solid @border;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item { padding: 7px 18px; border-radius: 6px; color: @text_soft; }
QMenu::item:selected { background-color: @primary_soft; color: @text; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 8px; }

QToolBar {
    background-color: @header;
    border: none;
    border-bottom: 1px solid @border;
    spacing: 6px;
    padding: 6px;
}
QStatusBar {
    background-color: @header;
    border-top: 1px solid @border;
    color: @muted;
}
QStatusBar::item { border: none; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @border_strong;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: @muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @border_strong;
    border-radius: 5px;
    min-width: 30px;
}

QProgressBar {
    background-color: @surface_alt;
    border: 1px solid @border;
    border-radius: 6px;
    text-align: center;
    color: @text_soft;
    height: 8px;
}
QProgressBar::chunk { background-color: @primary; border-radius: 6px; }

QFrame#LockOverlay { background-color: @bg; border: none; }
QMessageBox { background-color: @surface; }
QMessageBox QLabel { color: @text; }
"""


@dataclass(frozen=True)
class Typography:
    base: int = 11
    small: int = 9
    title: int = 17
    section: int = 13
    kpi: int = 22
    brand: int = 20

    @classmethod
    def from_base(cls, base: int) -> "Typography":
        base = max(9, min(int(base or 11), 18))
        return cls(base=base, small=max(8, base - 2), title=base + 6, section=base + 2,
                   kpi=base + 11, brand=base + 9)


ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def icons_dir(theme: str) -> Path:
    folder = "dark" if (theme or "light").lower() == "dark" else "light"
    return ICONS_DIR / folder


def build_stylesheet(theme: str = "light", *, font_family: str = "Vazirmatn",
                     font_size: int = 11) -> str:
    palette = palette_for(theme)
    typography = Typography.from_base(font_size)
    css = QSS_TEMPLATE
    # longest token first so "@surface_hover" is not eaten by "@surface"
    for token in sorted(palette, key=len, reverse=True):
        css = css.replace(f"@{token}", palette[token])
    # forward slashes are required by Qt stylesheets on Windows too
    icon_path = str(icons_dir(theme)).replace("\\", "/")
    css = css.replace("@icons", icon_path)
    replacements = {
        "@font_family": f'"{font_family}"',
        "@font_sizept": f"{typography.base}pt",
        "@smallpt": f"{typography.small}pt",
        "@titlept": f"{typography.title}pt",
        "@sectionpt": f"{typography.section}pt",
        "@kpipt": f"{typography.kpi}pt",
        "@brandpt": f"{typography.brand}pt",
    }
    for token, value in replacements.items():
        css = css.replace(token, value)
    return css


def apply_theme(app, snapshot) -> None:
    """Apply direction, font, locale and stylesheet to the whole application."""
    from PySide6.QtCore import QLocale, Qt
    from PySide6.QtGui import QFont

    from pars_erp.ui.fonts import load_bundled_fonts, resolve_family

    load_bundled_fonts()
    family = resolve_family(snapshot.font_family)
    size = max(9, min(int(snapshot.font_size), 18))

    QLocale.setDefault(QLocale(QLocale.Language.Persian, QLocale.Country.Iran))
    app.setLayoutDirection(Qt.RightToLeft)
    font = QFont(family, size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(snapshot.theme, font_family=family, font_size=size))
