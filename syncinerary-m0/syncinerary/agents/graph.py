"""LangGraph wiring.

M0 ships a single node so we can verify the trace pipeline is alive. Node
execution is auto-instrumented via OpenInference (see obs/tracing.py), so the
node itself does not need to open a manual span for its own execution. The
manual span here demonstrates the pattern for adding *domain* attributes on
top of the auto-instrumented span (trip_id, destination, etc).

M1 replaces this with the real 6-stage pipeline (CLAUDE.md §3, §13 Phase A).

Architectural rules (CLAUDE.md §2, §14):
- LLM nodes go through harness/wrapper.py (lands in M2).
- aggregate.py, shortlist.py, solver/* must NEVER import the LLM SDK.
- Nodes RETURN a partial dict for LangGraph to merge into state. Nodes must
  NOT mutate the input state in place: in-place mutation breaks LangGraph's
  checkpointer serialization for the pydantic-BaseModel state pattern.

Why BaseModel not TypedDict for state:
- We share one pydantic schema across LangGraph state, FastAPI validation,
  and Postgres persistence. TypedDict would fragment that.
- Cost is that nodes MUST use the return-dict merge pattern (below), not
  attribute assignment on the state object.
"""
from typing import Any

from langgraph.graph import END, START, StateGraph

from syncinerary.domain.models import TripState
from syncinerary.obs.tracing import get_tracer


def _noop_node(state: TripState) -> dict[str, Any]:
    """M0 placeholder. Adds domain attributes to the auto-instrumented span
    so Phoenix shows trip context alongside the LangChain-emitted span.

    Returns an empty dict: no state fields change. M1+ nodes return dicts
    like `{"candidates": [...]}` for LangGraph to merge into state; they do
    NOT do `state.candidates.append(...)`.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span("noop_node.domain") as span:
        span.set_attribute("trip_id", str(state.trip.id))
        span.set_attribute("destination", state.trip.destination)
        span.set_attribute("days", state.trip.days)
        span.set_attribute("milestone", "M0")
    return {}


def build_graph():
    g = StateGraph(TripState)
    g.add_node("noop", _noop_node)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    return g.compile()


async def run_noop(state: TripState) -> TripState:
    """Run the M0 no-op graph and return the (unchanged) state."""
    graph = build_graph()
    result = await graph.ainvoke(state)
    # LangGraph returns a dict-shaped state; re-validate as the typed model.
    return TripState.model_validate(result)
