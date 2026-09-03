"""Core domain models. Mirror of the persisted schema in CLAUDE.md §7.

These are the pydantic models the LangGraph state, the API layer, and the
store layer all share. Per the architectural rule (CLAUDE.md §2), no untyped
dicts are allowed to cross a node boundary; everything is a model.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from syncinerary.config.solver import DEFAULT_DAY_END_HOUR, DEFAULT_DAY_START_HOUR


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ----- Enums -----

class TripStatus(str, Enum):
    SETUP = "setup"
    SWIPING = "swiping"
    SHORTLISTING = "shortlisting"
    SCHEDULING = "scheduling"
    ACTIVE = "active"
    DISRUPTED = "disrupted"


class CandidateType(str, Enum):
    ATTRACTION = "attraction"
    FOOD = "food"
    LODGING = "lodging"


class ConstraintKind(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class VoteSignal(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"
    LIKE_WITH_NOTE = "like_with_note"
    MUST_HAVE = "must_have"


class BadgeType(str, Enum):
    WARNING = "warning"
    CONFIRM = "confirm"
    NEUTRAL = "neutral"


class ItineraryStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ReplanTrigger(str, Enum):
    RESERVATION_CANCELLED = "reservation_cancelled"
    TRANSIT_DELAY = "transit_delay"
    OVERSLEPT = "overslept"
    PLACE_CLOSED = "place_closed"
    WEATHER = "weather"
    OTHER = "other"


class ReplanStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SocialPlatform(str, Enum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    REDNOTE = "rednote"


class AttachmentInputType(str, Enum):
    LINK = "link"
    SCREENSHOT = "screenshot"


class AttachmentStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


# ----- Core entities (mirror Postgres schema in CLAUDE.md §7) -----

class Trip(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    # Display label for the trip, derived from `cities`.
    destination: str
    # The cities the traveler typed. Gather searches each one and scopes every
    # result to it, so this is the real input; `destination` is what the UI
    # shows. Ordered as entered.
    cities: list[str] = Field(default_factory=list)
    # The country all of those cities are in. Trips do not span countries: the
    # day plan assumes you can move between cities without a border or a
    # long-haul flight in the middle of the trip.
    country: str | None = None
    # Where each typed city actually is, resolved once when the trip is
    # created. Stored so gather does not resolve them again, and so an
    # unknown city fails at the form rather than part-way through a search.
    resolved_cities: list[dict[str, Any]] = Field(default_factory=list)
    # IANA zone for the destination, looked up from the first city.
    timezone: str | None = None
    start_date: date
    end_date: date
    days: int
    status: TripStatus = TripStatus.SETUP
    created_by: UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class Account(BaseModel):
    """A person across trips. Stub identity per CLAUDE.md section 15.

    Deliberately not an auth record: no password, no email verification, no
    provider. It exists to answer "who is this, on which trips", which is what
    invites and chat need and nothing more.
    """

    id: UUID = Field(default_factory=uuid4)
    display_name: str
    handle: str
    created_at: datetime = Field(default_factory=_utcnow)


class AccountSession(BaseModel):
    """An opaque bearer token. Stub: issued on sign-in, never rotated."""

    token: str
    account_id: UUID
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime


class Traveler(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    name: str
    home_city: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    # Nullable so every pre-M7a traveler stays valid and the single-player
    # flow keeps working with no account behind it.
    account_id: UUID | None = None


class TripInvite(BaseModel):
    """A revocable, expiring join code.

    Not the trip UUID: a UUID pasted into a group chat is a permanent
    credential nobody can turn off.
    """

    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    code: str
    created_by_traveler_id: UUID
    expires_at: datetime
    max_uses: int = 20
    uses: int = 0
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    def is_usable(self, *, now: datetime) -> bool:
        """Every reason a code can be refused, in one place.

        Callers must not re-derive this: a join path that checked expiry but
        forgot revocation would be a silent hole.
        """
        return (
            self.revoked_at is None
            and self.expires_at > now
            and self.uses < self.max_uses
        )


class TripMessageKind(str, Enum):
    TEXT = "text"
    LINK = "link"
    SYSTEM = "system"


class TripMessage(BaseModel):
    """One message in a trip's thread.

    `body` is untrusted user content (GROUP_TRIP_PLAN.md section 7). Anything
    that reads it treats it as data, never as instructions.
    """

    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    traveler_id: UUID | None = None
    body: str
    kind: TripMessageKind = TripMessageKind.TEXT
    # Set when a pasted URL became an attachment, so the thread can show that
    # the link is in the deck instead of leaving the poster guessing.
    link_attachment_id: UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class SourceAttachment(BaseModel):
    """A traveler-provided source waiting to become candidate evidence."""

    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    traveler_id: UUID
    platform: SocialPlatform
    input_type: AttachmentInputType
    status: AttachmentStatus = AttachmentStatus.PENDING
    original_url: str | None = None
    canonical_url: str | None = None
    platform_id: str | None = None
    screenshot_storage_key: str | None = None
    extracted_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class Constraint(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    traveler_id: UUID | None = None  # None means group-level
    type: str
    value: dict[str, Any] = Field(default_factory=dict)
    priority: int = 1
    kind: ConstraintKind


class Source(BaseModel):
    """One row inside CandidatePlace.sources. Dedup unions these across sources."""
    type: str  # 'discovery' | 'buzz' | 'personal'
    score: float | None = None
    articles_count: int | None = None
    sources_count: int | None = None
    subtype: str | None = None  # for personal: 'user_paste' | 'profile_driven'
    by: UUID | None = None      # for personal: which traveler
    via: str | None = None      # for personal: 'instagram_link', 'xhs_screenshot', ...


class CandidatePlace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    type: CandidateType
    name_canonical: str
    name_original_lang: str | None = None
    lat: float
    lng: float
    address: str | None = None
    area: str | None = None
    hours_by_weekday: dict[str, list[list[int]]] = Field(default_factory=dict)
    price_tier: int = 2
    duration_estimate_min: int = 60
    dietary_tags: list[str] = Field(default_factory=list)
    weather_dependent: bool = False
    reservation_required: bool = False
    fatigue_cost: int = 2
    category: str | None = None
    sources: list[Source] = Field(default_factory=list)
    enrichment: dict[str, Any] = Field(default_factory=dict)
    trending_signals: dict[str, Any] = Field(default_factory=dict)


class CandidateBadge(BaseModel):
    """Per-traveler badge generated by the delegate. Section 9 of CLAUDE.md."""
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    traveler_id: UUID
    badge_type: BadgeType
    badge_text: str
    reasoning: str
    generated_at: datetime = Field(default_factory=_utcnow)


class Vote(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    traveler_id: UUID
    signal: VoteSignal
    note_text: str | None = None
    note_parsed: dict[str, Any] | None = None


class ShortlistState(BaseModel):
    trip_id: UUID
    selected_candidate_ids: list[UUID] = Field(default_factory=list)
    must_go_candidate_ids: list[UUID] = Field(default_factory=list)
    confirmed_by: list[UUID] = Field(default_factory=list)
    confirmed_at: datetime | None = None
    wishlist_excluded_ids: list[UUID] = Field(default_factory=list)


class ItineraryVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    version_no: int
    status: ItineraryStatus = ItineraryStatus.PROPOSED
    created_by: str = "agent"  # 'agent' | 'user'
    parent_version_id: UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    objective_breakdown: dict[str, float] = Field(default_factory=dict)


class ItineraryNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    version_id: UUID
    candidate_id: UUID
    day: int
    start_time: time
    end_time: time
    fixed: bool = False
    lock_reason: str | None = None
    transit_from_prev_min: int = 0
    transit_from_prev_mode: str | None = None
    notes_for_travelers: dict[str, str] = Field(default_factory=dict)


class WishlistNotPlaced(BaseModel):
    version_id: UUID
    candidate_id: UUID
    reason_code: str
    reason_text: str


class ReplanEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    trigger_type: ReplanTrigger
    trigger_payload: dict[str, Any] = Field(default_factory=dict)
    affected_node_ids: list[UUID] = Field(default_factory=list)
    trace_json: dict[str, Any] = Field(default_factory=dict)
    proposed_version_id: UUID | None = None
    status: ReplanStatus = ReplanStatus.PENDING
    decided_by: UUID | None = None
    decided_at: datetime | None = None


class AgentRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    kind: str
    status: str
    step_count: int = 0
    token_cost: Decimal = Decimal(0)
    trace_id: str | None = None  # OTel trace id, joinable to Phoenix


class EvalScenario(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    fixture: dict[str, Any]
    disruption: dict[str, Any] | None = None
    expected: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    commit_sha: str
    scores: dict[str, Any]
    passed: bool
    run_at: datetime = Field(default_factory=_utcnow)


class CandidateScore(BaseModel):
    """One candidate's group consensus score (CLAUDE.md §10.1).

    The whole breakdown is carried, not just `score`. §2 puts consensus
    scoring on the deterministic side precisely because it has to be
    reproducible and auditable, and "auditable" means being able to see why a
    card ranked where it did without rerunning anything.
    """

    candidate_id: UUID
    votes_pos: int
    votes_neg: int
    votes_must: int
    votes_total: int
    acceptance: float
    must_have_bonus: float
    score: float


class SolverObjectiveWeights(BaseModel):
    """Bounded soft costs selected before deterministic scheduling."""

    dispersion: int = Field(default=20, ge=0, le=100)
    diversity: int = Field(default=15, ge=0, le=100)
    weather: int = Field(default=30, ge=0, le=100)
    vote: int = Field(default=25, ge=0, le=100)
    conditional: int = Field(default=35, ge=0, le=100)


# ----- Working state for the LangGraph -----

class TripState(BaseModel):
    """Working state passed through the LangGraph nodes during a run.

    NOTE: the durable source of truth lives in Postgres (itinerary_version chain).
    This is the in-flight view assembled for the current run.
    """
    trip: Trip
    travelers: list[Traveler] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    candidates: list[CandidatePlace] = Field(default_factory=list)
    votes: list[Vote] = Field(default_factory=list)
    badges: list[CandidateBadge] = Field(default_factory=list)
    candidate_scores: list[CandidateScore] = Field(default_factory=list)
    shortlist: ShortlistState | None = None
    solver_weights: SolverObjectiveWeights = Field(default_factory=SolverObjectiveWeights)
    current_itinerary: ItineraryVersion | None = None
    # M1 defaults to an 08:00 to 20:00 active window. These are graph state,
    # not trip persistence fields, so POST /plan can override them without a
    # schema migration. A later settings screen can expose the same inputs.
    day_start: time = time(DEFAULT_DAY_START_HOUR)
    day_end: time = time(DEFAULT_DAY_END_HOUR)
    # Written by the explainer, the last stage (§3). Purely descriptive: it is
    # produced from an itinerary that is already decided and feeds nothing.
    narrative: str | None = None
