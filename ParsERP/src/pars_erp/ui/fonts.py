"""Bundled Persian font loading.

Vazirmatn (SIL Open Font License, see resources/fonts/OFL.txt) ships with the
application so Persian text renders identically on every Windows installation,
even where no Persian font is installed. If loading fails we fall back to fonts
that exist on Windows/Linux.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"
BUNDLED_FAMILY = "Vazirmatn"
BUNDLED_FILES = ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf",
                 "Vazirmatn-SemiBold.ttf", "Vazirmatn-Bold.ttf")
FALLBACK_FAMILIES = ("Vazirmatn", "IRANSans", "Segoe UI", "Tahoma", "DejaVu Sans", "Arial")

_loaded = False
_available_families: list[str] = []


def load_bundled_fonts() -> list[str]:
    """Register the bundled fonts with Qt (idempotent). Returns the families."""
    global _loaded, _available_families
    if _loaded:
        return _available_families
    _loaded = True
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:  # pragma: no cover - Qt missing
        logger.warning("Qt not available; bundled fonts were not registered")
        return []
    families: list[str] = []
    for filename in BUNDLED_FILES:
        path = FONT_DIR / filename
        if not path.exists():
            logger.warning("bundled font missing: %s", path)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    _available_families = sorted(set(families))
    logger.info("loaded bundled font families: %s", _available_families)
    return _available_families


def resolve_family(preferred: str | None = None) -> str:
    """Pick the best available family for Persian UI text."""
    try:
        from PySide6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
    except Exception:  # pragma: no cover
        installed = set()
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(FALLBACK_FAMILIES)
    for candidate in candidates:
        if candidate in installed:
            return candidate
    return preferred or BUNDLED_FAMILY


def available_families() -> list[str]:
    try:
        from PySide6.QtGui import QFontDatabase
        return sorted(QFontDatabase.families())
    except Exception:  # pragma: no cover
        return []
