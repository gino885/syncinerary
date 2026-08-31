"""M3 meal slotting and the make-up pass for fuller selected itineraries.

Covers the two scheduling gaps found on the M3 branch: days could come back
half empty with no way to refill them, and food was scheduled at whatever hour
minimised transit rather than at a meal time.
"""
from __future__ import annotations

from datetime import date, time
from typing import Self
from uuid import uuid4

from syncinerary.agents.solver import stage2_route as solver_module
from syncinerary.agents.solver.stage1_days import (
    allocate_days,
    assign_days_by_city,
    cluster_nearby_evenly,
)
from syncinerary.agents.solver.stage2_route import (
    DayRoute,
    ScheduledStop,
    SolverOptions,
    UnplacedCandidate,
    _is_better,
    solve_day,
    solve_routes,
)
from syncinerary.config.solver import ATTRACTIONS_PER_DAY_MIN, FOOD_PER_DAY_MAX
from syncinerary.domain.models import CandidatePlace, CandidateType, Trip, TripState
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    haversine_km,
)

THURSDAY = date(2026, 5, 21)


def _trip(days: int = 1) -> Trip:
    return Trip(
        destination="Hokkaido",
        start_date=THURSDAY,
        end_date=date(2026, 5, 20 + days),
        days=days,
    )


def _place(
    name: str,
    lat: float,
    lng: float,
    *,
    kind: CandidateType = CandidateType.ATTRACTION,
    hours: list[list[int]] | None = None,
    duration: int = 60,
) -> CandidatePlace:
    weekdays = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    window = [[8, 22]] if hours is None else hours
    return CandidatePlace(
        trip_id=uuid4(),
        type=kind,
        name_canonical=name,
        lat=lat,
        lng=lng,
        hours_by_weekday={day: window for day in weekdays},
        duration_estimate_min=duration,
    )


def _food(name: str, lat: float, lng: float, **kwargs) -> CandidatePlace:
    kwargs.setdefault("duration", 75)
    return _place(name, lat, lng, kind=CandidateType.FOOD, **kwargs)


def _matrix(candidates: list[CandidatePlace], minutes: int = 10) -> TransitMatrix:
    return TransitMatrix(
        legs=[
            TransitDuration(
                origin=TransitLocation(lat=origin.lat, lng=origin.lng),
                destination=TransitLocation(lat=destination.lat, lng=destination.lng),
                mode=TransitMode.WALKING,
                departure_window="test",
                duration_seconds=minutes * 60,
                duration_minutes=minutes,
            )
            for origin in candidates
            for destination in candidates
            if origin.id != destination.id
        ]
    )


class StubTransitClient:
    """Distance-proportional transit, and a record of what was asked for.

    Durations track real distance so the tests can tell a nearby stand-in from
    a far one, which a flat matrix cannot.
    """

    def __init__(self) -> None:
        self.requests: list[PairwiseTransitRequest] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.requests.append(request)
        legs = []
        for origin in request.locations:
            for destination in request.locations:
                if origin == destination:
                    continue
                minutes = max(5, round(haversine_km(origin, destination) * 3))
                legs.append(
                    TransitDuration(
                        origin=origin,
                        destination=destination,
                        mode=TransitMode.WALKING,
                        departure_window=request.departure_window,
                        duration_seconds=minutes * 60,
                        duration_minutes=minutes,
                    )
                )
        return TransitMatrix(legs=legs)


def _slot_of(route, name: str, candidates: list[CandidatePlace]) -> str | None:
    by_id = {candidate.id: candidate.name_canonical for candidate in candidates}
    for stop in route.stops:
        if by_id[stop.candidate_id] == name:
            return stop.meal_slot
    return None


# ----- meal windows -----


def test_lunch_and_dinner_are_both_scheduled_inside_their_windows():
    candidates = [
        _place(f"Sight {index}", 43.06 + index * 0.001, 141.35) for index in range(4)
    ] + [
        _food("Ramen counter", 43.062, 141.352),
        _food("Izakaya", 43.063, 141.353),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
    )

    assert "lunch" in route.meals_covered
    assert "dinner" in route.meals_covered
    for stop in route.stops:
        if stop.meal_slot == "lunch":
            assert 11 * 60 <= stop.start_minute and stop.end_minute <= 15 * 60
        if stop.meal_slot == "dinner":
            assert 17 * 60 <= stop.start_minute and stop.end_minute <= 21 * 60


