"""Open-Meteo daily forecast client."""
from __future__ import annotations

from typing import Any, Self

import httpx

from syncinerary.tools.weather.models import (
    WeatherDay,
    WeatherForecast,
    WeatherForecastRequest,
)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT_SECONDS = 15.0


class WeatherResponseError(RuntimeError):
    """Open-Meteo did not return a usable daily forecast."""


class OpenMeteoClient:
    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=OPEN_METEO_TIMEOUT_SECONDS)
        self._owns_http = http_client is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def forecast(self, request: WeatherForecastRequest) -> WeatherForecast:
        response = await self._http.get(
            OPEN_METEO_URL,
            params={
                "latitude": request.lat,
                "longitude": request.lng,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "daily": (
                    "weather_code,precipitation_probability_max,precipitation_sum"
                ),
                "timezone": request.timezone,
            },
        )
        response.raise_for_status()
        return parse_forecast(response.json())


def parse_forecast(payload: dict[str, Any]) -> WeatherForecast:
    try:
        daily = payload["daily"]
        dates = daily["time"]
        codes = daily["weather_code"]
        probabilities = daily["precipitation_probability_max"]
        precipitation = daily["precipitation_sum"]
        if not (
            len(dates) == len(codes) == len(probabilities) == len(precipitation)
        ):
            raise ValueError("daily arrays differ in length")
        return WeatherForecast(
            days=[
                WeatherDay(
                    date=value,
                    weather_code=code,
                    precipitation_probability_max=probability,
                    precipitation_sum_mm=amount,
                )
                for value, code, probability, amount in zip(
                    dates,
                    codes,
                    probabilities,
                    precipitation,
                    strict=True,
                )
            ]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherResponseError(f"Malformed Open-Meteo response: {exc}") from exc


__all__ = ["OpenMeteoClient", "WeatherResponseError", "parse_forecast"]
