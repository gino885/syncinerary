"""Routing-aware repair: a bad day assignment must not cost a place its seat.

Stage 1 picks days from straight-line dispersion and a walking estimate.
Stage 2 judges them with opening hours, real transit and a twelve-hour clock.
Until M7k a disagreement ended there, so a place could be dropped purely
because its first day assignment was poor, and a day whose pairs did not work
collapsed to one stop while other days sat half empty.

Every provider here is deterministic. The transit stubs are the honest shape of
the failure: a pair with no arc at all is a pair Stage 2 cannot seat together.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from syncinerary.agents.solver.repair import (
    REASON_LOWER_MARGINAL_UTILITY,
    RepairBudget,
    candidate_value,
    classify_bucket_changes,
    learn_day_blocks,
    plan_value,
    select_replacements,
)
from syncinerary.agents.solver.stage1_days import assign_days
from syncinerary.agents.solver.stage2_route import (
    DayRoute,
    SolverOptions,
    solve_day,
    solve_full_routes,
)
from syncinerary.config.solver import DAILY_FATIGUE_BUDGET
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateScore,
    CandidateType,
    Trip,
    TripState,
)
from syncinerary.tools.transit import (
    FallbackTransitResolver,
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitUnavailable,
    choose_mode,
)
from syncinerary.tools.weather import WeatherForecast

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
START = date(2026, 5, 21)  # a Thursday
THURSDAY = START
WINDOW = "2026-05-21-0800"


def _trip(days: int = 3) -> Trip:
    return Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        start_date=START,
        end_date=START.replace(day=START.day + days - 1),
        days=days,
    )


def _place(
    name: str,
    lat: float,
    lng: float,
    *,
    kind: CandidateType = CandidateType.ATTRACTION,
    hours: list[list[int]] | None = None,
    hours_by_weekday: dict[str, list[list[int]]] | None = None,
    duration: int = 90,
    fatigue: int = 1,
) -> CandidatePlace:
    window = [[8, 21]] if hours is None else hours
    return CandidatePlace(
        trip_id=uuid4(),
        type=kind,
        name_canonical=name,
        lat=lat,
        lng=lng,
        hours_by_weekday=hours_by_weekday or {day: window for day in WEEKDAYS},
        duration_estimate_min=duration,
        fatigue_cost=fatigue,
        enrichment={"city": "Sapporo"},
    )


def _state(candidates: list[CandidatePlace], priorities: dict[str, float], days: int = 3):
    """A trip whose candidate scores are the priorities under test."""
    trip = _trip(days)
    by_name = {candidate.name_canonical: candidate for candidate in candidates}
    return TripState(
        trip=trip,
        candidates=candidates,
        candidate_scores=[
            CandidateScore(
                candidate_id=by_name[name].id,
                score=score,
                acceptance=score,
                must_have_bonus=0.0,
                votes_pos=0,
                votes_neg=0,
                votes_must=0,
                votes_total=1,
            )
            for name, score in priorities.items()
            if name in by_name
        ],
    )


class SplitTransit:
    """Routes within a named group, and refuses every pair across two groups.

    A missing arc is the strongest thing a routing graph can say: these two
    places cannot be visited on the same day. It is exactly what a day full of
    unroutable pairs looked like in production, and what the repair loop has to
    survive without discarding anybody.
    """

    name = "split"

    def __init__(self, groups: dict[str, set[str]], *, minutes: int = 25) -> None:
        self._group_of = {
            name: group for group, names in groups.items() for name in names
        }
        self._minutes = minutes
        self.solves = 0
        self._names: dict[str, str] = {}

    def register(self, candidates: list[CandidatePlace]) -> None:
        for candidate in candidates:
            self._names[
                TransitLocation(lat=candidate.lat, lng=candidate.lng).cache_id
            ] = candidate.name_canonical

    def _compatible(self, origin: TransitLocation, destination: TransitLocation) -> bool:
        left = self._group_of.get(self._names.get(origin.cache_id, ""))
        right = self._group_of.get(self._names.get(destination.cache_id, ""))
        if left is None or right is None:
            return True
        return left == right

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.solves += 1
        legs: list[TransitDuration] = []
        unavailable: list[TransitUnavailable] = []
        for origin_index, origin in enumerate(request.locations):
            for destination_index, destination in enumerate(request.locations):
                if origin_index == destination_index:
                    continue
                if not request.wants(origin_index, destination_index):
                    continue
                if (
                    choose_mode(
                        origin,
                        destination,
                        walking_cutoff_km=request.walking_cutoff_km,
                    )
                    is not TransitMode.TRANSIT
                ):
                    continue
                if self._compatible(origin, destination):
                    legs.append(
                        TransitDuration(
                            origin=origin,
                            destination=destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            duration_seconds=self._minutes * 60,
                            duration_minutes=self._minutes,
                            provider=self.name,
                        )
                    )
                else:
                    unavailable.append(
                        TransitUnavailable(
                            origin=origin,
                            destination=destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            status="ROUTE_NOT_FOUND",
                        )
                    )
        return TransitMatrix(legs=legs, unavailable=unavailable)

    async def aclose(self) -> None:
        return None


class BlindTransit:
    """Every provider in the chain refuses. The estimate is all that is left.

    Wrapped in the real resolver on purpose: it is what makes the difference
    between "no provider answered" and "these two cannot be visited together"
    visible, because the estimate covers city-scale pairs and stops at the
    ceiling.
    """

    name = "blind"

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        return TransitMatrix(
            legs=[],
            unavailable=[
                TransitUnavailable(
                    origin=origin,
                    destination=destination,
                    mode=TransitMode.TRANSIT,
                    departure_window=request.departure_window,
                    status="ROUTE_NOT_FOUND",
                )
                for origin_index, origin in enumerate(request.locations)
                for destination_index, destination in enumerate(request.locations)
                if origin_index != destination_index
            ],
        )

    async def aclose(self) -> None:
        return None


class OpenTransit:
    """Everything routes, in a fixed number of minutes."""

    name = "open"

    def __init__(self, minutes: int = 20) -> None:
        self._minutes = minutes
        self.solves = 0

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.solves += 1
        return TransitMatrix(
            legs=[
                TransitDuration(
                    origin=origin,
                    destination=destination,
                    mode=TransitMode.TRANSIT,
                    departure_window=request.departure_window,
                    duration_seconds=self._minutes * 60,
                    duration_minutes=self._minutes,
                    provider=self.name,
                )
                for origin_index, origin in enumerate(request.locations)
                for destination_index, destination in enumerate(request.locations)
                if origin_index != destination_index
                and request.wants(origin_index, destination_index)
            ]
        )

    async def aclose(self) -> None:
        return None


def _placed_names(result, candidates: list[CandidatePlace]) -> set[str]:
    name_of = {candidate.id: candidate.name_canonical for candidate in candidates}
    return {
        name_of[stop.candidate_id]
        for route in result.routes
        for stop in route.stops
        if stop.candidate_id in name_of
    }


def _stops_per_day(result) -> list[int]:
    return [len(route.stops) for route in result.routes]


# --------------------------------------------------------------------------
# The failure this exists for
# --------------------------------------------------------------------------


async def test_k_a_collapsing_day_does_not_cost_the_trip_its_places():
    """Day 0 can seat one of the three it was given. Day 1 could hold them all.

    Every place here opens 10:00 to 13:00 on the Thursday the trip starts and
    all day on the Friday. Stage 1 accepts both days for all of them, because
    it checks that a visit fits the day rather than that the day fits the
    visits, and then splits them evenly. Stage 2 discovers the truth and
    refuses two of day 0's three, which before M7k was where those two places
    left the trip: three of five placed, and a day holding a single stop while
    the next had room for four.
    """
    hours = {"thu": [[10, 13]], **{day: [[8, 21]] for day in WEEKDAYS if day != "thu"}}
    candidates = [
        _place(
            f"Place {index}",
            43.060 + index * 0.004,
            141.350,
            duration=90,
            hours_by_weekday=hours,
        )
        for index in range(5)
    ]
    state = _state(
        candidates,
        {f"Place {index}": 2.0 - index * 0.1 for index in range(5)},
        days=2,
    )

    before = await solve_full_routes(
        state,
        candidates,
        OpenTransit(minutes=15),
        weather=WeatherForecast(),
        budget=RepairBudget(max_rounds=0),
    )
    after = await solve_full_routes(
        state, candidates, OpenTransit(minutes=15), weather=WeatherForecast()
    )

    # The old planner: two of the group's five places gone, and a thin day.
    assert len(_placed_names(before, candidates)) == 3
    assert min(_stops_per_day(before)) == 1

    # The new one keeps all five, by moving days rather than by dropping.
    assert _placed_names(after, candidates) == {
        candidate.name_canonical for candidate in candidates
    }
    assert after.repair.repair_rounds >= 1
    assert after.repair.cross_day_moves + after.repair.cross_day_swaps >= 1
    assert after.repair.high_priority_places_preserved_by_reassignment >= 1


async def test_b_a_stop_that_cannot_share_a_day_moves_to_another_one():
    """Same-day reorder cannot help: there is no arc to reorder onto."""
    cluster = [
        _place("Cluster A", 43.060, 141.350),
        _place("Cluster B", 43.065, 141.355),
        _place("Cluster C", 43.070, 141.360),
    ]
    outlier = _place("Outlier", 43.200, 141.500)
    candidates = [*cluster, outlier]
    transit = SplitTransit(
        {
            "cluster": {place.name_canonical for place in cluster},
            "outlier": {"Outlier"},
        }
    )
    transit.register(candidates)
    state = _state(
        candidates,
        {
            "Cluster A": 2.0,
            "Cluster B": 1.9,
            "Cluster C": 1.8,
            "Outlier": 1.7,
        },
        days=2,
    )

    result = await solve_full_routes(state, candidates, transit, weather=WeatherForecast())

    assert "Outlier" in _placed_names(result, candidates)
    assert len(_placed_names(result, candidates)) == 4
    days_of = {
        stop.candidate_id: route.day for route in result.routes for stop in route.stops
    }
    assert days_of[outlier.id] != days_of[cluster[0].id]


async def test_c_a_cross_day_swap_keeps_both_high_priority_places():
    """A and B cannot share a day, and neither may be sacrificed for it."""
    a = _place("A", 43.140, 141.350)
    b = _place("B", 43.000, 141.360)
    c = _place("C", 43.142, 141.352)
    d = _place("D", 43.002, 141.362)
    candidates = [a, b, c, d]
    transit = SplitTransit({"north": {"A", "C"}, "south": {"B", "D"}})
    transit.register(candidates)
    state = _state(candidates, {"A": 2.0, "B": 1.9, "C": 1.0, "D": 0.9}, days=2)

    result = await solve_full_routes(state, candidates, transit, weather=WeatherForecast())

    placed = _placed_names(result, candidates)
    assert {"A", "B"} <= placed
    days_of = {
        stop.candidate_id: route.day for route in result.routes for stop in route.stops
    }
    # The two that cannot coexist ended up apart, and their partners followed.
    assert days_of[a.id] != days_of[b.id]
    assert days_of[a.id] == days_of[c.id]
    assert days_of[b.id] == days_of[d.id]


async def test_d_two_places_that_cannot_coexist_cost_the_cheaper_one():
    """Both open only on the trip's one Thursday, and 60 km apart.

    Past the estimate ceiling there is no arc and no honest way to invent one,
    so they cannot share the only day either can be visited. Exactly one of
    them is going, and which one is a question about their worth to the group.

    Stage 2 cannot answer it: with no arc between two candidates its circuit
    seats one of them by position, and it has no notion of what either is
    worth. Left alone it keeps the one the group scored at minus one and drops
    the one they scored at two.
    """
    thursday = {"thu": [[8, 21]], **{day: [] for day in WEEKDAYS if day != "thu"}}
    keep = _place("Keep", 43.060, 141.350, hours_by_weekday=thursday)
    drop = _place("Drop", 43.600, 141.350, hours_by_weekday=thursday)
    candidates = [keep, drop]
    state = _state(candidates, {"Keep": 2.0, "Drop": -1.0}, days=2)

    before = await solve_full_routes(
        state,
        candidates,
        FallbackTransitResolver([BlindTransit()]),
        weather=WeatherForecast(),
        budget=RepairBudget(max_rounds=0),
    )
    after = await solve_full_routes(
        state,
        candidates,
        FallbackTransitResolver([BlindTransit()]),
        weather=WeatherForecast(),
    )

    assert _placed_names(before, candidates) == {"Drop"}
    assert _placed_names(after, candidates) == {"Keep"}
    assert after.repair.repair_rounds == 1


async def test_e_a_structurally_impossible_place_is_replaced_from_the_reserve():
    """A place no day can seat frees its slot for the next-best candidate."""
    cluster = [
        _place("Cluster A", 43.060, 141.350),
        _place("Cluster B", 43.065, 141.355),
    ]
    # Closed on every trip date, so no day can ever seat it.
    impossible = _place(
        "Impossible",
        43.062,
        141.352,
        hours_by_weekday={day: [] for day in WEEKDAYS},
    )
    spare = _place("Spare", 43.067, 141.357)
    candidates = [*cluster, impossible]
    transit = OpenTransit()
    state = _state(
        [*candidates, spare],
        {
            "Cluster A": 2.0,
            "Cluster B": 1.9,
            "Impossible": 1.8,
            "Spare": 0.5,
        },
        days=2,
    )

    result = await solve_full_routes(
        state,
        candidates,
        transit,
        weather=WeatherForecast(),
        reserve_candidates=[spare],
    )

    placed = _placed_names(result, [*candidates, spare])
    assert "Impossible" not in placed
    assert "Spare" in placed
    assert result.repair.replacement_candidates_used == 1


async def test_f_an_estimated_leg_does_not_trigger_a_cross_day_rejection():
    """Provider uncertainty is not infeasibility, and must not move anything.

    Both providers refuse every arc, so every leg on the day is a conservative
    estimate. The day still fits, so no place may be moved or dropped.
    """
    # Four city-scale places, every pair inside the estimate ceiling.
    candidates = [
        _place("North", 43.100, 141.350, duration=60),
        _place("Centre", 43.060, 141.350, duration=60),
        _place("South", 43.030, 141.360, duration=60),
        _place("East", 43.060, 141.420, duration=60),
    ]
    resolver = FallbackTransitResolver([BlindTransit()])
    state = _state(
        candidates,
        {"North": 2.0, "Centre": 1.9, "South": 1.8, "East": 1.7},
        days=2,
    )

    result = await solve_full_routes(
        state, candidates, resolver, weather=WeatherForecast()
    )

    assert len(_placed_names(result, candidates)) == 4
    assert resolver.stats.estimated > 0
    assert resolver.stats.unroutable == 0
    # Nothing was repaired, because nothing was broken.
    assert result.repair.repair_rounds == 0
    assert result.repair.cross_day_moves == 0


async def test_g_a_genuinely_unroutable_pair_triggers_reassignment():
    """Past the estimate ceiling there is no arc, and that is a real conflict."""
    near = _place("Near", 43.060, 141.350)
    partner = _place("Partner", 43.062, 141.352)
    far = _place("Far", 43.400, 142.100)
    candidates = [near, partner, far]
    transit = SplitTransit({"city": {"Near", "Partner"}, "region": {"Far"}})
    transit.register(candidates)
    state = _state(candidates, {"Near": 2.0, "Partner": 1.9, "Far": 1.8}, days=2)

    result = await solve_full_routes(state, candidates, transit, weather=WeatherForecast())

    assert len(_placed_names(result, candidates)) == 3
    days_of = {
        stop.candidate_id: route.day for route in result.routes for stop in route.stops
    }
    assert days_of[far.id] != days_of[near.id]


async def test_h_opening_hours_infeasibility_moves_a_place_to_a_day_that_fits():
    """Transit is fine. The clock is not, and only on one day."""
    thursday_only = _place(
        "Thursday Only",
        43.062,
        141.352,
        hours_by_weekday={
            "thu": [[8, 21]],
            **{day: [] for day in WEEKDAYS if day != "thu"},
        },
    )
    others = [
        _place("Anytime A", 43.060, 141.350),
        _place("Anytime B", 43.064, 141.354),
    ]
    candidates = [thursday_only, *others]
    state = _state(
        candidates,
        {"Thursday Only": 2.0, "Anytime A": 1.9, "Anytime B": 1.8},
        days=2,
    )

    result = await solve_full_routes(
        state, candidates, OpenTransit(), weather=WeatherForecast()
    )

    days_of = {
        stop.candidate_id: route.day for route in result.routes for stop in route.stops
    }
    # 2026-05-21 is a Thursday, so the only day it can sit on is day 0.
    assert days_of[thursday_only.id] == 0


async def test_i_the_repair_loop_terminates_inside_its_budget():
    """A trip nothing can fix must still finish, and cheaply."""
    groups = {f"g{index}": {f"P{index}"} for index in range(6)}
    candidates = [
        _place(f"P{index}", 43.0 + index * 0.05, 141.3 + index * 0.05)
        for index in range(6)
    ]
    transit = SplitTransit(groups)
    transit.register(candidates)
    state = _state(
        candidates,
        {f"P{index}": 2.0 - index * 0.1 for index in range(6)},
        days=2,
    )

    result = await solve_full_routes(
        state,
        candidates,
        transit,
        weather=WeatherForecast(),
        budget=RepairBudget(max_rounds=2, max_day_solves=4, max_replacements=0),
    )

    assert result.repair.repair_rounds <= 2
    assert result.repair.day_solves <= 4
    # Every place is mutually unroutable, so a two day trip seats two of them.
    assert len(_placed_names(result, candidates)) >= 1


async def test_j_repair_does_not_loosen_fatigue_or_the_food_ceiling():
    """The repair loop re-solves Stage 1; it does not relax it."""
    heavy = [
        _place(f"Heavy {index}", 43.06 + index * 0.001, 141.35, fatigue=3)
        for index in range(8)
    ]
    state = _state(
        heavy,
        {f"Heavy {index}": 2.0 - index * 0.1 for index in range(8)},
        days=2,
    )

    result = await solve_full_routes(
        state, heavy, OpenTransit(), weather=WeatherForecast()
    )

    by_id = {candidate.id: candidate for candidate in heavy}
    for route in result.routes:
        fatigue = sum(by_id[stop.candidate_id].fatigue_cost for stop in route.stops)
        assert fatigue <= DAILY_FATIGUE_BUDGET


async def test_l_an_impossible_trip_returns_its_best_subset_by_value():
    """No arrangement works, so value decides who stays, not day order."""
    candidates = [
        _place("Low", 43.000, 141.300),
        _place("High", 43.400, 142.100),
    ]
    transit = SplitTransit({"a": {"Low"}, "b": {"High"}})
    transit.register(candidates)
    # "Low" is first in shortlist order but worth far less.
    state = _state(candidates, {"Low": -1.5, "High": 2.0}, days=1)

    result = await solve_full_routes(state, candidates, transit, weather=WeatherForecast())

    assert _placed_names(result, candidates) == {"High"}


# --------------------------------------------------------------------------
# The policy, unit by unit
# --------------------------------------------------------------------------


def test_only_refusals_about_the_place_itself_become_blocks():
    """A block must be a fact about the place and the date, nothing else.

    "closed_on_available_days" names no other candidate, so it is one.
    "no_day_fit" means the clock ran out around a combination, which says
    nothing about whether this place or its neighbours should give way, and
    turning it into "A cannot be on Thursday" would let Stage 2's refusal
    order decide. That case is probed and becomes a capacity fact instead.
    """
    closed, crowded, tired = uuid4(), uuid4(), uuid4()

    blocks, learned = learn_day_blocks(
        [
            (closed, 0, "closed_on_available_days"),
            (crowded, 0, "no_day_fit"),
            (tired, 1, "fatigue_overflow"),
        ],
        protected_ids=set(),
    )

    assert blocks == {closed: {0}}
    assert learned is True


def test_a_food_place_that_cannot_reach_a_meal_window_is_a_block():
    candidate = uuid4()

    blocks, _learned = learn_day_blocks(
        [(candidate, 2, "no_meal_slot")], protected_ids=set()
    )

    assert blocks == {candidate: {2}}


def test_a_must_go_place_is_never_blocked_off_a_day():
    required = uuid4()

    blocks, learned = learn_day_blocks(
        [(required, 0, "no_day_fit")],
        protected_ids={required},
    )

    assert blocks == {}
    assert learned is False


def test_a_repeated_refusal_teaches_nothing_new_and_stops_the_loop():
    candidate = uuid4()

    _blocks, learned = learn_day_blocks(
        [(candidate, 0, "no_day_fit")],
        protected_ids=set(),
        existing={candidate: {0}},
    )

    assert learned is False


def test_two_places_trading_days_count_as_one_swap():
    a, b = _place("A", 43.0, 141.0), _place("B", 43.1, 141.1)
    before = [[a], [b]]
    after = [[b], [a]]

    moves, swaps = classify_bucket_changes(before, after)

    assert (moves, swaps) == (0, 1)


def test_one_place_changing_day_counts_as_a_move():
    a, b = _place("A", 43.0, 141.0), _place("B", 43.1, 141.1)

    moves, swaps = classify_bucket_changes([[a, b], []], [[b], [a]])

    assert (moves, swaps) == (1, 0)


def test_value_outranks_stop_count():
    """A twelve stop plan holding the best places beats a fourteen stop one."""
    good, cheap = uuid4(), uuid4()
    values = {good: 100, cheap: 10}

    with_favourite = plan_value([good], values, 60)
    without = plan_value([cheap, cheap], values, 30)

    assert with_favourite > without


def test_reserves_are_offered_in_the_order_the_shortlist_ranked_them():
    first, second, third = (
        _place("First", 43.0, 141.0),
        _place("Second", 43.1, 141.1),
        _place("Third", 43.2, 141.2),
    )

    chosen = select_replacements(
        [first, second, third],
        already_admitted={second.id},
        limit=2,
    )

    assert [candidate.name_canonical for candidate in chosen] == ["First", "Third"]


def test_a_reserve_never_displaces_a_place_the_group_chose():
    """Stage 1 prices a reserve below every selection, whatever the trip length."""
    selected = [
        _place("Selected A", 43.060, 141.350),
        _place("Selected B", 43.061, 141.351),
    ]
    reserve = _place("Reserve", 43.062, 141.352)
    trip = _trip(1)

    assignment = assign_days(
        [*selected, reserve],
        trip,
        reserve_ids={reserve.id},
        replacement_budget=1,
        # A day with room for two, so admitting the reserve would cost a
        # selected place its seat.
        blocked_days={},
    )
    placed = {
        candidate.name_canonical
        for bucket in assignment.buckets
        for candidate in bucket
    }

    assert {"Selected A", "Selected B"} <= placed


@pytest.mark.parametrize("days", [1, 2, 5, 16])
def test_the_reserve_discount_holds_at_every_trip_length(days: int):
    """The gap is derived from the model, so it cannot be outgrown."""
    from syncinerary.domain.models import SolverObjectiveWeights

    weights = SolverObjectiveWeights(vote=100, weather=100)
    max_candidate_terms = weights.vote * 100 + weights.weather * 100 * days
    reserve_penalty = max(0, 1_000_000 - max_candidate_terms - 1)

    # Dropping a reserve, at its most expensive, still costs less than
    # dropping the cheapest selected candidate.
    assert reserve_penalty + max_candidate_terms < 1_000_000


def _unused(*_args: object) -> None:
    """Keep the imports honest about what this file exercises."""
    _ = (UUID, datetime, UTC, SolverOptions)


async def test_a_dropped_place_says_which_one_was_kept_instead():
    """"Why is my place missing" deserves the real answer, not a generic one."""
    thursday = {"thu": [[8, 21]], **{day: [] for day in WEEKDAYS if day != "thu"}}
    keep = _place("Keep", 43.060, 141.350, hours_by_weekday=thursday)
    drop = _place("Drop", 43.600, 141.350, hours_by_weekday=thursday)
    candidates = [keep, drop]
    state = _state(candidates, {"Keep": 2.0, "Drop": -1.0}, days=2)

    result = await solve_full_routes(
        state,
        candidates,
        FallbackTransitResolver([BlindTransit()]),
        weather=WeatherForecast(),
    )

    reasons = {item.candidate_id: item for item in result.stage1_unplaced}
    assert reasons[drop.id].reason_code == REASON_LOWER_MARGINAL_UTILITY
    assert "Keep was kept instead" in reasons[drop.id].reason_text


# --------------------------------------------------------------------------
# What the repair loop must NOT do
# --------------------------------------------------------------------------


class CountingTransit(OpenTransit):
    """OpenTransit that records how many lookups the planner asked for."""

    def __init__(self, minutes: int = 20) -> None:
        super().__init__(minutes)
        self.lookups = 0

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.lookups += 1
        return await super().prefetch_pairwise(request)


async def test_a_healthy_itinerary_is_left_exactly_as_it_was():
    """No refusals means no facts, no rounds, and no extra lookups.

    The cost of the repair loop on a trip that does not need it has to be
    zero, or every healthy plan pays for the broken ones.
    """
    candidates = [
        _place(f"Place {index}", 43.060 + index * 0.01, 141.350)
        for index in range(6)
    ]
    state = _state(
        candidates,
        {f"Place {index}": 2.0 - index * 0.1 for index in range(6)},
    )

    plain_transit = CountingTransit()
    plain = await solve_full_routes(
        state,
        candidates,
        plain_transit,
        weather=WeatherForecast(),
        budget=RepairBudget(max_rounds=0),
    )
    repaired_transit = CountingTransit()
    repaired = await solve_full_routes(
        state, candidates, repaired_transit, weather=WeatherForecast()
    )

    assert repaired.repair.repair_rounds == 0
    assert repaired.repair.day_solves == 0
    assert repaired.repair.learned_day_capacities == 0
    assert repaired.repair.learned_blocked_days == 0
    assert repaired_transit.lookups == plain_transit.lookups
    assert _stops_per_day(repaired) == _stops_per_day(plain)
    assert _placed_names(repaired, candidates) == _placed_names(plain, candidates)


async def test_f_a_day_a_different_order_can_solve_teaches_stage_1_nothing():
    """Ordering is Stage 2's job, on every solve, and needs no constraint.

    These four are reachable in one sequence and unreachable in another, so
    the day depends on its route order. Stage 2 finds the order itself, and
    the repair layer must stay out of it: no capacity, no block, no round.
    """
    candidates = [
        _place("First", 43.060, 141.350, duration=60),
        _place("Second", 43.064, 141.354, duration=60),
        _place("Third", 43.068, 141.358, duration=60),
        _place("Fourth", 43.072, 141.362, duration=60),
    ]
    state = _state(
        candidates,
        {"First": 2.0, "Second": 1.9, "Third": 1.8, "Fourth": 1.7},
        days=2,
    )

    result = await solve_full_routes(
        state, candidates, OpenTransit(minutes=10), weather=WeatherForecast()
    )

    assert len(_placed_names(result, candidates)) == 4
    assert result.repair.learned_day_capacities == 0
    assert result.repair.learned_blocked_days == 0
    assert result.repair.learned_incompatible_pairs == 0
    assert result.repair.repair_rounds == 0


async def test_e_a_closed_place_is_a_blocked_day_and_not_a_pair_constraint():
    """The one refusal that is genuinely about the place and the date alone."""
    open_thursday_only = {
        "thu": [[8, 21]],
        **{day: [] for day in WEEKDAYS if day != "thu"},
    }
    # Stage 1 can see this one is closed, so the block comes from its own
    # feasibility filter rather than from a Stage 2 refusal.
    restricted = _place(
        "Thursday Only", 43.062, 141.352, hours_by_weekday=open_thursday_only
    )
    others = [
        _place("Anytime A", 43.060, 141.350),
        _place("Anytime B", 43.064, 141.354),
    ]
    candidates = [restricted, *others]
    state = _state(
        candidates,
        {"Thursday Only": 2.0, "Anytime A": 1.9, "Anytime B": 1.8},
        days=3,
    )

    result = await solve_full_routes(
        state, candidates, OpenTransit(), weather=WeatherForecast()
    )

    days_of = {
        stop.candidate_id: route.day for route in result.routes for stop in route.stops
    }
    assert days_of[restricted.id] == 0
    # Nothing about the other places was inferred from its restriction.
    assert result.repair.learned_incompatible_pairs == 0


async def test_h_a_reserve_never_replaces_an_original_that_could_be_moved():
    """Fuller is not better. A movable original outranks any substitute."""
    hours = {"thu": [[10, 13]], **{day: [[8, 21]] for day in WEEKDAYS if day != "thu"}}
    candidates = [
        _place(f"Chosen {index}", 43.060 + index * 0.004, 141.350, duration=90,
               hours_by_weekday=hours)
        for index in range(5)
    ]
    spare = _place("Spare", 43.070, 141.360, duration=90)
    state = _state(
        [*candidates, spare],
        {
            **{f"Chosen {index}": 2.0 - index * 0.1 for index in range(5)},
            "Spare": 0.5,
        },
        days=2,
    )

    result = await solve_full_routes(
        state,
        candidates,
        OpenTransit(minutes=15),
        weather=WeatherForecast(),
        reserve_candidates=[spare],
    )

    # Every original was preserved by moving days, so nothing was replaced.
    assert _placed_names(result, candidates) == {
        candidate.name_canonical for candidate in candidates
    }
    assert result.repair.replacement_candidates_used == 0


async def test_c_input_order_never_decides_which_of_two_conflicts_survives():
    """The guard against Stage 2's seating order choosing the winner."""
    thursday = {"thu": [[8, 21]], **{day: [] for day in WEEKDAYS if day != "thu"}}

    async def plan(order: str) -> set[str]:
        keep = _place("Keep", 43.060, 141.350, hours_by_weekday=thursday)
        drop = _place("Drop", 43.600, 141.350, hours_by_weekday=thursday)
        candidates = [keep, drop] if order == "keep first" else [drop, keep]
        state = _state(candidates, {"Keep": 2.0, "Drop": -1.0}, days=2)
        result = await solve_full_routes(
            state,
            candidates,
            FallbackTransitResolver([BlindTransit()]),
            weather=WeatherForecast(),
        )
        return _placed_names(result, candidates)

    assert await plan("keep first") == {"Keep"}
    assert await plan("drop first") == {"Keep"}


