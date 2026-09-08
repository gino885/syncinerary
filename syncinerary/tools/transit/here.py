"""HERE Transit v8 adapter, used only for arcs the primary provider missed.

HERE publishes no transit matrix endpoint, so this adapter routes one arc per
request. That is affordable precisely because it never sees a whole day: the
resolver hands it the leftovers, bounded by HERE_MAX_ARCS_PER_REQUEST and run
at HERE_MAX_CONCURRENCY.

The adapter is optional. With no HERE_API_KEY configured it is never built,
and the chain is Google then estimate exactly as before.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from math import ceil
from typing import Any, Self

import httpx
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.config.transit import (
    HERE_MAX_ARCS_PER_REQUEST,
    HERE_MAX_CONCURRENCY,
    HERE_TIMEOUT_SECONDS,
    HERE_TRANSIT_ROUTES_URL,
    TRANSIT_CACHE_TTL_SECONDS,
)
from syncinerary.store.redis import get_redis
from syncinerary.tools.transit.errors import TransitFailureKind, TransitProviderError
from syncinerary.tools.transit.models import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRequest,
    TransitUnavailable,
    choose_mode,
)

PROVIDER_NAME = "here"


class HereError(TransitProviderError):
    """Base class for typed HERE failures."""


class HereConfigurationError(HereError):
    """No API key, or a request beyond this adapter's bounded size."""

    kind = TransitFailureKind.UNSUPPORTED


class HereResponseError(HereError):
    """HERE rejected the request or returned something unusable."""

    def __init__(self, status: str, message: str | None = None) -> None:
        self.status = status
        self.detail = message
        suffix = f": {message}" if message else ""
        super().__init__(f"HERE Transit returned {status}{suffix}")


class HereRouteUnavailable(HereResponseError):
    """HERE found no public transport route for one directed pair."""

    kind = TransitFailureKind.NO_ROUTE


class HereRateLimited(HereResponseError):
    """The HERE plan's request rate or quota was exceeded."""

    kind = TransitFailureKind.RATE_LIMITED


class _TravelSummary(BaseModel):
    duration: float = Field(gt=0)
    length: int | None = None


class _Section(BaseModel):
    travel_summary: _TravelSummary | None = Field(default=None, alias="travelSummary")


class _Route(BaseModel):
    sections: list[_Section] = Field(default_factory=list)


class _RoutesResponse(BaseModel):
    routes: list[_Route] = Field(default_factory=list)


def _coordinate(location: TransitLocation) -> str:
    return f"{location.lat:.6f},{location.lng:.6f}"


def _cache_key(request: TransitRequest) -> str:
    return (
        f"transit:here:v1:{request.origin.cache_id}:{request.destination.cache_id}:"
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
        provider=PROVIDER_NAME,
    )


