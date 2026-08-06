"""M1-2a: trip, traveler and constraint repositories against real Postgres.

Each test runs inside a transaction that is rolled back afterwards, so the
suite leaves no rows behind and tests do not see each other's data.
"""
from __future__ import annotations

from datetime import date

import pytest

from syncinerary.domain.models import Constraint, ConstraintKind, Traveler, Trip, TripStatus
from syncinerary.store.repositories import (
    ConstraintRepository,
    TravelerRepository,
    TripRepository,
)


def _hokkaido() -> Trip:
    return Trip(
        destination="Hokkaido",
        start_date=date(2026, 5, 21),
        end_date=date(2026, 5, 25),
        days=5,
    )


async def test_trip_round_trips(session):
    repo = TripRepository(session)
    saved = await repo.add(_hokkaido())

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.destination == "Hokkaido"
    assert fetched.days == 5
    assert fetched.status is TripStatus.SETUP
    assert fetched.start_date == date(2026, 5, 21)


async def test_trip_status_advances(session):
    repo = TripRepository(session)
    trip = await repo.add(_hokkaido())

    updated = await repo.set_status(trip.id, TripStatus.SWIPING)
    assert updated is not None
    assert updated.status is TripStatus.SWIPING

    reread = await repo.get(trip.id)
    assert reread is not None
    assert reread.status is TripStatus.SWIPING


async def test_traveler_profile_json_round_trips(session):
    """profile is `profile_json` in Postgres and holds arbitrary structure."""
    trip = await TripRepository(session).add(_hokkaido())
    repo = TravelerRepository(session)

    profile = {"dietary": ["vegetarian"], "mobility": "low", "interests": ["temples", "coffee"]}
    saved = await repo.add(
        Traveler(trip_id=trip.id, name="Gino", home_city="Taipei", profile=profile)
    )

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.profile == profile
    assert fetched.home_city == "Taipei"


async def test_traveler_count_drives_votes_total(session):
    trip = await TripRepository(session).add(_hokkaido())
    repo = TravelerRepository(session)
    for name in ("Ana", "Bo", "Cai"):
        await repo.add(Traveler(trip_id=trip.id, name=name))

    assert await repo.count_for_trip(trip.id) == 3
    # Ordered by name, so the list is stable across runs.
    assert [t.name for t in await repo.list_for_trip(trip.id)] == ["Ana", "Bo", "Cai"]


async def test_constraint_splits_group_level_from_per_traveler(session):
    """traveler_id NULL means group-level (CLAUDE.md §7)."""
    trip = await TripRepository(session).add(_hokkaido())
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    repo = ConstraintRepository(session)

    await repo.add(
        Constraint(
            trip_id=trip.id,
            traveler_id=None,
            type="budget_daily",
            value={"jpy": 15000},
            priority=5,
            kind=ConstraintKind.HARD,
        )
    )
    await repo.add(
        Constraint(
            trip_id=trip.id,
            traveler_id=traveler.id,
            type="dietary",
            value={"excludes": ["seafood"]},
            priority=9,
            kind=ConstraintKind.HARD,
        )
    )

    assert len(await repo.list_for_trip(trip.id)) == 2

    group = await repo.list_group_level(trip.id)
    assert len(group) == 1
    assert group[0].type == "budget_daily"
    assert group[0].value == {"jpy": 15000}

    personal = await repo.list_for_traveler(traveler.id)
    assert len(personal) == 1
    assert personal[0].value == {"excludes": ["seafood"]}


async def test_constraints_come_back_highest_priority_first(session):
    trip = await TripRepository(session).add(_hokkaido())
    repo = ConstraintRepository(session)
    for priority in (1, 9, 5):
        await repo.add(
            Constraint(
                trip_id=trip.id,
                type=f"p{priority}",
                value={},
                priority=priority,
                kind=ConstraintKind.SOFT,
            )
        )

    assert [c.priority for c in await repo.list_for_trip(trip.id)] == [9, 5, 1]


async def test_deleting_a_trip_cascades_to_its_children(session):
    trip = await TripRepository(session).add(_hokkaido())
    traveler_repo = TravelerRepository(session)
    await traveler_repo.add(Traveler(trip_id=trip.id, name="Ana"))

    assert await TripRepository(session).delete(trip.id) == 1
    await session.flush()
    assert await traveler_repo.list_for_trip(trip.id) == []


async def test_get_returns_none_for_unknown_id(session):
    from uuid import uuid4

    assert await TripRepository(session).get(uuid4()) is None


@pytest.mark.parametrize("kind", [ConstraintKind.HARD, ConstraintKind.SOFT])
async def test_constraint_kind_enum_round_trips(session, kind: ConstraintKind):
    trip = await TripRepository(session).add(_hokkaido())
    repo = ConstraintRepository(session)
    saved = await repo.add(
        Constraint(trip_id=trip.id, type="t", value={}, priority=1, kind=kind)
    )
    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.kind is kind
