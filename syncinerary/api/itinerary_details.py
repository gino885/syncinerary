"""Directions and meal-break presentation derived from the saved timetable."""
from __future__ import annotations

from datetime import time
from urllib.parse import urlencode
from uuid import UUID

from syncinerary.agents.solver.meal_breaks import available_meal_breaks
from syncinerary.agents.solver.stage2_route import ScheduledStop
from syncinerary.api.schemas import ItineraryStopOut, MealBreakOut
from syncinerary.domain.models import CandidatePlace


def directions_url(
    origin: CandidatePlace, destination: CandidatePlace, mode: str | None,
) -> str:
    travelmode = "transit"
    if mode in {"walk", "walking", "walking_estimated"}:
        travelmode = "walking"
    elif mode == "taxi":
        travelmode = "driving"
    params = {"api": "1", "origin": f"{origin.lat},{origin.lng}",
              "destination": f"{destination.lat},{destination.lng}", "travelmode": travelmode}
    for prefix, place in (("origin", origin), ("destination", destination)):
        if place_id := place.enrichment.get("google_place_id"):
            params[f"{prefix}_place_id"] = place_id
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def meal_breaks_for_day(
    stops: list[ItineraryStopOut], candidates: dict[UUID, CandidatePlace],
    *, day_start: int, day_end: int, duration_cap_minutes: int = 720,
    fallback_query: str | None = None,
) -> list[MealBreakOut]:
    timed = [ScheduledStop(candidate_id=s.candidate_id, day=0,
              start_minute=s.start_time.hour * 60 + s.start_time.minute,
              end_minute=s.end_time.hour * 60 + s.end_time.minute,
              transit_from_prev_min=s.transit_from_prev_min,
              transit_from_prev_mode=s.transit_from_prev_mode, meal_slot=s.meal_slot)
             for s in stops]
    result = []
    for gap in available_meal_breaks(
        timed, day_start=day_start, day_end=day_end, duration_cap_minutes=duration_cap_minutes
    ):
        place = None
        if timed:
            previous = [s for s in timed if s.end_minute <= gap.start_minute]
            anchor = max(previous, key=lambda s: s.end_minute) if previous else min(
                timed, key=lambda s: s.start_minute)
            place = candidates.get(anchor.candidate_id)
        query = (
            f"restaurants near {place.lat},{place.lng}"
            if place is not None else (
                f"restaurants near {fallback_query}" if fallback_query else None
            )
        )
        if query is None:
            continue
        result.append(MealBreakOut(
            meal=gap.meal, start_time=time(*divmod(gap.start_minute, 60)),
            end_time=time(*divmod(gap.end_minute, 60)),
            nearby_url="https://www.google.com/maps/search/?" + urlencode({
                "api": "1", "query": query}),
        ))
    return result
