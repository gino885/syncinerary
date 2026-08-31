"""M3 live destination discovery and geographically useful pool selection."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from uuid import uuid4

from syncinerary.agents.gather import live as live_module
from syncinerary.agents.gather.live import (
    CLUSTER_FOOD_QUERIES,
    build_search_queries,
    discover_candidates,
    gather_node,
    select_dense_pool,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Source,
    Trip,
    TripState,
)
from syncinerary.store.repositories import CandidatePlaceRepository, TripRepository
from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput


def _candidate(name: str, lat: float, lng: float) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=lat,
        lng=lng,
        hours_by_weekday={day: [[8, 20]] for day in _WEEKDAYS},
    )


_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def test_search_queries_are_destination_specific_and_cover_a_full_day_mix():
    queries = build_search_queries("  Hokkaido  ")

    assert len(queries) >= 5
    assert all("Hokkaido" in query for query in queries)
    assert any("restaurant" in query.lower() for query in queries)
    assert any("attraction" in query.lower() for query in queries)
    assert any("museum" in query.lower() for query in queries)


def test_dense_pool_prefers_day_sized_groups_over_isolated_landmarks():
    sapporo = [
        _candidate(f"Sapporo {index}", 43.061 + index * 0.002, 141.354)
        for index in range(7)
    ]
    otaru = [
        _candidate(f"Otaru {index}", 43.198 + index * 0.002, 140.994)
        for index in range(7)
    ]
    isolated = [
        _candidate("Blue Pond", 43.493, 142.614),
        _candidate("Lake Toya", 42.603, 140.851),
    ]

    selected = select_dense_pool(sapporo + otaru + isolated, days=2, limit=14)

    assert {candidate.name_canonical for candidate in selected} == {
        *(candidate.name_canonical for candidate in sapporo),
        *(candidate.name_canonical for candidate in otaru),
    }


def test_city_core_and_distant_suburbs_form_separate_day_clusters():
    core = [
        _candidate(f"Core {index}", 43.060 + index * 0.001, 141.350)
        for index in range(5)
    ]
    eastern_suburb = [
        _candidate(f"East {index}", 43.050 + index * 0.001, 141.490)
        for index in range(4)
    ]

    clusters = live_module._dense_clusters(core + eastern_suburb)

    assert [len(cluster) for cluster in clusters] == [5, 4]


def test_places_beyond_the_walking_cutoff_do_not_claim_one_dense_cluster():
    first = [
        _candidate(f"First {index}", 43.060 + index * 0.0005, 141.350)
        for index in range(5)
    ]
    three_km_away = [
        _candidate(f"Second {index}", 43.088 + index * 0.0005, 141.350)
        for index in range(5)
    ]

    clusters = live_module._dense_clusters(first + three_km_away)

    assert [len(cluster) for cluster in clusters] == [5, 5]


def test_a_tiny_outlying_cluster_does_not_take_a_whole_day_from_the_core():
    core = [
        _candidate(f"Core {index}", 43.060 + index * 0.0005, 141.350)
        for index in range(40)
    ]
    outlying = [
        _candidate(f"Outlying {index}", 42.920 + index * 0.0005, 141.360)
        for index in range(4)
    ]

    selected = select_dense_pool(core + outlying, days=5, limit=40)

    assert {candidate.name_canonical for candidate in selected} == {
        candidate.name_canonical for candidate in core
    }


def test_dense_pool_keeps_food_in_each_full_day_mix():
    attractions = [
        _candidate(f"Attraction {index}", 43.061 + index * 0.001, 141.354)
        for index in range(10)
    ]
    food = [
        _candidate(f"Restaurant {index}", 43.062 + index * 0.001, 141.356).model_copy(
            update={"type": CandidateType.FOOD}
        )
        for index in range(3)
    ]

    selected = select_dense_pool(attractions + food, days=1, limit=7)

    assert sum(candidate.type is CandidateType.FOOD for candidate in selected) >= 1


async def test_live_discovery_uses_google_results_without_preset_candidates(monkeypatch):
    trip = Trip(
        destination="Hokkaido",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 9, 28),
        days=2,
    )
    calls: list[str] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        calls.append(arguments.query)
        query_index = len(calls)
        is_food = "restaurant" in arguments.query.lower()
        is_lodging = "hotel" in arguments.query.lower()
        assert arguments.included_type == (
            "restaurant" if is_food else "hotel" if is_lodging else None
        )
        primary_type = (
            "hotel" if is_lodging else "restaurant" if is_food else "tourist_attraction"
        )
        if arguments.location_bias is not None:
            return PlaceSearchOutput(
                matches=[
                    PlaceMatch(
                        place_id=f"cluster-food-{query_index}",
                        display_name=f"Cluster restaurant {query_index}",
                        formatted_address="Hokkaido, Japan",
                        area="Cluster",
                        lat=arguments.location_bias.lat,
                        lng=arguments.location_bias.lng,
                        primary_type="restaurant",
                        types=["restaurant"],
                        editorial_summary="A nearby restaurant for this day cluster.",
                        hours_by_weekday={day: [[11, 21]] for day in _WEEKDAYS},
                    )
                ]
            )
        cluster_lat = 43.061 if query_index <= 4 or is_lodging else 43.493
        cluster_lng = 141.354 if query_index <= 4 or is_lodging else 142.614
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"place-{query_index}-{index}",
                    display_name=f"Live result {query_index}-{index}",
                    formatted_address="Sapporo, Hokkaido, Japan",
                    area="Sapporo",
                    lat=cluster_lat + index * 0.001,
                    lng=cluster_lng + index * 0.001,
                    primary_type=primary_type,
                    types=(
                        [primary_type, "restaurant"]
                        if query_index == 1 and index == 0
                        else [primary_type]
                    ),
                    editorial_summary="A real place returned by the live search provider.",
                    hours_by_weekday={day: [[9, 20]] for day in _WEEKDAYS},
                )
                for index in range(4)
            ]
        )

    async def no_social(_trip, _travelers):
        return []

    monkeypatch.setattr("syncinerary.agents.gather.live.run_tool", fake_run_tool)
    # Social buzz has its own tests and its own network calls; this one is
    # about what the destination search alone produces.
    monkeypatch.setattr(live_module, "discover_social_candidates", no_social)

    candidates = await discover_candidates(trip)

    base_queries = build_search_queries("Hokkaido")
    assert calls[: len(base_queries)] == base_queries
    assert len(calls) == len(base_queries) + trip.days * len(CLUSTER_FOOD_QUERIES)
    assert sum(" near Live result " in query for query in calls) == (
        trip.days * len(CLUSTER_FOOD_QUERIES)
    )
    assert any("breakfast" in query for query in base_queries)
    assert any("dinner" in query for query in base_queries)
    # days * POOL_PER_DAY swipeable candidates plus the three lodging options.
    assert len(candidates) == 19
    # Enough food for lunch and dinner on every day, not one restaurant a day.
    assert sum(candidate.type is CandidateType.FOOD for candidate in candidates) >= (
        trip.days * 2
    )
    assert sum(candidate.type is CandidateType.LODGING for candidate in candidates) == 3
    first_attraction = next(
        candidate for candidate in candidates if candidate.name_canonical == "Live result 1-0"
    )
    assert first_attraction.type is CandidateType.ATTRACTION
    assert all(candidate.enrichment["google_place_id"] for candidate in candidates)
    assert all(candidate.enrichment["discovery_provider"] == "google_places" for candidate in candidates)
    assert all(candidate.enrichment["source_description"] for candidate in candidates)
    assert all(source.type == "discovery" for candidate in candidates for source in candidate.sources)
    assert "Blue Pond" not in {candidate.name_canonical for candidate in candidates}


async def test_gather_node_persists_a_live_pool_and_returns_only_partial_state(
    session,
    monkeypatch,
):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 9, 27),
            end_date=date(2026, 9, 28),
            days=2,
        )
    )
    discovered = [
        _candidate(f"Live {index}", 43.061 + index * 0.001, 141.354)
        .model_copy(update={"trip_id": trip.id})
        for index in range(14)
    ]

    @asynccontextmanager
    async def test_scope():
        yield session

    async def fake_discover(_trip, _travelers=None):
        return discovered

    monkeypatch.setattr(live_module, "session_scope", test_scope)
    monkeypatch.setattr(live_module, "discover_candidates", fake_discover)
    state = TripState(trip=trip)

    result = await gather_node(state)

    assert set(result) == {"candidates"}
    assert state.candidates == []
    assert await CandidatePlaceRepository(session).count_for_trip(trip.id) == 14


async def test_gather_node_reuses_existing_rows_without_searching_again(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 9, 27),
            end_date=date(2026, 9, 28),
            days=2,
        )
    )
    existing = await CandidatePlaceRepository(session).add(
        _candidate("Already saved", 43.061, 141.354).model_copy(
            update={"trip_id": trip.id}
        )
    )

    @asynccontextmanager
    async def test_scope():
        yield session

    async def should_not_search(_trip, _travelers=None):
        raise AssertionError("re-entering gather must not repeat a live search")

    monkeypatch.setattr(live_module, "session_scope", test_scope)
    monkeypatch.setattr(live_module, "discover_candidates", should_not_search)

    result = await gather_node(TripState(trip=trip))

    assert [candidate.id for candidate in result["candidates"]] == [existing.id]


def test_one_cluster_serving_every_day_still_reserves_every_day_a_meal():
    """A city destination collapses to a single cluster that covers all days."""
    attractions = [
        _candidate(f"Sight {index}", 43.06 + index * 0.0002, 141.35)
        for index in range(40)
    ]
    food = [
        _candidate(f"Restaurant {index}", 43.062 + index * 0.0002, 141.356).model_copy(
            update={"type": CandidateType.FOOD}
        )
        for index in range(20)
    ]

    selected = select_dense_pool(attractions + food, days=5, limit=40)

    meals = sum(1 for candidate in selected if candidate.type is CandidateType.FOOD)
    assert meals >= 5 * 2, f"only {meals} restaurants for five days"


async def test_a_buzz_place_joins_the_pool_and_keeps_both_source_rows(monkeypatch):
    """Section 8.4: found by search and by a post is one card, two sources."""
    trip = Trip(
        destination="Hokkaido",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 9, 28),
        days=2,
    )

    async def fake_run_tool(_tool, arguments, **_kwargs):
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"shared-{index}",
                    display_name=f"Place {index}",
                    lat=43.061 + index * 0.002,
                    lng=141.354 + index * 0.002,
                    primary_type="tourist_attraction",
                    types=["tourist_attraction"],
                    hours_by_weekday={day: [[9, 20]] for day in _WEEKDAYS},
                )
                for index in range(12)
            ]
        )

    async def fake_social(trip_arg, _travelers):
        return [
            CandidatePlace(
                trip_id=trip_arg.id,
                type=CandidateType.ATTRACTION,
                name_canonical="Place 0",
                lat=43.061,
                lng=141.354,
                sources=[Source(type="buzz", sources_count=4)],
                enrichment={
                    "google_place_id": "shared-0",
                    "social_platforms": ["tiktok"],
                    "social_post_urls": ["a", "b", "c", "d"],
                },
            )
        ]

    monkeypatch.setattr("syncinerary.agents.gather.live.run_tool", fake_run_tool)
    monkeypatch.setattr(live_module, "discover_social_candidates", fake_social)

    candidates = await discover_candidates(trip, [])

    shared = [c for c in candidates if c.enrichment.get("google_place_id") == "shared-0"]
    assert len(shared) == 1
    assert {source.type for source in shared[0].sources} == {"discovery", "buzz"}
    assert shared[0].enrichment["social_platforms"] == ["tiktok"]


async def test_a_profile_place_merges_with_google_and_survives_pool_selection(monkeypatch):
    trip = Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 9, 28),
        days=2,
    )
    traveler_id = uuid4()

    async def fake_run_tool(_tool, _arguments, **_kwargs):
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"shared-{index}",
                    display_name=f"Place {index}",
                    formatted_address="Sapporo, Hokkaido, Japan",
                    lat=43.061 + index * 0.001,
                    lng=141.354 + index * 0.001,
                    primary_type="tourist_attraction",
                    types=["tourist_attraction"],
                    hours_by_weekday={day: [[9, 20]] for day in _WEEKDAYS},
                )
                for index in range(16)
            ]
        )

    async def no_social(_trip, _travelers):
        return []

    async def fake_profile(trip_arg, _travelers):
        return [
            CandidatePlace(
                trip_id=trip_arg.id,
                type=CandidateType.ATTRACTION,
                name_canonical="Place 0",
                lat=43.061,
                lng=141.354,
                sources=[
                    Source(
                        type="personal",
                        subtype="profile_driven",
                        by=traveler_id,
                    )
                ],
                enrichment={"google_place_id": "shared-0"},
            )
        ]

    monkeypatch.setattr(live_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(live_module, "discover_social_candidates", no_social)
    monkeypatch.setattr(live_module, "discover_profile_candidates", fake_profile)

    candidates = await discover_candidates(trip, [])

    shared = [c for c in candidates if c.enrichment.get("google_place_id") == "shared-0"]
    assert len(shared) == 1
    assert {source.type for source in shared[0].sources} == {"discovery", "personal"}


async def test_a_buzz_card_survives_even_when_it_stands_alone_geographically(monkeypatch):
    """The reason to leave the city for a day sits in its own sparse cluster."""
    trip = Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 9, 28),
        days=2,
    )

    async def fake_run_tool(_tool, arguments, **_kwargs):
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"sapporo-{index}",
                    display_name=f"Sapporo place {index}",
                    lat=43.061 + index * 0.002,
                    lng=141.354 + index * 0.002,
                    primary_type="tourist_attraction",
                    types=["tourist_attraction"],
                    hours_by_weekday={day: [[9, 20]] for day in _WEEKDAYS},
                )
                for index in range(14)
            ]
        )

    async def fake_social(trip_arg, _travelers):
        return [
            CandidatePlace(
                trip_id=trip_arg.id,
                type=CandidateType.ATTRACTION,
                name_canonical="Otaru Canal",
                lat=43.1987,
                lng=140.9947,
                sources=[Source(type="buzz", sources_count=3)],
                enrichment={
                    "google_place_id": "otaru-canal",
                    "social_platforms": ["instagram", "tiktok"],
                    "social_post_urls": ["a", "b", "c"],
                },
            )
        ]

    monkeypatch.setattr("syncinerary.agents.gather.live.run_tool", fake_run_tool)
    monkeypatch.setattr(live_module, "discover_social_candidates", fake_social)

    candidates = await discover_candidates(trip, [])

    assert "Otaru Canal" in {c.name_canonical for c in candidates}
