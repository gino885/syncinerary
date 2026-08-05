"""SQLAlchemy 2.0 table definitions. One-to-one with the schema in CLAUDE.md §7.

This is the persistence shape only. The domain shape lives in domain/models.py
and the two are deliberately separate: repositories in store/repositories/
own the translation. Nothing outside store/ imports this module (CLAUDE.md §14:
the API layer never touches SQLAlchemy).

Deviations from §7, each deliberate:

- `constraint` is renamed `trip_constraint`. CONSTRAINT is a Postgres reserved
  word, so the original name would need double quoting in every hand-written
  statement, and a single missed quote is a runtime error rather than a syntax
  error caught in review.
- `wishlist_not_placed` gets a composite primary key (version_id,
  candidate_id). §7 lists no id column and that pair is naturally unique: one
  reason per candidate per version.
- `created_at` on trip, and `unique(trip_id, version_no)` on itinerary_version,
  are present because domain/models.py already carries them.

Primary keys are client-generated uuid4, matching domain/models.py. The
supabase-postgres-best-practices skill prefers bigint identity or time-ordered
UUIDv7 to avoid btree fragmentation. CLAUDE.md §16 and the domain models take
precedence (§18), and the fragmentation argument needs far more rows than a
trip's few hundred to matter.

Append-only rule (§7): itinerary_version and itinerary_node are never updated
in place. That is enforced in the repository layer, which exposes no update
method for either, not by a database trigger.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from syncinerary.domain.models import (
    BadgeType,
    CandidateType,
    ConstraintKind,
    ItineraryStatus,
    ReplanStatus,
    ReplanTrigger,
    TripStatus,
    VoteSignal,
)

# Deterministic constraint names. Without this, alembic autogenerate emits
# unnamed constraints that later revisions cannot drop by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

EMBEDDING_DIM = 1536  # CLAUDE.md §7: candidate_place.embedding vector(1536)


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def _pg_enum(python_enum: type, name: str) -> sa.Enum:
    """Native Postgres enum storing the enum *values*, not the member names.

    Without values_callable SQLAlchemy persists "SETUP" rather than "setup",
    which would not match the literals in CLAUDE.md §7.
    """
    return sa.Enum(
        python_enum,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )


def _jsonb_dict() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))


def _jsonb_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))


class Trip(Base):
    __tablename__ = "trip"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    destination: Mapped[str] = mapped_column(sa.Text, nullable=False)
    start_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    days: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[TripStatus] = mapped_column(
        _pg_enum(TripStatus, "trip_status"),
        nullable=False,
        server_default=TripStatus.SETUP.value,
    )
    # No FK: this points at a traveler, and traveler.trip_id points back here.
    # A real FK would make the pair mutually dependent and unwritable without
    # a deferred constraint.
    created_by: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Traveler(Base):
    __tablename__ = "traveler"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    home_city: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    profile_json: Mapped[dict[str, Any]] = _jsonb_dict()


class TripConstraint(Base):
    """CLAUDE.md §7 calls this `constraint`. Renamed: reserved word."""

    __tablename__ = "trip_constraint"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL means group-level rather than attached to one traveler.
    traveler_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("traveler.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    value_json: Mapped[dict[str, Any]] = _jsonb_dict()
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="1")
    kind: Mapped[ConstraintKind] = mapped_column(
        _pg_enum(ConstraintKind, "constraint_kind"), nullable=False
    )


class CandidatePlace(Base):
    __tablename__ = "candidate_place"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[CandidateType] = mapped_column(
        _pg_enum(CandidateType, "candidate_type"), nullable=False
    )
    name_canonical: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name_original_lang: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    lat: Mapped[float] = mapped_column(sa.Double, nullable=False)
    lng: Mapped[float] = mapped_column(sa.Double, nullable=False)
    address: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    area: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # {mon: [[9, 18]], tue: [...], ...}. Hours as integer hours, per §7.
    hours_by_weekday: Mapped[dict[str, Any]] = _jsonb_dict()
    price_tier: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="2")
    duration_estimate_min: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="60"
    )
    dietary_tags: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")
    )
    weather_dependent: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    reservation_required: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    fatigue_cost: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="2")
    category: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Provenance, unioned by dedup (§8.4). Never overwritten on merge.
    sources: Mapped[list[Any]] = _jsonb_list()
    enrichment: Mapped[dict[str, Any]] = _jsonb_dict()
    trending_signals: Mapped[dict[str, Any]] = _jsonb_dict()
    # Nullable: only populated once enrichment embeds the place (M3 dedup).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    __table_args__ = (
        # Swipe and gather both filter by trip and card type (§8.6 excludes
        # lodging from the swipe deck).
        sa.Index("ix_candidate_place_trip_id_type", "trip_id", "type"),
    )


class CandidateBadge(Base):
    __tablename__ = "candidate_badge"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("candidate_place.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    traveler_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("traveler.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge_type: Mapped[BadgeType] = mapped_column(_pg_enum(BadgeType, "badge_type"), nullable=False)
    badge_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(sa.Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    __table_args__ = (
        # One badge per traveler per card (§9.1: exactly one badge, or none).
        sa.UniqueConstraint("candidate_id", "traveler_id", name="uq_candidate_badge_per_traveler"),
    )


class Vote(Base):
    __tablename__ = "vote"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("candidate_place.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    traveler_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("traveler.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal: Mapped[VoteSignal] = mapped_column(_pg_enum(VoteSignal, "vote_signal"), nullable=False)
    note_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    note_parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # Not in §7. A swipe deck lets a traveler revisit a card, and without
        # this the aggregator in §10.1 would count one person's second thoughts
        # as two votes. Repositories upsert on this key.
        sa.UniqueConstraint("candidate_id", "traveler_id", name="uq_vote_per_traveler"),
    )


class ShortlistState(Base):
    __tablename__ = "shortlist_state"

    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), primary_key=True
    )
    # Ordered (§7). JSONB arrays of candidate uuids rather than a join table:
    # order matters, the lists are short, and they are read whole or not at all.
    selected_candidate_ids: Mapped[list[Any]] = _jsonb_list()
    must_go_candidate_ids: Mapped[list[Any]] = _jsonb_list()
    confirmed_by: Mapped[list[Any]] = _jsonb_list()
    confirmed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    wishlist_excluded_ids: Mapped[list[Any]] = _jsonb_list()


class ItineraryVersion(Base):
    """Append-only (§7). Repositories expose no update method."""

    __tablename__ = "itinerary_version"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[ItineraryStatus] = mapped_column(
        _pg_enum(ItineraryStatus, "itinerary_status"),
        nullable=False,
        server_default=ItineraryStatus.PROPOSED.value,
    )
    created_by: Mapped[str] = mapped_column(
        sa.Enum("agent", "user", name="itinerary_created_by"),
        nullable=False,
        server_default="agent",
    )
    # The replan chain (§12.2): a proposal points at the version it supersedes.
    # RESTRICT, not CASCADE: losing a parent must not silently delete history.
    parent_version_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("itinerary_version.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    objective_breakdown: Mapped[dict[str, Any]] = _jsonb_dict()

    __table_args__ = (
        sa.UniqueConstraint("trip_id", "version_no", name="uq_itinerary_version_no_per_trip"),
    )


class ItineraryNode(Base):
    """Append-only (§7). Written once with its version, never edited."""

    __tablename__ = "itinerary_node"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("itinerary_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("candidate_place.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    day: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(sa.Time, nullable=False)
    end_time: Mapped[time] = mapped_column(sa.Time, nullable=False)
    fixed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    lock_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    transit_from_prev_min: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0"
    )
    transit_from_prev_mode: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    notes_for_travelers: Mapped[dict[str, Any]] = _jsonb_dict()

    __table_args__ = (
        # The itinerary view reads a whole day in visit order.
        sa.Index("ix_itinerary_node_version_id_day_start_time", "version_id", "day", "start_time"),
    )


class WishlistNotPlaced(Base):
    """Shortlisted cards the solver could not fit, with a reason (§10.3)."""

    __tablename__ = "wishlist_not_placed"

    version_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("itinerary_version.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("candidate_place.id", ondelete="CASCADE"), primary_key=True
    )
    # 'no_day_fit' | 'budget' | 'fatigue_overflow' | 'closed_on_available_days'
    reason_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    __table_args__ = (sa.Index("ix_wishlist_not_placed_candidate_id", "candidate_id"),)


class ReplanEvent(Base):
    __tablename__ = "replan_event"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_type: Mapped[ReplanTrigger] = mapped_column(
        _pg_enum(ReplanTrigger, "replan_trigger"), nullable=False
    )
    trigger_payload: Mapped[dict[str, Any]] = _jsonb_dict()
    affected_node_ids: Mapped[list[Any]] = _jsonb_list()
    # Structured decision trace (§12.2). The HITL gate renders this.
    trace_json: Mapped[dict[str, Any]] = _jsonb_dict()
    proposed_version_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("itinerary_version.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status: Mapped[ReplanStatus] = mapped_column(
        _pg_enum(ReplanStatus, "replan_status"),
        nullable=False,
        server_default=ReplanStatus.PENDING.value,
    )
    decided_by: Mapped[UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("traveler.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    trip_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("trip.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    step_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    # USD. numeric, not float: budget comparisons in harness/budget.py (M2)
    # must not drift on repeated accumulation.
    token_cost: Mapped[Decimal] = mapped_column(
        sa.Numeric(12, 6), nullable=False, server_default="0"
    )
    # OTel trace id, joinable to Phoenix.
    trace_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True, index=True)


class EvalScenario(Base):
    __tablename__ = "eval_scenario"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    fixture_json: Mapped[dict[str, Any]] = _jsonb_dict()
    disruption_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expected_json: Mapped[dict[str, Any]] = _jsonb_dict()


class EvalResult(Base):
    __tablename__ = "eval_result"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("eval_scenario.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commit_sha: Mapped[str] = mapped_column(sa.Text, nullable=False)
    scores_json: Mapped[dict[str, Any]] = _jsonb_dict()
    passed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    run_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    __table_args__ = (
        # F2 diffs the current commit's run against the previous one (§12.3).
        sa.Index("ix_eval_result_commit_sha_scenario_id", "commit_sha", "scenario_id"),
    )
