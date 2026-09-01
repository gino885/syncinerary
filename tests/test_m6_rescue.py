"""M6 rescue proposal behavior without external API calls."""
from __future__ import annotations

from datetime import date, time
from uuid import UUID

import pytest

from syncinerary.agents.rescue import create_replan_proposal, select_affected_nodes
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanStatus,
    ReplanTrigger,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TripRepository,
)
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitMatrix,
    TransitMode,
)


class StubTransit:
    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        return TransitMatrix(
            legs=[
                TransitDuration(
                    origin=origin,
                    destination=destination,
                    mode=TransitMode.WALKING,
                    departure_window=request.departure_window,
                    duration_seconds=600,
                    duration_minutes=10,
                )
                for origin in request.locations
                for destination in request.locations
                if origin != destination
            ]
        )


def _node(number: int, *, day: int, start: int) -> ItineraryNode:
    return ItineraryNode(
        id=UUID(f"10000000-0000-0000-0000-{number:012d}"),
        version_id=UUID("20000000-0000-0000-0000-000000000001"),
        candidate_id=UUID(f"30000000-0000-0000-0000-{number:012d}"),
        day=day,
        start_time=time(start),
        end_time=time(start + 1),
    )


@pytest.mark.parametrize(
    ("trigger", "payload", "expected"),
    [
        (ReplanTrigger.RESERVATION_CANCELLED, {"node_id": str(_node(1, day=0, start=9).id)}, [1]),
        (ReplanTrigger.TRANSIT_DELAY, {"node_id": str(_node(2, day=0, start=11).id), "delay_minutes": 45}, [2]),
        (ReplanTrigger.OVERSLEPT, {"day": 0, "at": "10:30"}, [1]),
        (ReplanTrigger.PLACE_CLOSED, {"node_id": str(_node(2, day=0, start=11).id)}, [2]),
        (ReplanTrigger.WEATHER, {"day": 0}, [2]),
        (ReplanTrigger.OTHER, {"affected_node_ids": [str(_node(3, day=1, start=9).id)]}, [3]),
    ],
)
def test_each_trigger_selects_only_directly_affected_nodes(trigger, payload, expected):
    nodes = [
        _node(1, day=0, start=9),
        _node(2, day=0, start=11),
        _node(3, day=1, start=9),
    ]
    candidates = {
        nodes[0].candidate_id: CandidatePlace(
            id=nodes[0].candidate_id,
            trip_id=UUID("40000000-0000-0000-0000-000000000001"),
            type=CandidateType.ATTRACTION,
            name_canonical="Indoor",
            lat=43.06,
            lng=141.35,
        ),
        nodes[1].candidate_id: CandidatePlace(
            id=nodes[1].candidate_id,
            trip_id=UUID("40000000-0000-0000-0000-000000000001"),
            type=CandidateType.ATTRACTION,
            name_canonical="Outdoor",
            lat=43.06,
            lng=141.35,
            weather_dependent=True,
        ),
    }

    affected = select_affected_nodes(trigger, payload, nodes, candidates)

    assert [int(str(node.id)[-12:]) for node in affected] == expected


async def test_closed_place_creates_pending_proposal_without_changing_active_version(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            cities=["Sapporo"],
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            days=1,
        )
    )
    places = await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=name,
                lat=43.06 + index / 1000,
                lng=141.35 + index / 1000,
                duration_estimate_min=60,
                fatigue_cost=1,
                hours_by_weekday={weekday: [[8, 20]] for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
            )
            for index, name in enumerate(("Closed stop", "Kept stop", "Nearby museum", "Local market"))
        ]
    )
    versions = ItineraryVersionRepository(session)
    active = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
        )
    )
    active_nodes = await ItineraryNodeRepository(session).add_many(
        [
            ItineraryNode(
                version_id=active.id,
                candidate_id=places[0].id,
                day=0,
                start_time=time(9),
                end_time=time(10),
            ),
            ItineraryNode(
                version_id=active.id,
                candidate_id=places[1].id,
                day=0,
                start_time=time(11),
                end_time=time(12),
            ),
        ]
    )

    proposal = await create_replan_proposal(
        session,
        trip_id=trip.id,
        trigger_type=ReplanTrigger.PLACE_CLOSED,
        trigger_payload={"node_id": str(active_nodes[0].id)},
        transit_provider=StubTransit(),
    )

    assert proposal.event.status is ReplanStatus.PENDING
    assert proposal.version.status is ItineraryStatus.PROPOSED
    assert proposal.version.parent_version_id == active.id
    assert (await versions.get_active(trip.id)).id == active.id
    assert proposal.event.affected_node_ids == [active_nodes[0].id]

    proposed_nodes = await ItineraryNodeRepository(session).list_for_version(
        proposal.version.id
    )
    proposed_candidates = {node.candidate_id for node in proposed_nodes}
    assert places[0].id not in proposed_candidates
    assert places[1].id in proposed_candidates
    assert proposed_candidates & {places[2].id, places[3].id}

    trace = proposal.event.trace_json
    assert trace["trigger"]["type"] == "place_closed"
    chosen = [item for item in trace["alternatives_considered"] if item["chosen"]]
    assert chosen
    assert all("km" in item["reason"] and "fatigue" in item["reason"] for item in chosen)
    assert await ReplanEventRepository(session).list_pending(trip.id) == [proposal.event]
