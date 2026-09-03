"""Request and response models for the HTTP surface.

Deliberately separate from domain/models.py. The domain models carry fields
the client has no business seeing or setting (a client must not choose a
trip's uuid, and the swipe deck does not need `enrichment`), and pinning the
wire format here means a domain change cannot silently alter the contract the
iOS app decodes.
"""
from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from syncinerary.agents.gather.cities import MAX_CITIES_PER_TRIP
from syncinerary.agents.gather.dietary import dietary_notice
from syncinerary.config.solver import (
    DEFAULT_DAY_END_HOUR,
    DEFAULT_DAY_START_HOUR,
    MEAL_WINDOWS,
)
from syncinerary.diff.itinerary_diff import ItineraryDiff
from syncinerary.domain.models import (
    Account,
    AttachmentInputType,
    AttachmentStatus,
    CandidateBadge,
    CandidatePlace,
    CandidateType,
    Constraint,
    ItineraryNode,
    ItineraryStatus,
    ReplanStatus,
    ReplanTrigger,
    SocialPlatform,
    SourceAttachment,
    Traveler,
    Trip,
    TripInvite,
    TripMessage,
    TripMessageKind,
    TripStatus,
    Vote,
    WishlistNotPlaced,
)
from syncinerary.tools.fetch.social import SocialReferenceKind, normalize_social_url

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
    # New clients send the Google prediction they selected. Older clients may
    # omit this and keep the text-resolution path during the transition.
    city_place_ids: list[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
        ]
    ] = Field(default_factory=list, max_length=MAX_CITIES_PER_TRIP)
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
        if self.city_place_ids and len(self.city_place_ids) != len(self.cities):
            raise ValueError("city_place_ids must match cities")
        return self


class CitySuggestionOut(BaseModel):
    place_id: str
    name: str
    subtitle: str | None = None


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


class AccountOut(BaseModel):
    id: UUID
    display_name: str
    handle: str

    @classmethod
    def of(cls, account: Account) -> AccountOut:
        return cls(
            id=account.id,
            display_name=account.display_name,
            handle=account.handle,
        )


class SignInRequest(BaseModel):
    """Stub sign-in: the handle is the whole credential (CLAUDE.md §15)."""

    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]
    handle: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=30)
    ]


class SignInResponse(BaseModel):
    token: str
    expires_at: datetime
    account: AccountOut


class TripSummaryOut(BaseModel):
    """One row in the trip list, with this account's traveler id on it."""

    id: UUID
    destination: str
    start_date: date
    end_date: date
    days: int
    status: TripStatus
    traveler_id: UUID
    member_count: int

    @classmethod
    def of(cls, trip: Trip, *, traveler_id: UUID, member_count: int) -> TripSummaryOut:
        return cls(
            id=trip.id,
            destination=trip.destination,
            start_date=trip.start_date,
            end_date=trip.end_date,
            days=trip.days,
            status=trip.status,
            traveler_id=traveler_id,
            member_count=member_count,
        )


class InviteCreateRequest(BaseModel):
    max_uses: Annotated[int, Field(ge=1, le=50)] = 20


class InviteOut(BaseModel):
    code: str
    expires_at: datetime
    max_uses: int
    uses: int
    revoked: bool

    @classmethod
    def of(cls, invite: TripInvite) -> InviteOut:
        return cls(
            code=invite.code,
            expires_at=invite.expires_at,
            max_uses=invite.max_uses,
            uses=invite.uses,
            revoked=invite.revoked_at is not None,
        )


class InvitePreviewOut(BaseModel):
    """What a person sees before joining, so they know what they are entering.

    Deliberately not the candidate pool or the thread: an invite code is
    shareable, so this must not leak trip content to whoever holds it.
    """

    trip: TripOut
    member_names: list[str]
    usable: bool
    reason: str | None = None


class JoinTripRequest(BaseModel):
    """Preference tags are required, not optional.

    A member with an empty profile contributes nothing to interest_fit and
    therefore nothing to the For You lane, so an optional field would quietly
    degrade the feature the group thread exists to feed.
    """

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ] | None = None
    preference_tags: Annotated[list[str], Field(min_length=1, max_length=20)]
    home_city: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ] | None = None


class JoinTripResponse(BaseModel):
    trip: TripOut
    traveler_id: UUID
    already_member: bool


