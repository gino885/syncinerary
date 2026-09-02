"""Redis-backed WebSocket notification helpers for pending replans."""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from fastapi import WebSocket

from syncinerary.api.schemas import ReplanProposalOut


class RedisPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


def replan_channel(trip_id: UUID) -> str:
    """Stable tenant-scoped channel for one trip's short-lived proposals."""
    return f"trip:{trip_id}:replan"


async def publish_replan_proposal(
    redis: RedisPublisher,
    proposal: ReplanProposalOut,
) -> None:
    payload = {
        "type": "replan_proposed",
        "proposal": proposal.model_dump(mode="json"),
    }
    await redis.publish(
        replan_channel(proposal.trip_id),
        json.dumps(payload, separators=(",", ":")),
    )


async def stream_replan_proposals(
    websocket: WebSocket,
    redis,
    trip_id: UUID,
) -> None:
    """Forward this trip's Redis pub/sub messages until the socket closes."""
    await websocket.accept()
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(replan_channel(trip_id))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if isinstance(data, str):
                await websocket.send_text(data)


__all__ = [
    "publish_replan_proposal",
    "replan_channel",
    "stream_replan_proposals",
]
