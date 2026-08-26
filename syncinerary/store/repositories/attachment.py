"""Traveler-provided source attachment persistence."""
from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from sqlalchemy import update

from syncinerary.domain.models import AttachmentStatus, SourceAttachment
from syncinerary.store import tables
from syncinerary.store.repositories.base import BaseRepository


class SourceAttachmentRepository(
    BaseRepository[tables.SourceAttachment, SourceAttachment]
):
    table = tables.SourceAttachment
    model = SourceAttachment
    column_aliases: ClassVar[dict[str, str]] = {"metadata": "metadata_json"}
    jsonb_fields = frozenset({"metadata"})

    async def list_for_trip(self, trip_id: UUID) -> list[SourceAttachment]:
        return await self.list_where(
            tables.SourceAttachment.trip_id == trip_id,
            order_by=tables.SourceAttachment.created_at,
        )

    async def record_screenshot(
        self,
        attachment_id: UUID,
        *,
        storage_key: str,
        extracted_text: str,
        metadata: dict,
    ) -> SourceAttachment | None:
        stmt = (
            update(tables.SourceAttachment)
            .where(tables.SourceAttachment.id == attachment_id)
            .values(
                screenshot_storage_key=storage_key,
                extracted_text=extracted_text,
                metadata_json=metadata,
                status=AttachmentStatus.READY,
            )
            .returning(tables.SourceAttachment)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def mark_ready(
        self,
        attachment_id: UUID,
        *,
        metadata: dict,
    ) -> SourceAttachment | None:
        stmt = (
            update(tables.SourceAttachment)
            .where(tables.SourceAttachment.id == attachment_id)
            .values(
                metadata_json=metadata,
                status=AttachmentStatus.READY,
            )
            .returning(tables.SourceAttachment)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None

    async def record_metadata(
        self,
        attachment_id: UUID,
        *,
        metadata: dict,
    ) -> SourceAttachment | None:
        stmt = (
            update(tables.SourceAttachment)
            .where(tables.SourceAttachment.id == attachment_id)
            .values(metadata_json=metadata)
            .returning(tables.SourceAttachment)
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self.to_model(row) if row is not None else None


__all__ = ["SourceAttachmentRepository"]
