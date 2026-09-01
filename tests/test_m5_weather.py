"""M5 Open-Meteo lookup and solver planning context."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import httpx

from syncinerary.agents.solver.planning_context import forecast_for_solver, pinned_days
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
    Trip,
    TripState,
)
from syncinerary.tools.weather import (
    OpenMeteoClient,
    WeatherForecast,
    WeatherForecastRequest,
)


def _trip() -> Trip:
    return Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        days=2,
    )


async def test_open_meteo_uses_daily_local_forecast_fields():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-09-01", "2026-09-02"],
                    "weather_code": [1, 61],
                    "precipitation_probability_max": [10, 80],
                    "precipitation_sum": [0.0, 7.4],
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        forecast = await OpenMeteoClient(http_client=http).forecast(
            WeatherForecastRequest(
                lat=43.0618,
                lng=141.3545,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 2),
                timezone="Asia/Tokyo",
            )
        )

    assert seen["daily"] == (
        "weather_code,precipitation_probability_max,precipitation_sum"
    )
    assert seen["timezone"] == "Asia/Tokyo"
    assert [day.precipitation_probability_max for day in forecast.days] == [10, 80]
    assert forecast.days[1].is_rainy is True


def test_user_pin_constraint_accepts_a_day_or_trip_date():
    trip = _trip()
    first_id, second_id = uuid4(), uuid4()
    constraints = [
        Constraint(
            trip_id=trip.id,
            type="user_pinned",
            value={"candidate_id": str(first_id), "day": 1},
            kind=ConstraintKind.HARD,
        ),
        Constraint(
            trip_id=trip.id,
            type="pinned_day",
            value={"candidate_id": str(second_id), "date": "2026-09-01"},
            kind=ConstraintKind.HARD,
        ),
    ]

    assert pinned_days(constraints, trip.start_date) == {first_id: 1, second_id: 0}


async def test_long_trip_weather_request_is_clipped_to_forecast_horizon():
    trip = _trip().model_copy(
        update={"end_date": date(2026, 9, 20), "days": 20}
    )
    candidate = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.ATTRACTION,
        name_canonical="Museum",
        lat=43.06,
        lng=141.35,
    )

    class StubWeather:
        def __init__(self) -> None:
            self.request: WeatherForecastRequest | None = None

        async def forecast(self, request: WeatherForecastRequest) -> WeatherForecast:
            self.request = request
            return WeatherForecast()

    provider = StubWeather()
    await forecast_for_solver(
        TripState(trip=trip),
        [candidate],
        provider,
        today=date(2026, 8, 25),
    )

    assert provider.request is not None
    assert provider.request.end_date == date(2026, 9, 9)
