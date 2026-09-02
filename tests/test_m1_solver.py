"""M1-7b: deterministic CP-SAT routing and append-only persistence."""
from __future__ import annotations

import ast
from contextlib import asynccontextmanager
from datetime import date, time
from itertools import pairwise
from pathlib import Path
from typing import Self
from uuid import uuid4

from syncinerary.agents.solver import stage2_route as solver_module
from syncinerary.agents.solver.stage1_days import chunk_evenly
from syncinerary.agents.solver.stage2_route import (
    SolverOptions,
    solve_day,
    solve_routes,
    solver_node,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryStatus,
    ShortlistState,
    Trip,
    TripState,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ShortlistStateRepository,
    TripRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
)


def _trip(days: int = 1) -> Trip:
    return Trip(
        destination="Hokkaido",
        start_date=date(2026, 5, 21),  # Thursday
        end_date=date(2026, 5, 20 + days),
        days=days,
    )


def _place(
    name: str,
    lat: float,
    lng: float,
    *,
    hours: list[list[int]] | None = None,
    duration: int = 60,
) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=lat,
        lng=lng,
        hours_by_weekday={"thu": [[8, 20]] if hours is None else hours},
        duration_estimate_min=duration,
    )


def _location(candidate: CandidatePlace) -> TransitLocation:
    return TransitLocation(lat=candidate.lat, lng=candidate.lng)


def _matrix(
    candidates: list[CandidatePlace],
    minutes: dict[tuple[str, str], int] | None = None,
) -> TransitMatrix:
    minutes = minutes or {}
    legs = []
    for origin in candidates:
        for destination in candidates:
            if origin.id == destination.id:
                continue
            duration = minutes.get((origin.name_canonical, destination.name_canonical), 10)
            legs.append(
                TransitDuration(
                    origin=_location(origin),
                    destination=_location(destination),
                    mode=TransitMode.WALKING,
                    departure_window="test",
                    duration_seconds=duration * 60,
                    duration_minutes=duration,
                )
            )
    return TransitMatrix(legs=legs)


class StubTransitClient:
    def __init__(self, minutes: int = 10) -> None:
        self.minutes = minutes
        self.requests: list[PairwiseTransitRequest] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.requests.append(request)
        legs = [
            TransitDuration(
                origin=origin,
                destination=destination,
                mode=TransitMode.WALKING,
                departure_window=request.departure_window,
                duration_seconds=self.minutes * 60,
                duration_minutes=self.minutes,
            )
            for origin in request.locations
            for destination in request.locations
            if origin != destination
        ]
        return TransitMatrix(legs=legs)


class NearbyOnlyTransitClient:
    """A transit graph where each local cluster is routable on its own."""

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        legs = [
            TransitDuration(
                origin=origin,
                destination=destination,
                mode=TransitMode.WALKING,
                departure_window=request.departure_window,
                duration_seconds=10 * 60,
                duration_minutes=10,
            )
            for origin in request.locations
            for destination in request.locations
            if origin != destination and abs(origin.lat - destination.lat) < 0.1
        ]
        return TransitMatrix(legs=legs)


def _use_test_session(monkeypatch, session) -> None:
    @asynccontextmanager
    async def test_scope():
        yield session

    monkeypatch.setattr(solver_module, "session_scope", test_scope)


# ----- placeholder day assignment -----


def test_chunk_evenly_keeps_score_order_and_balances_days():
    buckets = chunk_evenly(list(range(13)), 5)
    assert [len(bucket) for bucket in buckets] == [3, 3, 3, 2, 2]
    assert [item for bucket in buckets for item in bucket] == list(range(13))


def test_five_day_thirty_card_shortlist_becomes_six_per_day():
    assert [len(bucket) for bucket in chunk_evenly(list(range(30)), 5)] == [6] * 5


