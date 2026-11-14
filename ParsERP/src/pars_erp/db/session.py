"""Engine/session management and schema migrations.

The application never touches SQLAlchemy sessions from UI code: services use
:meth:`Database.session_scope`, which guarantees commit/rollback/close and keeps
multi-table operations atomic.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from pars_erp.config.paths import AppPaths
from pars_erp.config.settings import is_sqlite_url, sqlite_file_from_url
from pars_erp.core.errors import ConfigurationError, UnsupportedOperationError
from pars_erp.db.base import Base

logger = logging.getLogger(__name__)

SQLITE_BUSY_TIMEOUT_MS = 5000
PG_CONNECT_TIMEOUT_S = 10
POOL_RECYCLE_S = 1800

_UNSAFE_URL_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def mask_database_url(url: str) -> str:
    """The connection URL with the password replaced by ``***``.

    Connection URLs land in logs, in ``pars-erp info`` output and in error
    dialogs, and a PostgreSQL URL carries the password: ``user:secret@host``.
    Everything printed or logged must go through this function.
    """
    text = str(url or "")
    if not text:
        return ""
    try:
        parsed = make_url(text)
        if not parsed.password:
            return text
        user = f"{parsed.username}:" if parsed.username else ""
        host = parsed.host or ""
        port = f":{parsed.port}" if parsed.port else ""
        database = f"/{parsed.database}" if parsed.database else ""
        query = ("?" + "&".join(f"{key}={value}"
                               for key, value in parsed.query.items())
                 if parsed.query else "")
        return f"{parsed.drivername}://{user}***@{host}{port}{database}{query}"
    except Exception:
        return _UNSAFE_URL_PASSWORD.sub(r"\1***@", text)


def describe_connection_error(error: BaseException, url: str = "") -> str:
    """A Persian, actionable explanation of a database connection failure."""
    text = str(error)
    name = type(error).__name__
    safe_url = mask_database_url(url)
    if "No module named 'psycopg" in text or "No module named \"psycopg" in text:
        return ("درایور PostgreSQL روی این سیستم نصب نیست. برای اتصال به PostgreSQL "
                "دستور «pip install psycopg[binary]» را اجرا کنید و برنامه را دوباره "
                "باز کنید.")
    if "No module named 'sqlite" in text:
        return "کتابخانهٔ SQLite پایتون در دسترس نیست؛ نصب پایتون را بررسی کنید."
    lowered = text.lower()
    if "password authentication failed" in lowered or "authentication failed" in lowered:
        return ("نام کاربری یا رمز پایگاه دادهٔ PostgreSQL پذیرفته نشد. مشخصات اتصال را در "
                "config.json بررسی کنید.")
    if "could not connect" in lowered or "connection refused" in lowered or \
            "could not translate host name" in lowered or "timeout expired" in lowered or \
            "server closed the connection" in lowered:
        return ("اتصال به سرور پایگاه داده برقرار نشد. روشن بودن سرور، نشانی/پورت و "
                f"دسترسی شبکه را بررسی کنید. ({safe_url})")
    if "unable to open database file" in lowered or "readonly database" in lowered:
        return ("فایل پایگاه دادهٔ SQLite قابل خواندن یا نوشتن نیست. دسترسی پوشهٔ داده و "
                "فضای دیسک را بررسی کنید.")
    if "disk is full" in lowered or "database or disk is full" in lowered:
        return "فضای دیسک برای پایگاه داده کافی نیست."
    if "locked" in lowered:
        return ("پایگاه دادهٔ SQLite در حال استفاده توسط برنامهٔ دیگری است. برنامه‌های "
                "دیگر را ببندید و دوباره تلاش کنید.")
    return f"{name}: {text}"


class Database:
    """Owns the SQLAlchemy engine and session factory."""

    def __init__(self, url: str, *, echo: bool = False, default_schema_check: bool = True) -> None:
        if not url:
            raise ConfigurationError("آدرس پایگاه داده تنظیم نشده است.")
        self.url = url
        self.echo = echo
        self._sqlite = is_sqlite_url(url)
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        if default_schema_check and self._sqlite:
            file = sqlite_file_from_url(url)
            if file is not None:
                file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ engine
    @property
    def is_sqlite(self) -> bool:
        return self._sqlite

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._create_engine()
        return self._engine

    def _create_engine(self) -> Engine:
        kwargs: dict = {"echo": self.echo, "future": True, "pool_pre_ping": True}
        if self._sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 5
            kwargs["pool_timeout"] = 10
            # a stale TCP connection after a network hiccup must not block a query
            kwargs["pool_recycle"] = POOL_RECYCLE_S
            connect_args: dict = {"connect_timeout": PG_CONNECT_TIMEOUT_S,
                                  "application_name": "ZarrinHormoz"}
            if "options" in make_url(self.url).query:
                connect_args.pop("application_name", None)
            kwargs["connect_args"] = connect_args
        engine = create_engine(self.url, **kwargs)
        if self._sqlite:
            self._install_sqlite_pragmas(engine)
        return engine

    @staticmethod
    def _install_sqlite_pragmas(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, _record):  # pragma: no cover - exercised via engine use
            if not isinstance(dbapi_connection, sqlite3.Connection):
                return
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False,
                                                 autoflush=False, future=True)
        return self._session_factory

    def new_session(self) -> Session:
        return self.session_factory()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Transactional unit of work: commit on success, rollback on any error."""
        session = self.new_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------ health
    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # pragma: no cover - depends on environment
            logger.exception("database ping failed")
            return False

    def dialect_name(self) -> str:
        return make_url(self.url).get_backend_name()

    def table_names(self) -> list[str]:
        return sorted(inspect(self.engine).get_table_names())

    def schema_revision(self) -> str | None:
        try:
            with self.engine.connect() as conn:
                return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            return None

    def file_path(self) -> Path | None:
        return sqlite_file_from_url(self.url)

    def size_bytes(self) -> int | None:
        file = self.file_path()
        if file is None or not file.exists():
            return None
        total = file.stat().st_size
        for suffix in ("-wal", "-shm"):
            candidate = Path(str(file) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    # ------------------------------------------------------------------ backup
    def copy_database_to(self, destination: Path) -> Path:
        """Create a consistent copy of the database file.

        SQLite uses the online backup API (safe while the app is running).
        PostgreSQL deployments rely on ``pg_dump`` in phase 7; calling this here
        raises a clear, documented error instead of producing a broken backup.
        """
        if not self._sqlite:
            raise UnsupportedOperationError(
                "پشتیبان‌گیری از پایگاه داده PostgreSQL در این نسخه پیاده‌سازی نشده است. "
                "از pg_dump استفاده کنید یا نسخه SQLite را به کار ببرید.")
        source = sqlite_file_from_url(self.url)
        if source is None:
            raise UnsupportedOperationError("پشتیبان‌گیری از پایگاه داده در حافظه ممکن نیست.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            target = sqlite3.connect(str(destination))
            try:
                raw.backup(target)
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                target.close()
        return destination

    # --------------------------------------------------------------- migrations
    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "migrations"

    def alembic_config(self, *, url: str | None = None):
        from alembic.config import Config as AlembicConfig

        ini_path = self.migrations_dir().parent.parent.parent / "alembic.ini"
        cfg = AlembicConfig(str(ini_path) if ini_path.exists() else None)
        cfg.set_main_option("script_location", str(self.migrations_dir()))
        cfg.set_main_option("sqlalchemy.url", (url or self.url).replace("%", "%%"))
        # the caller owns the logging configuration (see migrations/env.py)
        cfg.attributes["configure_logger"] = False
        return cfg

    def upgrade_to_head(self) -> str:
        """Apply pending migrations and return the resulting revision."""
        from alembic import command

        self.dispose()
        command.upgrade(self.alembic_config(), "head")
        return self.schema_revision() or "head"

    def migrate(self) -> str:
        return self.upgrade_to_head()

    def create_all(self) -> None:
        """Create the schema directly from metadata (tests only)."""
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)


def build_database(url: str | None = None, *, paths: AppPaths | None = None,
                   echo: bool = False) -> Database:
    paths = paths or AppPaths.default()
    if url:
        return Database(url, echo=echo)
    return Database(f"sqlite:///{paths.database_file.as_posix()}", echo=echo)


def set_environment_home(home: Path) -> None:  # pragma: no cover - helper for scripts
    os.environ["PARSERP_HOME"] = str(home)
