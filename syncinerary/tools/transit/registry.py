"""Where a country-specific transit provider plugs in, if one ever does.

Empty by default, and it must stay that way. The point of the registry is
that adding NAVITIME for Japan, or a city's own API, is a registration and a
credential rather than a branch inside the routing code. Nothing in the
resolver or in either solver stage may ask what country a trip is in.

    from syncinerary.tools.transit.registry import regional_provider_registry

    regional_provider_registry.register(
        country="Japan",
        factory=lambda: NavitimeClient(),
    )
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncinerary.tools.transit.resolver import TransitProvider

ProviderFactory = Callable[[], "TransitProvider"]


@dataclass(frozen=True)
class TransitRegion:
    """Where a trip is, in the only terms the trip record actually knows."""

    country: str | None = None
    city: str | None = None


def _normalize(value: str | None) -> str | None:
    return value.strip().casefold() if value else None


class RegionalProviderRegistry:
    """Ordered regional providers, looked up by country and optionally city.

    A city entry is more specific than a country entry, so it is offered
    first. Registration is idempotent per key: registering the same key twice
    replaces the earlier factory rather than routing through both.
    """

    def __init__(self) -> None:
        self._by_country: dict[str, list[ProviderFactory]] = {}
        self._by_city: dict[tuple[str | None, str], list[ProviderFactory]] = {}

    def register(
        self,
        *,
        factory: ProviderFactory,
        country: str | None = None,
        city: str | None = None,
    ) -> None:
        if country is None and city is None:
            raise ValueError("A regional provider needs a country or a city")
        if city is not None:
            self._by_city.setdefault((_normalize(country), _normalize(city)), []).append(
                factory
            )
            return
        assert country is not None
        self._by_country.setdefault(_normalize(country) or "", []).append(factory)

    def clear(self) -> None:
        """Drop every registration. Exists for tests, not for runtime code."""
        self._by_country.clear()
        self._by_city.clear()

    def for_location(self, region: TransitRegion | None) -> list[TransitProvider]:
        """Build the providers registered for this place, most specific first."""
        if region is None:
            return []
        factories: list[ProviderFactory] = []
        city = _normalize(region.city)
        country = _normalize(region.country)
        if city is not None:
            factories.extend(self._by_city.get((country, city), ()))
            factories.extend(self._by_city.get((None, city), ()))
        if country is not None:
            factories.extend(self._by_country.get(country, ()))
        return [factory() for factory in factories]


#: The process-wide registry. Deliberately empty in this repository.
regional_provider_registry = RegionalProviderRegistry()


__all__ = [
    "ProviderFactory",
    "RegionalProviderRegistry",
    "TransitRegion",
    "regional_provider_registry",
]
