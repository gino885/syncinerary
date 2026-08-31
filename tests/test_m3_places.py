"""M3 Google Places resolution and uncached attributed photo lookup."""
from __future__ import annotations

import httpx
import pytest

from syncinerary.api.routers import trips as trips_module
from syncinerary.domain.models import CandidatePlace, CandidateType
from syncinerary.harness import run_tool
from syncinerary.store.repositories import CandidatePlaceRepository
from syncinerary.tools.places.google_places import (
    CityResolveInput,
    PhotoAttribution,
    PlaceMatch,
    PlacePhotoInput,
    PlacePhotoOutput,
    PlaceSearchBias,
    PlaceSearchInput,
    PlaceSearchOutput,
    make_city_resolve_tool,
    make_place_photo_tool,
    make_place_search_tool,
)


async def test_text_search_returns_typed_place_identity_and_location():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        assert request.headers["X-Goog-FieldMask"] == (
            "places.id,places.displayName,places.formattedAddress,"
            "places.addressComponents,places.location,places.primaryType,places.types,"
            "places.editorialSummary,places.regularOpeningHours,places.priceLevel"
        )
        assert request.read() == b'{"textQuery":"Otaru Canal, Hokkaido"}'
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-test",
                        "displayName": {"text": "Otaru Canal", "languageCode": "en"},
                        "formattedAddress": "Otaru, Hokkaido, Japan",
                        "addressComponents": [
                            {"longText": "Otaru", "types": ["locality"]},
                            {"longText": "Hokkaido", "types": ["administrative_area_level_1"]},
                        ],
                        "location": {"latitude": 43.1987, "longitude": 140.9947},
                        "primaryType": "tourist_attraction",
                        "types": ["tourist_attraction", "point_of_interest"],
                        "editorialSummary": {"text": "Canal-side warehouses glow after dark."},
                        "regularOpeningHours": {
                            "periods": [
                                {
                                    "open": {"day": 1, "hour": 9, "minute": 30},
                                    "close": {"day": 1, "hour": 18, "minute": 15},
                                }
                            ]
                        },
                        "priceLevel": "PRICE_LEVEL_MODERATE",
                    }
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(query="Otaru Canal", destination="Hokkaido"),
        )

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.place_id == "ChIJ-test"
    assert match.display_name == "Otaru Canal"
    assert match.lat == 43.1987
    assert match.lng == 140.9947
    assert match.primary_type == "tourist_attraction"
    assert match.area == "Otaru"
    assert match.editorial_summary == "Canal-side warehouses glow after dark."
    assert match.hours_by_weekday == {"mon": [[10, 18]]}
    assert match.price_tier == 2


async def test_text_search_rejects_results_from_another_city():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-odori",
                        "displayName": {"text": "Odori Park"},
                        "formattedAddress": "日本、北海道札幌市",
                        "addressComponents": [
                            {"longText": "札幌市", "types": ["locality"]},
                            {
                                "longText": "北海道",
                                "types": ["administrative_area_level_1"],
                            },
                        ],
                        "location": {"latitude": 43.0605, "longitude": 141.3544},
                    },
                    {
                        "id": "ChIJ-central-park",
                        "displayName": {"text": "Central Park"},
                        "formattedAddress": "New York, NY, USA",
                        "addressComponents": [
                            {"longText": "New York", "types": ["locality"]},
                        ],
                        "location": {"latitude": 40.7829, "longitude": -73.9654},
                    },
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(
                query="popular parks",
                destination="Sapporo",
                city_center=PlaceSearchBias(lat=43.0618, lng=141.3545),
                city_radius_km=20,
            ),
        )

    # The typed name is Latin and the address is Japanese, so no string rule
    # would have matched. Distance from the resolved city does.
    assert [match.display_name for match in result.matches] == ["Odori Park"]


