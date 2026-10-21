"""Design tokens — the single source of truth for colour, type and spacing.

No widget may hard-code a colour.  Palettes are pure data (no Qt imports) so
they can be unit-tested and reused by the stylesheet generator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# --------------------------------------------------------------------------- accents
# Each accent carries values tuned separately for dark and light surfaces.
ACCENTS: dict[str, dict[str, str]] = {
    "azure": {
        "name_key": "settings.accent",
        "dark": "#4C8DFF",
        "dark_hover": "#6BA1FF",
        "dark_pressed": "#3B79E6",
        "light": "#2563EB",
        "light_hover": "#1D4ED8",
        "light_pressed": "#1E40AF",
        "glow": "#4C8DFF",
    },
    "violet": {
        "name_key": "settings.accent",
        "dark": "#8B6CF6",
        "dark_hover": "#A088FF",
        "dark_pressed": "#7457E0",
        "light": "#6D4AE0",
        "light_hover": "#5B38CB",
        "light_pressed": "#4C2EB0",
        "glow": "#8B6CF6",
    },
    "teal": {
        "name_key": "settings.accent",
        "dark": "#2DD4BF",
        "dark_hover": "#5EEAD4",
        "dark_pressed": "#14B8A6",
        "light": "#0F9488",
        "light_hover": "#0D7C73",
        "light_pressed": "#0A655E",
        "glow": "#2DD4BF",
    },
    "amber": {
        "name_key": "settings.accent",
        "dark": "#F2B24C",
        "dark_hover": "#FFC66B",
        "dark_pressed": "#D99A32",
        "light": "#B45309",
        "light_hover": "#92400E",
        "light_pressed": "#78350F",
        "glow": "#F2B24C",
    },
    "rose": {
        "name_key": "settings.accent",
        "dark": "#F471A0",
        "dark_hover": "#FF8DB4",
        "dark_pressed": "#DB5B89",
        "light": "#D6336C",
        "light_hover": "#B92A5D",
        "light_pressed": "#9B2350",
        "glow": "#F471A0",
    },
}

THEMES: dict[str, str] = {
    "midnight": "settings.theme_dark",
    "dawn": "settings.theme_light",
    "aurora": "settings.theme_midnight",
    "system": "settings.theme_system",
}

# --------------------------------------------------------------------------- palettes
_DARK_BASE: dict[str, str] = {
    "bg": "#070B14",
    "bg_soft": "#090E1A",
    "sidebar": "#090D18",
    "header": "#080C15",
    "surface": "#0D1424",
    "surface_2": "#111A2E",
    "surface_3": "#16213A",
    "surface_hover": "#15203A",
    "glass": "#0F182B",
    "border": "#1B2740",
    "border_strong": "#2A3A5C",
    "text": "#E9EFFB",
    "text_muted": "#97A5C1",
    "text_faint": "#65738F",
    "accent_contrast": "#031018",
    "violet": "#9B7BFF",
    "violet_soft": "#1B1835",
    "success": "#3DDB9A",
    "success_soft": "#0D2A22",
    "warning": "#F2B24C",
    "warning_soft": "#2C2210",
    "danger": "#FF7189",
    "danger_soft": "#2E121D",
    "info": "#57C7FF",
    "selection": "#17233D",
    "overlay": "#05080F",
    "shadow": "#000000",
    "ring": "#7FA9FF",
    "composer": "#0F1729",
    "bubble_user": "#132342",
    "code_bg": "#080D18",
    "scrollbar": "#233150",
    "scrollbar_hover": "#33456B",
    "gradient_start": "#12244A",
    "gradient_end": "#0A0F1D",
    "skeleton": "#16213A",
    "skeleton_highlight": "#1F2D4B",
    "divider": "#16203552",
    "nav_active": "#121D33",
    "nav_hover": "#0E1727",
    "ambient_a": "#1B3A78",
    "ambient_b": "#3A2A72",
}

_LIGHT_BASE: dict[str, str] = {
    "bg": "#F2F5FB",
    "bg_soft": "#EDF1F8",
    "sidebar": "#F7F9FD",
    "header": "#F5F8FD",
    "surface": "#FFFFFF",
    "surface_2": "#F3F6FC",
    "surface_3": "#E9EFF9",
    "surface_hover": "#EDF2FA",
    "glass": "#FFFFFF",
    "border": "#DDE5F2",
    "border_strong": "#C4D1E6",
    "text": "#0E182B",
    "text_muted": "#5A6B89",
    "text_faint": "#8B99B3",
    "accent_contrast": "#FFFFFF",
    "violet": "#7457E0",
    "violet_soft": "#EFEBFF",
    "success": "#0F9D6B",
    "success_soft": "#E4F7EF",
    "warning": "#B7791F",
    "warning_soft": "#FDF3E1",
    "danger": "#D93A56",
    "danger_soft": "#FDE9ED",
    "info": "#0D7FC4",
    "selection": "#E4ECFB",
    "overlay": "#0B1224",
    "shadow": "#1B2A4A",
    "ring": "#2563EB",
    "composer": "#FFFFFF",
    "bubble_user": "#E8F0FF",
    "code_bg": "#F6F8FC",
    "scrollbar": "#CBD6E7",
    "scrollbar_hover": "#AFBFD8",
    "gradient_start": "#EAF1FF",
    "gradient_end": "#F7F9FD",
    "skeleton": "#E7EDF7",
    "skeleton_highlight": "#F3F7FD",
    "divider": "#DDE5F255",
    "nav_active": "#E9F0FC",
    "nav_hover": "#EFF4FC",
    "ambient_a": "#CFE0FF",
    "ambient_b": "#E3D9FF",
}

_AURORA_OVERRIDES: dict[str, str] = {
    "bg": "#080714",
    "bg_soft": "#0A0918",
    "sidebar": "#090817",
    "header": "#080713",
    "surface": "#0F0D20",
    "surface_2": "#14112A",
    "surface_3": "#1A1636",
    "surface_hover": "#191534",
    "glass": "#120F26",
    "border": "#241E45",
    "border_strong": "#382F66",
    "text": "#F0EDFF",
    "text_muted": "#A49ACB",
    "text_faint": "#6E6595",
    "selection": "#1E1940",
    "composer": "#120F27",
    "bubble_user": "#1B1640",
    "code_bg": "#080713",
    "scrollbar": "#2C2454",
    "scrollbar_hover": "#443976",
    "gradient_start": "#231A52",
    "gradient_end": "#0A0817",
    "skeleton": "#1B1537",
    "skeleton_highlight": "#251E49",
    "nav_active": "#191333",
    "nav_hover": "#120F26",
    "ambient_a": "#38266E",
    "ambient_b": "#1D3A63",
    "violet": "#B79CFF",
}


# Short names used by widget APIs map onto palette tokens.
_ALIASES = {
    "muted": "text_muted",
    "faint": "text_faint",
    "normal": "text",
    "text": "text",
    "danger": "danger",
    "success": "success",
    "warning": "warning",
    "accent": "accent",
    "violet": "violet",
    "info": "info",
}


@dataclass(frozen=True)
class Theme:
    key: str
    mode: str
    accent_key: str
    colors: Mapping[str, str]
    name_key: str = "settings.theme_dark"

    def color(self, token: str, fallback: str = "#FF00FF") -> str:
        value = self.colors.get(token)
        if value is None:
            value = self.colors.get(_ALIASES.get(token, ""))
        if value is None:
            return fallback
        return value

    def alpha(self, token: str, alpha: float) -> str:
        """Return a CSS rgba() string for the token with the given 0..1 alpha."""
        hex_color = self.color(token).lstrip("#")
        if len(hex_color) == 8:
            hex_color = hex_color[:6]
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r}, {g}, {b}, {alpha:.3f})"

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"


@dataclass(frozen=True)
class Metrics:
    radius_xs: int = 6
    radius_sm: int = 9
    radius_md: int = 12
    radius_lg: int = 16
    radius_xl: int = 22
    sidebar_width: int = 288
    sidebar_collapsed: int = 76
    inspector_width: int = 332
    header_height: int = 64
    row_height: int = 30
    base_font: int = 14
    small_font: int = 12
    tiny_font: int = 11
    title_font: int = 20
    display_font: int = 34
    mono_font: int = 13
    animation_fast: int = 140
    animation_normal: int = 220
    animation_slow: int = 320
    easing: str = "OutCubic"


METRICS = Metrics()


def build_theme(name: str, accent: str = "azure", *, system_dark: bool = True) -> Theme:
    accent = accent if accent in ACCENTS else "azure"
    if name == "system":
        name = "midnight" if system_dark else "dawn"
    if name == "dawn":
        colors = dict(_LIGHT_BASE)
        mode = "light"
        accent_data = ACCENTS[accent]
        colors.update(
            {
                "accent": accent_data["light"],
                "accent_hover": accent_data["light_hover"],
                "accent_pressed": accent_data["light_pressed"],
                "accent_soft": _blend(_LIGHT_BASE["surface"], accent_data["light"], 0.12),
                "accent_glow": _blend(_LIGHT_BASE["surface"], accent_data["glow"], 0.22),
            }
        )
        name_key = THEMES["dawn"]
    else:
        colors = dict(_DARK_BASE)
        if name == "aurora":
            colors.update(_AURORA_OVERRIDES)
        mode = "dark"
        accent_data = ACCENTS[accent]
        colors.update(
            {
                "accent": accent_data["dark"],
                "accent_hover": accent_data["dark_hover"],
                "accent_pressed": accent_data["dark_pressed"],
                "accent_soft": _blend(colors["surface"], accent_data["dark"], 0.16),
                "accent_glow": _blend(colors["surface"], accent_data["glow"], 0.32),
            }
        )
        name_key = THEMES.get(name, THEMES["midnight"])
    return Theme(
        key=name if name != "system" else ("midnight" if system_dark else "dawn"),
        mode=mode,
        accent_key=accent,
        colors=colors,
        name_key=name_key,
    )


def _blend(base: str, overlay: str, ratio: float) -> str:
    def parse(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    br, bg, bb = parse(base)
    orr, og, ob = parse(overlay)
    r = round(br + (orr - br) * ratio)
    g = round(bg + (og - bg) * ratio)
    b = round(bb + (ob - bb) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"
