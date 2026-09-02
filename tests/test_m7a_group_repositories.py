"""M7a: accounts, sessions, and invites against real Postgres.

Covers the parts that are not obvious from reading the models: the invite use
cap under concurrency, expiry enforced on read, and revocation.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from syncinerary.domain.models import Traveler, Trip
from syncinerary.store.repositories import (
    AccountRepository,
    AccountSessionRepository,
    TravelerRepository,
    TripInviteRepository,
    TripRepository,
)

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(UTC)


async def _trip_with_owner(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            cities=["Sapporo"],
            country="Japan",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    owner = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Gino")
    )
    return trip, owner


async def test_signing_in_twice_keeps_one_identity(session):
    accounts = AccountRepository(session)
    first = await accounts.upsert_by_handle(display_name="Gino", handle="gino")
    second = await accounts.upsert_by_handle(display_name="Gino Again", handle="GINO")

    assert second.id == first.id, "handle is case-insensitive, so this is one person"


async def test_an_expired_session_authenticates_nobody(session):
    account = await AccountRepository(session).upsert_by_handle(
        display_name="Gino", handle="gino"
    )
    sessions = AccountSessionRepository(session)
    issued = await sessions.issue(account.id)

    assert await sessions.resolve(issued.token) is not None

    # Expiry is checked on read, so a stale row cannot authenticate even when
    # nothing has swept it up.
    import sqlalchemy as sa

    from syncinerary.store import tables

    await session.execute(
        sa.update(tables.AccountSession)
        .where(tables.AccountSession.token == issued.token)
        .values(expires_at=_now() - timedelta(seconds=1))
    )

    assert await sessions.resolve(issued.token) is None


async def test_an_invite_cannot_be_used_past_its_cap(session):
    trip, owner = await _trip_with_owner(session)
    invites = TripInviteRepository(session)
    invite = await invites.create_for_trip(
        trip_id=trip.id, created_by_traveler_id=owner.id, max_uses=2
    )

    assert await invites.claim(invite.id) is not None
    assert await invites.claim(invite.id) is not None
    # The bound lives in the UPDATE's WHERE clause, so two people opening the
    # same link at once cannot both read uses < max and both write uses + 1.
    assert await invites.claim(invite.id) is None


async def test_a_revoked_invite_stops_working_immediately(session):
    trip, owner = await _trip_with_owner(session)
    invites = TripInviteRepository(session)
    invite = await invites.create_for_trip(
        trip_id=trip.id, created_by_traveler_id=owner.id
    )

    await invites.revoke(invite.id)

    assert await invites.claim(invite.id) is None


async def test_an_expired_invite_stops_working(session):
    trip, owner = await _trip_with_owner(session)
    invites = TripInviteRepository(session)
    invite = await invites.create_for_trip(
        trip_id=trip.id, created_by_traveler_id=owner.id
    )

    import sqlalchemy as sa

    from syncinerary.store import tables

    await session.execute(
        sa.update(tables.TripInvite)
        .where(tables.TripInvite.id == invite.id)
        .values(expires_at=_now() - timedelta(seconds=1))
    )

    assert await invites.claim(invite.id) is None


async def test_invite_codes_avoid_ambiguous_characters(session):
    """A code gets read aloud and retyped from a screenshot, so I/L/O/U and
    0/1 would send someone to the wrong trip."""
    from syncinerary.store.repositories.group import generate_invite_code

    codes = "".join(generate_invite_code() for _ in range(50))

    assert not set(codes) & set("ILOU01")


async def test_one_account_joins_a_trip_once(session):
    """A double-tapped invite link must not create a second traveler whose
    votes would then be counted twice."""
    import sqlalchemy.exc

    trip, _ = await _trip_with_owner(session)
    account = await AccountRepository(session).upsert_by_handle(
        display_name="Mei", handle="mei"
    )
    travelers = TravelerRepository(session)
    await travelers.add(
        Traveler(trip_id=trip.id, name="Mei", account_id=account.id)
    )

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await travelers.add(
            Traveler(trip_id=trip.id, name="Mei", account_id=account.id)
        )
