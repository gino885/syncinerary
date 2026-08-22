"""Typed inputs and outputs for transit lookups."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field, model_validator

from syncinerary.config.solver import NEARBY_WALKING_KM


class TransitMode(str, Enum):
    WALKING = "walking"
    TRANSIT = "transit"


class TransitLocation(BaseModel):
    """A routable place.

    M3 gather will provide Google Place IDs. The hand-written M1 fixture only
    has coordinates, so callers may omit ``place_id`` until then.
    """

    place_id: str | None = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    @property
    def google_value(self) -> str:
        if self.place_id:
            return f"place_id:{self.place_id}"
        return f"{self.lat:.6f},{self.lng:.6f}"

    @property
    def cache_id(self) -> str:
        if self.place_id:
            return f"place:{self.place_id}"
        return f"ll:{self.lat:.6f},{self.lng:.6f}"


class TransitRequest(BaseModel):
    origin: TransitLocation
    destination: TransitLocation
    mode: TransitMode
    departure_window: str = Field(min_length=1, max_length=40)
    departure_at: datetime | None = None

    @model_validator(mode="after")
    def _transit_departure_is_timezone_aware(self) -> TransitRequest:
        if (
            self.mode is TransitMode.TRANSIT
            and self.departure_at is not None
            and self.departure_at.tzinfo is None
        ):
            raise ValueError("departure_at must be timezone-aware")
        return self


class TransitDuration(BaseModel):
    origin: TransitLocation
    destination: TransitLocation
    mode: TransitMode
    departure_window: str
    duration_seconds: int = Field(gt=0)
    duration_minutes: int = Field(gt=0)
    cache_hit: bool = False


class PairwiseTransitRequest(BaseModel):
    locations: list[TransitLocation]
    departure_window: str = Field(min_length=1, max_length=40)
    departure_at: datetime | None = None
    walking_cutoff_km: float = Field(default=NEARBY_WALKING_KM, gt=0)


class TransitUnavailable(BaseModel):
    origin: TransitLocation
    destination: TransitLocation
    mode: TransitMode
    departure_window: str
    status: str
    detail: str | None = None


class TransitMatrix(BaseModel):
    legs: list[TransitDuration]
    unavailable: list[TransitUnavailable] = Field(default_factory=list)


def haversine_km(origin: TransitLocation, destination: TransitLocation) -> float:
    """Straight-line distance used only to choose a Directions travel mode."""
    earth_radius_km = 6371.0088
    lat1, lng1 = radians(origin.lat), radians(origin.lng)
    lat2, lng2 = radians(destination.lat), radians(destination.lng)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(a))


def choose_mode(
    origin: TransitLocation,
    destination: TransitLocation,
    *,
    walking_cutoff_km: float = NEARBY_WALKING_KM,
) -> TransitMode:
    return (
        TransitMode.WALKING
        if haversine_km(origin, destination) <= walking_cutoff_km
        else TransitMode.TRANSIT
    )
