"""The transit chain: what happens between a provider missing and a lost arc.

A missing arc is not a slow leg. In the Stage 2 circuit it says two places
cannot share a day, which no single provider is entitled to claim. These tests
pin the order the chain asks in, what it costs, and where it stops.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest

from syncinerary.agents.solver.stage2_route import solve_day
from syncinerary.config.solver import ESTIMATED_TRANSIT_MAX_KM
from syncinerary.domain.models import CandidatePlace, CandidateType
from syncinerary.tools.transit import (
    FallbackTransitResolver,
    HereTransitClient,
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    TransitRoutingStatus,
    TransitUnavailable,
    make_transit_client,
    regional_provider_registry,
    transit_chain_names,
)
from syncinerary.tools.transit.errors import TransitProviderError
from syncinerary.tools.transit.google_routes import RoutesRateLimited, RoutesResponseError
from syncinerary.tools.transit.here import HereConfigurationError
from syncinerary.tools.transit.registry import TransitRegion

DEPARTURE = datetime(2026, 5, 21, 9, tzinfo=UTC)
WINDOW = "2026-05-21-0900"


class FakePipeline:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.pending: list[tuple[str, str]] = []

    def set(self, key: str, value: int, *, ex: int) -> FakePipeline:
        assert ex > 0
        self.pending.append((key, str(value)))
        return self

    async def execute(self) -> list[bool]:
        self.values.update(self.pending)
        return [True] * len(self.pending)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: int, *, ex: int) -> bool:
        self.values[key] = str(value)
        return True

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.values.get(key) for key in keys]

    def pipeline(self, *, transaction: bool) -> FakePipeline:
        assert transaction is False
        return FakePipeline(self.values)


def _at(lat: float, lng: float) -> TransitLocation:
    return TransitLocation(lat=lat, lng=lng)


#: Four places across one city, every pair past the walking cutoff and well
#: inside the estimate ceiling: the 4 to 9 km shape that lost a real day.
CITY = [
    _at(43.100, 141.350),
    _at(43.060, 141.350),
    _at(43.030, 141.360),
    _at(43.060, 141.420),
]
#: A pair a provider may honestly be unable to route: about 65 km apart.
FAR = [_at(43.060, 141.350), _at(43.400, 142.100)]


def _request(locations: list[TransitLocation]) -> PairwiseTransitRequest:
    return PairwiseTransitRequest(
        locations=locations,
        departure_window=WINDOW,
        departure_at=DEPARTURE,
    )


class StubProvider:
    """A provider that routes the pairs it was told to and misses the rest."""

    def __init__(
        self,
        name: str,
        *,
        routes: set[tuple[int, int]] | None = None,
        routes_all: bool = False,
        raises: Exception | None = None,
        minutes: int = 20,
    ) -> None:
        self.name = name
        self._routes = routes or set()
        self._routes_all = routes_all
        self._raises = raises
        self._minutes = minutes
        self.calls: list[PairwiseTransitRequest] = []
        self.closed = False

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.calls.append(request)
        if self._raises is not None:
            raise self._raises
        legs: list[TransitDuration] = []
        unavailable: list[TransitUnavailable] = []
        for origin_index, origin in enumerate(request.locations):
            for destination_index, destination in enumerate(request.locations):
                if origin_index == destination_index:
                    continue
                if not request.wants(origin_index, destination_index):
                    continue
                key = (_index_of(origin), _index_of(destination))
                if self._routes_all or key in self._routes:
                    legs.append(
                        TransitDuration(
                            origin=origin,
                            destination=destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            duration_seconds=self._minutes * 60,
                            duration_minutes=self._minutes,
                            provider=self.name,
                        )
                    )
                else:
                    unavailable.append(
                        TransitUnavailable(
                            origin=origin,
                            destination=destination,
                            mode=TransitMode.TRANSIT,
                            departure_window=request.departure_window,
                            status="ROUTE_NOT_FOUND",
                        )
                    )
        return TransitMatrix(legs=legs, unavailable=unavailable)

    async def aclose(self) -> None:
        self.closed = True


def _index_of(location: TransitLocation) -> int:
    """Stable identity for a stub's routing table, independent of reindexing."""
    for index, known in enumerate(CITY + FAR):
        if known.cache_id == location.cache_id:
            return index
    raise AssertionError("unknown stub location")


