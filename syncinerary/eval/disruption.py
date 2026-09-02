"""One injector per F4 trigger type (CLAUDE.md section 12.3).

A fixture says which stop is hit in fixture terms ("day 0, the second stop").
These injectors resolve that against a seeded itinerary's real node ids and
produce the `trigger_payload` the rescue agent expects. Keeping the fixture
in positional terms is what lets the same fixture survive a solver change:
the disruption stays "whatever the group was doing second that morning"
rather than a uuid that stopped existing.
"""
from __future__ import annotations

from datetime import time
from typing import Any

from syncinerary.domain.models import ItineraryNode, ReplanTrigger
from syncinerary.eval.fixtures import DisruptionSpec


class DisruptionNotApplicable(RuntimeError):
    """The seeded itinerary has no stop matching what the fixture describes."""


def _stops_on_day(nodes: list[ItineraryNode], day: int) -> list[ItineraryNode]:
    return sorted(
        (node for node in nodes if node.day == day),
        key=lambda node: (node.start_time, str(node.id)),
    )


def target_node(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> ItineraryNode:
    """The stop the fixture points at, by position within its day."""
    stops = _stops_on_day(nodes, spec.day)
    if not stops:
        raise DisruptionNotApplicable(f"No stops scheduled on day {spec.day}")
    if spec.stop_index >= len(stops):
        raise DisruptionNotApplicable(
            f"Day {spec.day} has {len(stops)} stops; the fixture asks for index {spec.stop_index}"
        )
    return stops[spec.stop_index]


def _parse_clock(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


def inject_reservation_cancelled(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    return {"node_id": str(target_node(spec, nodes).id)}


def inject_place_closed(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    return {"node_id": str(target_node(spec, nodes).id)}


def inject_transit_delay(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    return {
        "node_id": str(target_node(spec, nodes).id),
        "delay_minutes": spec.delay_minutes or 30,
    }


def inject_overslept(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    """Everything before the group actually got up is affected.

    The fixture gives a clock time. If that time is early enough that nothing
    was missed, the fixture is not testing anything, so this raises rather
    than producing a disruption the rescue agent will reject as empty.
    """
    started = _parse_clock(spec.at) if spec.at else time(11)
    stops = _stops_on_day(nodes, spec.day)
    if not any(node.start_time < started for node in stops):
        raise DisruptionNotApplicable(
            f"Nothing on day {spec.day} starts before {started.isoformat(timespec='minutes')}"
        )
    return {"day": spec.day, "at": started.isoformat(timespec="minutes")}


def inject_weather(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    return {"day": spec.day}


def inject_other(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> dict[str, Any]:
    return {"affected_node_ids": [str(target_node(spec, nodes).id)]}


INJECTORS = {
    ReplanTrigger.RESERVATION_CANCELLED: inject_reservation_cancelled,
    ReplanTrigger.TRANSIT_DELAY: inject_transit_delay,
    ReplanTrigger.OVERSLEPT: inject_overslept,
    ReplanTrigger.PLACE_CLOSED: inject_place_closed,
    ReplanTrigger.WEATHER: inject_weather,
    ReplanTrigger.OTHER: inject_other,
}


def inject(spec: DisruptionSpec, nodes: list[ItineraryNode]) -> tuple[ReplanTrigger, dict[str, Any]]:
    """Turn a fixture's disruption block into a real trigger and payload."""
    trigger = ReplanTrigger(spec.trigger)
    return trigger, INJECTORS[trigger](spec, nodes)


__all__ = [
    "INJECTORS",
    "DisruptionNotApplicable",
    "inject",
    "inject_other",
    "inject_overslept",
    "inject_place_closed",
    "inject_reservation_cancelled",
    "inject_transit_delay",
    "inject_weather",
    "target_node",
]
