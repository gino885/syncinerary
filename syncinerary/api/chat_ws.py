"""Redis-backed WebSocket for a trip's message thread.

Same shape as replan_ws.py deliberately: one trip-scoped channel, a publisher,
and a forwarder. Redis is transport and Postgres is storage, per the CLAUDE.md
section 4 rationale for having both.
"""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from fastapi import WebSocket

from syncinerary.api.schemas import TripMessageOut


class RedisPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


def chat_channel(trip_id: UUID) -> str:
    return f"trip:{trip_id}:chat"


async def publish_trip_message(
    redis: RedisPublisher,
    message: TripMessageOut,
) -> None:
    payload = {
        "type": "trip_message",
        "message": message.model_dump(mode="json"),
    }
    await redis.publish(
        chat_channel(message.trip_id),
        json.dumps(payload, separators=(",", ":")),
    )


async def stream_trip_messages(
    websocket: WebSocket,
    redis,
    trip_id: UUID,
) -> None:
    """Forward this trip's chat channel until the socket closes."""
    await websocket.accept()
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(chat_channel(trip_id))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if isinstance(data, str):
                await websocket.send_text(data)


__all__ = ["chat_channel", "publish_trip_message", "stream_trip_messages"]
