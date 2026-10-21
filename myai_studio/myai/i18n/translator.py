"""Lightweight runtime translation with Persian (RTL) and English (LTR).

A JSON catalogue per language keeps strings out of widget code.  Missing keys
fall back to English, then to the key itself, so a missing translation can
never crash the UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).with_name("locales")
RTL_LANGUAGES = {"fa", "ar", "he", "ur"}
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}


class Translator:
    def __init__(self, language: str = "fa", locales_dir: Path | None = None) -> None:
        self._dir = locales_dir or LOCALES_DIR
        self._cache: dict[str, dict[str, str]] = {}
        self._language = "en"
        self.set_language(language)

    @property
    def language(self) -> str:
        return self._language

    @property
    def is_rtl(self) -> bool:
        return self._language in RTL_LANGUAGES

    def set_language(self, language: str) -> None:
        if language not in ("fa", "en"):
            language = "en"
        self._language = language
        self._load(language)
        self._load("en")

    def _load(self, language: str) -> None:
        if language in self._cache:
            return
        path = self._dir / f"{language}.json"
        try:
            self._cache[language] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cache[language] = {}

    def t(self, key: str, /, **kwargs: Any) -> str:
        text = self._cache.get(self._language, {}).get(key)
        if text is None:
            text = self._cache.get("en", {}).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def has(self, key: str) -> bool:
        return key in self._cache.get(self._language, {}) or key in self._cache.get("en", {})


_global = Translator()


def set_language(language: str) -> None:
    _global.set_language(language)


def current_language() -> str:
    return _global.language


def is_rtl() -> bool:
    return _global.is_rtl


def tr(key: str, /, **kwargs: Any) -> str:
    return _global.t(key, **kwargs)


def has_key(key: str) -> bool:
    return _global.has(key)
