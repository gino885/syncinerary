"""M1-2c: shortlist and itinerary repositories against real Postgres.

The append-only rule in CLAUDE.md §7 is what most of these assert. F4's diff
and F2's replay both read the version chain, so a version that could be
edited in place would break both silently.
"""
from __future__ import annotations

from datetime import date, time

import pytest
from sqlalchemy.exc import IntegrityError

from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ShortlistState,
    Trip,
    WishlistNotPlaced,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ShortlistStateRepository,
    TripRepository,
    WishlistNotPlacedRepository,
)


async def _trip(session) -> Trip:
    return await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )


async def _places(session, trip_id, count: int) -> list[CandidatePlace]:
    return await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip_id,
                type=CandidateType.ATTRACTION,
                name_canonical=f"Place {i}",
                lat=43.0 + i / 100,
                lng=141.3 + i / 100,
            )
            for i in range(count)
        ]
    )


async def test_shortlist_round_trips_with_uuid_lists(session):
    trip = await _trip(session)
    places = await _places(session, trip.id, 5)
    repo = ShortlistStateRepository(session)

    saved = await repo.upsert(
        ShortlistState(
            trip_id=trip.id,
            selected_candidate_ids=[p.id for p in places[:3]],
            must_go_candidate_ids=[places[0].id],
            wishlist_excluded_ids=[p.id for p in places[3:]],
        )
    )
    assert saved.trip_id == trip.id

    fetched = await repo.get_for_trip(trip.id)
    assert fetched is not None
    # UUIDs went into JSONB as strings and must come back as UUIDs.
    assert fetched.selected_candidate_ids == [p.id for p in places[:3]]
    assert fetched.must_go_candidate_ids == [places[0].id]
    assert fetched.wishlist_excluded_ids == [places[3].id, places[4].id]


async def test_shortlist_selection_order_is_preserved(session):
    """§7 calls selected_candidate_ids ordered, and the solver relies on it."""
    trip = await _trip(session)
    places = await _places(session, trip.id, 6)
    repo = ShortlistStateRepository(session)

    scrambled = [places[4].id, places[1].id, places[5].id, places[0].id]
    await repo.upsert(ShortlistState(trip_id=trip.id, selected_candidate_ids=scrambled))

    fetched = await repo.get_for_trip(trip.id)
    assert fetched is not None
    assert fetched.selected_candidate_ids == scrambled


async def test_rebuilding_the_shortlist_overwrites_rather_than_collides(session):
    trip = await _trip(session)
    places = await _places(session, trip.id, 4)
    repo = ShortlistStateRepository(session)

    await repo.upsert(
        ShortlistState(trip_id=trip.id, selected_candidate_ids=[places[0].id, places[1].id])
    )
    await repo.upsert(ShortlistState(trip_id=trip.id, selected_candidate_ids=[places[2].id]))

    fetched = await repo.get_for_trip(trip.id)
    assert fetched is not None
    assert fetched.selected_candidate_ids == [places[2].id]


async def test_shortlist_is_absent_before_it_is_built(session):
    trip = await _trip(session)
    assert await ShortlistStateRepository(session).get_for_trip(trip.id) is None


async def test_version_numbers_increment_and_never_reuse(session):
    trip = await _trip(session)
    repo = ItineraryVersionRepository(session)

    assert await repo.next_version_no(trip.id) == 1
    v1 = await repo.add(ItineraryVersion(trip_id=trip.id, version_no=1))
    assert await repo.next_version_no(trip.id) == 2

    v2 = await repo.add(
        ItineraryVersion(trip_id=trip.id, version_no=2, parent_version_id=v1.id)
    )
    assert v2.parent_version_id == v1.id
    assert await repo.next_version_no(trip.id) == 3


async def test_version_numbers_are_unique_per_trip(session):
    trip = await _trip(session)
    repo = ItineraryVersionRepository(session)
    await repo.add(ItineraryVersion(trip_id=trip.id, version_no=1))

    with pytest.raises(IntegrityError):
        await repo.add(ItineraryVersion(trip_id=trip.id, version_no=1))


async def test_approval_promotes_the_proposal_and_supersedes_its_parent(session):
    """The §12.2 HITL gate transition. Status is the one mutable field."""
    trip = await _trip(session)
    repo = ItineraryVersionRepository(session)

    active = await repo.add(
        ItineraryVersion(trip_id=trip.id, version_no=1, status=ItineraryStatus.ACTIVE)
    )
    proposed = await repo.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=2,
            status=ItineraryStatus.PROPOSED,
            parent_version_id=active.id,
        )
    )
    assert (await repo.get_active(trip.id)).id == active.id

    await repo.set_status(proposed.id, ItineraryStatus.ACTIVE)
    await repo.set_status(active.id, ItineraryStatus.SUPERSEDED)

    assert (await repo.get_active(trip.id)).id == proposed.id
    assert (await repo.get(active.id)).status is ItineraryStatus.SUPERSEDED
    # Both versions still exist. Nothing was overwritten.
    assert len(await repo.list_for_trip(trip.id)) == 2


