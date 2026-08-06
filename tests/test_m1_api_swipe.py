"""M1-4: trip creation and the two-button swipe API."""
from __future__ import annotations

from uuid import uuid4

from syncinerary.agents.gather import gather_node
from syncinerary.domain.models import TripState, TripStatus, VoteSignal
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    TripRepository,
    VoteRepository,
)

TRIP_BODY = {
    "destination": "Hokkaido",
    "start_date": "2026-05-21",
    "end_date": "2026-05-25",
    "creator_name": "Gino",
    "creator_home_city": "Taipei",
}


async def _created_trip(client) -> dict:
    response = await client.post("/trips", json=TRIP_BODY)
    assert response.status_code == 201, response.text
    return response.json()


async def _trip_with_deck(client, session, monkeypatch) -> dict:
    body = await _created_trip(client)
    trip = await TripRepository(session).get(body["trip"]["id"])
    _use_test_session(monkeypatch, session)
    await gather_node(TripState(trip=trip))
    return body


# ----- health -----


async def test_health_reports_the_milestone(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "milestone": "M1"}


# ----- trip creation -----


async def test_create_trip_returns_trip_and_traveler_identity(client):
    body = await _created_trip(client)
    assert body["trip"]["destination"] == "Hokkaido"
    assert body["trip"]["status"] == "setup"
    # The client holds this and sends it when voting: there is no auth in M1.
    assert body["traveler_id"]


async def test_days_are_inclusive_of_both_end_dates(client):
    body = await _created_trip(client)
    # 21 to 25 May is five days, not four.
    assert body["trip"]["days"] == 5


async def test_single_day_trip_is_one_day(client):
    response = await client.post(
        "/trips", json={**TRIP_BODY, "start_date": "2026-05-21", "end_date": "2026-05-21"}
    )
    assert response.json()["trip"]["days"] == 1


async def test_end_date_before_start_date_is_rejected(client):
    response = await client.post(
        "/trips", json={**TRIP_BODY, "start_date": "2026-05-25", "end_date": "2026-05-21"}
    )
    assert response.status_code == 422


async def test_blank_destination_is_rejected(client):
    response = await client.post("/trips", json={**TRIP_BODY, "destination": ""})
    assert response.status_code == 422


async def test_creator_is_recorded_on_the_trip(client, session):
    body = await _created_trip(client)
    trip = await TripRepository(session).get(body["trip"]["id"])
    assert str(trip.created_by) == body["traveler_id"]


async def test_get_trip_round_trips(client):
    body = await _created_trip(client)
    response = await client.get(f"/trips/{body['trip']['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == body["trip"]["id"]


async def test_unknown_trip_is_404(client):
    response = await client.get(f"/trips/{uuid4()}")
    assert response.status_code == 404


# ----- the deck -----


async def test_deck_excludes_lodging(client, session, monkeypatch):
    """§8.6: lodging is solver-driven, never swiped."""
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]

    response = await client.get(f"/trips/{trip_id}/candidates")
    assert response.status_code == 200
    deck = response.json()

    assert deck
    assert all(card["type"] != "lodging" for card in deck)
    # Lodging was still gathered, it is just not in the deck.
    stored = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    assert any(c.type.value == "lodging" for c in stored)
    assert len(deck) < len(stored)


