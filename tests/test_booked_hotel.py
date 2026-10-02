from datetime import date
from uuid import uuid4

import httpx
import pytest

from syncinerary.domain.models import CandidatePlace, CandidateType, Traveler, Trip
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    TravelerRepository,
    TripRepository,
)


def test_maps_name_and_place_id_are_parsed_without_fetching():
    from syncinerary.tools.places.hotel import maps_reference

    assert (
        maps_reference("https://www.google.com/maps/place/Hotel+Nikko/@35,139,17z").query
        == "Hotel Nikko"
    )
    ref = maps_reference(
        "https://www.google.com/maps/search/?api=1&query=Hotel&query_place_id=ChIJ123"
    )
    assert ref.place_id == "ChIJ123"
    with pytest.raises(ValueError):
        maps_reference("https://google.com.evil.test/maps/place/Hotel")
    with pytest.raises(ValueError):
        maps_reference("https://user:secret@www.google.com/maps/place/Hotel")


async def test_short_link_redirect_cannot_leave_google():
    from syncinerary.tools.places.hotel import HotelLookupInput, lookup_hotel

    calls = []

    def transport(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(ValueError):
            await lookup_hotel(
                HotelLookupInput(query="https://maps.app.goo.gl/test", destination="Tokyo"),
                client=client,
                api_key="test",
            )
    assert len(calls) == 1


async def test_booked_hotel_selection_is_verified_and_survives_options_reload(
    client, session, monkeypatch
):
    from syncinerary.api.routers import booked_hotels

    trip = await TripRepository(session).add(
        Trip(
            destination="Tokyo",
            cities=["Tokyo"],
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 1),
            days=1,
        )
    )
    member = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Gino"))
    hotel = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.LODGING,
        name_canonical="Hotel Nikko",
        lat=35,
        lng=139,
        enrichment={"google_place_id": "ChIJ123", "city": "Tokyo"},
    )

    async def found(*args, **kwargs):
        return [hotel]

    monkeypatch.setattr(booked_hotels, "find_hotels", found)
    base = f"/trips/{trip.id}"
    body = {
        "traveler_id": str(member.id),
        "query": "Hotel Nikko",
        "city": "Tokyo",
        "place_id": "ChIJ123",
    }
    bad = await client.post(base + "/booked-hotel", json={**body, "place_id": "invented"})
    assert bad.status_code == 422
    assert not await CandidatePlaceRepository(session).list_for_trip(trip.id)
    saved = await client.post(base + "/booked-hotel", json=body)
    assert saved.status_code == 201, saved.text
    same = await client.post(base + "/booked-hotel", json=body)
    assert same.json()["candidate_id"] == saved.json()["candidate_id"]
    options = (await client.get(base + "/lodging-options")).json()
    assert options[0]["is_booked"] and options[0]["is_selected"]
    assert len(await CandidatePlaceRepository(session).list_for_trip(trip.id)) == 1
    denied = await client.post(base + "/booked-hotel", json={**body, "traveler_id": str(uuid4())})
    assert denied.status_code == 403


@pytest.mark.parametrize(
    "kind,lat,status,count",
    [
        ("hotel", 35.0, "OPERATIONAL", 1),
        ("restaurant", 35.0, "OPERATIONAL", 0),
        ("hotel", 40.0, "OPERATIONAL", 0),
        ("hotel", 35.0, "CLOSED_PERMANENTLY", 0),
    ],
)
async def test_hotel_link_checks_google_identity_type_city_and_closure(kind, lat, status, count):
    from syncinerary.tools.places import PlaceSearchBias
    from syncinerary.tools.places.hotel import HotelLookupInput, lookup_hotel

    def transport(request):
        assert request.url.host == "places.googleapis.com"
        assert request.url.path == "/v1/places/ChIJ1"
        return httpx.Response(
            200,
            json={
                "id": "ChIJ1",
                "displayName": {"text": "Hotel"},
                "formattedAddress": "Tokyo, Japan",
                "location": {"latitude": lat, "longitude": 139},
                "primaryType": kind,
                "types": [kind],
                "businessStatus": status,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await lookup_hotel(
            HotelLookupInput(
                query="https://www.google.com/maps/search/?query=Hotel&query_place_id=ChIJ1",
                destination="Tokyo",
                city_center=PlaceSearchBias(lat=35, lng=139),
                city_radius_km=20,
            ),
            client=client,
            api_key="test",
        )
    assert len(result.matches) == count


async def test_normal_selection_preserves_booked_state_in_response(client, session):
    from syncinerary.domain.models import ConstraintKind
    from syncinerary.store.repositories import ConstraintRepository

    trip = await TripRepository(session).add(
        Trip(
            destination="Tokyo",
            cities=["Tokyo"],
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 1),
            days=1,
        )
    )
    member = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Gino"))
    hotel = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id, type=CandidateType.LODGING, name_canonical="Hotel", lat=35, lng=139
        )
    )
    await ConstraintRepository(session).set_group_constraint(
        trip.id,
        constraint_type="selected_lodging",
        value={"candidate_id": str(hotel.id), "booked": True},
        priority=100,
        kind=ConstraintKind.HARD,
    )
    result = await client.post(
        f"/trips/{trip.id}/lodging-selection",
        json={"traveler_id": str(member.id), "candidate_id": str(hotel.id)},
    )
    assert result.status_code == 200
    assert result.json()["is_booked"] is True and result.json()["is_selected"] is True
