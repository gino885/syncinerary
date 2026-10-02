"""Explicit edits retain user choices and only become active after approval."""

from datetime import date, time
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from syncinerary.agents.manual_itinerary import propose_edit
from syncinerary.agents.rescue import ReplanConflict, ReplanInputError, decide_replan
from syncinerary.domain.itinerary_edit import EditedStop, ItineraryEdit
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.tools.transit import TransitDuration, TransitMatrix, TransitMode


class Transit:
    async def prefetch_pairwise(self, request):
        return TransitMatrix(
            legs=[
                TransitDuration(
                    origin=a,
                    destination=b,
                    mode=TransitMode.WALKING,
                    departure_window=request.departure_window,
                    duration_seconds=600,
                    duration_minutes=10,
                )
                for i, a in enumerate(request.locations)
                for j, b in enumerate(request.locations)
                if i != j
            ]
        )


async def seed(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Tokyo",
            cities=["Tokyo"],
            city_days=[2],
            days=2,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 2),
            timezone="Asia/Tokyo",
        )
    )
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Owner"))
    places = await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=f"Museum {i}",
                lat=35.68 + i * 0.001,
                lng=139.7,
                fatigue_cost=1,
                duration_estimate_min=60,
                enrichment={"city": "Tokyo"},
            )
            for i in range(4)
        ]
    )
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
            objective_breakdown={"day_start_minute": 480, "day_end_minute": 1260},
        )
    )
    nodes = await ItineraryNodeRepository(session).add_many(
        [
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[0].id,
                day=0,
                start_time=time(9),
                end_time=time(10),
            ),
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[1].id,
                day=1,
                start_time=time(9),
                end_time=time(10),
            ),
        ]
    )
    edit = ItineraryEdit(
        base_version_id=version.id,
        traveler_id=traveler.id,
        stops=[
            EditedStop(
                candidate_id=n.candidate_id, day=n.day, start_time=n.start_time, end_time=n.end_time
            )
            for n in nodes
        ],
    )
    return trip, traveler, places, version, nodes, edit


async def test_add_non_reel_stop_preserves_parent_and_other_day_until_approval(session):
    trip, traveler, places, version, old, edit = await seed(session)
    edit.stops.append(
        EditedStop(candidate_id=places[2].id, day=0, start_time=time(10, 30), end_time=time(11, 30))
    )
    proposal = await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == version.id
    assert await ItineraryNodeRepository(session).list_for_version(version.id) == old
    new = await ItineraryNodeRepository(session).list_for_version(proposal.version.id)
    assert {(n.candidate_id, n.day, n.start_time, n.end_time) for n in new} == {
        *((n.candidate_id, n.day, n.start_time, n.end_time) for n in old),
        (places[2].id, 0, time(10, 30), time(11, 30)),
    }
    await decide_replan(
        session, trip_id=trip.id, event_id=proposal.event.id, traveler_id=traveler.id, approve=True
    )
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == proposal.version.id


async def test_move_retime_duration_and_remove_are_exact(session):
    trip, _, places, _, _, edit = await seed(session)
    edit.stops = [
        EditedStop(candidate_id=places[0].id, day=1, start_time=time(10), end_time=time(11, 30))
    ]
    result = await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    nodes = await ItineraryNodeRepository(session).list_for_version(result.version.id)
    assert [(n.candidate_id, n.day, n.start_time, n.end_time) for n in nodes] == [
        (places[0].id, 1, time(10), time(11, 30))
    ]


@pytest.mark.parametrize(
    "case", ["overlap", "travel_gap", "foreign", "city", "fixed", "stale", "outsider"]
)
async def test_invalid_edits_leave_active_version_unchanged(session, case):
    trip, _, places, version, _, edit = await seed(session)
    if case in {"overlap", "travel_gap"}:
        edit.stops.append(
            EditedStop(
                candidate_id=places[2].id,
                day=0,
                start_time=time(9, 30) if case == "overlap" else time(10),
                end_time=time(11),
            )
        )
    elif case == "foreign":
        edit.stops[0].candidate_id = uuid4()
    elif case == "city":
        other = await CandidatePlaceRepository(session).add(
            places[2].model_copy(update={"id": uuid4(), "enrichment": {"city": "Atami"}})
        )
        edit.stops[0].candidate_id = other.id
    elif case == "fixed":
        # Append a reservation to the active fixture; the edit omitted it.
        await ItineraryNodeRepository(session).add(
            ItineraryNode(
                version_id=version.id,
                candidate_id=places[3].id,
                day=0,
                start_time=time(15),
                end_time=time(16),
                fixed=True,
                lock_reason="reservation",
            )
        )
    elif case == "stale":
        edit.base_version_id = uuid4()
    elif case == "outsider":
        edit.traveler_id = uuid4()
    with pytest.raises((ReplanInputError, ReplanConflict)):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    assert len(await ItineraryVersionRepository(session).list_for_trip(trip.id)) == 1


