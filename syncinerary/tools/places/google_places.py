"""Typed Places API (New) search and uncached photo lookup tools."""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.harness import ToolDefinition

SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.primaryType,places.types"
)


class PlaceSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=200)


class PlaceMatch(BaseModel):
    place_id: str
    display_name: str
    formatted_address: str | None = None
    lat: float
    lng: float
    primary_type: str | None = None
    types: list[str] = Field(default_factory=list)


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


async def _search_place(
    value: PlaceSearchInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> PlaceSearchOutput:
    _require_key(api_key)
    response = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
        },
        json={"textQuery": f"{value.query.strip()}, {value.destination.strip()}"},
    )
    response.raise_for_status()
    matches = []
    for place in response.json().get("places", []):
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
    "PlaceSearchInput",
    "PlaceSearchOutput",
    "make_place_photo_tool",
    "make_place_search_tool",
]
