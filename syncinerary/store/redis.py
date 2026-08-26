"""Process-wide async Redis client.

redis-py owns a connection pool behind this client. Keeping one client for
the application lifetime avoids opening a socket per transit lookup while
still allowing concurrent Directions cache reads.
"""
from __future__ import annotations

from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.config.transit import (
    REDIS_CONNECT_TIMEOUT_SECONDS,
    REDIS_MAX_CONNECTIONS,
    REDIS_SOCKET_TIMEOUT_SECONDS,
)

_redis: Redis | None = None


def init_redis() -> Redis:
    """Create the pooled process-wide client. Idempotent."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    return _redis


def get_redis() -> Redis:
    return init_redis()


async def dispose_redis() -> None:
    """Close pooled sockets at application shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
