"""M6 itinerary version diff behavior."""
from __future__ import annotations

from datetime import time
from uuid import UUID

from syncinerary.diff.itinerary_diff import itinerary_diff
from syncinerary.domain.models import ItineraryNode

OLD_VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")
NEW_VERSION_ID = UUID("10000000-0000-0000-0000-000000000002")


def _node(
    candidate: int,
    *,
    version_id: UUID,
    day: int,
    start: time,
    end: time,
) -> ItineraryNode:
    return ItineraryNode(
        id=UUID(f"20000000-0000-0000-0000-{candidate:012d}"),
        version_id=version_id,
        candidate_id=UUID(f"30000000-0000-0000-0000-{candidate:012d}"),
        day=day,
        start_time=start,
        end_time=end,
    )


def test_diff_separates_added_removed_moved_and_time_changes():
    old_nodes = [
        _node(1, version_id=OLD_VERSION_ID, day=0, start=time(9), end=time(10)),
        _node(2, version_id=OLD_VERSION_ID, day=0, start=time(11), end=time(12)),
        _node(3, version_id=OLD_VERSION_ID, day=1, start=time(10), end=time(11)),
    ]
    new_nodes = [
        _node(2, version_id=NEW_VERSION_ID, day=1, start=time(9), end=time(10)),
        _node(3, version_id=NEW_VERSION_ID, day=1, start=time(10, 30), end=time(11, 30)),
        _node(4, version_id=NEW_VERSION_ID, day=1, start=time(13), end=time(14)),
    ]

    result = itinerary_diff(old_nodes, new_nodes)

    assert [item.candidate_id for item in result.added] == [new_nodes[2].candidate_id]
    assert [item.candidate_id for item in result.removed] == [old_nodes[0].candidate_id]
    assert [(item.old_day, item.new_day) for item in result.moved] == [(0, 1)]
    assert [item.candidate_id for item in result.time_changed] == [old_nodes[2].candidate_id]
    assert result.time_changed[0].old_start_time == time(10)
    assert result.time_changed[0].new_start_time == time(10, 30)


def test_diff_is_empty_for_equivalent_versions_with_new_node_ids():
    old = _node(1, version_id=OLD_VERSION_ID, day=2, start=time(14), end=time(15))
    new = _node(1, version_id=NEW_VERSION_ID, day=2, start=time(14), end=time(15))

    result = itinerary_diff([old], [new])

    assert result.added == []
    assert result.removed == []
    assert result.moved == []
    assert result.time_changed == []


def test_diff_output_order_is_deterministic():
    old_nodes = [
        _node(2, version_id=OLD_VERSION_ID, day=1, start=time(11), end=time(12)),
        _node(1, version_id=OLD_VERSION_ID, day=0, start=time(9), end=time(10)),
    ]
    new_nodes = [
        _node(4, version_id=NEW_VERSION_ID, day=2, start=time(15), end=time(16)),
        _node(3, version_id=NEW_VERSION_ID, day=0, start=time(8), end=time(9)),
    ]

    result = itinerary_diff(old_nodes, new_nodes)

    assert [item.day for item in result.removed] == [0, 1]
    assert [item.day for item in result.added] == [0, 2]
