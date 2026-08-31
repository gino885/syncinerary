"""M1 LangGraph pipeline and Postgres checkpointer lifecycle.

The graph pauses after gather for human swiping, then resumes the same
``thread_id == trip_id`` through deterministic aggregate, shortlist and
solver nodes before the final descriptive LLM call.
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from syncinerary.agents.aggregate import aggregate_node
from syncinerary.agents.delegate.badge import badge_node
from syncinerary.agents.explain import explain_node
from syncinerary.agents.gather.live import gather_node
from syncinerary.agents.shortlist import shortlist_node
from syncinerary.agents.solver.stage2_route import solver_node
from syncinerary.config import settings
from syncinerary.domain.models import (
    AgentRun,
    BadgeType,
    CandidateBadge,
    CandidatePlace,
    CandidateScore,
    CandidateType,
    Constraint,
    ConstraintKind,
    EvalResult,
    EvalScenario,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    ShortlistState,
    Source,
    Traveler,
    Trip,
    TripState,
    TripStatus,
    Vote,
    VoteSignal,
    WishlistNotPlaced,
)
from syncinerary.obs.tracing import get_tracer

_checkpoint_pool: AsyncConnectionPool | None = None
_graph: Any | None = None

# Checkpoints deserialize constructors, so allow only our typed state models.
# The asyncpg UUID entry reads checkpoints written before repository values
# were normalized to stdlib UUID; new checkpoints no longer write that type.
CHECKPOINT_TYPES = (
    ("asyncpg.pgproto.pgproto", "UUID"),
    AgentRun,
    BadgeType,
    CandidateBadge,
    CandidatePlace,
    CandidateScore,
    CandidateType,
    Constraint,
    ConstraintKind,
    EvalResult,
    EvalScenario,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    ShortlistState,
    Source,
    Traveler,
    Trip,
    TripState,
    TripStatus,
    Vote,
    VoteSignal,
    WishlistNotPlaced,
)


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(TripState)
    graph.add_node("gather", gather_node)
    graph.add_node("badges", badge_node)
    graph.add_node("aggregate", aggregate_node)
    graph.add_node("shortlist", shortlist_node)
    graph.add_node("solver", solver_node)
    graph.add_node("explain", explain_node)

    graph.add_edge(START, "gather")
    graph.add_edge("gather", "badges")
    graph.add_edge("badges", "aggregate")
    graph.add_edge("aggregate", "shortlist")
    graph.add_edge("shortlist", "solver")
    graph.add_edge("solver", "explain")
    graph.add_edge("explain", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=["badges", "shortlist"],
    )


def graph_config(trip_id: object) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": str(trip_id)}}


def _psycopg_url() -> str:
    """The store uses asyncpg syntax; psycopg rejects the driver suffix."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def init_graph():
    """Open the checkpointer pool, own its tables, and compile once."""
    global _checkpoint_pool, _graph
    if _graph is not None:
        return _graph

    pool = AsyncConnectionPool(
        _psycopg_url(),
        min_size=1,
        max_size=4,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    )
    await pool.open(wait=True)
    saver = AsyncPostgresSaver(
        pool,
        serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES),
    )
    try:
        await saver.setup()
    except Exception:
        await pool.close()
        raise

    _checkpoint_pool = pool
    _graph = build_graph(saver)
    return _graph


def get_graph():
    if _graph is None:
        raise RuntimeError("LangGraph runtime is not initialized")
    return _graph


async def dispose_graph() -> None:
    global _checkpoint_pool, _graph
    _graph = None
    if _checkpoint_pool is not None:
        await _checkpoint_pool.close()
        _checkpoint_pool = None


# Kept as an M0 regression helper. build_graph() itself is the real M1 graph.
def _noop_node(state: TripState) -> dict[str, Any]:
    tracer = get_tracer()
    with tracer.start_as_current_span("noop_node.domain") as span:
        span.set_attribute("trip_id", str(state.trip.id))
        span.set_attribute("destination", state.trip.destination)
        span.set_attribute("days", state.trip.days)
        span.set_attribute("milestone", "M0")
    return {}


async def run_noop(state: TripState) -> TripState:
    graph = StateGraph(TripState)
    graph.add_node("noop", _noop_node)
    graph.add_edge(START, "noop")
    graph.add_edge("noop", END)
    result = await graph.compile().ainvoke(state)
    return TripState.model_validate(result)


__all__ = [
    "build_graph",
    "dispose_graph",
    "get_graph",
    "graph_config",
    "init_graph",
    "run_noop",
]