def test_edit_schema_rejects_duplicate_and_off_grid_stops():
    with pytest.raises(ValidationError):
        EditedStop(candidate_id=uuid4(), day=0, start_time=time(9, 5), end_time=time(10))
    stop = EditedStop(candidate_id=uuid4(), day=0, start_time=time(9), end_time=time(10))
    with pytest.raises(ValidationError):
        ItineraryEdit(base_version_id=uuid4(), traveler_id=uuid4(), stops=[stop, stop])


async def test_manual_api_requires_membership_and_returns_reviewable_proposal(
    client, session, monkeypatch
):
    from contextlib import asynccontextmanager

    from syncinerary.api.routers import itinerary_edits

    trip, traveler, places, version, _, edit = await seed(session)

    @asynccontextmanager
    async def scoped():
        yield session

    monkeypatch.setattr("syncinerary.harness.wrapper.session_scope", scoped)

    @asynccontextmanager
    async def transit():
        yield Transit()

    from syncinerary.agents import manual_itinerary

    monkeypatch.setattr(manual_itinerary, "make_transit_client", transit)

    async def publish(*args):
        pass

    monkeypatch.setattr(itinerary_edits, "publish_replan_proposal", publish)
    monkeypatch.setattr(itinerary_edits, "get_redis", lambda: None)
    bad = await client.get(
        f"/trips/{trip.id}/itinerary/edit-places", params={"traveler_id": str(uuid4()), "day": 0}
    )
    assert bad.status_code == 403
    saved = await client.get(
        f"/trips/{trip.id}/itinerary/edit-places",
        params={"traveler_id": str(traveler.id), "day": 0},
    )
    assert saved.status_code == 200 and len(saved.json()) == 4
    edit.stops.append(
        EditedStop(candidate_id=places[2].id, day=0, start_time=time(10, 30), end_time=time(11, 30))
    )
    response = await client.post(
        f"/trips/{trip.id}/itinerary/edits", json=edit.model_dump(mode="json")
    )
    assert response.status_code == 201, response.text
    assert response.json()["trigger_type"] == "user_request"
    assert response.json()["diff"]["added"][0]["candidate_id"] == str(places[2].id)
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == version.id
    await decide_replan(
        session,
        trip_id=trip.id,
        event_id=UUID(response.json()["event_id"]),
        traveler_id=traveler.id,
        approve=True,
    )
    reloaded = await client.get(
        f"/trips/{trip.id}/itinerary", params={"traveler_id": str(traveler.id)}
    )
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["version_id"] == response.json()["proposed_version_id"]
    assert reloaded.json()["narrative"] is None
    assert places[2].id in {
        UUID(stop["candidate_id"]) for day in reloaded.json()["days"] for stop in day["stops"]
    }


async def test_empty_day_and_rejection_preserve_original(session):
    trip, traveler, _, version, old, edit = await seed(session)
    edit.stops = []
    proposal = await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    assert await ItineraryNodeRepository(session).list_for_version(proposal.version.id) == []
    await decide_replan(
        session, trip_id=trip.id, event_id=proposal.event.id, traveler_id=traveler.id, approve=False
    )
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == version.id
    assert await ItineraryNodeRepository(session).list_for_version(version.id) == old


async def test_adjust_day_keeps_every_selected_place_and_other_day(session):
    trip, _, places, _version, old, edit = await seed(session)
    edit.stops.append(
        EditedStop(candidate_id=places[2].id, day=0, start_time=time(9), end_time=time(10))
    )
    edit.adjust_days = [0]
    proposal = await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    new = await ItineraryNodeRepository(session).list_for_version(proposal.version.id)
    assert {n.candidate_id for n in new} == {s.candidate_id for s in edit.stops}
    unchanged = next(n for n in new if n.day == 1)
    assert unchanged.start_time == old[1].start_time and unchanged.end_time == old[1].end_time


async def test_provider_failure_and_pending_update_leave_active_intact(session):
    trip, _, _places, version, _, edit = await seed(session)
    edit.stops[0].start_time = time(10)
    edit.stops[0].end_time = time(11)

    class FailedTransit:
        async def prefetch_pairwise(self, request):
            raise ConnectionError("Transit provider unavailable")

    with pytest.raises(ConnectionError):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=FailedTransit())
    assert len(await ItineraryVersionRepository(session).list_for_trip(trip.id)) == 1
    await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    with pytest.raises(ReplanConflict):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == version.id


