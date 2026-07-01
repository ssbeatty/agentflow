"""Alembic environment for AgentFlow.

Single source of truth for the DB URL: the app's own settings
(``app.database.DATABASE_URL``), so ``DATABASE_URL`` drives the app and the
migrations identically — sqlite for local/single-host, postgres in docker.

We reuse the app's configured ``engine`` (pool settings + sqlite pragmas) rather
than building a fresh one from the ini, and turn on ``render_as_batch`` for
sqlite so ``ALTER TABLE`` operations (which sqlite only partially supports) are
emitted as copy-and-move batches. That keeps the *same* revision files working
on both sqlite and postgres.
"""
from logging.config import fileConfig

from alembic import context

# App metadata + engine. Importing app.models ensures every table is registered
# on Base.metadata so --autogenerate can diff the full schema.
from app.database import Base, engine, DATABASE_URL
import app.models  # noqa: F401  (populates Base.metadata)

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade --sql``) without a live DB."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=DATABASE_URL.startswith("sqlite"),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the app's live engine."""
    with engine.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
