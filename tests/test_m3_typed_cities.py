"""Travelers type their own cities, and nothing is hardcoded to Hokkaido.

The prototype used to ship a fixed list of five Hokkaido cities and match
results by looking for the city name, plus its Japanese alias, in the returned
address. Both are gone: a typed name is resolved to a real place, and results
belong to it by distance from that place.
"""
from __future__ import annotations

from datetime import date

import pytest

from syncinerary.agents.gather.cities import (
    MAX_CITIES_PER_TRIP,
    CityOutsideCountry,
    UnknownCity,
    destination_label,
    normalize_city_names,
    resolve_cities,
    search_bias,
)
from syncinerary.domain.models import Trip
from syncinerary.tools.places import CityResolveOutput, ResolvedCity
from syncinerary.tools.places.google_places import (
    DEFAULT_CITY_RADIUS_KM,
    MAX_CITY_RADIUS_KM,
    MIN_CITY_RADIUS_KM,
    PlaceSearchBias,
    _belongs_to_destination,
    _radius_from_viewport,
)


def _city(
    name: str,
    lat: float,
    lng: float,
    radius_km: float = 25.0,
    country: str = "Japan",
    country_code: str | None = None,
) -> ResolvedCity:
    return ResolvedCity(
        query=name,
        place_id=f"city-{name.casefold()}",
        name=name,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        country=country,
        country_code=country_code or {"Japan": "JP", "Portugal": "PT"}.get(country),
    )


# ----- what the traveler typed -----


def test_typed_names_are_trimmed_deduplicated_and_kept_in_order():
    assert normalize_city_names(
        ["  Sapporo ", "Otaru", "sapporo", "", "   "]
    ) == ["Sapporo", "Otaru"]


def test_internal_whitespace_is_collapsed_not_just_trimmed():
    assert normalize_city_names(["New    York"]) == ["New York"]


def test_the_trip_label_is_built_from_the_cities():
    assert destination_label(["Sapporo", "Otaru"]) == "Sapporo, Otaru"


def test_nothing_restricts_the_traveler_to_one_region():
    """Any city name is accepted here; resolution decides if it is real."""
    assert normalize_city_names(["Lisbon", "Porto"]) == ["Lisbon", "Porto"]


# ----- resolution -----


