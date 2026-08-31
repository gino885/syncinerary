"""Typed Places API (New) search and uncached photo lookup tools."""
from __future__ import annotations

import math
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

# Resolving a typed city needs its extent, not its hours or price.
CITY_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.addressComponents,places.location,places.viewport,"
    "places.primaryType,places.types"
)

# Fallback extent for a city whose viewport the provider does not return.
DEFAULT_CITY_RADIUS_KM = 20.0
MIN_CITY_RADIUS_KM = 5.0
MAX_CITY_RADIUS_KM = 60.0

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



class PlaceSearchBias(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(default=15_000, gt=0, le=50_000)


class PlaceSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=200)
    included_type: str | None = Field(default=None, min_length=1, max_length=100)
    location_bias: PlaceSearchBias | None = None
    # Where the destination actually is, resolved from what the traveler typed.
    # When present a result belongs to the city if it sits inside this circle,
    # which works for any city in any language. Without it the check falls back
    # to looking for the destination name in the returned address.
    city_center: PlaceSearchBias | None = None
    city_radius_km: float | None = Field(default=None, gt=0, le=200)


class CityResolveInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(default=None, min_length=1, max_length=120)


class ResolvedCity(BaseModel):
    """A typed city name resolved to a real place with a real extent."""

    query: str
    place_id: str
    name: str
    formatted_address: str | None = None
    lat: float
    lng: float
    radius_km: float
    country: str | None = None
    country_code: str | None = None


class CityResolveOutput(BaseModel):
    city: ResolvedCity | None = None


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


def _belongs_to_destination(
    place: dict[str, Any],
    destination: str,
    *,
    city_center: PlaceSearchBias | None = None,
    city_radius_km: float | None = None,
) -> bool:
    """Keep only results that really sit in the destination.

    Google text search happily ranks a globally famous place above a local one
    even with the city in the query, so results have to be checked.

    When the city has been resolved to a point, membership is distance from
    that point. That is what lets a traveler type any city in any language: a
    name-matching rule needs a table of local-language aliases per city, and
    that table is exactly the hardcoding this replaced.
    """
    if city_center is not None:
        location = place.get("location", {})
        if "latitude" not in location or "longitude" not in location:
            return False
        distance_km = haversine_km(
            (city_center.lat, city_center.lng),
            (location["latitude"], location["longitude"]),
        )
        return distance_km <= (city_radius_km or DEFAULT_CITY_RADIUS_KM)

    # No resolved centre: fall back to the destination name appearing in the
    # address. Weaker, and only used by callers that look a single place up by
    # name rather than building a pool.
    destination_key = destination.strip().casefold()
    address_parts = [place.get("formattedAddress", "")]
    for component in place.get("addressComponents", []):
        address_parts.extend(
            [component.get("longText", ""), component.get("shortText", "")]
        )
    address = " ".join(part for part in address_parts if isinstance(part, str)).casefold()
    return bool(address) and destination_key in address


def haversine_km(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> float:
    """Great-circle distance in kilometres.

    Local to this module on purpose: importing the transit package here would
    make a provider wrapper depend on the routing stack.
    """
    lat1, lng1 = (math.radians(value) for value in origin)
    lat2, lng2 = (math.radians(value) for value in destination)
    d_lat = lat2 - lat1
    d_lng = lng2 - lng1
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def _country_of(place: dict[str, Any]) -> tuple[str | None, str | None]:
    """The country name and ISO code Google recorded for this place."""
    for component in place.get("addressComponents", []):
        if "country" in component.get("types", []):
            return component.get("longText"), component.get("shortText")
    return None, None


def _radius_from_viewport(viewport: dict[str, Any]) -> float:
    """Half the viewport diagonal, clamped to a sane city size."""
    low = viewport.get("low", {})
    high = viewport.get("high", {})
    if not {"latitude", "longitude"} <= low.keys() or not {"latitude", "longitude"} <= high.keys():
        return DEFAULT_CITY_RADIUS_KM
    diagonal = haversine_km(
        (low["latitude"], low["longitude"]),
        (high["latitude"], high["longitude"]),
    )
    return min(MAX_CITY_RADIUS_KM, max(MIN_CITY_RADIUS_KM, diagonal / 2))


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
        if not _belongs_to_destination(
            place,
            destination,
            city_center=value.city_center,
            city_radius_km=value.city_radius_km,
        ):
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


async def _resolve_city(
    value: CityResolveInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> CityResolveOutput:
    """Turn whatever the traveler typed into one real city with an extent."""
    _require_key(api_key)
    # The country goes into the query as well as being checked afterwards:
    # "Springfield" alone is ambiguous, "Springfield, United States" is not.
    query = value.name.strip()
    if value.country:
        query = f"{query}, {value.country.strip()}"
    response = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": CITY_FIELD_MASK},
        json={"textQuery": query, "includedType": "locality"},
    )
    response.raise_for_status()
    for place in response.json().get("places", []):
        if (
            place.get("primaryType") != "locality"
            and "locality" not in place.get("types", [])
        ):
            continue
        location = place.get("location", {})
        display_name = place.get("displayName", {}).get("text")
        if not place.get("id") or not display_name:
            continue
        if "latitude" not in location or "longitude" not in location:
            continue
        country_name, country_code = _country_of(place)
        return CityResolveOutput(
            city=ResolvedCity(
                query=value.name.strip(),
                place_id=place["id"],
                name=display_name,
                formatted_address=place.get("formattedAddress"),
                lat=location["latitude"],
                lng=location["longitude"],
                radius_km=_radius_from_viewport(place.get("viewport", {})),
                country=country_name,
                country_code=country_code,
            )
        )
    # A name nothing matches is reported as unresolved rather than guessed at,
    # so the caller can tell the traveler instead of searching somewhere else.
    return CityResolveOutput()


def make_city_resolve_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    resolved_key = settings.google_maps_api_key if api_key is None else api_key

    async def resolve(value: CityResolveInput) -> CityResolveOutput:
        if client is not None:
            return await _resolve_city(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _resolve_city(value, client=owned_client, api_key=resolved_key)

    return ToolDefinition(
        name="google_places_city_resolve",
        input_model=CityResolveInput,
        output_model=CityResolveOutput,
        handler=resolve,
    )


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
