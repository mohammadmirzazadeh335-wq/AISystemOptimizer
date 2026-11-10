"""Digit and text normalisation helpers for Persian input/output.

Persian/Arabic-Indic digits, Arabic yeh/kaf variants and the Arabic thousands
separator are all normalised so that user input is understood regardless of the
keyboard layout, while storage always uses ASCII digits.
"""

from __future__ import annotations

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
LATIN_DIGITS = "0123456789"

_PERSIAN_TO_LATIN = {ord(p): l for p, l in zip(PERSIAN_DIGITS, LATIN_DIGITS)}
_PERSIAN_TO_LATIN.update({ord(a): l for a, l in zip(ARABIC_DIGITS, LATIN_DIGITS)})
_LATIN_TO_PERSIAN = {ord(l): p for p, l in zip(PERSIAN_DIGITS, LATIN_DIGITS)}

# Characters that must never reach the database in half-broken form.
_TEXT_REPLACEMENTS = {
    "\u064a": "\u06cc",  # ARABIC YEH -> FARSI YEH
    "\u0643": "\u06a9",  # ARABIC KAF -> KEHEH
    "\u0629": "\u0647",  # TEH MARBUTA -> HEH (common in typed Persian)
    "\u0640": "",        # TATWEEL (kashida) is decorative only
}


def to_latin_digits(text: str) -> str:
    """Convert Persian/Arabic-Indic digits to ASCII digits."""
    if not text:
        return text or ""
    return str(text).translate(_PERSIAN_TO_LATIN)


def to_persian_digits(text: str) -> str:
    """Convert ASCII digits to Persian digits."""
    if not text:
        return text or ""
    return str(text).translate(_LATIN_TO_PERSIAN)


def normalize_text(text: str | None) -> str:
    """Trim, collapse whitespace and repair common Persian typing artefacts."""
    if text is None:
        return ""
    value = str(text).strip()
    for src, dst in _TEXT_REPLACEMENTS.items():
        value = value.replace(src, dst)
    value = " ".join(value.split())
    return value


def normalize_username(text: str | None) -> str:
    """Usernames are stored lower-case, with digits normalised to ASCII."""
    return normalize_text(to_latin_digits(text or "")).lower()
