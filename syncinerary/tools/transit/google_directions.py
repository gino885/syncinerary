"""Google Directions client with a Redis-backed duration cache."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Self

import httpx
from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.config.transit import (
    DIRECTIONS_MAX_CONCURRENCY,
    DIRECTIONS_TIMEOUT_SECONDS,
    DIRECTIONS_URL,
    TRANSIT_CACHE_TTL_SECONDS,
)
from syncinerary.store.redis import get_redis
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitMatrix,
    TransitMode,
    TransitRequest,
    choose_mode,
)


class DirectionsError(RuntimeError):
    """Base class for typed Google Directions failures."""


class DirectionsConfigurationError(DirectionsError):
    """The API key is absent."""


class DirectionsResponseError(DirectionsError):
    """The response was malformed or Google rejected the request."""

    def __init__(self, status: str, message: str | None = None) -> None:
        self.status = status
        self.detail = message
        suffix = f": {message}" if message else ""
        super().__init__(f"Google Directions returned {status}{suffix}")


class DirectionsRouteUnavailable(DirectionsResponseError):
    """Google found no route for this origin, destination and mode."""


class DirectionsRateLimited(DirectionsResponseError):
    """The Google Directions quota was exhausted."""


def parse_duration_seconds(payload: Mapping[str, Any]) -> int:
    """Parse ``routes[0].legs[0].duration.value`` from a live response."""
    status = str(payload.get("status", "MISSING_STATUS"))
    message = payload.get("error_message")
    if status == "ZERO_RESULTS":
        raise DirectionsRouteUnavailable(status, str(message) if message else None)
    if status in {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}:
        raise DirectionsRateLimited(status, str(message) if message else None)
    if status != "OK":
        raise DirectionsResponseError(status, str(message) if message else None)

    try:
        value = payload["routes"][0]["legs"][0]["duration"]["value"]
        seconds = int(value)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise DirectionsResponseError("MALFORMED_RESPONSE", "missing leg duration") from exc
    if seconds <= 0:
        raise DirectionsResponseError("MALFORMED_RESPONSE", "duration must be positive")
    return seconds


def _cache_key(request: TransitRequest) -> str:
    return (
        f"transit:{request.origin.cache_id}:{request.destination.cache_id}:"
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


class GoogleDirectionsClient:
    """Pluggable Directions implementation.

    One instance owns one HTTP connection pool. Redis is injected for tests
    or taken from the application's process-wide pooled client.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        redis: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.google_maps_api_key
        self._redis = redis if redis is not None else get_redis()
        self._http = http_client or httpx.AsyncClient(timeout=DIRECTIONS_TIMEOUT_SECONDS)
        self._owns_http = http_client is None
        self._semaphore = asyncio.Semaphore(DIRECTIONS_MAX_CONCURRENCY)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _require_key(self) -> str:
        if not self._api_key:
            raise DirectionsConfigurationError("GOOGLE_MAPS_API_KEY is not configured")
        return self._api_key

    async def _fetch(self, request: TransitRequest) -> int:
        params: dict[str, str | int] = {
            "origin": request.origin.google_value,
            "destination": request.destination.google_value,
            "mode": request.mode.value,
            "key": self._require_key(),
        }
        if request.mode is TransitMode.TRANSIT and request.departure_at is not None:
            params["departure_time"] = int(request.departure_at.timestamp())

        async with self._semaphore:
            try:
                response = await self._http.get(DIRECTIONS_URL, params=params)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as exc:
                # httpx's exception string includes the request URL, whose
                # query contains the API key. Report only the status code.
                raise DirectionsResponseError(
                    "HTTP_ERROR", f"HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise DirectionsResponseError("HTTP_ERROR", type(exc).__name__) from exc
            except ValueError as exc:
                raise DirectionsResponseError("MALFORMED_RESPONSE", "invalid JSON") from exc
        return parse_duration_seconds(payload)

    async def duration(self, request: TransitRequest) -> TransitDuration:
        key = _cache_key(request)
        cached = await self._redis.get(key)
        if cached is not None:
            return _duration(request, int(cached), cache_hit=True)

        seconds = await self._fetch(request)
        await self._redis.set(key, seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
        return _duration(request, seconds, cache_hit=False)

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        """Fetch every directed non-self pair, batching Redis I/O.

        Google misses run concurrently under a small semaphore. Any typed
        Directions failure propagates so callers can decide whether an
        unavailable leg makes a candidate unplaceable.
        """
        lookups = [
            TransitRequest(
                origin=origin,
                destination=destination,
                mode=choose_mode(
                    origin,
                    destination,
                    walking_cutoff_km=request.walking_cutoff_km,
                ),
                departure_window=request.departure_window,
                departure_at=request.departure_at,
            )
            for origin in request.locations
            for destination in request.locations
            if origin != destination
        ]
        if not lookups:
            return TransitMatrix(legs=[])

        keys = [_cache_key(item) for item in lookups]
        cached_values = await self._redis.mget(keys)
        results: list[TransitDuration | None] = [None] * len(lookups)
        missing_indexes: list[int] = []
        for index, cached in enumerate(cached_values):
            if cached is None:
                missing_indexes.append(index)
            else:
                results[index] = _duration(lookups[index], int(cached), cache_hit=True)

        if missing_indexes:
            fetched = await asyncio.gather(
                *(self._fetch(lookups[index]) for index in missing_indexes)
            )
            pipe = self._redis.pipeline(transaction=False)
            for index, seconds in zip(missing_indexes, fetched, strict=True):
                results[index] = _duration(lookups[index], seconds, cache_hit=False)
                pipe.set(keys[index], seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
            await pipe.execute()

        return TransitMatrix(legs=[leg for leg in results if leg is not None])
