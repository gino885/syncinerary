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

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from syncinerary.agents.gather.cities import MAX_CITIES_PER_TRIP
from syncinerary.agents.gather.dietary import dietary_notice
from syncinerary.config.solver import (
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    MEAL_WINDOWS,
)
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    CandidatePlace,
    CandidateType,
    Constraint,
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

ProfileValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]


class TripCreateRequest(BaseModel):
    # One country per trip. It disambiguates repeated city names and keeps the
    # day plan to distances a traveler can actually cover.
    country: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ]
    # The cities the traveler typed, in order. There is no supported-city list:
    # each name is resolved against the places provider when the trip is created, and
    # one that resolves to nothing comes back as a 422 naming it.
    cities: list[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
        ]
    ] = Field(min_length=1, max_length=MAX_CITIES_PER_TRIP)
    start_date: date
    end_date: date
    # M1 has no invite flow, so the creator is the only traveler (§15 keeps
    # auth to a stub). M4 adds the rest of the group.
    creator_name: str = Field(min_length=1, examples=["Gino"])
    creator_home_city: str | None = None
    creator_interests: list[ProfileValue] = Field(default_factory=list, max_length=12)
    creator_dietary_excludes: list[ProfileValue] = Field(default_factory=list, max_length=12)

    @field_validator("creator_interests", "creator_dietary_excludes")
    @classmethod
    def _clean_profile_values(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
        return cleaned

    @model_validator(mode="after")
    def _check_dates(self) -> TripCreateRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class TripOut(BaseModel):
    id: UUID
    destination: str
    cities: list[str]
    country: str | None
    timezone: str | None
    start_date: date
    end_date: date
    days: int
    status: TripStatus

    @classmethod
    def of(cls, trip: Trip) -> TripOut:
        return cls(
            id=trip.id,
            destination=trip.destination,
            cities=trip.cities or [trip.destination],
            country=trip.country,
            timezone=trip.timezone,
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
    DISCOVERED = "discovered"
    ATTACHED_BY_YOU = "attached_by_you"
    ATTACHED_BY_GROUP = "attached_by_group"


class SourceBadgeOut(BaseModel):
    kind: SourceBadgeKind
    label: str
    contributor_name: str | None = None


PLATFORM_LABELS = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "rednote": "RedNote",
}


def source_badges(
    candidate: CandidatePlace,
    *,
    viewer_id: UUID | None = None,
    contributor_names: dict[UUID, str] | None = None,
) -> list[SourceBadgeOut]:
    """Where this place came from, in the order it entered the pool.

    Shared by the swipe deck and the itinerary. The itinerary needs it for the
    same reason the deck does: "why is this on my trip" is the first question a
    traveler asks, and the answer is provenance, not the blurb underneath.
    """
    names = contributor_names or {}
    badges: list[SourceBadgeOut] = []

    if any(source.type == "backbone" for source in candidate.sources):
        badges.append(SourceBadgeOut(kind=SourceBadgeKind.CLASSIC, label="Classic"))

    if any(source.type == "buzz" for source in candidate.sources):
        platforms = candidate.enrichment.get("social_platforms")
        named = [
            PLATFORM_LABELS[platform]
            for platform in platforms
            if platform in PLATFORM_LABELS
        ] if isinstance(platforms, list) else []
        badges.append(
            SourceBadgeOut(
                kind=SourceBadgeKind.TRENDING,
                label=(
                    f"Trending on {', '.join(named)}" if named else "Trending"
                ),
            )
        )

    if any(source.type == "discovery" for source in candidate.sources):
        badges.append(
            SourceBadgeOut(
                kind=SourceBadgeKind.DISCOVERED,
                label="Found on Google Maps",
            )
        )

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
    return badges


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
    dietary_notice: str | None
    source_badges: list[SourceBadgeOut]

    @classmethod
    def of(
        cls,
        candidate: CandidatePlace,
        *,
        viewer_id: UUID | None = None,
        contributor_names: dict[UUID, str] | None = None,
        constraints: list[Constraint] | None = None,
    ) -> CandidateCardOut:
        badges = source_badges(
            candidate,
            viewer_id=viewer_id,
            contributor_names=contributor_names,
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
            dietary_notice=dietary_notice(candidate, constraints or []),
            source_badges=badges,
        )


class LodgingOptionOut(BaseModel):
    candidate_id: UUID
    name: str
    area: str | None
    address: str | None
    price_tier: int
    trip_start_date: date
    trip_end_date: date
    availability_note: str = (
        "Room availability is not verified. Confirm dates with the hotel before booking."
    )

    @classmethod
    def of(cls, candidate: CandidatePlace, trip: Trip) -> LodgingOptionOut:
        return cls(
            candidate_id=candidate.id,
            name=candidate.name_canonical,
            area=candidate.area,
            address=candidate.address,
            price_tier=candidate.price_tier,
            trip_start_date=trip.start_date,
            trip_end_date=trip.end_date,
        )


class LodgingSelectionRequest(BaseModel):
    traveler_id: UUID
    candidate_id: UUID


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
    meal_slot: str | None
    source_badges: list[SourceBadgeOut]

    @classmethod
    def of(
        cls,
        node: ItineraryNode,
        candidate: CandidatePlace | None,
        *,
        viewer_id: UUID | None = None,
        contributor_names: dict[UUID, str] | None = None,
    ) -> ItineraryStopOut:
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
            meal_slot=_meal_slot(candidate, node.start_time),
            source_badges=(
                source_badges(
                    candidate,
                    viewer_id=viewer_id,
                    contributor_names=contributor_names,
                )
                if candidate
                else []
            ),
        )


def _meal_slot(candidate: CandidatePlace | None, start_time: time) -> str | None:
    """Which meal a food stop fills, read back from the time the solver chose.

    The solver already constrains food stops to a meal window, so the label is
    derived here rather than stored: itinerary_node is append-only (CLAUDE.md
    section 7) and a new column would be a migration for a value that is a
    function of two columns already present.
    """
    if candidate is None or candidate.type is not CandidateType.FOOD:
        return None
    minute = start_time.hour * 60 + start_time.minute
    for name, (start_hour, end_hour) in MEAL_WINDOWS.items():
        if start_hour * 60 <= minute < end_hour * 60:
            return name
    return None


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
