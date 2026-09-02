"""Compare two append-only itinerary versions by candidate identity."""
from __future__ import annotations

from datetime import time
from uuid import UUID

from pydantic import BaseModel, Field

from syncinerary.domain.models import ItineraryNode


class ItineraryDiffStop(BaseModel):
    candidate_id: UUID
    node_id: UUID
    day: int
    start_time: time
    end_time: time


class ItineraryMove(BaseModel):
    candidate_id: UUID
    old_node_id: UUID
    new_node_id: UUID
    old_day: int
    new_day: int
    old_start_time: time
    new_start_time: time


class ItineraryTimeChange(BaseModel):
    candidate_id: UUID
    old_node_id: UUID
    new_node_id: UUID
    day: int
    old_start_time: time
    old_end_time: time
    new_start_time: time
    new_end_time: time


class ItineraryDiff(BaseModel):
    added: list[ItineraryDiffStop] = Field(default_factory=list)
    removed: list[ItineraryDiffStop] = Field(default_factory=list)
    moved: list[ItineraryMove] = Field(default_factory=list)
    time_changed: list[ItineraryTimeChange] = Field(default_factory=list)


def _stop(node: ItineraryNode) -> ItineraryDiffStop:
    return ItineraryDiffStop(
        candidate_id=node.candidate_id,
        node_id=node.id,
        day=node.day,
        start_time=node.start_time,
        end_time=node.end_time,
    )


def _node_order(node: ItineraryNode) -> tuple[int, time, str]:
    return node.day, node.start_time, str(node.candidate_id)


def itinerary_diff(
    old_nodes: list[ItineraryNode],
    new_nodes: list[ItineraryNode],
) -> ItineraryDiff:
    """Return stable, mutually exclusive changes between two versions.

    Node IDs change with every append-only version, so candidate identity is
    the durable comparison key. A day change is reported as moved; a time
    change is reported separately only when the candidate stays on its day.
    """
    old_by_candidate = {node.candidate_id: node for node in old_nodes}
    new_by_candidate = {node.candidate_id: node for node in new_nodes}

    removed = [
        _stop(old_by_candidate[candidate_id])
        for candidate_id in old_by_candidate.keys() - new_by_candidate.keys()
    ]
    added = [
        _stop(new_by_candidate[candidate_id])
        for candidate_id in new_by_candidate.keys() - old_by_candidate.keys()
    ]

    moved: list[ItineraryMove] = []
    time_changed: list[ItineraryTimeChange] = []
    for candidate_id in old_by_candidate.keys() & new_by_candidate.keys():
        old = old_by_candidate[candidate_id]
        new = new_by_candidate[candidate_id]
        if old.day != new.day:
            moved.append(
                ItineraryMove(
                    candidate_id=candidate_id,
                    old_node_id=old.id,
                    new_node_id=new.id,
                    old_day=old.day,
                    new_day=new.day,
                    old_start_time=old.start_time,
                    new_start_time=new.start_time,
                )
            )
        elif old.start_time != new.start_time or old.end_time != new.end_time:
            time_changed.append(
                ItineraryTimeChange(
                    candidate_id=candidate_id,
                    old_node_id=old.id,
                    new_node_id=new.id,
                    day=old.day,
                    old_start_time=old.start_time,
                    old_end_time=old.end_time,
                    new_start_time=new.start_time,
                    new_end_time=new.end_time,
                )
            )

    removed.sort(key=lambda item: (item.day, item.start_time, str(item.candidate_id)))
    added.sort(key=lambda item: (item.day, item.start_time, str(item.candidate_id)))
    moved.sort(key=lambda item: (item.old_day, item.old_start_time, str(item.candidate_id)))
    time_changed.sort(key=lambda item: (item.day, item.old_start_time, str(item.candidate_id)))
    return ItineraryDiff(
        added=added,
        removed=removed,
        moved=moved,
        time_changed=time_changed,
    )


__all__ = [
    "ItineraryDiff",
    "ItineraryDiffStop",
    "ItineraryMove",
    "ItineraryTimeChange",
    "itinerary_diff",
]
