"""Schema, portable column types, SQLite pragmas and configuration handling."""

from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from pars_erp.config.paths import AppPaths
from pars_erp.config.settings import FileConfig, load_config, save_config, write_default_config
from pars_erp.db.base import Base
from pars_erp.db.models import Role, User, UserSession, user_roles
from pars_erp.db.session import Database
from pars_erp.db.types import MoneyAmount, UtcDateTime, utcnow


class TestSchema:
    def test_migrations_create_all_model_tables(self, database: Database) -> None:
        created = set(database.table_names())
        expected = set(Base.metadata.tables) | {"alembic_version"}
        assert expected <= created, f"missing tables: {expected - created}"

    def test_migration_matches_metadata_columns(self, database: Database) -> None:
        inspector = inspect(database.engine)
        for table_name, table in Base.metadata.tables.items():
            if table_name not in inspector.get_table_names():
                continue
            columns = {col["name"] for col in inspector.get_columns(table_name)}
            model_columns = {column.name for column in table.columns}
            assert model_columns <= columns, f"{table_name}: {model_columns - columns}"

    def test_schema_revision_recorded(self, database: Database) -> None:
        revision = database.schema_revision()
        assert revision and len(revision) >= 8

    def test_migrate_is_idempotent(self, database: Database) -> None:
        assert database.migrate() == database.schema_revision()
        assert database.ping() is True

    def test_foreign_keys_are_enforced(self, database: Database) -> None:
        with database.session_scope() as session:
            user = User(username="fkuser", full_name="کاربر", password_hash="$argon2id$test")
            session.add(user)
            session.flush()
            with pytest.raises(IntegrityError):
                session.execute(user_roles.insert().values(user_id=user.id, role_id=9999))
            session.rollback()


class TestColumnTypes:
    def test_money_amount_is_exact_and_integer_backed(self, database: Database) -> None:
        with database.engine.connect() as conn:
            conn.execute(text("CREATE TABLE money_probe (amount BIGINT)"))
            conn.execute(text("DELETE FROM money_probe"))
            from sqlalchemy import MetaData, Table, Column, Integer
            metadata = MetaData()
            probe = Table("money_probe", metadata, Column("amount", MoneyAmount()), extend_existing=True)
            conn.execute(probe.insert().values(amount=Decimal("1234.5678")))
            stored = conn.execute(text("SELECT amount FROM money_probe")).scalar()
            assert stored == 12345678          # minor units, no floating point
            value = conn.execute(select(probe.c.amount)).scalar()
            assert value == Decimal("1234.5678")
            with pytest.raises(Exception):
                conn.execute(probe.insert().values(amount=1.5))
            conn.execute(text("DROP TABLE money_probe"))
            conn.commit()

    def test_money_amount_rejects_excess_precision(self, database: Database) -> None:
        column = MoneyAmount()
        with pytest.raises(Exception):
            column.process_bind_param(Decimal("1.123456"), None)

    def test_utc_datetime_roundtrip(self, database: Database) -> None:
        moment = dt.datetime(2026, 10, 30, 12, 34, 56, tzinfo=dt.timezone.utc)
        with database.session_scope() as session:
            session.add(UserSession(user_id=None, username="clocktest", login_at=moment,
                                    app_version="test"))
        with database.session_scope() as session:
            row = session.execute(
                select(UserSession).where(UserSession.username == "clocktest")).scalar_one()
            assert row.login_at.tzinfo is not None
            assert row.login_at == moment

    def test_naive_datetime_is_treated_as_utc(self, database: Database) -> None:
        column = UtcDateTime()
        naive = dt.datetime(2026, 1, 1, 10, 0, 0)
        stored = column.process_bind_param(naive, type("D", (), {"name": "sqlite"})())
        assert stored.endswith("Z")

    def test_utcnow_is_aware(self) -> None:
        assert utcnow().tzinfo is not None


class TestSqlitePragmas:
    def test_wal_mode_and_foreign_keys(self, database: Database) -> None:
        with database.engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
            assert int(conn.execute(text("PRAGMA foreign_keys")).scalar()) == 1

    def test_size_bytes_and_file_path(self, database: Database) -> None:
        assert database.file_path() is not None
        assert (database.size_bytes() or 0) > 0

    def test_postgresql_backup_is_refused_explicitly(self, database: Database,
                                                     tmp_path: Path) -> None:
        from pars_erp.core.errors import BackupError
        pg_like = Database.__new__(Database)
        pg_like.url = "postgresql+psycopg://user@localhost/db"
        pg_like._sqlite = False
        pg_like._engine = None
        pg_like._session_factory = None
        from pars_erp.services.backup_service import BackupService
        with pytest.raises(BackupError):
            BackupService(pg_like, AppPaths(tmp_path / "x"), audit=None).create_backup(
                None, require_permission_check=False)


class TestConfiguration:
    def test_defaults_are_written_and_reloaded(self, app_paths: AppPaths) -> None:
        write_default_config(app_paths)
        config = load_config(app_paths)
        assert config.database_url.startswith("sqlite:///")
        assert config.database_url.endswith("pars_erp.db")
        assert config.log_level == "INFO"

    def test_environment_variable_wins(self, app_paths: AppPaths, monkeypatch) -> None:
        write_default_config(app_paths)
        monkeypatch.setenv("PARSERP_DATABASE_URL", "sqlite:////tmp/override.db")
        assert load_config(app_paths).database_url == "sqlite:////tmp/override.db"

    def test_postgres_url_gets_psycopg_driver(self, app_paths: AppPaths, monkeypatch) -> None:
        monkeypatch.setenv("PARSERP_DATABASE_URL", "postgresql://user@host/db")
        assert load_config(app_paths).database_url.startswith("postgresql+psycopg://")

    def test_save_and_reload(self, app_paths: AppPaths) -> None:
        config = FileConfig(database_url="sqlite:////tmp/x.db", log_level="debug", echo_sql=True)
        save_config(config, app_paths)
        loaded = load_config(app_paths)
        assert loaded.log_level == "DEBUG" and loaded.echo_sql is True

    def test_corrupted_config_is_reported(self, app_paths: AppPaths) -> None:
        from pars_erp.core.errors import ConfigurationError
        app_paths.config_file.write_text("{not json", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_config(app_paths)

    def test_paths_layout(self, app_paths: AppPaths) -> None:
        app_paths.ensure()
        for path in (app_paths.data_dir, app_paths.backups_dir, app_paths.logs_dir,
                     app_paths.exports_dir):
            assert path.exists()
        assert app_paths.database_file.parent == app_paths.data_dir

    def test_home_override(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PARSERP_HOME", str(tmp_path / "custom"))
        assert AppPaths.default().home == (tmp_path / "custom").resolve()
