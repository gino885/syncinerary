"""Idempotent suggestions and optimistic shared edits."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from syncinerary.domain.checklist import ChecklistItem
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class ChecklistItemRepository(BaseRepository[tables.ChecklistItem, ChecklistItem]):
    table = tables.ChecklistItem
    model = ChecklistItem

    async def suggest(self, items: list[ChecklistItem]) -> None:
        if items:
            await self.session.execute(
                insert(self.table)
                .values([self.to_row_values(item) for item in items])
                .on_conflict_do_nothing(index_elements=["trip_id", "source_key"])
            )
            await self.session.flush()

    async def list_for_trip(self, trip_id: UUID) -> list[ChecklistItem]:
        return await self.list_where(
            self.table.trip_id == trip_id,
            self.table.deleted.is_(False),
            order_by=self.table.created_at,
        )

    async def change(
        self, trip_id: UUID, item_id: UUID, revision: int, **values: object
    ) -> ChecklistItem | None:
        row = await self.session.scalar(
            update(self.table)
            .where(
                self.table.id == item_id,
                self.table.trip_id == trip_id,
                self.table.revision == revision,
                self.table.deleted.is_(False),
            )
            .values(**values, revision=revision + 1)
            .returning(self.table)
            .execution_options(populate_existing=True)
        )
        await self.session.flush()
        return self.to_model(row) if row else None

    async def count_for_trip(self, trip_id: UUID) -> int:
        from sqlalchemy import func

        return (
            await self.session.scalar(
                select(func.count())
                .select_from(self.table)
                .where(self.table.trip_id == trip_id, self.table.deleted.is_(False))
            )
            or 0
        )
