"""Traveler-confirmed hotel lookup. Never claims to verify a room booking."""

from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from syncinerary.agents.gather.cities import resolve_trip_cities, search_bias
from syncinerary.agents.gather.live import candidate_from_place
from syncinerary.api.deps import OptionalAccount, Session
from syncinerary.api.schemas import LodgingOptionOut
from syncinerary.api.trip_membership import require_member
from syncinerary.domain.models import CandidatePlace, CandidateType, ConstraintKind, Source, Trip
from syncinerary.harness import run_tool, tracked_run
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    TripRepository,
)
from syncinerary.tools.places.hotel import HotelLookupInput, make_hotel_lookup_tool

router = APIRouter(prefix="/trips/{trip_id}", tags=["booked hotels"])


class HotelMatchOut(BaseModel):
    place_id: str
    name: str
    address: str | None


class BookedHotelRequest(BaseModel):
    traveler_id: UUID
    city: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2048)
    place_id: str = Field(min_length=1, max_length=300)


async def find_hotels(trip: Trip, city_name: str, query: str) -> list[CandidatePlace]:
    if city_name not in trip.cities:
        raise HTTPException(422, "Choose one of this trip's cities")
    cities = await resolve_trip_cities(trip)
    city = next((c for c in cities if c.name == city_name), None)
    if city is None:
        raise HTTPException(422, "The selected city could not be resolved")
    try:
        async with tracked_run(trip_id=trip.id, kind="booked_hotel_lookup"):
            result = await run_tool(
                make_hotel_lookup_tool(),
                HotelLookupInput(
                    query=query,
                    destination=city.name,
                    location_bias=search_bias(city),
                    city_center=search_bias(city),
                    city_radius_km=city.radius_km,
                ),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Hotel lookup is unavailable. Try again shortly") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [
        candidate_from_place(p, trip, query, city=city).model_copy(
            update={"type": CandidateType.LODGING}
        )
        for p in result.matches[:5]
    ]


@router.get("/hotel-search")
async def search(
    trip_id: UUID,
    traveler_id: UUID,
    city: str,
    session: Session,
    account: OptionalAccount,
    q: str = Query(min_length=1, max_length=2048),
) -> list[HotelMatchOut]:
    trip = await require_member(session, trip_id, traveler_id, account)
    return [
        HotelMatchOut(
            place_id=c.enrichment["google_place_id"], name=c.name_canonical, address=c.address
        )
        for c in await find_hotels(trip, city, q)
    ]


@router.post("/booked-hotel", status_code=201)
async def save(
    trip_id: UUID, payload: BookedHotelRequest, session: Session, account: OptionalAccount
) -> LodgingOptionOut:
    trip = await require_member(session, trip_id, payload.traveler_id, account)
    found = await find_hotels(trip, payload.city, payload.query)
    candidate = next(
        (c for c in found if c.enrichment.get("google_place_id") == payload.place_id), None
    )
    if candidate is None:
        raise HTTPException(422, "That hotel is no longer in the results. Search again")
    await TripRepository(session).lock(trip_id)
    repo = CandidatePlaceRepository(session)
    existing = next(
        (
            c
            for c in await repo.list_by_type(trip_id, CandidateType.LODGING)
            if c.enrichment.get("google_place_id") == payload.place_id
        ),
        None,
    )
    if existing is None:
        candidate.sources.append(
            Source(type="personal", subtype="booked_hotel", by=payload.traveler_id)
        )
        candidate = await repo.add(candidate)
    else:
        candidate = existing
    await ConstraintRepository(session).set_group_constraint(
        trip_id,
        constraint_type="selected_lodging",
        value={"candidate_id": str(candidate.id), "booked": True},
        priority=100,
        kind=ConstraintKind.HARD,
    )
    return LodgingOptionOut.of(candidate, trip).model_copy(
        update={"is_booked": True, "is_selected": True}
    )
