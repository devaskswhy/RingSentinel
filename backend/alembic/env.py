"""Alembic environment.

The database URL always comes from the environment (DATABASE_URL), never from
alembic.ini, so the same migration runs identically in Docker and on the host.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `app` importable when alembic runs from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ringsentinel:ringsentinel@db:5432/ringsentinel",
)

# Managed hosts (Neon, Render, Heroku) hand out `postgresql://` or
# `postgres://`, which SQLAlchemy resolves to psycopg2 — a driver this project
# does not install. The same normalisation runs in app/config.py, but Alembic
# never loads Settings, so without this `alembic upgrade head` fails with
# ModuleNotFoundError: psycopg2 while the app itself would have been fine.
# entrypoint.sh runs migrations on every start, so this is the first thing a
# deployment would have hit.
from app.config import _normalise_database_url  # noqa: E402

database_url = _normalise_database_url(database_url)

config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
