"""System doctor: every check is exercised against a real temporary workspace."""

from __future__ import annotations

import json
import zipfile

from myai.core.redaction import find_secrets
from myai.services.doctor import FAIL, OK, SKIP, WARN, report_text, run_checks
from myai.services.toolchains import ToolchainRegistry

KEYS = {
    "database", "schema", "workspace", "disk", "backups", "logs", "attachments",
    "secrets", "api_key", "platform", "toolchains", "tables", "locales", "settings",
}


def run(ctx, **kwargs) -> object:  # noqa: ANN001
    return run_checks(paths=ctx.paths, settings=ctx.settings, db=ctx.db, secrets=ctx.secrets, **kwargs)


def by_key(report) -> dict:  # noqa: ANN001
    return {check.key: check for check in report.checks}


def test_every_check_runs_on_a_fresh_workspace(ctx) -> None:  # noqa: ANN001
    report = run(ctx)
    assert set(by_key(report)) == KEYS
    assert len(report.checks) == len(KEYS)
    assert report.counts[SKIP] == 2  # no key yet, no toolchain registry injected
    assert report.counts[FAIL] == 0
    assert 0 <= report.score <= 100
    assert report.verdict in {"healthy", "attention", "needs_care"}


def test_the_database_and_locales_are_actually_healthy(ctx) -> None:  # noqa: ANN001
    report = run(ctx)
    checks = by_key(report)
    assert checks["database"].status == OK
    assert "integrity_check" in checks["database"].detail
    assert checks["schema"].status == OK and checks["schema"].detail == "v4"
    assert checks["locales"].status == OK
    import json

    from myai.i18n.translator import LOCALES_DIR

    expected = len(json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8")))
    assert f"{expected} keys" in checks["locales"].detail
    assert checks["workspace"].status == OK
    assert checks["platform"].status == OK


def test_missing_backup_and_missing_key_are_warnings_not_failures(ctx) -> None:  # noqa: ANN001
    checks = by_key(run(ctx))
    assert checks["backups"].status == WARN
    assert checks["secrets"].status == WARN
    assert checks["api_key"].status == SKIP
    # Two warnings keep the app in "attention", never "needs_care".
    assert run(ctx).verdict == "attention"


def test_storing_a_key_makes_the_security_checks_green(ctx) -> None:  # noqa: ANN001
    key = "sk-or-v1-" + "a1b2c3d4e5" * 4
    ctx.secrets.set_api_key(key)
    checks = by_key(run(ctx))
    assert checks["secrets"].status == OK
    assert checks["api_key"].status == OK
    assert "sk-or- prefix" in checks["api_key"].detail
    assert "OpenRouter" in checks["api_key"].detail
    # The detail must never contain the key itself.
    assert all(key not in check.detail for check in checks.values())
    report = run(ctx)
    packed = json.dumps(report.to_dict())
    assert key not in packed


def test_a_plaintext_key_on_disk_is_a_failure(ctx) -> None:  # noqa: ANN001
    key = "sk-or-v1-" + "deadbeef" * 5
    ctx.secrets.set_api_key(key)
    ctx.paths.secrets_file.write_text(f"api_key={key}", encoding="utf-8")
    checks = by_key(run(ctx))
    assert checks["secrets"].status == FAIL
    assert "plaintext" in checks["secrets"].detail
    assert key not in checks["secrets"].detail
    assert run(ctx).verdict == "needs_care"


def test_malformed_key_has_a_precise_failure(ctx) -> None:  # noqa: ANN001
    ctx.secrets.set_api_key("sk-or-v1-" + "a" * 40 + "\r\nX-Injected: 1")
    checks = by_key(run(ctx))
    assert checks["api_key"].status == FAIL
    assert checks["api_key"].detail == "api.key_invalid_chars"


def test_a_recent_backup_turns_the_amber_check_green(ctx) -> None:  # noqa: ANN001
    from datetime import datetime, timezone

    backup = ctx.paths.backups_dir / "backup-test.zip"
    ctx.paths.backups_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", "{}")
    ctx.settings.set("data.last_backup", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    checks = by_key(run(ctx))
    assert checks["backups"].status == OK
    assert "1 file" in checks["backups"].detail


def test_stale_backup_is_flagged(ctx) -> None:  # noqa: ANN001
    backup = ctx.paths.backups_dir / "backup-old.zip"
    ctx.paths.backups_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("manifest.json", "{}")
    ctx.settings.set("data.last_backup", "2020-01-01T00:00:00+00:00")
    assert by_key(run(ctx))["backups"].status == WARN


def test_toolchains_are_reported_when_a_registry_is_passed(ctx) -> None:  # noqa: ANN001
    checks = by_key(run(ctx, toolchain_registry=ToolchainRegistry()))
    assert checks["toolchains"].status in {OK, WARN}
    assert checks["toolchains"].detail


def test_log_size_warning_uses_the_real_folder(ctx) -> None:  # noqa: ANN001
    from myai.services.doctor import LOG_WARN_BYTES

    ctx.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    (ctx.paths.logs_dir / "big.log").write_bytes(b"x" * (LOG_WARN_BYTES + 10))
    checks = by_key(run(ctx))
    assert checks["logs"].status == WARN
    assert checks["logs"].fix_key == "doctor.fix_logs"


def test_a_crashing_check_becomes_a_failure_not_an_exception(ctx, monkeypatch) -> None:  # noqa: ANN001
    def explode() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(ctx.db, "integrity_check", explode)
    report = run(ctx)
    assert by_key(report)["database"].status == FAIL
    assert "RuntimeError" in by_key(report)["database"].detail


def test_report_text_lists_every_check_and_no_secret(ctx) -> None:  # noqa: ANN001
    key = "sk-or-v1-" + "f00dbabe" * 5
    ctx.secrets.set_api_key(key)
    text = report_text(run(ctx))
    assert "score:" in text
    for name in KEYS:
        assert name in text
    assert key not in text


def test_score_penalises_failures_more_than_warnings(ctx) -> None:  # noqa: ANN001
    healthy = run(ctx)
    ctx.paths.secrets_file.write_text("api_key=sk-or-v1-" + "a" * 30, encoding="utf-8")
    broken = run(ctx)
    assert broken.score < healthy.score


def test_find_secrets_detects_common_shapes() -> None:
    found = find_secrets(
        "a sk-or-v1-abcdef123456 b ghp_abcdefghijklmnopqrstuvwxyz c Bearer abcdefghijkl"
    )
    assert any(value.startswith("sk-or-v1-") for value in found)
    assert any(value.startswith("ghp_") for value in found)
    assert find_secrets("nothing here") == []
