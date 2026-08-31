"""M1-9: Postgres-checkpointed graph and end-to-end planning API."""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Self

import pytest_asyncio

from syncinerary.agents import aggregate as aggregate_module
from syncinerary.agents import explain as explain_module
from syncinerary.agents import shortlist as shortlist_module
from syncinerary.agents.gather import live as gather_module
from syncinerary.agents.graph import dispose_graph, graph_config, init_graph
from syncinerary.agents.solver import stage2_route as solver_module
from syncinerary.domain.models import CandidatePlace, CandidateType, TripState
from syncinerary.harness import wrapper as harness_wrapper_module
from syncinerary.store.repositories import AgentRunRepository
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitMatrix,
    TransitMode,
)


class StubTransitClient:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        legs = [
            TransitDuration(
                origin=origin,
                destination=destination,
                mode=TransitMode.WALKING,
                departure_window=request.departure_window,
                duration_seconds=10 * 60,
                duration_minutes=10,
            )
            for origin in request.locations
            for destination in request.locations
            if origin != destination
        ]
        return TransitMatrix(legs=legs)


class StubMessages:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="A tested Hokkaido itinerary.")],
            usage=SimpleNamespace(input_tokens=12, output_tokens=6),
        )


def _use_test_session(monkeypatch, session) -> None:
    @asynccontextmanager
    async def test_scope():
        yield session

    for module in (
        gather_module,
        aggregate_module,
        shortlist_module,
        solver_module,
        explain_module,
        harness_wrapper_module,
    ):
        monkeypatch.setattr(module, "session_scope", test_scope)

    async def discover(trip, _travelers=None):
        swipeable = [
            CandidatePlace(
                trip_id=trip.id,
                type=(CandidateType.FOOD if index % 4 == 0 else CandidateType.ATTRACTION),
                name_canonical=f"Live candidate {index:02d}",
                lat=43.05 + (index % 7) * 0.002,
                lng=141.34 + (index // 7) * 0.002,
                hours_by_weekday={
                    day: [[8, 20]]
                    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                },
            )
            for index in range(trip.days * 7)
        ]
        lodging = [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.LODGING,
                name_canonical=f"Live hotel {index}",
                lat=43.06 + index * 0.001,
                lng=141.35,
                hours_by_weekday={
                    day: [[0, 24]]
                    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                },
            )
            for index in range(3)
        ]
        return swipeable + lodging

    monkeypatch.setattr(gather_module, "discover_candidates", discover)


@pytest_asyncio.fixture
async def graph_runtime():
    graph = await init_graph()
    try:
        yield graph
    finally:
        await dispose_graph()


async def test_http_pipeline_interrupts_for_swipes_then_returns_itinerary(
    client,
    session,
    monkeypatch,
    graph_runtime,
):
    _use_test_session(monkeypatch, session)
    monkeypatch.setattr(solver_module, "_make_transit_client", StubTransitClient)
    monkeypatch.setattr(explain_module, "_make_client", StubMessages)

    created_response = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-22",
            "creator_name": "Gino",
            "creator_home_city": "Chicago",
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    trip_id = created["trip"]["id"]
    traveler_id = created["traveler_id"]
    config = graph_config(trip_id)

    try:
        gathered = await client.post(f"/trips/{trip_id}/gather")
        assert gathered.status_code == 200
        assert gathered.json() == {"deck_size": 14}

        interrupted = await graph_runtime.aget_state(config)
        assert interrupted.next == ("aggregate",)
        interrupted_state = TripState.model_validate(interrupted.values)
        assert len(interrupted_state.candidates) == 17

        # Gather is idempotent and must not accidentally resume planning.
        gathered_again = await client.post(f"/trips/{trip_id}/gather")
        assert gathered_again.json() == {"deck_size": 14}
        assert (await graph_runtime.aget_state(config)).next == ("aggregate",)

        deck_response = await client.get(f"/trips/{trip_id}/candidates")
        deck = deck_response.json()
        for candidate in deck[:3]:
            vote = await client.post(
                f"/trips/{trip_id}/votes",
                json={
                    "traveler_id": traveler_id,
                    "candidate_id": candidate["id"],
                    "signal": "like",
                },
            )
            assert vote.status_code == 201

        planned = await client.post(
            f"/trips/{trip_id}/plan",
            json={"day_start": "09:00:00", "day_end": "21:00:00"},
        )
        assert planned.status_code == 200, planned.text
        plan_body = planned.json()
        assert plan_body["version_no"] == 1
        assert plan_body["placed_stops"] > 0
        assert plan_body["narrative"] == "A tested Hokkaido itinerary."

        completed = await graph_runtime.aget_state(config)
        assert completed.next == ()
        completed_state = TripState.model_validate(completed.values)
        assert completed_state.day_start.hour == 9
        assert completed_state.day_end.hour == 21

        itinerary_response = await client.get(f"/trips/{trip_id}/itinerary")
        assert itinerary_response.status_code == 200
        itinerary = itinerary_response.json()
        assert itinerary["version_id"] == plan_body["version_id"]
        assert itinerary["status"] == "active"
        assert len(itinerary["days"]) == 2
        assert itinerary["narrative"] == "A tested Hokkaido itinerary."
        assert all(
            stop["start_time"] >= "09:00:00"
            for day in itinerary["days"]
            for stop in day["stops"]
        )

        runs = await AgentRunRepository(session).list_for_trip(trip_id)
        assert len(runs) == 1
        assert runs[0].kind == "plan"
        assert runs[0].status == "ok"
        # Two day-level transit tool calls plus the explainer LLM call. No
        # make-up re-solve: both days fill from the shortlist on the first pass.
        assert runs[0].step_count == 3

        # A completed thread returns the same version instead of appending one.
        planned_again = await client.post(
            f"/trips/{trip_id}/plan",
            json={"day_start": "09:00:00", "day_end": "21:00:00"},
        )
        assert planned_again.json()["version_id"] == plan_body["version_id"]
    finally:
        await graph_runtime.checkpointer.adelete_thread(trip_id)


async def test_plan_before_gather_is_a_conflict(client, graph_runtime):
    created = (
        await client.post(
            "/trips",
            json={
                "cities": ["Hokkaido"],
                "country": "Japan",
                "start_date": "2026-05-21",
                "end_date": "2026-05-21",
                "creator_name": "Gino",
            },
        )
    ).json()
    trip_id = created["trip"]["id"]

    response = await client.post(f"/trips/{trip_id}/plan", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Gather must run before planning"


async def test_itinerary_before_plan_is_not_found(client, graph_runtime):
    created = (
        await client.post(
            "/trips",
            json={
                "cities": ["Hokkaido"],
                "country": "Japan",
                "start_date": "2026-05-21",
                "end_date": "2026-05-21",
                "creator_name": "Gino",
            },
        )
    ).json()
    trip_id = created["trip"]["id"]

    response = await client.get(f"/trips/{trip_id}/itinerary")

    assert response.status_code == 404
    assert response.json()["detail"] == "No itinerary has been planned"
