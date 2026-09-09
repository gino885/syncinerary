"""Policy for the routing-aware repair loop. No orchestration, no LLM.

Stage 1 measures a day by straight-line dispersion and a walking estimate.
Stage 2 measures it by opening hours, real transit and a twelve-hour clock.
When the two disagree the fact learned is "not this candidate on that day",
which is a much weaker claim than "not this candidate", and the difference is
the whole point: a place should not lose its seat on the trip because its
first day assignment happened to be a bad one.

This module holds the decisions. The loop that applies them lives beside
_solve_one_day in stage2_route, because that is where a day is routed.

NO LLM IN THIS FILE. It is part of solver/ under CLAUDE.md section 2.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from syncinerary.config.solver import (
    REPAIR_MAX_DAY_SOLVES,
    REPAIR_MAX_REPLACEMENTS,
    REPAIR_MAX_ROUNDS,
)
from syncinerary.domain.models import CandidatePlace, CandidateScore

#: Refusals that are already a fact about the place and the date alone, with
#: no other candidate involved: its opening hours cannot hold a visit that
#: day, or a restaurant's hours never meet a meal window that day. These are
#: the only refusals that justify a unary "not on that day" block.
UNARY_REASON_CODES = frozenset({"closed_on_available_days", "no_meal_slot"})

#: A refusal that is about the day's whole combination, not about the place.
#: Stage 2 reports it when the place was open and the clock ran out, which
#: says nothing on its own about whether the place or its neighbours should
#: give way. It is the case that has to be probed rather than assumed.
COMBINATION_REASON_CODE = "no_day_fit"

#: Why the repair loop, rather than a single constraint, ended up removing a
#: place. The per-day codes above stay as they are; these two only appear when
#: the loop itself is the reason.
REASON_REPAIR_EXHAUSTED = "cross_day_repair_exhausted"
REASON_LOWER_MARGINAL_UTILITY = "lower_marginal_utility_than_conflicting_place"


class DayCapacity(BaseModel):
    """At most `limit` of these candidates can share this day.

    Measured by Stage 2 rather than inferred from which place it happened to
    refuse. That distinction is the whole point: a refusal names a victim, and
    a capacity names the constraint, leaving Stage 1 to choose the victim with
    the group's scores in front of it. With two members and a limit of one it
    is exactly the pairwise form the day-independent conflicts use.
    """

    day: int
    members: frozenset[UUID]
    limit: int = Field(ge=0)

    def key(self) -> tuple[int, tuple[str, ...]]:
        return (self.day, tuple(sorted(str(member) for member in self.members)))


class RepairBudget(BaseModel):
    """What the loop is allowed to spend. Every field is a hard stop."""

    max_rounds: int = Field(default=REPAIR_MAX_ROUNDS, ge=0)
    #: Extra Stage 2 solves across the whole loop. Each one is a transit
    #: lookup and a harness step, so this and not the round count is what
    #: bounds a long trip.
    max_day_solves: int = Field(default=REPAIR_MAX_DAY_SOLVES, ge=0)
    max_replacements: int = Field(default=REPAIR_MAX_REPLACEMENTS, ge=0)


class RepairLedger(BaseModel):
    """What the loop did, in terms a person can argue with.

    "The itinerary got better" is not a claim worth making without these: more
    stops can mean the planner swapped a place the group loved for two it did
    not, and that is a regression wearing a larger number.
    """

    repair_rounds: int = 0
    day_solves: int = 0
    same_day_reorders: int = 0
    cross_day_moves: int = 0
    cross_day_swaps: int = 0
    places_dropped_for_feasibility: int = 0
    #: What Stage 2 taught Stage 1, counted so a plan can be argued with.
    learned_blocked_days: int = 0
    learned_incompatible_pairs: int = 0
    learned_day_capacities: int = 0
    replacement_candidates_used: int = 0
    high_priority_places_preserved_by_reassignment: int = 0
    unresolved_structural_conflicts: int = 0

    def as_metrics(self) -> dict[str, int]:
        return {f"repair.{name}": value for name, value in self.model_dump().items()}


def candidate_value(score: float) -> int:
    """One candidate's worth to the trip, on Stage 1's own scale.

    Deliberately the same expression Stage 1 minimizes against, so the repair
    loop cannot prefer an itinerary Stage 1 would have rejected. Inventing a
    second priority model here is how the two ends of the planner start
    disagreeing about which places matter.
    """
    return round((max(-2.0, min(2.0, score)) + 2.0) * 25)


def value_by_candidate(
    candidates: Sequence[CandidatePlace],
    scores: Sequence[CandidateScore],
) -> dict[UUID, int]:
    by_id = {score.candidate_id: score.score for score in scores}
    return {
        candidate.id: candidate_value(by_id.get(candidate.id, 0.0))
        for candidate in candidates
    }


class PlanValue(BaseModel):
    """How good an itinerary is, ordered the way section 9 asks for.

    Retained user value first and stop count second, so a twelve-stop plan
    holding the group's best places beats a fourteen-stop one that bought its
    extra rows by dropping them. Transit only breaks ties.
    """

    retained_value: int
    placed_count: int
    total_transit_minutes: int

    def __gt__(self, other: PlanValue) -> bool:
        return self._key() > other._key()

    def _key(self) -> tuple[int, int, int]:
        return (self.retained_value, self.placed_count, -self.total_transit_minutes)


def plan_value(
    placed_ids: Iterable[UUID],
    values: dict[UUID, int],
    total_transit_minutes: int,
) -> PlanValue:
    placed = list(placed_ids)
    return PlanValue(
        retained_value=sum(values.get(candidate_id, 0) for candidate_id in placed),
        placed_count=len(placed),
        total_transit_minutes=total_transit_minutes,
    )


def learn_day_blocks(
    refusals: Iterable[tuple[UUID, int, str]],
    *,
    protected_ids: set[UUID],
    conflicted_ids: set[UUID] | None = None,
    existing: dict[UUID, set[int]] | None = None,
) -> tuple[dict[UUID, set[int]], bool]:
    """Turn this round's Stage 2 refusals into "not on that day" facts.

    Returns the accumulated blocks and whether anything new was learned, which
    is the loop's termination signal: a round that learns nothing would re-run
    an identical Stage 1 and get an identical answer.

    Only the two refusals that are already about the place and the date alone
    are learned here: its hours cannot hold a visit that day, or a restaurant
    cannot reach a meal window that day. Neither mentions another candidate,
    so neither can be an accident of which places shared the day.

    A "no_day_fit" refusal is deliberately not among them, and that is the
    point of this function being narrow. It means the clock ran out, which is
    a fact about the whole combination: the place was open, and something has
    to give, but nothing here says it should be this one. Turning it into
    "A cannot be on Thursday" is both too strong and decided by the wrong
    party. It is probed instead, and becomes an ExclusionGroup.

    A refusal the transit chain caused by having no provider answer never
    reaches this function at all: Stage 2's codes come from its schedule
    model, after the chain has already applied its estimate.

    A candidate already known to conflict with another is never blocked, and
    that exclusion is the whole reason `conflicted_ids` exists. Stage 2 seats
    one of two incompatible places and refuses the other by position, not by
    worth, so blocking whichever it refused would let seating order decide
    which of the two survives. The pair constraint says the same thing more
    precisely and leaves the choice to Stage 1, where the group's scores are.
    """
    blocks = {
        candidate_id: set(days) for candidate_id, days in (existing or {}).items()
    }
    conflicted = conflicted_ids or set()
    learned = False
    for candidate_id, day, reason_code in refusals:
        if reason_code not in UNARY_REASON_CODES:
            continue
        if candidate_id in protected_ids or candidate_id in conflicted:
            continue
        days = blocks.setdefault(candidate_id, set())
        if day not in days:
            days.add(day)
            learned = True
    return blocks, learned


def merge_day_capacities(
    existing: Sequence[DayCapacity],
    found: Iterable[DayCapacity],
) -> tuple[list[DayCapacity], bool]:
    """Accumulate capacity facts, keeping the tightest known for each day set.

    A later round can only measure the same set as tight or tighter, never
    looser, so replacing on a strictly smaller limit is safe and re-learning
    the same limit teaches nothing and stops the loop.
    """
    by_key = {capacity.key(): capacity for capacity in existing}
    learned = False
    for capacity in found:
        known = by_key.get(capacity.key())
        if known is None or capacity.limit < known.limit:
            by_key[capacity.key()] = capacity
            learned = True
    return sorted(by_key.values(), key=lambda item: (item.day, item.key())), learned


def learn_incompatible_pairs(
    routes_pairs: Iterable[Iterable[tuple[UUID, UUID]]],
    *,
    existing: set[tuple[UUID, UUID]] | None = None,
) -> tuple[set[tuple[UUID, UUID]], bool]:
    """Accumulate "these two cannot share any day" facts across the days.

    A pair with no arc in either direction is the one genuinely structural
    thing Stage 2 discovers, and it is not a fact about the day it was found
    on. Kept apart from the per-day blocks because Stage 1 acts on it
    differently: a block moves a place, a conflict makes Stage 1 choose
    between two of them on value.
    """
    pairs = set(existing or set())
    before = len(pairs)
    for day_pairs in routes_pairs:
        pairs.update(day_pairs)
    return pairs, len(pairs) > before


def classify_bucket_changes(
    before: Sequence[Sequence[CandidatePlace]],
    after: Sequence[Sequence[CandidatePlace]],
) -> tuple[int, int]:
    """(cross-day moves, cross-day swaps) between two Stage 1 assignments.

    A swap is counted as one swap rather than two moves, because that is what
    a reader wants to know: two places traded days to keep them both, which is
    a different repair from one place finding a quieter day.
    """
    day_of_before = {
        candidate.id: day for day, bucket in enumerate(before) for candidate in bucket
    }
    day_of_after = {
        candidate.id: day for day, bucket in enumerate(after) for candidate in bucket
    }
    moved = {
        candidate_id: (day_of_before[candidate_id], day_of_after[candidate_id])
        for candidate_id in day_of_before.keys() & day_of_after.keys()
        if day_of_before[candidate_id] != day_of_after[candidate_id]
    }
    swapped: set[UUID] = set()
    for candidate_id, (origin, destination) in moved.items():
        if candidate_id in swapped:
            continue
        partner = next(
            (
                other
                for other, (other_origin, other_destination) in moved.items()
                if other not in swapped
                and other != candidate_id
                and (other_origin, other_destination) == (destination, origin)
            ),
            None,
        )
        if partner is not None:
            swapped.update({candidate_id, partner})
    swaps = len(swapped) // 2
    return len(moved) - len(swapped), swaps


def select_replacements(
    reserve: Sequence[CandidatePlace],
    *,
    already_admitted: set[UUID],
    limit: int,
) -> list[CandidatePlace]:
    """The next-best reserves, in the order the shortlist already ranked them.

    No re-scoring: `reserve` arrives in `wishlist_excluded_ids` order, which is
    aggregate's ranking with its name tiebreak, and re-sorting it here would
    make the planner's second choice disagree with its first.
    """
    if limit <= 0:
        return []
    return [
        candidate
        for candidate in reserve
        if candidate.id not in already_admitted
    ][:limit]


__all__ = [
    "COMBINATION_REASON_CODE",
    "REASON_LOWER_MARGINAL_UTILITY",
    "REASON_REPAIR_EXHAUSTED",
    "UNARY_REASON_CODES",
    "DayCapacity",
    "PlanValue",
    "RepairBudget",
    "RepairLedger",
    "candidate_value",
    "classify_bucket_changes",
    "learn_day_blocks",
    "learn_incompatible_pairs",
    "merge_day_capacities",
    "plan_value",
    "select_replacements",
    "value_by_candidate",
]