async def test_search_is_ephemeral_and_selection_is_verified_deduplicated(
    client, session, monkeypatch
):
    from syncinerary.api.routers import itinerary_edits

    trip, traveler, _, _, _, _ = await seed(session)
    place = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.FOOD,
        name_canonical="User restaurant",
        lat=35.68,
        lng=139.7,
        enrichment={"city": "Tokyo", "google_place_id": "verified-place"},
    )

    async def search(*args, **kwargs):
        return [place]

    monkeypatch.setattr(itinerary_edits, "searched_places", search)
    base = f"/trips/{trip.id}/itinerary/edit-places"
    query = {"traveler_id": str(traveler.id), "day": 0, "q": "User restaurant"}
    response = await client.get(base, params=query)
    assert response.status_code == 200 and response.json()[0]["candidate_id"] is None
    assert len(await CandidatePlaceRepository(session).list_for_trip(trip.id)) == 4
    body = {
        "traveler_id": str(traveler.id),
        "day": 0,
        "query": "User restaurant",
        "place_id": "forged",
    }
    assert (await client.post(base, json=body)).status_code == 422
    body["place_id"] = "verified-place"
    selected = await client.post(base, json=body)
    repeated = await client.post(base, json=body)
    assert selected.status_code == 201, selected.text
    assert selected.json()["candidate_id"] == repeated.json()["candidate_id"]
    candidate = await CandidatePlaceRepository(session).get(UUID(selected.json()["candidate_id"]))
    assert candidate.sources[-1].by == traveler.id
    assert candidate.sources[-1].subtype == "manual_selection"


async def test_known_dietary_conflict_and_closed_venue_are_rejected(session):
    from syncinerary.domain.models import Constraint, ConstraintKind
    from syncinerary.store.repositories import ConstraintRepository

    trip, _, places, _, _, edit = await seed(session)
    await ConstraintRepository(session).add(
        Constraint(
            trip_id=trip.id,
            type="dietary",
            kind=ConstraintKind.HARD,
            value={"excludes": ["seafood"]},
        )
    )
    seafood = await CandidatePlaceRepository(session).add(
        places[2].model_copy(
            update={"id": uuid4(), "type": CandidateType.FOOD, "dietary_tags": ["seafood"]}
        )
    )
    edit.stops.append(
        EditedStop(candidate_id=seafood.id, day=0, start_time=time(12), end_time=time(13))
    )
    with pytest.raises(ReplanInputError, match="dietary"):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())
    closed = await CandidatePlaceRepository(session).add(
        places[3].model_copy(
            update={
                "id": uuid4(),
                "category": "museum",
                "hours_by_weekday": {"thu": [[16, 17]]},
            }
        )
    )
    edit.stops[-1].candidate_id = closed.id
    with pytest.raises(ReplanInputError):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())


def test_legacy_city_days_follow_the_existing_route():
    from syncinerary.agents.manual_itinerary import city_for_day

    trip = Trip(
        destination="Tokyo",
        cities=["Tokyo", "Atami"],
        days=3,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
    )
    assert city_for_day(trip, 1, existing_city="Atami") == "Atami"
    trip.city_days = [2, 1]
    assert city_for_day(trip, 1, existing_city="Atami") == "Tokyo"


async def test_manual_edit_respects_original_daily_duration_cap(session):
    trip, _, _, version, _, edit = await seed(session)
    repo = ItineraryVersionRepository(session)
    await repo.set_status(version.id, ItineraryStatus.SUPERSEDED)
    bounded = await repo.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=2,
            status=ItineraryStatus.ACTIVE,
            objective_breakdown={"day_duration_cap_minutes": 60.0},
        )
    )
    edit.base_version_id = bounded.id
    edit.stops = [edit.stops[0].model_copy(update={"end_time": time(11)})]
    with pytest.raises(ReplanInputError):
        await propose_edit(session, trip_id=trip.id, edit=edit, transit_provider=Transit())


async def test_bound_member_cannot_be_impersonated_without_their_account(client, session):
    from syncinerary.domain.models import Account
    from syncinerary.store.repositories import AccountRepository

    trip, _, _, _, _, _ = await seed(session)
    account = await AccountRepository(session).add(
        Account(display_name="Member", handle="manual-editor")
    )
    member = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Member", account_id=account.id)
    )
    response = await client.get(
        f"/trips/{trip.id}/itinerary/edit-places", params={"traveler_id": str(member.id), "day": 0}
    )
    assert response.status_code == 403


async def test_edit_detects_version_change_during_transit_validation(session):
    trip, _, _, version, _, edit = await seed(session)
    edit.stops[0].start_time = time(10)
    edit.stops[0].end_time = time(11)

    class ConcurrentTransit(Transit):
        async def prefetch_pairwise(self, request):
            repo = ItineraryVersionRepository(session)
            await repo.set_status(version.id, ItineraryStatus.SUPERSEDED)
            await repo.add(
                ItineraryVersion(trip_id=trip.id, version_no=2, status=ItineraryStatus.ACTIVE)
            )
            return await super().prefetch_pairwise(request)

    with pytest.raises(ReplanConflict, match="while checking"):
        await propose_edit(
            session, trip_id=trip.id, edit=edit, transit_provider=ConcurrentTransit()
        )
    versions = await ItineraryVersionRepository(session).list_for_trip(trip.id)
    assert len(versions) == 2 and all(v.status is not ItineraryStatus.PROPOSED for v in versions)
