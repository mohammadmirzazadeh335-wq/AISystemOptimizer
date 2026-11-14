"""The controlled-update path: check, verify, stage, health check, roll back.

Nothing here talks to the internet.  A manifest is written to a temporary folder
and pointed at by the ``update_source`` setting, which is exactly what an
organisation with an internal file share would do.  The signature test generates
a throw-away Ed25519 key pair, so the verification path is genuinely exercised
rather than assumed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.update_service import (
    MANIFEST_FORMAT,
    STATUS_AHEAD,
    STATUS_AVAILABLE,
    STATUS_INVALID_MANIFEST,
    STATUS_NOT_CONFIGURED,
    STATUS_UNREACHABLE,
    STATUS_UP_TO_DATE,
    UpdateError,
    UpdateService,
    version_key,
)

NEW_VERSION = "0.9.1"


def _write_manifest(tmp_path: Path, releases: list[dict], **extra) -> Path:
    path = tmp_path / "releases.json"
    payload = {"format": MANIFEST_FORMAT, "channel": "stable", "releases": releases, **extra}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _package(tmp_path: Path, content: bytes = b"installer-bytes") -> Path:
    path = tmp_path / "ZarrinHormoz-setup.bin"
    path.write_bytes(content)
    return path


def _release(package: Path, *, version: str = NEW_VERSION, signature: str | None = None,
             sha256: str | None = None, size: int | None = None) -> dict:
    return {
        "version": version,
        "released_at": "2026-11-01",
        "notes_fa": ["رفع اشکال در گزارش تراز", "افزودن خروجی PDF با شمارهٔ صفحه"],
        "url": str(package),
        "sha256": sha256 if sha256 is not None else hashlib.sha256(
            package.read_bytes()).hexdigest(),
        "size_bytes": size if size is not None else package.stat().st_size,
        "schema_revision": "0006_phase7_alerts",
        **({"signature": signature} if signature else {}),
    }


def _use_source(services, admin, path: Path) -> None:
    services.settings.update(admin, {"update_source": str(path)})


# ------------------------------------------------------------------- version
def test_version_ordering_puts_prereleases_first() -> None:
    assert version_key("0.7.0-beta") < version_key("0.7.0") < version_key("0.10.0")
    with pytest.raises(ValidationError):
        version_key("not-a-version")


# --------------------------------------------------------------------- check
def test_check_without_a_configured_source_is_honest(services, admin) -> None:
    result = services.updates.check(admin)
    assert result.status == STATUS_NOT_CONFIGURED
    assert result.has_update is False
    assert "تنظیم نشده" in result.message_fa


def test_check_requires_permission(services) -> None:
    with pytest.raises(PermissionDeniedError):
        services.updates.check(None)


def test_check_finds_a_newer_release_with_its_notes(services, admin, tmp_path: Path) -> None:
    package = _package(tmp_path)
    source = _write_manifest(tmp_path, [_release(package)])
    _use_source(services, admin, source)

    result = services.updates.check(admin)
    assert result.status == STATUS_AVAILABLE
    assert result.release is not None and result.release.version == NEW_VERSION
    assert "رفع اشکال" in result.release.notes_text()
    assert result.status_fa


def test_check_reports_being_up_to_date_and_ahead(services, admin, tmp_path: Path) -> None:
    package = _package(tmp_path)
    older = services.updates.app_version
    source = _write_manifest(tmp_path, [_release(package, version=older)])
    _use_source(services, admin, source)
    assert services.updates.check(admin).status == STATUS_UP_TO_DATE

    source = _write_manifest(tmp_path, [_release(package, version="0.1.0")])
    _use_source(services, admin, source)
    assert services.updates.check(admin).status == STATUS_AHEAD


def test_stable_channel_ignores_prereleases_but_beta_sees_them(services, admin,
                                                               tmp_path: Path) -> None:
    package = _package(tmp_path)
    source = _write_manifest(tmp_path, [_release(package, version="0.9.0-rc1")])
    _use_source(services, admin, source)
    assert services.updates.check(admin).status in (STATUS_UP_TO_DATE, STATUS_AHEAD)
    services.settings.update(admin, {"update_channel": "beta"})
    result = services.updates.check(admin)
    assert result.status == STATUS_AVAILABLE and result.release.version == "0.9.0-rc1"


def test_unreadable_source_and_broken_manifest_are_reported(services, admin,
                                                            tmp_path: Path) -> None:
    _use_source(services, admin, tmp_path / "missing.json")
    assert services.updates.check(admin).status == STATUS_UNREACHABLE

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    _use_source(services, admin, broken)
    assert services.updates.check(admin).status == STATUS_INVALID_MANIFEST

    wrong_format = tmp_path / "old.json"
    wrong_format.write_text(json.dumps({"format": "something-else", "releases": []}),
                            encoding="utf-8")
    _use_source(services, admin, wrong_format)
    assert services.updates.check(admin).status == STATUS_INVALID_MANIFEST


# ------------------------------------------------------------ verify & stage
def test_verify_rejects_a_tampered_package_and_deletes_it(services, admin,
                                                          tmp_path: Path) -> None:
    package = _package(tmp_path, b"original")
    good = _release(package)
    package.write_bytes(b"tampered")
    result = services.updates.verify_package(package, services.updates._parse_manifest(
        json.dumps({"format": MANIFEST_FORMAT, "releases": [good]}))[0])
    assert result.ok is False
    assert "SHA-256" in result.message_fa
    assert not package.exists(), "a package that fails verification must not be kept"


def test_verify_rejects_a_size_mismatch(services, admin, tmp_path: Path) -> None:
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package, size=1)]}))[0]
    assert services.updates.verify_package(package, release).ok is False


def test_unsigned_package_is_blocked_when_signatures_are_required(services, admin,
                                                                  tmp_path: Path) -> None:
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]
    result = services.updates.verify_package(package, release)
    assert result.ok is False
    assert result.signature_status == "unsigned"
    assert "امضا" in result.message_fa

    services.settings.update(admin, {"update_require_signature": False})
    package = _package(tmp_path)  # the rejected file was deleted by design
    result = services.updates.verify_package(package, release)
    assert result.ok is True and result.signature_status == "unsigned"


def test_a_valid_ed25519_signature_is_verified(services, admin, tmp_path: Path) -> None:
    crypto = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    services.settings.update(admin, {
        "update_public_key": base64.b64encode(public_key).decode("ascii")})
    package = _package(tmp_path)
    signature = base64.b64encode(private_key.sign(package.read_bytes())).decode("ascii")
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package, signature=signature)]}))[0]

    verified = services.updates.verify_package(package, release)
    assert verified.ok is True
    assert verified.signature_status == "verified"

    # a different payload with the same signature must fail
    package.write_bytes(b"other-bytes")
    forged = services.updates.verify_package(package, replace(
        release, sha256=hashlib.sha256(b"other-bytes").hexdigest(),
        size_bytes=len(b"other-bytes")))
    assert forged.ok is False and forged.signature_status == "invalid"
    assert crypto  # imported, so the branch really ran


def test_stage_backs_up_first_and_records_a_pending_marker(services, admin,
                                                           tmp_path: Path) -> None:
    services.settings.update(admin, {"update_require_signature": False})
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]

    staged = services.updates.stage(admin, release, package)
    assert staged.backup is not None and staged.backup.exists()
    marker = services.updates.pending()
    assert marker is not None
    assert marker["to_version"] == NEW_VERSION
    assert marker["backup"] == staged.backup.name
    assert marker["signature_status"] == "unsigned"

    events = [e.event_type for e in services.audit.list_security_events(page_size=30).items]
    assert "update.staged" in events


def test_stage_refuses_a_package_that_fails_verification(services, admin,
                                                         tmp_path: Path) -> None:
    services.settings.update(admin, {"update_require_signature": False})
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]
    package.write_bytes(b"corrupt")
    with pytest.raises(UpdateError):
        services.updates.stage(admin, release, package)
    assert services.updates.pending() is None


def test_stage_needs_the_settings_permission(services, admin, accountant,
                                             tmp_path: Path) -> None:
    services.settings.update(admin, {"update_require_signature": False})
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]
    with pytest.raises(PermissionDeniedError):
        services.updates.stage(accountant, release, package)


# ------------------------------------------------------ health check/rollback
def test_health_check_reports_the_real_state(services, admin) -> None:
    report = services.updates.health_check(admin)
    assert report.ok is True
    assert report.checks["database"] is True
    assert report.checks["migrations_current"] is True

    wrong = services.updates.health_check(admin, expected_revision="9999_nope")
    assert wrong.ok is False
    assert wrong.checks["schema_matches_update"] is False


def test_rollback_without_a_staged_update_is_refused(services, admin) -> None:
    assert services.updates.pending() is None
    with pytest.raises(UpdateError):
        services.updates.rollback(admin, confirm_phrase="بازیابی")


def test_rollback_restores_the_pre_update_backup(services, admin, tmp_path: Path) -> None:
    services.settings.update(admin, {"update_require_signature": False})
    from pars_erp.services.user_service import UserCreateData

    services.users.create_user(admin, UserCreateData(
        username="beforupdate", full_name="کاربر پیش از به‌روزرسانی",
        password="UpdatePass1234", confirm_password="UpdatePass1234",
        role_codes=("viewer",)))
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]
    services.updates.stage(admin, release, package)

    # simulate the damage an update could cause: the user disappears
    row = services.users.list_users(admin, search="beforupdate").items[0]
    services.users.set_active(admin, row.id, False)
    assert services.users.get_user(admin, row.id).is_active is False

    services.updates.rollback(admin, confirm_phrase="بازیابی")
    assert services.users.get_user(admin, row.id).is_active is True
    assert services.updates.pending() is None
    events = [e.event_type for e in services.audit.list_security_events(page_size=30).items]
    assert "update.rolled_back" in events


def test_download_copies_a_local_package_into_the_updates_folder(services, admin,
                                                                 tmp_path: Path) -> None:
    services.settings.update(admin, {"update_require_signature": False})
    package = _package(tmp_path)
    release = services.updates._parse_manifest(json.dumps({
        "format": MANIFEST_FORMAT, "releases": [_release(package)]}))[0]
    downloaded = services.updates.download(admin, release)
    assert downloaded.is_file()
    assert downloaded.parent == services.updates.updates_dir
    assert downloaded.read_bytes() == package.read_bytes()
    assert services.updates.verify_package(downloaded, release).ok is True


def test_service_is_wired_into_the_application(services) -> None:
    assert isinstance(services.updates, UpdateService)
    assert services.updates.app_version.startswith("0.")


# ------------------------------------------------- end-to-end release tooling
def test_release_manifest_built_from_a_real_artefact_is_accepted(services, admin,
                                                                 tmp_path: Path) -> None:
    """``packaging/make_release_manifest.py`` -> ``UpdateService.check/stage``."""
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[1] / "packaging" / "make_release_manifest.py"
    spec = importlib.util.spec_from_file_location("make_release_manifest", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    artefact = tmp_path / "ZarrinHormoz-0.9.1-setup.exe"
    artefact.write_bytes(b"MZ-real-installer-bytes")
    document = module.build(
        artefact, version="0.9.1", released_at="2026-11-20",
        notes=["افزودن گزارش کاردکس بیرون‌انبار"], url=str(artefact))
    entry = document["releases"][0]
    assert document["format"] == MANIFEST_FORMAT
    assert entry["sha256"] == hashlib.sha256(artefact.read_bytes()).hexdigest()
    assert entry["size_bytes"] == artefact.stat().st_size
    assert entry["schema_revision"]  # read from the real migrations
    assert "signature" not in entry  # unsigned without a key

    source = tmp_path / "releases.json"
    source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    services.settings.update(admin, {"update_source": str(source),
                                    "update_require_signature": False})
    result = services.updates.check(admin)
    assert result.status == STATUS_AVAILABLE and result.release.version == "0.9.1"
    staged = services.updates.stage(admin, result.release, artefact)
    assert staged.backup is not None


def test_release_manifest_can_be_signed_with_ed25519(tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    import importlib.util
    import sys

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    script = Path(__file__).resolve().parents[1] / "packaging" / "make_release_manifest.py"
    spec = importlib.util.spec_from_file_location("make_release_manifest_signed", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "release_signing_key.pem"
    key_file.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                           NoEncryption()))
    artefact = tmp_path / "setup.exe"
    artefact.write_bytes(b"signed-installer")
    document = module.build(artefact, version="0.9.2", released_at="2026-11-21",
                            notes=["امضای واقعی"], url=str(artefact), private_key=key_file)
    signature = base64.b64decode(document["releases"][0]["signature"])
    key.public_key().verify(signature, artefact.read_bytes())  # really valid
    assert key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
