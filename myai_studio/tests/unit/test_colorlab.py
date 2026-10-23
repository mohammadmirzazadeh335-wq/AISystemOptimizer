"""Colour lab: the numbers the atelier shows must be the WCAG numbers."""

from __future__ import annotations

import pytest

from myai.ui.theme import colorlab
from myai.ui.theme.tokens import ACCENTS, build_theme


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#ffffff", (255, 255, 255)),
        ("#000", (0, 0, 0)),
        ("12ab88", (18, 171, 136)),
        ("#12AB88FF", (18, 171, 136)),
        ("#abcd", (170, 187, 204)),
    ],
)
def test_hex_variants_parse(value: str, expected: tuple[int, int, int]) -> None:
    assert colorlab.parse_hex(value) == expected


@pytest.mark.parametrize("value", ["", "#12", "#12345", "red", "#gggggg", None])
def test_invalid_hex_is_rejected(value) -> None:  # noqa: ANN001
    assert colorlab.parse_hex(value) is None
    assert colorlab.normalize(value if isinstance(value, str) else "") == ""


def test_round_trip_normalises_case() -> None:
    assert colorlab.to_hex((18, 171, 136)) == "#12ab88"
    assert colorlab.normalize("#12AB88") == "#12ab88"


# ---------------------------------------------------------------- contrast
def test_known_contrast_ratios() -> None:
    assert colorlab.contrast_ratio("#000000", "#ffffff") == 21.0
    assert colorlab.contrast_ratio("#ffffff", "#ffffff") == 1.0
    # #767676 on white is the classic 4.5 boundary.
    assert colorlab.contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.02)
    # Order must not matter.
    assert colorlab.contrast_ratio("#ffffff", "#0b1020") == colorlab.contrast_ratio("#0b1020", "#ffffff")


def test_wcag_levels() -> None:
    assert colorlab.wcag_level(21.0) == "AAA"
    assert colorlab.wcag_level(7.0) == "AAA"
    assert colorlab.wcag_level(4.5) == "AA"
    assert colorlab.wcag_level(3.2) == "large-only"
    assert colorlab.wcag_level(3.2, large=True) == "AA-large"
    assert colorlab.wcag_level(2.9) == "fail"
    assert colorlab.passes_aa(4.5) and not colorlab.passes_aa(4.4)
    assert colorlab.passes_aa(3.0, large=True)


# ------------------------------------------------------------------- mixing
def test_mix_endpoints_and_middle() -> None:
    assert colorlab.mix("#000000", "#ffffff", 0.0) == "#000000"
    assert colorlab.mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert colorlab.mix("#000000", "#ffffff", 0.5) == "#808080"
    assert colorlab.lighten("#000000", 0.5) == "#808080"
    assert colorlab.darken("#ffffff", 0.5) == "#808080"


def test_hue_rotation_keeps_saturation() -> None:
    rotated = colorlab.rotate_hue("#ff0000", 120)
    assert rotated == "#00ff00"
    hue, saturation, value = colorlab.hex_to_hsv("#12ab88")
    assert 0 <= hue < 360 and saturation > 0 and value > 0
    assert colorlab.hsv_hex(hue, saturation, value) == "#12ab88"


def test_with_alpha_formats_rgba() -> None:
    assert colorlab.with_alpha("#12ab88", 0.25) == "rgba(18, 171, 136, 0.250)"
    assert colorlab.with_alpha("nope", 0.5).startswith("rgba(0, 0, 0")


# ------------------------------------------------------------------- ramps
def test_dark_ramp_brightens_on_hover() -> None:
    ramp = colorlab.accent_ramp("#12ab88", mode="dark")
    assert ramp["base"] == "#12ab88"
    assert colorlab.relative_luminance(ramp["hover"]) > colorlab.relative_luminance(ramp["base"])
    assert colorlab.relative_luminance(ramp["pressed"]) < colorlab.relative_luminance(ramp["base"])


def test_light_ramp_is_darkened_until_usable_on_white() -> None:
    ramp = colorlab.accent_ramp("#ffe066", mode="light", surface="#ffffff")
    assert colorlab.contrast_ratio(ramp["base"], "#ffffff") >= 3.2
    assert colorlab.relative_luminance(ramp["base"]) < colorlab.relative_luminance("#ffe066")


def test_ensure_contrast_reaches_the_target() -> None:
    fixed = colorlab.ensure_contrast("#dddddd", "#ffffff", 4.5)
    assert colorlab.contrast_ratio(fixed, "#ffffff") >= 4.5
    assert colorlab.ensure_contrast("#000000", "#ffffff", 4.5) == "#000000"


def test_readable_on_picks_the_better_text_colour() -> None:
    assert colorlab.readable_on("#ffffff") == "#0b1020"
    assert colorlab.readable_on("#05080f") == "#ffffff"


def test_invalid_input_never_raises() -> None:
    assert colorlab.accent_ramp("not-a-colour")["base"] == "#4c8dff"
    assert colorlab.rotate_hue("", 30) == "#000000"
    assert colorlab.contrast_ratio("", "#ffffff") == 1.0


# ------------------------------------------------------------- theme wiring
def test_custom_accent_reaches_the_theme() -> None:
    theme = build_theme("midnight", "custom", custom_accent="#12ab88")
    assert theme.color("accent") == "#12ab88"
    assert theme.accent_key == "custom"
    assert theme.color("accent_soft").startswith("#")


def test_custom_accent_is_contrast_corrected_for_light_theme() -> None:
    theme = build_theme("dawn", "custom", custom_accent="#ffe066")
    assert colorlab.contrast_ratio(theme.color("accent"), "#ffffff") >= 3.2


def test_invalid_or_unknown_accent_falls_back_to_azure() -> None:
    theme = build_theme("midnight", "custom", custom_accent="nonsense")
    assert theme.color("accent") == ACCENTS["azure"]["dark"]
    fallback = build_theme("midnight", "does-not-exist")
    assert fallback.color("accent") == ACCENTS["azure"]["dark"]


@pytest.mark.parametrize("name", ["midnight", "dawn", "aurora"])
def test_every_built_in_theme_keeps_body_text_readable(name: str) -> None:
    theme = build_theme(name)
    ratio = colorlab.contrast_ratio(theme.color("text"), theme.color("surface"))
    assert ratio >= 7.0, f"{name} body text contrast is only {ratio}"


def test_custom_accent_keeps_button_text_readable() -> None:
    for colour in ("#12ab88", "#ffe066", "#7b61ff", "#111111"):
        theme = build_theme("midnight", "custom", custom_accent=colour)
        ratio = colorlab.contrast_ratio(theme.color("text"), theme.color("surface"))
        assert ratio >= 4.5
        label = colorlab.readable_on(theme.color("accent"))
        assert colorlab.contrast_ratio(theme.color("accent"), label) >= 4.5
