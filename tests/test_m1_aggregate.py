"""M1-5: deterministic consensus scoring (CLAUDE.md §10.1).

Mostly pure-function tests: no database, no clock. That is the point of
putting this module on the deterministic side of §2.
"""
from __future__ import annotations

import ast
import inspect
from datetime import date
from uuid import UUID, uuid4

import pytest

from syncinerary.agents import aggregate
from syncinerary.agents.aggregate import (
    aggregate_node,
    score_candidate,
    score_candidates,
)
from syncinerary.config.aggregate import DISLIKE_WEIGHT
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Traveler,
    Trip,
    TripState,
    Vote,
    VoteSignal,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    TravelerRepository,
    TripRepository,
    VoteRepository,
)


def _votes(candidate_id: UUID, *signals: VoteSignal) -> list[Vote]:
    return [
        Vote(candidate_id=candidate_id, traveler_id=uuid4(), signal=s) for s in signals
    ]


def _candidate(name: str, kind: CandidateType = CandidateType.ATTRACTION) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(), type=kind, name_canonical=name, lat=43.0, lng=141.3
    )


# ----- the architectural rule -----


BANNED_IMPORT_ROOTS = {"anthropic", "langchain", "langchain_anthropic", "openai", "langgraph"}


def _imported_roots(module) -> set[str]:
    """Top-level package of every import in a module, read from its AST.

    Grepping the source would trip over the module docstring, which talks
    about LLMs at length precisely because it must not import one.
    """
    tree = ast.parse(inspect.getsource(module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_aggregate_module_imports_no_llm_sdk():
    """CLAUDE.md §2 names aggregate.py in the forbidden list. This is the rule
    the whole design is defended on, so it gets a test, not a comment. M2
    generalises it into the CI grep check across every forbidden module."""
    offending = _imported_roots(aggregate) & BANNED_IMPORT_ROOTS
    assert offending == set(), f"aggregate.py must not import: {sorted(offending)}"


# ----- the formula -----


def test_unanimous_like_scores_one():
    cid = uuid4()
    score = score_candidate(cid, _votes(cid, *[VoteSignal.LIKE] * 4), traveler_count=4)
    assert score.votes_pos == 4
    assert score.votes_neg == 0
    assert score.acceptance == pytest.approx(1.0)
    assert score.score == pytest.approx(1.0)


def test_dislike_is_weighted_more_heavily_than_like():
    """§16 sets dislike_weight to 1.5: one objection outweighs one approval."""
    cid = uuid4()
    score = score_candidate(
        cid, _votes(cid, VoteSignal.LIKE, VoteSignal.DISLIKE), traveler_count=2
    )
    # (1 - 1 * 1.5) / 2
    assert score.acceptance == pytest.approx(-0.25)
    assert score.score < 0


def test_worked_example_from_section_10_1():
    cid = uuid4()
    score = score_candidate(
        cid,
        _votes(cid, VoteSignal.LIKE, VoteSignal.LIKE, VoteSignal.DISLIKE),
        traveler_count=4,
    )
    # votes_pos 2, votes_neg 1, votes_total 4 -> (2 - 1.5) / 4
    assert score.acceptance == pytest.approx(0.125)


def test_like_with_note_counts_the_same_as_a_plain_like():
    """§9.3: a condition attached to a note does not reduce weight. The
    condition is the solver's problem, not the aggregator's."""
    plain, noted = uuid4(), uuid4()
    a = score_candidate(plain, _votes(plain, VoteSignal.LIKE, VoteSignal.LIKE), 3)
    b = score_candidate(
        noted, _votes(noted, VoteSignal.LIKE, VoteSignal.LIKE_WITH_NOTE), 3
    )
    assert a.score == b.score
    assert b.votes_pos == 2


def test_must_have_is_ignored_in_m1():
    """§13 M1: acceptance score ignoring must_have."""
    cid = uuid4()
    with_must = score_candidate(cid, _votes(cid, VoteSignal.MUST_HAVE), traveler_count=2)
    assert with_must.votes_must == 1
    # Counted and visible, but contributing nothing yet.
    assert with_must.must_have_bonus == 0.0
    assert with_must.score == with_must.acceptance


def test_must_have_arm_works_when_the_weight_is_turned_on():
    """M4 enables this by changing a constant, not by reshaping the model."""
    cid = uuid4()
    score = score_candidate(
        cid,
        _votes(cid, VoteSignal.LIKE, VoteSignal.MUST_HAVE),
        traveler_count=2,
        must_have_weight=0.3,
    )
    assert score.must_have_bonus == pytest.approx(0.3)
    assert score.score == pytest.approx(score.acceptance + 0.3)


def test_a_candidate_with_no_votes_scores_zero():
    score = score_candidate(uuid4(), [], traveler_count=4)
    assert score.score == 0.0
    assert score.votes_pos == score.votes_neg == 0


def test_empty_trip_does_not_divide_by_zero():
    score = score_candidate(uuid4(), [], traveler_count=0)
    assert score.score == 0.0
    # votes_total stays visible so the reason is readable, not inferred.
    assert score.votes_total == 0


def test_the_whole_breakdown_is_carried_not_just_the_score():
    """§2 requires this to be auditable: you should see why a card ranked
    where it did without rerunning anything."""
    cid = uuid4()
    score = score_candidate(
        cid, _votes(cid, VoteSignal.LIKE, VoteSignal.DISLIKE, VoteSignal.LIKE), 5
    )
    assert score.votes_pos == 2
    assert score.votes_neg == 1
    assert score.votes_total == 5
    assert score.acceptance == pytest.approx((2 - 1 * DISLIKE_WEIGHT) / 5)
    assert score.score == pytest.approx(score.acceptance + score.must_have_bonus)


# ----- ranking a pool -----


def test_pool_comes_back_highest_first():
    loved, mixed, hated = _candidate("Aaa"), _candidate("Bbb"), _candidate("Ccc")
    votes = [
        *_votes(loved.id, VoteSignal.LIKE, VoteSignal.LIKE),
        *_votes(mixed.id, VoteSignal.LIKE, VoteSignal.DISLIKE),
        *_votes(hated.id, VoteSignal.DISLIKE, VoteSignal.DISLIKE),
    ]
    ranked = score_candidates([mixed, hated, loved], votes, traveler_count=2)
    assert [s.candidate_id for s in ranked] == [loved.id, mixed.id, hated.id]


def test_ties_break_on_name_so_ranking_is_reproducible():
    """F2 replay compares rankings across runs; sorting on score alone would
    leave ties at the mercy of input order."""
    zulu, alpha = _candidate("Zulu"), _candidate("Alpha")
    votes = [*_votes(zulu.id, VoteSignal.LIKE), *_votes(alpha.id, VoteSignal.LIKE)]

    forwards = score_candidates([zulu, alpha], votes, 2)
    backwards = score_candidates([alpha, zulu], votes, 2)

    assert forwards[0].score == forwards[1].score
    assert [s.candidate_id for s in forwards] == [alpha.id, zulu.id]
    assert [s.candidate_id for s in backwards] == [alpha.id, zulu.id]


def test_lodging_is_not_scored():
    """§8.6 keeps lodging out of the deck, so it has no votes. Scoring it
    would put zeroes at the bottom of every ranking and imply the group
    considered and rejected it."""
    hotel = _candidate("JR Tower Hotel", CandidateType.LODGING)
    park = _candidate("Odori Park")
    ranked = score_candidates([hotel, park], _votes(park.id, VoteSignal.LIKE), 1)
    assert [s.candidate_id for s in ranked] == [park.id]


def test_votes_for_other_candidates_do_not_leak():
    a, b = _candidate("Aaa"), _candidate("Bbb")
    votes = _votes(a.id, VoteSignal.LIKE, VoteSignal.LIKE)
    ranked = score_candidates([a, b], votes, traveler_count=2)
    by_id = {s.candidate_id: s for s in ranked}
    assert by_id[a.id].votes_pos == 2
    assert by_id[b.id].votes_pos == 0


def test_scoring_an_empty_pool_is_empty():
    assert score_candidates([], [], 3) == []


def test_scoring_is_reproducible():
    pool = [_candidate(n) for n in ("Aaa", "Bbb", "Ccc")]
    votes = [
        *_votes(pool[0].id, VoteSignal.LIKE),
        *_votes(pool[1].id, VoteSignal.DISLIKE),
    ]
    runs = [score_candidates(pool, votes, 3) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


# ----- the node -----


async def test_aggregate_node_scores_what_is_stored(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    travelers = TravelerRepository(session)
    ana = await travelers.add(Traveler(trip_id=trip.id, name="Ana"))
    bo = await travelers.add(Traveler(trip_id=trip.id, name="Bo"))

    places = CandidatePlaceRepository(session)
    loved = await places.add(
        CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Canal",
            lat=43.19,
            lng=140.99,
        )
    )
    hated = await places.add(
        CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.ATTRACTION,
            name_canonical="Some Mall",
            lat=43.06,
            lng=141.35,
        )
    )
    votes = VoteRepository(session)
    for traveler in (ana, bo):
        await votes.upsert(
            Vote(candidate_id=loved.id, traveler_id=traveler.id, signal=VoteSignal.LIKE)
        )
        await votes.upsert(
            Vote(candidate_id=hated.id, traveler_id=traveler.id, signal=VoteSignal.DISLIKE)
        )

    _use_test_session(monkeypatch, session)
    result = await aggregate_node(TripState(trip=trip))

    scores = result["candidate_scores"]
    assert [s.candidate_id for s in scores] == [loved.id, hated.id]
    assert scores[0].votes_total == 2
    assert scores[0].score == pytest.approx(1.0)
    assert scores[1].score == pytest.approx(-1.5)


async def test_aggregate_node_returns_a_partial_dict_only(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    _use_test_session(monkeypatch, session)
    state = TripState(trip=trip)

    result = await aggregate_node(state)

    assert set(result) == {"candidates", "votes", "candidate_scores"}
    assert state.candidate_scores == []


def _use_test_session(monkeypatch, session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(aggregate, "session_scope", _scope)
