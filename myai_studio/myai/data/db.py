"""SQLite database lifecycle.

* WAL journaling, foreign keys and a busy timeout are always enabled.
* A schema version is stored so future phases can migrate safely.
* The connection is created on the calling thread and sessions are short
  lived, which keeps background workers safe.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.errors import DatabaseError
from .models import Base

logger = logging.getLogger(__name__)

LATEST_SCHEMA = 4

# Future schema changes are appended here: version -> list of SQL statements.
# v2 adds the memory, output and output-revision tables; ``create_all`` already
# creates them for fresh and existing databases, so the migration only ensures
# the indexes exist for databases upgraded in place.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "CREATE INDEX IF NOT EXISTS ix_memories_scope ON memories(scope)",
        "CREATE INDEX IF NOT EXISTS ix_memories_conversation ON memories(conversation_id)",
        "CREATE INDEX IF NOT EXISTS ix_outputs_conversation ON outputs(conversation_id)",
        "CREATE INDEX IF NOT EXISTS ix_revisions_output ON output_revisions(output_id)",
    ],
    # v3 adds the prompt library and the persisted task centre (Phase 5).
    3: [
        "CREATE INDEX IF NOT EXISTS ix_prompts_category ON prompts(category)",
        "CREATE INDEX IF NOT EXISTS ix_prompts_updated ON prompts(updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_prompts_source ON prompts(source)",
        "CREATE INDEX IF NOT EXISTS ix_task_runs_created ON task_runs(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_task_runs_kind ON task_runs(kind)",
    ],
    # v4 adds real file attachments (Phase 6 / post-5 upgrade).
    4: [
        "CREATE INDEX IF NOT EXISTS ix_attachments_message ON attachments(message_id)",
    ],
}


class Database:
    def __init__(self, path: str | Path, *, echo: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 20},
        )
        self._install_pragmas(self._engine)
        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, class_=Session
        )
        self._initialized = False

    @staticmethod
    def _install_pragmas(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=20000")
            finally:
                cursor.close()

    @property
    def engine(self) -> Engine:
        return self._engine

    def initialize(self) -> "Database":
        try:
            Base.metadata.create_all(self._engine)
            with self._engine.begin() as conn:
                version = self._read_version(conn)
                if version > LATEST_SCHEMA:
                    raise DatabaseError(
                        f"Database schema v{version} is newer than this build (v{LATEST_SCHEMA}).",
                        message_key="error.db",
                        hint_key="settings.about_help",
                    )
                for target in range(version + 1, LATEST_SCHEMA + 1):
                    for statement in MIGRATIONS.get(target, []):
                        conn.execute(text(statement))
                self._write_version(conn, LATEST_SCHEMA)
        except DatabaseError:
            raise
        except Exception as exc:  # pragma: no cover - exercised on corrupt files
            raise DatabaseError(
                f"Could not initialize database at {self.path}: {exc}",
                message_key="error.db",
                details=str(exc),
                cause=exc,
            ) from exc
        self._initialized = True
        logger.info("database_ready path=%s schema=%s", self.path, LATEST_SCHEMA)
        return self

    @staticmethod
    def _read_version(conn) -> int:  # noqa: ANN001
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS schema_info (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)")
        )
        row = conn.execute(text("SELECT version FROM schema_info WHERE id = 1")).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _write_version(conn, version: int) -> None:  # noqa: ANN001
        conn.execute(
            text(
                "INSERT INTO schema_info (id, version) VALUES (1, :v) "
                "ON CONFLICT(id) DO UPDATE SET version = :v"
            ),
            {"v": version},
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        if not self._initialized:
            raise DatabaseError("Database.initialize() must be called first", message_key="error.db")
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def schema_version(self) -> int:
        with self._engine.connect() as conn:
            return self._read_version(conn)

    def integrity_check(self) -> str:
        with self._engine.connect() as conn:
            return str(conn.execute(text("PRAGMA integrity_check")).scalar_one())

    def file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def counts(self) -> dict[str, int]:
        from .models import (
            Attachment,
            Conversation,
            Folder,
            Memory,
            Message,
            OutputFile,
            Project,
            Prompt,
            TaskRun,
        )

        with self.session() as session:
            return {
                "conversations": _count(session, Conversation),
                "messages": _count(session, Message),
                "folders": _count(session, Folder),
                "projects": _count(session, Project),
                "memories": _count(session, Memory),
                "outputs": _count(session, OutputFile),
                "prompts": _count(session, Prompt),
                "task_runs": _count(session, TaskRun),
                "attachments": _count(session, Attachment),
            }

    def close(self) -> None:
        self._engine.dispose()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Database {self.path}>"


def _count(session: Session, model) -> int:  # noqa: ANN001
    from sqlalchemy import func

    return int(session.scalar(select(func.count()).select_from(model)) or 0)
