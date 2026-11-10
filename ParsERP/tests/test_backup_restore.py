"""Backup creation, verification, restore and retention."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from pars_erp.core.errors import BackupError, PermissionDeniedError, RestoreError, ValidationError
from pars_erp.services.audit_service import EventType
from pars_erp.services.context import AppServices
from pars_erp.services.user_service import UserCreateData
from tests.conftest import TEST_USER_PASSWORD


class TestBackupCreation:
    def test_create_backup_produces_verified_archive(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin, note="آزمون")
        assert info.path.exists()
        assert info.kind == "manual"
        assert info.size_bytes > 0
        with zipfile.ZipFile(info.path) as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            manifest = archive.read("manifest.json").decode("utf-8")
            assert "pars_erp.db" in manifest
            assert "database/" in "".join(names)

    def test_backup_is_recorded_and_listed(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        listed = services.backups.list_backups(admin)
        assert any(item.filename == info.filename for item in listed)
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.BACKUP_CREATED in events

    def test_backup_requires_permission(self, services: AppServices, accountant) -> None:
        with pytest.raises(PermissionDeniedError):
            services.backups.create_backup(accountant)

    def test_verify_detects_tampering(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        result = services.backups.verify_backup(info.path, ctx=admin)
        assert result.ok is True
        assert result.checks["checksum"] and result.checks["sqlite_integrity"]

        corrupted = info.path.parent / "corrupted.zip"
        with zipfile.ZipFile(info.path) as source, zipfile.ZipFile(corrupted, "w") as target:
            for name in source.namelist():
                payload = source.read(name)
                if name.startswith("database/"):
                    payload = payload[:-100] + b"0" * 100
                target.writestr(name, payload)
        bad = services.backups.verify_backup(corrupted, ctx=admin)
        assert bad.ok is False

    def test_verify_missing_file(self, services: AppServices, admin, tmp_path: Path) -> None:
        result = services.backups.verify_backup(tmp_path / "nope.zip", ctx=admin)
        assert result.ok is False

    def test_delete_backup(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        services.backups.delete_backup(admin, info.path)
        assert not info.path.exists()
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.BACKUP_DELETED in events

    def test_delete_outside_folder_is_refused(self, services: AppServices, admin, tmp_path) -> None:
        stray = tmp_path / "stray.zip"
        stray.write_bytes(b"x")
        with pytest.raises(BackupError):
            services.backups.delete_backup(admin, stray)

    def test_retention_pruning(self, services: AppServices, admin) -> None:
        for _ in range(4):
            services.backups.create_backup(admin)
        services.backups.prune(admin, keep=2)
        assert len(list(services.backups.backup_dir().glob("pars_erp_backup_*.zip"))) == 2


class TestRestore:
    def test_restore_brings_back_deleted_data(self, services: AppServices, admin) -> None:
        services.users.create_user(admin, UserCreateData(
            username="beforebackup", full_name="کاربر قبل از پشتیبان",
            password=TEST_USER_PASSWORD, confirm_password=TEST_USER_PASSWORD,
            role_codes=("viewer",)))
        info = services.backups.create_backup(admin)

        # delete the user's roles relation by deactivating; then restore should bring state back
        row = services.users.list_users(admin, search="beforebackup").items[0]
        services.users.set_active(admin, row.id, False)
        assert services.users.get_user(admin, row.id).is_active is False

        result = services.backups.restore_backup(admin, info.path, confirm_phrase="بازیابی")
        assert result.ok is True
        assert result.safety_backup is not None and result.safety_backup.exists()
        restored = services.users.list_users(admin, search="beforebackup").items[0]
        assert restored.is_active is True

    def test_restore_requires_confirmation_phrase(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        with pytest.raises(ValidationError):
            services.backups.restore_backup(admin, info.path, confirm_phrase="خیر")

    def test_restore_requires_permission(self, services: AppServices, admin, accountant) -> None:
        info = services.backups.create_backup(admin)
        with pytest.raises(PermissionDeniedError):
            services.backups.restore_backup(accountant, info.path, confirm_phrase="بازیابی")

    def test_restore_rejects_invalid_archive(self, services: AppServices, admin) -> None:
        broken = services.backups.backup_dir() / "broken.zip"
        broken.write_bytes(b"not a zip")
        with pytest.raises(RestoreError):
            services.backups.restore_backup(admin, broken, confirm_phrase="بازیابی")

    def test_restore_is_logged(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        services.backups.restore_backup(admin, info.path, confirm_phrase="بازیابی")
        events = [e.event_type for e in services.audit.list_security_events(page_size=20).items]
        assert EventType.BACKUP_RESTORED in events

    def test_database_still_usable_after_restore(self, services: AppServices, admin) -> None:
        info = services.backups.create_backup(admin)
        services.backups.restore_backup(admin, info.path, confirm_phrase="بازیابی")
        assert services.db.ping() is True
        assert services.auth.authenticate("admin", "ModirPass1234").username == "admin"


class TestStartupBackup:
    def test_first_startup_creates_backup(self, services: AppServices, admin) -> None:
        info = services.backups.startup_backup_if_due(interval_hours=24)
        assert info is not None and info.kind == "startup"

    def test_second_startup_within_interval_skips(self, services: AppServices, admin) -> None:
        services.backups.startup_backup_if_due(interval_hours=24)
        assert services.backups.startup_backup_if_due(interval_hours=24) is None

    def test_startup_skipped_without_users(self, services: AppServices) -> None:
        assert services.backups.last_backup_at() is None