def _asked_pairs(request: PairwiseTransitRequest) -> set[tuple[int, int]]:
    """Which of the well-known places one provider was actually asked about."""
    return {
        (_index_of(request.locations[origin]), _index_of(request.locations[destination]))
        for origin in range(len(request.locations))
        for destination in range(len(request.locations))
        if origin != destination and request.wants(origin, destination)
    }


def _pair(matrix: TransitMatrix, origin: int, destination: int) -> TransitDuration | None:
    for leg in matrix.legs:
        if (_index_of(leg.origin), _index_of(leg.destination)) == (origin, destination):
            return leg
    return None


# ----- A: the primary answers and nothing else is spent -----


async def test_a_primary_success_stops_the_chain():
    primary = StubProvider("google", routes_all=True)
    secondary = StubProvider("here", routes_all=True)

    matrix = await FallbackTransitResolver([primary, secondary]).prefetch_pairwise(
        _request(CITY)
    )

    assert len(matrix.legs) == 12
    assert {leg.provider for leg in matrix.legs} == {"google"}
    assert all(leg.routing_status is TransitRoutingStatus.ROUTED for leg in matrix.legs)
    assert secondary.calls == []


# ----- B: the primary misses, the secondary is believed -----


async def test_b_secondary_route_is_a_real_route_not_an_approximation():
    primary = StubProvider("google")
    secondary = StubProvider("here", routes_all=True, minutes=41)

    resolver = FallbackTransitResolver([primary, secondary])
    matrix = await resolver.prefetch_pairwise(_request(CITY))

    assert len(matrix.legs) == 12
    assert {leg.provider for leg in matrix.legs} == {"here"}
    # A route from any real provider is a route. Only an estimate is approximate.
    assert all(leg.routing_status is TransitRoutingStatus.ROUTED for leg in matrix.legs)
    assert all(leg.duration_minutes == 41 for leg in matrix.legs)
    assert resolver.stats.routed["secondary"] == 12
    assert resolver.stats.no_route["primary"] == 12
    assert resolver.stats.estimated == 0


# ----- C: nobody routes it, and the city-scale estimate holds the day -----


async def test_c_city_scale_pairs_are_estimated_when_every_provider_misses():
    primary = StubProvider("google")
    secondary = StubProvider("here")

    resolver = FallbackTransitResolver([primary, secondary])
    matrix = await resolver.prefetch_pairwise(_request(CITY))

    assert len(matrix.legs) == 12
    assert matrix.unavailable == []
    assert {leg.provider for leg in matrix.legs} == {"estimated"}
    assert all(
        leg.routing_status is TransitRoutingStatus.ESTIMATED for leg in matrix.legs
    )
    assert resolver.stats.estimated == 12
    assert resolver.stats.unroutable == 0


# ----- D: past the ceiling, an invented journey would strand somebody -----


async def test_d_long_distance_stays_unroutable_after_every_provider_misses():
    resolver = FallbackTransitResolver(
        [StubProvider("google"), StubProvider("here")]
    )

    matrix = await resolver.prefetch_pairwise(_request(FAR))

    assert matrix.legs == []
    assert len(matrix.unavailable) == 2
    assert resolver.stats.unroutable == 2
    assert resolver.stats.estimated == 0


# ----- E: a technical failure is not a verdict about the world -----


