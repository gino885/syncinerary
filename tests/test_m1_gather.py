"""M1-3: the fixture-backed gather stage."""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest

from syncinerary.agents.gather import FixtureNotFound, gather_node, load_candidates
from syncinerary.agents.gather.fixture import FIXTURE_DIR
from syncinerary.config.gather import POOL_PER_DAY
from syncinerary.domain.models import CandidatePlace, CandidateType, Trip, TripState
from syncinerary.store.repositories import CandidatePlaceRepository, TripRepository

RAW_FIXTURE = json.loads((FIXTURE_DIR / "hokkaido_fixture.json").read_text(encoding="utf-8"))


def _trip_model(days: int = 5) -> Trip:
    return Trip(
        destination="Hokkaido",
        start_date=date(2026, 5, 21),
        end_date=date(2026, 5, 25),
        days=days,
    )


# ----- fixture content -----


def test_fixture_covers_all_three_card_types():
    by_type = {t: 0 for t in ("attraction", "food", "lodging")}
    for entry in RAW_FIXTURE["candidates"]:
        by_type[entry["type"]] += 1
    assert all(count > 0 for count in by_type.values()), by_type
    # Enough swipeable cards to fill a 5-day pool (5 * 7 = 35) with room over.
    assert by_type["attraction"] + by_type["food"] >= 35


def test_every_fixture_entry_validates_as_a_candidate():
    trip_id = uuid4()
    for entry in RAW_FIXTURE["candidates"]:
        CandidatePlace(trip_id=trip_id, **entry)


def test_fixture_entries_carry_the_fields_the_solver_needs():
    """Stage 2 in M1 uses opening hours and coordinates, nothing else."""
    for entry in RAW_FIXTURE["candidates"]:
        assert -90 <= entry["lat"] <= 90
        assert 100 <= entry["lng"] <= 180, entry["name_canonical"]
        assert 1 <= entry["price_tier"] <= 4
        assert 1 <= entry["fatigue_cost"] <= 3
        assert entry["category"]
        hours = entry["hours_by_weekday"]
        assert set(hours) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        for intervals in hours.values():
            for start, end in intervals:
                assert 0 <= start < end <= 24, entry["name_canonical"]


def test_fixture_names_are_unique():
    names = [e["name_canonical"] for e in RAW_FIXTURE["candidates"]]
    assert len(names) == len(set(names))


def test_fixture_backbone_scores_are_not_passed_off_as_mined():
    """§8.1 computes backbone_score from articles_mentioning / total_articles.
    These are hand-authored, so articles_count stays null rather than
    inventing a denominator that never existed."""
    for entry in RAW_FIXTURE["candidates"]:
        for source in entry["sources"]:
            assert source["type"] == "backbone"
            assert source["articles_count"] is None
            assert 0.0 < source["score"] <= 1.0


# ----- pool building -----


def test_pool_is_capped_at_days_times_pool_per_day():
    trip_id = uuid4()
    pool = load_candidates("Hokkaido", trip_id, days=5)
    swipeable = [c for c in pool if c.type is not CandidateType.LODGING]
    assert len(swipeable) == 5 * POOL_PER_DAY


def test_shorter_trips_get_smaller_pools():
    trip_id = uuid4()
    short = load_candidates("Hokkaido", trip_id, days=3)
    long = load_candidates("Hokkaido", trip_id, days=5)
    short_swipeable = [c for c in short if c.type is not CandidateType.LODGING]
    long_swipeable = [c for c in long if c.type is not CandidateType.LODGING]
    assert len(short_swipeable) == 3 * POOL_PER_DAY
    assert len(short_swipeable) < len(long_swipeable)


def test_lodging_does_not_compete_for_pool_slots(session):
    """§8.6 keeps lodging out of the swipe deck, so it is not in the pool
    budget: all of it loads regardless of trip length."""
    fixture_lodging = sum(1 for e in RAW_FIXTURE["candidates"] if e["type"] == "lodging")
    for days in (2, 5):
        pool = load_candidates("Hokkaido", uuid4(), days=days)
        lodging = [c for c in pool if c.type is CandidateType.LODGING]
        assert len(lodging) == fixture_lodging


