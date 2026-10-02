"""Shared trip preparation tasks, independent of immutable itinerary versions."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChecklistItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)
    completed: bool = False
    source_key: str | None = None
    deleted: bool = False
    revision: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
