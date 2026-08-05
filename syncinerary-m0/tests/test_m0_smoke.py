"""M0 smoke tests.

These verify the scaffold without external services. Tests that need Postgres /
Phoenix live behind explicit fixtures introduced in M1.
"""
from datetime import date

import pytest

from syncinerary.agents.graph import run_noop
from syncinerary.domain.models import Trip, TripState


def _hokkaido_state() -> TripState:
    trip = Trip(
        destination="Hokkaido",
        start_date=date(2026, 5, 21),
        end_date=date(2026, 5, 26),
        days=6,
    )
    return TripState(trip=trip)


@pytest.mark.asyncio
async def test_noop_graph_runs():
    state = _hokkaido_state()
    result = await run_noop(state)
    assert result.trip.destination == "Hokkaido"
    assert result.trip.days == 6


@pytest.mark.asyncio
async def test_noop_graph_preserves_empty_collections():
    """M0 contract: the no-op must NOT add candidates / votes / etc."""
    state = _hokkaido_state()
    result = await run_noop(state)
    assert result.candidates == []
    assert result.votes == []
    assert result.badges == []
    assert result.shortlist is None
