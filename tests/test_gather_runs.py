from tests.test_m7a_group_api import _auth, _owner_trip, _sign_in


async def test_create_draft_start_is_authorized_and_idempotent(
    client, session, creator_anthropic_credential
):
    from syncinerary.store.repositories.gather import GatherRunRepository

    owner = await _sign_in(client, display_name="Leader", handle="leader")
    created = await _owner_trip(client, owner)
    trip_id = created["trip"]["id"]
    await creator_anthropic_credential(trip_id)
    assert created["trip"]["status"] == "draft"
    other = await _sign_in(client, display_name="Other", handle="other")
    url = f"/trips/{trip_id}/gather-runs"
    assert (await client.post(url, headers=_auth(other["token"]))).status_code == 403
    first = await client.post(url, headers=_auth(owner["token"]))
    second = await client.post(url, headers=_auth(owner["token"]))
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    current = await client.get(url + "/current", headers=_auth(owner["token"]))
    assert current.json()["status"] == "queued"
    from uuid import UUID

    run = await GatherRunRepository(session).get(UUID(first.json()["run_id"]))
    assert run.input_snapshot.trip.cities == ["Hokkaido"]
    assert len(run.input_snapshot.travelers) == 1
    assert (
        await client.get(f"/trips/{trip_id}", headers=_auth(owner["token"]))
    ).json()["status"] == "gathering"


async def test_draft_links_do_not_create_deck_and_late_links_do_not_change_snapshot(
    client, session, creator_anthropic_credential
):
    from uuid import UUID

    from syncinerary.store.repositories.gather import GatherRunRepository

    owner = await _sign_in(client, display_name="Leader", handle="leader")
    created = await _owner_trip(client, owner)
    trip_id = created["trip"]["id"]
    await creator_anthropic_credential(trip_id)
    headers = _auth(owner["token"])
    endpoint = f"/trips/{trip_id}/attachments/links"
    response = await client.post(
        endpoint,
        headers=headers,
        json={
            "traveler_id": created["traveler_id"],
            "url": "https://www.instagram.com/p/abc123/",
        },
    )
    assert response.status_code == 201, response.text
    assert (
        await client.get(f"/trips/{trip_id}/candidates", headers=headers)
    ).json() == []
    started = await client.post(f"/trips/{trip_id}/gather-runs", headers=headers)
    await client.post(
        endpoint,
        headers=headers,
        json={
            "traveler_id": created["traveler_id"],
            "url": "https://www.instagram.com/p/late123/",
        },
    )
    run = await GatherRunRepository(session).get(UUID(started.json()["run_id"]))
    assert len(run.input_snapshot.attachments) == 1
    assert run.input_snapshot.attachments[0].canonical_url.endswith("/abc123/")


async def test_trip_creation_requires_an_authenticated_owner(client):
    response = await client.post(
        "/trips",
        json={
            "cities": ["Tokyo"],
            "country": "Japan",
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
            "creator_name": "Anonymous",
        },
    )
    assert response.status_code == 401


async def test_concurrent_starts_use_one_snapshot_and_worker_lock_recovers(engine, monkeypatch):
    import asyncio
    from datetime import date

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from syncinerary.domain.models import Traveler, Trip
    from syncinerary.store.repositories import (
        GatherRunRepository,
        TravelerRepository,
        TripRepository,
    )
    from syncinerary.store.repositories import gather as repository

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        trip = await TripRepository(session).add(
            Trip(
                destination="Tokyo",
                days=1,
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 1),
            )
        )
        leader = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Leader"))
        await TripRepository(session).set_created_by(trip.id, leader.id)

    async def start():
        async with factory.begin() as session:
            return await GatherRunRepository(session).start(trip.id, leader.id)

    try:
        first, second = await asyncio.gather(start(), start())
        assert first.id == second.id
        assert first.input_snapshot == second.input_snapshot
        monkeypatch.setattr(repository, "init_engine", lambda: engine)
        async with repository.own_gather(trip.id) as owner:
            assert owner is not None
            async with repository.own_gather(trip.id) as duplicate:
                assert duplicate is None
        async with repository.own_gather(trip.id) as resumed:
            assert resumed is not None
    finally:
        async with factory.begin() as session:
            run = await GatherRunRepository(session).current(trip.id)
            if run:
                await GatherRunRepository(session).delete(run.id)
            await TravelerRepository(session).delete(leader.id)
            await TripRepository(session).delete(trip.id)


