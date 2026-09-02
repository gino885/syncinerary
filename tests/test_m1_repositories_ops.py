"""M1-2d: replan, agent run and eval repositories against real Postgres."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest_asyncio
import sqlalchemy as sa

from syncinerary.domain.models import (
    AgentRun,
    EvalResult,
    EvalScenario,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    Traveler,
    Trip,
)
from syncinerary.store import tables
from syncinerary.store.repositories import (
    AgentRunRepository,
    EvalResultRepository,
    EvalScenarioRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
)


@pytest_asyncio.fixture
async def empty_eval_tables(session):
    """Start these tests from an empty eval rail.

    `previous_commit_sha` is deliberately a table-wide query, and scenario
    names are unique, so any run of `python -m syncinerary.eval.runner` on
    the same database leaves rows that would make these assertions depend on
    whoever ran the eval last. The delete happens inside the test's own
    transaction, so it is rolled back with everything else.
    """
    await session.execute(sa.delete(tables.EvalResult))
    await session.execute(sa.delete(tables.EvalScenario))
    return session



async def _trip(session) -> Trip:
    return await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )


async def test_replan_event_stores_its_whole_trace(session):
    """§12.2: the trace is what the group reads before approving."""
    trip = await _trip(session)
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=2)
    )
    repo = ReplanEventRepository(session)

    trace = {
        "trigger": {"type": "reservation_cancelled", "node_id": "n1"},
        "affected_nodes": [{"node_id": "n1", "classification": "movable"}],
        "alternatives_considered": [
            {"candidate_id": "c1", "score": 0.72, "rejected_reason": "violates fatigue cap"},
            {"candidate_id": "c2", "score": 0.65, "chosen": True, "reason": "lowest transit"},
        ],
        "downstream_changes": [{"node_id": "n2", "old_time": "14:00", "new_time": "15:10"}],
    }
    saved = await repo.add(
        ReplanEvent(
            trip_id=trip.id,
            trigger_type=ReplanTrigger.RESERVATION_CANCELLED,
            trigger_payload={"node_id": "n1", "reason": "restaurant called"},
            affected_node_ids=[],
            trace_json=trace,
            proposed_version_id=version.id,
        )
    )

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.trigger_type is ReplanTrigger.RESERVATION_CANCELLED
    assert fetched.status is ReplanStatus.PENDING
    assert fetched.proposed_version_id == version.id
    assert fetched.trace_json == trace
    # A quantified reason on the chosen alternative is an F4 acceptance
    # criterion, so it has to survive the round trip intact.
    assert fetched.trace_json["alternatives_considered"][1]["chosen"] is True


async def test_approval_and_rejection_are_both_logged(session):
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    repo = ReplanEventRepository(session)

    approved = await repo.add(
        ReplanEvent(trip_id=trip.id, trigger_type=ReplanTrigger.WEATHER)
    )
    rejected = await repo.add(
        ReplanEvent(trip_id=trip.id, trigger_type=ReplanTrigger.OVERSLEPT)
    )
    assert len(await repo.list_pending(trip.id)) == 2

    a = await repo.decide(approved.id, ReplanStatus.APPROVED, traveler.id)
    r = await repo.decide(rejected.id, ReplanStatus.REJECTED, traveler.id)

    assert a.status is ReplanStatus.APPROVED
    assert r.status is ReplanStatus.REJECTED
    # Both carry who decided and when: a rejection is evidence the gate held.
    for event in (a, r):
        assert event.decided_by == traveler.id
        assert event.decided_at is not None
    assert await repo.list_pending(trip.id) == []


async def test_every_trigger_type_persists(session):
    """F4 must handle all five triggers plus other (§12.2)."""
    trip = await _trip(session)
    repo = ReplanEventRepository(session)
    for trigger in ReplanTrigger:
        await repo.add(ReplanEvent(trip_id=trip.id, trigger_type=trigger))

    stored = {e.trigger_type for e in await repo.list_for_trip(trip.id)}
    assert stored == set(ReplanTrigger)


async def test_agent_run_counters_accumulate(session):
    """§12.1: the budget breaker needs a partial trace when it aborts."""
    trip = await _trip(session)
    repo = AgentRunRepository(session)
    run = await repo.add(
        AgentRun(trip_id=trip.id, kind="plan", status="running", trace_id="abc123")
    )

    await repo.record_progress(
        run.id,
        step_count=7,
        token_cost=Decimal("0.0412"),
    )
    mid = await repo.get(run.id)
    assert mid.step_count == 7
    assert mid.token_cost == Decimal("0.041200")
    assert mid.status == "running"

    await repo.record_progress(run.id, status="budget_exceeded", step_count=12)
    end = await repo.get(run.id)
    assert end.status == "budget_exceeded"
    assert end.step_count == 12
    # Not passed this time, so it must not be reset.
    assert end.token_cost == Decimal("0.041200")


async def test_agent_run_trace_id_joins_to_phoenix(session):
    trip = await _trip(session)
    repo = AgentRunRepository(session)
    await repo.add(AgentRun(trip_id=trip.id, kind="gather", status="ok", trace_id="deadbeef"))
    runs = await repo.list_for_trip(trip.id)
    assert runs[0].trace_id == "deadbeef"


async def test_eval_scenario_round_trips_with_optional_disruption(session, empty_eval_tables):
    repo = EvalScenarioRepository(session)
    clean = await repo.add(
        EvalScenario(
            name="clean_5day_hokkaido",
            fixture={"days": 5, "travelers": 3},
            expected={"must_include": ["otaru_canal"]},
        )
    )
    await repo.add(
        EvalScenario(
            name="weather_storm_day3",
            fixture={"days": 5},
            disruption={"type": "weather", "day": 3},
            expected={},
        )
    )

    found = await repo.get_by_name("clean_5day_hokkaido")
    assert found is not None
    assert found.id == clean.id
    assert found.disruption is None
    assert found.expected == {"must_include": ["otaru_canal"]}

    stormy = await repo.get_by_name("weather_storm_day3")
    assert stormy.disruption == {"type": "weather", "day": 3}

    assert [s.name for s in await repo.list_all()] == [
        "clean_5day_hokkaido",
        "weather_storm_day3",
    ]


async def test_unknown_scenario_name_returns_none(session):
    assert await EvalScenarioRepository(session).get_by_name("nope") is None


async def test_eval_results_are_tagged_by_commit(session, empty_eval_tables):
    scenario = await EvalScenarioRepository(session).add(
        EvalScenario(name="budget_tight", fixture={}, expected={})
    )
    repo = EvalResultRepository(session)

    await repo.add(
        EvalResult(
            scenario_id=scenario.id,
            commit_sha="aaa111",
            scores={"feasibility": 1.0, "faithfulness": 0.81},
            passed=True,
        )
    )
    await repo.add(
        EvalResult(
            scenario_id=scenario.id,
            commit_sha="bbb222",
            scores={"feasibility": 0.0, "faithfulness": 0.79},
            passed=False,
        )
    )

    first = await repo.list_for_commit("aaa111")
    assert len(first) == 1
    assert first[0].passed is True
    assert first[0].scores["feasibility"] == 1.0

    second = await repo.list_for_commit("bbb222")
    assert second[0].passed is False


async def test_previous_commit_is_found_for_the_regression_diff(session, empty_eval_tables):
    """§12.3: the runner prints a diff against the last run."""
    scenario = await EvalScenarioRepository(session).add(
        EvalScenario(name="group_split", fixture={}, expected={})
    )
    repo = EvalResultRepository(session)
    await repo.add(
        EvalResult(scenario_id=scenario.id, commit_sha="older", scores={}, passed=True)
    )
    await repo.add(
        EvalResult(scenario_id=scenario.id, commit_sha="current", scores={}, passed=True)
    )

    assert await repo.previous_commit_sha("current") == "older"


async def test_previous_commit_is_none_on_the_very_first_run(session, empty_eval_tables):
    scenario = await EvalScenarioRepository(session).add(
        EvalScenario(name="first_ever", fixture={}, expected={})
    )
    repo = EvalResultRepository(session)
    await repo.add(
        EvalResult(scenario_id=scenario.id, commit_sha="only", scores={}, passed=True)
    )
    assert await repo.previous_commit_sha("only") is None


def test_every_table_has_a_repository():
    """CLAUDE.md §14: all CRUD goes through a repository, so a table without
    one is a table the API layer would be tempted to reach past store/ for."""
    from syncinerary.store import repositories
    from syncinerary.store.tables import Base

    covered = {
        cls.table.__tablename__
        for cls in vars(repositories).values()
        if isinstance(cls, type)
        and issubclass(cls, repositories.BaseRepository)
        and hasattr(cls, "table")
    }
    uncovered = set(Base.metadata.tables) - covered
    assert uncovered == set(), f"tables with no repository: {sorted(uncovered)}"