class MessageLinkOut(BaseModel):
    """The unfurled card for a pasted post.

    Every mainstream chat product turns a bare URL into a card, and this app
    has more to say than most: the post became a place, or it needs a name
    before it can. A raw URL in the thread hides the one thing the product
    claims to do.
    """

    attachment_id: UUID
    platform: SocialPlatform
    status: AttachmentStatus
    url: str | None
    # Present once the link resolved into a candidate.
    place_name: str | None = None
    candidate_id: UUID | None = None
    photo_url: str | None = None
    # Present when it could not: the client turns this into an inline repair.
    failure_reason: str | None = None

    @classmethod
    def of(
        cls,
        attachment: SourceAttachment,
        *,
        candidate: CandidatePlace | None,
    ) -> MessageLinkOut:
        return cls(
            attachment_id=attachment.id,
            platform=attachment.platform,
            status=attachment.status,
            url=attachment.canonical_url,
            place_name=candidate.name_canonical if candidate else None,
            candidate_id=candidate.id if candidate else None,
            photo_url=(
                candidate.enrichment.get("platform_preview_url") if candidate else None
            ),
            failure_reason=attachment.metadata.get("failure_reason"),
        )


class TripMessageOut(BaseModel):
    id: UUID
    trip_id: UUID
    traveler_id: UUID | None
    author_name: str | None
    body: str
    kind: TripMessageKind
    link_attachment_id: UUID | None
    link: MessageLinkOut | None = None
    created_at: datetime

    @classmethod
    def of(
        cls,
        message: TripMessage,
        *,
        author_name: str | None,
        link: MessageLinkOut | None = None,
    ) -> TripMessageOut:
        return cls(
            id=message.id,
            trip_id=message.trip_id,
            traveler_id=message.traveler_id,
            author_name=author_name,
            body=message.body,
            kind=message.kind,
            link_attachment_id=message.link_attachment_id,
            link=link,
            created_at=message.created_at,
        )


class NamePlaceRequest(BaseModel):
    place_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]


class PostMessageRequest(BaseModel):
    body: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]


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
    # Why a failed attachment failed. The client uses this to ask for a place
    # name instead of showing a dead card with no way forward.
    failure_reason: str | None
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
            failure_reason=attachment.metadata.get("failure_reason"),
            contributor=AttachmentContributorOut(id=traveler.id, name=traveler.name),
        )


class SourceBadgeKind(str, Enum):
    CLASSIC = "classic"
    TRENDING = "trending"
    SOCIAL = "social"
    DISCOVERED = "discovered"
    ATTACHED_BY_YOU = "attached_by_you"
    ATTACHED_BY_GROUP = "attached_by_group"


class SourceBadgeOut(BaseModel):
    kind: SourceBadgeKind
    label: str
    contributor_name: str | None = None
    # CLAUDE.md section 8.5, source links. A badge whose provenance has a
    # public URL carries it here and the client renders a link; a badge
    # without one stays plain text. Never a search page, never synthesized.
    url: str | None = None
    platform: str | None = None


class SourcePostOut(BaseModel):
    """One post behind a card, so the badge count can be checked against it."""

    platform: str
    label: str
    url: str
    author_name: str | None = None
    highlight: str | None = None


PLATFORM_LABELS = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "rednote": "RedNote",
}
GOOGLE_MAPS_LABEL = "Google Maps"


