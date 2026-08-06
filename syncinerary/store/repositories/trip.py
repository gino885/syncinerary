"""Trip, traveler and trip-level constraint repositories."""
from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from syncinerary.domain.models import Constraint, Traveler, Trip, TripStatus
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class TripRepository(BaseRepository[tables.Trip, Trip]):
    table = tables.Trip
    model = Trip

    async def set_status(self, trip_id: UUID, status: TripStatus) -> Trip | None:
        """Advance the trip through setup -> swiping -> ... (CLAUDE.md §7).

        Trip status is the one mutable piece of trip state; the itinerary
        chain it drives stays append-only.
        """
        row = await self.session.get(self.table, trip_id)
        if row is None:
            return None
        row.status = status
        await self.session.flush()
        return self.to_model(row)


class TravelerRepository(BaseRepository[tables.Traveler, Traveler]):
    table = tables.Traveler
    model = Traveler
    column_aliases: ClassVar[dict[str, str]] = {"profile": "profile_json"}
    jsonb_fields = frozenset({"profile"})

    async def list_for_trip(self, trip_id: UUID) -> list[Traveler]:
        return await self.list_where(
            tables.Traveler.trip_id == trip_id, order_by=tables.Traveler.name
        )

    async def count_for_trip(self, trip_id: UUID) -> int:
        """votes_total in the §10.1 aggregator is the traveler count."""
        return len(await self.list_for_trip(trip_id))


class ConstraintRepository(BaseRepository[tables.TripConstraint, Constraint]):
    """Backed by `trip_constraint`: CONSTRAINT is a Postgres reserved word."""

    table = tables.TripConstraint
    model = Constraint
    column_aliases: ClassVar[dict[str, str]] = {"value": "value_json"}
    jsonb_fields = frozenset({"value"})

    async def list_for_trip(self, trip_id: UUID) -> list[Constraint]:
        """Everything in scope for the trip, group-level and per-traveler."""
        return await self.list_where(
            tables.TripConstraint.trip_id == trip_id,
            order_by=tables.TripConstraint.priority.desc(),
        )

    async def list_group_level(self, trip_id: UUID) -> list[Constraint]:
        """traveler_id IS NULL means the constraint binds the whole group."""
        return await self.list_where(
            tables.TripConstraint.trip_id == trip_id,
            tables.TripConstraint.traveler_id.is_(None),
            order_by=tables.TripConstraint.priority.desc(),
        )

    async def list_for_traveler(self, traveler_id: UUID) -> list[Constraint]:
        return await self.list_where(
            tables.TripConstraint.traveler_id == traveler_id,
            order_by=tables.TripConstraint.priority.desc(),
        )
