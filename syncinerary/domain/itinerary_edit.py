"""Exact user choices, separate from natural-language revision preferences."""

from datetime import time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from syncinerary.config.schedule import validate_clock


class EditedStop(BaseModel):
    candidate_id: UUID
    day: int = Field(ge=0, strict=True)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def valid_times(self):
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("Use local clock times without a timezone offset")
        validate_clock(self.start_time)
        validate_clock(self.end_time)
        if self.end_time <= self.start_time:
            raise ValueError("The visit must finish after it starts")
        return self


class ItineraryEdit(BaseModel):
    traveler_id: UUID
    base_version_id: UUID
    stops: list[EditedStop] = Field(max_length=200)
    adjust_days: list[Annotated[int, Field(strict=True, ge=0)]] = Field(
        default_factory=list, max_length=31
    )

    @model_validator(mode="after")
    def unique_stops(self):
        if len({s.candidate_id for s in self.stops}) != len(self.stops):
            raise ValueError("A place can appear only once in the itinerary")
        if any(day < 0 for day in self.adjust_days):
            raise ValueError("Choose a valid day to adjust")
        return self