async def test_objective_breakdown_round_trips(session):
    trip = await _trip(session)
    repo = ItineraryVersionRepository(session)
    saved = await repo.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            objective_breakdown={"transit_min": 214.0, "vote_score": 18.5},
        )
    )
    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.objective_breakdown == {"transit_min": 214.0, "vote_score": 18.5}


async def test_nodes_come_back_in_visit_order(session):
    trip = await _trip(session)
    places = await _places(session, trip.id, 4)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    repo = ItineraryNodeRepository(session)

    # Inserted deliberately out of order.
    await repo.add_many(
        [
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[2].id,
                day=1,
                start_time=time(9, 0),
                end_time=time(10, 30),
            ),
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[0].id,
                day=0,
                start_time=time(14, 0),
                end_time=time(15, 0),
            ),
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[1].id,
                day=0,
                start_time=time(9, 30),
                end_time=time(11, 0),
            ),
        ]
    )

    ordered = await repo.list_for_version(version.id)
    assert [(n.day, n.start_time) for n in ordered] == [
        (0, time(9, 30)),
        (0, time(14, 0)),
        (1, time(9, 0)),
    ]


async def test_one_day_can_be_read_alone(session):
    """§11.3: stage 2 runs per day so F4 can replan one day in isolation."""
    trip = await _trip(session)
    places = await _places(session, trip.id, 3)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    repo = ItineraryNodeRepository(session)
    await repo.add_many(
        [
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[i].id,
                day=day,
                start_time=time(9 + i, 0),
                end_time=time(10 + i, 0),
            )
            for i, day in enumerate((0, 0, 2))
        ]
    )

    assert len(await repo.list_for_day(version.id, 0)) == 2
    assert len(await repo.list_for_day(version.id, 2)) == 1
    assert await repo.list_for_day(version.id, 1) == []


async def test_node_transit_and_lock_fields_round_trip(session):
    trip = await _trip(session)
    places = await _places(session, trip.id, 1)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    repo = ItineraryNodeRepository(session)

    saved = await repo.add(
        ItineraryNode(
            version_id=version.id,
            candidate_id=places[0].id,
            day=0,
            start_time=time(18, 30),
            end_time=time(20, 0),
            fixed=True,
            lock_reason="reservation",
            transit_from_prev_min=37,
            transit_from_prev_mode="transit",
            notes_for_travelers={str(trip.id): "self-handles meal"},
        )
    )
    fetched = (await repo.list_for_version(version.id))[0]
    assert fetched.id == saved.id
    assert fetched.fixed is True
    assert fetched.lock_reason == "reservation"
    assert fetched.transit_from_prev_min == 37
    assert fetched.transit_from_prev_mode == "transit"
    assert fetched.notes_for_travelers == {str(trip.id): "self-handles meal"}


async def test_a_candidate_referenced_by_a_node_cannot_be_deleted(session):
    """RESTRICT, not CASCADE: deleting history must fail loudly."""
    trip = await _trip(session)
    places = await _places(session, trip.id, 1)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    await ItineraryNodeRepository(session).add(
        ItineraryNode(
            version_id=version.id,
            candidate_id=places[0].id,
            day=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
    )

    with pytest.raises(IntegrityError):
        await CandidatePlaceRepository(session).delete(places[0].id)
        await session.flush()


async def test_wishlist_records_a_reason_per_unplaced_card(session):
    """§10.3: answer "why did my favourite not get in" up front."""
    trip = await _trip(session)
    places = await _places(session, trip.id, 2)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    repo = WishlistNotPlacedRepository(session)

    await repo.add_many(
        [
            WishlistNotPlaced(
                version_id=version.id,
                candidate_id=places[0].id,
                reason_code="fatigue_overflow",
                reason_text="Day 4 was already at the fatigue cap",
            ),
            WishlistNotPlaced(
                version_id=version.id,
                candidate_id=places[1].id,
                reason_code="closed_on_available_days",
                reason_text="Closed Tuesday and Wednesday, the only days with room",
            ),
        ]
    )

    entries = await repo.list_for_version(version.id)
    assert len(entries) == 2
    assert {e.reason_code for e in entries} == {"fatigue_overflow", "closed_on_available_days"}


async def test_deleting_a_version_takes_its_nodes_and_wishlist_with_it(session):
    """Nodes have no life of their own outside their version."""
    trip = await _trip(session)
    places = await _places(session, trip.id, 1)
    versions = ItineraryVersionRepository(session)
    version = await versions.add(ItineraryVersion(trip_id=trip.id, version_no=1))
    nodes = ItineraryNodeRepository(session)
    wishlist = WishlistNotPlacedRepository(session)

    await nodes.add(
        ItineraryNode(
            version_id=version.id,
            candidate_id=places[0].id,
            day=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
    )
    await wishlist.add(
        WishlistNotPlaced(
            version_id=version.id,
            candidate_id=places[0].id,
            reason_code="no_day_fit",
            reason_text="No day had room",
        )
    )

    assert await versions.delete(version.id) == 1
    await session.flush()
    assert await nodes.list_for_version(version.id) == []
    assert await wishlist.list_for_version(version.id) == []