@pytest.mark.parametrize(
    "failure",
    [
        RoutesResponseError("HTTP_ERROR", "HTTP 500"),
        RoutesRateLimited("HTTP_429", "quota exhausted"),
        HereConfigurationError("no key"),
    ],
)
async def test_e_recoverable_primary_failure_falls_through_to_the_secondary(
    failure: TransitProviderError,
):
    primary = StubProvider("google", raises=failure)
    secondary = StubProvider("here", routes_all=True)

    resolver = FallbackTransitResolver([primary, secondary])
    matrix = await resolver.prefetch_pairwise(_request(CITY))

    assert len(matrix.legs) == 12
    assert {leg.provider for leg in matrix.legs} == {"here"}
    assert sum(resolver.stats.errors.values()) == 1
    assert next(iter(resolver.stats.errors)).startswith("primary.")


async def test_e2_a_failing_secondary_still_leaves_the_estimate_intact():
    """A fallback that breaks must not be worse than no fallback at all."""
    primary = StubProvider("google")
    secondary = StubProvider("here", raises=RoutesResponseError("HTTP_ERROR", "HTTP 500"))

    resolver = FallbackTransitResolver([primary, secondary])
    matrix = await resolver.prefetch_pairwise(_request(CITY))

    assert len(matrix.legs) == 12
    assert resolver.stats.estimated == 12


# ----- F and G: what the fallback is allowed to cost -----


async def test_f_fallback_is_not_called_when_the_primary_resolves_everything():
    secondary = StubProvider("here", routes_all=True)

    await FallbackTransitResolver(
        [StubProvider("google", routes_all=True), secondary]
    ).prefetch_pairwise(_request(CITY))

    assert secondary.calls == []


async def test_g_fallback_sees_only_the_arcs_the_primary_missed():
    """Not one matrix lookup turned into two, but one plus the leftovers."""
    resolved = {(0, 1), (1, 0), (0, 2), (2, 0), (1, 2), (2, 1), (0, 3), (3, 0)}
    missing = {(1, 3), (3, 1), (2, 3), (3, 2)}
    primary = StubProvider("google", routes=resolved)
    secondary = StubProvider("here", routes_all=True)

    matrix = await FallbackTransitResolver([primary, secondary]).prefetch_pairwise(
        _request(CITY)
    )

    assert len(secondary.calls) == 1
    assert _asked_pairs(secondary.calls[0]) == missing
    # And over only the locations those arcs touch, so the matrix is smaller.
    assert len(secondary.calls[0].locations) == 3
    assert len(matrix.legs) == 12
    assert _pair(matrix, 0, 1).provider == "google"
    assert _pair(matrix, 1, 3).provider == "here"


async def test_g2_the_same_provider_is_not_asked_twice_about_a_refused_arc():
    """A day is re-solved on every top-up round; a refusal is remembered."""
    primary = StubProvider("google", routes={(0, 1), (1, 0)})
    secondary = StubProvider("here")
    resolver = FallbackTransitResolver([primary, secondary])

    await resolver.prefetch_pairwise(_request(CITY))
    await resolver.prefetch_pairwise(_request(CITY))

    assert len(secondary.calls) == 1


# ----- H: provenance survives, and stays out of the traveler's way -----


async def test_h_every_leg_carries_the_provider_that_produced_it():
    primary = StubProvider("google", routes={(0, 1)})
    secondary = StubProvider("here", routes={(1, 0)})

    matrix = await FallbackTransitResolver([primary, secondary]).prefetch_pairwise(
        _request(CITY)
    )

    assert _pair(matrix, 0, 1).provider == "google"
    assert _pair(matrix, 1, 0).provider == "here"
    assert _pair(matrix, 2, 3).provider == "estimated"
    # Provenance is a property of the leg, not of the label on it.
    assert _pair(matrix, 0, 1).routing_status is TransitRoutingStatus.ROUTED
    assert _pair(matrix, 1, 0).routing_status is TransitRoutingStatus.ROUTED
    assert _pair(matrix, 2, 3).routing_status is TransitRoutingStatus.ESTIMATED


