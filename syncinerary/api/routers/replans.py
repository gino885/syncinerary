"""Disruption reporting, proposal review, decisions, and live delivery."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError

from syncinerary.agents.rescue import (
    ReplanAlreadyDecided,
    ReplanConflict,
    ReplanInputError,
    ReplanNotFound,
    create_replan_proposal,
    decide_replan,
)
from syncinerary.api.deps import Session
from syncinerary.api.replan_ws import publish_replan_proposal, stream_replan_proposals
from syncinerary.api.schemas import (
    DisruptionRequest,
    ItineraryDiffOut,
    ReplanDecisionRequest,
    ReplanProposalOut,
)
from syncinerary.diff.itinerary_diff import itinerary_diff
from syncinerary.domain.models import ReplanEvent, Trip
from syncinerary.harness import tracked_run
from syncinerary.store.db import session_scope
from syncinerary.store.redis import get_redis
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
)

router = APIRouter(prefix="/trips", tags=["replan"])
logger = logging.getLogger(__name__)


async def _load_trip(session: Session, trip_id: UUID) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No trip {trip_id}")
    return trip


async def _load_traveler(session: Session, trip_id: UUID, traveler_id: UUID) -> None:
    traveler = await TravelerRepository(session).get(traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Traveler is not part of this trip",
        )


async def _diff_out(
    session: Session,
    *,
    trip_id: UUID,
    from_version_id: UUID,
    to_version_id: UUID,
) -> ItineraryDiffOut:
    versions = ItineraryVersionRepository(session)
    old_version = await versions.get(from_version_id)
    new_version = await versions.get(to_version_id)
    if (
        old_version is None
        or new_version is None
        or old_version.trip_id != trip_id
        or new_version.trip_id != trip_id
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Both itinerary versions must belong to this trip",
        )
    nodes = ItineraryNodeRepository(session)
    old_nodes = await nodes.list_for_version(old_version.id)
    new_nodes = await nodes.list_for_version(new_version.id)
    diff = itinerary_diff(old_nodes, new_nodes)
    candidate_ids = {
        item.candidate_id
        for collection in (diff.added, diff.removed, diff.moved, diff.time_changed)
        for item in collection
    }
    candidates = await CandidatePlaceRepository(session).list_by_ids(list(candidate_ids))
    return ItineraryDiffOut.of(
        diff,
        {candidate.id: candidate.name_canonical for candidate in candidates},
    )


async def _proposal_out(session: Session, event: ReplanEvent) -> ReplanProposalOut:
    if event.proposed_version_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Replan event has no proposed itinerary",
        )
    proposed = await ItineraryVersionRepository(session).get(event.proposed_version_id)
    if proposed is None or proposed.parent_version_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Replan proposal chain is incomplete",
        )
    diff = await _diff_out(
        session,
        trip_id=event.trip_id,
        from_version_id=proposed.parent_version_id,
        to_version_id=proposed.id,
    )
    return ReplanProposalOut(
        event_id=event.id,
        trip_id=event.trip_id,
        trigger_type=event.trigger_type,
        status=event.status,
        current_version_id=proposed.parent_version_id,
        proposed_version_id=proposed.id,
        trace=event.trace_json,
        diff=diff,
    )


@router.get("/{trip_id}/itinerary/diff")
async def get_itinerary_diff(
    trip_id: UUID,
    session: Session,
    from_version_id: UUID,
    to_version_id: UUID,
) -> ItineraryDiffOut:
    await _load_trip(session, trip_id)
    return await _diff_out(
        session,
        trip_id=trip_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
    )


@router.post("/{trip_id}/disruptions", status_code=status.HTTP_201_CREATED)
async def report_disruption(
    trip_id: UUID,
    payload: DisruptionRequest,
    session: Session,
) -> ReplanProposalOut:
    await _load_trip(session, trip_id)
    try:
        async with tracked_run(trip_id=trip_id, kind="replan"):
            proposal = await create_replan_proposal(
                session,
                trip_id=trip_id,
                trigger_type=payload.trigger_type,
                trigger_payload=payload.trigger_payload,
            )
    except ReplanInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    response = await _proposal_out(session, proposal.event)
    try:
        await publish_replan_proposal(get_redis(), response)
    except RedisError:
        logger.warning("Replan proposal persisted but WebSocket publish failed")
    return response


@router.get("/{trip_id}/replans/{event_id}")
async def get_replan(
    trip_id: UUID,
    event_id: UUID,
    session: Session,
) -> ReplanProposalOut:
    await _load_trip(session, trip_id)
    event = await ReplanEventRepository(session).get(event_id)
    if event is None or event.trip_id != trip_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Replan event not found")
    return await _proposal_out(session, event)


async def _decide(
    session: Session,
    *,
    trip_id: UUID,
    event_id: UUID,
    traveler_id: UUID,
    approve: bool,
) -> ReplanProposalOut:
    await _load_trip(session, trip_id)
    await _load_traveler(session, trip_id, traveler_id)
    try:
        event = await decide_replan(
            session,
            trip_id=trip_id,
            event_id=event_id,
            traveler_id=traveler_id,
            approve=approve,
        )
    except ReplanNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (ReplanAlreadyDecided, ReplanConflict) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _proposal_out(session, event)


@router.post("/{trip_id}/replans/{event_id}/approve")
async def approve_replan(
    trip_id: UUID,
    event_id: UUID,
    payload: ReplanDecisionRequest,
    session: Session,
) -> ReplanProposalOut:
    return await _decide(
        session,
        trip_id=trip_id,
        event_id=event_id,
        traveler_id=payload.traveler_id,
        approve=True,
    )


@router.post("/{trip_id}/replans/{event_id}/reject")
async def reject_replan(
    trip_id: UUID,
    event_id: UUID,
    payload: ReplanDecisionRequest,
    session: Session,
) -> ReplanProposalOut:
    return await _decide(
        session,
        trip_id=trip_id,
        event_id=event_id,
        traveler_id=payload.traveler_id,
        approve=False,
    )


@router.websocket("/{trip_id}/replans/ws")
async def replan_websocket(
    websocket: WebSocket,
    trip_id: UUID,
    traveler_id: UUID,
) -> None:
    async with session_scope() as session:
        trip = await TripRepository(session).get(trip_id)
        traveler = await TravelerRepository(session).get(traveler_id)
        if trip is None or traveler is None or traveler.trip_id != trip_id:
            await websocket.close(code=1008, reason="Trip membership required")
            return
    try:
        await stream_replan_proposals(websocket, get_redis(), trip_id)
    except WebSocketDisconnect:
        return


__all__ = ["router"]
