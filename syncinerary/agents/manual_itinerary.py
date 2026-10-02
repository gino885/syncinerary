"""Validate exact edits and create an append-only proposal without discovery."""

from datetime import time, timedelta
from itertools import pairwise
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.agents.gather.dietary import filter_dietary_conflicts
from syncinerary.agents.rescue import (
    FIXED_LOCK_REASONS,
    ReplanConflict,
    ReplanInputError,
    ReplanProposal,
)
from syncinerary.agents.solver.stage2_route import SolverOptions, TransitProvider, _solve_one_day
from syncinerary.config.solver import (
    DAILY_FATIGUE_BUDGET,
    DAY_DURATION_CAP_HOURS,
    M1_DESTINATION_TIMEZONE,
    WALKING_MINUTES_PER_DAY,
)
from syncinerary.diff.itinerary_diff import itinerary_diff
from syncinerary.domain.city_plan import city_day_counts
from syncinerary.domain.itinerary_edit import ItineraryEdit
from syncinerary.domain.models import (
    CandidateType,
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    ReplanEvent,
    ReplanTrigger,
    Trip,
    WishlistNotPlaced,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ReplanEventRepository,
    TravelerRepository,
    TripRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.tools.transit import make_transit_client


def minute(value: time) -> int:
    return value.hour * 60 + value.minute


def city_for_day(trip: Trip, day: int, *, existing_city: str | None = None) -> str:
    if not 0 <= day < trip.days:
        raise ReplanInputError("Choose a day within the trip dates")
    if not trip.city_days and existing_city in trip.cities:
        return existing_city
    offset = 0
    for city, count in zip(trip.cities or [trip.destination], city_day_counts(trip), strict=True):
        offset += count
        if day < offset:
            return city
    raise ReplanInputError("The city's day allocation is incomplete")


async def propose_edit(
    session: AsyncSession,
    *,
    trip_id: UUID,
    edit: ItineraryEdit,
    transit_provider: TransitProvider | None = None,
) -> ReplanProposal:
    if transit_provider is None:
        async with make_transit_client() as provider:
            return await propose_edit(
                session, trip_id=trip_id, edit=edit, transit_provider=provider
            )
    trip = await TripRepository(session).get(trip_id)
    traveler = await TravelerRepository(session).get(edit.traveler_id)
    if trip is None or traveler is None or traveler.trip_id != trip_id:
        raise ReplanInputError("Traveler is not part of this trip")
    versions = ItineraryVersionRepository(session)
    active = await versions.get_active(trip_id)
    if active is None or active.id != edit.base_version_id:
        raise ReplanConflict("The itinerary changed. Reload it before editing")
    events = ReplanEventRepository(session)
    if await events.list_pending(trip_id):
        raise ReplanConflict("Review the pending trip update before editing")
    old = await ItineraryNodeRepository(session).list_for_version(active.id)
    old_by_id = {n.candidate_id: n for n in old}
    requested = {s.candidate_id: s for s in edit.stops}
    candidates = {c.id: c for c in await CandidatePlaceRepository(session).list_for_trip(trip_id)}
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    allowed = {c.id for c in filter_dietary_conflicts(list(candidates.values()), constraints)}
    signature = lambda s: (s.day, s.start_time, s.end_time)
    for stop in edit.stops:
        if stop.candidate_id not in candidates or stop.candidate_id not in allowed:
            raise ReplanInputError(
                "The selected place is unavailable for this trip or conflicts with dietary rules"
            )
        candidate = candidates[stop.candidate_id]
        if candidate.type is CandidateType.LODGING:
            raise ReplanInputError("Choose a place or meal rather than a lodging option")
        existing_cities = {
            candidates[n.candidate_id].enrichment.get("city") for n in old if n.day == stop.day
        } - {None}
        city = city_for_day(
            trip,
            stop.day,
            existing_city=(next(iter(existing_cities)) if len(existing_cities) == 1 else None),
        )
        recorded_city = candidate.enrichment.get("city")
        if recorded_city and recorded_city != city:
            raise ReplanInputError(
                f"{candidate.name_canonical} is in {recorded_city}; day {stop.day + 1} is in {city}"
            )
        if not recorded_city and len(trip.cities) > 1:
            previous = old_by_id.get(stop.candidate_id)
            if previous is None or previous.day != stop.day:
                raise ReplanInputError("Confirm this place's city before moving or adding it")
    for node in old:
        if node.fixed or node.lock_reason in FIXED_LOCK_REASONS:
            updated = requested.get(node.candidate_id)
            if updated is None or signature(updated) != signature(node):
                raise ReplanInputError(
                    f"{candidates[node.candidate_id].name_canonical} has a fixed reservation and cannot be moved or removed"
                )
    changed = set(edit.adjust_days)
    if any(day >= trip.days for day in changed):
        raise ReplanInputError("Choose a day within the trip dates")
    for candidate_id in old_by_id.keys() | requested.keys():
        before, after = old_by_id.get(candidate_id), requested.get(candidate_id)
        if before is None or after is None or signature(before) != signature(after):
            if before:
                changed.add(before.day)
            if after:
                changed.add(after.day)
    if not changed:
        raise ReplanInputError("Make a change before previewing")
    options = SolverOptions(
        day_start=time(
            int(active.objective_breakdown.get("day_start_minute", 480)) // 60,
            int(active.objective_breakdown.get("day_start_minute", 480)) % 60,
        ),
        day_end=time(
            int(active.objective_breakdown.get("day_end_minute", 1260)) // 60,
            int(active.objective_breakdown.get("day_end_minute", 1260)) % 60,
        ),
        day_duration_cap_hours=int(
            active.objective_breakdown.get("day_duration_cap_minutes", DAY_DURATION_CAP_HOURS * 60)
        )
        // 60,
        timezone=trip.timezone or M1_DESTINATION_TIMEZONE,
    )
    planned = [n for n in old if n.day not in changed]
    # Release the read transaction before provider calls. Recheck the version
    # and pending event under its lock before any proposal writes.
    await session.commit()
    for day in sorted(changed):
        stops = sorted((s for s in edit.stops if s.day == day), key=lambda s: s.start_time)
        if len(stops) > 20:
            raise ReplanInputError("A day can contain at most 20 stops")
        if not stops:
            continue
        if day not in edit.adjust_days:
            for left, right in pairwise(stops):
                if left.end_time > right.start_time:
                    raise ReplanInputError(
                        f"Day {day + 1}: {candidates[right.candidate_id].name_canonical} overlaps another stop"
                    )
        pool = [
            candidates[s.candidate_id].model_copy(
                update={
                    "duration_estimate_min": minute(s.end_time) - minute(s.start_time),
                }
            )
            for s in stops
        ]
        if sum(max(1, c.fatigue_cost) for c in pool) > DAILY_FATIGUE_BUDGET:
            raise ReplanInputError(
                f"Day {day + 1} exceeds the daily activity limit; move a stop to another day"
            )
        fixed = {
            s.candidate_id: minute(s.start_time)
            for s in stops
            if day not in edit.adjust_days
            or (
                s.candidate_id in old_by_id
                and (
                    old_by_id[s.candidate_id].fixed
                    or old_by_id[s.candidate_id].lock_reason in FIXED_LOCK_REASONS
                )
            )
        }
        try:
            route = await _solve_one_day(
                pool,
                day=day,
                trip_date=trip.start_date + timedelta(days=day),
                transit_provider=transit_provider,
                options=options,
                required_candidate_ids={s.candidate_id for s in stops},
                fixed_start_minutes=fixed,
            )
        except RuntimeError as exc:
            raise ReplanInputError(
                f"Could not validate day {day + 1}: {exc}. Check the times and try again, or use Adjust this day"
            ) from exc
        if {s.candidate_id for s in route.stops} != {s.candidate_id for s in stops}:
            raise ReplanInputError(f"Day {day + 1} cannot fit every selected stop")
        if (
            sum(
                s.transit_from_prev_min
                for s in route.stops
                if (s.transit_from_prev_mode or "").startswith("walk")
            )
            > WALKING_MINUTES_PER_DAY
        ):
            raise ReplanInputError(f"Day {day + 1} exceeds the daily walking limit")
        for stop in route.stops:
            previous = old_by_id.get(stop.candidate_id)
            planned.append(
                ItineraryNode(
                    version_id=active.id,
                    candidate_id=stop.candidate_id,
                    day=day,
                    start_time=time(stop.start_minute // 60, stop.start_minute % 60),
                    end_time=time(stop.end_minute // 60, stop.end_minute % 60),
                    fixed=previous.fixed if previous else False,
                    lock_reason=previous.lock_reason if previous else None,
                    notes_for_travelers=previous.notes_for_travelers if previous else {},
                    transit_from_prev_min=stop.transit_from_prev_min,
                    transit_from_prev_mode=stop.transit_from_prev_mode,
                    transit_from_prev_provider=stop.transit_from_prev_provider,
                )
            )
    await versions.get_many_for_update([active.id])
    current = await versions.get_active(trip_id)
    if current is None or current.id != active.id or await events.list_pending(trip_id):
        raise ReplanConflict("The itinerary changed while checking your edit. Reload and try again")
    version = await versions.add(
        ItineraryVersion(
            trip_id=trip_id,
            version_no=await versions.next_version_no(trip_id),
            status=ItineraryStatus.PROPOSED,
            parent_version_id=active.id,
            objective_breakdown={
                "day_start_minute": float(minute(options.day_start)),
                "day_end_minute": float(minute(options.day_end)),
                "day_duration_cap_minutes": float(options.day_duration_cap_hours * 60),
                "manual_edit": 1.0,
                "placed_count": float(len(planned)),
                "total_transit_minutes": float(sum(n.transit_from_prev_min for n in planned)),
            },
        )
    )

    nodes = [n.model_copy(update={"id": uuid4(), "version_id": version.id}) for n in planned]
    await ItineraryNodeRepository(session).add_many(nodes)
    placed = {n.candidate_id for n in nodes}
    wishlist = {
        w.candidate_id: w
        for w in await WishlistNotPlacedRepository(session).list_for_version(active.id)
        if w.candidate_id not in placed
    }
    for node in old:
        if node.candidate_id not in placed:
            wishlist[node.candidate_id] = WishlistNotPlaced(
                version_id=version.id,
                candidate_id=node.candidate_id,
                reason_code="user_removed",
                reason_text="Removed from the plan by a traveler",
            )
    await WishlistNotPlacedRepository(session).add_many(
        [w.model_copy(update={"version_id": version.id}) for w in wishlist.values()]
    )
    diff = itinerary_diff(old, nodes)
    payload = {"manual_edit": True, "traveler_id": str(edit.traveler_id), "days": sorted(changed)}
    event = await events.add(
        ReplanEvent(
            trip_id=trip_id,
            trigger_type=ReplanTrigger.USER_REQUEST,
            trigger_payload=payload,
            proposed_version_id=version.id,
            affected_node_ids=[n.id for n in old if n.day in changed],
            trace_json={
                "trigger": {"type": "user_request", **payload},
                "affected_nodes": [],
                "alternatives_considered": [],
                "downstream_changes": [],
            },
        )
    )
    return ReplanProposal(event=event, version=version, diff=diff)
