"""Ambient theme access for custom-painted widgets.

The manager is registered once at startup.  Small widgets read colours and
fonts through these helpers instead of receiving the whole theme graph.
Widgets can connect to ``signals.changed`` to refresh painted state.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont

from .icons import IconCache
from .tokens import Theme, build_theme

_DEFAULT_THEME = build_theme("midnight", "azure")
_DEFAULT_ICONS = IconCache()
_manager = None


class _ThemeSignals(QObject):
    changed = Signal(object)


signals = _ThemeSignals()


def set_manager(manager) -> None:  # noqa: ANN001
    global _manager
    _manager = manager


def manager():
    return _manager


def theme() -> Theme:
    return _manager.theme if _manager is not None else _DEFAULT_THEME


def icons() -> IconCache:
    return _manager.icons if _manager is not None else _DEFAULT_ICONS


def scale() -> float:
    return _manager.scale if _manager is not None else 1.0


def ui_font(pixel_size: int = 13, weight: int = 400) -> QFont:
    family = _manager.font_family if _manager is not None else "DejaVu Sans"
    font = QFont(family)
    font.setPixelSize(max(8, round(pixel_size * scale())))
    font.setWeight(QFont.Weight(weight))
    return font


def mono_font(pixel_size: int = 12, weight: int = 400) -> QFont:
    family = _manager.mono_family if _manager is not None else "DejaVu Sans Mono"
    font = QFont(family)
    font.setPixelSize(max(8, round(pixel_size * scale())))
    font.setWeight(QFont.Weight(weight))
    return font


def px(value: float) -> int:
    return max(1, round(value * scale()))
