"""Google Routes transit matrix client with Redis-backed leg caching."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.config.transit import (
    ROUTES_FIELD_MASK,
    ROUTES_MATRIX_URL,
    ROUTES_TIMEOUT_SECONDS,
    TRANSIT_CACHE_TTL_SECONDS,
)
from syncinerary.store.redis import get_redis
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRequest,
    TransitUnavailable,
    choose_mode,
    haversine_km,
)

MAX_TRANSIT_MATRIX_LOCATIONS = 10


class RoutesError(RuntimeError):
    """Base class for typed Google Routes failures."""


class RoutesConfigurationError(RoutesError):
    """The API key or matrix dimensions are invalid."""


class RoutesResponseError(RoutesError):
    """The response was malformed or Google rejected the request."""

    def __init__(self, status: str, message: str | None = None) -> None:
        self.status = status
        self.detail = message
        suffix = f": {message}" if message else ""
        super().__init__(f"Google Routes returned {status}{suffix}")


class RoutesRouteUnavailable(RoutesResponseError):
    """Google found no transit route for one directed pair."""


class RoutesRateLimited(RoutesResponseError):
    """The Google Routes quota was exhausted."""


class _ElementStatus(BaseModel):
    code: int = 0
    message: str | None = None


class _RouteMatrixElement(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    origin_index: int = Field(alias="originIndex")
    destination_index: int = Field(alias="destinationIndex")
    status: _ElementStatus = Field(default_factory=_ElementStatus)
    condition: str | None = None
    duration: str | None = None


@dataclass(frozen=True)
class _IndexedLookup:
    origin_index: int
    destination_index: int
    request: TransitRequest


def parse_duration_seconds(raw: str) -> int:
    """Parse a protobuf duration such as ``578s`` without rounding down."""
    if not raw.endswith("s"):
        raise RoutesResponseError("MALFORMED_RESPONSE", "invalid duration")
    try:
        seconds = Decimal(raw[:-1])
    except InvalidOperation as exc:
        raise RoutesResponseError("MALFORMED_RESPONSE", "invalid duration") from exc
    if not seconds.is_finite() or seconds <= 0:
        raise RoutesResponseError("MALFORMED_RESPONSE", "duration must be positive")
    return int(seconds.to_integral_value(rounding=ROUND_CEILING))


def _cache_key(request: TransitRequest) -> str:
    return (
        f"transit:v2:{request.origin.cache_id}:{request.destination.cache_id}:"
        f"{request.mode.value}:{request.departure_window}"
    )


def _duration(request: TransitRequest, seconds: int, *, cache_hit: bool) -> TransitDuration:
    return TransitDuration(
        origin=request.origin,
        destination=request.destination,
        mode=request.mode,
        departure_window=request.departure_window,
        duration_seconds=seconds,
        duration_minutes=max(1, (seconds + 59) // 60),
        cache_hit=cache_hit,
    )


def _waypoint(location: TransitLocation) -> dict[str, Any]:
    if location.place_id:
        return {"waypoint": {"placeId": location.place_id}}
    return {
        "waypoint": {
            "location": {
                "latLng": {
                    "latitude": location.lat,
                    "longitude": location.lng,
                }
            }
        }
    }


def _departure_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _walking_seconds(request: TransitRequest) -> int:
    minutes = max(5, round(haversine_km(request.origin, request.destination) * 12))
    return minutes * 60


class GoogleRoutesClient:
    """Fetch one transit matrix per day and estimate nearby walking locally."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        redis: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.google_maps_api_key
        self._redis = redis if redis is not None else get_redis()
        self._http = http_client or httpx.AsyncClient(timeout=ROUTES_TIMEOUT_SECONDS)
        self._owns_http = http_client is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _require_key(self) -> str:
        if not self._api_key:
            raise RoutesConfigurationError("GOOGLE_MAPS_API_KEY is not configured")
        return self._api_key

    async def _fetch_matrix(
        self,
        origins: list[TransitLocation],
        destinations: list[TransitLocation],
        *,
        departure_at: datetime | None,
    ) -> list[_RouteMatrixElement]:
        body: dict[str, Any] = {
            "origins": [_waypoint(location) for location in origins],
            "destinations": [_waypoint(location) for location in destinations],
            "travelMode": "TRANSIT",
        }
        if departure := _departure_time(departure_at):
            body["departureTime"] = departure
        try:
            response = await self._http.post(
                ROUTES_MATRIX_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self._require_key(),
                    "X-Goog-FieldMask": ROUTES_FIELD_MASK,
                },
                json=body,
            )
            if response.status_code == 429:
                raise RoutesRateLimited("HTTP_429", "quota exhausted")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RoutesResponseError(
                    "MALFORMED_RESPONSE",
                    "route matrix must be a list",
                )
            return [_RouteMatrixElement.model_validate(item) for item in payload]
        except RoutesError:
            raise
        except httpx.HTTPStatusError as exc:
            raise RoutesResponseError(
                "HTTP_ERROR",
                f"HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            raise RoutesResponseError("HTTP_ERROR", type(exc).__name__) from exc
        except (ValueError, ValidationError) as exc:
            raise RoutesResponseError(
                "MALFORMED_RESPONSE",
                "invalid route matrix JSON",
            ) from exc

    @staticmethod
    def _element_seconds(element: _RouteMatrixElement) -> int:
        if element.status.code:
            if element.status.code == 8:
                raise RoutesRateLimited("RESOURCE_EXHAUSTED", element.status.message)
            raise RoutesResponseError(
                f"ELEMENT_{element.status.code}",
                element.status.message,
            )
        if element.condition == "ROUTE_NOT_FOUND":
            raise RoutesRouteUnavailable("ROUTE_NOT_FOUND")
        if element.condition != "ROUTE_EXISTS" or element.duration is None:
            raise RoutesResponseError(
                "MALFORMED_RESPONSE",
                "route element has no duration",
            )
        return parse_duration_seconds(element.duration)

    async def duration(self, request: TransitRequest) -> TransitDuration:
        key = _cache_key(request)
        cached = await self._redis.get(key)
        if cached is not None:
            return _duration(request, int(cached), cache_hit=True)

        if request.mode is TransitMode.WALKING:
            seconds = _walking_seconds(request)
        else:
            elements = await self._fetch_matrix(
                [request.origin],
                [request.destination],
                departure_at=request.departure_at,
            )
            if len(elements) != 1:
                raise RoutesResponseError(
                    "MALFORMED_RESPONSE",
                    "single route response has the wrong size",
                )
            seconds = self._element_seconds(elements[0])
        await self._redis.set(key, seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
        return _duration(request, seconds, cache_hit=False)

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        """Fetch uncached long pairs in one transit matrix.

        Nearby walking pairs are deliberately omitted. The route solver uses
        its existing honest ``walking_estimated`` fallback for those pairs.
        """
        lookups = [
            _IndexedLookup(
                origin_index=origin_index,
                destination_index=destination_index,
                request=TransitRequest(
                    origin=origin,
                    destination=destination,
                    mode=TransitMode.TRANSIT,
                    departure_window=request.departure_window,
                    departure_at=request.departure_at,
                ),
            )
            for origin_index, origin in enumerate(request.locations)
            for destination_index, destination in enumerate(request.locations)
            if origin_index != destination_index
            and choose_mode(
                origin,
                destination,
                walking_cutoff_km=request.walking_cutoff_km,
            )
            is TransitMode.TRANSIT
        ]
        if not lookups:
            return TransitMatrix(legs=[])
        if len(request.locations) > MAX_TRANSIT_MATRIX_LOCATIONS:
            raise RoutesConfigurationError(
                "A transit route matrix supports at most 10 locations"
            )

        keys = [_cache_key(item.request) for item in lookups]
        cached_values = await self._redis.mget(keys)
        results: list[TransitDuration | None] = [None] * len(lookups)
        missing_indexes: list[int] = []
        for index, cached in enumerate(cached_values):
            if cached is None:
                missing_indexes.append(index)
            else:
                results[index] = _duration(
                    lookups[index].request,
                    int(cached),
                    cache_hit=True,
                )

        unavailable: list[TransitUnavailable] = []
        if missing_indexes:
            elements = await self._fetch_matrix(
                request.locations,
                request.locations,
                departure_at=request.departure_at,
            )
            by_pair = {
                (element.origin_index, element.destination_index): element
                for element in elements
            }
            pipe = self._redis.pipeline(transaction=False)
            for index in missing_indexes:
                lookup = lookups[index]
                element = by_pair.get(
                    (lookup.origin_index, lookup.destination_index)
                )
                if element is None:
                    raise RoutesResponseError(
                        "MALFORMED_RESPONSE",
                        "route matrix omitted a requested pair",
                    )
                try:
                    seconds = self._element_seconds(element)
                except RoutesRouteUnavailable as exc:
                    unavailable.append(
                        TransitUnavailable(
                            origin=lookup.request.origin,
                            destination=lookup.request.destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            status=exc.status,
                            detail=exc.detail,
                        )
                    )
                    continue
                results[index] = _duration(
                    lookup.request,
                    seconds,
                    cache_hit=False,
                )
                pipe.set(keys[index], seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
            await pipe.execute()

        return TransitMatrix(
            legs=[leg for leg in results if leg is not None],
            unavailable=unavailable,
        )


__all__ = [
    "GoogleRoutesClient",
    "RoutesConfigurationError",
    "RoutesError",
    "RoutesRateLimited",
    "RoutesResponseError",
    "RoutesRouteUnavailable",
    "parse_duration_seconds",
]
