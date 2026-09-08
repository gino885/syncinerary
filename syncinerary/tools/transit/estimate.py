"""The conservative fallback used when no provider could route a pair.

Owned here rather than in the solver because two callers need the same
numbers: the resolver, which fills gaps before the matrix reaches Stage 2,
and ``solve_day`` itself, which still has to cope with matrices built
somewhere else (the eval provider, hand-written test fixtures).

Deliberately pessimistic. Over-estimating a leg costs at most one stop;
under-estimating one strands somebody or loses them a reservation.
"""
from __future__ import annotations

from syncinerary.config.solver import (
    ESTIMATED_TRANSIT_KMH,
    ESTIMATED_TRANSIT_MAX_KM,
    ESTIMATED_TRANSIT_OVERHEAD_MIN,
    NEARBY_WALKING_KM,
)
from syncinerary.tools.transit.models import (
    TransitLocation,
    TransitMode,
    haversine_km,
)


def estimated_transit_leg(
    origin: TransitLocation,
    destination: TransitLocation,
) -> tuple[int, TransitMode] | None:
    """Minutes and mode for a pair nobody could route, or ``None``.

    Inside a city a failed lookup is almost always a gap in the provider's
    coverage rather than proof the two places are unreachable from each
    other, so the leg is estimated. Past ``ESTIMATED_TRANSIT_MAX_KM`` the
    providers may be telling the truth, and an invented journey would put a
    stop on the plan that nobody can actually reach.
    """
    distance_km = haversine_km(origin, destination)
    if distance_km <= NEARBY_WALKING_KM:
        # Walking pace, 5 km/h.
        return max(5, round(distance_km * 12)), TransitMode.WALKING
    if distance_km > ESTIMATED_TRANSIT_MAX_KM:
        return None
    minutes = ESTIMATED_TRANSIT_OVERHEAD_MIN + round(
        distance_km / ESTIMATED_TRANSIT_KMH * 60
    )
    return max(5, minutes), TransitMode.TRANSIT


__all__ = ["estimated_transit_leg"]
