"""M1-6: deterministic shortlist selection (CLAUDE.md §10.2)."""
from __future__ import annotations

import ast
import inspect
from datetime import date
from uuid import uuid4

from syncinerary.agents import shortlist as shortlist_module
from syncinerary.agents.aggregate import score_candidates
from syncinerary.agents.shortlist import build_shortlist, shortlist_node, target_size
from syncinerary.config.aggregate import SLOTS_PER_DAY
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateScore,
    CandidateType,
    Trip,
    TripState,
    Vote,
    VoteSignal,
)
from syncinerary.store.repositories import ShortlistStateRepository, TripRepository

BANNED_IMPORT_ROOTS = {"anthropic", "langchain", "langchain_anthropic", "openai", "langgraph"}


def _score(score: float) -> CandidateScore:
    return CandidateScore(
        candidate_id=uuid4(),
        votes_pos=0,
        votes_neg=0,
        votes_must=0,
        votes_total=3,
        acceptance=score,
        must_have_bonus=0.0,
        score=score,
    )


def _ranked(count: int) -> list[CandidateScore]:
    """Descending scores, as aggregate.score_candidates would produce."""
    return [_score(1.0 - i / 100) for i in range(count)]


# ----- the architectural rule -----


def test_shortlist_module_imports_no_llm_sdk():
    """§2 forbidden list, same reasoning as aggregate.py."""
    tree = ast.parse(inspect.getsource(shortlist_module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots & BANNED_IMPORT_ROOTS == set()


# ----- target size -----


def test_target_size_is_days_times_slots_per_day():
    assert target_size(5) == 5 * SLOTS_PER_DAY
    assert target_size(5) == 30  # §16 default of 6 slots


def test_target_size_scales_with_trip_length():
    assert target_size(1) == SLOTS_PER_DAY
    assert target_size(10) == 10 * SLOTS_PER_DAY


def test_target_size_is_never_negative():
    assert target_size(0) == 0
    assert target_size(-3) == 0


# ----- selection -----


def test_top_n_are_shortlisted_and_the_rest_are_wishlisted():
    ranked = _ranked(40)
    selected, excluded = build_shortlist(ranked, days=5)

    assert len(selected) == 30
    assert len(excluded) == 10
    assert selected == [s.candidate_id for s in ranked[:30]]
    assert excluded == [s.candidate_id for s in ranked[30:]]


def test_nothing_is_lost_between_the_two_lists():
    """§10.3 surfaces excluded cards next to the itinerary, so a card that
    fell off the shortlist has to be findable."""
    ranked = _ranked(37)
    selected, excluded = build_shortlist(ranked, days=5)
    assert set(selected) | set(excluded) == {s.candidate_id for s in ranked}
    assert set(selected) & set(excluded) == set()


def test_a_pool_smaller_than_target_shortlists_everything():
    ranked = _ranked(12)
    selected, excluded = build_shortlist(ranked, days=5)
    assert len(selected) == 12
    assert excluded == []


def test_an_empty_pool_produces_an_empty_shortlist():
    assert build_shortlist([], days=5) == ([], [])


def test_shorter_trips_shortlist_less():
    ranked = _ranked(40)
    three_day, _ = build_shortlist(ranked, days=3)
    five_day, _ = build_shortlist(ranked, days=5)
    assert len(three_day) == 3 * SLOTS_PER_DAY
    assert len(five_day) == 5 * SLOTS_PER_DAY


def test_incoming_order_is_preserved_not_re_sorted():
    """Re-sorting on score alone would drop the name tiebreak that
    aggregate.score_candidates applied, making equal-scoring cards
    non-reproducible."""
    tied = [_score(0.5) for _ in range(6)]
    selected, _ = build_shortlist(tied, days=1)
    assert selected == [s.candidate_id for s in tied[:SLOTS_PER_DAY]]


def test_disliked_cards_still_make_a_small_pool():
    """§10.2 is literally top-N. On a short pool that can include a card the
    group disliked; the M4 confirmation screen is the designed remedy, not a
    score floor invented here."""
    ranked = [_score(0.9), _score(-1.5)]
    selected, excluded = build_shortlist(ranked, days=5)
    assert len(selected) == 2
    assert excluded == []


def test_selection_is_reproducible():
    ranked = _ranked(40)
    runs = [build_shortlist(ranked, days=5) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_it_composes_with_the_aggregator():
    """The two deterministic stages have to agree end to end."""
    pool = [
        CandidatePlace(
            trip_id=uuid4(),
            type=CandidateType.ATTRACTION,
            name_canonical=f"Place {i:02d}",
            lat=43.0,
            lng=141.3,
        )
        for i in range(10)
    ]
    # Place 00 liked twice, Place 01 disliked twice, rest unvoted.
    votes = [
        Vote(candidate_id=pool[0].id, traveler_id=uuid4(), signal=VoteSignal.LIKE),
        Vote(candidate_id=pool[0].id, traveler_id=uuid4(), signal=VoteSignal.LIKE),
        Vote(candidate_id=pool[1].id, traveler_id=uuid4(), signal=VoteSignal.DISLIKE),
        Vote(candidate_id=pool[1].id, traveler_id=uuid4(), signal=VoteSignal.DISLIKE),
    ]
    scores = score_candidates(pool, votes, traveler_count=2)
    selected, excluded = build_shortlist(scores, days=1)

    # 10 cards, target 1 * 6, so six in and four out.
    assert len(selected) == SLOTS_PER_DAY
    assert len(excluded) == 10 - SLOTS_PER_DAY
    # The card everyone liked ranks first, the one everyone disliked ranks
    # last and is therefore the furthest from making the cut.
    assert selected[0] == pool[0].id
    assert excluded[-1] == pool[1].id


# ----- the node -----


async def test_shortlist_node_persists_the_state(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    ranked = _ranked(40)
    _use_test_session(monkeypatch, session)

    result = await shortlist_node(TripState(trip=trip, candidate_scores=ranked))

    stored = await ShortlistStateRepository(session).get_for_trip(trip.id)
    assert stored is not None
    assert len(stored.selected_candidate_ids) == 30
    assert len(stored.wishlist_excluded_ids) == 10
    assert result["shortlist"].selected_candidate_ids == stored.selected_candidate_ids


async def test_shortlist_node_claims_no_approval_that_did_not_happen(session, monkeypatch):
    """M1 auto-proceeds with no confirmation step (§13), so writing a
    confirmed_at would assert a group approval that never occurred."""
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    _use_test_session(monkeypatch, session)

    await shortlist_node(TripState(trip=trip, candidate_scores=_ranked(40)))

    stored = await ShortlistStateRepository(session).get_for_trip(trip.id)
    assert stored.confirmed_by == []
    assert stored.confirmed_at is None
    # Must-go is marked by the group in M4; nothing pins a card in M1.
    assert stored.must_go_candidate_ids == []


async def test_rerunning_replaces_rather_than_duplicates(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    _use_test_session(monkeypatch, session)

    await shortlist_node(TripState(trip=trip, candidate_scores=_ranked(40)))
    second = _ranked(8)
    await shortlist_node(TripState(trip=trip, candidate_scores=second))

    stored = await ShortlistStateRepository(session).get_for_trip(trip.id)
    assert stored.selected_candidate_ids == [s.candidate_id for s in second]


async def test_shortlist_node_returns_a_partial_dict_only(session, monkeypatch):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    _use_test_session(monkeypatch, session)
    state = TripState(trip=trip, candidate_scores=_ranked(40))

    result = await shortlist_node(state)

    assert set(result) == {"shortlist"}
    assert state.shortlist is None


def _use_test_session(monkeypatch, session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(shortlist_module, "session_scope", _scope)