async def test_deck_cards_carry_what_the_swipe_screen_needs(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    deck = (await client.get(f"/trips/{body['trip']['id']}/candidates")).json()

    card = deck[0]
    assert set(card) == {
        "id",
        "type",
        "name_canonical",
        "name_original_lang",
        "lat",
        "lng",
        "area",
        "address",
        "category",
        "price_tier",
        "duration_estimate_min",
        "dietary_tags",
    }
    # Provenance and enrichment are not part of the M1 card.
    assert "sources" not in card
    assert "enrichment" not in card


async def test_deck_is_empty_before_gather(client):
    body = await _created_trip(client)
    response = await client.get(f"/trips/{body['trip']['id']}/candidates")
    assert response.status_code == 200
    assert response.json() == []


async def test_deck_for_unknown_trip_is_404(client):
    assert (await client.get(f"/trips/{uuid4()}/candidates")).status_code == 404


# ----- voting -----


async def test_like_is_recorded(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()

    response = await client.post(
        f"/trips/{trip_id}/votes",
        json={
            "traveler_id": body["traveler_id"],
            "candidate_id": deck[0]["id"],
            "signal": "like",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["signal"] == "like"

    stored = await VoteRepository(session).list_for_trip(trip_id)
    assert len(stored) == 1
    assert stored[0].signal is VoteSignal.LIKE


async def test_dislike_is_recorded(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()

    response = await client.post(
        f"/trips/{trip_id}/votes",
        json={
            "traveler_id": body["traveler_id"],
            "candidate_id": deck[0]["id"],
            "signal": "dislike",
        },
    )
    assert response.status_code == 201
    assert response.json()["signal"] == "dislike"


async def test_m4_signals_are_rejected_in_m1(client, session, monkeypatch):
    """like_with_note and must_have arrive in M4 with the note parser and the
    long-press gesture. Accepting them now would store a note nothing parses
    and a must_have the aggregator ignores."""
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()

    for signal in ("like_with_note", "must_have", "shrug"):
        response = await client.post(
            f"/trips/{trip_id}/votes",
            json={
                "traveler_id": body["traveler_id"],
                "candidate_id": deck[0]["id"],
                "signal": signal,
            },
        )
        assert response.status_code == 422, signal


async def test_changing_your_mind_replaces_the_vote(client, session, monkeypatch):
    """§10.1 counts travelers, so one person must never count twice."""
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()
    payload = {"traveler_id": body["traveler_id"], "candidate_id": deck[0]["id"]}

    first = await client.post(f"/trips/{trip_id}/votes", json={**payload, "signal": "like"})
    second = await client.post(f"/trips/{trip_id}/votes", json={**payload, "signal": "dislike"})

    stored = await VoteRepository(session).list_for_trip(trip_id)
    assert len(stored) == 1
    assert stored[0].signal is VoteSignal.DISLIKE
    assert first.json()["id"] == second.json()["id"]


async def test_voting_moves_the_trip_out_of_setup(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id = body["trip"]["id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()

    assert (await TripRepository(session).get(trip_id)).status is TripStatus.SETUP
    await client.post(
        f"/trips/{trip_id}/votes",
        json={
            "traveler_id": body["traveler_id"],
            "candidate_id": deck[0]["id"],
            "signal": "like",
        },
    )
    assert (await TripRepository(session).get(trip_id)).status is TripStatus.SWIPING


async def test_voting_on_another_trips_candidate_is_rejected(client, session, monkeypatch):
    """A candidate id from a different trip must not slip through."""
    mine = await _trip_with_deck(client, session, monkeypatch)
    theirs = await _trip_with_deck(client, session, monkeypatch)
    their_deck = (await client.get(f"/trips/{theirs['trip']['id']}/candidates")).json()

    response = await client.post(
        f"/trips/{mine['trip']['id']}/votes",
        json={
            "traveler_id": mine["traveler_id"],
            "candidate_id": their_deck[0]["id"],
            "signal": "like",
        },
    )
    assert response.status_code == 404


async def test_voting_as_a_traveler_from_another_trip_is_rejected(
    client, session, monkeypatch
):
    mine = await _trip_with_deck(client, session, monkeypatch)
    theirs = await _created_trip(client)
    my_deck = (await client.get(f"/trips/{mine['trip']['id']}/candidates")).json()

    response = await client.post(
        f"/trips/{mine['trip']['id']}/votes",
        json={
            "traveler_id": theirs["traveler_id"],
            "candidate_id": my_deck[0]["id"],
            "signal": "like",
        },
    )
    assert response.status_code == 404


async def test_voting_on_an_unknown_candidate_is_404(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    response = await client.post(
        f"/trips/{body['trip']['id']}/votes",
        json={
            "traveler_id": body["traveler_id"],
            "candidate_id": str(uuid4()),
            "signal": "like",
        },
    )
    assert response.status_code == 404


# ----- progress -----


async def test_progress_tracks_the_deck(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id, traveler_id = body["trip"]["id"], body["traveler_id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()

    start = (
        await client.get(f"/trips/{trip_id}/votes/progress", params={"traveler_id": traveler_id})
    ).json()
    assert start == {"total_candidates": len(deck), "voted": 0, "remaining": len(deck)}

    for card in deck[:3]:
        await client.post(
            f"/trips/{trip_id}/votes",
            json={"traveler_id": traveler_id, "candidate_id": card["id"], "signal": "like"},
        )

    after = (
        await client.get(f"/trips/{trip_id}/votes/progress", params={"traveler_id": traveler_id})
    ).json()
    assert after["voted"] == 3
    assert after["remaining"] == len(deck) - 3


async def test_progress_ignores_revotes(client, session, monkeypatch):
    body = await _trip_with_deck(client, session, monkeypatch)
    trip_id, traveler_id = body["trip"]["id"], body["traveler_id"]
    deck = (await client.get(f"/trips/{trip_id}/candidates")).json()
    payload = {"traveler_id": traveler_id, "candidate_id": deck[0]["id"]}

    await client.post(f"/trips/{trip_id}/votes", json={**payload, "signal": "like"})
    await client.post(f"/trips/{trip_id}/votes", json={**payload, "signal": "dislike"})

    progress = (
        await client.get(f"/trips/{trip_id}/votes/progress", params={"traveler_id": traveler_id})
    ).json()
    assert progress["voted"] == 1


def _use_test_session(monkeypatch, session):
    """Point gather_node's session_scope at the test transaction."""
    from contextlib import asynccontextmanager

    from syncinerary.agents.gather import fixture as fixture_module

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(fixture_module, "session_scope", _scope)