async def test_h2_counters_say_where_each_arc_came_from():
    resolver = FallbackTransitResolver(
        [
            StubProvider("google", routes={(0, 1), (1, 0)}),
            StubProvider("here", routes={(0, 2)}),
        ]
    )

    await resolver.prefetch_pairwise(_request(CITY))
    metrics = resolver.stats.as_metrics()

    assert metrics["transit.primary.routed"] == 2
    assert metrics["transit.primary.no_route"] == 10
    assert metrics["transit.secondary.routed"] == 1
    assert metrics["transit.secondary.no_route"] == 9
    assert metrics["transit.estimated"] == 9
    assert metrics["transit.unroutable"] == 0


# ----- departure time travels with the question -----


async def test_the_fallback_is_asked_about_the_same_departure_as_the_primary():
    primary = StubProvider("google")
    secondary = StubProvider("here", routes_all=True)

    await FallbackTransitResolver([primary, secondary]).prefetch_pairwise(
        _request(CITY)
    )

    assert secondary.calls[0].departure_at == DEPARTURE
    assert secondary.calls[0].departure_window == WINDOW


# ----- the chain, and how it is configured -----


async def test_an_unconfigured_secondary_is_left_out_rather_than_failing():
    client = make_transit_client(
        provider="google",
        fallbacks="here",
        redis=FakeRedis(),  # type: ignore[arg-type]
    )

    assert [provider.name for provider in client.providers] == ["google"]


async def test_a_configured_secondary_joins_the_chain_behind_the_primary(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("syncinerary.config.settings.here_api_key", "test-key")

    client = make_transit_client(
        provider="google",
        fallbacks="here",
        redis=FakeRedis(),  # type: ignore[arg-type]
    )

    assert [provider.name for provider in client.providers] == ["google", "here"]


def test_the_default_chain_puts_a_global_provider_first():
    assert transit_chain_names(provider="google", fallbacks="here") == ["google", "here"]
    # A fallback named twice is still asked once.
    assert transit_chain_names(provider="google", fallbacks="here, here") == [
        "google",
        "here",
    ]


async def test_a_regional_provider_is_registered_rather_than_branched_on():
    """The country lives in a registry entry, never in the routing code."""
    regional = StubProvider("regional", routes_all=True)
    regional_provider_registry.register(country="Japan", factory=lambda: regional)
    try:
        client = make_transit_client(
            provider="google",
            fallbacks="",
            region=TransitRegion(country="japan", city="Sapporo"),
            redis=FakeRedis(),  # type: ignore[arg-type]
        )
        elsewhere = make_transit_client(
            provider="google",
            fallbacks="",
            region=TransitRegion(country="Norway"),
            redis=FakeRedis(),  # type: ignore[arg-type]
        )
    finally:
        regional_provider_registry.clear()

    assert [provider.name for provider in client.providers] == ["google", "regional"]
    assert [provider.name for provider in elsewhere.providers] == ["google"]


# ----- the HERE adapter itself -----


async def test_here_sums_a_journey_and_caches_the_leg():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "sections": [
                            {"travelSummary": {"duration": 600, "length": 2000}},
                            {"travelSummary": {"duration": 1_200, "length": 8000}},
                        ]
                    }
                ]
            },
        )

    redis = FakeRedis()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HereTransitClient(
            api_key="test-key",
            redis=redis,  # type: ignore[arg-type]
            http_client=http,
        )
        first = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[CITY[0], CITY[1]],
                departure_window=WINDOW,
                departure_at=DEPARTURE,
                required_pairs=[(0, 1)],
            )
        )
        second = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[CITY[0], CITY[1]],
                departure_window=WINDOW,
                departure_at=DEPARTURE,
                required_pairs=[(0, 1)],
            )
        )

    assert first.legs[0].duration_minutes == 30
    assert first.legs[0].provider == "here"
    assert second.legs[0].cache_hit is True
    # One arc asked once, and the second read came from the cache.
    assert len(calls) == 1
    assert calls[0].url.params["departureTime"] == DEPARTURE.isoformat()