async def test_each_typed_city_is_resolved_to_a_real_place(monkeypatch):
    seen: list[str] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        seen.append(arguments.name)
        return CityResolveOutput(city=_city(arguments.name, 43.06, 141.35, country="Japan"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    resolved = await resolve_cities(["Sapporo", "Otaru"], "Japan")

    assert seen == ["Sapporo", "Otaru"]
    assert [city.name for city in resolved] == ["Sapporo", "Otaru"]


async def test_a_city_that_resolves_to_nothing_is_named_in_the_error(monkeypatch):
    async def fake_run_tool(_tool, _arguments, **_kwargs):
        return CityResolveOutput()

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    with pytest.raises(UnknownCity, match="Zzzqqx"):
        await resolve_cities(["Zzzqqx"], "Japan")


async def test_more_cities_than_a_trip_can_hold_are_rejected(monkeypatch):
    async def fake_run_tool(_tool, arguments, **_kwargs):
        return CityResolveOutput(city=_city(arguments.name, 43.06, 141.35, country="Japan"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    with pytest.raises(ValueError, match=f"at most {MAX_CITIES_PER_TRIP}"):
        await resolve_cities([f"City {index}" for index in range(10)], "Japan")


async def test_an_older_single_destination_trip_still_resolves(monkeypatch):
    """Trips created before the cities column carry only a label."""
    from syncinerary.agents.gather.cities import resolve_trip_cities

    async def fake_run_tool(_tool, arguments, **_kwargs):
        return CityResolveOutput(city=_city(arguments.name, 43.06, 141.35, country="Japan"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)
    trip = Trip(
        destination="Sapporo",
        cities=[],
        country="Japan",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 9, 28),
        days=2,
    )

    assert [city.name for city in await resolve_trip_cities(trip)] == ["Sapporo"]


# ----- scoping by distance, not by name -----


def test_a_place_in_the_city_is_kept_even_with_a_foreign_language_address():
    sapporo = PlaceSearchBias(lat=43.0618, lng=141.3545)
    place = {
        "formattedAddress": "日本、北海道札幌市",
        "location": {"latitude": 43.0605, "longitude": 141.3544},
    }

    assert _belongs_to_destination(place, "Sapporo", city_center=sapporo, city_radius_km=20)


def test_a_famous_place_somewhere_else_is_rejected():
    sapporo = PlaceSearchBias(lat=43.0618, lng=141.3545)
    central_park = {
        "formattedAddress": "New York, NY, USA",
        "location": {"latitude": 40.7829, "longitude": -73.9654},
    }

    assert not _belongs_to_destination(
        central_park, "Sapporo", city_center=sapporo, city_radius_km=20
    )


def test_a_place_just_outside_the_radius_is_rejected():
    sapporo = PlaceSearchBias(lat=43.0618, lng=141.3545)
    otaru = {"location": {"latitude": 43.1987, "longitude": 140.9947}}

    assert not _belongs_to_destination(
        otaru, "Sapporo", city_center=sapporo, city_radius_km=10
    )
    assert _belongs_to_destination(
        otaru, "Sapporo", city_center=sapporo, city_radius_km=40
    )


def test_a_result_with_no_location_cannot_be_placed_in_the_city():
    assert not _belongs_to_destination(
        {"formattedAddress": "Sapporo"},
        "Sapporo",
        city_center=PlaceSearchBias(lat=43.06, lng=141.35),
    )


# ----- city extent -----


def test_a_viewport_becomes_a_clamped_radius():
    radius = _radius_from_viewport(
        {
            "low": {"latitude": 42.95, "longitude": 141.20},
            "high": {"latitude": 43.17, "longitude": 141.50},
        }
    )
    assert MIN_CITY_RADIUS_KM <= radius <= MAX_CITY_RADIUS_KM


def test_a_country_sized_viewport_is_clamped_to_a_city_sized_radius():
    radius = _radius_from_viewport(
        {
            "low": {"latitude": 30.0, "longitude": 128.0},
            "high": {"latitude": 46.0, "longitude": 146.0},
        }
    )
    assert radius == MAX_CITY_RADIUS_KM


def test_a_missing_viewport_falls_back_to_a_default_radius():
    assert _radius_from_viewport({}) == DEFAULT_CITY_RADIUS_KM


def test_the_search_bias_stays_inside_the_provider_limit():
    bias = search_bias(_city("Tokyo", 35.68, 139.76, radius_km=120))
    assert bias.radius_m == 50_000


# ----- one country per trip -----


async def test_a_city_in_another_country_is_rejected_by_name(monkeypatch):
    async def fake_run_tool(_tool, arguments, **_kwargs):
        return CityResolveOutput(city=_city(arguments.name, 38.72, -9.14, country="Portugal"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    with pytest.raises(CityOutsideCountry, match="Portugal"):
        await resolve_cities(["Lisbon"], "Japan")


async def test_the_country_is_sent_with_the_city_so_repeated_names_resolve(monkeypatch):
    seen: list[str | None] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        seen.append(arguments.country)
        return CityResolveOutput(city=_city(arguments.name, 38.72, -9.14, country="Portugal"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    await resolve_cities(["Porto"], "Portugal")

    assert seen == ["Portugal"]


async def test_an_iso_country_code_matches_the_provider_country_name(monkeypatch):
    async def fake_run_tool(_tool, arguments, **_kwargs):
        return CityResolveOutput(city=_city(arguments.name, 35.68, 139.76, country="Japan", country_code="JP"))

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    resolved = await resolve_cities(["Tokyo"], "JP")

    assert [city.name for city in resolved] == ["Tokyo"]


async def test_a_partial_country_name_does_not_match_another_country(monkeypatch):
    async def fake_run_tool(_tool, arguments, **_kwargs):
        return CityResolveOutput(
            city=_city(
                arguments.name,
                1.86,
                9.77,
                country="Equatorial Guinea",
                country_code="GQ",
            )
        )

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    with pytest.raises(CityOutsideCountry, match="Equatorial Guinea"):
        await resolve_cities(["Malabo"], "Guinea")


async def test_an_empty_country_is_refused():
    with pytest.raises(ValueError, match="country"):
        await resolve_cities(["Sapporo"], "   ")


# ----- the destination's own clock -----


async def test_the_timezone_comes_from_the_first_city(monkeypatch):
    from syncinerary.agents.gather.cities import resolve_timezone
    from syncinerary.tools.timezone import TimezoneLookup

    seen: list[tuple[float, float]] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        seen.append((arguments.lat, arguments.lng))
        return TimezoneLookup(timezone="Europe/Lisbon", name="Western European Time")

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    zone = await resolve_timezone(_city("Lisbon", 38.7223, -9.1393, country="Portugal"))

    assert zone == "Europe/Lisbon"
    assert seen == [(38.7223, -9.1393)]


async def test_a_timezone_the_provider_cannot_name_is_rejected(monkeypatch):
    from syncinerary.agents.gather.cities import resolve_timezone
    from syncinerary.tools.timezone import TimezoneLookup, TimezoneUnavailable

    async def fake_run_tool(_tool, _arguments, **_kwargs):
        return TimezoneLookup()

    monkeypatch.setattr("syncinerary.agents.gather.cities.run_tool", fake_run_tool)

    with pytest.raises(TimezoneUnavailable, match="Nowhere"):
        await resolve_timezone(_city("Nowhere", 0.0, 0.0))
