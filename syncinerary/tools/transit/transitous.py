"""Prototype-only Transitous public transport client.

The hosted endpoint permits light, open-source, non-commercial prototypes.
Production deployments must use a contracted provider or a self-hosted MOTIS
instance. See https://transitous.org/api/ before changing that boundary.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any, Self

import httpx
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis

from syncinerary.config.transit import (
    TRANSIT_CACHE_TTL_SECONDS,
    TRANSITOUS_MAX_TRAVEL_MINUTES,
    TRANSITOUS_ONE_TO_MANY_URL,
    TRANSITOUS_TIMEOUT_SECONDS,
    TRANSITOUS_USER_AGENT,
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

MAX_TRANSITOUS_LOCATIONS = 10


class TransitousError(RuntimeError):
    """Base class for typed Transitous failures."""


class TransitousConfigurationError(TransitousError):
    """The prototype request exceeds its bounded size."""


class TransitousResponseError(TransitousError):
    """Transitous rejected the request or returned malformed data."""

    def __init__(self, status: str, message: str | None = None) -> None:
        self.status = status
        self.detail = message
        suffix = f": {message}" if message else ""
        super().__init__(f"Transitous returned {status}{suffix}")


class TransitousRouteUnavailable(TransitousResponseError):
    """Transitous found no public transport route for one pair."""


class TransitousRateLimited(TransitousResponseError):
    """The shared prototype endpoint asked the client to slow down."""


class _IntermodalDuration(BaseModel):
    duration: float = Field(gt=0)
    transfers: int = Field(default=0, ge=0)


class _OneToManyResponse(BaseModel):
    street_durations: list[dict[str, Any]]
    transit_durations: list[list[_IntermodalDuration]]


@dataclass(frozen=True)
class _IndexedLookup:
    origin_index: int
    destination_index: int
    request: TransitRequest


def _coordinate(location: TransitLocation) -> str:
    return f"{location.lat:.6f};{location.lng:.6f}"


def _cache_key(request: TransitRequest) -> str:
    return (
        f"transit:transitous:v1:{_coordinate(request.origin)}:"
        f"{_coordinate(request.destination)}:{request.mode.value}:"
        f"{request.departure_window}"
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
        provider="transitous",
    )


def _walking_seconds(request: TransitRequest) -> int:
    minutes = max(5, round(haversine_km(request.origin, request.destination) * 12))
    return minutes * 60


class TransitousClient:
    """Fetch bounded one-to-many transit rows and cache every directed leg."""

    def __init__(
        self,
        *,
        redis: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._redis = redis if redis is not None else get_redis()
        self._http = http_client or httpx.AsyncClient(
            timeout=TRANSITOUS_TIMEOUT_SECONDS,
            headers={"User-Agent": TRANSITOUS_USER_AGENT},
        )
        self._owns_http = http_client is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _fetch_one_to_many(
        self,
        origin: TransitLocation,
        destinations: list[TransitLocation],
        *,
        departure_at: datetime | None,
    ) -> list[int | None]:
        params: dict[str, str | int] = {
            "one": _coordinate(origin),
            "many": ",".join(_coordinate(item) for item in destinations),
            "maxTravelTime": TRANSITOUS_MAX_TRAVEL_MINUTES,
            "arriveBy": "false",
            "transitModes": "TRANSIT",
            "directMode": "WALK",
        }
        if departure_at is not None:
            params["time"] = departure_at.isoformat()
        try:
            response = await self._http.get(
                TRANSITOUS_ONE_TO_MANY_URL,
                headers={"User-Agent": TRANSITOUS_USER_AGENT},
                params=params,
            )
            if response.status_code == 429:
                raise TransitousRateLimited("HTTP_429", "shared endpoint rate limit")
            response.raise_for_status()
            payload = _OneToManyResponse.model_validate(response.json())
        except TransitousError:
            raise
        except httpx.HTTPStatusError as exc:
            raise TransitousResponseError(
                "HTTP_ERROR",
                f"HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            raise TransitousResponseError("HTTP_ERROR", type(exc).__name__) from exc
        except (ValueError, ValidationError) as exc:
            raise TransitousResponseError(
                "MALFORMED_RESPONSE",
                "invalid one-to-many JSON",
            ) from exc

        if len(payload.transit_durations) != len(destinations):
            raise TransitousResponseError(
                "MALFORMED_RESPONSE",
                "transit duration count did not match destinations",
            )
        return [
            ceil(min(option.duration for option in options)) if options else None
            for options in payload.transit_durations
        ]

    async def duration(self, request: TransitRequest) -> TransitDuration:
        key = _cache_key(request)
        cached = await self._redis.get(key)
        if cached is not None:
            return _duration(request, int(cached), cache_hit=True)

        if request.mode is TransitMode.WALKING:
            seconds = _walking_seconds(request)
        else:
            values = await self._fetch_one_to_many(
                request.origin,
                [request.destination],
                departure_at=request.departure_at,
            )
            if values[0] is None:
                raise TransitousRouteUnavailable("ROUTE_NOT_FOUND")
            seconds = values[0]
        await self._redis.set(key, seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
        return _duration(request, seconds, cache_hit=False)

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
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
        if len(request.locations) > MAX_TRANSITOUS_LOCATIONS:
            raise TransitousConfigurationError(
                "The prototype transit provider supports at most 10 locations"
            )

        keys = [_cache_key(item.request) for item in lookups]
        cached_values = await self._redis.mget(keys)
        results: list[TransitDuration | None] = [None] * len(lookups)
        missing_by_origin: dict[int, list[int]] = defaultdict(list)
        for index, cached in enumerate(cached_values):
            if cached is None:
                missing_by_origin[lookups[index].origin_index].append(index)
            else:
                results[index] = _duration(
                    lookups[index].request,
                    int(cached),
                    cache_hit=True,
                )

        unavailable: list[TransitUnavailable] = []
        pipe = self._redis.pipeline(transaction=False)
        pending_writes = 0
        for origin_index, indexes in missing_by_origin.items():
            values = await self._fetch_one_to_many(
                request.locations[origin_index],
                [lookups[index].request.destination for index in indexes],
                departure_at=request.departure_at,
            )
            for index, seconds in zip(indexes, values, strict=True):
                lookup = lookups[index]
                if seconds is None:
                    unavailable.append(
                        TransitUnavailable(
                            origin=lookup.request.origin,
                            destination=lookup.request.destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            status="ROUTE_NOT_FOUND",
                        )
                    )
                    continue
                results[index] = _duration(
                    lookup.request,
                    seconds,
                    cache_hit=False,
                )
                pipe.set(keys[index], seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
                pending_writes += 1
        if pending_writes:
            await pipe.execute()

        return TransitMatrix(
            legs=[leg for leg in results if leg is not None],
            unavailable=unavailable,
        )


__all__ = [
    "TransitousClient",
    "TransitousConfigurationError",
    "TransitousError",
    "TransitousRateLimited",
    "TransitousResponseError",
    "TransitousRouteUnavailable",
]
