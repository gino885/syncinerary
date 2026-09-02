"""Deterministic stand-ins for the providers the pipeline calls out to.

The eval harness has to produce the same numbers twice, on a laptop and in
CI, or a diff between two commits means nothing. Live Google Directions and
Google Places cannot offer that, and they cost money per run. These
substitutes are pure functions of the fixture.

They are not mocks in the "return whatever the test needs" sense. Transit
durations come from real distance, so a route that wanders is genuinely
scored as slower than one that does not, and the transit efficiency metric
keeps its meaning.
"""
from __future__ import annotations

from syncinerary.agents.rescue_alternatives import AlternativeSearchRequest
from syncinerary.config.solver import NEARBY_WALKING_KM
from syncinerary.domain.models import CandidatePlace
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitLocation,
    TransitMatrix,
    TransitMode,
    haversine_km,
)

# Speeds chosen to sit near real city numbers without pretending to be a
# routing engine: a brisk 4.5 km/h on foot, 18 km/h door to door on transit
# once waiting and transfers are counted.
WALKING_KM_PER_HOUR = 4.5
TRANSIT_KM_PER_HOUR = 18.0
#: Every leg costs something, so two stops in one building are not free.
MINIMUM_LEG_MINUTES = 4


def leg_minutes(origin: TransitLocation, destination: TransitLocation) -> tuple[int, TransitMode]:
    """Minutes and mode for one leg, from distance alone."""
    distance = haversine_km(origin, destination)
    if distance <= NEARBY_WALKING_KM:
        minutes = distance / WALKING_KM_PER_HOUR * 60
        return max(MINIMUM_LEG_MINUTES, round(minutes)), TransitMode.WALKING
    minutes = distance / TRANSIT_KM_PER_HOUR * 60
    return max(MINIMUM_LEG_MINUTES, round(minutes)), TransitMode.TRANSIT


class DistanceTransitProvider:
    """A transit provider whose answers are a function of distance.

    Counts its calls, so the harness-health family can assert the solver did
    not fan out further than the pairwise prefetch it is supposed to do.
    """

    def __init__(self) -> None:
        self.request_count = 0
        self.leg_count = 0

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        self.request_count += 1
        legs: list[TransitDuration] = []
        for origin in request.locations:
            for destination in request.locations:
                if origin == destination:
                    continue
                minutes, mode = leg_minutes(origin, destination)
                legs.append(
                    TransitDuration(
                        origin=origin,
                        destination=destination,
                        mode=mode,
                        departure_window=request.departure_window,
                        duration_seconds=minutes * 60,
                        duration_minutes=minutes,
                    )
                )
        self.leg_count += len(legs)
        return TransitMatrix(legs=legs)


class FixtureAlternativeProvider:
    """Replan alternatives come from the fixture's own spare candidates.

    A disruption fixture declares a few places marked `spare`: they are kept
    out of the swipe pool and exist only so the rescue agent has somewhere to
    put the group when a stop falls through. Using the fixture's own spares
    keeps the replan reproducible and keeps the fixture honest about what the
    agent was allowed to find.
    """

    def __init__(self, candidates: list[CandidatePlace]) -> None:
        self.candidates = candidates
        self.requests: list[AlternativeSearchRequest] = []

    async def discover(self, request: AlternativeSearchRequest) -> list[CandidatePlace]:
        self.requests.append(request)
        if request.avoid_weather_dependent:
            usable = [
                candidate for candidate in self.candidates if not candidate.weather_dependent
            ]
        else:
            usable = list(self.candidates)
        return usable[: request.limit]


__all__ = [
    "MINIMUM_LEG_MINUTES",
    "TRANSIT_KM_PER_HOUR",
    "WALKING_KM_PER_HOUR",
    "DistanceTransitProvider",
    "FixtureAlternativeProvider",
    "leg_minutes",
]