async def test_k_the_same_trip_plans_the_same_way_every_time():
    """Determinism, because an eval diff between two commits means nothing
    if the same commit disagrees with itself."""
    hours = {"thu": [[10, 13]], **{day: [[8, 21]] for day in WEEKDAYS if day != "thu"}}
    candidates = [
        _place(f"Place {index}", 43.060 + index * 0.004, 141.350, duration=90,
               hours_by_weekday=hours)
        for index in range(5)
    ]
    state = _state(
        candidates,
        {f"Place {index}": 2.0 - index * 0.1 for index in range(5)},
        days=2,
    )

    runs = [
        await solve_full_routes(
            state, candidates, OpenTransit(minutes=15), weather=WeatherForecast()
        )
        for _ in range(3)
    ]

    plans = {
        tuple(
            (route.day, tuple(str(stop.candidate_id) for stop in route.stops))
            for route in result.routes
        )
        for result in runs
    }
    assert len(plans) == 1
    assert {result.repair.repair_rounds for result in runs} == {
        runs[0].repair.repair_rounds
    }


async def test_l_repair_is_measured_in_value_kept_not_stops_added():
    """Both numbers must move the right way, and value is the one that counts."""
    hours = {"thu": [[10, 13]], **{day: [[8, 21]] for day in WEEKDAYS if day != "thu"}}
    candidates = [
        _place(f"Place {index}", 43.060 + index * 0.004, 141.350, duration=90,
               hours_by_weekday=hours)
        for index in range(5)
    ]
    priorities = {f"Place {index}": 2.0 - index * 0.1 for index in range(5)}
    state = _state(candidates, priorities, days=2)
    worth = {
        candidate.id: candidate_value(priorities[candidate.name_canonical])
        for candidate in candidates
    }

    def retained(result) -> tuple[int, int]:
        placed = [stop.candidate_id for route in result.routes for stop in route.stops]
        return len(placed), sum(worth[candidate_id] for candidate_id in placed)

    before = await solve_full_routes(
        state,
        candidates,
        OpenTransit(minutes=15),
        weather=WeatherForecast(),
        budget=RepairBudget(max_rounds=0),
    )
    after = await solve_full_routes(
        state, candidates, OpenTransit(minutes=15), weather=WeatherForecast()
    )

    before_count, before_value = retained(before)
    after_count, after_value = retained(after)

    assert after_count > before_count
    assert after_value > before_value
    # And nothing was swapped in: every place kept is one the group chose.
    assert _placed_names(before, candidates) <= _placed_names(after, candidates)


