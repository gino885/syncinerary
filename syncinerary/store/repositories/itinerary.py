"""Shortlist and itinerary repositories.

The append-only rule (CLAUDE.md §7) shapes this module. A replan never edits
an existing itinerary_version: it writes a new one pointing at its parent.
So there is no update path for version content or for nodes at all, and the
only mutable field is `status`, which is the lifecycle marker the HITL gate
in §12.2 flips (proposed -> active, prior -> superseded). F4's diff and F2's
replay both read the chain, so an in-place edit anywhere here would quietly
destroy both.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from syncinerary.domain.models import (
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ShortlistState,
    WishlistNotPlaced,
)
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class ShortlistStateRepository(BaseRepository[tables.ShortlistState, ShortlistState]):
    """One row per trip: trip_id is the primary key (§7)."""

    table = tables.ShortlistState
    model = ShortlistState
    jsonb_fields = frozenset(
        {
            "selected_candidate_ids",
            "must_go_candidate_ids",
            "confirmed_by",
            "wishlist_excluded_ids",
        }
    )

    async def get_for_trip(self, trip_id: UUID) -> ShortlistState | None:
        row = await self.session.get(self.table, trip_id)
        return self.to_model(row) if row is not None else None

    async def upsert(self, state: ShortlistState) -> ShortlistState:
        """Write the shortlist, replacing any earlier one for this trip.

        Re-running the shortlist builder for a trip must overwrite rather than
        collide on the primary key. Unlike itinerary_version this table holds
        no history: it is current selection state, and the audit trail lives
        in the version chain.
        """
        values = self.to_row_values(state)
        stmt = (
            pg_insert(tables.ShortlistState)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[tables.ShortlistState.trip_id],
                set_={k: v for k, v in values.items() if k != "trip_id"},
            )
            .returning(tables.ShortlistState)
        )
        row = (await self.session.scalars(stmt)).one()
        return self.to_model(row)

    async def delete_for_trip(self, trip_id: UUID) -> int:
        result = await self.session.execute(
            sa_delete(tables.ShortlistState).where(tables.ShortlistState.trip_id == trip_id)
        )
        return result.rowcount or 0


class ItineraryVersionRepository(BaseRepository[tables.ItineraryVersion, ItineraryVersion]):
    table = tables.ItineraryVersion
    model = ItineraryVersion
    jsonb_fields = frozenset({"objective_breakdown"})

    async def next_version_no(self, trip_id: UUID) -> int:
        """Version numbers start at 1 and never reuse a number."""
        current = await self.session.scalar(
            select(func.max(tables.ItineraryVersion.version_no)).where(
                tables.ItineraryVersion.trip_id == trip_id
            )
        )
        return (current or 0) + 1

    async def list_for_trip(self, trip_id: UUID) -> list[ItineraryVersion]:
        return await self.list_where(
            tables.ItineraryVersion.trip_id == trip_id,
            order_by=tables.ItineraryVersion.version_no,
        )

    async def get_active(self, trip_id: UUID) -> ItineraryVersion | None:
        found = await self.list_where(
            tables.ItineraryVersion.trip_id == trip_id,
            tables.ItineraryVersion.status == ItineraryStatus.ACTIVE,
        )
        return found[0] if found else None

    async def get_latest(self, trip_id: UUID) -> ItineraryVersion | None:
        versions = await self.list_for_trip(trip_id)
        return versions[-1] if versions else None

    async def set_status(
        self, version_id: UUID, status: ItineraryStatus
    ) -> ItineraryVersion | None:
        """The only mutation allowed on a version.

        Status is lifecycle, not content: the HITL gate (§12.2) promotes a
        proposal to active and supersedes its parent. Everything else about a
        version is written once.
        """
        row = await self.session.get(self.table, version_id)
        if row is None:
            return None
        row.status = status
        await self.session.flush()
        return self.to_model(row)


class ItineraryNodeRepository(BaseRepository[tables.ItineraryNode, ItineraryNode]):
    """Append-only. Deliberately exposes no update method."""

    table = tables.ItineraryNode
    model = ItineraryNode
    jsonb_fields = frozenset({"notes_for_travelers"})

    async def list_for_version(self, version_id: UUID) -> list[ItineraryNode]:
        """Whole itinerary in visit order: day, then start time."""
        stmt = (
            select(tables.ItineraryNode)
            .where(tables.ItineraryNode.version_id == version_id)
            .order_by(tables.ItineraryNode.day, tables.ItineraryNode.start_time)
        )
        result = await self.session.scalars(stmt)
        return [self.to_model(row) for row in result.all()]

    async def list_for_day(self, version_id: UUID, day: int) -> list[ItineraryNode]:
        """One day, in visit order.

        Stage 2 runs per day (§11.2), which is what lets F4 replan a single
        day without touching the rest of the trip (§11.3).
        """
        stmt = (
            select(tables.ItineraryNode)
            .where(
                tables.ItineraryNode.version_id == version_id,
                tables.ItineraryNode.day == day,
            )
            .order_by(tables.ItineraryNode.start_time)
        )
        result = await self.session.scalars(stmt)
        return [self.to_model(row) for row in result.all()]


class WishlistNotPlacedRepository(BaseRepository[tables.WishlistNotPlaced, WishlistNotPlaced]):
    """Shortlisted cards the solver could not fit, with reasons (§10.3).

    Composite primary key (version_id, candidate_id), so the id-based helpers
    on the base class do not apply.
    """

    table = tables.WishlistNotPlaced
    model = WishlistNotPlaced

    async def list_for_version(self, version_id: UUID) -> list[WishlistNotPlaced]:
        return await self.list_where(tables.WishlistNotPlaced.version_id == version_id)

    async def delete_for_version(self, version_id: UUID) -> int:
        result = await self.session.execute(
            sa_delete(tables.WishlistNotPlaced).where(
                tables.WishlistNotPlaced.version_id == version_id
            )
        )
        return result.rowcount or 0
