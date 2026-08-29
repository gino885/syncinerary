"""Typed Places API (New) search and uncached photo lookup tools."""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.harness import ToolDefinition

SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.addressComponents,places.location,places.primaryType,places.types,"
    "places.editorialSummary,places.regularOpeningHours,places.priceLevel"
)

_WEEKDAY_BY_GOOGLE_DAY = {
    0: "sun",
    1: "mon",
    2: "tue",
    3: "wed",
    4: "thu",
    5: "fri",
    6: "sat",
}

_PRICE_TIER = {
    "PRICE_LEVEL_FREE": 1,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

_DESTINATION_ALIASES = {
    "hokkaido": ("北海道",),
    "sapporo": ("札幌",),
    "otaru": ("小樽",),
    "hakodate": ("函館",),
    "asahikawa": ("旭川",),
    "kushiro": ("釧路",),
}


class PlaceSearchBias(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=15_000, gt=0, le=50_000)


class PlaceSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=200)
    included_type: str | None = Field(default=None, min_length=1, max_length=100)
    location_bias: PlaceSearchBias | None = None


class PlaceMatch(BaseModel):
    place_id: str
    display_name: str
    formatted_address: str | None = None
    lat: float
    lng: float
    primary_type: str | None = None
    types: list[str] = Field(default_factory=list)
    area: str | None = None
    editorial_summary: str | None = None
    hours_by_weekday: dict[str, list[list[int]]] = Field(default_factory=dict)
    price_tier: int | None = Field(default=None, ge=1, le=4)


class PlaceSearchOutput(BaseModel):
    matches: list[PlaceMatch]


class PlacePhotoInput(BaseModel):
    place_id: str = Field(min_length=1, max_length=300)
    max_width_px: int = Field(default=1200, ge=1, le=4800)


class PhotoAttribution(BaseModel):
    display_name: str
    uri: str | None = None
    photo_uri: str | None = None


class PlacePhotoOutput(BaseModel):
    place_id: str
    photo_url: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    attributions: list[PhotoAttribution] = Field(default_factory=list)


def _require_key(api_key: str) -> None:
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required for Places lookup")


def _area(place: dict[str, Any]) -> str | None:
    preferred_types = (
        "locality",
        "postal_town",
        "administrative_area_level_2",
        "administrative_area_level_1",
    )
    components = place.get("addressComponents", [])
    for component_type in preferred_types:
        for component in components:
            if component_type in component.get("types", []) and component.get("longText"):
                return component["longText"]
    return None


def _belongs_to_destination(place: dict[str, Any], destination: str) -> bool:
    """Require returned address evidence for the requested city or region."""
    destination_key = destination.strip().casefold()
    accepted_names = {destination_key, *_DESTINATION_ALIASES.get(destination_key, ())}
    address_parts = [place.get("formattedAddress", "")]
    for component in place.get("addressComponents", []):
        address_parts.extend(
            [component.get("longText", ""), component.get("shortText", "")]
        )
    address = " ".join(part for part in address_parts if isinstance(part, str)).casefold()
    return bool(address) and any(name.casefold() in address for name in accepted_names)


def _opening_hours(place: dict[str, Any]) -> dict[str, list[list[int]]]:
    """Convert Google minute-level periods into conservative whole-hour windows."""
    by_day: dict[str, list[list[int]]] = {}
    periods = place.get("regularOpeningHours", {}).get("periods", [])
    always_open = (
        len(periods) == 1
        and periods[0].get("open") == {"day": 0, "hour": 0, "minute": 0}
        and "close" not in periods[0]
    )
    if always_open:
        return {weekday: [[0, 24]] for weekday in _WEEKDAY_BY_GOOGLE_DAY.values()}

    for period in periods:
        # Places represents an always-open location as a single period that
        # opens on day 0 and never closes. Read literally that produced hours
        # for Sunday alone, which made every public park in the pool look shut
        # for six days a week and dropped it from the itinerary.
        if "close" not in period:
            continue

        opened = period.get("open", {})
        closed = period.get("close", {})
        weekday = _WEEKDAY_BY_GOOGLE_DAY.get(opened.get("day"))
        if weekday is None:
            continue

        open_hour = opened.get("hour")
        if not isinstance(open_hour, int):
            continue
        open_minute = opened.get("minute", 0)
        start = open_hour + (1 if open_minute else 0)

        close_hour = closed.get("hour")
        close_day = closed.get("day")
        if not isinstance(close_hour, int) or close_day != opened.get("day"):
            end = 24
        else:
            end = close_hour

        if start == end and opened.get("day") == close_day:
            start, end = 0, 24
        if 0 <= start < end <= 24:
            by_day.setdefault(weekday, []).append([start, end])
    return by_day