def _linkable_social_url(value: object) -> str | None:
    """Only a URL the social parser accepts is linkable (section 8.5).

    Re-normalizing at output time means a row that somehow holds a tracking
    link or an unsupported host renders with no link rather than a bad one.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        reference = normalize_social_url(value)
    except ValueError:
        return None
    # A discovery page is a search, and section 8.5 never links to a search
    # page in place of a post.
    if reference.kind is SocialReferenceKind.SEARCH:
        return None
    return reference.canonical_url


def _post_out(
    url_value: object,
    platform_value: object,
    *,
    author_name: object = None,
    highlight: object = None,
) -> SourcePostOut | None:
    url = _linkable_social_url(url_value)
    if url is None:
        return None
    platform = platform_value if isinstance(platform_value, str) else None
    if platform not in PLATFORM_LABELS:
        platform = normalize_social_url(url).platform.value
    return SourcePostOut(
        platform=platform,
        label=PLATFORM_LABELS[platform],
        url=url,
        author_name=author_name if isinstance(author_name, str) else None,
        highlight=highlight if isinstance(highlight, str) else None,
    )


def _buzz_posts(candidate: CandidatePlace) -> list[SourcePostOut]:
    """The posts behind a buzz card, in search-rank order, without repeats.

    Rows written before per-post details existed only hold a URL list; they
    still list their posts, just without an author or a quote.
    """
    posts: list[SourcePostOut] = []
    seen: set[str] = set()
    detailed = candidate.enrichment.get("social_posts")
    if isinstance(detailed, list) and detailed:
        entries = [
            _post_out(
                entry.get("url"),
                entry.get("platform"),
                author_name=entry.get("author_name"),
                highlight=entry.get("highlight"),
            )
            for entry in detailed
            if isinstance(entry, dict)
        ]
    else:
        urls = candidate.enrichment.get("social_post_urls")
        entries = [_post_out(url, None) for url in (urls if isinstance(urls, list) else [])]
    for post in entries:
        if post is not None and post.url not in seen:
            seen.add(post.url)
            posts.append(post)
    return posts


def _attached_post(candidate: CandidatePlace) -> SourcePostOut | None:
    """The post a traveler shared, when the attachment was a link."""
    return _post_out(
        candidate.enrichment.get("source_url"),
        candidate.enrichment.get("platform"),
    )


def source_posts(candidate: CandidatePlace) -> list[SourcePostOut]:
    """Every post behind a card: buzz posts first, then the traveler's own."""
    posts = _buzz_posts(candidate)
    attached = _attached_post(candidate)
    if attached is not None and all(post.url != attached.url for post in posts):
        posts.append(attached)
    return posts


def google_maps_place_url(candidate: CandidatePlace) -> str | None:
    """The place's Google Maps page, in the documented Maps URLs form."""
    place_id = candidate.enrichment.get("google_place_id")
    if not isinstance(place_id, str) or not place_id:
        return None
    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={quote(candidate.name_canonical, safe='')}"
        f"&query_place_id={quote(place_id, safe='')}"
    )


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
        # The badge opens the highest-ranked post; the card details list all.
        top = next(iter(_buzz_posts(candidate)), None)
        detailed_posts = candidate.enrichment.get("social_posts")
        has_engagement = isinstance(detailed_posts, list) and any(
            isinstance(post, dict)
            and (post.get("like_count") is not None or post.get("comment_count") is not None)
            for post in detailed_posts
        )
        badges.append(
            SourceBadgeOut(
                kind=(
                    SourceBadgeKind.TRENDING
                    if has_engagement
                    else SourceBadgeKind.SOCIAL
                ),
                label=(
                    f"{'Popular' if has_engagement else 'Found'} on {', '.join(named)}"
                    if named
                    else ("Popular post" if has_engagement else "Found on social")
                ),
                url=top.url if top is not None else None,
                platform=top.label if top is not None else None,
            )
        )

    if any(source.type == "discovery" for source in candidate.sources):
        maps_url = google_maps_place_url(candidate)
        badges.append(
            SourceBadgeOut(
                kind=SourceBadgeKind.DISCOVERED,
                label="Found on Google Maps",
                url=maps_url,
                platform=GOOGLE_MAPS_LABEL if maps_url is not None else None,
            )
        )

    contributors = {
        source.by
        for source in candidate.sources
        if source.type == "personal" and source.subtype == "user_paste" and source.by
    }
    attached = _attached_post(candidate)
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
                url=attached.url if attached is not None else None,
                platform=attached.label if attached is not None else None,
            )
        )
    return badges


class DelegateBadgeOut(BaseModel):
    type: str
    text: str
    reasoning: str

    @classmethod
    def of(cls, badge: CandidateBadge) -> DelegateBadgeOut:
        return cls(
            type=badge.badge_type.value,
            text=badge.badge_text,
            reasoning=badge.reasoning,
        )


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
    # What the source said about the place, and which source: a post's own
    # words for a buzz or attached card, the place listing otherwise.
    description: str | None
    description_source: str | None
    source_badges: list[SourceBadgeOut]
    source_posts: list[SourcePostOut]
    delegate_badge: DelegateBadgeOut | None

    @classmethod
    def of(
        cls,
        candidate: CandidatePlace,
        *,
        viewer_id: UUID | None = None,
        contributor_names: dict[UUID, str] | None = None,
        constraints: list[Constraint] | None = None,
        delegate_badge: CandidateBadge | None = None,
    ) -> CandidateCardOut:
        badges = source_badges(
            candidate,
            viewer_id=viewer_id,
            contributor_names=contributor_names,
        )
        description, description_source = _itinerary_description(candidate)

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
            description=description,
            description_source=description_source,
            source_badges=badges,
            source_posts=source_posts(candidate),
            delegate_badge=(
                DelegateBadgeOut.of(delegate_badge)
                if delegate_badge is not None
                else None
            ),
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
    LIKE = "like"
    DISLIKE = "dislike"
    LIKE_WITH_NOTE = "like_with_note"
    MUST_HAVE = "must_have"


