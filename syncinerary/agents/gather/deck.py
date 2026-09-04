"""Deterministic swipe-deck order. No LLM (CLAUDE.md section 2).

The deck was ordered by `name_canonical`, which is to say alphabetically, so
the two-lane selection in social.py had no effect on what anyone actually saw.
A traveler swiping forty cards gives the last ones less attention than the
first, so where a card sits is a real decision and it should be made on
evidence rather than on spelling.
"""
from __future__ import annotations

from syncinerary.domain.models import CandidatePlace

# Why a card is in the deck, best-attention-first on a tie. A traveler's own
# attachment goes first because being asked to vote on the thing you added is
# the least surprising place to start.
_LANE_PRIORITY = {
    "personal": 0,
    "for_you": 1,
    "trending": 2,
    "foundation": 3,
}


def deck_lane(candidate: CandidatePlace) -> str:
    """Which group a card belongs to, from its provenance.

    Reads the lane the selector already recorded rather than recomputing it,
    so the deck and the badge cannot disagree.
    """
    source_types = {source.type for source in candidate.sources}
    if "personal" in source_types:
        return "personal"
    if "buzz" in source_types:
        lane = candidate.trending_signals.get("selection_lane")
        return "for_you" if lane == "for_you" else "trending"
    return "foundation"


def _evidence_rank(candidate: CandidatePlace) -> tuple[float, str]:
    """Strongest evidence first inside a group; the name only breaks ties."""
    buzz = 0.0
    for source in candidate.sources:
        if source.type == "buzz" and source.score is not None:
            buzz = max(buzz, float(source.score))
    return (-buzz, candidate.name_canonical.casefold())


def order_deck(candidates: list[CandidatePlace]) -> list[CandidatePlace]:
    """Interleave the groups so none of them clumps.

    A traveler's own attachments go first. Everything else is spread evenly by
    giving each group's i-th card the position (i + 0.5) / n, so the groups mix
    in proportion to their sizes. That matters because For You cards are chosen
    for interest rather than popularity: ordered by evidence alone they would
    all land at the end, behind the fatigue, and the lane would buy nothing.

    Foundation cards carry no evidence to rank on, so within their own group
    they fall back to name order. That is arbitrary, and saying so is better
    than inventing a score they do not have.
    """
    groups: dict[str, list[CandidatePlace]] = {}
    for candidate in candidates:
        groups.setdefault(deck_lane(candidate), []).append(candidate)

    # Your own attachments lead outright rather than being spread. Spreading
    # places a one-card lane at its own midpoint, which buried the single card
    # a traveler had contributed at position 30 of 40.
    leading = sorted(groups.pop("personal", []), key=_evidence_rank)

    placed: list[tuple[float, int, str, CandidatePlace]] = []
    for lane, members in groups.items():
        members.sort(key=_evidence_rank)
        size = len(members)
        priority = _LANE_PRIORITY.get(lane, len(_LANE_PRIORITY))
        for index, candidate in enumerate(members):
            placed.append(((index + 0.5) / size, priority, lane, candidate))

    placed.sort(key=lambda row: (row[0], row[1], row[3].name_canonical.casefold()))
    return [*leading, *(row[3] for row in placed)]


__all__ = ["deck_lane", "order_deck"]
