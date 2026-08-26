"""Alembic environment.

Two things here are not boilerplate:

1. The database URL comes from `config.settings`, not from alembic.ini. One
   source of truth, and no credentials in a committed file.

2. `include_object` filters out the LangGraph checkpointer's own tables. The
   graph is compiled with interrupt_after=["gather"] (the human swipe break),
   which needs AsyncPostgresSaver, and that package creates and owns
   `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and
   `checkpoint_migrations` in this same database via its own setup() call.
   Without this filter the next `alembic revision --autogenerate` sees tables
   absent from our metadata and cheerfully emits DROP TABLE for all of them.
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from syncinerary.config import settings
from syncinerary.store.tables import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

# Owned by langgraph-checkpoint-postgres, not by us. See module docstring.
LANGGRAPH_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and name in LANGGRAPH_TABLES)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