async def test_worker_resumes_badges_without_repeating_gather(session, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import date

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    from syncinerary.agents.graph import graph_config
    from syncinerary.domain.gather import GatherInput, GatherRun
    from syncinerary.domain.models import CandidatePlace, CandidateType, Trip, TripState
    from syncinerary.store.repositories import (
        CandidatePlaceRepository,
        GatherRunRepository,
        TripRepository,
    )
    from syncinerary.workers import gather as worker

    calls = []

    async def discover(state):
        calls.append("gather")
        candidate = await CandidatePlaceRepository(session).add(
            CandidatePlace(
                trip_id=state.trip.id,
                name_canonical="Museum",
                type=CandidateType.ATTRACTION,
                lat=35,
                lng=139,
            )
        )
        return {"candidates": [candidate]}

    async def badges(state):
        calls.append("badges")
        if calls.count("badges") == 1:
            raise RuntimeError("simulated process failure after gather checkpoint")
        return {}

    builder = StateGraph(TripState)
    builder.add_node("gather", discover)
    builder.add_node("badges", badges)
    builder.add_node("aggregate", lambda state: {})
    builder.add_edge(START, "gather")
    builder.add_edge("gather", "badges")
    builder.add_edge("badges", "aggregate")
    builder.add_edge("aggregate", END)
    graph = builder.compile(checkpointer=InMemorySaver(), interrupt_after=["badges"])
    trip = await TripRepository(session).add(
        Trip(destination="Tokyo", days=1, start_date=date(2026, 10, 1), end_date=date(2026, 10, 1))
    )
    run = await GatherRunRepository(session).add(
        GatherRun(
            trip_id=trip.id,
            input_snapshot=GatherInput(trip=trip, travelers=[], constraints=[], attachments=[]),
        )
    )

    @asynccontextmanager
    async def scope():
        yield session

    @asynccontextmanager
    async def tracked(**kwargs):
        yield

    monkeypatch.setattr(worker, "session_scope", scope)
    monkeypatch.setattr(worker, "tracked_run", tracked)
    import pytest

    with pytest.raises(RuntimeError, match="simulated"):
        await worker.execute_run(run, graph)
    await worker.execute_run(run, graph)
    assert calls == ["gather", "badges", "badges"]
    assert (await GatherRunRepository(session).get(run.id)).status == "completed"
    assert (await TripRepository(session).get(trip.id)).status.value == "swiping"
    assert (await graph.aget_state(graph_config(trip.id))).next == ("aggregate",)


async def test_joined_member_preferences_and_links_are_frozen_at_start(
    client, session, creator_anthropic_credential
):
    from uuid import UUID

    from syncinerary.store.repositories import GatherRunRepository

    owner = await _sign_in(client, display_name="Leader", handle="leader")
    created = await _owner_trip(client, owner)
    trip_id = created["trip"]["id"]
    await creator_anthropic_credential(trip_id)
    invite = await client.post(f"/trips/{trip_id}/invites", json={}, headers=_auth(owner["token"]))
    member = await _sign_in(client, display_name="Guest", handle="guest")
    joined = await client.post(
        f"/invites/{invite.json()['code']}/join",
        json={"preference_tags": ["art"]},
        headers=_auth(member["token"]),
    )
    assert joined.status_code == 201, joined.text
    headers = _auth(member["token"])
    consent = await client.put(
        "/accounts/me/ai-consent",
        headers=headers,
        json={"consent_to_anthropic": True},
    )
    assert consent.status_code == 200, consent.text
    saved = await client.put(
        f"/trips/{trip_id}/preferences",
        headers=headers,
        json={"interests": [" Art ", "art"], "dietary_excludes": ["shellfish"]},
    )
    assert saved.status_code == 200, saved.text
    link = await client.post(
        f"/trips/{trip_id}/attachments/links",
        headers=headers,
        json={
            "traveler_id": joined.json()["traveler_id"],
            "url": "https://www.instagram.com/p/guest123/",
        },
    )
    assert link.status_code == 201, link.text
    assert (await client.post(f"/trips/{trip_id}/gather-runs", headers=headers)).status_code == 403
    started = await client.post(f"/trips/{trip_id}/gather-runs", headers=_auth(owner["token"]))
    run = await GatherRunRepository(session).get(UUID(started.json()["run_id"]))
    guest = next(t for t in run.input_snapshot.travelers if t.name == "Guest")
    assert guest.profile["interests"] == ["art"]
    assert any(
        c.traveler_id == guest.id and c.value["excludes"] == ["shellfish"]
        for c in run.input_snapshot.constraints
    )
    assert len(run.input_snapshot.attachments) == 1
    assert (
        await client.put(
            f"/trips/{trip_id}/preferences", headers=headers, json={"interests": ["nightlife"]}
        )
    ).status_code == 409
