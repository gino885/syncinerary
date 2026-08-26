"""Deterministic consensus scoring. CLAUDE.md §10.1.

NO LLM IN THIS FILE. §2 puts consensus scoring on the deterministic side and
names this module explicitly in the forbidden list. The reason is not
stylistic: the score decides what reaches the shortlist, and a group has to
be able to see the same inputs produce the same ranking every time. If a
model call ever looks necessary here, it belongs before this module (parsing
notes into structure) or after it (explaining the outcome), never inside.

The formula, from §10.1:

    votes_pos       = count(like) + count(like_with_note)
    votes_neg       = count(dislike)
    votes_must      = count(must_have)
    votes_total     = number of travelers

    acceptance      = (votes_pos - votes_neg * dislike_weight) / votes_total
    must_have_bonus = votes_must * must_have_weight
    score           = acceptance + must_have_bonus

M1 scope: §13 says the thin slice uses the acceptance score "ignoring
must_have". The must_have arm is computed and carried anyway, with its weight
forced to zero, so M4 turns it on by changing one constant rather than
reshaping the model that the shortlist and the solver already read.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from syncinerary.config.aggregate import DISLIKE_WEIGHT, MUST_HAVE_WEIGHT
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateScore,
    CandidateType,
    TripState,
    Vote,
    VoteSignal,
)
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    TravelerRepository,
    VoteRepository,
)

# M1 ignores must_have (§13). M4 drops this and uses MUST_HAVE_WEIGHT.
M1_MUST_HAVE_WEIGHT = 0.0

POSITIVE_SIGNALS = frozenset({VoteSignal.LIKE, VoteSignal.LIKE_WITH_NOTE})


def score_candidate(
    candidate_id: UUID,
    votes: list[Vote],
    traveler_count: int,
    *,
    dislike_weight: float = DISLIKE_WEIGHT,
    must_have_weight: float = M1_MUST_HAVE_WEIGHT,
) -> CandidateScore:
    """Score one candidate. Pure function: no I/O, no clock, no randomness.

    `votes` must already be filtered to this candidate.

    A like_with_note counts exactly as much as a plain like. §9.3 is explicit
    that conditions attached to a note do not reduce weight; the condition is
    the solver's problem, not the aggregator's.
    """
    votes_pos = sum(1 for v in votes if v.signal in POSITIVE_SIGNALS)
    votes_neg = sum(1 for v in votes if v.signal is VoteSignal.DISLIKE)
    votes_must = sum(1 for v in votes if v.signal is VoteSignal.MUST_HAVE)

    # A trip with no travelers has no consensus to measure. Returning zero
    # beats a ZeroDivisionError on an empty trip, and the breakdown still
    # shows votes_total = 0 so the reason is visible rather than inferred.
    if traveler_count <= 0:
        acceptance = 0.0
    else:
        acceptance = (votes_pos - votes_neg * dislike_weight) / traveler_count

    must_have_bonus = votes_must * must_have_weight

    return CandidateScore(
        candidate_id=candidate_id,
        votes_pos=votes_pos,
        votes_neg=votes_neg,
        votes_must=votes_must,
        votes_total=traveler_count,
        acceptance=acceptance,
        must_have_bonus=must_have_bonus,
        score=acceptance + must_have_bonus,
    )


def score_candidates(
    candidates: list[CandidatePlace],
    votes: list[Vote],
    traveler_count: int,
    *,
    dislike_weight: float = DISLIKE_WEIGHT,
    must_have_weight: float = M1_MUST_HAVE_WEIGHT,
) -> list[CandidateScore]:
    """Score a whole pool, highest first.

    Lodging is excluded. §8.6 keeps it out of the swipe deck, so it has no
    votes; scoring it would put a row of zeroes at the bottom of every
    ranking and imply the group had considered and rejected it.

    Ties break on the candidate's canonical name, so two cards with identical
    votes always come back in the same order. Sorting on score alone would
    leave ties at the mercy of input order, and F2 replay compares rankings
    across runs.
    """
    votes_by_candidate: dict[UUID, list[Vote]] = {}
    for vote in votes:
        votes_by_candidate.setdefault(vote.candidate_id, []).append(vote)

    scorable = [c for c in candidates if c.type is not CandidateType.LODGING]
    name_by_id = {c.id: c.name_canonical for c in scorable}

    scores = [
        score_candidate(
            c.id,
            votes_by_candidate.get(c.id, []),
            traveler_count,
            dislike_weight=dislike_weight,
            must_have_weight=must_have_weight,
        )
        for c in scorable
    ]
    scores.sort(key=lambda s: (-s.score, name_by_id[s.candidate_id]))
    return scores


async def aggregate_node(state: TripState) -> dict[str, Any]:
    """LangGraph node: score the pool from what is stored for this trip.

    Reads from the database rather than from `state.votes` because the votes
    arrived over HTTP while the graph was interrupted at the swipe break, so
    the in-flight state predates them.

    Returns a partial dict (§14); does not mutate `state`.
    """
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("aggregate.consensus") as span:
        span.set_attribute("trip_id", str(trip.id))

        async with session_scope() as session:
            candidates = await CandidatePlaceRepository(session).list_for_trip(trip.id)
            votes = await VoteRepository(session).list_for_trip(trip.id)
            traveler_count = await TravelerRepository(session).count_for_trip(trip.id)

        scores = score_candidates(candidates, votes, traveler_count)

        span.set_attribute("aggregate.traveler_count", traveler_count)
        span.set_attribute("aggregate.vote_count", len(votes))
        span.set_attribute("aggregate.scored_count", len(scores))
        span.set_attribute("aggregate.dislike_weight", DISLIKE_WEIGHT)
        span.set_attribute("aggregate.must_have_weight", M1_MUST_HAVE_WEIGHT)
        if scores:
            span.set_attribute("aggregate.top_score", scores[0].score)

        return {"candidates": candidates, "votes": votes, "candidate_scores": scores}


__all__ = ["MUST_HAVE_WEIGHT", "aggregate_node", "score_candidate", "score_candidates"]
