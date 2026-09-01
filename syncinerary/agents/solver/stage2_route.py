"""Two-stage deterministic itinerary solver.

Stage 1 chooses a day or the wishlist for every shortlisted place. Stage 2
orders each assigned day against opening hours and cached transit durations.

NO LLM IN THIS FILE. Feasibility and final ordering are deterministic work
owned by OR-Tools under CLAUDE.md §2.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field, model_validator

from syncinerary.agents.solver.objective import SolverObjectiveWeights
from syncinerary.agents.solver.planning_context import forecast_for_solver, pinned_days
from syncinerary.agents.solver.stage1_days import assign_days, assign_days_by_city
from syncinerary.config.solver import (
    DAY_DURATION_CAP_HOURS,
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    M1_DESTINATION_TIMEZONE,
    MEAL_WINDOWS,
    MIN_STOPS_PER_DAY,
    NEARBY_WALKING_KM,
    OPTIONAL_MEALS,
    REQUIRED_MEALS,
    TOPUP_CANDIDATES_PER_ROUND,
    TOPUP_MAX_DETOUR_KM,
    TOPUP_MAX_ROUNDS,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    TripState,
    WishlistNotPlaced,
)
from syncinerary.harness import ToolDefinition, run_tool
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
    haversine_km,
)
from syncinerary.tools.weather import OpenMeteoClient, WeatherForecast


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
    # Which meal this stop fills, when it is a food stop inside a meal window.
    meal_slot: str | None = None


class UnplacedCandidate(BaseModel):
    candidate_id: UUID
    reason_code: str
    reason_text: str


class DayRoute(BaseModel):
    day: int
    stops: list[ScheduledStop] = Field(default_factory=list)
    unplaced: list[UnplacedCandidate] = Field(default_factory=list)
    total_transit_minutes: int = 0
    meals_covered: list[str] = Field(default_factory=list)

    @property
    def missing_required_meals(self) -> list[str]:
        return [meal for meal in REQUIRED_MEALS if meal not in self.meals_covered]

    @property
    def is_thin(self) -> bool:
        """A day worth topping up: too few stops, or missing lunch or dinner."""
        return len(self.stops) < MIN_STOPS_PER_DAY or bool(self.missing_required_meals)


class SolverResult(BaseModel):
    routes: list[DayRoute]
    stage1_unplaced: list[UnplacedCandidate] = Field(default_factory=list)
    stage1_objective: dict[str, float] = Field(default_factory=dict)

    def wishlist(self, shortlisted: list[UUID]) -> list[UnplacedCandidate]:
        """Shortlisted cards no day ended up placing, each reported once.

        A card one day could not fit is not unplaced if the make-up pass
        seated it on another day. Cards the group excluded never enter the
        solver.
        """
        placed = {stop.candidate_id for route in self.routes for stop in route.stops}
        wanted = [candidate_id for candidate_id in shortlisted if candidate_id not in placed]
        reasons: dict[UUID, UnplacedCandidate] = {}
        for item in self.stage1_unplaced:
            reasons.setdefault(item.candidate_id, item)
        for route in self.routes:
            for item in route.unplaced:
                reasons.setdefault(item.candidate_id, item)
        return [reasons[candidate_id] for candidate_id in wanted if candidate_id in reasons]

    @property
    def meal_coverage_count(self) -> int:
        return sum(
            1
            for route in self.routes
            for meal in REQUIRED_MEALS
            if meal in route.meals_covered
        )

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


def _meal_slot_windows(options: SolverOptions) -> dict[str, tuple[int, int]]:
    """Meal windows clipped to the configured day, dropping any that vanish."""
    day_start = _minute_of_day(options.day_start)
    day_end = _minute_of_day(options.day_end)
    slots: dict[str, tuple[int, int]] = {}
    for name, (start_hour, end_hour) in MEAL_WINDOWS.items():
        start = max(day_start, start_hour * 60)
        end = min(day_end, end_hour * 60)
        if start < end:
            slots[name] = (start, end)
    return slots


def _eligible_meal_slots(
    candidate: CandidatePlace,
    open_windows: list[tuple[int, int]],
    meal_slots: dict[str, tuple[int, int]],
) -> list[str]:
    """Meal slots this food candidate can actually sit a full visit inside."""
    duration = candidate.duration_estimate_min
    eligible: list[str] = []
    for name, (slot_start, slot_end) in meal_slots.items():
        for window_start, window_end in open_windows:
            start = max(window_start, slot_start)
            end = min(window_end, slot_end)
            if start + duration <= end:
                eligible.append(name)
                break
    return eligible


def _estimated_leg(
    origin: CandidatePlace,
    destination: CandidatePlace,
) -> tuple[int, str] | None:
    """Estimate only a nearby walking leg the provider could not route.

    The group chose walking for nearby pairs and public transit for longer
    pairs. A missing long transit route stays missing rather than becoming an
    invented car journey the group never selected.
    """
    distance_km = haversine_km(
        TransitLocation(lat=origin.lat, lng=origin.lng),
        TransitLocation(lat=destination.lat, lng=destination.lng),
    )
    if distance_km <= NEARBY_WALKING_KM:
        # Walking pace, 5 km/h.
        return max(5, round(distance_km * 12)), "walking_estimated"
    return None


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
    required_candidate_ids: set[UUID] | None = None,
) -> DayRoute:
    """Solve one day's optional path with opening and transit constraints."""
    options = options or SolverOptions()
    required = required_candidate_ids or set()
    if not candidates:
        return DayRoute(day=day)

    open_candidates: list[CandidatePlace] = []
    windows_by_id: dict[UUID, list[tuple[int, int]]] = {}
    unplaced: list[UnplacedCandidate] = []
    for candidate in candidates:
        windows = _open_windows(candidate, trip_date, options)
        if not windows:
            if candidate.id in required:
                raise RuntimeError(
                    f"Required candidate {candidate.name_canonical} is closed on {trip_date}"
                )
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

    # Food only counts as a meal when it sits inside a meal window, so a
    # restaurant whose hours never meet one is rejected here with its own
    # reason rather than looking like a routing failure later.
    meal_slots = _meal_slot_windows(options)
    eligible_meals: dict[UUID, list[str]] = {}
    routable: list[CandidatePlace] = []
    for candidate in open_candidates:
        if candidate.type is not CandidateType.FOOD:
            routable.append(candidate)
            continue
        eligible = _eligible_meal_slots(
            candidate,
            windows_by_id[candidate.id],
            meal_slots,
        )
        if not eligible:
            unplaced.append(
                UnplacedCandidate(
                    candidate_id=candidate.id,
                    reason_code="no_meal_slot",
                    reason_text=(
                        f"{candidate.name_canonical} is not open during breakfast, "
                        f"lunch, or dinner on {trip_date.isoformat()}."
                    ),
                )
            )
            continue
        eligible_meals[candidate.id] = eligible
        routable.append(candidate)

    open_candidates = routable
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
    meal_assignment: dict[tuple[int, str], cp_model.IntVar] = {}
    circuit: list[tuple[int, int, cp_model.IntVar]] = []

    empty = model.new_bool_var("empty_day")
    circuit.append((0, 0, empty))

    for index, candidate in enumerate(open_candidates, start=1):
        duration = candidate.duration_estimate_min
        active[index] = model.new_bool_var(f"active_{index}")
        if candidate.id in required:
            model.add(active[index] == 1)
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

        if candidate.id in eligible_meals:
            for meal in eligible_meals[candidate.id]:
                slot_start, slot_end = meal_slots[meal]
                assigned = model.new_bool_var(f"meal_{index}_{meal}")
                meal_assignment[(index, meal)] = assigned
                model.add(starts[index] >= slot_start).only_enforce_if(assigned)
                model.add(ends[index] <= slot_end).only_enforce_if(assigned)
            model.add(
                sum(
                    meal_assignment[(index, meal)]
                    for meal in eligible_meals[candidate.id]
                )
                == active[index]
            )

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
                leg = _estimated_leg(origin, destination)
                if leg is None:
                    continue
                leg_by_pair[(origin.id, destination.id)] = leg
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

    # One food stop per meal window at most: covered is boolean, so the
    # equality below also stops the day from scheduling two lunches.
    covered: dict[str, cp_model.IntVar] = {}
    for meal in meal_slots:
        terms = [
            variable
            for (_index, assigned_meal), variable in meal_assignment.items()
            if assigned_meal == meal
        ]
        if not terms:
            continue
        covered[meal] = model.new_bool_var(f"covered_{meal}")
        model.add(covered[meal] == sum(terms))

    max_start_cost = (day_end - day_start) * count
    transit_weight = max_start_cost + 1
    max_transit_cost = cap_minutes * max(0, count - 1) * transit_weight
    unplaced_penalty = max_transit_cost + max_start_cost + 1
    # Lunch and dinner are worth exactly one ordinary stop plus a tiebreak, so
    # a day will swap one sight for a meal and never two. At three times the
    # placement penalty the solver was dropping four sights to seat two meals,
    # which is how days came back holding nothing but restaurants.
    required_meal_penalty = unplaced_penalty + max_transit_cost + max_start_cost
    # Breakfast sits just under a single placement: it is taken when it is
    # free, and never at the cost of another stop.
    optional_meal_penalty = max_transit_cost + max_start_cost

    meal_terms = []
    for meal, variable in covered.items():
        if meal in REQUIRED_MEALS:
            meal_terms.append(required_meal_penalty * (1 - variable))
        elif meal in OPTIONAL_MEALS:
            meal_terms.append(optional_meal_penalty * (1 - variable))

    model.minimize(
        unplaced_penalty * (count - sum(active.values()))
        + sum(meal_terms)
        + transit_weight * sum(transit_terms)
        + sum(start_costs.values())
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if required:
            names = ", ".join(
                candidate.name_canonical
                for candidate in open_candidates
                if candidate.id in required
            )
            raise RuntimeError(f"Required candidates could not fit the daily route: {names}")
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
        meal_slot = next(
            (
                meal
                for (meal_index, meal), variable in meal_assignment.items()
                if meal_index == index and solver.value(variable)
            ),
            None,
        )
        stops.append(
            ScheduledStop(
                candidate_id=candidate.id,
                day=day,
                start_minute=solver.value(starts[index]),
                end_minute=solver.value(ends[index]),
                transit_from_prev_min=transit_minutes,
                transit_from_prev_mode=mode,
                meal_slot=meal_slot,
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
        meals_covered=[
            meal for meal in MEAL_WINDOWS if any(s.meal_slot == meal for s in stops)
        ],
    )


async def _solve_one_day(
    bucket: list[CandidatePlace],
    *,
    day: int,
    trip_date: date,
    transit_provider: TransitProvider,
    options: SolverOptions,
    required_candidate_ids: set[UUID] | None = None,
) -> DayRoute:
    """Fetch this day's pairwise transit and route it."""
    timezone = ZoneInfo(options.timezone)
    departure_at = datetime.combine(trip_date, options.day_start, tzinfo=timezone)
    routable = [
        candidate
        for candidate in bucket
        if _open_windows(candidate, trip_date, options)
    ]
    transit_request = PairwiseTransitRequest(
        locations=[_location(candidate) for candidate in routable],
        departure_window=(
            f"{trip_date.isoformat()}-{options.day_start.strftime('%H%M')}"
        ),
        departure_at=departure_at,
    )
    matrix = await run_tool(
        ToolDefinition(
            name="transit.prefetch_pairwise",
            input_model=PairwiseTransitRequest,
            output_model=TransitMatrix,
            handler=transit_provider.prefetch_pairwise,
        ),
        transit_request,
        state={
            "node": "solver",
            "day": day,
            "candidate_ids": [str(candidate.id) for candidate in bucket],
        },
    )
    assert isinstance(matrix, TransitMatrix)
    return solve_day(
        bucket,
        day=day,
        trip_date=trip_date,
        transit=matrix,
        options=options,
        required_candidate_ids=required_candidate_ids,
    )


def _centre(candidates: list[CandidatePlace]) -> tuple[float, float]:
    return (
        sum(candidate.lat for candidate in candidates) / len(candidates),
        sum(candidate.lng for candidate in candidates) / len(candidates),
    )


def _offers_for_day(
    route: DayRoute,
    bucket: list[CandidatePlace],
    pool: list[CandidatePlace],
    *,
    trip_date: date,
    options: SolverOptions,
    limit: int,
) -> list[CandidatePlace]:
    """Nearest usable stand-ins for a thin day, meals first when one is missing.

    Only candidates open on this date and within a walkable-ish detour of the
    day are offered. The radius is what keeps the make-up plan local: lunch and
    dinner are weighted heavily enough that an unbounded offer list would send
    a day across the region for a meal, and take the restaurant the next day
    was going to use while it was there.
    """
    anchor = [
        candidate
        for candidate in bucket
        if candidate.id in {stop.candidate_id for stop in route.stops}
    ] or bucket
    if not anchor:
        return []
    centre_lat, centre_lng = _centre(anchor)
    origin = TransitLocation(lat=centre_lat, lng=centre_lng)

    missing_meals = set(route.missing_required_meals)
    meal_slots = _meal_slot_windows(options)
    ranked: list[tuple[int, float, str, CandidatePlace]] = []
    for candidate in pool:
        windows = _open_windows(candidate, trip_date, options)
        if not windows:
            continue
        is_food = candidate.type is CandidateType.FOOD
        if is_food:
            eligible = set(_eligible_meal_slots(candidate, windows, meal_slots))
            if not eligible:
                continue
            # A day short of lunch or dinner takes food that can fill the gap
            # before it takes another sight.
            priority = 0 if eligible & missing_meals else 2
        else:
            priority = 1 if missing_meals else 0
        distance = haversine_km(
            origin,
            TransitLocation(lat=candidate.lat, lng=candidate.lng),
        )
        if distance > TOPUP_MAX_DETOUR_KM:
            continue
        ranked.append((priority, distance, str(candidate.id), candidate))

    ranked.sort(key=lambda row: row[:3])
    return [row[3] for row in ranked[:limit]]


def _is_better(trial: DayRoute, current: DayRoute) -> bool:
    """A required meal may trade for one stop, never two."""
    def key(route: DayRoute) -> tuple[int, int, int, int]:
        meals = sum(1 for meal in REQUIRED_MEALS if meal in route.meals_covered)
        stops = len(route.stops)
        return (stops + meals, meals, stops, -route.total_transit_minutes)

    return key(trial) > key(current)


async def solve_routes(
    state: TripState,
    candidates: list[CandidatePlace],
    transit_provider: TransitProvider,
    *,
    options: SolverOptions | None = None,
) -> SolverResult:
    """Geographic day assignment, per-day CP-SAT, then a make-up pass.

    The first pass routes the shortlist. Any day that comes back below the
    configured stop floor, or without lunch or dinner, then gets a bounded
    top-up: selected candidates another day could not fit are offered to it and
    the day is re-solved. The re-solve is
    kept only when it strictly improves that day, so the make-up pass can
    never make an itinerary worse than the plain shortlist run.
    """
    options = options or SolverOptions()
    buckets = assign_days_by_city(
        candidates,
        state.trip.days,
        state.trip.cities,
    )
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    candidate_rank = {
        candidate.id: index for index, candidate in enumerate(candidates)
    }
    routes: list[DayRoute] = []

    for day, bucket in enumerate(buckets):
        routes.append(
            await _solve_one_day(
                bucket,
                day=day,
                trip_date=state.trip.start_date + timedelta(days=day),
                transit_provider=transit_provider,
                options=options,
            )
        )

    placed = {stop.candidate_id for route in routes for stop in route.stops}
    seen: set[UUID] = set(placed)
    pool: list[CandidatePlace] = []
    for candidate in candidates:
        if candidate.id not in seen:
            seen.add(candidate.id)
            pool.append(candidate)

    for _round in range(TOPUP_MAX_ROUNDS):
        if not pool:
            break
        improved = False
        for day, route in enumerate(routes):
            if not route.is_thin or not pool:
                continue
            trip_date = state.trip.start_date + timedelta(days=day)
            offers = _offers_for_day(
                route,
                buckets[day],
                pool,
                trip_date=trip_date,
                options=options,
                limit=TOPUP_CANDIDATES_PER_ROUND,
            )
            if not offers:
                continue
            trial_bucket = buckets[day] + offers
            trial = await _solve_one_day(
                trial_bucket,
                day=day,
                trip_date=trip_date,
                transit_provider=transit_provider,
                options=options,
            )
            if not _is_better(trial, route):
                continue
            previous_ids = {stop.candidate_id for stop in route.stops}
            trial_ids = {stop.candidate_id for stop in trial.stops}
            newly_placed = trial_ids - previous_ids
            dropped = previous_ids - trial_ids
            routes[day] = trial
            buckets[day] = trial_bucket
            improved = True

            # A card moved onto this day must leave every other future trial
            # bucket. Otherwise a later make-up solve can schedule it twice.
            for other_day in range(len(buckets)):
                if other_day == day:
                    continue
                buckets[other_day] = [
                    candidate
                    for candidate in buckets[other_day]
                    if candidate.id not in newly_placed
                ]

            placed_now = {
                stop.candidate_id
                for current_route in routes
                for stop in current_route.stops
            }
            pool_by_id = {candidate.id: candidate for candidate in pool}
            for candidate_id in dropped:
                pool_by_id[candidate_id] = candidate_by_id[candidate_id]
            pool = sorted(
                (
                    candidate
                    for candidate_id, candidate in pool_by_id.items()
                    if candidate_id not in placed_now
                ),
                key=lambda candidate: candidate_rank[candidate.id],
            )
        if not improved:
            break

    return SolverResult(routes=routes)


async def solve_full_routes(
    state: TripState,
    candidates: list[CandidatePlace],
    transit_provider: TransitProvider,
    *,
    weather: WeatherForecast | None = None,
    options: SolverOptions | None = None,
    must_go_ids: set[UUID] | None = None,
    pinned_days: dict[UUID, int] | None = None,
    weights: SolverObjectiveWeights | None = None,
) -> SolverResult:
    """Run the M5 Stage 1 assignment, then route each decided day once."""
    options = options or SolverOptions()
    must_go = must_go_ids or set()
    pinned = pinned_days or {}
    assignment = assign_days(
        candidates,
        state.trip,
        weather=weather,
        weights=weights,
        scores=state.candidate_scores,
        votes=state.votes,
        must_go_ids=must_go,
        pinned_days=pinned,
        day_start=options.day_start,
        day_end=options.day_end,
    )
    routes = [
        await _solve_one_day(
            bucket,
            day=day,
            trip_date=state.trip.start_date + timedelta(days=day),
            transit_provider=transit_provider,
            options=options,
            required_candidate_ids=(must_go | set(pinned))
            & {candidate.id for candidate in bucket},
        )
        for day, bucket in enumerate(assignment.buckets)
    ]
    return SolverResult(
        routes=routes,
        stage1_unplaced=[
            UnplacedCandidate(
                candidate_id=item.candidate_id,
                reason_code=item.reason_code,
                reason_text=item.reason_text,
            )
            for item in assignment.unplaced
        ],
        stage1_objective=assignment.objective_breakdown,
    )


def _make_transit_client() -> GoogleDirectionsClient:
    return GoogleDirectionsClient()


def _make_weather_client() -> OpenMeteoClient:
    return OpenMeteoClient()


async def solver_node(state: TripState) -> dict[str, Any]:
    """LangGraph node: solve, append a version and persist its immutable rows."""
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("solver.two_stage_route") as span:
        span.set_attribute("trip_id", str(trip.id))

        async with session_scope() as session:
            shortlist = state.shortlist or await ShortlistStateRepository(session).get_for_trip(
                trip.id
            )
            if shortlist is None:
                raise ValueError("Cannot solve a trip before its shortlist exists")
            repo = CandidatePlaceRepository(session)
            candidates = await repo.list_by_ids(shortlist.selected_candidate_ids)

        options = SolverOptions(
            day_start=state.day_start,
            day_end=state.day_end,
            # The destination's own clock, resolved when the trip was created.
            # Older trips predate the column and keep the previous constant.
            timezone=trip.timezone or M1_DESTINATION_TIMEZONE,
        )
        pinned_by_candidate = pinned_days(state.constraints, trip.start_date)
        async with _make_weather_client() as weather_client:
            weather = await forecast_for_solver(state, candidates, weather_client)
        async with _make_transit_client() as transit_client:
            result = await solve_full_routes(
                state,
                candidates,
                transit_client,
                options=options,
                weather=weather,
                must_go_ids=set(shortlist.must_go_candidate_ids),
                pinned_days=pinned_by_candidate,
                weights=state.solver_weights,
            )

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
                        **result.stage1_objective,
                        "placed_count": float(result.placed_count),
                        "total_transit_minutes": float(result.total_transit_minutes),
                        "required_meals_covered": float(result.meal_coverage_count),
                        "required_meals_target": float(len(REQUIRED_MEALS) * trip.days),
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
                    fixed=stop.candidate_id in pinned_by_candidate,
                    lock_reason=(
                        "user_pinned"
                        if stop.candidate_id in pinned_by_candidate
                        else None
                    ),
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
                for item in result.wishlist(shortlist.selected_candidate_ids)
            ]
            await WishlistNotPlacedRepository(session).add_many(wishlist)

        span.set_attribute("solver.placed_count", result.placed_count)
        span.set_attribute(
            "solver.unplaced_count",
            len(result.wishlist(shortlist.selected_candidate_ids)),
        )
        span.set_attribute("solver.total_transit_minutes", result.total_transit_minutes)
        span.set_attribute("solver.required_meals_covered", result.meal_coverage_count)
        span.set_attribute(
            "solver.thin_day_count",
            sum(1 for route in result.routes if route.is_thin),
        )
        return {"current_itinerary": version}


__all__ = [
    "DayRoute",
    "ScheduledStop",
    "SolverOptions",
    "SolverResult",
    "UnplacedCandidate",
    "solve_day",
    "solve_full_routes",
    "solve_routes",
    "solver_node",
]