async def test_day_assignment_groups_nearby_places_to_avoid_sparse_days():
    hours = {"thu": [[8, 20]], "fri": [[8, 20]]}
    north_one = _place("North one", 44.00, 142.00).model_copy(
        update={"hours_by_weekday": hours}
    )
    south_one = _place("South one", 42.00, 140.00).model_copy(
        update={"hours_by_weekday": hours}
    )
    north_two = _place("North two", 44.01, 142.01).model_copy(
        update={"hours_by_weekday": hours}
    )
    south_two = _place("South two", 42.01, 140.01).model_copy(
        update={"hours_by_weekday": hours}
    )

    result = await solve_routes(
        TripState(trip=_trip(days=2)),
        [north_one, south_one, north_two, south_two],
        NearbyOnlyTransitClient(),
    )

    assert [len(route.stops) for route in result.routes] == [2, 2]
    assert result.placed_count == 4


# ----- CP-SAT day route -----


def test_solver_places_stops_inside_real_weekday_opening_hours():
    museum = _place("Museum", 43.06, 141.35, hours=[[10, 17]], duration=90)
    park = _place("Park", 43.07, 141.36, hours=[[8, 20]], duration=60)

    route = solve_day(
        [museum, park],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=_matrix([museum, park]),
    )

    assert len(route.stops) == 2
    by_id = {stop.candidate_id: stop for stop in route.stops}
    assert by_id[museum.id].start_minute >= 10 * 60
    assert by_id[museum.id].end_minute <= 17 * 60
    assert all(8 * 60 <= stop.start_minute < stop.end_minute <= 20 * 60 for stop in route.stops)


def test_solver_minimizes_total_transit_after_maximizing_placements():
    a = _place("A", 43.00, 141.00)
    b = _place("B", 43.01, 141.01)
    c = _place("C", 43.02, 141.02)
    minutes = {
        ("A", "B"): 5,
        ("B", "A"): 5,
        ("B", "C"): 5,
        ("C", "B"): 5,
        ("A", "C"): 60,
        ("C", "A"): 60,
    }

    route = solve_day(
        [a, b, c],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=_matrix([a, b, c], minutes),
    )

    assert len(route.stops) == 3
    assert route.total_transit_minutes == 10
    assert [stop.transit_from_prev_min for stop in route.stops] == [0, 5, 5]
    for previous, current in pairwise(route.stops):
        assert current.start_minute >= previous.end_minute + current.transit_from_prev_min


def test_solver_preserves_transitous_attribution_on_the_scheduled_leg():
    first = _place("First", 43.06, 141.35)
    second = _place("Second", 43.10, 141.40)
    matrix = _matrix([first, second])
    matrix = matrix.model_copy(
        update={
            "legs": [
                leg.model_copy(
                    update={"mode": TransitMode.TRANSIT, "provider": "transitous"}
                )
                for leg in matrix.legs
            ]
        }
    )

    route = solve_day(
        [first, second],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=matrix,
    )

    assert route.stops[1].transit_from_prev_mode == "transit_transitous"


def test_closed_candidate_is_unplaced_with_specific_reason():
    closed = _place("Closed Thursdays", 43.06, 141.35, hours=[])

    route = solve_day(
        [closed],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=TransitMatrix(legs=[]),
    )

    assert route.stops == []
    assert route.unplaced[0].candidate_id == closed.id
    assert route.unplaced[0].reason_code == "closed_on_available_days"


def test_day_duration_cap_can_force_a_shortlisted_card_out():
    first = _place("Long A", 43.06, 141.35, duration=600)
    second = _place("Long B", 43.07, 141.36, duration=600)

    route = solve_day(
        [first, second],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=_matrix([first, second]),
    )

    assert len(route.stops) == 1
    assert len(route.unplaced) == 1
    assert route.unplaced[0].reason_code == "no_day_fit"


def test_user_adjustable_window_is_an_explicit_solver_option():
    place = _place("Late Start", 43.06, 141.35, hours=[[0, 24]])
    options = SolverOptions(day_start=time(10), day_end=time(22))

    route = solve_day(
        [place],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=TransitMatrix(legs=[]),
        options=options,
    )

    assert route.stops[0].start_minute == 10 * 60