def test_a_single_restaurant_is_kept_for_a_required_meal_not_used_at_breakfast():
    """Breakfast is optional, so the only restaurant goes to lunch or dinner."""
    candidates = [
        _place("Morning market", 43.06, 141.35, hours=[[7, 12]]),
        _place("Museum", 43.061, 141.351),
        _food("The only restaurant", 43.062, 141.352),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
    )

    assert _slot_of(route, "The only restaurant", candidates) in {"lunch", "dinner"}
    assert "breakfast" not in route.meals_covered


def test_food_that_never_opens_at_a_meal_time_is_reported_as_such():
    candidates = [
        _place("Museum", 43.06, 141.35),
        _food("Mid afternoon tearoom", 43.061, 141.351, hours=[[15, 17]]),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
    )

    reasons = {item.reason_code for item in route.unplaced}
    assert "no_meal_slot" in reasons
    assert route.meals_covered == []


def test_two_restaurants_never_share_one_meal_window():
    candidates = [
        _food("Lunch spot", 43.06, 141.35, hours=[[11, 15]]),
        _food("Second lunch spot", 43.061, 141.351, hours=[[11, 15]]),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
    )

    assert sum(1 for stop in route.stops if stop.meal_slot == "lunch") == 1


# ----- per-day food supply -----


def test_every_day_receives_a_share_of_the_food_candidates():
    sapporo = [_place(f"Sapporo sight {i}", 43.06 + i * 0.001, 141.35) for i in range(4)]
    otaru = [_place(f"Otaru sight {i}", 43.19 + i * 0.001, 140.99) for i in range(4)]
    food = [
        _food("Sapporo ramen", 43.062, 141.352),
        _food("Sapporo sushi", 43.063, 141.353),
        _food("Otaru seafood", 43.192, 140.992),
        _food("Otaru cafe", 43.193, 140.993),
    ]

    buckets = cluster_nearby_evenly(sapporo + otaru + food, 2)

    for bucket in buckets:
        assert any(candidate.type is CandidateType.FOOD for candidate in bucket)


# ----- the make-up plan -----


async def test_the_make_up_pass_leaves_an_already_full_day_alone():
    candidates = [
        _place(f"Sight {index}", 43.06 + index * 0.001, 141.35) for index in range(4)
    ] + [
        _food("Ramen counter", 43.064, 141.354),
        _food("Izakaya", 43.065, 141.355),
    ]
    state = TripState(trip=_trip(days=1))
    client = StubTransitClient()

    result = await solve_routes(
        state,
        candidates,
        client,
    )

    assert len(result.routes[0].stops) == len(candidates)
    # One transit prefetch means the day was never re-solved.
    assert len(client.requests) == 1


async def test_a_card_another_day_seated_is_not_reported_as_not_placed():
    shortlisted = [
        _place("Sapporo sight", 43.06, 141.35),
        _place("Otaru sight", 43.19, 140.99),
        _food("Sapporo lunch", 43.061, 141.351),
    ]
    state = TripState(trip=_trip(days=2))

    result = await solve_routes(state, shortlisted, StubTransitClient())

    placed = {stop.candidate_id for route in result.routes for stop in route.stops}
    reported = {
        item.candidate_id
        for item in result.wishlist([candidate.id for candidate in shortlisted])
    }
    assert not (placed & reported)


def test_day_window_can_be_narrowed_past_dinner_without_breaking_the_solver():
    """A group that wants an early night simply loses the dinner slot."""
    options = SolverOptions(day_start=SolverOptions().day_start, day_end=time(16))
    candidates = [
        _place("Museum", 43.06, 141.35),
        _food("Ramen counter", 43.061, 141.351),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
        options=options,
    )

    assert "lunch" in route.meals_covered
    assert "dinner" not in route.meals_covered


# ----- a day is sights first, with meals around them -----


def test_a_day_keeps_its_sights_and_still_eats():
    """The whole point: three to five places to go, plus lunch and dinner."""
    candidates = [
        _place(f"Sight {index}", 43.06 + index * 0.001, 141.35) for index in range(5)
    ] + [
        _food("Ramen counter", 43.066, 141.356),
        _food("Izakaya", 43.067, 141.357),
    ]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates),
    )

    sights = [stop for stop in route.stops if stop.meal_slot is None]
    assert len(sights) >= ATTRACTIONS_PER_DAY_MIN
    assert "lunch" in route.meals_covered
    assert "dinner" in route.meals_covered