async def _search_place(
    value: PlaceSearchInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> PlaceSearchOutput:
    _require_key(api_key)
    query = value.query.strip()
    destination = value.destination.strip()
    text_query = query if destination.casefold() in query.casefold() else f"{query}, {destination}"
    body: dict[str, Any] = {"textQuery": text_query}
    if value.included_type:
        body["includedType"] = value.included_type
        body["strictTypeFiltering"] = True
    if value.location_bias:
        body["locationBias"] = {
            "circle": {
                "center": {
                    "latitude": value.location_bias.lat,
                    "longitude": value.location_bias.lng,
                },
                "radius": value.location_bias.radius_m,
            }
        }
    response = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json=body,
    )
    response.raise_for_status()
    matches = []
    for place in response.json().get("places", []):
        if not _belongs_to_destination(place, destination):
            continue
        location = place.get("location", {})
        display_name = place.get("displayName", {}).get("text")
        if not place.get("id") or not display_name:
            continue
        if "latitude" not in location or "longitude" not in location:
            continue
        matches.append(
            PlaceMatch(
                place_id=place["id"],
                display_name=display_name,
                formatted_address=place.get("formattedAddress"),
                lat=location["latitude"],
                lng=location["longitude"],
                primary_type=place.get("primaryType"),
                types=place.get("types", []),
                area=_area(place),
                editorial_summary=place.get("editorialSummary", {}).get("text"),
                hours_by_weekday=_opening_hours(place),
                price_tier=_PRICE_TIER.get(place.get("priceLevel")),
            )
        )
    return PlaceSearchOutput(matches=matches)


def _attributions(photo: dict[str, Any]) -> list[PhotoAttribution]:
    return [
        PhotoAttribution(
            display_name=item["displayName"],
            uri=item.get("uri"),
            photo_uri=item.get("photoUri"),
        )
        for item in photo.get("authorAttributions", [])
        if item.get("displayName")
    ]


async def _fetch_photo(
    value: PlacePhotoInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> PlacePhotoOutput:
    _require_key(api_key)
    headers = {"X-Goog-Api-Key": api_key}
    detail = await client.get(
        f"https://places.googleapis.com/v1/places/{value.place_id}",
        headers={**headers, "X-Goog-FieldMask": "id,photos"},
    )
    detail.raise_for_status()
    photos = detail.json().get("photos", [])
    if not photos:
        return PlacePhotoOutput(place_id=value.place_id)

    photo = photos[0]
    photo_name = photo.get("name", "")
    expected_prefix = f"places/{value.place_id}/photos/"
    if not photo_name.startswith(expected_prefix):
        raise RuntimeError("Google Places returned an invalid photo resource name")
    media = await client.get(
        f"https://places.googleapis.com/v1/{photo_name}/media",
        headers=headers,
        params={
            "maxWidthPx": value.max_width_px,
            "skipHttpRedirect": "true",
        },
    )
    media.raise_for_status()
    return PlacePhotoOutput(
        place_id=value.place_id,
        photo_url=media.json().get("photoUri"),
        width_px=photo.get("widthPx"),
        height_px=photo.get("heightPx"),
        attributions=_attributions(photo),
    )


def make_place_search_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    resolved_key = settings.google_maps_api_key if api_key is None else api_key

    async def search(value: PlaceSearchInput) -> PlaceSearchOutput:
        if client is not None:
            return await _search_place(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _search_place(
                value,
                client=owned_client,
                api_key=resolved_key,
            )

    return ToolDefinition(
        name="google_places_text_search",
        input_model=PlaceSearchInput,
        output_model=PlaceSearchOutput,
        handler=search,
    )


def make_place_photo_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    resolved_key = settings.google_maps_api_key if api_key is None else api_key

    async def photo(value: PlacePhotoInput) -> PlacePhotoOutput:
        if client is not None:
            return await _fetch_photo(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _fetch_photo(
                value,
                client=owned_client,
                api_key=resolved_key,
            )

    return ToolDefinition(
        name="google_places_photo",
        input_model=PlacePhotoInput,
        output_model=PlacePhotoOutput,
        handler=photo,
    )


__all__ = [
    "PhotoAttribution",
    "PlaceMatch",
    "PlacePhotoInput",
    "PlacePhotoOutput",
    "PlaceSearchBias",
    "PlaceSearchInput",
    "PlaceSearchOutput",
    "make_place_photo_tool",
    "make_place_search_tool",
]
