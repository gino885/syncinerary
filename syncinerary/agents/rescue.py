"""Replan proposal lifecycle and rescue orchestration."""
from __future__ import annotations

from datetime import time, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.agents.aggregate import score_candidates
from syncinerary.agents.solver.stage2_route import (
    SolverOptions,
    TransitProvider,
    solve_full_routes,
)
from syncinerary.config.solver import DEFAULT_DAY_END_HOUR, DEFAULT_DAY_START_HOUR
from syncinerary.diff.itinerary_diff import ItineraryDiff, itinerary_diff
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanStatus,
    ReplanTrigger,
    TripState,
    WishlistNotPlaced,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
    VoteRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.tools.transit import GoogleDirectionsClient, TransitLocation, haversine_km
from syncinerary.tools.weather import WeatherForecast

REPLAN_NEARBY_KM = 12.0
REPLAN_ALTERNATIVE_LIMIT = 8
FIXED_LOCK_REASONS = frozenset({"reservation", "paid_ticket", "flight", "check_in"})


class ReplanProposal(BaseModel):
    event: ReplanEvent
    version: ItineraryVersion
    diff: ItineraryDiff


class ReplanInputError(ValueError):
    """The disruption payload cannot identify one affected itinerary day."""


class ReplanNotFound(LookupError):
    """The event, traveler, or proposal chain does not exist for this trip."""


class ReplanAlreadyDecided(RuntimeError):
    """A pending proposal has already received its one final decision."""


class ReplanConflict(RuntimeError):
    """The proposal no longer points at the active itinerary version."""


def _payload_uuid(payload: dict[str, Any], key: str) -> UUID | None:
    raw = payload.get(key)
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        try:
            return UUID(raw)
        except ValueError:
            return None
    return None


def _payload_time(payload: dict[str, Any], key: str) -> time | None:
    raw = payload.get(key)
    if isinstance(raw, time):
        return raw
    if isinstance(raw, str):
        try:
            return time.fromisoformat(raw)
        except ValueError:
            return None
    return None


def select_affected_nodes(
    trigger_type: ReplanTrigger,
    trigger_payload: dict[str, Any],
    nodes: list[ItineraryNode],
    candidates: dict[UUID, CandidatePlace],
) -> list[ItineraryNode]:
    """Select directly disrupted rows; later shifts belong in the diff."""
    if trigger_type in {
        ReplanTrigger.RESERVATION_CANCELLED,
        ReplanTrigger.TRANSIT_DELAY,
        ReplanTrigger.PLACE_CLOSED,
    }:
        node_id = _payload_uuid(trigger_payload, "node_id")
        affected = [node for node in nodes if node.id == node_id]
    elif trigger_type is ReplanTrigger.OVERSLEPT:
        day = trigger_payload.get("day")
        actual_start = _payload_time(trigger_payload, "at")
        affected = [
            node
            for node in nodes
            if node.day == day
            and actual_start is not None
            and node.start_time < actual_start
        ]
    elif trigger_type is ReplanTrigger.WEATHER:
        day = trigger_payload.get("day")
        affected = [
            node
            for node in nodes
            if node.day == day
            and candidates.get(node.candidate_id) is not None
            and candidates[node.candidate_id].weather_dependent
        ]
    else:
        requested: set[UUID] = set()
        for raw in trigger_payload.get("affected_node_ids", []):
            parsed = _payload_uuid({"value": raw}, "value")
            if parsed is not None:
                requested.add(parsed)
        affected = [node for node in nodes if node.id in requested]

    if not affected:
        raise ReplanInputError("Disruption did not match any itinerary nodes")
    return sorted(affected, key=lambda node: (node.day, node.start_time, str(node.id)))


def _affected_day(affected: list[ItineraryNode]) -> int:
    days = {node.day for node in affected}
    if len(days) != 1:
        raise ReplanInputError("A replan can change only one day at a time")
    return next(iter(days))


