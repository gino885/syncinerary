"""Trip setup and swipe voting.

The M1 surface from CLAUDE.md §13: create a trip, read the deck, swipe it.
Shortlist confirmation (M4), badges (M4) and replan (M6) are not here.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from syncinerary.api.deps import Session
from syncinerary.api.schemas import (
    CandidateCardOut,
    TripCreatedResponse,
    TripCreateRequest,
    TripOut,
    VoteOut,
    VoteProgressOut,
    VoteRequest,
)
from syncinerary.domain.models import Traveler, Trip, TripStatus, Vote, VoteSignal
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    TravelerRepository,
    TripRepository,
    VoteRepository,
)

router = APIRouter(prefix="/trips", tags=["trips"])


async def _load_trip(session: Session, trip_id: UUID) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No trip {trip_id}")
    return trip


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trip(payload: TripCreateRequest, session: Session) -> TripCreatedResponse:
    """Create a trip and its creator traveler.

    `days` is derived here and stored (§7 calls it derived but persisted):
    every downstream default is expressed as a multiple of it, so recomputing
    it in three places would be three chances to disagree. Inclusive of both
    end dates, so 21 to 25 May is 5 days, not 4.
    """
    days = (payload.end_date - payload.start_date).days + 1

    trip = await TripRepository(session).add(
        Trip(
            destination=payload.destination,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days=days,
            status=TripStatus.SETUP,
        )
    )
    traveler = await TravelerRepository(session).add(
        Traveler(
            trip_id=trip.id,
            name=payload.creator_name,
            home_city=payload.creator_home_city,
        )
    )
    # created_by points at the traveler and carries no FK, since traveler
    # points back at the trip (see store/tables.py).
    trip = await TripRepository(session).set_created_by(trip.id, traveler.id)

    return TripCreatedResponse(trip=TripOut.of(trip), traveler_id=traveler.id)


@router.get("/{trip_id}")
async def get_trip(trip_id: UUID, session: Session) -> TripOut:
    return TripOut.of(await _load_trip(session, trip_id))


@router.get("/{trip_id}/candidates")
async def list_candidates(trip_id: UUID, session: Session) -> list[CandidateCardOut]:
    """The swipe deck.

    Lodging is excluded. §8.6 makes it solver-driven after shortlist
    confirmation, not something the group swipes.
    """
    await _load_trip(session, trip_id)
    candidates = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    return [CandidateCardOut.of(c) for c in candidates]


@router.post("/{trip_id}/votes", status_code=status.HTTP_201_CREATED)
async def cast_vote(trip_id: UUID, payload: VoteRequest, session: Session) -> VoteOut:
    """Record one swipe.

    M1 accepts like and dislike only; the request schema rejects anything
    else with a 422 before reaching here.

    Re-voting on the same card replaces the earlier vote rather than adding
    one, so a traveler who changes their mind still counts once in §10.1.
    """
    await _load_trip(session, trip_id)

    traveler = await TravelerRepository(session).get(payload.traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {payload.traveler_id} is not on trip {trip_id}",
        )

    candidate = await CandidatePlaceRepository(session).get(payload.candidate_id)
    if candidate is None or candidate.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Candidate {payload.candidate_id} is not in trip {trip_id}",
        )

    vote = await VoteRepository(session).upsert(
        Vote(
            candidate_id=payload.candidate_id,
            traveler_id=payload.traveler_id,
            signal=VoteSignal(payload.signal.value),
        )
    )

    # First vote moves the trip out of setup. Status is advisory in M1; the
    # pipeline does not gate on it until the shortlist screen lands in M4.
    trip = await TripRepository(session).get(trip_id)
    if trip is not None and trip.status is TripStatus.SETUP:
        await TripRepository(session).set_status(trip_id, TripStatus.SWIPING)

    return VoteOut.of(vote)


@router.get("/{trip_id}/votes/progress")
async def vote_progress(
    trip_id: UUID, traveler_id: UUID, session: Session
) -> VoteProgressOut:
    """How far through the deck one traveler is. The iOS swipe screen uses
    this to decide when to offer planning."""
    await _load_trip(session, trip_id)

    deck = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    deck_ids = {c.id for c in deck}
    votes = await VoteRepository(session).list_for_traveler(traveler_id)
    voted = sum(1 for v in votes if v.candidate_id in deck_ids)

    return VoteProgressOut(
        total_candidates=len(deck),
        voted=voted,
        remaining=len(deck) - voted,
    )
