from __future__ import annotations

import json
import re
from pathlib import Path

from myai.i18n import Translator, is_rtl, set_language, tr

LOCALES = Path(__file__).resolve().parents[2] / "myai" / "i18n" / "locales"


def _load(code: str) -> dict:
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def test_catalogues_have_identical_keys() -> None:
    en, fa = _load("en"), _load("fa")
    assert set(en) == set(fa), f"missing in fa: {sorted(set(en) - set(fa))}; missing in en: {sorted(set(fa) - set(en))}"


def test_no_empty_translations() -> None:
    for code in ("en", "fa"):
        catalogue = _load(code)
        empty = [key for key, value in catalogue.items() if not str(value).strip()]
        assert not empty, (code, empty)


def test_every_key_used_in_source_exists() -> None:
    catalogue = _load("en")
    used: set[str] = set()
    root = LOCALES.parents[1]
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r'(?<![A-Za-z0-9_])tr\(\s*["\']([a-zA-Z0-9_.{}]+)["\']', text))
        used |= set(re.findall(r'"(settings\.[a-z_]+_subtitle)"', text))
    missing = sorted(k for k in used if "{" not in k and k not in catalogue)
    assert not missing, missing


def test_placeholders_match_between_languages() -> None:
    en, fa = _load("en"), _load("fa")
    pattern = re.compile(r"\{(\w+)\}")
    mismatched = []
    for key in en:
        if set(pattern.findall(en[key])) != set(pattern.findall(fa.get(key, ""))):
            mismatched.append(key)
    assert not mismatched, mismatched


def test_translator_fallback_and_formatting() -> None:
    translator = Translator("fa", LOCALES)
    assert translator.is_rtl
    assert "{n}" not in translator.t("time.minute", n=5)
    assert translator.t("does.not.exist") == "does.not.exist"
    translator.set_language("en")
    assert not translator.is_rtl
    assert translator.t("time.hour", n=3) == "3h ago"


def test_language_switching_updates_direction() -> None:
    set_language("fa")
    assert is_rtl() is True
    assert tr("nav.new_chat") == "گفتگوی جدید"
    set_language("en")
    assert is_rtl() is False
    assert tr("nav.new_chat") == "New chat"


def test_dynamic_key_patterns_resolve() -> None:
    """Keys composed with f-strings are easy to break silently - pin them."""
    catalogue = _load("en")
    generated: list[str] = []
    for index in range(1, 5):
        generated += [
            f"chat.suggestion_{index}_title",
            f"chat.suggestion_{index}_sub",
            f"chat.suggestion_{index}_prompt",
        ]
    # The counts must match ROUTES in myai/ui/views/placeholder.py.
    # "code" is no longer a placeholder: Phase 3 replaced it with the real page.
    for route, count in (("agent", 3), ("images", 3), ("web", 3),
                         ("prompts", 3), ("tasks", 3), ("performance", 3)):
        generated += [f"placeholder.{route}.f{i}" for i in range(1, count + 1)]
    generated += ["chat.trust_local", "chat.trust_secret", "chat.trust_real"]
    missing = [key for key in generated if key not in catalogue]
    assert not missing, missing
    for key in generated:
        assert "{" not in catalogue[key] or key.startswith("chat.suggestion"), key


def test_plural_forms_exist_for_counted_keys() -> None:
    en, fa = _load("en"), _load("fa")
    counted = [
        "api.models_loaded",
        "api.models_loaded_short",
        "inspector.memory_injected",
        "memory.count_global",
        "memory.count_chat",
        "memory.summary_review",
        "memory.summary_committed",
        "studio.revisions",
    ]
    for key in counted:
        for suffix in ("one", "many"):
            assert f"{key}.{suffix}" in en, (key, suffix)
            assert f"{key}.{suffix}" in fa, (key, suffix)
    assert "entry" in en["memory.count_chat.one"]
    assert "entries" in en["memory.count_chat.many"]


def test_phase2_strings_are_translated_not_copied() -> None:
    """A Persian catalogue full of English copy would look unfinished."""
    en, fa = _load("en"), _load("fa")
    suspects = [
        "api.title",
        "api.test_ok",
        "memory.title",
        "memory.summary_hint",
        "persona.title",
        "persona.separation_body",
        "studio.title",
        "studio.history_hint",
        "nav.memory",
        "nav.studio",
        "inspector.connect_model",
    ]
    identical = [key for key in suspects if en[key] == fa[key]]
    assert not identical, identical
    persian = re.compile(r"[\u0600-\u06FF]")
    not_persian = [key for key in suspects if not persian.search(fa[key])]
    assert not not_persian, not_persian
