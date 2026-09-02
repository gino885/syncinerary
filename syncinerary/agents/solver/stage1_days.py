"""Deterministic Stage 1 day assignment."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time, timedelta
from math import ceil
from uuid import UUID

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field

from syncinerary.agents.solver.objective import SolverObjectiveWeights
from syncinerary.config.solver import (
    ATTRACTIONS_PER_DAY_MIN,
    DAILY_FATIGUE_BUDGET,
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    FOOD_PER_DAY_MAX,
    MEALS_PER_DAY_MIN,
    SOLVER_DETERMINISTIC_LIMIT,
    SOLVER_TIME_LIMIT_SECONDS,
    WALKING_MINUTES_PER_DAY,
)
from syncinerary.domain.models import CandidatePlace, CandidateScore, CandidateType, Trip, Vote
from syncinerary.tools.transit import TransitLocation, haversine_km
from syncinerary.tools.weather import WeatherForecast


class Stage1Unplaced(BaseModel):
    candidate_id: UUID
    reason_code: str
    reason_text: str


class DayAssignment(BaseModel):
    buckets: list[list[CandidatePlace]]
    unplaced: list[Stage1Unplaced] = Field(default_factory=list)
    objective_breakdown: dict[str, float] = Field(default_factory=dict)


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


def cluster_nearby_evenly(
    candidates: Sequence[CandidatePlace],
    bucket_count: int,
) -> list[list[CandidatePlace]]:
    """Build balanced geographic day groups without losing score priority.

    The highest-ranked candidate is the first seed. Later seeds are the
    places farthest from every existing seed, which spreads days across the
    destination before the optimizer assigns each remaining candidate to a
    nearby day. Shortlist rank and day index are deterministic tiebreaks.

    Every day also receives a share of both kinds of candidate. Grouping on
    distance alone let one day take every restaurant in an area and leave the
    next with nothing to eat, and let food fill a day that was supposed to be
    sightseeing. Food has a floor for lunch and dinner and a ceiling so it
    cannot crowd out the sights; attractions have a floor of their own. Each
    quota degrades to what the pool can supply, so an unbalanced shortlist
    stays feasible instead of failing to solve.
    """
    capacities = [len(bucket) for bucket in chunk_evenly(candidates, bucket_count)]
    ranked = list(candidates)
    active_bucket_count = sum(capacity > 0 for capacity in capacities)
    if active_bucket_count == 0:
        return [[] for _capacity in capacities]

    rank_by_id = {candidate.id: index for index, candidate in enumerate(ranked)}
    seeds = [ranked[0]]
    while len(seeds) < active_bucket_count:
        next_seed = max(
            (candidate for candidate in ranked if candidate not in seeds),
            key=lambda candidate: (
                min(_distance_km(candidate, seed) for seed in seeds),
                -rank_by_id[candidate.id],
            ),
        )
        seeds.append(next_seed)

    assignment = cp_model.CpModel()
    choices = {
        (candidate_index, bucket_index): assignment.new_bool_var(
            f"candidate_{candidate_index}_day_{bucket_index}"
        )
        for candidate_index in range(len(ranked))
        for bucket_index in range(active_bucket_count)
    }
    for candidate_index in range(len(ranked)):
        assignment.add(
            sum(
                choices[(candidate_index, bucket_index)]
                for bucket_index in range(active_bucket_count)
            )
            == 1
        )
    for bucket_index in range(active_bucket_count):
        target_capacity = capacities[bucket_index]
        assigned_count = sum(
            choices[(candidate_index, bucket_index)]
            for candidate_index in range(len(ranked))
        )
        assignment.add(assigned_count >= max(1, target_capacity - 2))
        assignment.add(assigned_count <= target_capacity + 2)
    for bucket_index, seed in enumerate(seeds):
        assignment.add(choices[(rank_by_id[seed.id], bucket_index)] == 1)

    food_indices = [
        index
        for index, candidate in enumerate(ranked)
        if candidate.type is CandidateType.FOOD
    ]
    attraction_indices = [
        index
        for index, candidate in enumerate(ranked)
        if candidate.type is not CandidateType.FOOD
    ]

    available_food = len(food_indices) // active_bucket_count
    food_floor = min(MEALS_PER_DAY_MIN, available_food)
    # Every candidate has to land somewhere, so the ceiling can never sit below
    # the share a day must absorb. Capping under that made the model infeasible
    # rather than balanced.
    unavoidable_food = -(-len(food_indices) // active_bucket_count)
    food_ceiling = max(food_floor, FOOD_PER_DAY_MAX, unavoidable_food)
    attraction_floor = min(
        ATTRACTIONS_PER_DAY_MIN,
        len(attraction_indices) // active_bucket_count,
    )

    for bucket_index in range(active_bucket_count):
        food_in_bucket = sum(
            choices[(candidate_index, bucket_index)]
            for candidate_index in food_indices
        )
        if food_floor >= 1:
            assignment.add(food_in_bucket >= food_floor)
        if food_indices:
            assignment.add(food_in_bucket <= food_ceiling)
        if attraction_floor >= 1:
            assignment.add(
                sum(
                    choices[(candidate_index, bucket_index)]
                    for candidate_index in attraction_indices
                )
                >= attraction_floor
            )

    costs = []
    for candidate_index, candidate in enumerate(ranked):
        for bucket_index, seed in enumerate(seeds):
            distance_meters = round(_distance_km(candidate, seed) * 1000)
            deterministic_tiebreak = (candidate_index + 1) * (bucket_index + 1)
            costs.append(
                (distance_meters * 1000 + deterministic_tiebreak)
                * choices[(candidate_index, bucket_index)]
            )
    assignment.minimize(sum(costs))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = SOLVER_DETERMINISTIC_LIMIT
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    status = solver.solve(assignment)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Could not build balanced geographic day groups")

    buckets = [[] for _index in range(active_bucket_count)]
    for candidate_index, candidate in enumerate(ranked):
        for bucket_index in range(active_bucket_count):
            if solver.value(choices[(candidate_index, bucket_index)]):
                buckets[bucket_index].append(candidate)
                break

    buckets.extend([] for _capacity in capacities[active_bucket_count:])
    return buckets


def allocate_days(
    counts: list[int],
    days: int,
) -> list[int]:
    """Split the trip's days between cities, proportional to their candidates.

    Every city with candidates gets at least one day: a city worth typing is
    worth a day, and a city with zero days would have its cards quietly
    dropped. Remainders go to the cities with the largest fractional claim,
    with the earlier city winning a tie so the split is reproducible.
    """
    if days <= 0 or not counts:
        return [0] * len(counts)

    active = [index for index, count in enumerate(counts) if count > 0]
    if not active:
        return [0] * len(counts)
    # More cities than days: the trip can only visit the first `days` of them.
    active = active[:days]

    total = sum(counts[index] for index in active)
    allocation = [0] * len(counts)
    remainders: list[tuple[float, int]] = []
    for index in active:
        exact = counts[index] / total * days
        allocation[index] = max(1, int(exact))
        remainders.append((exact - int(exact), index))

    # max(1, ...) can overshoot; take days back from the largest allocations.
    while sum(allocation) > days:
        index = max(active, key=lambda i: (allocation[i], -i))
        if allocation[index] <= 1:
            break
        allocation[index] -= 1

    remainders.sort(key=lambda item: (-item[0], item[1]))
    position = 0
    while sum(allocation) < days and remainders:
        allocation[remainders[position % len(remainders)][1]] += 1
        position += 1

    return allocation


def assign_days_by_city(
    candidates: Sequence[CandidatePlace],
    days: int,
    city_names: list[str],
) -> list[list[CandidatePlace]]:
    """Give each city a consecutive block of days, then cluster inside it.

    Grouping on distance alone let a two city trip alternate: Lisbon, Porto,
    Lisbon, Porto. Each of those hops is a few hundred kilometres, which no
    itinerary should ask for daily. Cities keep the order they were typed, so
    the trip reads as a route rather than a shuffle.
    """
    if not city_names:
        return cluster_nearby_evenly(candidates, days)

    by_city: dict[str, list[CandidatePlace]] = {name: [] for name in city_names}
    unplaced: list[CandidatePlace] = []
    for candidate in candidates:
        city = candidate.enrichment.get("city")
        if isinstance(city, str) and city in by_city:
            by_city[city].append(candidate)
        else:
            unplaced.append(candidate)

    # A card with no city recorded joins whichever city it is nearest to, so
    # nothing is lost just because its provenance is thin.
    for candidate in unplaced:
        nearest = min(
            (name for name in city_names if by_city[name]),
            key=lambda name: min(
                _distance_km(candidate, other) for other in by_city[name]
            ),
            default=None,
        )
        by_city[nearest or city_names[0]].append(candidate)

    allocation = allocate_days([len(by_city[name]) for name in city_names], days)

    buckets: list[list[CandidatePlace]] = []
    for name, day_count in zip(city_names, allocation, strict=True):
        if day_count == 0:
            continue
        buckets.extend(cluster_nearby_evenly(by_city[name], day_count))
    return buckets


def assign_days(
    candidates: Sequence[CandidatePlace],
    trip: Trip,
    *,
    weather: WeatherForecast | None = None,
    weights: SolverObjectiveWeights | None = None,
    scores: Sequence[CandidateScore] = (),
    votes: Sequence[Vote] = (),
    must_go_ids: set[UUID] | None = None,
    pinned_days: dict[UUID, int] | None = None,
    day_start: time = time(DEFAULT_DAY_START_HOUR),
    day_end: time = time(DEFAULT_DAY_END_HOUR),
) -> DayAssignment:
    """Assign each shortlisted candidate to a day or the wishlist.

    Hard constraints decide feasibility. The weighted objective only chooses
    among feasible assignments, so model-produced weights can never override
    opening hours, fatigue, walking, city blocks, must-go, or pinned days.
    """
    ranked = list(candidates)
    if trip.days <= 0:
        return DayAssignment(buckets=[], unplaced=[])
    if not ranked:
        return DayAssignment(buckets=[[] for _day in range(trip.days)])

    objective_weights = weights or SolverObjectiveWeights()
    must_go = must_go_ids or set()
    pinned = dict(pinned_days or {})
    candidate_by_id = {candidate.id: candidate for candidate in ranked}
    unknown_required = (must_go | set(pinned)) - set(candidate_by_id)
    if unknown_required:
        raise ValueError("Must-go and pinned candidates must be in the shortlist")
    if any(day < 0 or day >= trip.days for day in pinned.values()):
        raise ValueError("Pinned day is outside the trip")

    for candidate in ranked:
        event_date = candidate.enrichment.get("event_date")
        if isinstance(event_date, str):
            try:
                event_day = (date.fromisoformat(event_date) - trip.start_date).days
            except ValueError:
                continue
            if 0 <= event_day < trip.days:
                pinned.setdefault(candidate.id, event_day)

    allowed_city_days = _allowed_days_by_city(ranked, trip)
    feasible_days: dict[UUID, list[int]] = {}
    for candidate in ranked:
        feasible_days[candidate.id] = [
            day
            for day in allowed_city_days[candidate.id]
            if _fits_open_hours(
                candidate,
                trip.start_date + timedelta(days=day),
                day_start,
                day_end,
            )
        ]

    for candidate_id in must_go | set(pinned):
        required_days = feasible_days[candidate_id]
        if candidate_id in pinned:
            required_days = [day for day in required_days if day == pinned[candidate_id]]
        if not required_days:
            candidate = candidate_by_id[candidate_id]
            raise RuntimeError(
                f"Required candidate {candidate.name_canonical} is not feasible on its required day"
            )

    model = cp_model.CpModel()
    assigned = {
        (index, day): model.new_bool_var(f"candidate_{index}_day_{day}")
        for index in range(len(ranked))
        for day in range(trip.days)
    }
    not_placed = {
        index: model.new_bool_var(f"candidate_{index}_not_placed")
        for index in range(len(ranked))
    }
    for index, candidate in enumerate(ranked):
        model.add(
            sum(assigned[(index, day)] for day in range(trip.days))
            + not_placed[index]
            == 1
        )
        feasible = set(feasible_days[candidate.id])
        for day in range(trip.days):
            if day not in feasible:
                model.add(assigned[(index, day)] == 0)
        if candidate.id in must_go:
            model.add(not_placed[index] == 0)
        if candidate.id in pinned:
            model.add(assigned[(index, pinned[candidate.id])] == 1)

    capacity = min(8, ceil(len(ranked) / trip.days) + 2)
    nearest_walk_minutes = _nearest_walk_minutes(ranked)
    for day in range(trip.days):
        model.add(sum(assigned[(index, day)] for index in range(len(ranked))) <= capacity)
        model.add(
            sum(
                max(1, candidate.fatigue_cost) * assigned[(index, day)]
                for index, candidate in enumerate(ranked)
            )
            <= DAILY_FATIGUE_BUDGET
        )
        model.add(
            sum(
                nearest_walk_minutes[index] * assigned[(index, day)]
                for index in range(len(ranked))
            )
            <= WALKING_MINUTES_PER_DAY
        )

    terms: list[cp_model.LinearExpr] = []
    base_not_placed_penalty = 1_000_000
    score_by_id = {score.candidate_id: score.score for score in scores}
    weather_good_ids = {
        vote.candidate_id
        for vote in votes
        if vote.note_parsed
        and vote.note_parsed.get("conditional_on") == "weather_good"
    }
    for index, candidate in enumerate(ranked):
        score = max(-2.0, min(2.0, score_by_id.get(candidate.id, 0.0)))
        vote_value = round((score + 2.0) * 25)
        terms.append(
            (
                base_not_placed_penalty
                + objective_weights.vote * vote_value
            )
            * not_placed[index]
        )
        for day in range(trip.days):
            rain = _rain_probability(weather, trip.start_date + timedelta(days=day))
            mismatch = rain if candidate.weather_dependent else 100 - rain
            suitability = 100 - rain if candidate.weather_dependent else rain
            terms.append(
                objective_weights.weather * mismatch * assigned[(index, day)]
            )
            terms.append(
                objective_weights.weather * suitability * not_placed[index]
            )
            if candidate.id in weather_good_ids:
                terms.append(
                    objective_weights.conditional * rain * assigned[(index, day)]
                )

    for left in range(len(ranked)):
        for right in range(left + 1, len(ranked)):
            distance_cost = min(2_000, round(_distance_km(ranked[left], ranked[right]) * 100))
            same_category = bool(
                ranked[left].category
                and ranked[left].category == ranked[right].category
            )
            for day in range(trip.days):
                together = model.new_bool_var(f"together_{left}_{right}_{day}")
                model.add(together <= assigned[(left, day)])
                model.add(together <= assigned[(right, day)])
                model.add(
                    together >= assigned[(left, day)] + assigned[(right, day)] - 1
                )
                terms.append(objective_weights.dispersion * distance_cost * together)
                if same_category:
                    terms.append(objective_weights.diversity * 100 * together)

    # Stable but deliberately tiny: it only decides exact objective ties.
    terms.extend(
        (index + 1) * (day + 1) * assigned[(index, day)]
        for index in range(len(ranked))
        for day in range(trip.days)
    )
    model.minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = SOLVER_DETERMINISTIC_LIMIT
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Could not assign shortlist candidates to feasible days")

    buckets = [[] for _day in range(trip.days)]
    unplaced: list[Stage1Unplaced] = []
    fatigue_by_day = [
        sum(
            max(1, ranked[index].fatigue_cost)
            for index in range(len(ranked))
            if solver.value(assigned[(index, day)])
        )
        for day in range(trip.days)
    ]
    for index, candidate in enumerate(ranked):
        placed_day = next(
            (day for day in range(trip.days) if solver.value(assigned[(index, day)])),
            None,
        )
        if placed_day is not None:
            buckets[placed_day].append(candidate)
            continue
        unplaced.append(
            _unplaced_reason(
                candidate,
                feasible_days[candidate.id],
                fatigue_by_day,
                weather,
                trip,
                capacity,
            )
        )

    return DayAssignment(
        buckets=buckets,
        unplaced=unplaced,
        objective_breakdown={
            "stage1_objective": float(solver.objective_value),
            "stage1_placed": float(sum(len(bucket) for bucket in buckets)),
            "stage1_unplaced": float(len(unplaced)),
        },
    )


def _fits_open_hours(
    candidate: CandidatePlace,
    trip_date: date,
    day_start: time,
    day_end: time,
) -> bool:
    weekday = trip_date.strftime("%a").lower()
    start_minute = day_start.hour * 60 + day_start.minute
    end_minute = day_end.hour * 60 + day_end.minute
    return any(
        max(start_minute, raw_start * 60) + candidate.duration_estimate_min
        <= min(end_minute, raw_end * 60)
        for raw_start, raw_end in candidate.hours_by_weekday.get(weekday, [])
    )


def _allowed_days_by_city(
    candidates: list[CandidatePlace],
    trip: Trip,
) -> dict[UUID, list[int]]:
    if not trip.cities:
        return {candidate.id: list(range(trip.days)) for candidate in candidates}
    counts = [
        sum(candidate.enrichment.get("city") == city for candidate in candidates)
        for city in trip.cities
    ]
    allocation = allocate_days(counts, trip.days)
    days_by_city: dict[str, list[int]] = {}
    offset = 0
    for city, count in zip(trip.cities, allocation, strict=True):
        days_by_city[city] = list(range(offset, offset + count))
        offset += count
    all_days = list(range(trip.days))
    return {
        candidate.id: days_by_city.get(candidate.enrichment.get("city"), all_days) or all_days
        for candidate in candidates
    }


def _nearest_walk_minutes(candidates: list[CandidatePlace]) -> list[int]:
    minutes: list[int] = []
    for candidate in candidates:
        distances = [
            _distance_km(candidate, other)
            for other in candidates
            if other.id != candidate.id
        ]
        nearest = min(distances, default=0.0)
        minutes.append(round(nearest * 12) if nearest <= 2.0 else 0)
    return minutes


def _rain_probability(weather: WeatherForecast | None, value: date) -> int:
    if weather is None:
        return 50
    day = weather.for_date(value)
    return day.precipitation_probability_max if day is not None else 50


def _unplaced_reason(
    candidate: CandidatePlace,
    feasible_days: list[int],
    fatigue_by_day: list[int],
    weather: WeatherForecast | None,
    trip: Trip,
    capacity: int,
) -> Stage1Unplaced:
    if not feasible_days:
        return Stage1Unplaced(
            candidate_id=candidate.id,
            reason_code="closed_on_available_days",
            reason_text=(
                f"{candidate.name_canonical} had no opening window long enough "
                f"between {trip.start_date.isoformat()} and {trip.end_date.isoformat()}."
            ),
        )
    if all(
        fatigue_by_day[day] + max(1, candidate.fatigue_cost) > DAILY_FATIGUE_BUDGET
        for day in feasible_days
    ):
        return Stage1Unplaced(
            candidate_id=candidate.id,
            reason_code="fatigue_overflow",
            reason_text=(
                f"{candidate.name_canonical} costs {max(1, candidate.fatigue_cost)} fatigue "
                f"points, but every open day was already at the {DAILY_FATIGUE_BUDGET}-point "
                "fatigue cap."
            ),
        )
    rain_chances = [
        _rain_probability(weather, trip.start_date + timedelta(days=day))
        for day in feasible_days
    ]
    if candidate.weather_dependent and rain_chances and min(rain_chances) >= 50:
        return Stage1Unplaced(
            candidate_id=candidate.id,
            reason_code="weather_mismatch",
            reason_text=(
                f"{candidate.name_canonical} is weather-dependent, and its driest open day "
                f"still had a {min(rain_chances)}% precipitation chance."
            ),
        )
    return Stage1Unplaced(
        candidate_id=candidate.id,
        reason_code="no_day_fit",
        reason_text=(
            f"{candidate.name_canonical} did not fit after each day reached its "
            f"{capacity}-place planning capacity or another hard limit."
        ),
    )


def _distance_km(origin: CandidatePlace, destination: CandidatePlace) -> float:
    return haversine_km(
        TransitLocation(lat=origin.lat, lng=origin.lng),
        TransitLocation(lat=destination.lat, lng=destination.lng),
    )


__all__ = [
    "allocate_days",
    "assign_days_by_city",
    "chunk_evenly",
    "cluster_nearby_evenly",
]
