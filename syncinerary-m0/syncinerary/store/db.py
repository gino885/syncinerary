"""SQLAlchemy async engine.

M0 only verifies the engine connects and pgvector is installed. The full schema
in CLAUDE.md §7 lands as alembic migrations in M1 (the thin vertical slice).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from syncinerary.config import settings


def make_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, echo=False, future=True)


async def verify_pgvector(engine: AsyncEngine) -> bool:
    """Return True if the pgvector extension is installed on the connected DB."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='vector'")
        )
        return result.first() is not None