def _cutoff(
    trigger_type: ReplanTrigger,
    payload: dict[str, Any],
    affected: list[ItineraryNode],
) -> time:
    if trigger_type is ReplanTrigger.OVERSLEPT:
        return _payload_time(payload, "at") or min(node.start_time for node in affected)
    if trigger_type is ReplanTrigger.TRANSIT_DELAY:
        delay = payload.get("delay_minutes")
        delay_minutes = delay if isinstance(delay, int) and delay > 0 else 0
        start = min(node.start_time for node in affected)
        minute = start.hour * 60 + start.minute + delay_minutes
        return time(min(23, minute // 60), minute % 60)
    if trigger_type is ReplanTrigger.WEATHER:
        return time(DEFAULT_DAY_START_HOUR)
    return min(node.start_time for node in affected)


def _unavailable_candidates(
    trigger_type: ReplanTrigger,
    affected: list[ItineraryNode],
) -> set[UUID]:
    if trigger_type in {
        ReplanTrigger.RESERVATION_CANCELLED,
        ReplanTrigger.PLACE_CLOSED,
        ReplanTrigger.WEATHER,
        ReplanTrigger.OTHER,
    }:
        return {node.candidate_id for node in affected}
    return set()


def _distance_from_day(
    candidate: CandidatePlace,
    day_candidates: list[CandidatePlace],
) -> float:
    if not day_candidates:
        return 0.0
    origin = TransitLocation(lat=candidate.lat, lng=candidate.lng)
    return min(
        haversine_km(origin, TransitLocation(lat=other.lat, lng=other.lng))
        for other in day_candidates
    )


async def _build_replan_proposal(
    session: AsyncSession,
    *,
    trip_id: UUID,
    trigger_type: ReplanTrigger,
    trigger_payload: dict[str, Any],
    transit_provider: TransitProvider,
) -> ReplanProposal:
    versions = ItineraryVersionRepository(session)
    active = await versions.get_active(trip_id)
    if active is None:
        raise ReplanInputError("Trip has no active itinerary to replan")

    old_nodes = await ItineraryNodeRepository(session).list_for_version(active.id)
    all_candidates = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    candidate_by_id = {candidate.id: candidate for candidate in all_candidates}
    affected = select_affected_nodes(
        trigger_type,
        trigger_payload,
        old_nodes,
        candidate_by_id,
    )
    day = _affected_day(affected)
    cutoff = _cutoff(trigger_type, trigger_payload, affected)
    if cutoff >= time(DEFAULT_DAY_END_HOUR):
        raise ReplanInputError("Disruption leaves no time to replan the affected day")

    unavailable = _unavailable_candidates(trigger_type, affected)
    affected_ids = {node.id for node in affected}
    day_nodes = [node for node in old_nodes if node.day == day]
    prefix = [
        node
        for node in day_nodes
        if node.end_time <= cutoff and node.id not in affected_ids
    ]
    suffix_nodes = [node for node in day_nodes if node not in prefix]
    suffix_candidates = [
        candidate_by_id[node.candidate_id]
        for node in suffix_nodes
        if node.candidate_id not in unavailable and node.candidate_id in candidate_by_id
    ]

    scheduled_ids = {node.candidate_id for node in old_nodes}
    current_day_candidates = [
        candidate_by_id[node.candidate_id]
        for node in day_nodes
        if node.candidate_id in candidate_by_id
    ]
    votes = await VoteRepository(session).list_for_trip(trip_id)
    travelers = await TravelerRepository(session).list_for_trip(trip_id)
    scores = score_candidates(all_candidates, votes, len(travelers))
    score_by_id = {score.candidate_id: score for score in scores}
    day_cities = {
        city
        for candidate in current_day_candidates
        if isinstance((city := candidate.enrichment.get("city")), str)
    }
    alternatives = [
        candidate
        for candidate in all_candidates
        if candidate.id not in scheduled_ids
        and candidate.id not in unavailable
        and candidate.type is not CandidateType.LODGING
        and (not day_cities or candidate.enrichment.get("city") in day_cities)
        and _distance_from_day(candidate, current_day_candidates) <= REPLAN_NEARBY_KM
    ]
    alternatives.sort(
        key=lambda candidate: (
            -score_by_id[candidate.id].score if candidate.id in score_by_id else 0.0,
            _distance_from_day(candidate, current_day_candidates),
            candidate.name_canonical,
        )
    )
    alternatives = alternatives[:REPLAN_ALTERNATIVE_LIMIT]

    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise ReplanNotFound("Trip does not exist")
    affected_date = trip.start_date + timedelta(days=day)
    one_day_trip = trip.model_copy(
        update={"start_date": affected_date, "end_date": affected_date, "days": 1}
    )
    candidate_pool = list(
        {candidate.id: candidate for candidate in [*suffix_candidates, *alternatives]}.values()
    )
    required = {
        candidate.id
        for candidate in suffix_candidates
        if any(
            node.candidate_id == candidate.id
            and (node.fixed or node.lock_reason in FIXED_LOCK_REASONS)
            for node in suffix_nodes
        )
    }
    state = TripState(
        trip=one_day_trip,
        travelers=travelers,
        candidates=candidate_pool,
        votes=votes,
        candidate_scores=[
            score_by_id[candidate.id]
            for candidate in candidate_pool
            if candidate.id in score_by_id
        ],
        day_start=cutoff,
        day_end=time(DEFAULT_DAY_END_HOUR),
    )
    # End the read-only transaction before the external transit lookup. The
    # active version is locked and revalidated after routing, before writes.
    await session.commit()
    result = await solve_full_routes(
        state,
        candidate_pool,
        transit_provider,
        weather=WeatherForecast(),
        options=SolverOptions(
            day_start=cutoff,
            day_end=time(DEFAULT_DAY_END_HOUR),
            timezone=trip.timezone or "Asia/Tokyo",
        ),
        must_go_ids=required,
    )

    locked_active = await versions.get_many_for_update([active.id])
    current_active = await versions.get_active(trip.id)
    if (
        len(locked_active) != 1
        or locked_active[0].status is not ItineraryStatus.ACTIVE
        or current_active is None
        or current_active.id != active.id
    ):
        raise ReplanConflict("Active itinerary changed while the rescue plan was running")
    version = await versions.add(
        ItineraryVersion(
            trip_id=trip.id,
            version_no=await versions.next_version_no(trip.id),
            status=ItineraryStatus.PROPOSED,
            parent_version_id=active.id,
            objective_breakdown={
                **result.stage1_objective,
                "placed_count": float(result.placed_count + len(prefix)),
                "total_transit_minutes": float(result.total_transit_minutes),
            },
        )
    )
    proposed_nodes = [
        ItineraryNode(
            version_id=version.id,
            candidate_id=node.candidate_id,
            day=node.day,
            start_time=node.start_time,
            end_time=node.end_time,
            fixed=node.fixed,
            lock_reason=node.lock_reason,
            transit_from_prev_min=node.transit_from_prev_min,
            transit_from_prev_mode=node.transit_from_prev_mode,
            notes_for_travelers=node.notes_for_travelers,
        )
        for node in old_nodes
        if node.day != day or node in prefix
    ]
    proposed_nodes.extend(
        ItineraryNode(
            version_id=version.id,
            candidate_id=stop.candidate_id,
            day=day,
            start_time=time(stop.start_minute // 60, stop.start_minute % 60),
            end_time=time(stop.end_minute // 60, stop.end_minute % 60),
            transit_from_prev_min=stop.transit_from_prev_min,
            transit_from_prev_mode=stop.transit_from_prev_mode,
            fixed=stop.candidate_id in required,
            lock_reason="reservation" if stop.candidate_id in required else None,
        )
        for route in result.routes
        for stop in route.stops
    )
    await ItineraryNodeRepository(session).add_many(proposed_nodes)

    old_wishlist = await WishlistNotPlacedRepository(session).list_for_version(active.id)
    proposed_ids = {node.candidate_id for node in proposed_nodes}
    wishlist_by_candidate = {
        item.candidate_id: item.model_copy(update={"version_id": version.id})
        for item in old_wishlist
        if item.candidate_id not in proposed_ids
    }
    for item in result.wishlist([candidate.id for candidate in candidate_pool]):
        wishlist_by_candidate[item.candidate_id] = WishlistNotPlaced(
            version_id=version.id,
            candidate_id=item.candidate_id,
            reason_code=item.reason_code,
            reason_text=item.reason_text,
        )
    await WishlistNotPlacedRepository(session).add_many(list(wishlist_by_candidate.values()))

    diff = itinerary_diff(old_nodes, proposed_nodes)
    new_candidate_ids = {item.candidate_id for item in diff.added}
    alternatives_trace = []
    for candidate in alternatives:
        distance = _distance_from_day(candidate, current_day_candidates)
        score = score_by_id.get(candidate.id)
        vote_score = score.score if score is not None else 0.0
        chosen = candidate.id in new_candidate_ids
        measurement = (
            f"{distance:.1f} km detour, fatigue {candidate.fatigue_cost}, "
            f"vote score {vote_score:.2f}"
        )
        alternatives_trace.append(
            {
                "candidate_id": str(candidate.id),
                "score": vote_score,
                "chosen": chosen,
                "reason": measurement if chosen else None,
                "rejected_reason": None if chosen else measurement,
            }
        )
    trace = {
        "trigger": {"type": trigger_type.value, **trigger_payload},
        "affected_nodes": [
            {
                "node_id": str(node.id),
                "candidate_id": str(node.candidate_id),
                "classification": (
                    "fixed"
                    if node.fixed or node.lock_reason in FIXED_LOCK_REASONS
                    else "movable"
                ),
            }
            for node in affected
        ],
        "alternatives_considered": alternatives_trace,
        "downstream_changes": [
            {
                "candidate_id": str(item.candidate_id),
                "old_time": item.old_start_time.isoformat(timespec="minutes"),
                "new_time": item.new_start_time.isoformat(timespec="minutes"),
            }
            for item in diff.time_changed
        ],
    }
    event = await ReplanEventRepository(session).add(
        ReplanEvent(
            trip_id=trip.id,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
            affected_node_ids=[node.id for node in affected],
            trace_json=trace,
            proposed_version_id=version.id,
        )
    )
    return ReplanProposal(event=event, version=version, diff=diff)


async def create_replan_proposal(
    session: AsyncSession,
    *,
    trip_id: UUID,
    trigger_type: ReplanTrigger,
    trigger_payload: dict[str, Any],
    transit_provider: TransitProvider | None = None,
) -> ReplanProposal:
    """Create a pending append-only proposal while leaving active unchanged."""
    if transit_provider is not None:
        return await _build_replan_proposal(
            session,
            trip_id=trip_id,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
            transit_provider=transit_provider,
        )
    async with GoogleDirectionsClient() as live_transit:
        return await _build_replan_proposal(
            session,
            trip_id=trip_id,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
            transit_provider=live_transit,
        )


async def decide_replan(
    session: AsyncSession,
    *,
    trip_id: UUID,
    event_id: UUID,
    traveler_id: UUID,
    approve: bool,
) -> ReplanEvent:
    """Apply one short, atomic approval or rejection transition.

    The event is locked first, followed by both version rows in stable ID
    order. No external call happens while these locks are held.
    """
    traveler = await TravelerRepository(session).get(traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise ReplanNotFound("Traveler is not part of this trip")

    events = ReplanEventRepository(session)
    event = await events.get_for_update(event_id)
    if event is None or event.trip_id != trip_id:
        raise ReplanNotFound("Replan event does not exist for this trip")
    if event.status is not ReplanStatus.PENDING:
        raise ReplanAlreadyDecided("Replan event has already been decided")
    if event.proposed_version_id is None:
        raise ReplanConflict("Replan event has no proposed itinerary")

    versions = ItineraryVersionRepository(session)
    proposal = await versions.get(event.proposed_version_id)
    if (
        proposal is None
        or proposal.trip_id != trip_id
        or proposal.parent_version_id is None
    ):
        raise ReplanConflict("Proposed itinerary chain is invalid")

    locked = {
        version.id: version
        for version in await versions.get_many_for_update(
            [proposal.parent_version_id, proposal.id]
        )
    }
    parent = locked.get(proposal.parent_version_id)
    proposal = locked.get(proposal.id)
    if parent is None or proposal is None:
        raise ReplanConflict("Proposed itinerary chain is incomplete")
    if proposal.status is not ItineraryStatus.PROPOSED:
        raise ReplanConflict("Proposed itinerary is no longer pending")
    if parent.status is not ItineraryStatus.ACTIVE:
        raise ReplanConflict("The proposal is based on a stale itinerary")

    if approve:
        await versions.set_status(parent.id, ItineraryStatus.SUPERSEDED)
        await versions.set_status(proposal.id, ItineraryStatus.ACTIVE)
        decision = ReplanStatus.APPROVED
    else:
        await versions.set_status(proposal.id, ItineraryStatus.REJECTED)
        decision = ReplanStatus.REJECTED

    decided = await events.decide(event.id, decision, traveler_id)
    if decided is None:
        raise ReplanNotFound("Replan event disappeared during decision")
    return decided


__all__ = [
    "ReplanAlreadyDecided",
    "ReplanConflict",
    "ReplanInputError",
    "ReplanNotFound",
    "ReplanProposal",
    "create_replan_proposal",
    "decide_replan",
    "select_affected_nodes",
]
