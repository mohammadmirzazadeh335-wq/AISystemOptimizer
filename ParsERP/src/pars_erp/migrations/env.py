"""Alembic environment for ParsERP.

Works both from the command line (``alembic upgrade head``) and from the
application itself (``Database.upgrade_to_head()``). The URL resolution order is:

1. ``-x url=...`` command line option,
2. ``sqlalchemy.url`` set programmatically (the app does this),
3. ``PARSERP_DATABASE_URL`` environment variable,
4. the installation's ``config.json``.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pars_erp.config.paths import AppPaths  # noqa: E402
from pars_erp.config.settings import load_config  # noqa: E402
from pars_erp.db.base import Base  # noqa: E402
import pars_erp.db.models  # noqa: E402,F401  (registers all tables)

config = context.config
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:  # pragma: no cover - logging config is optional
        pass

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def _resolve_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("url"):
        return x_args["url"]
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured.replace("%%", "%")
    env_url = os.environ.get("PARSERP_DATABASE_URL")
    if env_url:
        return env_url
    settings = load_config(AppPaths.default())
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
