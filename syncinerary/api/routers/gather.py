"""Fast discovery commands and group readiness; execution belongs to a worker."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from syncinerary.api.deps import CurrentAccount, Session
from syncinerary.api.routers.group import _require_membership
from syncinerary.api.schemas import ProfileValue
from syncinerary.domain.gather import GatherRun
from syncinerary.domain.models import Constraint, ConstraintKind, TripStatus
from syncinerary.store.repositories import (
    AccountRepository,
    AnthropicCredentialRepository,
    ConstraintRepository,
    GatherRunRepository,
    SourceAttachmentRepository,
    TravelerRepository,
    TripRepository,
)

router = APIRouter(prefix="/trips", tags=["discovery"])


class GatherRunOut(BaseModel):
    run_id: UUID
    status: str
    phase: str
    city: str | None
    completed_units: int
    total_units: int | None
    deck_size: int | None
    error_code: str | None
    retryable: bool
    updated_at: datetime

    @classmethod
    def of(cls, run: GatherRun):
        return cls(
            run_id=run.id,
            retryable=run.status == "failed" and run.retry_count < 2,
            **run.model_dump(
                exclude={
                    "id",
                    "trip_id",
                    "credential_account_id",
                    "input_snapshot",
                    "retry_count",
                    "created_at",
                }
            ),
        )


@router.post("/{trip_id}/gather-runs", status_code=202)
async def start_gather(trip_id: UUID, account: CurrentAccount, session: Session) -> GatherRunOut:
    member = await _require_membership(session, trip_id=trip_id, account_id=account.id)
    trip = await TripRepository(session).get(trip_id)
    if trip is None or trip.created_by != member.id:
        raise HTTPException(403, "Only the trip leader may start discovery")
    if await AnthropicCredentialRepository(session).get(account.id) is None:
        raise HTTPException(
            409,
            "Add your Anthropic API key in AI access before starting discovery",
        )
    missing_consent = await AccountRepository(
        session
    ).missing_anthropic_consent_for_trip(trip_id)
    if missing_consent:
        raise HTTPException(
            409,
            "Every trip member must approve Anthropic data sharing in AI privacy",
        )
    try:
        run = await GatherRunRepository(session).start(trip_id, member.id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return GatherRunOut.of(run)


@router.get("/{trip_id}/gather-runs/current")
async def current_gather(trip_id: UUID, account: CurrentAccount, session: Session) -> GatherRunOut:
    await _require_membership(session, trip_id=trip_id, account_id=account.id)
    run = await GatherRunRepository(session).current(trip_id)
    if run is None:
        raise HTTPException(404, "Discovery has not started")
    return GatherRunOut.of(run)


class ReadyMember(BaseModel):
    id: UUID
    name: str
    preferences_complete: bool
    interests: list[str] = Field(default_factory=list)
    dietary_excludes: list[str] = Field(default_factory=list)


class ReadyLink(BaseModel):
    id: UUID
    traveler_id: UUID
    canonical_url: str | None
    status: str
    deferred: bool = False


class PreparationOut(BaseModel):
    leader_id: UUID | None
    status: str
    members: list[ReadyMember]
    links: list[ReadyLink]
    run_status: str | None = None
    retryable: bool = False


@router.get("/{trip_id}/preparation")
async def preparation(trip_id: UUID, account: CurrentAccount, session: Session) -> PreparationOut:
    await _require_membership(session, trip_id=trip_id, account_id=account.id)
    trip = await TripRepository(session).get(trip_id)
    members = await TravelerRepository(session).list_for_trip(trip_id)
    links = await SourceAttachmentRepository(session).list_for_trip(trip_id)
    run = await GatherRunRepository(session).current(trip_id)
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    included = {a.id for a in run.input_snapshot.attachments} if run else set()
    return PreparationOut(
        leader_id=trip.created_by,
        status=trip.status.value,
        run_status=run.status if run else None,
        retryable=bool(run and run.status == "failed" and run.retry_count < 2),
        members=[
            ReadyMember(
                id=m.id,
                name=m.name,
                interests=m.profile.get("interests", []),
                dietary_excludes=[
                    value
                    for c in constraints
                    if c.traveler_id == m.id and c.type == "dietary"
                    for value in c.value.get("excludes", [])
                ],
                preferences_complete=bool(
                    m.profile.get("preferences_complete") or m.profile.get("interests")
                ),
            )
            for m in members
        ],
        links=[
            ReadyLink(
                id=a.id,
                traveler_id=a.traveler_id,
                canonical_url=a.canonical_url,
                status=a.status.value,
                deferred=bool(run and a.id not in included),
            )
            for a in links
        ],
    )


class MemberPreferences(BaseModel):
    interests: list[ProfileValue] = Field(default_factory=list, max_length=20)
    dietary_excludes: list[ProfileValue] = Field(default_factory=list, max_length=12)

    @field_validator("interests", "dietary_excludes")
    @classmethod
    def clean(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip().casefold() for v in values if v.strip()))


@router.put("/{trip_id}/preferences")
async def preferences(
    trip_id: UUID, payload: MemberPreferences, account: CurrentAccount, session: Session
) -> ReadyMember:
    member = await _require_membership(session, trip_id=trip_id, account_id=account.id)
    trip = await TripRepository(session).lock(trip_id)
    if trip.status not in {TripStatus.DRAFT, TripStatus.SETUP}:
        raise HTTPException(409, "Preferences are frozen for this discovery run")
    await TravelerRepository(session).set_profile(
        member.id,
        {
            **member.profile,
            "interests": payload.interests,
            "preferences_complete": True,
        },
    )
    constraints = ConstraintRepository(session)
    for constraint in await constraints.list_for_traveler(member.id):
        if constraint.type == "dietary":
            await constraints.delete(constraint.id)
    if payload.dietary_excludes:
        await constraints.add(
            Constraint(
                trip_id=trip_id,
                traveler_id=member.id,
                type="dietary",
                value={"excludes": payload.dietary_excludes},
                priority=10,
                kind=ConstraintKind.HARD,
            )
        )
    return ReadyMember(
        id=member.id,
        name=member.name,
        preferences_complete=True,
        interests=payload.interests,
        dietary_excludes=payload.dietary_excludes,
    )