async def test_text_search_can_require_a_real_restaurant_type():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.read() == (
            b'{"textQuery":"local restaurants, Hokkaido",'
            b'"includedType":"restaurant","strictTypeFiltering":true}'
        )
        return httpx.Response(200, json={"places": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(
                query="local restaurants",
                destination="Hokkaido",
                included_type="restaurant",
            ),
        )


async def test_text_search_does_not_repeat_a_destination_already_in_the_query():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.read() == b'{"textQuery":"top attractions in Hokkaido"}'
        return httpx.Response(200, json={"places": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(
                query="top attractions in Hokkaido",
                destination="Hokkaido",
            ),
        )


async def test_text_search_can_bias_results_to_a_day_cluster():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.read() == (
            b'{"textQuery":"local restaurants, Hokkaido",'
            b'"includedType":"restaurant","strictTypeFiltering":true,'
            b'"locationBias":{"circle":{"center":'
            b'{"latitude":43.06,"longitude":141.35},"radius":15000.0}}}'
        )
        return httpx.Response(200, json={"places": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(
                query="local restaurants",
                destination="Hokkaido",
                included_type="restaurant",
                location_bias=PlaceSearchBias(lat=43.06, lng=141.35),
            ),
        )


async def test_photo_lookup_gets_a_fresh_name_and_keeps_required_attribution():
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        if request.url.path == "/v1/places/ChIJ-test":
            assert request.headers["X-Goog-FieldMask"] == "id,photos"
            return httpx.Response(
                200,
                json={
                    "id": "ChIJ-test",
                    "photos": [
                        {
                            "name": "places/ChIJ-test/photos/photo-token",
                            "widthPx": 1600,
                            "heightPx": 900,
                            "authorAttributions": [
                                {
                                    "displayName": "A Photographer",
                                    "uri": "https://maps.google.com/maps/contrib/123",
                                    "photoUri": "https://example.test/avatar.jpg",
                                }
                            ],
                        }
                    ],
                },
                request=request,
            )
        assert request.url.path == (
            "/v1/places/ChIJ-test/photos/photo-token/media"
        )
        assert request.url.params["maxWidthPx"] == "1200"
        assert request.url.params["skipHttpRedirect"] == "true"
        return httpx.Response(
            200,
            json={"photoUri": "https://lh3.googleusercontent.com/photo"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_place_photo_tool(client=client, api_key="test-key"),
            PlacePhotoInput(place_id="ChIJ-test", max_width_px=1200),
        )

    assert len(requests) == 2
    assert result.photo_url == "https://lh3.googleusercontent.com/photo"
    assert result.width_px == 1600
    assert result.height_px == 900
    assert result.attributions[0].display_name == "A Photographer"
    assert result.attributions[0].uri == "https://maps.google.com/maps/contrib/123"
    assert "test-key" not in result.model_dump_json()


async def test_places_tools_stop_clearly_when_key_is_missing():
    with pytest.raises(RuntimeError, match="GOOGLE_MAPS_API_KEY"):
        await run_tool(
            make_place_search_tool(api_key=""),
            PlaceSearchInput(query="Otaru Canal", destination="Hokkaido"),
        )


async def test_candidate_photo_endpoint_searches_by_name_and_returns_attribution(
    client,
    session,
    monkeypatch,
):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    candidate = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip_id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Canal",
            lat=43.1987,
            lng=140.9947,
        )
    )

    async def fake_run_tool(tool, arguments, **_kwargs):
        if tool.name == "google_places_text_search":
            assert arguments.query == "Otaru Canal"
            assert arguments.destination == "Hokkaido"
            return PlaceSearchOutput(
                matches=[
                    PlaceMatch(
                        place_id="ChIJ-test",
                        display_name="Otaru Canal",
                        lat=43.1987,
                        lng=140.9947,
                    )
                ]
            )
        assert tool.name == "google_places_photo"
        assert arguments.place_id == "ChIJ-test"
        return PlacePhotoOutput(
            place_id="ChIJ-test",
            photo_url="https://lh3.googleusercontent.com/photo",
            width_px=1600,
            height_px=900,
            attributions=[
                PhotoAttribution(
                    display_name="A Photographer",
                    uri="https://maps.google.com/maps/contrib/123",
                )
            ],
        )

    monkeypatch.setattr(trips_module, "run_tool", fake_run_tool)
    response = await client.get(
        f"/trips/{trip_id}/candidates/{candidate.id}/photo"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "provider": "google_places",
        "photo_url": "https://lh3.googleusercontent.com/photo",
        "width_px": 1600,
        "height_px": 900,
        "attributions": [
            {
                "display_name": "A Photographer",
                "uri": "https://maps.google.com/maps/contrib/123",
                "photo_uri": None,
            }
        ],
    }


async def test_candidate_photo_endpoint_prefers_permitted_platform_preview(
    client,
    session,
    monkeypatch,
):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    candidate = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip_id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Canal",
            lat=43.1987,
            lng=140.9947,
            enrichment={
                "platform": "tiktok",
                "platform_preview_url": (
                    "https://p16-sign.tiktokcdn-us.com/preview.jpeg"
                ),
            },
        )
    )

    async def unexpected_tool_call(*_args, **_kwargs):
        raise AssertionError("platform preview should avoid a Places lookup")

    monkeypatch.setattr(trips_module, "run_tool", unexpected_tool_call)
    response = await client.get(
        f"/trips/{trip_id}/candidates/{candidate.id}/photo"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "provider": "tiktok",
        "photo_url": "https://p16-sign.tiktokcdn-us.com/preview.jpeg",
        "width_px": None,
        "height_px": None,
        "attributions": [],
    }


