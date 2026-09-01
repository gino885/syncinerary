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
    closed = _place("Closed", outdoor=False).model_copy(update={"hours_by_weekday": {}})
    candidates = [closed, *[_place(f"Heavy {index}", outdoor=False, fatigue=3) for index in range(6)]]

    assignment = assign_days(
        candidates,
        _trip(),
        weather=_forecast([20, 20]),
        weights=SolverObjectiveWeights(),
    )
    reasons = {item.candidate_id: item for item in assignment.unplaced}

    assert reasons[closed.id].reason_code == "closed_on_available_days"
    fatigue = [item for item in assignment.unplaced if item.reason_code == "fatigue_overflow"]
    assert fatigue
    assert "8-point fatigue cap" in fatigue[0].reason_text
