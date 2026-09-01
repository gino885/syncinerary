"""M6 HTTP and Redis notification contracts."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, time
from uuid import UUID

import pytest
from pydantic import ValidationError

from syncinerary.api.replan_ws import (
    publish_replan_proposal,
    replan_channel,
    stream_replan_proposals,
)
from syncinerary.api.schemas import DisruptionRequest, ReplanProposalOut
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.tools.transit import (
    PairwiseTransitRequest,
    TransitDuration,
    TransitMatrix,
    TransitMode,
)


@pytest.mark.parametrize(
    ("trigger", "payload"),
    [
        ("reservation_cancelled", {"node_id": "10000000-0000-0000-0000-000000000001"}),
        ("transit_delay", {"node_id": "10000000-0000-0000-0000-000000000001", "delay_minutes": 30}),
        ("overslept", {"day": 0, "at": "10:30"}),
        ("place_closed", {"node_id": "10000000-0000-0000-0000-000000000001"}),
        ("weather", {"day": 1}),
        ("other", {"affected_node_ids": ["10000000-0000-0000-0000-000000000001"]}),
    ],
)
def test_disruption_request_validates_every_trigger_payload(trigger, payload):
    request = DisruptionRequest(trigger_type=trigger, trigger_payload=payload)

    assert request.trigger_type.value == trigger


def test_disruption_request_rejects_missing_trigger_fields():
    with pytest.raises(ValidationError):
        DisruptionRequest(trigger_type="transit_delay", trigger_payload={"delay_minutes": 30})


async def _proposal_fixture(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            days=1,
        )
    )
    traveler = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Gino")
    )
    places = await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=name,
                lat=43.06,
                lng=141.35,
            )
            for name in ("Old stop", "Moved stop", "New stop")
        ]
    )
    versions = ItineraryVersionRepository(session)
    active = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
        )
    )
    proposed = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=2,
            status=ItineraryStatus.PROPOSED,
            parent_version_id=active.id,
        )
    )
    await ItineraryNodeRepository(session).add_many(
        [
            ItineraryNode(
                version_id=active.id,
                candidate_id=places[0].id,
                day=0,
                start_time=time(9),
                end_time=time(10),
            ),
            ItineraryNode(
                version_id=active.id,
                candidate_id=places[1].id,
                day=0,
                start_time=time(11),
                end_time=time(12),
            ),
            ItineraryNode(
                version_id=proposed.id,
                candidate_id=places[1].id,
                day=0,
                start_time=time(12),
                end_time=time(13),
            ),
            ItineraryNode(
                version_id=proposed.id,
                candidate_id=places[2].id,
                day=0,
                start_time=time(14),
                end_time=time(15),
            ),
        ]
    )
    event = await ReplanEventRepository(session).add(
        ReplanEvent(
            trip_id=trip.id,
            trigger_type=ReplanTrigger.PLACE_CLOSED,
            trigger_payload={"node_id": "old"},
            proposed_version_id=proposed.id,
            trace_json={
                "trigger": {"type": "place_closed"},
                "affected_nodes": [],
                "alternatives_considered": [],
                "downstream_changes": [],
            },
        )
    )
    return trip, traveler, active, proposed, event


async def test_diff_endpoint_names_each_change(client, session):
    trip, _traveler, active, proposed, _event = await _proposal_fixture(session)

    response = await client.get(
        f"/trips/{trip.id}/itinerary/diff",
        params={"from_version_id": str(active.id), "to_version_id": str(proposed.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["name"] for item in body["removed"]] == ["Old stop"]
    assert [item["name"] for item in body["added"]] == ["New stop"]
    assert [item["name"] for item in body["time_changed"]] == ["Moved stop"]


async def test_approve_endpoint_applies_the_pending_proposal(client, session):
    trip, traveler, active, proposed, event = await _proposal_fixture(session)

    response = await client.post(
        f"/trips/{trip.id}/replans/{event.id}/approve",
        json={"traveler_id": str(traveler.id)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    versions = ItineraryVersionRepository(session)
    assert (await versions.get(active.id)).status is ItineraryStatus.SUPERSEDED
    assert (await versions.get(proposed.id)).status is ItineraryStatus.ACTIVE

    repeated = await client.post(
        f"/trips/{trip.id}/replans/{event.id}/reject",
        json={"traveler_id": str(traveler.id)},
    )
    assert repeated.status_code == 409


class ContextTransit:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def prefetch_pairwise(self, request: PairwiseTransitRequest) -> TransitMatrix:
        return TransitMatrix(
            legs=[
                TransitDuration(
                    origin=origin,
                    destination=destination,
                    mode=TransitMode.WALKING,
                    departure_window=request.departure_window,
                    duration_seconds=600,
                    duration_minutes=10,
                )
                for origin in request.locations
                for destination in request.locations
                if origin != destination
            ]
        )


async def test_disruption_endpoint_builds_a_pending_proposal(
    client,
    session,
    monkeypatch,
):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            days=1,
        )
    )
    places = await CandidatePlaceRepository(session).add_many(
        [
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=name,
                lat=43.06 + index / 1000,
                lng=141.35 + index / 1000,
                fatigue_cost=1,
                hours_by_weekday={
                    weekday: [[8, 20]]
                    for weekday in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                },
            )
            for index, name in enumerate(("Closed stop", "Nearby replacement"))
        ]
    )
    active = await ItineraryVersionRepository(session).add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=1,
            status=ItineraryStatus.ACTIVE,
        )
    )
    closed = await ItineraryNodeRepository(session).add(
        ItineraryNode(
            version_id=active.id,
            candidate_id=places[0].id,
            day=0,
            start_time=time(9),
            end_time=time(10),
        )
    )

    async def no_publish(*_args):
        return None

    @asynccontextmanager
    async def use_test_session():
        yield session

    monkeypatch.setattr(
        "syncinerary.agents.rescue.GoogleDirectionsClient",
        ContextTransit,
    )
    monkeypatch.setattr(
        "syncinerary.api.routers.replans.publish_replan_proposal",
        no_publish,
    )
    monkeypatch.setattr(
        "syncinerary.harness.wrapper.session_scope",
        use_test_session,
    )

    response = await client.post(
        f"/trips/{trip.id}/disruptions",
        json={
            "trigger_type": "place_closed",
            "trigger_payload": {"node_id": str(closed.id)},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["current_version_id"] == str(active.id)
    assert body["diff"]["added"][0]["name"] == "Nearby replacement"
    assert (await ItineraryVersionRepository(session).get_active(trip.id)).id == active.id


class FakeRedis:
    def __init__(self):
        self.messages = []

    async def publish(self, channel, message):
        self.messages.append((channel, message))
        return 1


async def test_proposal_notification_uses_trip_scoped_channel():
    trip_id = "40000000-0000-0000-0000-000000000001"
    redis = FakeRedis()
    proposal = ReplanProposalOut.model_validate(
        {
            "event_id": "50000000-0000-0000-0000-000000000001",
            "trip_id": trip_id,
            "trigger_type": "weather",
            "status": ReplanStatus.PENDING,
            "current_version_id": "60000000-0000-0000-0000-000000000001",
            "proposed_version_id": "60000000-0000-0000-0000-000000000002",
            "trace": {
                "trigger": {"type": "weather"},
                "affected_nodes": [],
                "alternatives_considered": [],
                "downstream_changes": [],
            },
            "diff": {"added": [], "removed": [], "moved": [], "time_changed": []},
        }
    )

    await publish_replan_proposal(redis, proposal)

    assert redis.messages[0][0] == replan_channel(proposal.trip_id)
    assert '"type":"replan_proposed"' in redis.messages[0][1]


class FakePubSub:
    def __init__(self):
        self.channel = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def subscribe(self, channel):
        self.channel = channel

    async def listen(self):
        yield {"type": "subscribe", "data": 1}
        yield {"type": "message", "data": '{"type":"replan_proposed"}'}


class FakeSocketRedis:
    def __init__(self):
        self.subscription = FakePubSub()

    def pubsub(self):
        return self.subscription


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, message):
        self.messages.append(message)


async def test_websocket_stream_forwards_only_trip_messages():
    trip_id = UUID("40000000-0000-0000-0000-000000000001")
    redis = FakeSocketRedis()
    websocket = FakeWebSocket()

    await stream_replan_proposals(websocket, redis, trip_id)

    assert websocket.accepted is True
    assert redis.subscription.channel == replan_channel(trip_id)
    assert websocket.messages == ['{"type":"replan_proposed"}']
