"""M1-7a: Google Directions transit tool and Redis cache."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from syncinerary.tools.transit import (
    DirectionsConfigurationError,
    DirectionsRateLimited,
    DirectionsResponseError,
    DirectionsRouteUnavailable,
    GoogleDirectionsClient,
    PairwiseTransitRequest,
    TransitLocation,
    TransitMode,
    TransitRequest,
    choose_mode,
    parse_duration_seconds,
)

RECORDED_RESPONSE = (
    Path(__file__).parent / "fixtures" / "google_directions_walking_ok.json"
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


def _request(*, mode: TransitMode = TransitMode.WALKING) -> TransitRequest:
    return TransitRequest(
        origin=_location(43.0605, 141.3469),
        destination=_location(43.0626, 141.3536),
        mode=mode,
        departure_window="morning",
        departure_at=datetime(2026, 8, 24, 9, tzinfo=UTC),
    )


def _ok_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    payload = json.loads(RECORDED_RESPONSE.read_text(encoding="utf-8"))["response"]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


# ----- typed models and mode selection -----


def test_place_id_is_preferred_and_coordinates_are_the_m1_fallback():
    with_place = _location(43.06, 141.35, "ChIJ-test")
    coordinates_only = _location(43.06, 141.35)

    assert with_place.google_value == "place_id:ChIJ-test"
    assert with_place.cache_id == "place:ChIJ-test"
    assert coordinates_only.google_value == "43.060000,141.350000"
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
            departure_at=datetime(2026, 8, 24, 9),  # noqa: DTZ001, intentionally invalid
        )


# ----- recorded response parser -----


def test_parser_reads_duration_from_a_recorded_real_response():
    recorded = json.loads(RECORDED_RESPONSE.read_text(encoding="utf-8"))
    assert "recorded_from" in recorded
    assert parse_duration_seconds(recorded["response"]) == 578


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        ("ZERO_RESULTS", DirectionsRouteUnavailable),
        ("OVER_QUERY_LIMIT", DirectionsRateLimited),
        ("OVER_DAILY_LIMIT", DirectionsRateLimited),
        ("REQUEST_DENIED", DirectionsResponseError),
    ],
)
def test_non_ok_google_statuses_are_typed(status: str, error_type: type[Exception]):
    with pytest.raises(error_type, match=status):
        parse_duration_seconds({"status": status})


def test_ok_response_without_a_leg_is_malformed():
    with pytest.raises(DirectionsResponseError, match="MALFORMED_RESPONSE"):
        parse_duration_seconds({"status": "OK", "routes": []})


# ----- client and cache -----


async def test_client_sends_typed_request_and_caches_the_duration():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleDirectionsClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        first = await client.duration(_request())
        second = await client.duration(_request())

    assert first.duration_seconds == 578
    assert first.duration_minutes == 10
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(calls) == 1
    assert calls[0].url.params["mode"] == "walking"
    assert "departure_time" not in calls[0].url.params
    assert all("test-key" not in key for key in redis.values)


async def test_transit_request_sends_departure_timestamp():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleDirectionsClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        await client.duration(_request(mode=TransitMode.TRANSIT))

    assert calls[0].url.params["departure_time"] == str(
        int(datetime(2026, 8, 24, 9, tzinfo=UTC).timestamp())
    )


async def test_missing_key_fails_before_an_http_request():
    calls: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleDirectionsClient(
            api_key="", redis=FakeRedis(), http_client=http  # type: ignore[arg-type]
        )
        with pytest.raises(DirectionsConfigurationError, match="GOOGLE_MAPS_API_KEY"):
            await client.duration(_request())
    assert calls == []


async def test_pairwise_prefetch_batches_cache_reads_and_writes():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    locations = [
        _location(43.0605, 141.3469),
        _location(43.0626, 141.3536),
        _location(43.0542, 141.3075),
    ]
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleDirectionsClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        first = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )
        second = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert len(first.legs) == 6
    assert all(not leg.cache_hit for leg in first.legs)
    assert all(leg.cache_hit for leg in second.legs)
    assert len(calls) == 6
    assert redis.mget_calls == 2
    assert redis.last_pipeline is not None
    assert redis.last_pipeline.executions == 1


async def test_pairwise_prefetch_uses_both_selected_modes():
    calls: list[httpx.Request] = []
    redis = FakeRedis()
    locations = [
        _location(43.0605, 141.3469),
        _location(43.0626, 141.3536),
        _location(43.1988, 140.9947),
    ]
    async with httpx.AsyncClient(transport=_ok_transport(calls)) as http:
        client = GoogleDirectionsClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert {leg.mode for leg in matrix.legs} == {
        TransitMode.WALKING,
        TransitMode.TRANSIT,
    }


async def test_pairwise_prefetch_reports_zero_results_without_losing_other_legs():
    calls: list[httpx.Request] = []
    redis = FakeRedis()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "routes": []})
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "routes": [{"legs": [{"duration": {"value": 600}}]}],
            },
        )

    locations = [_location(43.0605, 141.3469), _location(43.0626, 141.3536)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GoogleDirectionsClient(
            api_key="test-key", redis=redis, http_client=http  # type: ignore[arg-type]
        )
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(locations=locations, departure_window="morning")
        )

    assert len(matrix.legs) == 1
    assert len(matrix.unavailable) == 1
    assert matrix.unavailable[0].status == "ZERO_RESULTS"
