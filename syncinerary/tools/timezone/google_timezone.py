"""Look up the IANA timezone for a coordinate.

The solver schedules against a wall clock and asks Directions for departures at
a real instant, so it needs the destination's timezone. That used to be the
constant `Asia/Tokyo`, which was correct only while every trip was in Hokkaido.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.harness import ToolDefinition


class TimezoneLookupInput(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class TimezoneLookup(BaseModel):
    timezone: str | None = None
    name: str | None = None


class TimezoneUnavailable(RuntimeError):
    """The provider could not name a timezone for this coordinate."""


async def _lookup(
    value: TimezoneLookupInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> TimezoneLookup:
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required for timezone lookup")

    response = await client.get(
        "https://maps.googleapis.com/maps/api/timezone/json",
        params={
            "location": f"{value.lat},{value.lng}",
            # The API wants an instant because offsets move with daylight
            # saving. The zone id it returns does not depend on which instant,
            # and the zone id is all the solver stores.
            "timestamp": int(datetime.now(UTC).timestamp()),
            "key": api_key,
        },
    )
    response.raise_for_status()
    payload = response.json()
    provider_status = payload.get("status")
    if provider_status == "ZERO_RESULTS":
        return TimezoneLookup()
    if provider_status != "OK" or not payload.get("timeZoneId"):
        detail = payload.get("errorMessage") or "No timezone id returned"
        raise TimezoneUnavailable(
            f"Google Timezone returned {provider_status or 'UNKNOWN'}: {detail}"
        )
    return TimezoneLookup(
        timezone=payload["timeZoneId"],
        name=payload.get("timeZoneName"),
    )


def make_timezone_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    resolved_key = settings.google_maps_api_key if api_key is None else api_key

    async def lookup(value: TimezoneLookupInput) -> TimezoneLookup:
        if client is not None:
            return await _lookup(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _lookup(value, client=owned_client, api_key=resolved_key)

    return ToolDefinition(
        name="google_timezone",
        input_model=TimezoneLookupInput,
        output_model=TimezoneLookup,
        handler=lookup,
    )


__all__ = [
    "TimezoneLookup",
    "TimezoneLookupInput",
    "TimezoneUnavailable",
    "make_timezone_tool",
]
