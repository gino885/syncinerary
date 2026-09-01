"""Routes API transit matrix and Redis cache behavior."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from syncinerary.tools.transit import (
    GoogleRoutesClient,
    PairwiseTransitRequest,
    RoutesConfigurationError,
    RoutesRateLimited,
    RoutesResponseError,
    TransitLocation,
    TransitMode,
    TransitRequest,
    choose_mode,
    parse_duration_seconds,
)


class FakePipeline:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.pending: list[tuple[str, str]] = []
        self.executions = 0

    def set(self, key: str, value: int, *, ex: int) -> FakePipeline:
        assert ex > 0
        self.pending.append((key, str(value)))
        return self

    async def execute(self) -> list[bool]:
        self.executions += 1
        for key, value in self.pending:
            self.values[key] = value
        return [True] * len(self.pending)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.mget_calls = 0
        self.last_pipeline: FakePipeline | None = None

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: int, *, ex: int) -> bool:
        assert ex > 0
        self.values[key] = str(value)
        return True

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.mget_calls += 1
        return [self.values.get(key) for key in keys]

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is False
        self.last_pipeline = FakePipeline(self.values)
        return self.last_pipeline


def _location(lat: float, lng: float, place_id: str | None = None) -> TransitLocation:
    return TransitLocation(lat=lat, lng=lng, place_id=place_id)


def _request(*, mode: TransitMode = TransitMode.TRANSIT) -> TransitRequest:
    return TransitRequest(
        origin=_location(43.0605, 141.3469),
        destination=_location(43.1988, 140.9947),
        mode=mode,
        departure_window="morning",
        departure_at=datetime(2026, 9, 2, 9, tzinfo=UTC),
    )


def _matrix_elements(size: int, *, duration: str = "600s") -> list[dict]:
    return [
        {
            "originIndex": origin,
            "destinationIndex": destination,
            "status": {},
            "condition": "ROUTE_EXISTS",
            "distanceMeters": 2_500,
            "duration": duration,
        }
        for origin in range(size)
        for destination in range(size)
    ]


def _ok_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=_matrix_elements(len(body["origins"])))

    return httpx.MockTransport(handler)


def test_place_id_and_coordinates_have_stable_cache_identities():
    with_place = _location(43.06, 141.35, "ChIJ-test")
    coordinates_only = _location(43.06, 141.35)

    assert with_place.cache_id == "place:ChIJ-test"
    assert coordinates_only.cache_id == "ll:43.060000,141.350000"


def test_nearby_pairs_walk_and_longer_pairs_use_public_transit():
    odori = _location(43.0605, 141.3469)
    clock_tower = _location(43.0626, 141.3536)
    otaru = _location(43.1988, 140.9947)

    assert choose_mode(odori, clock_tower) is TransitMode.WALKING
    assert choose_mode(odori, otaru) is TransitMode.TRANSIT


def test_transit_departure_must_be_timezone_aware():
    with pytest.raises(ValidationError, match="timezone-aware"):
        TransitRequest(
            origin=_location(43.06, 141.35),
            destination=_location(43.07, 141.36),
            mode=TransitMode.TRANSIT,
            departure_window="morning",
            departure_at=datetime(2026, 9, 2, 9),  # noqa: DTZ001
        )


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [("578s", 578), ("3.5s", 4), ("0.1s", 1)],
)
def test_routes_duration_parser_rounds_up(raw: str, seconds: int):
    assert parse_duration_seconds(raw) == seconds


@pytest.mark.parametrize("raw", ["", "578", "nope", "0s", "-2s"])
def test_invalid_routes_durations_are_rejected(raw: str):
    with pytest.raises(RoutesResponseError, match="MALFORMED_RESPONSE"):
        parse_duration_seconds(raw)


async def test_transit_request_uses_routes_post_shape_and_caches_duration():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        first = await client.duration(_request())
        second = await client.duration(_request())

    assert first.duration_seconds == 600
    assert first.duration_minutes == 10
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    )
    assert request.headers["X-Goog-Api-Key"] == "test-key"
    assert request.headers["X-Goog-FieldMask"] == (
        "originIndex,destinationIndex,status,condition,distanceMeters,duration"
    )
    body = json.loads(request.content)
    assert body["travelMode"] == "TRANSIT"
    assert body["departureTime"] == "2026-09-02T09:00:00Z"
    assert body["origins"][0]["waypoint"]["location"]["latLng"] == {
        "latitude": 43.0605,
        "longitude": 141.3469,
    }
    assert "test-key" not in str(request.url)
    assert all("test-key" not in key for key in redis.values)


async def test_routes_request_prefers_place_ids_when_available():
    calls: list[httpx.Request] = []
    request = _request().model_copy(
        update={
            "origin": _location(43.06, 141.35, "origin-place"),
            "destination": _location(43.19, 140.99, "destination-place"),
        }
    )
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        await client.duration(request)

    body = json.loads(calls[0].content)
    assert body["origins"][0]["waypoint"] == {"placeId": "origin-place"}
    assert body["destinations"][0]["waypoint"] == {
        "placeId": "destination-place"
    }


async def test_nearby_walking_duration_is_estimated_without_google_request():
    calls: list[httpx.Request] = []
    request = TransitRequest(
        origin=_location(43.0605, 141.3469),
        destination=_location(43.0626, 141.3536),
        mode=TransitMode.WALKING,
        departure_window="morning",
    )
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        duration = await client.duration(request)

    assert duration.mode is TransitMode.WALKING
    assert duration.duration_minutes >= 5
    assert calls == []


async def test_missing_key_fails_before_a_transit_http_request():
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        with pytest.raises(RoutesConfigurationError, match="GOOGLE_MAPS_API_KEY"):
            await client.duration(_request())
    assert calls == []


async def test_pairwise_prefetch_uses_one_matrix_call_and_caches_long_pairs():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    locations = [
        _location(43.0605, 141.3469),
        _location(43.0626, 141.3536),
        _location(43.1988, 140.9947),
    ]
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        first = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )
        second = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert len(first.legs) == 4
    assert {leg.mode for leg in first.legs} == {TransitMode.TRANSIT}
    assert all(not leg.cache_hit for leg in first.legs)
    assert all(leg.cache_hit for leg in second.legs)
    assert len(calls) == 1
    assert redis.mget_calls == 2
    assert redis.last_pipeline is not None
    assert redis.last_pipeline.executions == 1


async def test_an_all_walking_day_needs_no_routes_request():
    calls: list[httpx.Request] = []
    locations = [
        _location(43.0605, 141.3469),
        _location(43.0626, 141.3536),
    ]
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert matrix.legs == []
    assert calls == []


async def test_route_not_found_is_reported_without_losing_other_long_legs():
    def handler(request: httpx.Request) -> httpx.Response:
        size = len(json.loads(request.content)["origins"])
        elements = _matrix_elements(size)
        elements[2] = {
            "originIndex": 0,
            "destinationIndex": 2,
            "status": {},
            "condition": "ROUTE_NOT_FOUND",
        }
        return httpx.Response(200, json=list(reversed(elements)))

    locations = [
        _location(43.0605, 141.3469),
        _location(43.0626, 141.3536),
        _location(43.1988, 140.9947),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleRoutesClient(
            api_key="test-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert len(matrix.legs) == 3
    assert len(matrix.unavailable) == 1
    assert matrix.unavailable[0].status == "ROUTE_NOT_FOUND"


async def test_http_429_is_typed_and_does_not_expose_the_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleRoutesClient(
            api_key="secret-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        with pytest.raises(RoutesRateLimited) as captured:
            await client.duration(_request())

    assert "secret-key" not in str(captured.value)


async def test_matrix_element_quota_error_does_not_require_a_route_condition():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "originIndex": 0,
                    "destinationIndex": 0,
                    "status": {"code": 8, "message": "quota exhausted"},
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleRoutesClient(
            api_key="secret-key", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        with pytest.raises(RoutesRateLimited, match="RESOURCE_EXHAUSTED"):
            await client.duration(_request())


async def test_route_matrix_rejects_more_than_ten_transit_locations():
    locations = [_location(43.0 + index / 10, 141.0) for index in range(11)]
    client = GoogleRoutesClient(api_key="test-key", redis=FakeRedis())  # type: ignore[arg-type]
    try:
        with pytest.raises(RoutesConfigurationError, match="at most 10"):
            await client.prefetch_pairwise(
                PairwiseTransitRequest(
                    locations=locations,
                    departure_window="morning",
                    walking_cutoff_km=0.1,
                )
            )
    finally:
        await client.aclose()
