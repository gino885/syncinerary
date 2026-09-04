"""M7b: the chat fan-out against a real Redis, with two live subscribers.

The existing coverage drives stream_trip_messages with a fake redis, which
proves the forwarder loop and nothing about the wiring underneath it. Whether
two people in the same trip both receive a message, and whether a message
leaks into another trip, are properties of the channel and pub/sub, so they
need the real thing. Redis is a service in CI for exactly this.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from syncinerary.api.chat_ws import (
    chat_channel,
    publish_trip_message,
    stream_trip_messages,
)
from syncinerary.api.schemas import TripMessageOut
from syncinerary.domain.models import TripMessageKind
from syncinerary.store.redis import get_redis

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def fresh_redis_client():
    """Give each test a Redis client built on its own event loop.

    store/redis.py keeps one pooled client for the process, which is right in
    production and wrong here: pytest-asyncio runs each test on a new loop, so
    the second test would inherit connections belonging to a closed one.
    """
    from syncinerary.store import redis as redis_module

    redis_module._redis = None
    try:
        yield
    finally:
        client = redis_module._redis
        redis_module._redis = None
        if client is not None:
            await client.aclose()


class RecordingSocket:
    """A websocket that only records. Starlette owns the framing; what is
    under test is which sockets get told."""

    def __init__(self) -> None:
        self.accepted = False
        self.received: list[dict] = []
        self.ready = asyncio.Event()

    async def accept(self) -> None:
        self.accepted = True
        self.ready.set()

    async def send_text(self, data: str) -> None:
        self.received.append(json.loads(data))


def _message(trip_id, body: str = "hello") -> TripMessageOut:
    return TripMessageOut(
        id=uuid4(),
        trip_id=trip_id,
        traveler_id=uuid4(),
        author_name="Gino",
        body=body,
        kind=TripMessageKind.TEXT,
        link_attachment_id=None,
        link=None,
        created_at=datetime.now(UTC),
    )


async def _subscribed(trip_id) -> tuple[RecordingSocket, asyncio.Task]:
    """Start a forwarder and wait until it has actually accepted.

    Publishing before the subscription exists would drop the message: Redis
    pub/sub has no backlog, so a test that raced here would pass or fail on
    timing rather than on behaviour.
    """
    socket = RecordingSocket()
    task = asyncio.create_task(stream_trip_messages(socket, get_redis(), trip_id))
    await asyncio.wait_for(socket.ready.wait(), timeout=5)
    await asyncio.sleep(0.1)
    return socket, task


async def _settle(*tasks: asyncio.Task) -> None:
    await asyncio.sleep(0.3)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_two_people_in_one_trip_both_receive_the_message():
    """The property M7a never actually exercised: a group thread is only a
    group thread if the other person's screen updates."""
    trip_id = uuid4()
    mei, mei_task = await _subscribed(trip_id)
    sam, sam_task = await _subscribed(trip_id)

    await publish_trip_message(get_redis(), _message(trip_id, "found a ramen place"))
    await _settle(mei_task, sam_task)

    assert len(mei.received) == 1, "the first subscriber missed it"
    assert len(sam.received) == 1, "the second subscriber missed it"
    assert mei.received[0]["type"] == "trip_message"
    assert mei.received[0]["message"]["body"] == "found a ramen place"
    assert sam.received[0] == mei.received[0], "both should see the same message"


async def test_a_message_does_not_leak_into_another_trip():
    """Channels are per trip. A leak here would put one group's plans in
    another group's thread."""
    ours = uuid4()
    theirs = uuid4()
    mine, mine_task = await _subscribed(ours)
    stranger, stranger_task = await _subscribed(theirs)

    await publish_trip_message(get_redis(), _message(ours, "our secret spot"))
    await _settle(mine_task, stranger_task)

    assert len(mine.received) == 1
    assert stranger.received == []


async def test_a_late_joiner_gets_what_is_sent_after_they_arrive():
    """Redis pub/sub has no backlog, so history comes from Postgres and the
    socket only carries what happens next. Worth pinning: a reader who assumed
    otherwise would build a thread with holes in it."""
    trip_id = uuid4()
    early, early_task = await _subscribed(trip_id)

    await publish_trip_message(get_redis(), _message(trip_id, "before"))
    await asyncio.sleep(0.2)

    late, late_task = await _subscribed(trip_id)
    await publish_trip_message(get_redis(), _message(trip_id, "after"))
    await _settle(early_task, late_task)

    assert [m["message"]["body"] for m in early.received] == ["before", "after"]
    assert [m["message"]["body"] for m in late.received] == ["after"]


async def test_the_channel_is_scoped_to_the_trip():
    trip_id = uuid4()
    assert chat_channel(trip_id) == f"trip:{trip_id}:chat"
    assert chat_channel(uuid4()) != chat_channel(trip_id)
