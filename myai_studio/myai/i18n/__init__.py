"""Internationalisation helpers."""

from .translator import (
    LANGUAGE_NAMES,
    Translator,
    current_language,
    has_key,
    is_rtl,
    set_language,
    tr,
)


def tn(key: str, count: int, /, **kwargs) -> str:  # noqa: ANN003
    """Plural-aware lookup: ``key.one`` for one item, ``key.many`` otherwise.

    Falls back to the plain key so missing plural forms never crash a label.
    """
    suffix = "one" if count == 1 else "many"
    candidate = f"{key}.{suffix}"
    if has_key(candidate):
        return tr(candidate, count=count, **kwargs)
    return tr(key, count=count, **kwargs)


__all__ = [
    "LANGUAGE_NAMES",
    "Translator",
    "current_language",
    "has_key",
    "is_rtl",
    "set_language",
    "tn",
    "tr",
]
