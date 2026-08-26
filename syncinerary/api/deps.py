"""FastAPI dependencies."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.store.db import session_scope


async def db_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commits on a clean response, rolls back
    if the handler raises."""
    async with session_scope() as session:
        yield session


Session = Annotated[AsyncSession, Depends(db_session)]
