"""Bounded gather-tool discovery for same-day rescue alternatives."""
from __future__ import annotations

from datetime import date, time
from typing import Protocol

from pydantic import BaseModel, Field

from syncinerary.agents.gather.cities import resolve_trip_cities
from syncinerary.agents.gather.dedup import dedup_candidates
from syncinerary.agents.gather.dietary import filter_dietary_conflicts
from syncinerary.agents.gather.live import candidate_from_place
from syncinerary.domain.models import CandidatePlace, CandidateType, Constraint, Trip
from syncinerary.harness import ToolDefinition, run_tool
from syncinerary.tools.places import (
    PlaceSearchBias,
    PlaceSearchInput,
    PlaceSearchOutput,
    ResolvedCity,
    make_place_search_tool,
)
from syncinerary.tools.transit import TransitLocation, haversine_km

REPLAN_SEARCH_RADIUS_KM = 12.0


class AlternativeSearchRequest(BaseModel):
    trip: Trip
    affected_date: date
    needed_at: time
    anchors: list[CandidatePlace] = Field(min_length=1)
    constraints: list[Constraint] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=20)
    avoid_weather_dependent: bool = False


class AlternativeProvider(Protocol):
    async def discover(
        self,
        request: AlternativeSearchRequest,
    ) -> list[CandidatePlace]: ...


def _center(candidates: list[CandidatePlace]) -> tuple[float, float]:
    return (
        sum(candidate.lat for candidate in candidates) / len(candidates),
        sum(candidate.lng for candidate in candidates) / len(candidates),
    )


def _distance_km(candidate: CandidatePlace, center: tuple[float, float]) -> float:
    return haversine_km(
        TransitLocation(lat=candidate.lat, lng=candidate.lng),
        TransitLocation(lat=center[0], lng=center[1]),
    )


def _nearest_city(cities: list[ResolvedCity], center: tuple[float, float]) -> ResolvedCity:
    return min(
        cities,
        key=lambda city: haversine_km(
            TransitLocation(lat=city.lat, lng=city.lng),
            TransitLocation(lat=center[0], lng=center[1]),
        ),
    )


def is_open_at(candidate: CandidatePlace, trip_date: date, needed_at: time) -> bool:
    weekday = trip_date.strftime("%a").lower()
    minute = needed_at.hour * 60 + needed_at.minute
    return any(
        start_hour * 60 <= minute < end_hour * 60
        for start_hour, end_hour in candidate.hours_by_weekday.get(weekday, [])
    )


def _query(anchors: list[CandidatePlace], avoid_weather: bool) -> tuple[str, str | None]:
    anchor_name = anchors[0].name_canonical
    if all(anchor.type is CandidateType.FOOD for anchor in anchors):
        return f"restaurants near {anchor_name}", "restaurant"
    if avoid_weather:
        return f"indoor attractions near {anchor_name}", None
    return f"things to do near {anchor_name}", None


class GooglePlacesAlternativeProvider:
    """Perform one local Places query and deterministically screen its results."""

    def __init__(self, *, search_tool: ToolDefinition | None = None) -> None:
        self._search_tool = search_tool

    async def discover(
        self,
        request: AlternativeSearchRequest,
    ) -> list[CandidatePlace]:
        center = _center(request.anchors)
        cities = await resolve_trip_cities(request.trip)
        if not cities:
            return []
        city = _nearest_city(cities, center)
        query, included_type = _query(
            request.anchors,
            request.avoid_weather_dependent,
        )
        result = await run_tool(
            self._search_tool or make_place_search_tool(),
            PlaceSearchInput(
                query=query,
                destination=city.name,
                included_type=included_type,
                location_bias=PlaceSearchBias(
                    lat=center[0],
                    lng=center[1],
                    radius_m=REPLAN_SEARCH_RADIUS_KM * 1000,
                ),
                city_center=PlaceSearchBias(lat=city.lat, lng=city.lng),
                city_radius_km=city.radius_km,
            ),
            state={"node": "rescue_gather", "trip_id": str(request.trip.id)},
        )
        assert isinstance(result, PlaceSearchOutput)
        candidates = [
            candidate_from_place(match, request.trip, query, city=city)
            for match in result.matches
            if match.hours_by_weekday
        ]
        candidates = [
            candidate
            for candidate in candidates
            if candidate.type is not CandidateType.LODGING
            and _distance_km(candidate, center) <= REPLAN_SEARCH_RADIUS_KM
            and is_open_at(candidate, request.affected_date, request.needed_at)
            and (
                not request.avoid_weather_dependent
                or not candidate.weather_dependent
            )
        ]
        candidates = filter_dietary_conflicts(candidates, request.constraints)
        candidates = dedup_candidates(candidates)
        candidates.sort(
            key=lambda candidate: (
                _distance_km(candidate, center),
                candidate.name_canonical,
            )
        )
        return candidates[: request.limit]


__all__ = [
    "REPLAN_SEARCH_RADIUS_KM",
    "AlternativeProvider",
    "AlternativeSearchRequest",
    "GooglePlacesAlternativeProvider",
    "is_open_at",
]
