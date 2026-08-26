"""SQLAlchemy async engine and session plumbing.

The engine is created once at FastAPI lifespan startup and disposed at
shutdown. Everything that touches the database goes through a session handed
out here, and through a repository in store/repositories/ (CLAUDE.md §14: the
API layer never talks to SQLAlchemy directly).

This engine speaks asyncpg. The LangGraph checkpointer that backs
interrupt_after=["gather"] runs its own psycopg3 pool against the same
database; that is the checkpointer package's design, not a second store.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from syncinerary.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def make_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, echo=False, future=True)


def init_engine() -> AsyncEngine:
    """Create the process-wide engine. Idempotent, called from lifespan."""
    global _engine, _session_factory
    if _engine is None:
        _engine = make_engine()
        # expire_on_commit=False: repositories return detached pydantic models,
        # so nothing should trigger a lazy refresh after the session closes.
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


async def dispose_engine() -> None:
    """Release pooled connections. Called from lifespan shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on clean exit, roll back on exception.

    Use this from graph nodes and scripts. FastAPI routes use the `db_session`
    dependency in api/deps.py, which wraps this.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def verify_pgvector(engine: AsyncEngine) -> bool:
    """Return True if the pgvector extension is installed on the connected DB."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='vector'")
        )
        return result.first() is not None
