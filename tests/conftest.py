"""Shared test fixtures.

Tests that need Postgres skip cleanly when it is not running, so `pytest`
stays useful without `docker compose up`. They do NOT fall back to sqlite:
the schema uses JSONB, native enums, text[] and pgvector, none of which sqlite
has, so a sqlite pass would prove nothing about the schema that ships.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from syncinerary.store.db import make_engine


@pytest_asyncio.fixture(scope="function")
async def engine() -> AsyncEngine:
    """A live engine against the configured Postgres, or skip the test."""
    eng = make_engine()
    try:
        async with eng.connect():
            pass
    except Exception as exc:  # noqa: BLE001 - any connection failure means skip
        await eng.dispose()
        pytest.skip(f"Postgres not reachable, skipping DB test: {exc}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine: AsyncEngine) -> AsyncSession:
    """A session inside a transaction that is always rolled back.

    Repository code under test calls flush(), never commit(), so wrapping the
    whole test in one outer transaction and rolling it back leaves the
    database exactly as it was found. That keeps the suite order-independent
    without truncating tables between tests.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        db = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield db
        finally:
            await db.close()
            # A test that provoked an IntegrityError has already had the
            # transaction rolled back underneath it, so rolling back again
            # warns about a transaction deassociated from its connection.
            if trans.is_active:
                await trans.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(session: AsyncSession) -> AsyncClient:
    """HTTP client against the real app, sharing the test's transaction.

    The db_session dependency is overridden rather than letting the app open
    its own, so request writes land in the transaction the session fixture
    rolls back. Lifespan is not run: it would start tracing and a second
    engine, neither of which a route test needs.
    """
    from syncinerary.api.deps import db_session
    from syncinerary.api.main import app

    async def _override_session():
        yield session

    app.dependency_overrides[db_session] = _override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            yield http
    finally:
        app.dependency_overrides.clear()
