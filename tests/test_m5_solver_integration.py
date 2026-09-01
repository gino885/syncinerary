"""M5 handoff from day assignment into the existing route solver."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from syncinerary.agents.solver.stage2_route import solve_full_routes
from syncinerary.domain.models import CandidatePlace, CandidateType, Trip, TripState
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitMatrix,
    TransitMode,
)
from syncinerary.tools.weather import WeatherForecast


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


def _place(name: str) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=43.06,
        lng=141.35,
        hours_by_weekday={
            weekday: [[8, 21]]
            for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        },
        fatigue_cost=3,
    )


async def test_stage2_keeps_must_go_and_pinned_stage1_assignments():
    trip = Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        days=2,
    )
    must_go = _place("Must go")
    pinned = _place("Pinned")
    extras = [_place(f"Extra {index}") for index in range(4)]

    result = await solve_full_routes(
        TripState(trip=trip),
        [must_go, pinned, *extras],
        StubTransit(),
        weather=WeatherForecast(),
        must_go_ids={must_go.id},
        pinned_days={pinned.id: 1},
    )

    day_by_id = {
        stop.candidate_id: route.day
        for route in result.routes
        for stop in route.stops
    }
    assert day_by_id[must_go.id] in {0, 1}
    assert day_by_id[pinned.id] == 1
    assert all(
        sum(
            candidate.fatigue_cost
            for candidate in [must_go, pinned, *extras]
            if candidate.id in {stop.candidate_id for stop in route.stops}
        )
        <= 8
        for route in result.routes
    )


async def test_typical_low_effort_day_keeps_five_stops():
    trip = Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        days=1,
    )
    candidates = [
        _place(f"Stop {index}").model_copy(update={"fatigue_cost": 1})
        for index in range(5)
    ]

    result = await solve_full_routes(
        TripState(trip=trip),
        candidates,
        StubTransit(),
        weather=WeatherForecast(),
    )

    assert len(result.routes[0].stops) == 5
