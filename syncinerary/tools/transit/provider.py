"""Select the configured transit provider without changing solver behavior."""
from __future__ import annotations

from typing import Literal

import httpx
from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.tools.transit.google_routes import GoogleRoutesClient
from syncinerary.tools.transit.transitous import TransitousClient

TransitProviderName = Literal["google", "transitous"]


def make_transit_client(
    *,
    provider: str | None = None,
    redis: Redis | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> GoogleRoutesClient | TransitousClient:
    """Build the production default or the explicitly enabled prototype client."""
    selected = provider or settings.sync_transit_provider
    if selected == "google":
        return GoogleRoutesClient(redis=redis, http_client=http_client)
    if selected == "transitous":
        return TransitousClient(redis=redis, http_client=http_client)
    raise ValueError(f"Unknown transit provider: {selected}")


__all__ = ["TransitProviderName", "make_transit_client"]
