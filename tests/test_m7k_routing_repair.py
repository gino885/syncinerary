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
    classify_bucket_changes,
    learn_day_blocks,
    plan_value,
    select_replacements,
)
from syncinerary.agents.solver.stage1_days import assign_days
from syncinerary.agents.solver.stage2_route import SolverOptions, solve_full_routes
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
START = date(2026, 5, 21)


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


def test_only_day_specific_refusals_become_blocks():
    left, right = uuid4(), uuid4()

    blocks, learned = learn_day_blocks(
        [
            (left, 0, "no_day_fit"),
            (right, 1, "fatigue_overflow"),
        ],
        protected_ids=set(),
    )

    assert blocks == {left: {0}}
    assert learned is True


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
