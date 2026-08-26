"""M2 reliability harness acceptance tests (CLAUDE.md section 12.1)."""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from syncinerary.domain.models import Trip
from syncinerary.harness import wrapper as wrapper_module
from syncinerary.harness.budget import BudgetExceeded, TokenPricing
from syncinerary.harness.loop_detector import LoopDetector, NoProgress, ToolCycle
from syncinerary.harness.wrapper import (
    LLMMessage,
    LLMRequest,
    PostgresRunRecorder,
    call_llm,
    tracked_run,
)
from syncinerary.store.repositories import AgentRunRepository, TripRepository


def test_two_step_state_cycle_raises_no_progress_before_step_budget():
    detector = LoopDetector(window_size=6, repeat_threshold=3)

    detector.observe_state({"node": "a", "value": 1})
    detector.observe_state({"node": "b", "value": 2})
    detector.observe_state({"node": "a", "value": 1})
    detector.observe_state({"node": "b", "value": 2})

    with pytest.raises(NoProgress, match="repeated 3 times"):
        detector.observe_state({"node": "a", "value": 1})


def test_equivalent_tool_arguments_raise_tool_cycle():
    detector = LoopDetector(window_size=6, repeat_threshold=3)

    detector.observe_tool("search", {"destination": "Hokkaido", "days": 5})
    detector.observe_tool("search", {"days": 5, "destination": "Hokkaido"})

    with pytest.raises(ToolCycle, match="search"):
        detector.observe_tool("search", {"destination": "Hokkaido", "days": 5})


def test_tool_cycle_uses_its_own_configured_threshold():
    detector = LoopDetector(
        window_size=6,
        repeat_threshold=3,
        tool_repeat_threshold=2,
    )

    detector.observe_tool("search", {"destination": "Hokkaido"})
    with pytest.raises(ToolCycle):
        detector.observe_tool("search", {"destination": "Hokkaido"})


def test_benign_distinct_states_do_not_raise_no_progress():
    detector = LoopDetector(window_size=6, repeat_threshold=3)
    for step in range(20):
        detector.observe_state({"step": step, "result_count": step + 1})


class StubMessages:
    async def create(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


class MissingUsageMessages:
    async def create(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="done")],
        )


async def test_missing_model_usage_fails_instead_of_bypassing_the_budget(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date="2026-05-21",
            end_date="2026-05-21",
            days=1,
        )
    )

    @asynccontextmanager
    async def test_session_scope():
        yield session

    recorder = PostgresRunRecorder(session_factory=test_session_scope)
    request = LLMRequest(
        model="claude-opus-4-7",
        max_tokens=10,
        system="Return one word.",
        messages=[LLMMessage(role="user", content="Go")],
    )

    with pytest.raises(RuntimeError, match="usage"):
        async with tracked_run(trip_id=trip.id, kind="plan", recorder=recorder):
            await call_llm(request, client=MissingUsageMessages())

    runs = await AgentRunRepository(session).list_for_trip(trip.id)
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].step_count == 1


async def test_tiny_token_budget_aborts_and_persists_partial_run(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date="2026-05-21",
            end_date="2026-05-21",
            days=1,
        )
    )

    @asynccontextmanager
    async def test_session_scope():
        yield session

    recorder = PostgresRunRecorder(session_factory=test_session_scope)
    request = LLMRequest(
        model="claude-opus-4-7",
        max_tokens=10,
        system="Return one word.",
        messages=[LLMMessage(role="user", content="Go")],
    )

    with pytest.raises(BudgetExceeded, match="token cost"):
        async with tracked_run(
            trip_id=trip.id,
            kind="plan",
            max_steps=10,
            max_token_cost_usd=Decimal("0.000001"),
            recorder=recorder,
        ):
            await call_llm(
                request,
                client=StubMessages(),
                pricing=TokenPricing(
                    input_usd_per_million=Decimal(5),
                    output_usd_per_million=Decimal(25),
                ),
                state={"node": "explain"},
            )

    runs = await AgentRunRepository(session).list_for_trip(trip.id)
    assert len(runs) == 1
    assert runs[0].status == "budget_exceeded"
    assert runs[0].step_count == 1
    assert runs[0].token_cost == Decimal("0.000030")


async def test_step_budget_aborts_and_persists_the_attempted_step(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date="2026-05-21",
            end_date="2026-05-21",
            days=1,
        )
    )

    @asynccontextmanager
    async def test_session_scope():
        yield session

    recorder = PostgresRunRecorder(session_factory=test_session_scope)
    request = LLMRequest(
        model="claude-opus-4-7",
        max_tokens=10,
        system="Return one word.",
        messages=[LLMMessage(role="user", content="Go")],
    )

    with pytest.raises(BudgetExceeded, match="step budget"):
        async with tracked_run(
            trip_id=trip.id,
            kind="plan",
            max_steps=1,
            max_token_cost_usd=Decimal(1),
            recorder=recorder,
        ):
            await call_llm(request, client=StubMessages(), state={"step": 1})
            await call_llm(request, client=StubMessages(), state={"step": 2})

    runs = await AgentRunRepository(session).list_for_trip(trip.id)
    assert len(runs) == 1
    assert runs[0].status == "budget_exceeded"
    assert runs[0].step_count == 2


async def test_tracked_run_opens_a_trip_scoped_span_before_persisting(monkeypatch):
    trip_id = Trip(
        destination="Hokkaido",
        start_date="2026-05-21",
        end_date="2026-05-21",
        days=1,
    ).id

    class FakeSpan:
        def __init__(self) -> None:
            self.attributes: dict[str, str] = {}

        def set_attribute(self, name: str, value: str) -> None:
            self.attributes[name] = value

    class FakeTracer:
        def __init__(self) -> None:
            self.inside = False
            self.span = FakeSpan()

        @contextmanager
        def start_as_current_span(self, name: str):
            assert name == "harness.plan"
            self.inside = True
            try:
                yield self.span
            finally:
                self.inside = False

    tracer = FakeTracer()
    monkeypatch.setattr(wrapper_module.trace, "get_tracer", lambda _name: tracer)

    class FakeRecorder:
        def __init__(self) -> None:
            self.statuses: list[str] = []

        async def start(self, *, trip_id, kind):
            assert tracer.inside
            return SimpleNamespace(id=trip_id)

        async def progress(
            self,
            run_id,
            *,
            status,
            step_count,
            token_cost,
        ) -> None:
            if status is not None:
                self.statuses.append(status)

    recorder = FakeRecorder()
    async with tracked_run(trip_id=trip_id, kind="plan", recorder=recorder):
        assert tracer.inside

    assert recorder.statuses == ["ok"]
    assert tracer.span.attributes["trip_id"] == str(trip_id)
    assert tracer.span.attributes["run_id"] == str(trip_id)