def test_one_meal_is_never_worth_two_sights():
    """A restaurant that can only be reached by dropping two sights is skipped."""
    candidates = [
        _place(f"Sight {index}", 43.06 + index * 0.001, 141.35, duration=180)
        for index in range(4)
    ] + [_food("Long detour diner", 43.20, 141.60, hours=[[11, 15]])]

    route = solve_day(
        candidates,
        day=0,
        trip_date=THURSDAY,
        transit=_matrix(candidates, minutes=120),
    )

    sights = [stop for stop in route.stops if stop.meal_slot is None]
    assert len(sights) >= 2


def test_food_never_takes_more_than_its_share_of_a_realistic_shortlist():
    """A shortlist shaped like the real one: 5 days, 20 sights, 15 restaurants."""
    sights = [_place(f"Sight {i}", 43.06 + i * 0.004, 141.35) for i in range(20)]
    food = [_food(f"Restaurant {i}", 43.061 + i * 0.005, 141.36) for i in range(15)]

    buckets = cluster_nearby_evenly(sights + food, 5)

    for bucket in buckets:
        meals = sum(1 for c in bucket if c.type is CandidateType.FOOD)
        places = sum(1 for c in bucket if c.type is not CandidateType.FOOD)
        assert meals <= FOOD_PER_DAY_MAX
        assert places >= ATTRACTIONS_PER_DAY_MIN


def test_the_food_ceiling_gives_way_rather_than_leaving_a_card_unassigned():
    """Every candidate must land somewhere, so an all-food pool relaxes the cap.

    Capping below the share a day has to absorb would make the assignment
    infeasible, which is worse than a food-heavy day.
    """
    food = [_food(f"Restaurant {i}", 43.06 + i * 0.001, 141.35) for i in range(8)]

    buckets = cluster_nearby_evenly(food, 2)

    assert sum(len(bucket) for bucket in buckets) == 8


# ----- an unroutable pair must not silently delete a stop -----


def test_a_missing_long_public_transit_leg_is_not_invented_as_a_road_trip():
    """Long pairs stay unroutable when the requested public transit has no route."""
    candidates = [
        _place("Museum", 43.06, 141.35),
        _place("Observatory", 43.40, 142.10),
    ]
    # A matrix with no legs at all: every pair is unroutable.
    empty = TransitMatrix(legs=[])

    route = solve_day(candidates, day=0, trip_date=THURSDAY, transit=empty)

    assert len(route.stops) == 1
    assert all(stop.transit_from_prev_mode != "road_estimated" for stop in route.stops)


def test_a_missing_nearby_leg_uses_an_honest_walking_estimate():
    near = [_place("A", 43.060, 141.350), _place("B", 43.062, 141.352)]

    route = solve_day(near, day=0, trip_date=THURSDAY, transit=TransitMatrix(legs=[]))

    assert len(route.stops) == 2
    assert route.stops[1].transit_from_prev_mode == "walking_estimated"
    assert route.stops[1].transit_from_prev_min > 0


def test_a_make_up_meal_is_never_worth_losing_two_stops():
    current = DayRoute(
        day=0,
        stops=[
            ScheduledStop(candidate_id=uuid4(), day=0, start_minute=480, end_minute=540)
            for _ in range(5)
        ],
        meals_covered=["lunch"],
    )
    trial = DayRoute(
        day=0,
        stops=[
            ScheduledStop(candidate_id=uuid4(), day=0, start_minute=480, end_minute=540)
            for _ in range(3)
        ],
        meals_covered=["lunch", "dinner"],
    )

    assert not _is_better(trial, current)


