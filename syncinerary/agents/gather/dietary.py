"""Deterministic hard-diet filtering for the swipe pool."""
from __future__ import annotations

from collections.abc import Iterable

from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
)

UNVERIFIED_DIETARY_NOTICE = (
    "Dietary details are unverified. Confirm with the restaurant."
)

_PLACE_TYPE_TAGS: dict[str, set[str]] = {
    "barbecue_restaurant": {"meat"},
    "hamburger_restaurant": {"meat"},
    "seafood_restaurant": {"seafood"},
    "steak_house": {"meat"},
    "sushi_restaurant": {"seafood"},
    "vegan_restaurant": {"vegan", "vegetarian"},
    "vegetarian_restaurant": {"vegetarian"},
}


def _normalize(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    return normalized or None


def dietary_tags_from_place_types(place_types: Iterable[str]) -> list[str]:
    """Extract only explicit cuisine evidence from Google place types."""
    tags: set[str] = set()
    for place_type in place_types:
        normalized = _normalize(place_type)
        if normalized:
            tags.update(_PLACE_TYPE_TAGS.get(normalized, set()))
    return sorted(tags)


def hard_dietary_exclusions(constraints: Iterable[Constraint]) -> set[str]:
    exclusions: set[str] = set()
    for constraint in constraints:
        if constraint.type != "dietary" or constraint.kind is not ConstraintKind.HARD:
            continue
        values = constraint.value.get("excludes", [])
        if not isinstance(values, list):
            continue
        for value in values:
            normalized = _normalize(value)
            if normalized:
                exclusions.add(normalized)
    return exclusions


def filter_dietary_conflicts(
    candidates: list[CandidatePlace],
    constraints: list[Constraint],
) -> list[CandidatePlace]:
    """Remove known conflicts, while preserving food with unknown metadata."""
    exclusions = hard_dietary_exclusions(constraints)
    if not exclusions:
        return list(candidates)
    return [
        candidate
        for candidate in candidates
        if candidate.type is not CandidateType.FOOD
        or not exclusions.intersection(
            normalized
            for tag in candidate.dietary_tags
            if (normalized := _normalize(tag)) is not None
        )
    ]


def dietary_notice(
    candidate: CandidatePlace,
    constraints: list[Constraint],
) -> str | None:
    """Warn on kept food because Places types are not a safety guarantee."""
    if (
        candidate.type is CandidateType.FOOD
        and hard_dietary_exclusions(constraints)
    ):
        return UNVERIFIED_DIETARY_NOTICE
    return None


__all__ = [
    "UNVERIFIED_DIETARY_NOTICE",
    "dietary_notice",
    "dietary_tags_from_place_types",
    "filter_dietary_conflicts",
    "hard_dietary_exclusions",
]
