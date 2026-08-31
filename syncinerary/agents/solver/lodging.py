"""Deterministic lodging comparison for the pre-solver group pick."""
from __future__ import annotations

from syncinerary.domain.models import CandidatePlace, CandidateType
from syncinerary.tools.transit import TransitLocation, haversine_km


def rank_lodging_options(
    lodging: list[CandidatePlace],
    activities: list[CandidatePlace],
    *,
    limit: int = 3,
) -> list[CandidatePlace]:
    """Prefer hotels near the activity centroid, then lower price tiers.

    Google Places does not expose room availability. Dates belong on the
    comparison response, but this ranking never claims a room is available.
    """
    hotels = [candidate for candidate in lodging if candidate.type is CandidateType.LODGING]
    if not hotels or limit <= 0:
        return []
    anchors = [
        candidate for candidate in activities
        if candidate.type is not CandidateType.LODGING
    ]
    if anchors:
        center = TransitLocation(
            lat=sum(candidate.lat for candidate in anchors) / len(anchors),
            lng=sum(candidate.lng for candidate in anchors) / len(anchors),
        )
    else:
        center = TransitLocation(lat=hotels[0].lat, lng=hotels[0].lng)

    def ranking(candidate: CandidatePlace) -> tuple[int, int, float, str]:
        distance = haversine_km(
            center,
            TransitLocation(lat=candidate.lat, lng=candidate.lng),
        )
        # Hotels in the same one-kilometer neighborhood are effectively tied
        # on area, so price breaks that tie before a few meters of noise.
        return (int(distance), candidate.price_tier, distance, candidate.name_canonical)

    return sorted(hotels, key=ranking)[:limit]


__all__ = ["rank_lodging_options"]
