"""Group trip persistence: accounts, sessions, invites, and the trip thread.

See GROUP_TRIP_PLAN.md. Identity here is a stub per CLAUDE.md section 15: an
account is a display name and a handle, and a session is an opaque token with
an expiry. There is no password, no provider, and nothing here should grow one
without reopening that section.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID

from sqlalchemy import update

from syncinerary.domain.models import (
    Account,
    AccountSession,
    TripInvite,
    TripMessage,
)
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository

SESSION_TTL = timedelta(days=30)
INVITE_TTL = timedelta(days=14)
# Crockford-ish: no I, L, O, U, so a code read aloud or retyped from a
# screenshot does not turn into a different trip.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 8


def _now() -> datetime:
    return datetime.now(UTC)


def generate_invite_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


class AccountRepository(BaseRepository[tables.Account, Account]):
    table = tables.Account
    model = Account

    async def find_by_handle(self, handle: str) -> Account | None:
        found = await self.list_where(tables.Account.handle == handle.casefold())
        return found[0] if found else None

    async def upsert_by_handle(self, *, display_name: str, handle: str) -> Account:
        """Sign-in for a stub identity: the handle is the whole credential.

        Deliberately not a security boundary. It exists so a person keeps one
        identity across trips, which is what invites and chat authorship need.
        """
        existing = await self.find_by_handle(handle)
        if existing is not None:
            return existing
        return await self.add(
            Account(display_name=display_name, handle=handle.casefold())
        )


class AccountSessionRepository(BaseRepository[tables.AccountSession, AccountSession]):
    table = tables.AccountSession
    model = AccountSession

    async def issue(self, account_id: UUID) -> AccountSession:
        return await self.add(
            AccountSession(
                token=secrets.token_urlsafe(32),
                account_id=account_id,
                expires_at=_now() + SESSION_TTL,
            )
        )

    async def resolve(self, token: str) -> AccountSession | None:
        """Return the session only while it is still valid.

        Expiry is enforced on read rather than by a sweep, so a stale row can
        never authenticate anyone even if nothing has cleaned it up.
        """
        found = await self.list_where(tables.AccountSession.token == token)
        if not found:
            return None
        session = found[0]
        return session if session.expires_at > _now() else None


class TripInviteRepository(BaseRepository[tables.TripInvite, TripInvite]):
    table = tables.TripInvite
    model = TripInvite

    async def create_for_trip(
        self,
        *,
        trip_id: UUID,
        created_by_traveler_id: UUID,
        max_uses: int = 20,
    ) -> TripInvite:
        return await self.add(
            TripInvite(
                trip_id=trip_id,
                code=generate_invite_code(),
                created_by_traveler_id=created_by_traveler_id,
                expires_at=_now() + INVITE_TTL,
                max_uses=max_uses,
            )
        )

    async def find_by_code(self, code: str) -> TripInvite | None:
        found = await self.list_where(tables.TripInvite.code == code.upper())
        return found[0] if found else None

    async def claim(self, invite_id: UUID) -> TripInvite | None:
        """Consume one use, refusing to exceed the cap.

        The bound is in the WHERE clause rather than in Python because two
        people opening the same link at once would both read uses < max and
        both write uses + 1. The database decides, so only one wins.
        """
        stmt = (
            update(tables.TripInvite)
            .where(
                tables.TripInvite.id == invite_id,
                tables.TripInvite.revoked_at.is_(None),
                tables.TripInvite.uses < tables.TripInvite.max_uses,
                tables.TripInvite.expires_at > _now(),
            )
            .values(uses=tables.TripInvite.uses + 1)
            .returning(tables.TripInvite)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def revoke(self, invite_id: UUID) -> TripInvite | None:
        stmt = (
            update(tables.TripInvite)
            .where(tables.TripInvite.id == invite_id)
            .values(revoked_at=_now())
            .returning(tables.TripInvite)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def list_for_trip(self, trip_id: UUID) -> list[TripInvite]:
        return await self.list_where(
            tables.TripInvite.trip_id == trip_id,
            order_by=tables.TripInvite.created_at,
        )


class TripMessageRepository(BaseRepository[tables.TripMessage, TripMessage]):
    table = tables.TripMessage
    model = TripMessage

    column_aliases: ClassVar[dict[str, str]] = {}

    async def list_for_trip(self, trip_id: UUID, *, limit: int = 200) -> list[TripMessage]:
        """Thread history, oldest first, capped so a long thread cannot
        become an unbounded response."""
        messages = await self.list_where(
            tables.TripMessage.trip_id == trip_id,
            order_by=tables.TripMessage.created_at,
        )
        return messages[-limit:]


__all__ = [
    "AccountRepository",
    "AccountSessionRepository",
    "TripInviteRepository",
    "TripMessageRepository",
    "generate_invite_code",
]