async def test_a_candidate_moved_to_another_day_is_never_scheduled_twice(
    monkeypatch,
):
    a = _place("Day zero", 43.060, 141.350)
    b = _place("Day one", 43.061, 141.351)
    moved = _place("Moved", 43.062, 141.352)
    later = _place("Later", 43.063, 141.353)

    monkeypatch.setattr(
        solver_module,
        "assign_days_by_city",
        lambda _candidates, _days, _cities: [[a], [b, moved, later]],
    )

    async def fake_solve(bucket, *, day, **_kwargs):
        if day == 0 and len(bucket) == 1:
            placed = [a]
        elif day == 0:
            placed = [a, moved]
        elif len(bucket) == 3:
            placed = [b]
        else:
            placed = list({candidate.id: candidate for candidate in bucket}.values())
        placed_ids = {candidate.id for candidate in placed}
        return DayRoute(
            day=day,
            stops=[
                ScheduledStop(
                    candidate_id=candidate.id,
                    day=day,
                    start_minute=480 + index * 90,
                    end_minute=540 + index * 90,
                )
                for index, candidate in enumerate(placed)
            ],
            unplaced=[
                UnplacedCandidate(
                    candidate_id=candidate.id,
                    reason_code="no_day_fit",
                    reason_text=f"{candidate.name_canonical} did not fit.",
                )
                for candidate in bucket
                if candidate.id not in placed_ids
            ],
        )

    monkeypatch.setattr(solver_module, "_solve_one_day", fake_solve)

    result = await solve_routes(
        TripState(trip=_trip(days=2)),
        [a, b, moved, later],
        StubTransitClient(),
    )

    placed_ids = [stop.candidate_id for route in result.routes for stop in route.stops]
    assert len(placed_ids) == len(set(placed_ids))


# ----- a multi city trip visits one city at a time -----


def _in_city(name: str, city: str, lat: float, lng: float) -> CandidatePlace:
    return _place(name, lat, lng).model_copy(update={"enrichment": {"city": city}})


def test_days_are_split_between_cities_by_how_much_there_is_to_do():
    assert allocate_days([20, 20], 4) == [2, 2]
    assert allocate_days([30, 10], 4) == [3, 1]


def test_a_city_worth_typing_always_gets_at_least_one_day():
    assert allocate_days([100, 1], 5) == [4, 1]


def test_a_city_with_nothing_found_gets_no_days():
    assert allocate_days([10, 0], 3) == [3, 0]


def test_all_the_days_are_handed_out():
    for days in range(1, 8):
        assert sum(allocate_days([7, 5, 3], days)) == days


def test_each_city_gets_consecutive_days_instead_of_alternating():
    """The Lisbon, Porto, Lisbon, Porto plan is what this prevents."""
    lisbon = [_in_city(f"Lisbon {i}", "Lisbon", 38.72 + i * 0.002, -9.14) for i in range(8)]
    porto = [_in_city(f"Porto {i}", "Porto", 41.15 + i * 0.002, -8.62) for i in range(8)]

    buckets = assign_days_by_city(lisbon + porto, 4, ["Lisbon", "Porto"])

    cities_by_day = [
        {candidate.enrichment["city"] for candidate in bucket} for bucket in buckets
    ]
    assert cities_by_day == [{"Lisbon"}, {"Lisbon"}, {"Porto"}, {"Porto"}]


def test_the_cities_keep_the_order_they_were_typed():
    porto = [_in_city(f"Porto {i}", "Porto", 41.15 + i * 0.002, -8.62) for i in range(6)]
    lisbon = [_in_city(f"Lisbon {i}", "Lisbon", 38.72 + i * 0.002, -9.14) for i in range(6)]

    buckets = assign_days_by_city(porto + lisbon, 2, ["Porto", "Lisbon"])

    assert buckets[0][0].enrichment["city"] == "Porto"
    assert buckets[1][0].enrichment["city"] == "Lisbon"


def test_a_card_with_no_recorded_city_joins_its_nearest_one():
    lisbon = [_in_city(f"Lisbon {i}", "Lisbon", 38.72 + i * 0.002, -9.14) for i in range(4)]
    porto = [_in_city(f"Porto {i}", "Porto", 41.15 + i * 0.002, -8.62) for i in range(4)]
    orphan = _place("Attached by a traveler", 41.16, -8.63)

    buckets = assign_days_by_city(lisbon + porto + [orphan], 2, ["Lisbon", "Porto"])

    porto_day = next(
        bucket for bucket in buckets
        if any(c.enrichment.get("city") == "Porto" for c in bucket)
    )
    assert orphan in porto_day


def test_a_single_city_trip_is_unchanged_by_the_city_split():
    candidates = [_in_city(f"Sight {i}", "Sapporo", 43.06 + i * 0.002, 141.35) for i in range(9)]

    by_city = assign_days_by_city(candidates, 3, ["Sapporo"])
    plain = cluster_nearby_evenly(candidates, 3)

    assert [len(bucket) for bucket in by_city] == [len(bucket) for bucket in plain]


def test_a_trip_with_no_cities_recorded_falls_back_to_plain_clustering():
    candidates = [_place(f"Sight {i}", 43.06 + i * 0.002, 141.35) for i in range(6)]

    assert len(assign_days_by_city(candidates, 2, [])) == 2