class VoteRequest(BaseModel):
    traveler_id: UUID
    candidate_id: UUID
    signal: SwipeSignal
    note_text: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def _check_note(self) -> VoteRequest:
        if self.signal is SwipeSignal.LIKE_WITH_NOTE:
            if self.note_text is None or not self.note_text.strip():
                raise ValueError("like_with_note requires note_text")
            self.note_text = self.note_text.strip()
        elif self.note_text is not None:
            raise ValueError("note_text is only valid with like_with_note")
        return self


class VoteOut(BaseModel):
    id: UUID
    candidate_id: UUID
    traveler_id: UUID
    signal: str
    note_text: str | None
    note_parsed: dict[str, Any] | None

    @classmethod
    def of(cls, vote: Vote) -> VoteOut:
        return cls(
            id=vote.id,
            candidate_id=vote.candidate_id,
            traveler_id=vote.traveler_id,
            signal=vote.signal.value,
            note_text=vote.note_text,
            note_parsed=vote.note_parsed,
        )


class VoteProgressOut(BaseModel):
    """How much of the deck this traveler has swiped."""

    total_candidates: int
    voted: int
    remaining: int


class ShortlistEditRequest(BaseModel):
    traveler_id: UUID
    selected_candidate_ids: list[UUID]
    must_go_candidate_ids: list[UUID]


class ShortlistConfirmRequest(BaseModel):
    traveler_id: UUID


class ShortlistOut(BaseModel):
    trip_id: UUID
    selected_candidate_ids: list[UUID]
    must_go_candidate_ids: list[UUID]
    wishlist_excluded_ids: list[UUID]
    confirmed_by: list[UUID]
    confirmed_at: datetime | None
    confirmations_required: int
    traveler_count: int
    is_confirmed: bool


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


class DisruptionRequest(BaseModel):
    trigger_type: ReplanTrigger
    trigger_payload: dict[str, Any]

    @model_validator(mode="after")
    def _validate_trigger_payload(self) -> DisruptionRequest:
        payload = self.trigger_payload

        def valid_uuid(value: Any) -> bool:
            try:
                UUID(str(value))
            except (TypeError, ValueError):
                return False
            return True

        if self.trigger_type in {
            ReplanTrigger.RESERVATION_CANCELLED,
            ReplanTrigger.PLACE_CLOSED,
            ReplanTrigger.TRANSIT_DELAY,
        } and not valid_uuid(payload.get("node_id")):
            raise ValueError(f"{self.trigger_type.value} requires node_id")
        if self.trigger_type is ReplanTrigger.TRANSIT_DELAY:
            delay = payload.get("delay_minutes")
            if not isinstance(delay, int) or isinstance(delay, bool) or delay <= 0:
                raise ValueError("transit_delay requires positive delay_minutes")
        if self.trigger_type is ReplanTrigger.OVERSLEPT:
            day = payload.get("day")
            if not isinstance(day, int) or isinstance(day, bool) or day < 0:
                raise ValueError("overslept requires a non-negative day")
            try:
                time.fromisoformat(str(payload.get("at")))
            except ValueError as exc:
                raise ValueError("overslept requires at as a local time") from exc
        if self.trigger_type is ReplanTrigger.WEATHER:
            day = payload.get("day")
            if not isinstance(day, int) or isinstance(day, bool) or day < 0:
                raise ValueError("weather requires a non-negative day")
        if self.trigger_type is ReplanTrigger.OTHER:
            node_ids = payload.get("affected_node_ids")
            if (
                not isinstance(node_ids, list)
                or not node_ids
                or not all(valid_uuid(value) for value in node_ids)
            ):
                raise ValueError("other requires affected_node_ids")
        return self


class ReplanDecisionRequest(BaseModel):
    traveler_id: UUID


class ItineraryDiffStopOut(BaseModel):
    candidate_id: UUID
    name: str
    node_id: UUID
    day: int
    start_time: time
    end_time: time


