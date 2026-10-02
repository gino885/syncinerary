"""Atomic start, immutable inputs, and durable worker ownership."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import and_, or_, select, text, update

from syncinerary.domain.gather import GatherInput, GatherRun
from syncinerary.domain.models import TripStatus
from syncinerary.store import tables
from syncinerary.store.db import init_engine
from syncinerary.store.repositories.attachment import SourceAttachmentRepository
from syncinerary.store.repositories.base import BaseRepository
from syncinerary.store.repositories.trip import ConstraintRepository, TravelerRepository


class GatherRunRepository(BaseRepository[tables.GatherRun, GatherRun]):
    table = tables.GatherRun
    model = GatherRun
    jsonb_fields = frozenset({"input_snapshot"})

    async def current(self, trip_id: UUID) -> GatherRun | None:
        row = await self.session.scalar(
            select(self.table)
            .where(
                self.table.trip_id == trip_id,
            )
            .order_by(self.table.created_at.desc())
            .limit(1)
        )
        return self.to_model(row) if row else None

    async def start(self, trip_id: UUID, leader_id: UUID) -> GatherRun:
        # All start requests serialize on the trip, including the zero-run case.
        # This lock lasts only until the request commits, never during discovery.
        trip = await self.session.scalar(
            select(tables.Trip)
            .where(
                tables.Trip.id == trip_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if trip is None or trip.created_by != leader_id:
            raise PermissionError("Only the trip leader may start discovery")
        existing = await self.current(trip_id)
        if existing:
            trace.get_current_span().add_event(
                "gather.start_coalesced", {"trip_id": str(trip_id), "run_id": str(existing.id)}
            )
            if existing.status == "failed" and existing.retry_count < 2:
                return await self.change(
                    existing.id,
                    status="queued",
                    error_code=None,
                    retry_count=existing.retry_count + 1,
                )
            return existing
        if trip.status not in {TripStatus.DRAFT, TripStatus.SETUP}:
            raise ValueError("Discovery has already started for this trip")
        from syncinerary.store.repositories.trip import TripRepository

        snapshot = GatherInput(
            trip=TripRepository.to_model(trip),
            travelers=await TravelerRepository(self.session).list_for_trip(trip_id),
            constraints=await ConstraintRepository(self.session).list_for_trip(trip_id),
            attachments=await SourceAttachmentRepository(self.session).list_for_trip(trip_id),
        )
        leader = await self.session.get(tables.Traveler, leader_id)
        run = await self.add(
            GatherRun(
                trip_id=trip_id,
                credential_account_id=leader.account_id if leader else None,
                input_snapshot=snapshot,
            )
        )
        trace.get_current_span().set_attribute(
            "gather.preparation_seconds", (datetime.now(UTC) - trip.created_at).total_seconds()
        )
        trip.status = TripStatus.GATHERING
        await self.session.flush()
        return run

    async def pending(self, limit: int = 32) -> list[GatherRun]:
        rows = await self.session.scalars(
            select(self.table)
            .where(
                or_(
                    self.table.status == "queued",
                    and_(
                        self.table.status == "running",
                        self.table.updated_at < datetime.now(UTC) - timedelta(seconds=60),
                    ),
                ),
            )
            .order_by(self.table.updated_at)
            .limit(limit)
        )
        return [self.to_model(row) for row in rows]

    async def change(self, run_id: UUID, *, only_status: str | None = None, **fields) -> GatherRun:
        if "input_snapshot" in fields:
            raise ValueError("Gather inputs are immutable")
        statement = update(self.table).where(self.table.id == run_id)
        if only_status is not None:
            statement = statement.where(self.table.status == only_status)
        row = (
            await self.session.scalars(
                statement.values(
                    **fields,
                    updated_at=datetime.now(UTC),
                ).returning(self.table)
            )
        ).one_or_none()
        return self.to_model(row) if row else await self.get(run_id)


@asynccontextmanager
async def own_gather(trip_id: UUID):
    """Session advisory lock on a dedicated connection, with no open transaction.

    A heartbeat never steals ownership from a slow worker. Process exit releases
    the lock; another worker can then resume the same running record. The caller
    probes this connection while working and cancels work if ownership is lost.
    """
    key = int.from_bytes(trip_id.bytes[:8], "big", signed=True)
    async with init_engine().connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        await connection.commit()
        try:
            yield connection if acquired else None
        finally:
            if acquired and not connection.invalidated:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                await connection.commit()


async def check_ownership(connection):
    await connection.execute(text("SELECT 1"))
    await connection.commit()
