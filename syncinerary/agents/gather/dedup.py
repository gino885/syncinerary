"""Cross-source entity resolution for the candidate pool. CLAUDE.md section 8.4.

A place found by the destination search, by a social post, and by a traveler's
attachment has to collapse into one card that keeps all three source rows. The
same applies to the duplicate listings Google itself returns: a museum indexed
twice under two place ids was showing up as two stops on two different days.

This is the deterministic half of section 8.4: exact identity, then geographic
proximity combined with name agreement. Embedding similarity and LLM-assisted
resolution for borderline pairs belong here too and are not built yet.
"""
from __future__ import annotations

import re
import unicodedata

from syncinerary.config.gather import GEO_CLUSTER_RADIUS_M
from syncinerary.domain.models import CandidatePlace
from syncinerary.tools.transit import TransitLocation, haversine_km

# Words that carry no identity: dropping them makes "Sapporo Art Museum" and
# "Sapporo Art Museum (Annex)" comparable without collapsing genuinely
# different places.
_NOISE = {
    "the",
    "a",
    "an",
    "of",
    "at",
    "in",
    "and",
    "museum",
    "park",
    "center",
    "centre",
    "store",
    "shop",
    "branch",
    "main",
}


def normalize_name(name: str) -> str:
    """Casefold, strip accents and punctuation, and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s]", " ", stripped.casefold())
    return " ".join(cleaned.split())


def _identity_tokens(name: str) -> frozenset[str]:
    tokens = {token for token in normalize_name(name).split() if token not in _NOISE}
    return frozenset(tokens or normalize_name(name).split())


def _same_place(left: CandidatePlace, right: CandidatePlace) -> bool:
    """Two rows describing one place: close together and named the same thing."""
    distance_m = (
        haversine_km(
            TransitLocation(lat=left.lat, lng=left.lng),
            TransitLocation(lat=right.lat, lng=right.lng),
        )
        * 1000
    )
    if distance_m > GEO_CLUSTER_RADIUS_M:
        return False

    left_tokens = _identity_tokens(left.name_canonical)
    right_tokens = _identity_tokens(right.name_canonical)
    if not left_tokens or not right_tokens:
        return False
    # One name containing the other is the common duplicate-listing shape
    # ("Hokkaido University Museum" against "The Hokkaido University Museum").
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def _merge(keeper: CandidatePlace, duplicate: CandidatePlace) -> CandidatePlace:
    """Union the sources and keep whichever enrichment is richer."""
    sources = list(keeper.sources)
    for source in duplicate.sources:
        if source not in sources:
            sources.append(source)

    enrichment = {**duplicate.enrichment, **keeper.enrichment}
    for key, value in duplicate.enrichment.items():
        if not keeper.enrichment.get(key) and value:
            enrichment[key] = value

    return keeper.model_copy(
        update={
            "sources": sources,
            "enrichment": enrichment,
            "hours_by_weekday": keeper.hours_by_weekday or duplicate.hours_by_weekday,
            "address": keeper.address or duplicate.address,
            "area": keeper.area or duplicate.area,
            "trending_signals": {
                **duplicate.trending_signals,
                **keeper.trending_signals,
            },
        }
    )


def dedup_candidates(candidates: list[CandidatePlace]) -> list[CandidatePlace]:
    """Collapse duplicate rows, keeping the first occurrence's position.

    Order matters downstream: the pool's order decides what survives the size
    limit, so a merge must not promote or demote the surviving card.
    """
    resolved: list[CandidatePlace] = []
    for candidate in candidates:
        for index, kept in enumerate(resolved):
            if _same_place(kept, candidate):
                resolved[index] = _merge(kept, candidate)
                break
        else:
            resolved.append(candidate)
    return resolved


__all__ = ["dedup_candidates", "normalize_name"]
