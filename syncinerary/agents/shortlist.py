"""Deterministic shortlist selection. CLAUDE.md §10.2.

NO LLM IN THIS FILE (§2 forbidden list, same reasoning as aggregate.py).

    target_size = days * slots_per_day        # slots_per_day defaults to 6
    sort all candidates by score desc
    take top target_size

M1 scope (§13): simple top-N, no confirmation screen, auto-proceeds. The
group confirmation cycle, must-go marking and the 50% quorum arrive in M4.
What M1 does build is the full shortlist_state row including the
wishlist_excluded list, because §10.3 surfaces those cards next to the
itinerary and the solver needs somewhere to put its not-placed reasons.

One consequence of following §10.2 literally: top-N takes the top N whatever
the scores are, so on a small pool a card the group actively disliked can
still be shortlisted. That is deliberate, not an oversight. The remedy in the
design is the M4 confirmation screen, where the group removes it; inventing a
score floor here would be a threshold nobody agreed to and would silently
shrink the shortlist below target_size.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from syncinerary.config.aggregate import SLOTS_PER_DAY
from syncinerary.domain.models import CandidateScore, ShortlistState, TripState
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import ShortlistStateRepository


def target_size(days: int, slots_per_day: int = SLOTS_PER_DAY) -> int:
    """§10.2: days * slots_per_day. Both live in config/aggregate.py (§16)."""
    return max(0, days) * slots_per_day


def build_shortlist(
    scores: list[CandidateScore],
    days: int,
    *,
    slots_per_day: int = SLOTS_PER_DAY,
) -> tuple[list[UUID], list[UUID]]:
    """Split ranked candidates into (shortlisted, wishlist_excluded).

    `scores` is expected in the order aggregate.score_candidates produced,
    which is score descending with a name tiebreak. It is not re-sorted here:
    re-sorting on score alone would drop that tiebreak and make the shortlist
    non-reproducible for equal-scoring cards.

    A shorter pool than target_size shortlists everything and excludes
    nothing.
    """
    limit = target_size(days, slots_per_day)
    selected = [s.candidate_id for s in scores[:limit]]
    excluded = [s.candidate_id for s in scores[limit:]]
    return selected, excluded


async def shortlist_node(state: TripState) -> dict[str, Any]:
    """LangGraph node: build the shortlist and persist it.

    Reads `state.candidate_scores`, which aggregate_node put there earlier in
    this same run. It does not recompute them: the shortlist has to be the
    consequence of a specific scoring, and rescoring here would let the two
    steps disagree without anything noticing.

    confirmed_by stays empty and confirmed_at stays null. M1 auto-proceeds
    with no confirmation step (§13), so there is genuinely nothing to record;
    writing a timestamp would claim an approval that never happened.

    Returns a partial dict (§14); does not mutate `state`.
    """
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("shortlist.build") as span:
        span.set_attribute("trip_id", str(trip.id))

        selected, excluded = build_shortlist(state.candidate_scores, trip.days)

        shortlist = ShortlistState(
            trip_id=trip.id,
            selected_candidate_ids=selected,
            # Must-go is a shortlist-stage hard pin marked by the group (§10.2).
            # M1 has no screen to mark it on, so nothing is pinned.
            must_go_candidate_ids=[],
            confirmed_by=[],
            confirmed_at=None,
            wishlist_excluded_ids=excluded,
        )

        async with session_scope() as session:
            saved = await ShortlistStateRepository(session).upsert(shortlist)

        span.set_attribute("shortlist.target_size", target_size(trip.days))
        span.set_attribute("shortlist.selected_count", len(selected))
        span.set_attribute("shortlist.excluded_count", len(excluded))

        return {"shortlist": saved}


__all__ = ["build_shortlist", "shortlist_node", "target_size"]
