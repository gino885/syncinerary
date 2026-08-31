"""Resolve the cities a traveler typed into real places to search.

A trip used to carry one destination picked from a fixed list, which meant the
supported destinations were whatever someone had hardcoded. Travelers type
their own cities now, so each typed name has to be turned into a real place
before anything is searched: a name nobody can resolve is a typo, not a
destination, and saying so is better than quietly searching somewhere else.

Resolving also gives each city a centre and a radius, which is what scopes
results without a table of local-language aliases per city.
"""
from __future__ import annotations

from syncinerary.domain.models import Trip
from syncinerary.harness import run_tool
from syncinerary.tools.places import (
    CityResolveInput,
    PlaceSearchBias,
    ResolvedCity,
    make_city_resolve_tool,
)
from syncinerary.tools.timezone import (
    TimezoneLookupInput,
    TimezoneUnavailable,
    make_timezone_tool,
)

# More cities than this in one trip and no day has enough time in any of them.
MAX_CITIES_PER_TRIP = 4


class UnknownCity(ValueError):
    """A typed city name did not resolve to a real place."""

    def __init__(self, name: str, country: str) -> None:
        super().__init__(f"No city called {name!r} was found in {country}.")
        self.name = name
        self.country = country


class CityOutsideCountry(ValueError):
    """A typed city resolved somewhere other than the chosen country."""

    def __init__(self, name: str, country: str, found_in: str) -> None:
        super().__init__(
            f"{name!r} is in {found_in}, not {country}. A trip covers one "
            f"country, so pick cities inside it or change the country."
        )
        self.name = name
        self.country = country
        self.found_in = found_in


def normalize_city_names(names: list[str]) -> list[str]:
    """Trim, drop blanks, and remove repeats while keeping the typed order."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names:
        trimmed = " ".join(name.split())
        if not trimmed:
            continue
        key = trimmed.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(trimmed)
    return cleaned


def destination_label(cities: list[str]) -> str:
    """The human label for a trip covering these cities."""
    return ", ".join(cities)


def _same_country(city: ResolvedCity, country: str) -> bool:
    """Compare against both the country name and its ISO code.

    Travelers type "Japan", "japan", or "JP", and Google answers with its own
    spelling, so neither side can be trusted to match exactly.
    """
    wanted = country.strip().casefold()
    candidates = {
        value.casefold()
        for value in (city.country, city.country_code)
        if value
    }
    return wanted in candidates


async def resolve_cities(
    names: list[str],
    country: str | None,
) -> list[ResolvedCity]:
    """Resolve each typed name, inside one country when one is given.

    A trip stays in one country. Beyond keeping the day plan honest, it is what
    makes the country usable as a disambiguator: many city names repeat around
    the world, and "the one in Portugal" resolves them.

    `None` means the trip predates the country field and its cities are taken
    wherever they resolve. An empty string is a caller mistake, not a trip
    without a country, so it is refused.
    """
    if country is not None:
        country = country.strip()
        if not country:
            raise ValueError("country cannot be empty")

    normalized = normalize_city_names(names)
    if len(normalized) > MAX_CITIES_PER_TRIP:
        raise ValueError(f"A trip can include at most {MAX_CITIES_PER_TRIP} cities")

    resolved: list[ResolvedCity] = []
    for name in normalized:
        result = await run_tool(
            make_city_resolve_tool(),
            CityResolveInput(name=name, country=country),
            state={"node": "gather_city_resolve", "name": name},
        )
        if result.city is None:
            raise UnknownCity(name, country or "any country")
        if country is not None and not _same_country(result.city, country):
            raise CityOutsideCountry(
                name,
                country,
                result.city.country or "another country",
            )
        resolved.append(result.city)
    return resolved


async def resolve_timezone(city: ResolvedCity) -> str:
    """The destination's IANA zone, from the first city the trip covers."""
    result = await run_tool(
        make_timezone_tool(),
        TimezoneLookupInput(lat=city.lat, lng=city.lng),
        state={"node": "trip_timezone", "city": city.name},
    )
    if result.timezone is None:
        raise TimezoneUnavailable(f"No timezone was found for {city.name}")
    return result.timezone


def trip_cities(trip: Trip) -> list[ResolvedCity]:
    """The trip's cities as resolved when it was created.

    Resolution happens once, at trip creation, so gather never repeats it and
    a bad city name fails at the form instead of part-way through a search.
    """
    return [ResolvedCity.model_validate(city) for city in trip.resolved_cities]


async def resolve_trip_cities(trip: Trip) -> list[ResolvedCity]:
    """Stored geometry when present, resolving older trips on demand."""
    stored = trip_cities(trip)
    if stored:
        return stored
    names = trip.cities or [trip.destination]
    return await resolve_cities(names, trip.country)


def search_bias(city: ResolvedCity) -> PlaceSearchBias:
    """A search bias covering the city, within the provider's radius limit."""
    return PlaceSearchBias(
        lat=city.lat,
        lng=city.lng,
        radius_m=min(50_000.0, city.radius_km * 1000),
    )


__all__ = [
    "MAX_CITIES_PER_TRIP",
    "CityOutsideCountry",
    "UnknownCity",
    "destination_label",
    "normalize_city_names",
    "resolve_cities",
    "resolve_timezone",
    "resolve_trip_cities",
    "search_bias",
    "trip_cities",
]