async def test_an_always_open_place_is_open_every_day_not_only_sunday():
    """Places marks 24/7 with one period that opens on day 0 and never closes."""
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-odori",
                        "displayName": {"text": "Odori Park"},
                        "formattedAddress": "Sapporo, Hokkaido, Japan",
                        "location": {"latitude": 43.0605, "longitude": 141.3544},
                        "primaryType": "park",
                        "types": ["park"],
                        "regularOpeningHours": {
                            "periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]
                        },
                    }
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(query="Odori Park", destination="Hokkaido"),
        )

    hours = result.matches[0].hours_by_weekday
    assert set(hours) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert all(window == [[0, 24]] for window in hours.values())


async def test_a_malformed_period_without_a_close_is_not_treated_as_always_open():
    """Only Google's exact Sunday-midnight sentinel means open 24/7."""
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-bad-hours",
                        "displayName": {"text": "Mystery Museum"},
                        "formattedAddress": "Sapporo, Hokkaido, Japan",
                        "location": {"latitude": 43.06, "longitude": 141.35},
                        "primaryType": "museum",
                        "types": ["museum"],
                        "regularOpeningHours": {
                            "periods": [{"open": {"day": 2, "hour": 9, "minute": 0}}]
                        },
                    }
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_place_search_tool(client=client, api_key="test-key"),
            PlaceSearchInput(query="Mystery Museum", destination="Hokkaido"),
        )

    assert result.matches[0].hours_by_weekday == {}


async def test_a_city_name_is_resolved_to_a_real_place_with_an_extent():
    """Typed cities are resolved, so nothing depends on a supported-city list."""
    def respond(request: httpx.Request) -> httpx.Response:
        assert b'"includedType":"locality"' in request.read()
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-sapporo",
                        "displayName": {"text": "Sapporo"},
                        "primaryType": "locality",
                        "types": ["locality", "political"],
                        "formattedAddress": "Sapporo, Hokkaido, Japan",
                        "location": {"latitude": 43.0618, "longitude": 141.3545},
                        "viewport": {
                            "low": {"latitude": 42.95, "longitude": 141.20},
                            "high": {"latitude": 43.17, "longitude": 141.50},
                        },
                    }
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_city_resolve_tool(client=client, api_key="test-key"),
            CityResolveInput(name="  Sapporo  "),
        )

    city = result.city
    assert city is not None
    assert city.name == "Sapporo"
    assert city.query == "Sapporo"
    assert 5 <= city.radius_km <= 60


async def test_city_resolution_skips_a_non_city_result():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "ChIJ-neighborhood",
                        "displayName": {"text": "Downtown"},
                        "primaryType": "neighborhood",
                        "types": ["neighborhood", "political"],
                        "location": {"latitude": 43.05, "longitude": 141.35},
                    },
                    {
                        "id": "ChIJ-sapporo",
                        "displayName": {"text": "Sapporo"},
                        "primaryType": "locality",
                        "types": ["locality", "political"],
                        "location": {"latitude": 43.0618, "longitude": 141.3545},
                    },
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_city_resolve_tool(client=client, api_key="test-key"),
            CityResolveInput(name="Sapporo"),
        )

    assert result.city is not None
    assert result.city.name == "Sapporo"


async def test_a_city_nobody_can_resolve_comes_back_empty_rather_than_guessed():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"places": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_city_resolve_tool(client=client, api_key="test-key"),
            CityResolveInput(name="Zzzqqx"),
        )

    assert result.city is None
