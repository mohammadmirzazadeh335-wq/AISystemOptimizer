"""The API key must be usable and must never leak.

No live OpenRouter call is made here (and none is made anywhere in this
repository's tests). What is proven instead is everything around the key that
can be proven offline:

* the shape check that runs *before* a request, including header injection;
* the encrypted store never holds the key in a readable form on disk;
* the SQLite database and the backup archive never contain it;
* every log handler redacts it, even when a caller logs it by mistake;
* the error shown to the user never echoes it.

That is the "is the key handling sound" question, answered without touching the
network.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

import httpx
import pytest

from myai.core.errors import ConfigurationError
from myai.core.logging import JsonFormatter, RedactFilter
from myai.core.redaction import mask_secret, redact
from myai.security.secrets import SecretStore
from myai.services.backup import BackupService
from myai.services.openrouter import (
    OpenRouterClient,
    api_key_problem,
    validate_api_key,
)

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


# ------------------------------------------------------------------ shape check
def test_a_normal_key_is_accepted() -> None:
    assert api_key_problem(KEY) is None
    assert validate_api_key(f"  {KEY}\n") == KEY


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("", "error.api_key_missing"),
        ("   ", "error.api_key_missing"),
        ("pk-live-123", "api.key_format"),
        ("sk-live-123", "api.key_format"),
        ("sk-or-v1-" + "a" * 300, "api.key_too_long"),
        ("sk-or-v1-abc def", "api.key_invalid_chars"),
        ("sk-or-v1-abc\r\nX-Injected: 1", "api.key_invalid_chars"),
        ("sk-or-v1-abc\ndef", "api.key_invalid_chars"),
        ("sk-or-v1-abc\x00def", "api.key_invalid_chars"),
    ],
)
def test_malformed_keys_are_named_precisely(value: str, key: str) -> None:
    assert api_key_problem(value) == key


def test_header_injection_never_reaches_a_request() -> None:
    """A key with CRLF is rejected before the request is built."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"data": []})

    client = OpenRouterClient(
        lambda: "sk-or-v1-abc\r\nX-Injected: 1",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConfigurationError) as caught:
        client.list_models()
    assert caught.value.message_key == "api.key_invalid_chars"
    assert sent == [], "no HTTP request may be attempted with a malformed key"
    assert "X-Injected" not in str(caught.value)


def test_a_rejected_key_is_not_echoed_in_the_error() -> None:
    client = OpenRouterClient(lambda: "pk-not-a-key", transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(ConfigurationError) as caught:
        client.list_models()
    assert "pk-not-a-key" not in str(caught.value)
    assert "pk-not-a-key" not in json.dumps(caught.value.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------- storage rules
def test_the_encrypted_file_does_not_contain_the_key(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    store.set_api_key(KEY)
    assert store.get_api_key() == KEY
    for path in tmp_path.iterdir():
        raw = path.read_bytes()
        assert KEY.encode() not in raw, path.name
        assert KEY[:24].encode() not in raw, path.name


def test_the_status_report_has_no_key_material(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets.bin", tmp_path / "secret.key")
    store.set_api_key(KEY)
    status = store.status()
    packed = json.dumps(status, default=str)
    assert "sk-or" not in packed
    assert status["count"] == 1


def test_the_settings_database_never_stores_the_key(ctx) -> None:  # noqa: ANN001
    ctx.secrets.set_api_key(KEY)
    ctx.settings.set("ai.default_model", "openai/gpt-4o-mini")
    for path in ctx.paths.home.rglob("*"):
        if path.is_file() and path.suffix in {".db", ".json", ".sqlite"}:
            raw = path.read_bytes()
            assert KEY.encode() not in raw, f"key found in {path}"


def test_a_backup_excludes_the_key(ctx) -> None:  # noqa: ANN001
    ctx.secrets.set_api_key(KEY)
    info = BackupService(ctx.paths, ctx.db, ctx.settings).create_backup()
    assert info.path.is_file()
    with zipfile.ZipFile(info.path) as archive:
        names = archive.namelist()
        assert not any("secret" in name.lower() for name in names)
        for name in names:
            assert KEY.encode() not in archive.read(name), name
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contains_secrets"] is False


# --------------------------------------------------------------------- redaction
def test_every_key_shape_is_masked() -> None:
    assert redact(KEY) != KEY
    assert "0123456789abcdef" not in redact(f"Authorization: Bearer {KEY}")
    for sample in (
        "sk-or-v1-aaaaaaaaaaaaaaaa",
        "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "github_pat_aaaaaaaaaaaaaaaaaaaaaaaaa",
        "sk-aaaaaaaaaaaaaaaaaaaaaaaa",
    ):
        assert sample not in redact(f"using {sample} now"), sample


def test_a_log_handler_cannot_write_the_key() -> None:
    """The production filter+formatter pair, exercised as it runs in the app."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactFilter())
    logger = logging.getLogger("myai.test.key_safety")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info("request failed with key %s", KEY)
        logger.info(f"second attempt using {KEY}")
        logger.warning("auth header", extra={"fields": {"header": f"Bearer {KEY}"}})
    finally:
        logger.removeHandler(handler)

    written = stream.getvalue()
    assert written.strip(), "the test must actually write a log line"
    assert KEY not in written
    assert KEY[:24] not in written
    assert "0123456789abcdef" not in written


def test_mask_keeps_only_the_edges() -> None:
    masked = mask_secret(KEY)
    assert masked.startswith("sk-or-v")
    assert masked.endswith(KEY[-4:])
    assert "0123456789" not in masked
    assert mask_secret("") == ""
