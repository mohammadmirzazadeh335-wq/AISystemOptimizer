from __future__ import annotations

import json
from pathlib import Path

import pytest

from myai.core.errors import ValidationError
from myai.core.events import SignalBus
from myai.data import Database
from myai.data.repositories import SettingRepository
from myai.security.secrets import SecretStore
from myai.services.settings import DEFAULTS, SettingsService


@pytest.fixture()
def settings(tmp_path: Path):
    db = Database(tmp_path / "s.db").initialize()
    service = SettingsService(SettingRepository(db), SignalBus())
    service.load()
    yield service
    db.close()


def test_defaults_loaded(settings: SettingsService) -> None:
    assert settings.get("ui.language") in {"fa", "en"}
    assert settings.get("ui.theme") == "midnight"
    assert settings.get("ai.temperature") == 0.7


def test_set_persists_and_notifies(settings: SettingsService) -> None:
    events = []
    settings.subscribe(lambda changes: events.append(changes))
    settings.set("ui.theme", "dawn")
    assert settings.get("ui.theme") == "dawn"
    assert events and events[0] == {"ui.theme": "dawn"}
    # reload from the repository
    reloaded = SettingsService(settings._repo, SignalBus())
    reloaded.load()
    assert reloaded.get("ui.theme") == "dawn"


def test_validation_rejects_bad_values(settings: SettingsService) -> None:
    with pytest.raises(ValidationError):
        settings.set("ui.theme", "neon")
    with pytest.raises(ValidationError):
        settings.set("ai.temperature", 9)
    with pytest.raises(ValidationError):
        settings.set("ai.max_tokens", 4)
    with pytest.raises(ValidationError):
        settings.set("ui.font_scale", 3.0)
    with pytest.raises(ValidationError):
        settings.set("ui.sidebar_width", 9999)


def test_base_url_must_be_https(settings: SettingsService) -> None:
    with pytest.raises(ValidationError):
        settings.set("ai.base_url", "http://insecure.example")
    settings.set("ai.base_url", "https://openrouter.ai/api/v1/")
    assert settings.get("ai.base_url") == "https://openrouter.ai/api/v1"


def test_language_change_applies_immediately(settings: SettingsService) -> None:
    from myai.i18n import current_language

    settings.set("ui.language", "en")
    assert current_language() == "en"
    settings.set("ui.language", "fa")
    assert current_language() == "fa"


def test_update_only_emits_changed(settings: SettingsService) -> None:
    changes = settings.update({"ui.theme": "midnight", "ui.accent": "violet"})
    assert changes == {"ui.accent": "violet"}


def test_reset_all(settings: SettingsService) -> None:
    settings.update({"ui.theme": "dawn", "ui.accent": "teal"})
    settings.reset_all()
    assert settings.get("ui.theme") == DEFAULTS["ui.theme"]
    assert settings.get("ui.accent") == "azure"


def test_public_export_has_no_secret_names(settings: SettingsService) -> None:
    export = settings.public_export()
    assert not any(key.startswith(("secret.", "auth.")) for key in export)


# --------------------------------------------------------------------- secrets
def test_secret_roundtrip_and_encryption(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    store.set("openrouter.api_key", "sk-or-v1-abcdef123456")
    assert store.get("openrouter.api_key") == "sk-or-v1-abcdef123456"
    assert store.has("openrouter.api_key")
    raw = (tmp_path / "secrets.bin").read_text(encoding="utf-8")
    assert "sk-or-v1-abcdef123456" not in raw
    envelope = json.loads(raw)
    assert envelope["backend"] in {"dpapi", "fernet"}
    assert len(envelope["data"]) > 20


def test_secret_reload_from_disk(tmp_path: Path) -> None:
    first = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    first.set("token", "value-1")
    second = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    assert second.get("token") == "value-1"
    assert second.names() == ["token"]
    assert second.delete("token") is True
    assert second.get("token") is None
    third = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    assert third.names() == []


def test_secret_rejects_bad_names_and_empty_values(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    with pytest.raises(ValueError):
        store.set("bad name", "x")
    with pytest.raises(ValueError):
        store.set("ok", "")


def test_secret_file_is_owner_only(tmp_path: Path) -> None:
    """The secret file must not be readable by anyone else.

    The mechanism is not the same on both platforms, so the assertion is not
    either: Windows has no POSIX mode bits (``os.stat`` always reports 0o666)
    and protects the file by encrypting it with DPAPI, bound to the user
    account. Asserting 0600 there would say nothing about the real protection.
    """
    import os
    import stat

    token = "super-secret-token-value"
    store = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    store.set("k", token)
    raw = (tmp_path / "secrets.bin").read_bytes()
    assert token.encode("utf-8") not in raw, "the secret was written in plaintext"
    if os.name == "nt":
        assert store.backend == "dpapi"
        return
    mode = stat.S_IMODE(os.stat(tmp_path / "secrets.bin").st_mode)
    assert mode & 0o077 == 0, oct(mode)


def test_phase2_setting_roundtrip(settings: SettingsService) -> None:
    settings.update(
        {
            "ai.tone": "concise",
            "ai.detail": "detailed",
            "ai.language_preference": "en",
            "ai.context_warn_ratio": 0.75,
            "ai.openrouter_cache": [{"id": "x/y", "name": "Y"}],
        }
    )
    assert settings.get("ai.tone") == "concise"
    assert settings.get("ai.detail") == "detailed"
    assert settings.get("ai.language_preference") == "en"
    assert settings.get("ai.context_warn_ratio") == 0.75
    assert settings.get("ai.openrouter_cache")[0]["id"] == "x/y"


def test_phase2_setting_validation(settings: SettingsService) -> None:
    import pytest

    from myai.core.errors import ValidationError

    for key, value in (
        ("ai.tone", "sarcastic"),
        ("ai.detail", "novel"),
        ("ai.language_preference", "klingon"),
        ("ai.context_warn_ratio", 1.5),
    ):
        with pytest.raises(ValidationError):
            settings.set(key, value)
