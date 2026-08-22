"""M1 single-stage itinerary solver.

This is deliberately narrower than the final two-stage design in CLAUDE.md
§11. M1 keeps the shortlist's score order, chunks it evenly across trip days,
then uses CP-SAT independently per day to choose visit order and times from
opening hours plus Google transit durations.

TODO(M5): replace the placeholder day chunking with stage1_days.py and add
weather, fatigue, diversity, dispersion, pinned anchors and must-go handling.

NO LLM IN THIS FILE. Feasibility and final ordering are deterministic work
owned by OR-Tools under CLAUDE.md §2.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field, model_validator

from syncinerary.config.solver import (
    DAY_DURATION_CAP_HOURS,
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    M1_DESTINATION_TIMEZONE,
)
from syncinerary.domain.models import (
    CandidatePlace,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    TripState,
    WishlistNotPlaced,
)
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ShortlistStateRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.tools.transit import (
    GoogleDirectionsClient,
    PairwiseTransitRequest,
    TransitLocation,
    TransitMatrix,
)


class SolverOptions(BaseModel):
    """Daily schedule bounds, explicit so a future user setting can override them."""

    day_start: time = time(DEFAULT_DAY_START_HOUR)
    day_end: time = time(DEFAULT_DAY_END_HOUR)
    day_duration_cap_hours: int = Field(default=DAY_DURATION_CAP_HOURS, gt=0, le=24)
    timezone: str = M1_DESTINATION_TIMEZONE

    @model_validator(mode="after")
    def _window_has_positive_length(self) -> SolverOptions:
        if _minute_of_day(self.day_end) <= _minute_of_day(self.day_start):
            raise ValueError("day_end must be after day_start")
        ZoneInfo(self.timezone)
        return self


class ScheduledStop(BaseModel):
    candidate_id: UUID
    day: int
    start_minute: int
    end_minute: int
    transit_from_prev_min: int = 0
    transit_from_prev_mode: str | None = None


class UnplacedCandidate(BaseModel):
    candidate_id: UUID
    reason_code: str
    reason_text: str


class DayRoute(BaseModel):
    day: int
    stops: list[ScheduledStop] = Field(default_factory=list)
    unplaced: list[UnplacedCandidate] = Field(default_factory=list)
    total_transit_minutes: int = 0


class SolverResult(BaseModel):
    routes: list[DayRoute]

    @property
    def placed_count(self) -> int:
        return sum(len(route.stops) for route in self.routes)

    @property
    def total_transit_minutes(self) -> int:
        return sum(route.total_transit_minutes for route in self.routes)


class TransitProvider(Protocol):
    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix: ...


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


def _as_time(minutes: int) -> time:
    return time(hour=minutes // 60, minute=minutes % 60)


def chunk_evenly[T](items: Sequence[T], bucket_count: int) -> list[list[T]]:
    """Contiguous score-ordered buckets whose sizes differ by at most one."""
    if bucket_count <= 0:
        return []
    base, remainder = divmod(len(items), bucket_count)
    buckets: list[list[T]] = []
    offset = 0
    for index in range(bucket_count):
        size = base + (1 if index < remainder else 0)
        buckets.append(list(items[offset : offset + size]))
        offset += size
    return buckets


def _open_windows(
    candidate: CandidatePlace,
    trip_date: date,
    options: SolverOptions,
) -> list[tuple[int, int]]:
    weekday = trip_date.strftime("%a").lower()
    day_start = _minute_of_day(options.day_start)
    day_end = _minute_of_day(options.day_end)
    duration = candidate.duration_estimate_min
    windows: list[tuple[int, int]] = []
    for raw_start, raw_end in candidate.hours_by_weekday.get(weekday, []):
        start = max(day_start, raw_start * 60)
        end = min(day_end, raw_end * 60)
        if start + duration <= end:
            windows.append((start, end))
    return windows


def _location(candidate: CandidatePlace) -> TransitLocation:
    place_id = candidate.enrichment.get("google_place_id")
    return TransitLocation(
        place_id=place_id if isinstance(place_id, str) and place_id else None,
        lat=candidate.lat,
        lng=candidate.lng,
    )


def solve_day(
    candidates: list[CandidatePlace],
    *,
    day: int,
    trip_date: date,
    transit: TransitMatrix,
    options: SolverOptions | None = None,
) -> DayRoute:
    """Solve one day's optional path with opening and transit constraints."""
    options = options or SolverOptions()
    if not candidates:
        return DayRoute(day=day)

    open_candidates: list[CandidatePlace] = []
    windows_by_id: dict[UUID, list[tuple[int, int]]] = {}
    unplaced: list[UnplacedCandidate] = []
    for candidate in candidates:
        windows = _open_windows(candidate, trip_date, options)
        if not windows:
            unplaced.append(
                UnplacedCandidate(
                    candidate_id=candidate.id,
                    reason_code="closed_on_available_days",
                    reason_text=(
                        f"{candidate.name_canonical} has no opening interval that fits "
                        f"on {trip_date.isoformat()}."
                    ),
                )
            )
        else:
            open_candidates.append(candidate)
            windows_by_id[candidate.id] = windows

    if not open_candidates:
        return DayRoute(day=day, unplaced=unplaced)

    locations = {candidate.id: _location(candidate) for candidate in open_candidates}
    candidate_by_cache_id = {
        location.cache_id: candidate_id for candidate_id, location in locations.items()
    }
    leg_by_pair: dict[tuple[UUID, UUID], tuple[int, str]] = {}
    for leg in transit.legs:
        origin_id = candidate_by_cache_id.get(leg.origin.cache_id)
        destination_id = candidate_by_cache_id.get(leg.destination.cache_id)
        if origin_id is not None and destination_id is not None:
            leg_by_pair[(origin_id, destination_id)] = (
                leg.duration_minutes,
                leg.mode.value,
            )

    model = cp_model.CpModel()
    day_start = _minute_of_day(options.day_start)
    day_end = _minute_of_day(options.day_end)
    cap_minutes = options.day_duration_cap_hours * 60
    count = len(open_candidates)

    active: dict[int, cp_model.IntVar] = {}
    starts: dict[int, cp_model.IntVar] = {}
    ends: dict[int, cp_model.IntVar] = {}
    start_costs: dict[int, cp_model.IntVar] = {}
    arcs: dict[tuple[int, int], cp_model.IntVar] = {}
    circuit: list[tuple[int, int, cp_model.IntVar]] = []

    empty = model.new_bool_var("empty_day")
    circuit.append((0, 0, empty))

    for index, candidate in enumerate(open_candidates, start=1):
        duration = candidate.duration_estimate_min
        active[index] = model.new_bool_var(f"active_{index}")
        starts[index] = model.new_int_var(day_start, day_end - duration, f"start_{index}")
        ends[index] = model.new_int_var(day_start + duration, day_end, f"end_{index}")
        model.add(ends[index] == starts[index] + duration)

        start_costs[index] = model.new_int_var(0, day_end - day_start, f"start_cost_{index}")
        model.add(start_costs[index] == starts[index] - day_start).only_enforce_if(
            active[index]
        )
        model.add(start_costs[index] == 0).only_enforce_if(active[index].Not())

        interval_choices: list[cp_model.IntVar] = []
        for window_index, (window_start, window_end) in enumerate(
            windows_by_id[candidate.id]
        ):
            chosen = model.new_bool_var(f"window_{index}_{window_index}")
            interval_choices.append(chosen)
            model.add(starts[index] >= window_start).only_enforce_if(chosen)
            model.add(ends[index] <= window_end).only_enforce_if(chosen)
        model.add(sum(interval_choices) == active[index])

        self_loop = model.new_bool_var(f"skip_{index}")
        model.add(self_loop + active[index] == 1)
        circuit.append((index, index, self_loop))

        from_depot = model.new_bool_var(f"first_{index}")
        to_depot = model.new_bool_var(f"last_{index}")
        arcs[(0, index)] = from_depot
        arcs[(index, 0)] = to_depot
        circuit.extend(((0, index, from_depot), (index, 0, to_depot)))

    for origin_index, origin in enumerate(open_candidates, start=1):
        for destination_index, destination in enumerate(open_candidates, start=1):
            if origin_index == destination_index:
                continue
            leg = leg_by_pair.get((origin.id, destination.id))
            if leg is None:
                continue
            transit_minutes, _mode = leg
            arc = model.new_bool_var(f"arc_{origin_index}_{destination_index}")
            arcs[(origin_index, destination_index)] = arc
            circuit.append((origin_index, destination_index, arc))
            model.add(
                starts[destination_index] >= ends[origin_index] + transit_minutes
            ).only_enforce_if(arc)

    model.add_circuit(circuit)
    model.add(sum(active.values()) == 0).only_enforce_if(empty)
    model.add(sum(active.values()) >= 1).only_enforce_if(empty.Not())

    # The active span, not merely the sum of visits, respects the configured cap.
    for first_index, first_active in active.items():
        for last_index, last_active in active.items():
            model.add(ends[last_index] - starts[first_index] <= cap_minutes).only_enforce_if(
                [first_active, last_active]
            )

    transit_terms = []
    for (origin_index, destination_index), arc in arcs.items():
        if origin_index == 0 or destination_index == 0:
            continue
        origin = open_candidates[origin_index - 1]
        destination = open_candidates[destination_index - 1]
        transit_minutes, _mode = leg_by_pair[(origin.id, destination.id)]
        transit_terms.append(transit_minutes * arc)

    max_start_cost = (day_end - day_start) * count
    transit_weight = max_start_cost + 1
    max_transit_cost = cap_minutes * max(0, count - 1) * transit_weight
    unplaced_penalty = max_transit_cost + max_start_cost + 1
    model.minimize(
        unplaced_penalty * (count - sum(active.values()))
        + transit_weight * sum(transit_terms)
        + sum(start_costs.values())
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return DayRoute(
            day=day,
            unplaced=unplaced
            + [
                UnplacedCandidate(
                    candidate_id=candidate.id,
                    reason_code="no_day_fit",
                    reason_text=f"{candidate.name_canonical} could not fit the daily route.",
                )
                for candidate in open_candidates
            ],
        )

    order: list[int] = []
    if solver.value(empty) == 0:
        current = next(
            index
            for index in range(1, count + 1)
            if solver.value(arcs[(0, index)])
        )
        while current != 0:
            order.append(current)
            current = next(
                destination
                for (origin, destination), arc in arcs.items()
                if origin == current and solver.value(arc)
            )

    stops: list[ScheduledStop] = []
    total_transit = 0
    previous_id: UUID | None = None
    for index in order:
        candidate = open_candidates[index - 1]
        transit_minutes = 0
        mode: str | None = None
        if previous_id is not None:
            transit_minutes, mode = leg_by_pair[(previous_id, candidate.id)]
            total_transit += transit_minutes
        stops.append(
            ScheduledStop(
                candidate_id=candidate.id,
                day=day,
                start_minute=solver.value(starts[index]),
                end_minute=solver.value(ends[index]),
                transit_from_prev_min=transit_minutes,
                transit_from_prev_mode=mode,
            )
        )
        previous_id = candidate.id

    placed_ids = {stop.candidate_id for stop in stops}
    for candidate in open_candidates:
        if candidate.id not in placed_ids:
            unplaced.append(
                UnplacedCandidate(
                    candidate_id=candidate.id,
                    reason_code="no_day_fit",
                    reason_text=(
                        f"{candidate.name_canonical} did not fit within opening hours, "
                        f"transit, and the {options.day_duration_cap_hours}-hour day cap."
                    ),
                )
            )

    # Preserve shortlist order in the unplaced explanation surface.
    rank = {candidate.id: index for index, candidate in enumerate(candidates)}
    unplaced.sort(key=lambda item: rank[item.candidate_id])
    return DayRoute(
        day=day,
        stops=stops,
        unplaced=unplaced,
        total_transit_minutes=total_transit,
    )


async def solve_routes(
    state: TripState,
    candidates: list[CandidatePlace],
    transit_provider: TransitProvider,
    *,
    options: SolverOptions | None = None,
) -> SolverResult:
    """Placeholder day assignment followed by independent per-day CP-SAT."""
    options = options or SolverOptions()
    buckets = chunk_evenly(candidates, state.trip.days)
    routes: list[DayRoute] = []
    timezone = ZoneInfo(options.timezone)

    for day, bucket in enumerate(buckets):
        trip_date = state.trip.start_date + timedelta(days=day)
        departure_at = datetime.combine(trip_date, options.day_start, tzinfo=timezone)
        routable = [
            candidate
            for candidate in bucket
            if _open_windows(candidate, trip_date, options)
        ]
        matrix = await transit_provider.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[_location(candidate) for candidate in routable],
                departure_window=(
                    f"{trip_date.isoformat()}-{options.day_start.strftime('%H%M')}"
                ),
                departure_at=departure_at,
            )
        )
        routes.append(
            solve_day(
                bucket,
                day=day,
                trip_date=trip_date,
                transit=matrix,
                options=options,
            )
        )

    return SolverResult(routes=routes)