def test_pool_is_ranked_by_source_score():
    pool = load_candidates("Hokkaido", uuid4(), days=5)
    swipeable = [c for c in pool if c.type is not CandidateType.LODGING]
    scores = [max(s.score for s in c.sources) for c in swipeable]
    assert scores == sorted(scores, reverse=True)
    # Otaru Canal is the highest scoring card in the fixture.
    assert swipeable[0].name_canonical == "Otaru Canal"


def test_pool_is_identical_across_runs():
    """F2 replay depends on gather being reproducible."""
    trip_id = uuid4()
    first = load_candidates("Hokkaido", trip_id, days=5)
    second = load_candidates("Hokkaido", trip_id, days=5)
    assert [c.name_canonical for c in first] == [c.name_canonical for c in second]


def test_unknown_destination_fails_loudly():
    with pytest.raises(FixtureNotFound, match="Antarctica"):
        load_candidates("Antarctica", uuid4(), days=5)


def test_destination_lookup_ignores_case_and_spacing():
    assert load_candidates("  hokkaido ", uuid4(), days=5)


# ----- the node -----


async def test_gather_node_persists_the_pool(session, monkeypatch):
    trip = await TripRepository(session).add(_trip_model())
    _use_test_session(monkeypatch, session)

    result = await gather_node(TripState(trip=trip))

    assert "candidates" in result
    saved = await CandidatePlaceRepository(session).list_for_trip(trip.id)
    assert len(saved) == len(result["candidates"])
    assert len(saved) == 5 * POOL_PER_DAY + 5  # pool cap plus all lodging


async def test_gather_node_returns_a_partial_dict_only(session, monkeypatch):
    """CLAUDE.md §14: nodes return a partial dict, they do not mutate state."""
    trip = await TripRepository(session).add(_trip_model())
    _use_test_session(monkeypatch, session)
    state = TripState(trip=trip)

    result = await gather_node(state)

    assert set(result) == {"candidates"}
    # The input state is untouched: mutating it would break the checkpointer
    # that the swipe interrupt relies on.
    assert state.candidates == []


async def test_gather_node_is_re_entrant(session, monkeypatch):
    """interrupt_after=["gather"] means a resumed thread can run this again."""
    trip = await TripRepository(session).add(_trip_model())
    _use_test_session(monkeypatch, session)

    first = await gather_node(TripState(trip=trip))
    second = await gather_node(TripState(trip=trip))

    # The second run wrote nothing: same rows, same ids, no second pool.
    repo = CandidatePlaceRepository(session)
    assert await repo.count_for_trip(trip.id) == len(first["candidates"])
    assert {c.id for c in second["candidates"]} == {c.id for c in first["candidates"]}


async def test_gather_node_keeps_lodging_out_of_the_swipe_deck(session, monkeypatch):
    trip = await TripRepository(session).add(_trip_model())
    _use_test_session(monkeypatch, session)
    await gather_node(TripState(trip=trip))

    repo = CandidatePlaceRepository(session)
    swipeable = await repo.list_swipeable(trip.id)
    lodging = await repo.list_by_type(trip.id, CandidateType.LODGING)
    assert len(lodging) == 5
    assert all(c.type is not CandidateType.LODGING for c in swipeable)
    assert len(swipeable) == 5 * POOL_PER_DAY


def _use_test_session(monkeypatch, session):
    """Point the node's session_scope at the test's rolled-back session.

    The node opens its own scope so it can run inside LangGraph without a
    session being threaded through the state. Under test we substitute the
    fixture's session so writes land in the transaction that gets rolled
    back, and suppress the commit for the same reason.
    """
    from contextlib import asynccontextmanager

    from syncinerary.agents.gather import fixture as fixture_module

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(fixture_module, "session_scope", _scope)
