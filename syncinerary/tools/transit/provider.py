"""Build the transit chain: one primary, then whatever can back it up.

``make_transit_client`` used to return exactly one client, which meant a
coverage gap or an HTTP 500 fell straight through to a distance estimate. It
now returns a resolver over an ordered chain, and keeps the same interface, so
neither solver stage learns that more than one provider exists.

A provider with no credentials is left out of the chain rather than failing.
That is what keeps the pipeline runnable on a laptop with only a Google key:
the chain degrades to Google then estimate, exactly as before.
"""
from __future__ import annotations

from typing import Literal

import httpx
from redis.asyncio import Redis

from syncinerary.config import settings
from syncinerary.tools.transit.google_routes import GoogleRoutesClient
from syncinerary.tools.transit.here import HereTransitClient
from syncinerary.tools.transit.registry import (
    TransitRegion,
    regional_provider_registry,
)
from syncinerary.tools.transit.resolver import FallbackTransitResolver, TransitProvider
from syncinerary.tools.transit.transitous import TransitousClient

TransitProviderName = Literal["google", "transitous", "here"]


def _build(
    name: str,
    *,
    redis: Redis | None,
    http_client: httpx.AsyncClient | None,
) -> TransitProvider | None:
    """One adapter by name, or ``None`` when it has nothing to work with."""
    if name == "google":
        return GoogleRoutesClient(redis=redis, http_client=http_client)
    if name == "transitous":
        return TransitousClient(redis=redis, http_client=http_client)
    if name == "here":
        if not HereTransitClient.is_configured():
            return None
        return HereTransitClient(redis=redis, http_client=http_client)
    raise ValueError(f"Unknown transit provider: {name}")


def transit_chain_names(
    *,
    provider: str | None = None,
    fallbacks: str | None = None,
) -> list[str]:
    """The configured chain, primary first, without building anything."""
    primary = provider or settings.sync_transit_provider
    raw = settings.sync_transit_fallback_providers if fallbacks is None else fallbacks
    ordered = [primary]
    for name in raw.split(","):
        cleaned = name.strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


def make_transit_client(
    *,
    provider: str | None = None,
    fallbacks: str | None = None,
    region: TransitRegion | None = None,
    redis: Redis | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> FallbackTransitResolver:
    """The resolver Stage 2 and the rescue agent both call.

    ``region`` is passed straight to the registry and is never inspected here.
    With an empty registry, which is how this repository ships, it changes
    nothing.
    """
    providers: list[TransitProvider] = []
    for name in transit_chain_names(provider=provider, fallbacks=fallbacks):
        built = _build(name, redis=redis, http_client=http_client)
        if built is not None:
            providers.append(built)
    providers.extend(regional_provider_registry.for_location(region))
    return FallbackTransitResolver(providers)


__all__ = [
    "TransitProviderName",
    "TransitRegion",
    "make_transit_client",
    "transit_chain_names",
]
