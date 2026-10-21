from __future__ import annotations

import re

import pytest

from myai.ui.theme.tokens import ACCENTS, METRICS, build_theme


@pytest.mark.parametrize("name", ["midnight", "dawn", "aurora"])
def test_theme_palette_is_complete(name: str) -> None:
    theme = build_theme(name)
    required = [
        "bg", "surface", "surface_2", "surface_3", "border", "text", "text_muted",
        "text_faint", "accent", "accent_hover", "accent_soft", "violet", "success",
        "warning", "danger", "ring", "composer", "code_bg", "scrollbar", "nav_active",
    ]
    for token in required:
        value = theme.color(token)
        assert value != "#FF00FF", f"missing token {token} for {name}"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), f"{token}={value}"


@pytest.mark.parametrize("accent", list(ACCENTS))
def test_each_accent_renders_in_both_modes(accent: str) -> None:
    dark = build_theme("midnight", accent)
    light = build_theme("dawn", accent)
    assert dark.is_dark and not light.is_dark
    assert dark.color("accent") != light.color("accent")
    assert dark.color("accent_contrast") in {"#031018", "#FFFFFF"} or dark.color("accent_contrast").startswith("#")


def test_system_theme_resolves_by_preference() -> None:
    assert build_theme("system", system_dark=True).key == "midnight"
    assert build_theme("system", system_dark=False).key == "dawn"


def test_token_aliases_resolve() -> None:
    theme = build_theme("midnight")
    assert theme.color("muted") == theme.color("text_muted")
    assert theme.color("normal") == theme.color("text")


def test_alpha_helper() -> None:
    theme = build_theme("midnight")
    assert theme.alpha("accent", 0.5).startswith("rgba(")


def test_stylesheet_generation_has_no_missing_tokens() -> None:
    from myai.ui.theme.manager import build_stylesheet

    css = build_stylesheet(build_theme("midnight", "violet"), 1.0, "DejaVu Sans Mono", True)
    assert "#FF00FF" not in css
    assert "border-left" in css  # RTL: the inspector border moves to the right
    assert "QPushButton[variant=\"primary\"]" in css
    assert "font-size" in css
    metrics = METRICS
    assert metrics.radius_md > 0 and metrics.header_height == 64
