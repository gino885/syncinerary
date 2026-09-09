"""Typed inputs and outputs for transit lookups."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from syncinerary.config.solver import NEARBY_WALKING_KM


class TransitMode(str, Enum):
    WALKING = "walking"
    TRANSIT = "transit"


class TransitRoutingStatus(str, Enum):
    """How much a leg's duration is actually worth.

    ``ROUTED`` came from a provider that planned the journey. ``ESTIMATED``
    was derived from distance because no provider could, and must never be
    presented to a traveler as though someone had routed it.
    """

    ROUTED = "routed"
    ESTIMATED = "estimated"


class TransitLocation(BaseModel):
    """A routable place.

    M3 gather will provide Google Place IDs. The hand-written M1 fixture only
    has coordinates, so callers may omit ``place_id`` until then.
    """

    place_id: str | None = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

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
    #: Internal provenance: which adapter produced this leg. Never rendered.
    provider: str | None = None
    routing_status: TransitRoutingStatus = TransitRoutingStatus.ROUTED


class PairwiseTransitRequest(BaseModel):
    """Every directed transit pair among ``locations``, or a named subset.

    ``required_pairs`` exists for the fallback chain: once the primary
    provider has answered, the next one is asked only about the arcs still
    missing, over only the locations those arcs touch. ``None`` keeps the
    original meaning of "every pair".
    """

    locations: list[TransitLocation]
    departure_window: str = Field(min_length=1, max_length=40)
    departure_at: datetime | None = None
    walking_cutoff_km: float = Field(default=NEARBY_WALKING_KM, gt=0)
    required_pairs: list[tuple[int, int]] | None = None

    _wanted: frozenset[tuple[int, int]] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _required_pairs_index_real_locations(self) -> PairwiseTransitRequest:
        if self.required_pairs is None:
            return self
        limit = len(self.locations)
        for origin_index, destination_index in self.required_pairs:
            if not 0 <= origin_index < limit or not 0 <= destination_index < limit:
                raise ValueError("required_pairs references a missing location")
            if origin_index == destination_index:
                raise ValueError("required_pairs cannot contain a self pair")
        return self

    @model_validator(mode="after")
    def _index_required_pairs(self) -> PairwiseTransitRequest:
        """Membership is checked once per directed pair, so precompute it."""
        self._wanted = (
            None if self.required_pairs is None else frozenset(self.required_pairs)
        )
        return self

    def wants(self, origin_index: int, destination_index: int) -> bool:
        """Whether this directed pair was asked for."""
        if self._wanted is None:
            return True
        return (origin_index, destination_index) in self._wanted


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
    """Straight-line distance used only to choose a routing mode."""
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
