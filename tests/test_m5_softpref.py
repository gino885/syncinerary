"""M5 bounded soft-preference weights."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from syncinerary.agents.softpref import generate_solver_weights, softpref_node
from syncinerary.domain.models import (
    Constraint,
    ConstraintKind,
    SolverObjectiveWeights,
    Trip,
    TripState,
    Vote,
    VoteSignal,
)


class StubMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(
                    type="text",
                    text=(
                        '{"dispersion":45,"diversity":30,"weather":80,'
                        '"vote":60,"conditional":70}'
                    ),
                )
            ],
        )


def _trip() -> Trip:
    return Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        days=2,
    )


def _state_with_preferences() -> TripState:
    trip = _trip()
    return TripState(
        trip=trip,
        constraints=[
            Constraint(
                trip_id=trip.id,
                type="pace",
                value={"level": "relaxed"},
                kind=ConstraintKind.SOFT,
            )
        ],
        votes=[
            Vote(
                candidate_id=uuid4(),
                traveler_id=uuid4(),
                signal=VoteSignal.LIKE_WITH_NOTE,
                note_parsed={"conditional_on": "weather_good"},
            )
        ],
    )


async def test_preferences_return_bounded_typed_weights():
    stub = StubMessages()

    weights = await generate_solver_weights(_state_with_preferences(), client=stub)

    assert weights == SolverObjectiveWeights(
        dispersion=45,
        diversity=30,
        weather=80,
        vote=60,
        conditional=70,
    )
    sent = stub.calls[0]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in sent
    assert "relaxed" in sent["messages"][0]["content"]
    assert "weather_good" in sent["messages"][0]["content"]
    assert "untrusted data" in sent["system"]


async def test_node_returns_defaults_without_an_unneeded_model_call():
    state = TripState(trip=_trip())
    stub = StubMessages()
    before = state.model_dump(mode="json")

    result = await softpref_node(state, client=stub)

    assert result == {"solver_weights": SolverObjectiveWeights()}
    assert stub.calls == []
    assert state.model_dump(mode="json") == before
