"""M6 rescue proposal behavior without external API calls."""
from __future__ import annotations

from datetime import date, time
from time import perf_counter
from uuid import UUID

import pytest

from syncinerary.agents.rescue import (
    ReplanConflict,
    create_replan_proposal,
    select_affected_nodes,
)
from syncinerary.agents.rescue_alternatives import AlternativeSearchRequest
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


class StubAlternatives:
    def __init__(self, candidates: list[CandidatePlace] | None = None) -> None:
        self.candidates = candidates or []
        self.requests: list[AlternativeSearchRequest] = []

    async def discover(
        self,
        request: AlternativeSearchRequest,
    ) -> list[CandidatePlace]:
        self.requests.append(request)
        return self.candidates


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
                fixed=True,
                lock_reason="paid_ticket",
            ),
        ]
    )

    discovered = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.ATTRACTION,
        name_canonical="Fresh Sapporo Gallery",
        lat=43.062,
        lng=141.352,
        duration_estimate_min=60,
        fatigue_cost=1,
        hours_by_weekday={
            weekday: [[8, 20]]
            for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        },
    )
    alternatives = StubAlternatives([discovered])
    proposal = await create_replan_proposal(
        session,
        trip_id=trip.id,
        trigger_type=ReplanTrigger.PLACE_CLOSED,
        trigger_payload={"node_id": str(active_nodes[0].id)},
        transit_provider=StubTransit(),
        alternative_provider=alternatives,
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
    kept = next(node for node in proposed_nodes if node.candidate_id == places[1].id)
    assert kept.fixed is True
    assert kept.lock_reason == "paid_ticket"
    assert kept.start_time == time(11)
    assert kept.end_time == time(12)
    assert (await CandidatePlaceRepository(session).get(discovered.id)) is not None
    assert alternatives.requests[0].needed_at == time(9)

    trace = proposal.event.trace_json
    assert trace["trigger"]["type"] == "place_closed"
    chosen = [item for item in trace["alternatives_considered"] if item["chosen"]]
    assert chosen
    assert str(discovered.id) in {
        item["candidate_id"] for item in trace["alternatives_considered"]
    }
    assert all("km" in item["reason"] and "fatigue" in item["reason"] for item in chosen)
    assert await ReplanEventRepository(session).list_pending(trip.id) == [proposal.event]


async def _seed_scheduled_trip(session, *, days: int):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            cities=["Sapporo"],
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, days),
            days=days,
        )
    )
    places = await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=f"Day {day + 1} stop {stop + 1}",
                lat=43.06 + day / 100 + stop / 1000,
                lng=141.35 + day / 100 + stop / 1000,
                duration_estimate_min=60,
                fatigue_cost=1,
                weather_dependent=stop == 0,
                hours_by_weekday={
                    weekday: [[8, 20]]
                    for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                },
                enrichment={"city": "Sapporo"},
            )
            for day in range(days)
            for stop in range(5)
        ]
    )
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
        )
    )
    nodes = await ItineraryNodeRepository(session).add_many(
        [
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[day * 5 + stop].id,
                day=day,
                start_time=(time(9), time(11), time(14))[stop],
                end_time=(time(10), time(12), time(15))[stop],
            )
            for day in range(days)
            for stop in range(3)
        ]
    )
    return trip, version, nodes


@pytest.mark.parametrize(
    "trigger",
    [
        ReplanTrigger.RESERVATION_CANCELLED,
        ReplanTrigger.TRANSIT_DELAY,
        ReplanTrigger.OVERSLEPT,
        ReplanTrigger.PLACE_CLOSED,
        ReplanTrigger.WEATHER,
    ],
)
async def test_each_main_trigger_creates_a_pending_proposal(session, trigger):
    trip, active, nodes = await _seed_scheduled_trip(session, days=1)
    if trigger is ReplanTrigger.OVERSLEPT:
        payload = {"day": 0, "at": "10:30"}
    elif trigger is ReplanTrigger.WEATHER:
        payload = {"day": 0, "condition": "heavy rain"}
    else:
        payload = {"node_id": str(nodes[0].id)}
        if trigger is ReplanTrigger.TRANSIT_DELAY:
            payload["delay_minutes"] = 30

    proposal = await create_replan_proposal(
        session,
        trip_id=trip.id,
        trigger_type=trigger,
        trigger_payload=payload,
        transit_provider=StubTransit(),
        alternative_provider=StubAlternatives(),
    )

    assert proposal.event.trigger_type is trigger
    assert proposal.event.status is ReplanStatus.PENDING
    assert proposal.version.status is ItineraryStatus.PROPOSED
    assert proposal.version.parent_version_id == active.id
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == active.id


async def test_five_day_replan_finishes_under_ten_seconds_without_provider_latency(session):
    trip, _active, nodes = await _seed_scheduled_trip(session, days=5)

    started = perf_counter()
    proposal = await create_replan_proposal(
        session,
        trip_id=trip.id,
        trigger_type=ReplanTrigger.PLACE_CLOSED,
        trigger_payload={"node_id": str(nodes[6].id)},
        transit_provider=StubTransit(),
        alternative_provider=StubAlternatives(),
    )
    elapsed = perf_counter() - started

    assert proposal.version.status is ItineraryStatus.PROPOSED
    assert elapsed < 10


async def test_a_second_disruption_waits_for_the_pending_decision(session):
    trip, _active, nodes = await _seed_scheduled_trip(session, days=1)
    kwargs = {
        "session": session,
        "trip_id": trip.id,
        "trigger_type": ReplanTrigger.PLACE_CLOSED,
        "trigger_payload": {"node_id": str(nodes[0].id)},
        "transit_provider": StubTransit(),
        "alternative_provider": StubAlternatives(),
    }
    await create_replan_proposal(**kwargs)

    with pytest.raises(ReplanConflict, match="pending replan"):
        await create_replan_proposal(**kwargs)
