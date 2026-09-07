"""M5 deterministic Stage 1 day assignment."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from syncinerary.agents.solver.objective import SolverObjectiveWeights
from syncinerary.agents.solver.stage1_days import assign_days
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Trip,
)
from syncinerary.tools.weather import (
    WeatherDay,
    WeatherForecast,
)


def _trip(days: int = 2) -> Trip:
    return Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, days),
        days=days,
    )


def _place(
    name: str,
    *,
    outdoor: bool,
    fatigue: int = 1,
    category: str | None = None,
    candidate_type: CandidateType = CandidateType.ATTRACTION,
) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=candidate_type,
        name_canonical=name,
        lat=43.06 + len(name) * 0.0001,
        lng=141.35 + len(name) * 0.0001,
        hours_by_weekday={
            weekday: [[8, 21]]
            for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        },
        weather_dependent=outdoor,
        fatigue_cost=fatigue,
        category=category,
        enrichment={"city": "Sapporo"},
    )


def _forecast(probabilities: list[int]) -> WeatherForecast:
    return WeatherForecast(
        days=[
            WeatherDay(
                date=date(2026, 9, index + 1),
                precipitation_probability_max=probability,
                weather_code=61 if probability >= 50 else 1,
                precipitation_sum_mm=5.0 if probability >= 50 else 0.0,
            )
            for index, probability in enumerate(probabilities)
        ]
    )


def test_mixed_weather_moves_outdoor_places_to_the_dry_day():
    candidates = [
        _place("Outdoor A", outdoor=True, category="park"),
        _place("Outdoor B", outdoor=True, category="garden"),
        _place("Indoor A", outdoor=False, category="museum"),
        _place("Indoor B", outdoor=False, category="gallery"),
    ]

    assignment = assign_days(
        candidates,
        _trip(),
        weather=_forecast([5, 95]),
        weights=SolverObjectiveWeights(weather=100),
    )

    day_by_id = {
        candidate.id: day
        for day, bucket in enumerate(assignment.buckets)
        for candidate in bucket
    }
    assert {day_by_id[candidate.id] for candidate in candidates[:2]} == {0}
    assert {day_by_id[candidate.id] for candidate in candidates[2:]} == {1}


def test_sunny_rainy_and_mixed_scenarios_produce_different_assignments():
    candidates = [
        *[_place(f"Outdoor {index}", outdoor=True, fatigue=3) for index in range(4)],
        *[_place(f"Indoor {index}", outdoor=False, fatigue=3) for index in range(4)],
    ]
    weights = SolverObjectiveWeights(weather=100, vote=1, dispersion=1, diversity=1)

    scenarios = [
        assign_days(candidates, _trip(), weather=_forecast([0, 10]), weights=weights),
        assign_days(candidates, _trip(), weather=_forecast([90, 100]), weights=weights),
        assign_days(candidates, _trip(), weather=_forecast([0, 100]), weights=weights),
    ]
    rendered = {
        tuple(tuple(candidate.name_canonical for candidate in bucket) for bucket in result.buckets)
        for result in scenarios
    }

    assert len(rendered) == 3


def test_stage1_honors_fatigue_must_go_and_pinned_day():
    pinned = _place("Pinned", outdoor=False, fatigue=3)
    must_go = _place("Must go", outdoor=True, fatigue=3)
    extras = [_place(f"Extra {index}", outdoor=False, fatigue=3) for index in range(5)]

    assignment = assign_days(
        [pinned, must_go, *extras],
        _trip(),
        weather=_forecast([100, 0]),
        weights=SolverObjectiveWeights(weather=100),
        must_go_ids={must_go.id},
        pinned_days={pinned.id: 1},
    )

    assert pinned in assignment.buckets[1]
    assert any(must_go in bucket for bucket in assignment.buckets)
    assert all(sum(candidate.fatigue_cost for candidate in bucket) <= 8 for bucket in assignment.buckets)


def test_closed_and_fatigue_overflow_reasons_are_quantified():
    # A published schedule that names no trip weekday. An absent schedule
    # means the hours are unknown, which is a different thing and must not
    # remove the place: see test_unknown_hours_are_not_a_closed_door.
    closed = _place("Closed", outdoor=False).model_copy(
        update={"hours_by_weekday": {"sun": [[9, 17]]}}
    )
    candidates = [closed, *[_place(f"Heavy {index}", outdoor=False, fatigue=3) for index in range(6)]]

    assignment = assign_days(
        candidates,
        _trip(),
        weather=_forecast([20, 20]),
        weights=SolverObjectiveWeights(),
    )
    reasons = {item.candidate_id: item for item in assignment.unplaced}

    assert reasons[closed.id].reason_code == "closed_on_available_days"
    assert "closed" in reasons[closed.id].reason_text
    fatigue = [item for item in assignment.unplaced if item.reason_code == "fatigue_overflow"]
    assert fatigue
    assert "8-point fatigue cap" in fatigue[0].reason_text


def test_a_day_is_never_given_more_food_than_it_can_seat():
    """Stage 2 can only place a restaurant inside a meal slot, so food beyond
    the day's meals is dropped however well it is clustered. Assigning it
    anyway wasted the slot twice: the food went nowhere, and the sight that
    could have used the space was never offered the day."""
    from syncinerary.config.solver import FOOD_PER_DAY_MAX

    food = [
        _place(f"Restaurant {index}", outdoor=False, candidate_type=CandidateType.FOOD)
        for index in range(8)
    ]
    sights = [_place(f"Sight {index}", outdoor=False) for index in range(8)]

    assignment = assign_days(
        [*food, *sights],
        _trip(),
        weather=_forecast([20, 20]),
        weights=SolverObjectiveWeights(),
    )

    for bucket in assignment.buckets:
        seated = sum(1 for place in bucket if place.type is CandidateType.FOOD)
        assert seated <= max(FOOD_PER_DAY_MAX, -(-len(food) // 2))


def test_the_food_ceiling_gives_way_before_it_makes_a_day_impossible():
    """An all-food pool relaxes the cap rather than failing to assign."""
    food = [
        _place(f"Restaurant {index}", outdoor=False, candidate_type=CandidateType.FOOD)
        for index in range(9)
    ]

    assignment = assign_days(
        food, _trip(), weather=_forecast([20, 20]), weights=SolverObjectiveWeights()
    )

    assert sum(len(bucket) for bucket in assignment.buckets) > 0


def test_unknown_hours_are_not_a_closed_door():
    """The bug this replaces dropped an onsen district and a shopping street.

    Google publishes no schedule for a place that is an area rather than a
    business. Reading that silence as "closed every day" removed them from the
    trip and told the traveler they had no opening window, which is the
    opposite of what the data said.
    """
    unknown = _place("Jozankei Onsen", outdoor=True).model_copy(
        update={"hours_by_weekday": {}}
    )

    assignment = assign_days(
        [unknown],
        _trip(),
        weather=_forecast([20, 20]),
        weights=SolverObjectiveWeights(),
    )

    assert not [
        item
        for item in assignment.unplaced
        if item.candidate_id == unknown.id
        and item.reason_code == "closed_on_available_days"
    ]
    assert any(unknown in bucket for bucket in assignment.buckets)


def test_an_area_is_not_gated_by_the_hours_of_a_business_inside_it():
    """A shopping street can inherit one shop's schedule. It is still a street."""
    area = _place("Susukino Street", outdoor=True).model_copy(
        update={"category": "natural_feature", "hours_by_weekday": {"sun": [[9, 17]]}}
    )

    assignment = assign_days(
        [area],
        _trip(),
        weather=_forecast([20, 20]),
        weights=SolverObjectiveWeights(),
    )

    assert any(area in bucket for bucket in assignment.buckets)