class ItineraryMoveOut(BaseModel):
    candidate_id: UUID
    name: str
    old_node_id: UUID
    new_node_id: UUID
    old_day: int
    new_day: int
    old_start_time: time
    new_start_time: time


class ItineraryTimeChangeOut(BaseModel):
    candidate_id: UUID
    name: str
    old_node_id: UUID
    new_node_id: UUID
    day: int
    old_start_time: time
    old_end_time: time
    new_start_time: time
    new_end_time: time


class ItineraryDiffOut(BaseModel):
    added: list[ItineraryDiffStopOut]
    removed: list[ItineraryDiffStopOut]
    moved: list[ItineraryMoveOut]
    time_changed: list[ItineraryTimeChangeOut]

    @classmethod
    def of(
        cls,
        diff: ItineraryDiff,
        candidate_names: dict[UUID, str],
    ) -> ItineraryDiffOut:
        def name(candidate_id: UUID) -> str:
            return candidate_names.get(candidate_id, "Unknown place")

        return cls(
            added=[
                ItineraryDiffStopOut(name=name(item.candidate_id), **item.model_dump())
                for item in diff.added
            ],
            removed=[
                ItineraryDiffStopOut(name=name(item.candidate_id), **item.model_dump())
                for item in diff.removed
            ],
            moved=[
                ItineraryMoveOut(name=name(item.candidate_id), **item.model_dump())
                for item in diff.moved
            ],
            time_changed=[
                ItineraryTimeChangeOut(
                    name=name(item.candidate_id),
                    **item.model_dump(),
                )
                for item in diff.time_changed
            ],
        )


class ReplanTraceTriggerOut(BaseModel):
    type: ReplanTrigger


class ReplanAffectedNodeOut(BaseModel):
    node_id: UUID
    candidate_id: UUID
    classification: str


class ReplanAlternativeOut(BaseModel):
    candidate_id: UUID
    score: float
    chosen: bool
    reason: str | None = None
    rejected_reason: str | None = None


class ReplanDownstreamChangeOut(BaseModel):
    node_id: UUID
    candidate_id: UUID
    old_time: time
    new_time: time


class ReplanTraceOut(BaseModel):
    trigger: ReplanTraceTriggerOut
    affected_nodes: list[ReplanAffectedNodeOut]
    alternatives_considered: list[ReplanAlternativeOut]
    downstream_changes: list[ReplanDownstreamChangeOut]


class ReplanProposalOut(BaseModel):
    event_id: UUID
    trip_id: UUID
    trigger_type: ReplanTrigger
    status: ReplanStatus
    current_version_id: UUID
    proposed_version_id: UUID
    trace: ReplanTraceOut
    diff: ItineraryDiffOut


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
    source_posts: list[SourcePostOut]

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
            source_posts=source_posts(candidate) if candidate else [],
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

    # A traveler's own post first, then what the posts behind a buzz card
    # said, then the place listing. Each is labelled with where it came from.
    pasted = candidate.enrichment.get("source_description")
    if _is_pasted(candidate) and isinstance(pasted, str) and pasted.strip():
        return _brief(pasted), _description_source(candidate)

    highlight = candidate.enrichment.get("social_highlight")
    if isinstance(highlight, str) and highlight.strip():
        return _brief(highlight), _highlight_source(candidate)

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


DESCRIPTION_SOURCE_LABELS = {
    "instagram": "Instagram Reel",
    "tiktok": "TikTok",
    "rednote": "RedNote",
}


def _is_pasted(candidate: CandidatePlace) -> bool:
    return candidate.enrichment.get("platform") in DESCRIPTION_SOURCE_LABELS


def _highlight_source(candidate: CandidatePlace) -> str:
    """Which platform's post the card's highlight was quoted from."""
    detailed = candidate.enrichment.get("social_posts")
    if isinstance(detailed, list):
        for entry in detailed:
            if isinstance(entry, dict) and entry.get("highlight"):
                return DESCRIPTION_SOURCE_LABELS.get(
                    str(entry.get("platform")), "Social discovery"
                )
    return "Social discovery"


def _description_source(candidate: CandidatePlace) -> str:
    platform = candidate.enrichment.get("platform")
    if isinstance(platform, str) and platform in DESCRIPTION_SOURCE_LABELS:
        return DESCRIPTION_SOURCE_LABELS[platform]
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
