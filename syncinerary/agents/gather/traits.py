"""Deterministic scheduling traits derived from Google place types."""
from __future__ import annotations

from collections.abc import Iterable

from syncinerary.domain.models import CandidateType

OUTDOOR_PLACE_TYPES = frozenset(
    {
        "beach",
        "botanical_garden",
        "garden",
        "hiking_area",
        "national_park",
        "park",
        "tourist_attraction",
    }
)
HIGH_FATIGUE_TYPES = frozenset(
    {"amusement_park", "hiking_area", "national_park", "zoo"}
)
LOW_FATIGUE_TYPES = OUTDOOR_PLACE_TYPES | {
    "art_gallery",
    "museum",
    "shopping_mall",
}


def _all_types(primary_type: str | None, place_types: Iterable[str]) -> set[str]:
    values = set(place_types)
    if primary_type:
        values.add(primary_type)
    return values


def is_weather_dependent(
    primary_type: str | None,
    place_types: Iterable[str],
) -> bool:
    return bool(_all_types(primary_type, place_types) & OUTDOOR_PLACE_TYPES)


def fatigue_cost(
    candidate_type: CandidateType,
    primary_type: str | None,
    place_types: Iterable[str],
) -> int:
    """Return the configured 1 low, 2 medium, or 3 high effort level."""
    if candidate_type is CandidateType.FOOD:
        return 1
    types = _all_types(primary_type, place_types)
    if types & HIGH_FATIGUE_TYPES:
        return 3
    if types & LOW_FATIGUE_TYPES:
        return 1
    return 2


__all__ = [
    "OUTDOOR_PLACE_TYPES",
    "fatigue_cost",
    "is_visitable_place",
    "is_weather_dependent",
]


# Google returns these for administrative areas rather than for anywhere a
# traveler can go. A city geocodes perfectly well, which is exactly the
# problem: "Sapporo" resolved, passed the city-boundary check, and became an
# attraction card. The NER prompt already says to skip cities, but a prompt is
# a request and this is the enforcement.
_ADMINISTRATIVE_PLACE_TYPES = frozenset(
    {
        "administrative_area_level_1",
        "administrative_area_level_2",
        "administrative_area_level_3",
        "administrative_area_level_4",
        "administrative_area_level_5",
        "archipelago",
        "continent",
        "country",
        "locality",
        "neighborhood",
        "political",
        "postal_code",
        "sublocality",
        "sublocality_level_1",
    }
)


def is_visitable_place(primary_type: str | None, types: list[str]) -> bool:
    """Whether this is somewhere you can go, rather than somewhere you are.

    A place is rejected when its types say administrative area and nothing
    says otherwise. The "and nothing says otherwise" matters: a park or a
    museum is often tagged `political` alongside its real type, so a bare
    membership test would throw away half the deck.
    """
    found = set(types)
    if primary_type:
        found.add(primary_type)
    if not found:
        return True
    return bool(found - _ADMINISTRATIVE_PLACE_TYPES)

