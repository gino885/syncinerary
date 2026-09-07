"""Deterministic scheduling traits derived from Google place types."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

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


# Places that are an area rather than a business, where a published opening
# window is not what decides whether a traveler can go. Google usually returns
# no hours at all for these, which is the case the tri-state below exists for;
# this set covers the ones that carry a type and sometimes inherit the hours of
# one business inside them.
AREA_PLACE_TYPES = frozenset(
    {
        "natural_feature",
        "neighborhood",
        "plaza",
        "sublocality",
        "sublocality_level_1",
    }
)


def opening_hours_are_binding(
    primary_type: str | None,
    types: Iterable[str],
    hours_by_weekday: Mapping[str, list] | None,
) -> bool:
    """Whether a published schedule should gate scheduling for this place.

    An area is open in the sense that matters: you can walk into an onsen
    district or a shopping street at any hour, and Google says nothing about
    when. Treating that silence as a schedule is what dropped both of them
    from a trip.
    """
    if _all_types(primary_type, types) & AREA_PLACE_TYPES:
        return False
    return bool(hours_by_weekday)


def opens_on(
    hours_by_weekday: Mapping[str, list] | None,
    weekday: str,
) -> bool | None:
    """Tri-state: open, closed, or the schedule does not say.

    None is the case that matters and the one the solver used to get wrong.
    An empty schedule is unknown hours, not a closed door, and the two deserve
    opposite treatment: unknown must not remove a place from the trip, while a
    weekday genuinely missing from a known schedule must.
    """
    if not hours_by_weekday:
        return None
    # A weekday the schedule names with no window is closed that day, and a
    # weekday it omits is too. Only an absent schedule is unknown.
    return bool(hours_by_weekday.get(weekday))


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
    "AREA_PLACE_TYPES",
    "OUTDOOR_PLACE_TYPES",
    "fatigue_cost",
    "is_visitable_place",
    "is_weather_dependent",
    "opening_hours_are_binding",
    "opens_on",
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

