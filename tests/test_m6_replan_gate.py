"""M6 approval gate transitions against real Postgres."""
from __future__ import annotations

from datetime import date

import pytest

from syncinerary.agents.rescue import ReplanAlreadyDecided, decide_replan
from syncinerary.domain.models import (
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
)


async def _pending_proposal(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            days=2,
        )
    )
    traveler = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Gino")
    )
    versions = ItineraryVersionRepository(session)
    active = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
        )
    )
    proposal = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=2,
            status=ItineraryStatus.PROPOSED,
            parent_version_id=active.id,
        )
    )
    event = await ReplanEventRepository(session).add(
        ReplanEvent(
            trip_id=trip.id,
            trigger_type=ReplanTrigger.WEATHER,
            proposed_version_id=proposal.id,
        )
    )
    return trip, traveler, active, proposal, event


async def test_approval_activates_proposal_and_supersedes_parent(session):
    trip, traveler, active, proposal, event = await _pending_proposal(session)

    decided = await decide_replan(
        session,
        trip_id=trip.id,
        event_id=event.id,
        traveler_id=traveler.id,
        approve=True,
    )

    versions = ItineraryVersionRepository(session)
    assert decided.status is ReplanStatus.APPROVED
    assert decided.decided_by == traveler.id
    assert decided.decided_at is not None
    assert (await versions.get(active.id)).status is ItineraryStatus.SUPERSEDED
    assert (await versions.get(proposal.id)).status is ItineraryStatus.ACTIVE
    assert (await versions.get_active(trip.id)).id == proposal.id


async def test_rejection_keeps_parent_active_and_rejects_proposal(session):
    trip, traveler, active, proposal, event = await _pending_proposal(session)

    decided = await decide_replan(
        session,
        trip_id=trip.id,
        event_id=event.id,
        traveler_id=traveler.id,
        approve=False,
    )

    versions = ItineraryVersionRepository(session)
    assert decided.status is ReplanStatus.REJECTED
    assert (await versions.get(active.id)).status is ItineraryStatus.ACTIVE
    assert (await versions.get(proposal.id)).status is ItineraryStatus.REJECTED
    assert (await versions.get_active(trip.id)).id == active.id


async def test_a_decided_proposal_cannot_be_decided_again(session):
    trip, traveler, _active, _proposal, event = await _pending_proposal(session)
    await decide_replan(
        session,
        trip_id=trip.id,
        event_id=event.id,
        traveler_id=traveler.id,
        approve=False,
    )

    with pytest.raises(ReplanAlreadyDecided):
        await decide_replan(
            session,
            trip_id=trip.id,
            event_id=event.id,
            traveler_id=traveler.id,
            approve=True,
        )