def _make_transit_client() -> GoogleDirectionsClient:
    return GoogleDirectionsClient()


async def solver_node(state: TripState) -> dict[str, Any]:
    """LangGraph node: solve, append a version and persist its immutable rows."""
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("solver.m1_route") as span:
        span.set_attribute("trip_id", str(trip.id))

        async with session_scope() as session:
            shortlist = state.shortlist or await ShortlistStateRepository(session).get_for_trip(
                trip.id
            )
            if shortlist is None:
                raise ValueError("Cannot solve a trip before its shortlist exists")
            candidates = await CandidatePlaceRepository(session).list_by_ids(
                shortlist.selected_candidate_ids
            )

        async with _make_transit_client() as transit_client:
            result = await solve_routes(state, candidates, transit_client)

        async with session_scope() as session:
            versions = ItineraryVersionRepository(session)
            previous = await versions.get_latest(trip.id)
            active = await versions.get_active(trip.id)
            if active is not None:
                await versions.set_status(active.id, ItineraryStatus.SUPERSEDED)

            version = await versions.add(
                ItineraryVersion(
                    trip_id=trip.id,
                    version_no=await versions.next_version_no(trip.id),
                    status=ItineraryStatus.ACTIVE,
                    parent_version_id=previous.id if previous else None,
                    objective_breakdown={
                        "placed_count": float(result.placed_count),
                        "total_transit_minutes": float(result.total_transit_minutes),
                    },
                )
            )

            nodes = [
                ItineraryNode(
                    version_id=version.id,
                    candidate_id=stop.candidate_id,
                    day=stop.day,
                    start_time=_as_time(stop.start_minute),
                    end_time=_as_time(stop.end_minute),
                    transit_from_prev_min=stop.transit_from_prev_min,
                    transit_from_prev_mode=stop.transit_from_prev_mode,
                )
                for route in result.routes
                for stop in route.stops
            ]
            await ItineraryNodeRepository(session).add_many(nodes)

            wishlist = [
                WishlistNotPlaced(
                    version_id=version.id,
                    candidate_id=item.candidate_id,
                    reason_code=item.reason_code,
                    reason_text=item.reason_text,
                )
                for route in result.routes
                for item in route.unplaced
            ]
            await WishlistNotPlacedRepository(session).add_many(wishlist)

        span.set_attribute("solver.placed_count", result.placed_count)
        span.set_attribute("solver.unplaced_count", sum(len(r.unplaced) for r in result.routes))
        span.set_attribute("solver.total_transit_minutes", result.total_transit_minutes)
        return {"current_itinerary": version}


__all__ = [
    "DayRoute",
    "ScheduledStop",
    "SolverOptions",
    "SolverResult",
    "UnplacedCandidate",
    "chunk_evenly",
    "solve_day",
    "solve_routes",
    "solver_node",
]
