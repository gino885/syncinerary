"""The reviewed city time allocation shared by discovery and scheduling."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncinerary.domain.models import Trip


def validate_city_plan(cities: list[str], days: int, city_days: list[int],
                       priority_city_index: int | None) -> None:
    if priority_city_index is not None and not 0 <= priority_city_index < len(cities):
        raise ValueError("The main city must be one of the selected cities")
    if city_days and (len(city_days) != len(cities) or sum(city_days) != days):
        raise ValueError("City days must match the selected cities and add up to the trip days")


def suggested_city_days(days: int, count: int, priority: int | None = None) -> list[int]:
    if count < 1 or days < count:
        raise ValueError("A trip needs at least one day per city")
    whole, remainder = divmod(days, count)
    result = [whole] * count
    order = list(range(count))
    if priority is not None:
        order.remove(priority)
        order.insert(0, priority)
    for index in order[:remainder]:
        result[index] += 1
    return result


def city_day_counts(trip: Trip) -> list[int]:
    return list(trip.city_days) or suggested_city_days(
        trip.days, len(trip.cities) or 1, trip.priority_city_index,
    )
