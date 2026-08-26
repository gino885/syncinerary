"""M1 gather: one source, read from a hand-written fixture.

CLAUDE.md §13 M1 asks for a single source in the thin vertical slice. M3
replaces this module with real backbone mining, buzz scoring and personal
sources plus cross-source dedup (§8); the fixture exists so the rest of the
pipeline has a candidate pool to work on before any of that is built.

No LLM here. Real gather is LLM plus tools (§2), but reading a JSON file
needs neither, and pretending otherwise would put a model call on the
critical path of every test for no benefit.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from syncinerary.config.gather import POOL_PER_DAY
from syncinerary.domain.models import CandidatePlace, CandidateType, TripState
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import CandidatePlaceRepository

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tools" / "fetch"


class FixtureNotFound(LookupError):
    """No fixture ships for the requested destination."""


@lru_cache(maxsize=8)
def _read_fixture(destination: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{destination.strip().lower().replace(' ', '_')}_fixture.json"
    if not path.exists():
        available = sorted(p.stem.removesuffix("_fixture") for p in FIXTURE_DIR.glob("*.json"))
        raise FixtureNotFound(
            f"No M1 fixture for destination {destination!r}. Available: {available}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _pool_size(days: int) -> int:
    """§8: the pool defaults to days * 7, configurable in config/gather.py."""
    return days * POOL_PER_DAY


def load_candidates(destination: str, trip_id: UUID, days: int) -> list[CandidatePlace]:
    """Build the candidate pool for a trip from the destination's fixture.

    Two rules from §8 are applied here rather than left to the caller:

    - The pool is capped at days * POOL_PER_DAY. Handing the swipe deck every
      card in the fixture regardless of trip length would ignore a §16
      default that M3 then has to retrofit.
    - Lodging does not count against that cap. §8.6 keeps lodging out of the
      swipe deck entirely, so it is not competing for pool slots; all lodging
      in the fixture is loaded and the solver picks from it later.

    Ranking inside the cap is by source score, descending. Ties break on name
    so the pool is identical across runs, which matters for F2 replay.
    """
    data = _read_fixture(destination)
    raw = data["candidates"]

    parsed = [CandidatePlace(trip_id=trip_id, **entry) for entry in raw]
    lodging = [c for c in parsed if c.type is CandidateType.LODGING]
    swipeable = [c for c in parsed if c.type is not CandidateType.LODGING]

    def rank(candidate: CandidatePlace) -> tuple[float, str]:
        best = max((s.score or 0.0) for s in candidate.sources) if candidate.sources else 0.0
        return (-best, candidate.name_canonical)

    swipeable.sort(key=rank)
    return swipeable[: _pool_size(days)] + lodging


async def gather_node(state: TripState) -> dict[str, Any]:
    """LangGraph node: build the pool and persist it.

    Returns a partial dict for LangGraph to merge (CLAUDE.md §14). It does not
    mutate `state`: in-place mutation breaks the checkpointer serialisation
    this graph depends on for the swipe interrupt.

    Re-entrant on purpose. The graph is compiled with
    interrupt_after=["gather"], so a resumed thread can execute this node
    again; if the trip already has candidates it reuses them rather than
    writing a second pool.
    """
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("gather.fixture") as span:
        span.set_attribute("trip_id", str(trip.id))
        span.set_attribute("destination", trip.destination)
        span.set_attribute("gather.source", "fixture")

        async with session_scope() as session:
            repo = CandidatePlaceRepository(session)
            existing = await repo.list_for_trip(trip.id)
            if existing:
                span.set_attribute("gather.reused_existing", True)
                span.set_attribute("gather.candidate_count", len(existing))
                return {"candidates": existing}

            candidates = load_candidates(trip.destination, trip.id, trip.days)
            saved = await repo.add_many(candidates)

        span.set_attribute("gather.reused_existing", False)
        span.set_attribute("gather.candidate_count", len(saved))
        return {"candidates": saved}
