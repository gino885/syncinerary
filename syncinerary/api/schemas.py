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
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from syncinerary.config.solver import DEFAULT_DAY_END_HOUR, DEFAULT_DAY_START_HOUR
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    SocialPlatform,
    SourceAttachment,
    Traveler,
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


class AttachmentLinkRequest(BaseModel):
    traveler_id: UUID
    url: str = Field(min_length=1, max_length=2048)
    place_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    ] | None = None


class AttachmentContributorOut(BaseModel):
    id: UUID
    name: str


class SourceAttachmentOut(BaseModel):
    id: UUID
    platform: SocialPlatform
    input_type: AttachmentInputType
    status: AttachmentStatus
    original_url: str | None
    canonical_url: str | None
    has_screenshot: bool
    submitted_place_name: str | None
    candidate_id: UUID | None
    contributor: AttachmentContributorOut

    @classmethod
    def of(
        cls,
        attachment: SourceAttachment,
        traveler: Traveler,
    ) -> SourceAttachmentOut:
        return cls(
            id=attachment.id,
            platform=attachment.platform,
            input_type=attachment.input_type,
            status=attachment.status,
            original_url=attachment.original_url,
            canonical_url=attachment.canonical_url,
            has_screenshot=attachment.screenshot_storage_key is not None,
            submitted_place_name=attachment.metadata.get("submitted_place_name"),
            candidate_id=attachment.metadata.get("candidate_id"),
            contributor=AttachmentContributorOut(id=traveler.id, name=traveler.name),
        )


class SourceBadgeKind(str, Enum):
    CLASSIC = "classic"
    TRENDING = "trending"
    ATTACHED_BY_YOU = "attached_by_you"
    ATTACHED_BY_GROUP = "attached_by_group"


class SourceBadgeOut(BaseModel):
    kind: SourceBadgeKind
    label: str
    contributor_name: str | None = None


class CandidateCardOut(BaseModel):
    """One swipe card with display-safe provenance badges."""

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
    source_badges: list[SourceBadgeOut]

    @classmethod
    def of(
        cls,
        candidate: CandidatePlace,
        *,
        viewer_id: UUID | None = None,
        contributor_names: dict[UUID, str] | None = None,
    ) -> CandidateCardOut:
        names = contributor_names or {}
        badges: list[SourceBadgeOut] = []
        if any(source.type == "backbone" for source in candidate.sources):
            badges.append(SourceBadgeOut(kind=SourceBadgeKind.CLASSIC, label="Classic"))
        if any(source.type == "buzz" for source in candidate.sources):
            badges.append(SourceBadgeOut(kind=SourceBadgeKind.TRENDING, label="Trending"))

        contributors = {
            source.by
            for source in candidate.sources
            if source.type == "personal" and source.subtype == "user_paste" and source.by
        }
        for contributor_id in sorted(contributors, key=str):
            contributor_name = names.get(contributor_id)
            is_viewer = contributor_id == viewer_id
            badges.append(
                SourceBadgeOut(
                    kind=(
                        SourceBadgeKind.ATTACHED_BY_YOU
                        if is_viewer
                        else SourceBadgeKind.ATTACHED_BY_GROUP
                    ),
                    label=(
                        "Attached by you"
                        if is_viewer
                        else f"Attached by {contributor_name or 'group'}"
                    ),
                    contributor_name=contributor_name,
                )
            )

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
            source_badges=badges,
        )


class CandidatePhotoAttributionOut(BaseModel):
    display_name: str
    uri: str | None = None
    photo_uri: str | None = None


class CandidatePhotoOut(BaseModel):
    provider: str = "google_places"
    photo_url: str
    width_px: int | None = None
    height_px: int | None = None
    attributions: list[CandidatePhotoAttributionOut] = Field(default_factory=list)


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
    description: str | None
    description_source: str | None
    start_time: time
    end_time: time
    transit_from_prev_min: int
    transit_from_prev_mode: str | None

    @classmethod
    def of(cls, node: ItineraryNode, candidate: CandidatePlace | None) -> ItineraryStopOut:
        description, description_source = _itinerary_description(candidate)
        return cls(
            candidate_id=node.candidate_id,
            name=candidate.name_canonical if candidate else "Unknown place",
            area=candidate.area if candidate else None,
            description=description,
            description_source=description_source,
            start_time=node.start_time,
            end_time=node.end_time,
            transit_from_prev_min=node.transit_from_prev_min,
            transit_from_prev_mode=node.transit_from_prev_mode,
        )


def _itinerary_description(
    candidate: CandidatePlace | None,
) -> tuple[str | None, str | None]:
    if candidate is None:
        return None, None

    raw_description = candidate.enrichment.get("source_description")
    if isinstance(raw_description, str) and raw_description.strip():
        return _brief(raw_description), _description_source(candidate)

    if candidate.type is CandidateType.FOOD:
        description = "A local food stop worth arriving hungry for."
    else:
        descriptions = {
            "historic": "A quick glimpse into the area’s local story.",
            "market": "Come hungry for local flavors and market energy.",
            "museum": "A compact culture stop with a local story.",
            "park": "An easy green pause between busier stops.",
            "shrine": "A peaceful cultural stop worth slowing down for.",
            "viewpoint": "A scenic pause made for taking in the view.",
            "zoo": "A relaxed wildlife stop with plenty to wander.",
        }
        description = descriptions.get(
            candidate.category or "",
            "A local landmark worth slowing down for.",
        )
    return description, _description_source(candidate)


def _description_source(candidate: CandidatePlace) -> str:
    platform = candidate.enrichment.get("platform")
    if platform == "instagram":
        return "Instagram Reel"
    if platform == "tiktok":
        return "TikTok"
    if platform == "rednote":
        return "RedNote"
    if candidate.enrichment.get("google_place_id"):
        return "Google Places"
    if any(source.type == "backbone" for source in candidate.sources):
        return "Travel guides"
    if any(source.type == "buzz" for source in candidate.sources):
        return "Social discovery"
    return "Place details"


def _brief(value: str, limit: int = 120) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    shortened = compact[: limit - 3].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{shortened}..."


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
