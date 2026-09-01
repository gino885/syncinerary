"""Hard pins and forecast context prepared before deterministic solving."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from syncinerary.config.solver import M1_DESTINATION_TIMEZONE
from syncinerary.domain.models import CandidatePlace, Constraint, TripState
from syncinerary.harness import ToolDefinition, run_tool
from syncinerary.tools.weather import (
    WeatherForecast,
    WeatherForecastRequest,
)


class WeatherProvider(Protocol):
    async def forecast(self, request: WeatherForecastRequest) -> WeatherForecast: ...


def pinned_days(constraints: list[Constraint], trip_start: date) -> dict[UUID, int]:
    """Read explicit user pins from persisted hard constraints."""
    pinned: dict[UUID, int] = {}
    for constraint in constraints:
        if constraint.type not in {"user_pinned", "pinned_day"}:
            continue
        raw_candidate = constraint.value.get("candidate_id")
        if not isinstance(raw_candidate, str):
            continue
        raw_day = constraint.value.get("day")
        if isinstance(raw_day, int):
            day = raw_day
        elif isinstance(constraint.value.get("date"), str):
            try:
                day = (
                    date.fromisoformat(constraint.value["date"]) - trip_start
                ).days
            except ValueError:
                continue
        else:
            continue
        try:
            pinned[UUID(raw_candidate)] = day
        except ValueError:
            continue
    return pinned


def _weather_location(
    state: TripState,
    candidates: list[CandidatePlace],
) -> tuple[float, float] | None:
    first = state.trip.resolved_cities[0] if state.trip.resolved_cities else None
    if isinstance(first, dict):
        lat, lng = first.get("lat"), first.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    if not candidates:
        return None
    return (
        sum(candidate.lat for candidate in candidates) / len(candidates),
        sum(candidate.lng for candidate in candidates) / len(candidates),
    )


async def forecast_for_solver(
    state: TripState,
    candidates: list[CandidatePlace],
    provider: WeatherProvider,
    *,
    today: date | None = None,
) -> WeatherForecast:
    """Fetch the portion of the trip inside Open-Meteo's 16-day horizon."""
    current = today or datetime.now(UTC).date()
    days_until_start = (state.trip.start_date - current).days
    if days_until_start < 0 or days_until_start > 15:
        return WeatherForecast()
    location = _weather_location(state, candidates)
    if location is None:
        return WeatherForecast()
    forecast_end = min(state.trip.end_date, current + timedelta(days=15))
    request = WeatherForecastRequest(
        lat=location[0],
        lng=location[1],
        start_date=state.trip.start_date,
        end_date=forecast_end,
        timezone=state.trip.timezone or M1_DESTINATION_TIMEZONE,
    )
    result = await run_tool(
        ToolDefinition(
            name="weather.open_meteo_forecast",
            input_model=WeatherForecastRequest,
            output_model=WeatherForecast,
            handler=provider.forecast,
        ),
        request,
        state={"node": "solver", "trip_id": str(state.trip.id)},
    )
    assert isinstance(result, WeatherForecast)
    return result


__all__ = ["WeatherProvider", "forecast_for_solver", "pinned_days"]