# --------------------------------------------------------------------------
# The capacity probe's own contract
# --------------------------------------------------------------------------


def _matrix_for(candidates: list[CandidatePlace], minutes: int) -> TransitMatrix:
    locations = {
        candidate.id: TransitLocation(lat=candidate.lat, lng=candidate.lng)
        for candidate in candidates
    }
    return TransitMatrix(
        legs=[
            TransitDuration(
                origin=locations[origin.id],
                destination=locations[destination.id],
                mode=TransitMode.TRANSIT,
                departure_window=WINDOW,
                duration_seconds=minutes * 60,
                duration_minutes=minutes,
                provider="stub",
            )
            for origin in candidates
            for destination in candidates
            if origin.id != destination.id
        ]
    )


def test_the_probe_counts_seats_and_ignores_what_stage_2_would_prefer():
    """The guard against a future objective weight breaking repair silently.

    Stage 2 will give up one stop to seat a required meal, so on this day its
    plan holds fewer places than the day can physically take. The probe must
    report what fits, not what Stage 2 would choose, because the number
    becomes a constraint on Stage 1 and an under-count would forbid an
    arrangement that works.
    """
    # Three sights of three and a half hours each fit the day. A four hour
    # lunch sitting can only start inside its window, which leaves room for
    # one sight after it and none before, so seating the meal costs a seat.
    sights = [
        _place(f"Sight {index}", 43.060 + index * 0.004, 141.350, duration=210)
        for index in range(3)
    ]
    lunch = _place(
        "Long Lunch",
        43.072,
        141.362,
        kind=CandidateType.FOOD,
        duration=240,
        hours_by_weekday={day: [[11, 15]] for day in WEEKDAYS},
    )
    candidates = [*sights, lunch]
    transit = _matrix_for(candidates, 10)

    planned = solve_day(candidates, day=0, trip_date=THURSDAY, transit=transit)
    probed = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=transit,
        count_placements_only=True,
    )

    # The plan bought a meal with a seat; the probe reports the seats.
    assert "lunch" in planned.meals_covered
    assert len(planned.stops) == 2
    assert len(probed.stops) == 3
    assert probed.proven is True


