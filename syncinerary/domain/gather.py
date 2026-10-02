"""Durable discovery job and its immutable input snapshot."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from syncinerary.domain.models import Constraint, SourceAttachment, Traveler, Trip


class GatherInput(BaseModel):
    trip: Trip
    travelers: list[Traveler]
    constraints: list[Constraint]
    attachments: list[SourceAttachment]


class GatherRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    credential_account_id: UUID | None = None
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    phase: str = "queued"
    city: str | None = None
    completed_units: int = 0
    total_units: int | None = None
    deck_size: int | None = None
    error_code: str | None = None
    retry_count: int = 0
    input_snapshot: GatherInput
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
