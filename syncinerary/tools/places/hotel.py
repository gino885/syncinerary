"""Verify a booked hotel from its name or a Google Maps share link."""

from urllib.parse import parse_qs, quote, unquote_plus, urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.harness import ToolDefinition
from syncinerary.tools.places.google_places import (
    PlaceMatch,
    PlaceSearchInput,
    PlaceSearchOutput,
    _belongs_to_destination,
    _search_place,
)

MAP_HOSTS = {
    "google.com",
    "www.google.com",
    "maps.google.com",
    "maps.app.goo.gl",
    "goo.gl",
    "www.google.co.jp",
    "www.google.com.tw",
    "www.google.com.hk",
}
HOTEL_TYPES = {
    "lodging",
    "hotel",
    "resort_hotel",
    "motel",
    "hostel",
    "bed_and_breakfast",
    "inn",
    "japanese_inn",
    "extended_stay_hotel",
    "guest_house",
}


class MapsReference(BaseModel):
    query: str | None = None
    place_id: str | None = None


class HotelLookupInput(PlaceSearchInput):
    query: str = Field(min_length=1, max_length=2048)


def maps_reference(url: str) -> MapsReference:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in MAP_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Use a Google Maps HTTPS link or enter the hotel name")
    if parsed.hostname == "goo.gl" and not parsed.path.startswith("/maps/"):
        raise ValueError("Use a Google Maps link")
    if parsed.hostname not in {"maps.app.goo.gl", "goo.gl"} and not (
        parsed.path.startswith("/maps") or parsed.hostname == "maps.google.com"
    ):
        raise ValueError("Use a Google Maps place link")
    params = parse_qs(parsed.query)
    place_id = (params.get("query_place_id") or [None])[0]
    query = (params.get("query") or params.get("q") or [None])[0]
    if query and query.startswith("place_id:"):
        place_id, query = query.removeprefix("place_id:"), None
    if "/maps/place/" in parsed.path:
        query = unquote_plus(parsed.path.split("/maps/place/", 1)[1].split("/", 1)[0])
    return MapsReference(query=query, place_id=place_id)


async def lookup_hotel(
    value: HotelLookupInput, *, client: httpx.AsyncClient, api_key: str
) -> PlaceSearchOutput:
    query = value.query.strip()
    ref = MapsReference(query=query)
    if "://" in query:
        current = query
        for _ in range(5):
            ref = maps_reference(current)
            if ref.query or ref.place_id:
                break
            if urlsplit(current).hostname not in {"maps.app.goo.gl", "goo.gl"}:
                raise ValueError("This Maps link has no hotel name. Enter the hotel name instead")
            response = await client.get(current, follow_redirects=False)
            if not response.is_redirect or not response.headers.get("location"):
                raise ValueError(
                    "This Maps link could not be resolved. Enter the hotel name instead"
                )
            current = urljoin(current, response.headers["location"])
        else:
            raise ValueError("Too many Maps redirects. Enter the hotel name instead")
    if ref.place_id:
        if not api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY is required for Places lookup")
        response = await client.get(
            "https://places.googleapis.com/v1/places/" + quote(ref.place_id, safe=""),
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "id,displayName,formattedAddress,location,primaryType,types,businessStatus",
            },
        )
        response.raise_for_status()
        data = response.json()
        if not _belongs_to_destination(
            data,
            value.destination,
            city_center=value.city_center,
            city_radius_km=value.city_radius_km,
        ):
            return PlaceSearchOutput(matches=[])
        place = PlaceMatch(
            place_id=data["id"],
            display_name=data["displayName"]["text"],
            formatted_address=data.get("formattedAddress"),
            lat=data["location"]["latitude"],
            lng=data["location"]["longitude"],
            primary_type=data.get("primaryType"),
            types=data.get("types", []),
            business_status=data.get("businessStatus"),
        )
        result = PlaceSearchOutput(matches=[place])
    else:
        if not ref.query or len(ref.query) > 300:
            raise ValueError("Enter a hotel name of up to 300 characters")
        arguments = value.model_dump(exclude={"query", "included_type"})
        result = await _search_place(
            PlaceSearchInput(**arguments, query=ref.query, included_type="lodging"),
            client=client,
            api_key=api_key,
        )
    return PlaceSearchOutput(
        matches=[
            p
            for p in result.matches
            if (set(p.types) | {p.primary_type}) & HOTEL_TYPES
            and p.business_status != "CLOSED_PERMANENTLY"
        ]
    )


def make_hotel_lookup_tool() -> ToolDefinition:
    async def lookup(value: HotelLookupInput) -> PlaceSearchOutput:
        async with httpx.AsyncClient(timeout=20) as client:
            return await lookup_hotel(value, client=client, api_key=settings.google_maps_api_key)

    return ToolDefinition(
        name="booked_hotel_lookup",
        input_model=HotelLookupInput,
        output_model=PlaceSearchOutput,
        handler=lookup,
    )