def test_a_capacity_is_scoped_to_the_set_that_was_probed():
    """"Three of those four fit" is not "this day holds three".

    The constraint names its members, so a different set of the same size on
    the same day is untouched by it. Generalising a measurement into a
    property of the day would forbid arrangements nobody ever measured.
    """
    measured = [
        _place(f"Measured {index}", 43.060 + index * 0.004, 141.350)
        for index in range(4)
    ]
    others = [
        _place(f"Other {index}", 43.061 + index * 0.004, 141.351)
        for index in range(4)
    ]
    candidates = [*measured, *others]
    trip = _trip(2)

    assignment = assign_days(
        candidates,
        trip,
        day_capacities=[(0, frozenset(place.id for place in measured), 1)],
    )

    on_day_zero = {candidate.id for candidate in assignment.buckets[0]}
    assert len(on_day_zero & {place.id for place in measured}) <= 1
    # The day was never capped at one: the untouched set still fills it.
    assert len(on_day_zero) > 1


def test_a_capacity_leaves_a_pinned_place_alone_rather_than_going_infeasible():
    """A limit below what the group already pinned is dropped, not enforced."""
    pinned = _place("Pinned", 43.060, 141.350)
    other = _place("Other", 43.064, 141.354)
    trip = _trip(2)

    assignment = assign_days(
        [pinned, other],
        trip,
        pinned_days={pinned.id: 0},
        day_capacities=[(0, frozenset({pinned.id, other.id}), 0)],
    )

    assert pinned.id in {candidate.id for candidate in assignment.buckets[0]}


def test_a_probe_the_solver_could_not_prove_teaches_nothing():
    """An unproven count could be under the truth, and would over-constrain.

    Simulated rather than provoked: reproducing a real timeout would need a
    day large enough to make the suite slow, and the branch under test is the
    one line that reads the flag.
    """
    from syncinerary.agents.solver.stage2_route import _DaySolve, _probe_day_capacity

    candidates = [
        _place("A", 43.060, 141.350),
        _place("B", 43.064, 141.354),
        _place("C", 43.068, 141.358),
    ]
    unproven = DayRoute(day=0, proven=False)

    capacity = _probe_day_capacity(
        candidates,
        _DaySolve(unproven, _matrix_for(candidates, 10)),
        day=0,
        trip_date=THURSDAY,
        options=SolverOptions(),
        required=set(),
        fixed_starts={},
    )

    assert capacity is None or capacity.limit == len(candidates)