def test_solver_output_is_deterministic():
    places = [
        _place("A", 43.00, 141.00),
        _place("B", 43.01, 141.01),
        _place("C", 43.02, 141.02),
    ]
    matrix = _matrix(places)
    renders = {
        solve_day(
            places,
            day=0,
            trip_date=date(2026, 5, 21),
            transit=matrix,
        ).model_dump_json()
        for _ in range(5)
    }
    assert len(renders) == 1


# ----- node persistence -----


async def test_solver_node_persists_active_append_only_itinerary(session, monkeypatch):
    trip = await TripRepository(session).add(_trip())
    raw_places = [
        _place("A", 43.00, 141.00),
        _place("B", 43.01, 141.01),
        _place("Closed", 43.02, 141.02, hours=[]),
    ]
    places = await CandidatePlaceRepository(session).add_many(
        [place.model_copy(update={"trip_id": trip.id}) for place in raw_places]
    )
    shortlist = await ShortlistStateRepository(session).upsert(
        ShortlistState(trip_id=trip.id, selected_candidate_ids=[place.id for place in places])
    )
    state = TripState(trip=trip, shortlist=shortlist)
    before = state.model_dump(mode="json")
    transit = StubTransitClient()
    _use_test_session(monkeypatch, session)
    monkeypatch.setattr(solver_module, "_make_transit_client", lambda: transit)

    first_result = await solver_node(state)
    first = first_result["current_itinerary"]
    first_nodes = await ItineraryNodeRepository(session).list_for_version(first.id)
    first_wishlist = await WishlistNotPlacedRepository(session).list_for_version(first.id)

    assert state.model_dump(mode="json") == before
    assert first.version_no == 1
    assert first.status is ItineraryStatus.ACTIVE
    assert len(first_nodes) == 2
    assert [item.reason_code for item in first_wishlist] == ["closed_on_available_days"]
    assert transit.requests[0].departure_window == "2026-05-21-0800"

    second_result = await solver_node(state)
    second = second_result["current_itinerary"]
    versions = await ItineraryVersionRepository(session).list_for_trip(trip.id)

    assert second.version_no == 2
    assert second.parent_version_id == first.id
    assert [version.status for version in versions] == [
        ItineraryStatus.SUPERSEDED,
        ItineraryStatus.ACTIVE,
    ]
    assert len(await ItineraryNodeRepository(session).list_for_version(first.id)) == 2


async def test_solver_node_never_schedules_a_card_the_group_excluded(
    session,
    monkeypatch,
):
    trip = await TripRepository(session).add(_trip())
    selected, excluded = await CandidatePlaceRepository(session).add_many(
        [
            _place("Selected museum", 43.060, 141.350).model_copy(
                update={"trip_id": trip.id}
            ),
            _place("Excluded annex", 43.061, 141.351).model_copy(
                update={"trip_id": trip.id}
            ),
        ]
    )
    shortlist = await ShortlistStateRepository(session).upsert(
        ShortlistState(
            trip_id=trip.id,
            selected_candidate_ids=[selected.id],
            wishlist_excluded_ids=[excluded.id],
        )
    )
    state = TripState(trip=trip, shortlist=shortlist)
    _use_test_session(monkeypatch, session)
    monkeypatch.setattr(solver_module, "_make_transit_client", StubTransitClient)

    result = await solver_node(state)
    nodes = await ItineraryNodeRepository(session).list_for_version(
        result["current_itinerary"].id
    )

    assert [node.candidate_id for node in nodes] == [selected.id]


def test_solver_module_has_no_llm_sdk_import():
    path = Path(solver_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = {
        node.names[0].name.split(".")[0]
        if isinstance(node, ast.Import)
        else (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    assert roots.isdisjoint({"anthropic", "openai", "langchain_anthropic"})
