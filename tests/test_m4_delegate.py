"""M4 delegate badges and structured vote-note parsing."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from syncinerary.agents.delegate import badge as badge_module
from syncinerary.agents.delegate.badge import badge_node, generate_badges_for_traveler
from syncinerary.agents.delegate.note import parse_vote_note
from syncinerary.config import settings
from syncinerary.domain.models import (
    BadgeType,
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
    Traveler,
    Trip,
    TripState,
)
from syncinerary.store.repositories import (
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    ConstraintRepository,
    TravelerRepository,
)


class StubMessages:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
            usage=SimpleNamespace(input_tokens=20, output_tokens=10),
        )


def _candidate(trip_id, name: str) -> CandidatePlace:
    return CandidatePlace(
        trip_id=trip_id,
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=43.0,
        lng=141.0,
        category="museum",
    )


@pytest.mark.asyncio
async def test_badges_are_generated_in_one_batch_for_one_traveler():
    trip_id = uuid4()
    traveler = Traveler(
        trip_id=trip_id,
        name="Ana",
        profile={"interests": ["art museums"]},
    )
    museum = _candidate(trip_id, "Modern Art Museum")
    seafood = _candidate(trip_id, "Seafood Market")
    constraint = Constraint(
        trip_id=trip_id,
        traveler_id=traveler.id,
        type="dietary",
        value={"excludes": ["shellfish"]},
        priority=10,
        kind=ConstraintKind.HARD,
    )
    messages = StubMessages(
        {
            "decisions": [
                {
                    "candidate_id": str(museum.id),
                    "badge_type": "confirm",
                    "badge_text": "Matches your love of art museums",
                    "reasoning": "Ana listed art museums as an interest.",
                },
                {
                    "candidate_id": str(seafood.id),
                    "badge_type": "warning",
                    "badge_text": "Shellfish may be central here",
                    "reasoning": "Ana has a hard shellfish exclusion.",
                },
            ]
        }
    )

    badges = await generate_badges_for_traveler(
        traveler,
        [museum, seafood],
        [constraint],
        client=messages,
    )

    assert len(messages.calls) == 1
    assert messages.calls[0]["model"] == settings.sync_cheap_model
    assert messages.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert [badge.candidate_id for badge in badges] == [museum.id, seafood.id]
    assert [badge.badge_type for badge in badges] == [BadgeType.CONFIRM, BadgeType.WARNING]
    assert all(badge.traveler_id == traveler.id for badge in badges)


@pytest.mark.asyncio
async def test_badge_batch_omits_no_badge_and_ignores_unknown_candidate_ids():
    trip_id = uuid4()
    traveler = Traveler(trip_id=trip_id, name="Gino")
    candidate = _candidate(trip_id, "Odori Park")
    messages = StubMessages(
        {
            "decisions": [
                {
                    "candidate_id": str(candidate.id),
                    "badge_type": None,
                    "badge_text": None,
                    "reasoning": None,
                },
                {
                    "candidate_id": str(uuid4()),
                    "badge_type": "confirm",
                    "badge_text": "Invented card",
                    "reasoning": "This id was not in the prompt.",
                },
            ]
        }
    )

    badges = await generate_badges_for_traveler(
        traveler,
        [candidate],
        [],
        client=messages,
    )

    assert badges == []


@pytest.mark.asyncio
async def test_badge_node_persists_different_badges_for_each_traveler(
    session,
    monkeypatch,
):
    trip = Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        start_date="2026-09-01",
        end_date="2026-09-02",
        days=2,
    )
    # The trip fixture helpers live at the API layer, so persist this compact
    # node scenario through the repositories directly.
    from syncinerary.store.repositories import TripRepository

    trip = await TripRepository(session).add(trip)
    ana = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Ana", profile={"interests": ["art"]})
    )
    gino = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Gino", profile={"interests": ["food"]})
    )
    candidate = await CandidatePlaceRepository(session).add(
        _candidate(trip.id, "Sapporo Art Park")
    )
    await ConstraintRepository(session).add(
        Constraint(
            trip_id=trip.id,
            traveler_id=ana.id,
            type="pace",
            value={"avoid": "long walks"},
            priority=8,
            kind=ConstraintKind.SOFT,
        )
    )

    async def fake_generate(traveler, candidates, constraints, **_kwargs):
        badge_type = BadgeType.CONFIRM if traveler.id == ana.id else BadgeType.WARNING
        return [
            badge_module.CandidateBadge(
                candidate_id=candidates[0].id,
                traveler_id=traveler.id,
                badge_type=badge_type,
                badge_text=f"For {traveler.name}",
                reasoning="Traveler-specific test reasoning.",
            )
        ]

    # Use the same async context manager shape as production without opening a
    # second transaction outside the pytest rollback.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def scoped_session():
        yield session

    monkeypatch.setattr(badge_module, "session_scope", scoped_session)
    monkeypatch.setattr(badge_module, "generate_badges_for_traveler", fake_generate)

    state = TripState(trip=trip, travelers=[ana, gino], candidates=[candidate])
    before = state.model_copy(deep=True)
    result = await badge_node(state)

    assert state == before
    assert len(result["badges"]) == 2
    ana_badges = await CandidateBadgeRepository(session).list_for_traveler_on_trip(ana.id)
    gino_badges = await CandidateBadgeRepository(session).list_for_traveler_on_trip(gino.id)
    assert ana_badges[0].badge_type is BadgeType.CONFIRM
    assert gino_badges[0].badge_type is BadgeType.WARNING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("note", "payload", "expected"),
    [
        (
            "I can grab a convenience store meal",
            {
                "kind": "self_handles_meal",
                "self_handles_meal": True,
                "alternative": "convenience_store",
                "requires_short_visit": None,
                "max_minutes": None,
                "conditional_on": None,
                "condition_detail": None,
                "raw": None,
            },
            {"self_handles_meal": True, "alternative": "convenience_store"},
        ),
        (
            "Only if the weather is good",
            {
                "kind": "conditional",
                "self_handles_meal": None,
                "alternative": None,
                "requires_short_visit": None,
                "max_minutes": None,
                "conditional_on": "weather_good",
                "condition_detail": None,
                "raw": None,
            },
            {"conditional_on": "weather_good"},
        ),
        (
            "I only have twenty minutes here",
            {
                "kind": "short_visit",
                "self_handles_meal": None,
                "alternative": None,
                "requires_short_visit": True,
                "max_minutes": 20,
                "conditional_on": None,
                "condition_detail": None,
                "raw": None,
            },
            {"requires_short_visit": True, "max_minutes": 20},
        ),
        (
            "This is nostalgic for me",
            {
                "kind": "raw",
                "self_handles_meal": None,
                "alternative": None,
                "requires_short_visit": None,
                "max_minutes": None,
                "conditional_on": None,
                "condition_detail": None,
                "raw": "This is nostalgic for me",
            },
            {"raw": "This is nostalgic for me"},
        ),
    ],
)
async def test_vote_note_is_parsed_into_the_supported_shape(note, payload, expected):
    messages = StubMessages(payload)

    parsed = await parse_vote_note(note, client=messages)

    assert parsed == expected
    assert messages.calls[0]["model"] == settings.sync_cheap_model
    assert messages.calls[0]["output_config"]["format"]["type"] == "json_schema"
