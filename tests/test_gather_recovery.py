from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from syncinerary.domain.gather import GatherInput, GatherRun
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    SocialPlatform,
    SourceAttachment,
    Trip,
)
from tests.test_m7a_group_api import _auth, _owner_trip, _sign_in

pytestmark = pytest.mark.asyncio


def _run(*, attachments: list[SourceAttachment] | None = None) -> GatherRun:
    trip = Trip(
        destination="Tokyo",
        cities=["Tokyo"],
        days=1,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
    )
    return GatherRun(
        trip_id=trip.id,
        input_snapshot=GatherInput(
            trip=trip,
            travelers=[],
            constraints=[],
            attachments=attachments or [],
        ),
    )


async def test_heartbeat_ownership_loss_leaves_run_recoverable(monkeypatch):
    from syncinerary.workers import gather as worker

    run = _run()
    changes: list[dict] = []

    class Runs:
        def __init__(self, _session):
            pass

        async def pending(self):
            return [run]

        async def get(self, _run_id):
            return run

        async def change(self, _run_id, **fields):
            changes.append(fields)
            return run.model_copy(update={"status": fields.get("status", run.status)})

    @asynccontextmanager
    async def scope():
        yield object()

    @asynccontextmanager
    async def ownership(_trip_id):
        yield SimpleNamespace(invalidated=True)

    async def never_finishes(_run, _graph):
        await worker.asyncio.Event().wait()

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(worker, "GatherRunRepository", Runs)
    monkeypatch.setattr(worker, "session_scope", scope)
    monkeypatch.setattr(worker, "own_gather", ownership)
    monkeypatch.setattr(worker, "execute_run", never_finishes)
    monkeypatch.setattr(worker.asyncio, "sleep", no_delay)

    assert await worker.work_one(object())
    assert any(change.get("status") == "running" for change in changes)
    assert not any(change.get("status") == "failed" for change in changes)


async def test_retry_before_checkpoint_skips_resolved_snapshot_attachment(monkeypatch):
    from syncinerary.workers import gather as worker

    attachment = SourceAttachment(
        trip_id=uuid4(),
        traveler_id=uuid4(),
        platform=SocialPlatform.INSTAGRAM,
        input_type=AttachmentInputType.LINK,
        status=AttachmentStatus.PENDING,
        canonical_url="https://www.instagram.com/p/already-resolved/",
    )
    run = _run(attachments=[attachment])
    attachment = attachment.model_copy(update={"trip_id": run.trip_id})
    run = run.model_copy(update={
        "input_snapshot": run.input_snapshot.model_copy(update={"attachments": [attachment]})
    })
    invoked = False

    class Graph:
        async def aget_state(self, _config):
            return SimpleNamespace(values={"trip": {}} if invoked else {},
                                   next=("aggregate",) if invoked else ())

        async def ainvoke(self, _state, _config):
            nonlocal invoked
            invoked = True

    class Attachments:
        def __init__(self, _session):
            pass

        async def get(self, _attachment_id):
            return attachment.model_copy(update={"status": AttachmentStatus.READY})

    class Candidates:
        def __init__(self, _session):
            pass

        async def list_swipeable(self, _trip_id):
            return [object()]

    class Trips:
        def __init__(self, _session):
            pass

        async def set_status(self, _trip_id, _status):
            return None

    class Runs:
        def __init__(self, _session):
            pass

        async def change(self, _run_id, **_fields):
            return run

    @asynccontextmanager
    async def scope():
        yield object()

    @asynccontextmanager
    async def tracked(**_kwargs):
        yield

    async def must_not_resolve(*_args, **_kwargs):
        pytest.fail("a terminal attachment was resolved twice")

    monkeypatch.setattr(worker, "SourceAttachmentRepository", Attachments)
    monkeypatch.setattr(worker, "CandidatePlaceRepository", Candidates)
    monkeypatch.setattr(worker, "TripRepository", Trips)
    monkeypatch.setattr(worker, "GatherRunRepository", Runs)
    monkeypatch.setattr(worker, "session_scope", scope)
    monkeypatch.setattr(worker, "tracked_run", tracked)
    monkeypatch.setattr(worker, "resolve_link_attachment", must_not_resolve)

    await worker.execute_run(run, Graph())
    assert invoked


async def test_post_swiping_link_requires_contributor_account(client, session):
    from uuid import UUID

    from syncinerary.domain.models import TripStatus
    from syncinerary.store.repositories import TripRepository

    owner = await _sign_in(client, display_name="Owner", handle="recovery-owner")
    created = await _owner_trip(client, owner)
    trip_id = created["trip"]["id"]
    endpoint = f"/trips/{trip_id}/attachments/links"
    payload = {
        "traveler_id": created["traveler_id"],
        "url": "https://www.instagram.com/p/contributor-only/",
    }
    await TripRepository(session).set_status(UUID(trip_id), TripStatus.SWIPING)

    assert (await client.post(endpoint, json=payload)).status_code == 403
    other = await _sign_in(client, display_name="Other", handle="recovery-other")
    assert (await client.post(endpoint, json=payload,
                              headers=_auth(other["token"]))).status_code == 403
