"""Trip, traveler and trip-level constraint repositories."""
from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from sqlalchemy import select

from syncinerary.domain.models import (
    Constraint,
    ConstraintKind,
    Traveler,
    Trip,
    TripStatus,
)
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class TripRepository(BaseRepository[tables.Trip, Trip]):
    table = tables.Trip
    model = Trip
    jsonb_fields = frozenset({"resolved_cities"})

    async def set_created_by(self, trip_id: UUID, traveler_id: UUID) -> Trip | None:
        """Set the creator after the traveler row exists.

        Two statements rather than one because trip.created_by points at a
        traveler and traveler.trip_id points back: neither row can be written
        with the other's id already in hand.
        """
        row = await self.session.get(self.table, trip_id)
        if row is None:
            return None
        row.created_by = traveler_id
        await self.session.flush()
        return self.to_model(row)

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

    async def list_for_account(self, account_id: UUID) -> list[Traveler]:
        """Every trip this person is on, as their per-trip traveler rows."""
        return await self.list_where(
            tables.Traveler.account_id == account_id,
            order_by=tables.Traveler.name,
        )

    async def find_for_account_on_trip(
        self,
        *,
        trip_id: UUID,
        account_id: UUID,
    ) -> Traveler | None:
        """Whether this account already joined, so a re-opened invite link is
        idempotent instead of hitting the unique constraint."""
        found = await self.list_where(
            tables.Traveler.trip_id == trip_id,
            tables.Traveler.account_id == account_id,
        )
        return found[0] if found else None


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

    async def set_group_constraint(
        self,
        trip_id: UUID,
        *,
        constraint_type: str,
        value: dict,
        priority: int,
        kind: ConstraintKind,
    ) -> Constraint:
        """Idempotently set one group-level choice such as lodging."""
        row = await self.session.scalar(
            select(tables.TripConstraint).where(
                tables.TripConstraint.trip_id == trip_id,
                tables.TripConstraint.traveler_id.is_(None),
                tables.TripConstraint.type == constraint_type,
            )
        )
        if row is None:
            return await self.add(
                Constraint(
                    trip_id=trip_id,
                    type=constraint_type,
                    value=value,
                    priority=priority,
                    kind=kind,
                )
            )
        row.value_json = value
        row.priority = priority
        row.kind = kind
        await self.session.flush()
        return self.to_model(row)