class HereTransitClient:
    """Route single arcs through HERE Transit v8, with the same leg cache."""

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        api_key: str | None = None,
        redis: Redis | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_arcs: int = HERE_MAX_ARCS_PER_REQUEST,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.here_api_key
        self._redis = redis if redis is not None else get_redis()
        self._http = http_client or httpx.AsyncClient(timeout=HERE_TIMEOUT_SECONDS)
        self._owns_http = http_client is None
        self._max_arcs = max_arcs

    @classmethod
    def is_configured(cls, api_key: str | None = None) -> bool:
        """Whether this adapter has what it needs to be worth building."""
        return bool(api_key if api_key is not None else settings.here_api_key)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _require_key(self) -> str:
        if not self._api_key:
            raise HereConfigurationError("HERE_API_KEY is not configured")
        return self._api_key

    async def _fetch_route_seconds(
        self,
        origin: TransitLocation,
        destination: TransitLocation,
        *,
        departure_at: datetime | None,
    ) -> int | None:
        """Seconds for this arc, or ``None`` when HERE reports no route."""
        params: dict[str, Any] = {
            "origin": _coordinate(origin),
            "destination": _coordinate(destination),
            "return": "travelSummary",
            "alternatives": 0,
            "apiKey": self._require_key(),
        }
        if departure_at is not None:
            # HERE wants the traveler's local wall clock with its offset, which
            # is exactly the departure the rest of the pipeline planned around.
            params["departureTime"] = departure_at.isoformat()
        try:
            response = await self._http.get(HERE_TRANSIT_ROUTES_URL, params=params)
            if response.status_code == 429:
                raise HereRateLimited("HTTP_429", "request rate or quota exceeded")
            response.raise_for_status()
            payload = _RoutesResponse.model_validate(response.json())
        except HereError:
            raise
        except httpx.HTTPStatusError as exc:
            raise HereResponseError(
                "HTTP_ERROR",
                f"HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            raise HereResponseError("HTTP_ERROR", type(exc).__name__) from exc
        except (ValueError, ValidationError) as exc:
            raise HereResponseError("MALFORMED_RESPONSE", "invalid routes JSON") from exc

        summaries = [
            section.travel_summary.duration
            for route in payload.routes
            for section in route.sections
            if section.travel_summary is not None
        ]
        if not summaries:
            # An empty routes array is HERE saying no journey exists, which is
            # an answer, not a failure. The resolver keeps looking.
            return None
        # Sections are the legs of one journey, so the trip is their sum.
        return max(1, ceil(sum(summaries)))

    async def duration(self, request: TransitRequest) -> TransitDuration:
        key = _cache_key(request)
        cached = await self._redis.get(key)
        if cached is not None:
            return _duration(request, int(cached), cache_hit=True)
        seconds = await self._fetch_route_seconds(
            request.origin,
            request.destination,
            departure_at=request.departure_at,
        )
        if seconds is None:
            raise HereRouteUnavailable("ROUTE_NOT_FOUND")
        await self._redis.set(key, seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
        return _duration(request, seconds, cache_hit=False)

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        """Route each requested arc, bounded in count and concurrency."""
        lookups = [
            TransitRequest(
                origin=request.locations[origin_index],
                destination=request.locations[destination_index],
                mode=TransitMode.TRANSIT,
                departure_window=request.departure_window,
                departure_at=request.departure_at,
            )
            for origin_index in range(len(request.locations))
            for destination_index in range(len(request.locations))
            if origin_index != destination_index
            and request.wants(origin_index, destination_index)
            and choose_mode(
                request.locations[origin_index],
                request.locations[destination_index],
                walking_cutoff_km=request.walking_cutoff_km,
            )
            is TransitMode.TRANSIT
        ]
        if not lookups:
            return TransitMatrix(legs=[])
        if len(lookups) > self._max_arcs:
            raise HereConfigurationError(
                f"HERE fallback covers at most {self._max_arcs} arcs per request"
            )
        self._require_key()

        keys = [_cache_key(lookup) for lookup in lookups]
        cached_values = await self._redis.mget(keys)
        legs: list[TransitDuration] = []
        unavailable: list[TransitUnavailable] = []
        pending: list[int] = []
        for index, cached in enumerate(cached_values):
            if cached is None:
                pending.append(index)
            else:
                legs.append(_duration(lookups[index], int(cached), cache_hit=True))

        if pending:
            limit = asyncio.Semaphore(HERE_MAX_CONCURRENCY)

            async def fetch(index: int) -> int | None:
                async with limit:
                    return await self._fetch_route_seconds(
                        lookups[index].origin,
                        lookups[index].destination,
                        departure_at=request.departure_at,
                    )

            results = await asyncio.gather(*(fetch(index) for index in pending))
            pipe = self._redis.pipeline(transaction=False)
            writes = 0
            for index, seconds in zip(pending, results, strict=True):
                if seconds is None:
                    unavailable.append(
                        TransitUnavailable(
                            origin=lookups[index].origin,
                            destination=lookups[index].destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            status="ROUTE_NOT_FOUND",
                        )
                    )
                    continue
                legs.append(_duration(lookups[index], seconds, cache_hit=False))
                pipe.set(keys[index], seconds, ex=TRANSIT_CACHE_TTL_SECONDS)
                writes += 1
            if writes:
                await pipe.execute()

        return TransitMatrix(legs=legs, unavailable=unavailable)


__all__ = [
    "PROVIDER_NAME",
    "HereConfigurationError",
    "HereError",
    "HereRateLimited",
    "HereResponseError",
    "HereRouteUnavailable",
    "HereTransitClient",
]
