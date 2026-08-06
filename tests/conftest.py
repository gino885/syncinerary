"""Shared test fixtures.

Tests that need Postgres skip cleanly when it is not running, so `pytest`
stays useful without `docker compose up`. They do NOT fall back to sqlite:
the schema uses JSONB, native enums, text[] and pgvector, none of which sqlite
has, so a sqlite pass would prove nothing about the schema that ships.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

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
