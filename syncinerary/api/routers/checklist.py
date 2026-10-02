"""Shared checklist available before discovery and after planning."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from syncinerary.api.deps import OptionalAccount, Session
from syncinerary.api.trip_membership import require_member
from syncinerary.domain.checklist import ChecklistItem
from syncinerary.domain.checklist_suggestions import suggestions
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ChecklistItemRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    TripRepository,
)

router = APIRouter(prefix="/trips/{trip_id}/checklist", tags=["checklist"])


class ChecklistItemOut(BaseModel):
    id: UUID
    title: str
    notes: str
    completed: bool
    revision: int
    source_key: str | None

    @classmethod
    def of(cls, item: ChecklistItem) -> "ChecklistItemOut":
        return cls.model_validate(item, from_attributes=True)


class ChecklistMember(BaseModel):
    traveler_id: UUID


class ChecklistCreate(ChecklistMember):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    notes: str = Field(default="", max_length=1000)


class ChecklistEdit(ChecklistCreate):
    completed: bool
    revision: int = Field(ge=1)


@router.post("/prepare")
async def prepare(
    trip_id: UUID, payload: ChecklistMember, session: Session, account: OptionalAccount
) -> list[ChecklistItemOut]:
    trip = await require_member(session, trip_id, payload.traveler_id, account)
    active = await ItineraryVersionRepository(session).get_active(trip_id)
    scheduled = []
    if active:
        ids = {
            n.candidate_id
            for n in await ItineraryNodeRepository(session).list_for_version(active.id)
        }
        scheduled = [
            c for c in await CandidatePlaceRepository(session).list_for_trip(trip_id) if c.id in ids
        ]
    repo = ChecklistItemRepository(session)
    await repo.suggest(suggestions(trip, scheduled))
    return [ChecklistItemOut.of(item) for item in await repo.list_for_trip(trip_id)]


@router.post("", status_code=201)
async def create(
    trip_id: UUID, payload: ChecklistCreate, session: Session, account: OptionalAccount
) -> ChecklistItemOut:
    await require_member(session, trip_id, payload.traveler_id, account)
    await TripRepository(session).lock(trip_id)
    repo = ChecklistItemRepository(session)
    if await repo.count_for_trip(trip_id) >= 300:
        raise HTTPException(422, "This checklist is full. Remove an item before adding another")
    return ChecklistItemOut.of(
        await repo.add(ChecklistItem(trip_id=trip_id, title=payload.title, notes=payload.notes))
    )


@router.put("/{item_id}")
async def edit(
    trip_id: UUID, item_id: UUID, payload: ChecklistEdit, session: Session, account: OptionalAccount
) -> ChecklistItemOut:
    await require_member(session, trip_id, payload.traveler_id, account)
    updated = await ChecklistItemRepository(session).change(
        trip_id,
        item_id,
        payload.revision,
        title=payload.title,
        notes=payload.notes,
        completed=payload.completed,
    )
    if updated is None:
        raise HTTPException(409, "This item changed. Refresh the checklist before editing it")
    return ChecklistItemOut.of(updated)


@router.delete("/{item_id}")
async def remove(
    trip_id: UUID,
    item_id: UUID,
    traveler_id: UUID,
    session: Session,
    account: OptionalAccount,
    revision: int = Query(ge=1),
) -> dict[str, bool]:
    await require_member(session, trip_id, traveler_id, account)
    if (
        await ChecklistItemRepository(session).change(trip_id, item_id, revision, deleted=True)
        is None
    ):
        raise HTTPException(409, "This item changed. Refresh the checklist before removing it")
    return {"deleted": True}
