"""FastAPI dependencies."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.domain.models import Account
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import AccountRepository, AccountSessionRepository


async def db_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commits on a clean response, rolls back
    if the handler raises."""
    async with session_scope() as session:
        yield session


Session = Annotated[AsyncSession, Depends(db_session)]


async def current_account(
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> Account:
    """Resolve a bearer token to an account, or 401.

    Stub identity per CLAUDE.md section 15: the token proves only that someone
    signed in with a handle. It is not a security boundary, and nothing here
    should start treating it as one without reopening that section.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in first: send 'Authorization: Bearer <token>'",
        )
    token = authorization.split(" ", 1)[1].strip()
    account_session = await AccountSessionRepository(session).resolve(token)
    if account_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or unknown")
    account = await AccountRepository(session).get(account_session.account_id)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return account


CurrentAccount = Annotated[Account, Depends(current_account)]


async def optional_account(
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> Account | None:
    """Same resolution, but anonymous is allowed.

    The single-player flow predates accounts and must keep working, so routes
    that gained an owner concept accept both.
    """
    if not authorization:
        return None
    try:
        return await current_account(session, authorization)
    except HTTPException:
        return None


OptionalAccount = Annotated[Account | None, Depends(optional_account)]
