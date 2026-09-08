"""Data-source credits some transit providers require in return for use.

This is not the same thing as naming a provider on a leg. A traveler is told
a leg was routed or is approximate and nothing more, because that is the only
part of it they can act on. A credit is a licence term about where the data
came from, so it is carried on the itinerary as a whole and derived from the
providers that actually contributed to it.

A provider with no credit requirement contributes nothing here, which is why
Google and the distance estimate are absent.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel


class TransitAttribution(BaseModel):
    """One credit line, with the page the provider asks it to point at."""

    provider: str
    text: str
    url: str | None = None


#: Keyed by the provider name adapters stamp on a leg.
REQUIRED_ATTRIBUTIONS: dict[str, TransitAttribution] = {
    "transitous": TransitAttribution(
        provider="transitous",
        text="Transit data by Transitous",
        url="https://transitous.org/sources/",
    ),
    "here": TransitAttribution(
        provider="here",
        text="Transit data by HERE",
        url="https://legal.here.com/terms/general-content-supplier/terms-and-notices",
    ),
}


def attributions_for(providers: Iterable[str | None]) -> list[TransitAttribution]:
    """Credits owed for the providers that appear in one itinerary.

    Order follows REQUIRED_ATTRIBUTIONS so the footer does not reshuffle
    itself between two reads of the same trip.
    """
    used = {name for name in providers if name}
    return [
        attribution
        for name, attribution in REQUIRED_ATTRIBUTIONS.items()
        if name in used
    ]


__all__ = ["REQUIRED_ATTRIBUTIONS", "TransitAttribution", "attributions_for"]