async def test_here_reports_no_route_rather_than_raising():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"routes": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HereTransitClient(
            api_key="test-key",
            redis=FakeRedis(),  # type: ignore[arg-type]
            http_client=http,
        )
        matrix = await client.prefetch_pairwise(
            PairwiseTransitRequest(
                locations=[CITY[0], CITY[1]],
                departure_window=WINDOW,
                departure_at=DEPARTURE,
            )
        )

    assert matrix.legs == []
    assert [item.status for item in matrix.unavailable] == [
        "ROUTE_NOT_FOUND",
        "ROUTE_NOT_FOUND",
    ]


async def test_here_refuses_a_whole_day_rather_than_fanning_out():
    """The per-arc adapter is a fallback. Handed a whole matrix it says so."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"routes": []}))
    ) as http:
        client = HereTransitClient(
            api_key="test-key",
            redis=FakeRedis(),  # type: ignore[arg-type]
            http_client=http,
            max_arcs=4,
        )
        with pytest.raises(HereConfigurationError):
            await client.prefetch_pairwise(_request(CITY))


def test_the_estimate_ceiling_is_the_one_the_repository_already_chose():
    """Test J's companion: the ceiling is configuration, not a literal here."""
    assert ESTIMATED_TRANSIT_MAX_KM == 30.0


# ----- I and J: the chain and Stage 2, end to end -----


def _candidate(name: str, location: TransitLocation) -> CandidatePlace:
    weekdays = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=location.lat,
        lng=location.lng,
        hours_by_weekday={day: [[8, 22]] for day in weekdays},
        duration_estimate_min=60,
    )


THURSDAY = date(2026, 5, 21)


async def test_i_a_city_day_no_provider_could_route_still_gets_all_its_stops():
    """The failure this work exists for: four city places, twelve dead arcs.

    Before the estimate, the circuit had no arcs and the day shipped with one
    stop. The chain must not have quietly undone that: with both providers
    missing, every pair is still estimated and every stop is still placed.
    """
    places = [
        _candidate(name, location)
        for name, location in zip(
            ("North", "Centre", "South", "East"), CITY, strict=True
        )
    ]
    resolver = FallbackTransitResolver([StubProvider("google"), StubProvider("here")])

    matrix = await resolver.prefetch_pairwise(_request(CITY))
    route = solve_day(places, day=0, trip_date=THURSDAY, transit=matrix)

    assert len(route.stops) == 4
    assert route.unplaced == []
    # Labelled as approximate, and internally attributed to nobody but us.
    assert {stop.transit_from_prev_mode for stop in route.stops[1:]} == {
        "transit_estimated"
    }
    assert {stop.transit_from_prev_provider for stop in route.stops[1:]} == {"estimated"}


async def test_i2_a_secondary_route_reaches_stage_2_as_a_routed_leg():
    places = [
        _candidate(name, location)
        for name, location in zip(("North", "Centre"), CITY[:2], strict=True)
    ]
    resolver = FallbackTransitResolver(
        [StubProvider("google"), StubProvider("here", routes_all=True, minutes=41)]
    )

    matrix = await resolver.prefetch_pairwise(_request(CITY[:2]))
    route = solve_day(places, day=0, trip_date=THURSDAY, transit=matrix)

    assert len(route.stops) == 2
    assert route.stops[1].transit_from_prev_min == 41
    # Routed by a fallback is still routed: no "approx." on this leg.
    assert route.stops[1].transit_from_prev_mode == "transit"
    assert route.stops[1].transit_from_prev_provider == "here"


async def test_j_a_regional_hop_no_provider_could_route_is_still_unroutable():
    """Preserved from M7g: past the ceiling, no arc is invented."""
    places = [
        _candidate(name, location)
        for name, location in zip(("Museum", "Observatory"), FAR, strict=True)
    ]
    resolver = FallbackTransitResolver([StubProvider("google"), StubProvider("here")])

    matrix = await resolver.prefetch_pairwise(_request(FAR))
    route = solve_day(places, day=0, trip_date=THURSDAY, transit=matrix)

    assert matrix.legs == []
    assert len(route.stops) == 1
