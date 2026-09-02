"""Prototype-only Transitous routing and cache behavior."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitLocation,
    TransitMode,
    TransitousClient,
    TransitousRateLimited,
    TransitousResponseError,
    TransitRequest,
    make_transit_client,
)


class FakePipeline:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.pending: list[tuple[str, str]] = []

    def set(self, key: str, value: int, *, ex: int) -> FakePipeline:
        assert ex > 0
        self.pending.append((key, str(value)))
        return self

    async def execute(self) -> list[bool]:
        for key, value in self.pending:
            self.values[key] = value
        return [True] * len(self.pending)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: int, *, ex: int) -> bool:
        assert ex > 0
        self.values[key] = str(value)
        return True

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is False
        return FakePipeline(self.values)


def _location(lat: float, lng: float) -> TransitLocation:
    return TransitLocation(lat=lat, lng=lng)


def _request(*, mode: TransitMode = TransitMode.TRANSIT) -> TransitRequest:
    return TransitRequest(
        origin=_location(43.0687, 141.3508),
        destination=_location(43.1970, 140.9947),
        mode=mode,
        departure_window="2026-09-02-0900",
        departure_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
    )


def _response(count: int, *, duration: float = 2_580) -> dict[str, Any]:
    return {
        "street_durations": [{} for _ in range(count)],
        "transit_durations": [
            [{"duration": duration + index * 60, "transfers": index % 2}]
            for index in range(count)
        ],
    }


async def test_duration_uses_identified_transitous_request_and_cache():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response(1))

    redis = FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=redis, http_client=http)  # type: ignore[arg-type]
        first = await client.duration(_request())
        second = await client.duration(_request())

    assert first.duration_seconds == 2_580
    assert first.duration_minutes == 43
    assert first.provider == "transitous"
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "GET"
    assert request.url.path == "/api/experimental/one-to-many-intermodal"
    assert request.url.params["one"] == "43.068700;141.350800"
    assert request.url.params["many"] == "43.197000;140.994700"
    assert request.url.params["transitModes"] == "TRANSIT"
    assert request.url.params["directMode"] == "WALK"
    assert "Syncinerary/" in request.headers["User-Agent"]
    assert "github.com/gino885/syncinerary" in request.headers["User-Agent"]


async def test_pairwise_prefetch_batches_each_origin_and_caches_the_result():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        destination_count = len(request.url.params["many"].split(","))
        return httpx.Response(200, json=_response(destination_count, duration=900))

    locations = [
        _location(43.0687, 141.3508),
        _location(43.1970, 140.9947),
        _location(42.9849, 144.3814),
    ]
    redis = FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=redis, http_client=http)  # type: ignore[arg-type]
        first = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=locations,
                departure_window="2026-09-02-0900",
                departure_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
                walking_cutoff_km=0.1,
            )
        )
        second = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=locations,
                departure_window="2026-09-02-0900",
                departure_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
                walking_cutoff_km=0.1,
            )
        )

    assert len(first.legs) == 6
    assert all(leg.provider == "transitous" for leg in first.legs)
    assert all(not leg.cache_hit for leg in first.legs)
    assert all(leg.cache_hit for leg in second.legs)
    assert len(calls) == 3


async def test_missing_transitous_route_is_reported_per_pair():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"street_durations": [{}], "transit_durations": [[]]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=FakeRedis(), http_client=http)  # type: ignore[arg-type]
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[_request().origin, _request().destination],
                departure_window="2026-09-02-0900",
                departure_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
                walking_cutoff_km=0.1,
            )
        )

    assert matrix.legs == []
    assert len(matrix.unavailable) == 2
    assert {item.status for item in matrix.unavailable} == {"ROUTE_NOT_FOUND"}


async def test_transitous_rejects_malformed_duration_lists():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"street_durations": [], "transit_durations": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=FakeRedis(), http_client=http)  # type: ignore[arg-type]
        with pytest.raises(TransitousResponseError, match="MALFORMED_RESPONSE"):
            await client.duration(_request())


async def test_transitous_rate_limit_is_typed():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=FakeRedis(), http_client=http)  # type: ignore[arg-type]
        with pytest.raises(TransitousRateLimited, match="HTTP_429"):
            await client.duration(_request())


async def test_all_walking_day_needs_no_transitous_request():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_response(1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TransitousClient(redis=FakeRedis(), http_client=http)  # type: ignore[arg-type]
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[
                    _location(43.0605, 141.3469),
                    _location(43.0626, 141.3536),
                ],
                departure_window="2026-09-02-0900",
            )
        )

    assert matrix.legs == []
    assert calls == []


async def test_transit_provider_factory_keeps_transitous_explicitly_opt_in():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)) as http:
        transitous = make_transit_client(
            provider="transitous",
            redis=FakeRedis(),  # type: ignore[arg-type]
            http_client=http,
        )
        google = make_transit_client(
            provider="google",
            redis=FakeRedis(),  # type: ignore[arg-type]
            http_client=http,
        )

        assert isinstance(transitous, TransitousClient)
        assert type(google).__name__ == "GoogleRoutesClient"


def test_unknown_transit_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown transit provider"):
        make_transit_client(
            provider="surprise",
            redis=FakeRedis(),  # type: ignore[arg-type]
        )
