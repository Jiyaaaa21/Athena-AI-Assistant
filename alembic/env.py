"""
Phase 12: Alembic environment.

Pulls DATABASE_URL from backend.core.config (i.e. the same env var the
running FastAPI app uses) instead of a separately-maintained URL in
alembic.ini, and points Alembic's autogenerate machinery at
backend.database.models.Base so future `alembic revision --autogenerate`
runs pick up new/changed models automatically.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure `backend` is importable when alembic is invoked from the
# project root (where alembic.ini's prepend_sys_path = . already points).
from backend.core.config import DATABASE_URL
from backend.database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override whatever (blank) value is in alembic.ini with the real,
# environment-driven URL the app itself uses.
config.set_main_option("sqlalchemy.url", DATABASE_URL)


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (`alembic upgrade head --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
