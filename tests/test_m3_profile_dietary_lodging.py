"""The three gather behaviors restored before M4."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from syncinerary.agents.gather import personal as personal_module
from syncinerary.agents.gather.dietary import (
    dietary_notice,
    filter_dietary_conflicts,
)
from syncinerary.agents.gather.personal import discover_profile_candidates
from syncinerary.agents.solver.lodging import rank_lodging_options
from syncinerary.config import settings
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
    Source,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput


class StubMessages:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


def _trip() -> Trip:
    return Trip(
        destination="Sapporo",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 10, 1),
        days=5,
    )


def _candidate(
    trip: Trip,
    name: str,
    *,
    kind: CandidateType = CandidateType.ATTRACTION,
    lat: float = 43.061,
    lng: float = 141.354,
    price_tier: int = 2,
    dietary_tags: list[str] | None = None,
) -> CandidatePlace:
    return CandidatePlace(
        trip_id=trip.id,
        type=kind,
        name_canonical=name,
        lat=lat,
        lng=lng,
        price_tier=price_tier,
        dietary_tags=dietary_tags or [],
        sources=[Source(type="discovery", subtype="google_places")],
    )


async def test_profile_suggestions_are_batched_capped_and_verified(monkeypatch):
    trip = _trip()
    gino = Traveler(
        trip_id=trip.id,
        name="Gino",
        profile={"interests": ["architecture", "coffee"]},
    )
    mei = Traveler(
        trip_id=trip.id,
        name="Mei",
        profile={"interests": ["pottery"]},
    )
    ignored_id = uuid4()
    messages = StubMessages(
        {
            "travelers": [
                {
                    "traveler_id": str(gino.id),
                    "place_names": ["Clock Tower", "Coffee Lab", "Over cap"],
                },
                {
                    "traveler_id": str(mei.id),
                    "place_names": ["Pottery Studio"],
                },
                {
                    "traveler_id": str(gino.id),
                    "place_names": ["Duplicate traveler bypass"],
                },
                {
                    "traveler_id": str(ignored_id),
                    "place_names": ["Invented traveler"],
                },
            ]
        }
    )
    geocoded: list[str] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        geocoded.append(arguments.query)
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"place-{len(geocoded)}",
                    display_name=arguments.query,
                    formatted_address="Sapporo, Hokkaido, Japan",
                    lat=43.061 + len(geocoded) * 0.001,
                    lng=141.354,
                    primary_type="tourist_attraction",
                )
            ]
        )

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)

    candidates = await discover_profile_candidates(
        trip,
        [gino, mei, Traveler(trip_id=trip.id, name="No profile")],
        client=messages,
    )

    assert len(messages.calls) == 1
    assert messages.calls[0]["model"] == settings.sync_cheap_model
    schema = messages.calls[0]["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["TravelerProfileSuggestions"]["additionalProperties"] is False
    assert geocoded == ["Clock Tower", "Coffee Lab", "Pottery Studio"]
    assert len(candidates) == 3
    assert [candidate.sources[0].by for candidate in candidates] == [
        gino.id,
        gino.id,
        mei.id,
    ]
    assert all(candidate.sources[0].subtype == "profile_driven" for candidate in candidates)
    assert all(candidate.enrichment["google_place_id"] for candidate in candidates)


def test_known_dietary_conflicts_are_removed_but_unknown_food_is_kept():
    trip = _trip()
    vegetarian = Constraint(
        trip_id=trip.id,
        type="dietary",
        value={"excludes": ["seafood", "meat"]},
        priority=10,
        kind=ConstraintKind.HARD,
    )
    candidates = [
        _candidate(
            trip,
            "Seafood Grill",
            kind=CandidateType.FOOD,
            dietary_tags=["seafood"],
        ),
        _candidate(trip, "Neighborhood Cafe", kind=CandidateType.FOOD),
        _candidate(trip, "Art Museum"),
    ]

    kept = filter_dietary_conflicts(candidates, [vegetarian])

    assert [candidate.name_canonical for candidate in kept] == [
        "Neighborhood Cafe",
        "Art Museum",
    ]
    assert dietary_notice(candidates[1], [vegetarian]) == (
        "Dietary details are unverified. Confirm with the restaurant."
    )
    vegan = _candidate(
        trip,
        "Vegan Cafe",
        kind=CandidateType.FOOD,
        dietary_tags=["vegan", "vegetarian"],
    )
    assert dietary_notice(vegan, [vegetarian]) == (
        "Dietary details are unverified. Confirm with the restaurant."
    )
    assert dietary_notice(candidates[2], [vegetarian]) is None


def test_soft_dietary_preferences_do_not_remove_food():
    trip = _trip()
    preference = Constraint(
        trip_id=trip.id,
        type="dietary",
        value={"excludes": ["seafood"]},
        kind=ConstraintKind.SOFT,
    )
    seafood = _candidate(
        trip,
        "Seafood Grill",
        kind=CandidateType.FOOD,
        dietary_tags=["seafood"],
    )

    assert filter_dietary_conflicts([seafood], [preference]) == [seafood]


def test_lodging_ranking_prefers_the_trip_area_then_lower_price():
    trip = _trip()
    activities = [
        _candidate(trip, "Museum", lat=43.061, lng=141.354),
        _candidate(trip, "Park", lat=43.062, lng=141.355),
    ]
    lodging = [
        _candidate(
            trip,
            "Far Cheap Hotel",
            kind=CandidateType.LODGING,
            lat=43.20,
            lng=141.50,
            price_tier=1,
        ),
        _candidate(
            trip,
            "Central Hotel",
            kind=CandidateType.LODGING,
            lat=43.0615,
            lng=141.3545,
            price_tier=2,
        ),
        _candidate(
            trip,
            "Central Budget Hotel",
            kind=CandidateType.LODGING,
            lat=43.0616,
            lng=141.3546,
            price_tier=1,
        ),
    ]

    ranked = rank_lodging_options(lodging, activities)

    assert [candidate.name_canonical for candidate in ranked] == [
        "Central Budget Hotel",
        "Central Hotel",
        "Far Cheap Hotel",
    ]


async def test_lodging_selection_is_idempotent_and_replaces_the_previous_pick(session):
    trip = await TripRepository(session).add(_trip())
    first = await CandidatePlaceRepository(session).add(
        _candidate(trip, "First Hotel", kind=CandidateType.LODGING)
    )
    second = await CandidatePlaceRepository(session).add(
        _candidate(trip, "Second Hotel", kind=CandidateType.LODGING)
    )
    repo = ConstraintRepository(session)

    await repo.set_group_constraint(
        trip.id,
        constraint_type="selected_lodging",
        value={"candidate_id": str(first.id)},
        priority=100,
        kind=ConstraintKind.HARD,
    )
    await repo.set_group_constraint(
        trip.id,
        constraint_type="selected_lodging",
        value={"candidate_id": str(second.id)},
        priority=100,
        kind=ConstraintKind.HARD,
    )

    stored = [
        item for item in await repo.list_for_trip(trip.id)
        if item.type == "selected_lodging"
    ]
    assert len(stored) == 1
    assert stored[0].value == {"candidate_id": str(second.id)}


async def test_trip_setup_persists_interests_and_hard_dietary_exclusions(client, session):
    response = await client.post(
        "/trips",
        json={
            "destination": "Sapporo",
            "start_date": "2026-09-27",
            "end_date": "2026-10-01",
            "creator_name": "Gino",
            "creator_interests": [" coffee ", "architecture", "coffee"],
            "creator_dietary_excludes": [" Seafood ", "meat", "seafood"],
        },
    )

    assert response.status_code == 201, response.text
    trip_id = response.json()["trip"]["id"]
    traveler_id = response.json()["traveler_id"]
    traveler = await TravelerRepository(session).get(traveler_id)
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    assert traveler.profile == {"interests": ["coffee", "architecture"]}
    assert len(constraints) == 1
    assert constraints[0].traveler_id == traveler.id
    assert constraints[0].kind is ConstraintKind.HARD
    assert constraints[0].value == {"excludes": ["seafood", "meat"]}


async def test_deck_removes_known_conflicts_and_warns_on_unknown_food(client, session):
    created = await client.post(
        "/trips",
        json={
            "destination": "Sapporo",
            "start_date": "2026-09-27",
            "end_date": "2026-10-01",
            "creator_name": "Gino",
            "creator_dietary_excludes": ["seafood"],
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]
    trip = await TripRepository(session).get(trip_id)
    await CandidatePlaceRepository(session).add_many(
        [
            _candidate(
                trip,
                "Seafood Grill",
                kind=CandidateType.FOOD,
                dietary_tags=["seafood"],
            ),
            _candidate(trip, "Unknown Cafe", kind=CandidateType.FOOD),
        ]
    )

    response = await client.get(
        f"/trips/{trip_id}/candidates",
        params={"traveler_id": traveler_id},
    )

    assert response.status_code == 200
    assert [card["name_canonical"] for card in response.json()] == ["Unknown Cafe"]
    assert response.json()[0]["dietary_notice"] == (
        "Dietary details are unverified. Confirm with the restaurant."
    )
    progress = await client.get(
        f"/trips/{trip_id}/votes/progress",
        params={"traveler_id": traveler_id},
    )
    assert progress.json() == {
        "total_candidates": 1,
        "voted": 0,
        "remaining": 1,
    }


async def test_lodging_options_can_be_compared_and_selected(client, session):
    created = await client.post(
        "/trips",
        json={
            "destination": "Sapporo",
            "start_date": "2026-09-27",
            "end_date": "2026-10-01",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]
    trip = await TripRepository(session).get(trip_id)
    await CandidatePlaceRepository(session).add_many(
        [
            _candidate(trip, "Museum", lat=43.061, lng=141.354),
            _candidate(
                trip,
                "Central Hotel",
                kind=CandidateType.LODGING,
                lat=43.0615,
                lng=141.3545,
                price_tier=2,
            ),
            _candidate(
                trip,
                "Budget Hotel",
                kind=CandidateType.LODGING,
                lat=43.0616,
                lng=141.3546,
                price_tier=1,
            ),
        ]
    )

    options = await client.get(f"/trips/{trip_id}/lodging-options")

    assert options.status_code == 200, options.text
    assert [option["name"] for option in options.json()] == [
        "Budget Hotel",
        "Central Hotel",
    ]
    assert all(option["availability_note"] for option in options.json())

    chosen_id = options.json()[0]["candidate_id"]
    selected = await client.post(
        f"/trips/{trip_id}/lodging-selection",
        json={"traveler_id": traveler_id, "candidate_id": chosen_id},
    )

    assert selected.status_code == 200, selected.text
    assert selected.json()["candidate_id"] == chosen_id
    constraints = await ConstraintRepository(session).list_for_trip(trip.id)
    lodging_choice = next(item for item in constraints if item.type == "selected_lodging")
    assert lodging_choice.value == {"candidate_id": chosen_id}
