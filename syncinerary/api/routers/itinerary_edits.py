"""Manual itinerary proposals and verified place selection after planning."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from syncinerary.agents.gather.admission import admit_place
from syncinerary.agents.gather.cities import resolve_trip_cities, search_bias
from syncinerary.agents.gather.dietary import filter_dietary_conflicts
from syncinerary.agents.gather.live import candidate_from_place
from syncinerary.agents.manual_itinerary import city_for_day, propose_edit
from syncinerary.agents.rescue import ReplanConflict, ReplanInputError
from syncinerary.api.deps import OptionalAccount, Session
from syncinerary.api.replan_ws import publish_replan_proposal
from syncinerary.api.routers.replans import _proposal_out
from syncinerary.api.schemas import ReplanProposalOut
from syncinerary.domain.itinerary_edit import ItineraryEdit
from syncinerary.domain.models import Account, CandidatePlace, CandidateType, Source, Trip
from syncinerary.harness import run_tool, tracked_run
from syncinerary.store.redis import get_redis
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.tools.places import PlaceSearchInput, make_place_search_tool

router = APIRouter(prefix="/trips/{trip_id}/itinerary", tags=["itinerary edits"])


class PlaceOption(BaseModel):
    candidate_id: UUID | None = None
    place_id: str | None = None
    name: str
    city: str | None
    duration_minutes: int

    @classmethod
    def of(cls, candidate: CandidatePlace) -> "PlaceOption":
        return cls(
            candidate_id=candidate.id,
            place_id=candidate.enrichment.get("google_place_id"),
            name=candidate.name_canonical,
            city=candidate.enrichment.get("city"),
            duration_minutes=candidate.duration_estimate_min,
        )


class SelectPlace(BaseModel):
    traveler_id: UUID
    day: int = Field(ge=0, strict=True)
    query: str = Field(min_length=1, max_length=200)
    place_id: str = Field(min_length=1, max_length=300)


async def require_editor(
    session: Session,
    trip_id: UUID,
    traveler_id: UUID,
    account: Account | None,
) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    member = await TravelerRepository(session).get(traveler_id)
    if trip is None or member is None or member.trip_id != trip_id:
        raise HTTPException(403, "Join this trip before editing")
    if member.account_id is not None and (account is None or account.id != member.account_id):
        raise HTTPException(403, "Sign in as this trip member before editing")
    if await ItineraryVersionRepository(session).get_active(trip_id) is None:
        raise HTTPException(409, "Create an itinerary before editing it")
    return trip


async def edit_city(session: Session, trip: Trip, day: int) -> str:
    existing_city = None
    if not trip.city_days:
        active = await ItineraryVersionRepository(session).get_active(trip.id)
        nodes = await ItineraryNodeRepository(session).list_for_version(active.id) if active else []
        candidates = {
            c.id: c for c in await CandidatePlaceRepository(session).list_for_trip(trip.id)
        }
        cities = {
            candidates[n.candidate_id].enrichment.get("city") for n in nodes if n.day == day
        } - {None}
        if len(cities) == 1:
            existing_city = next(iter(cities))
    try:
        return city_for_day(trip, day, existing_city=existing_city)
    except ReplanInputError as exc:
        raise HTTPException(422, str(exc)) from exc


async def searched_places(
    trip: Trip, day: int, query: str, *, city_name: str | None = None
) -> list[CandidatePlace]:
    try:
        city_name = city_name or city_for_day(trip, day)
    except ReplanInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    cities = await resolve_trip_cities(trip)
    city = next((c for c in cities if c.name == city_name), None)
    if city is None:
        raise HTTPException(422, "The selected day has no resolved city")
    async with tracked_run(trip_id=trip.id, kind="manual_place_search"):
        result = await run_tool(
            make_place_search_tool(),
            PlaceSearchInput(
                query=query.strip(),
                destination=city.name,
                location_bias=search_bias(city),
                city_center=search_bias(city),
                city_radius_km=city.radius_km,
            ),
        )
    return [
        candidate_from_place(p, trip, query, city=city)
        for p in result.matches
        if admit_place(p, destination=city.name, city=city).accepted and p.primary_type != "lodging"
    ]


@router.get("/edit-places")
async def edit_places(
    trip_id: UUID,
    traveler_id: UUID,
    day: int,
    session: Session,
    account: OptionalAccount,
    q: str = Query(default="", max_length=200),
) -> list[PlaceOption]:
    trip = await require_editor(session, trip_id, traveler_id, account)
    city = await edit_city(session, trip, day)
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    saved = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    if not q.strip():
        return [
            PlaceOption.of(c)
            for c in filter_dietary_conflicts(saved, constraints)
            if c.type is not CandidateType.LODGING
            and (
                c.enrichment.get("city") == city
                or not c.enrichment.get("city")
                and len(trip.cities) <= 1
            )
        ]
    # Search results are ephemeral. Only the exact selection is persisted.
    found = filter_dietary_conflicts(
        await searched_places(trip, day, q, city_name=city), constraints
    )
    saved_by_place = {c.enrichment.get("google_place_id"): c for c in saved}
    result = []
    for c in found:
        if c.type is CandidateType.LODGING:
            continue
        old = saved_by_place.get(c.enrichment.get("google_place_id"))
        result.append(
            PlaceOption.of(old)
            if old
            else PlaceOption.of(c).model_copy(update={"candidate_id": None})
        )
    return result


@router.post("/edit-places", status_code=201)
async def select_place(
    trip_id: UUID, payload: SelectPlace, session: Session, account: OptionalAccount
) -> PlaceOption:
    trip = await require_editor(session, trip_id, payload.traveler_id, account)
    found = await searched_places(
        trip, payload.day, payload.query, city_name=await edit_city(session, trip, payload.day)
    )
    found = filter_dietary_conflicts(
        found, await ConstraintRepository(session).list_for_trip(trip_id)
    )
    candidate = next(
        (
            c
            for c in found
            if c.enrichment.get("google_place_id") == payload.place_id
            and c.type is not CandidateType.LODGING
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            422, "That place is no longer available in this city's results. Search again"
        )
    await TripRepository(session).lock(trip_id)
    repo = CandidatePlaceRepository(session)
    saved = await repo.list_for_trip(trip_id)
    existing = next(
        (c for c in saved if c.enrichment.get("google_place_id") == payload.place_id), None
    )
    if existing:
        return PlaceOption.of(existing)
    candidate.sources.append(
        Source(type="personal", subtype="manual_selection", by=payload.traveler_id)
    )
    return PlaceOption.of(await repo.add(candidate))


@router.post("/edits", status_code=201)
async def edit_itinerary(
    trip_id: UUID, payload: ItineraryEdit, session: Session, account: OptionalAccount
) -> ReplanProposalOut:
    await require_editor(session, trip_id, payload.traveler_id, account)
    try:
        async with tracked_run(trip_id=trip_id, kind="manual_itinerary_edit"):
            proposal = await propose_edit(session, trip_id=trip_id, edit=payload)
    except ReplanInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ReplanConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    result = await _proposal_out(session, proposal.event)
    # Publish only a durable proposal, so another device can approve it immediately.
    await session.commit()
    try:
        await publish_replan_proposal(get_redis(), result)
    except RedisError:
        # The pending endpoint remains the durable recovery path.

        logging.getLogger(__name__).warning("Manual edit persisted; live notification unavailable")
    return result
