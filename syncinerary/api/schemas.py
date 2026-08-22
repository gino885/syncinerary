"""Request and response models for the HTTP surface.

Deliberately separate from domain/models.py. The domain models carry fields
the client has no business seeing or setting (a client must not choose a
trip's uuid, and the swipe deck does not need `enrichment`), and pinning the
wire format here means a domain change cannot silently alter the contract the
iOS app decodes.
"""
from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from syncinerary.config.solver import DEFAULT_DAY_END_HOUR, DEFAULT_DAY_START_HOUR
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    Trip,
    TripStatus,
    Vote,
    WishlistNotPlaced,
)


class TripCreateRequest(BaseModel):
    destination: str = Field(min_length=1, examples=["Hokkaido"])
    start_date: date
    end_date: date
    # M1 has no invite flow, so the creator is the only traveler (§15 keeps
    # auth to a stub). M4 adds the rest of the group.
    creator_name: str = Field(min_length=1, examples=["Gino"])
    creator_home_city: str | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> TripCreateRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class TripOut(BaseModel):
    id: UUID
    destination: str
    start_date: date
    end_date: date
    days: int
    status: TripStatus

    @classmethod
    def of(cls, trip: Trip) -> TripOut:
        return cls(
            id=trip.id,
            destination=trip.destination,
            start_date=trip.start_date,
            end_date=trip.end_date,
            days=trip.days,
            status=trip.status,
        )


class TripCreatedResponse(BaseModel):
    """The traveler_id is the client's identity for every later call.

    There is no auth in M1 (§15), so the client holds on to this and sends it
    when voting. M4 replaces it with a real group membership.
    """

    trip: TripOut
    traveler_id: UUID


class CandidateCardOut(BaseModel):
    """One swipe card. A subset of CandidatePlace: enrichment, sources and
    trending signals are not part of the M1 card."""

    id: UUID
    type: CandidateType
    name_canonical: str
    name_original_lang: str | None
    lat: float
    lng: float
    area: str | None
    address: str | None
    category: str | None
    price_tier: int
    duration_estimate_min: int
    dietary_tags: list[str]

    @classmethod
    def of(cls, candidate: CandidatePlace) -> CandidateCardOut:
        return cls(
            id=candidate.id,
            type=candidate.type,
            name_canonical=candidate.name_canonical,
            name_original_lang=candidate.name_original_lang,
            lat=candidate.lat,
            lng=candidate.lng,
            area=candidate.area,
            address=candidate.address,
            category=candidate.category,
            price_tier=candidate.price_tier,
            duration_estimate_min=candidate.duration_estimate_min,
            dietary_tags=candidate.dietary_tags,
        )


class SwipeSignal(str, Enum):
    """M1 swipe vocabulary: two buttons only (§13 M1).

    Deliberately narrower than domain VoteSignal. like_with_note and
    must_have are real signals that arrive in M4 together with the note
    parser and the long-press gesture; accepting them now would mean storing
    a note nothing parses and a must_have the aggregator ignores.
    """

    LIKE = "like"
    DISLIKE = "dislike"


class VoteRequest(BaseModel):
    traveler_id: UUID
    candidate_id: UUID
    signal: SwipeSignal


class VoteOut(BaseModel):
    id: UUID
    candidate_id: UUID
    traveler_id: UUID
    signal: str

    @classmethod
    def of(cls, vote: Vote) -> VoteOut:
        return cls(
            id=vote.id,
            candidate_id=vote.candidate_id,
            traveler_id=vote.traveler_id,
            signal=vote.signal.value,
        )


class VoteProgressOut(BaseModel):
    """How much of the deck this traveler has swiped."""

    total_candidates: int
    voted: int
    remaining: int


class GatherResponse(BaseModel):
    deck_size: int


class PlanRequest(BaseModel):
    """Optional daily bounds for the user-adjustable planning window."""

    day_start: time = time(DEFAULT_DAY_START_HOUR)
    day_end: time = time(DEFAULT_DAY_END_HOUR)

    @model_validator(mode="after")
    def _check_window(self) -> PlanRequest:
        start = self.day_start.hour * 60 + self.day_start.minute
        end = self.day_end.hour * 60 + self.day_end.minute
        if end <= start:
            raise ValueError("day_end must be after day_start")
        return self


class PlanResponse(BaseModel):
    version_id: UUID
    version_no: int
    placed_stops: int
    narrative: str | None


class ItineraryStopOut(BaseModel):
    candidate_id: UUID
    name: str
    area: str | None
    start_time: time
    end_time: time
    transit_from_prev_min: int
    transit_from_prev_mode: str | None

    @classmethod
    def of(cls, node: ItineraryNode, candidate: CandidatePlace | None) -> ItineraryStopOut:
        return cls(
            candidate_id=node.candidate_id,
            name=candidate.name_canonical if candidate else "Unknown place",
            area=candidate.area if candidate else None,
            start_time=node.start_time,
            end_time=node.end_time,
            transit_from_prev_min=node.transit_from_prev_min,
            transit_from_prev_mode=node.transit_from_prev_mode,
        )


class ItineraryDayOut(BaseModel):
    day: int
    date: date
    stops: list[ItineraryStopOut]


class WishlistNotPlacedOut(BaseModel):
    candidate_id: UUID
    name: str
    reason_code: str
    reason_text: str

    @classmethod
    def of(
        cls,
        item: WishlistNotPlaced,
        candidate: CandidatePlace | None,
    ) -> WishlistNotPlacedOut:
        return cls(
            candidate_id=item.candidate_id,
            name=candidate.name_canonical if candidate else "Unknown place",
            reason_code=item.reason_code,
            reason_text=item.reason_text,
        )


class ItineraryOut(BaseModel):
    version_id: UUID
    version_no: int
    status: ItineraryStatus
    days: list[ItineraryDayOut]
    narrative: str | None
    wishlist_not_placed: list[WishlistNotPlacedOut]


class ErrorOut(BaseModel):
    detail: str | dict[str, Any]
