"""M3 Google Places resolution and uncached attributed photo lookup."""
from __future__ import annotations

import httpx
import pytest

from syncinerary.api.routers import trips as trips_module
from syncinerary.domain.models import CandidatePlace, CandidateType
from syncinerary.harness import run_tool
from syncinerary.store.repositories import CandidatePlaceRepository
from syncinerary.tools.places.google_places import (
    PhotoAttribution,
    PlaceMatch,
    PlacePhotoInput,
    PlacePhotoOutput,
    PlaceSearchInput,
    PlaceSearchOutput,
    make_place_photo_tool,
    make_place_search_tool,
)


async def test_text_search_returns_typed_place_identity_and_location():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        assert request.headers["X-Goog-FieldMask"] == (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.primaryType,places.types"
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
                        "location": {"latitude": 43.1987, "longitude": 140.9947},
                        "primaryType": "tourist_attraction",
                        "types": ["tourist_attraction", "point_of_interest"],
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
            "destination": "Hokkaido",
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
            "destination": "Hokkaido",
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
