"""Colour mathematics for the appearance atelier.

Pure functions, no Qt: WCAG contrast, mixing, hue rotation and the accent ramp.
The theme, the appearance page and the tests all call exactly these functions,
so the number shown next to a swatch is the number the renderer relies on.
"""

from __future__ import annotations

import colorsys
import re
from collections.abc import Mapping

HEX_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

RGB = tuple[int, int, int]


def parse_hex(value: str) -> RGB | None:
    """Return ``(r, g, b)`` for ``#rgb``, ``#rrggbb`` or ``#rrggbbaa``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not HEX_RE.match(text):
        return None
    text = text.lstrip("#")
    if len(text) in (3, 4):
        text = "".join(character * 2 for character in text[:3])
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def to_hex(rgb: RGB | tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(channel))) for channel in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def normalize(value: str) -> str:
    """Return a lower-case ``#rrggbb`` string, or ``""`` when invalid."""
    rgb = parse_hex(value)
    return to_hex(rgb) if rgb is not None else ""


def _linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(value: str | RGB) -> float:
    """WCAG 2.1 relative luminance (0 = black, 1 = white)."""
    rgb = parse_hex(value) if isinstance(value, str) else value
    if rgb is None:
        return 0.0
    r, g, b = (_linear(channel) for channel in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio, rounded to two decimals (1.0 … 21.0).

    An unparsable colour reports 1.0 — the weakest possible ratio. Reporting
    black's 21.0 for garbage would let an invalid value pass the audit.
    """
    if parse_hex(first) is None or parse_hex(second) is None:
        return 1.0
    a = relative_luminance(first)
    b = relative_luminance(second)
    darker, lighter = sorted((a, b))
    return round((lighter + 0.05) / (darker + 0.05), 2)


def wcag_level(ratio: float, *, large: bool = False) -> str:
    """``AAA``, ``AA``, ``AA-large`` or ``fail`` for a contrast ratio."""
    if ratio >= 7.0:
        return "AAA"
    if ratio >= 4.5:
        return "AA"
    if ratio >= 3.0:
        return "AA-large" if large else "large-only"
    return "fail"


def passes_aa(ratio: float, *, large: bool = False) -> bool:
    return ratio >= (3.0 if large else 4.5)


def mix(first: str, second: str, amount: float) -> str:
    """Blend ``first`` towards ``second`` by ``amount`` (0…1)."""
    a = parse_hex(first)
    b = parse_hex(second)
    if a is None or b is None:
        return "#000000"
    amount = max(0.0, min(1.0, float(amount)))
    return to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))


def lighten(value: str, amount: float = 0.15) -> str:
    return mix(value, "#ffffff", amount)


def darken(value: str, amount: float = 0.15) -> str:
    return mix(value, "#000000", amount)


def with_alpha(value: str, alpha: float) -> str:
    """``rgba(...)`` string for a hex colour."""
    rgb = parse_hex(value)
    if rgb is None:
        return "rgba(0, 0, 0, 0)"
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {max(0.0, min(1.0, alpha)):.3f})"


def rotate_hue(value: str, degrees: float) -> str:
    rgb = parse_hex(value)
    if rgb is None:
        return "#000000"
    h, s, v = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in rgb))
    h = (h + degrees / 360.0) % 1.0
    return to_hex(tuple(channel * 255.0 for channel in colorsys.hsv_to_rgb(h, s, v)))


def hsv_hex(hue: float, saturation: float, value: float) -> str:
    """Build a colour from 0…360 hue and 0…100 saturation/value."""
    h = (float(hue) % 360.0) / 360.0
    s = max(0.0, min(1.0, float(saturation) / 100.0))
    v = max(0.0, min(1.0, float(value) / 100.0))
    return to_hex(tuple(channel * 255.0 for channel in colorsys.hsv_to_rgb(h, s, v)))


def hex_to_hsv(value: str) -> tuple[float, float, float]:
    rgb = parse_hex(value) or (0, 0, 0)
    h, s, v = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in rgb))
    return round(h * 360.0, 1), round(s * 100.0, 1), round(v * 100.0, 1)


def ensure_contrast(value: str, background: str, minimum: float = 4.5) -> str:
    """Darken/lighten ``value`` until it reaches ``minimum`` on ``background``.

    Used for accents chosen by the user: a pastel colour picked for a light
    theme is nudged towards black until body text built on it is readable.
    """
    current = normalize(value) or "#000000"
    if contrast_ratio(current, background) >= minimum:
        return current
    background_is_light = relative_luminance(background) > 0.5
    toward = "#000000" if background_is_light else "#ffffff"
    for step in range(1, 21):
        candidate = mix(current, toward, step / 20)
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return mix(current, toward, 1.0)


def readable_on(background: str, *, dark: str = "#0b1020", light: str = "#ffffff") -> str:
    """The text colour of the two that is readable on ``background``."""
    return light if contrast_ratio(background, light) >= contrast_ratio(background, dark) else dark


def accent_ramp(base: str, *, mode: str = "dark", surface: str = "#0B1020") -> dict[str, str]:
    """Derive the five accent tokens from one colour.

    Dark themes brighten the base for hover and deepen it for pressed; light
    themes need a darker base before it can be used as text on white, so the
    base is contrast-corrected first and the ramp is built from that.
    """
    seed = normalize(base) or normalize("#4C8DFF")
    if mode == "light":
        base_color = ensure_contrast(seed, surface, 3.2)
        return {
            "base": base_color,
            "hover": darken(base_color, 0.12),
            "pressed": darken(base_color, 0.24),
            "glow": base_color,
        }
    return {
        "base": seed,
        "hover": lighten(seed, 0.18),
        "pressed": darken(seed, 0.16),
        "glow": seed,
    }


def audit_pairs(colors: Mapping[str, str], pairs: list[tuple[str, str, str]]) -> list[dict]:
    """Contrast report for ``(label key, foreground, background)`` triples."""
    report: list[dict] = []
    for label, foreground, background in pairs:
        fg = colors.get(foreground, "#000000")
        bg = colors.get(background, "#ffffff")
        ratio = contrast_ratio(fg, bg)
        report.append(
            {
                "label": label,
                "foreground": fg,
                "background": bg,
                "ratio": ratio,
                "level": wcag_level(ratio),
                "passes": passes_aa(ratio),
            }
        )
    return report


__all__ = [
    "accent_ramp",
    "audit_pairs",
    "contrast_ratio",
    "darken",
    "ensure_contrast",
    "hex_to_hsv",
    "hsv_hex",
    "lighten",
    "mix",
    "normalize",
    "parse_hex",
    "passes_aa",
    "readable_on",
    "relative_luminance",
    "rotate_hue",
    "to_hex",
    "wcag_level",
    "with_alpha",
]
