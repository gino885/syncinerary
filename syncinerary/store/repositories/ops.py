"""Replan, agent run and eval repositories.

These back the two features that are built last but matter most in review:
F4's replan log (§12.2) and F2's eval rail (§12.3). The tables exist from M1
so the store layer covers all of §7 rather than growing a hole, but only
agent_run is written before M2.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from sqlalchemy import select

from syncinerary.domain.models import (
    AgentRun,
    EvalResult,
    EvalScenario,
    ReplanEvent,
    ReplanStatus,
)
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class ReplanEventRepository(BaseRepository[tables.ReplanEvent, ReplanEvent]):
    table = tables.ReplanEvent
    model = ReplanEvent
    jsonb_fields = frozenset({"trigger_payload", "affected_node_ids", "trace_json"})

    async def list_for_trip(self, trip_id: UUID) -> list[ReplanEvent]:
        return await self.list_where(tables.ReplanEvent.trip_id == trip_id)

    async def list_pending(self, trip_id: UUID) -> list[ReplanEvent]:
        """Proposals awaiting the group. §12.2: never auto-commit."""
        return await self.list_where(
            tables.ReplanEvent.trip_id == trip_id,
            tables.ReplanEvent.status == ReplanStatus.PENDING,
        )

    async def get_for_update(self, event_id: UUID) -> ReplanEvent | None:
        """Lock one approval decision so only its first answer can win."""
        row = await self.session.scalar(
            select(tables.ReplanEvent)
            .where(tables.ReplanEvent.id == event_id)
            .with_for_update()
        )
        return self.to_model(row) if row is not None else None

    async def decide(
        self, event_id: UUID, status: ReplanStatus, decided_by: UUID
    ) -> ReplanEvent | None:
        """Record the group's answer.

        Both outcomes are logged, not just approval (§12.2 acceptance
        criteria): a rejection is evidence the gate held.
        """
        row = await self.session.get(self.table, event_id)
        if row is None:
            return None
        row.status = status
        row.decided_by = decided_by
        row.decided_at = datetime.now(UTC)
        await self.session.flush()
        return self.to_model(row)


class AgentRunRepository(BaseRepository[tables.AgentRun, AgentRun]):
    """Per-run accounting. The harness (M2) reads and writes this."""

    table = tables.AgentRun
    model = AgentRun

    async def list_for_trip(self, trip_id: UUID) -> list[AgentRun]:
        return await self.list_where(tables.AgentRun.trip_id == trip_id)

    async def record_progress(
        self,
        run_id: UUID,
        *,
        status: str | None = None,
        step_count: int | None = None,
        token_cost: Decimal | None = None,
    ) -> AgentRun | None:
        """Update the live counters a run accumulates.

        The budget circuit breaker in §12.1 needs a partial trace to survive
        when it aborts a run, so these counters are written as the run
        proceeds rather than once at the end.
        """
        row = await self.session.get(self.table, run_id)
        if row is None:
            return None
        if status is not None:
            row.status = status
        if step_count is not None:
            row.step_count = step_count
        if token_cost is not None:
            row.token_cost = token_cost
        await self.session.flush()
        return self.to_model(row)


class EvalScenarioRepository(BaseRepository[tables.EvalScenario, EvalScenario]):
    table = tables.EvalScenario
    model = EvalScenario
    column_aliases: ClassVar[dict[str, str]] = {
        "fixture": "fixture_json",
        "disruption": "disruption_json",
        "expected": "expected_json",
    }
    jsonb_fields = frozenset({"fixture", "disruption", "expected"})

    async def get_by_name(self, name: str) -> EvalScenario | None:
        found = await self.list_where(tables.EvalScenario.name == name)
        return found[0] if found else None

    async def list_all(self) -> list[EvalScenario]:
        return await self.list_where(order_by=tables.EvalScenario.name)


class EvalResultRepository(BaseRepository[tables.EvalResult, EvalResult]):
    table = tables.EvalResult
    model = EvalResult
    column_aliases: ClassVar[dict[str, str]] = {"scores": "scores_json"}
    jsonb_fields = frozenset({"scores"})

    async def list_for_commit(self, commit_sha: str) -> list[EvalResult]:
        return await self.list_where(tables.EvalResult.commit_sha == commit_sha)

    async def previous_commit_sha(self, current_sha: str) -> str | None:
        """The commit before this one to have a recorded run.

        §12.3 wants the runner to print a diff against the last run. Ordering
        is by run_at rather than by git history: the eval rail records when it
        ran, and it has no view of the commit graph.
        """
        return await self.session.scalar(
            select(tables.EvalResult.commit_sha)
            .where(tables.EvalResult.commit_sha != current_sha)
            .order_by(tables.EvalResult.run_at.desc())
            .limit(1)
        )
