"""Real gaps reserved for meals without selecting an unapproved restaurant."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from syncinerary.config.schedule import SCHEDULE_QUANTUM_MINUTES, ceil_slot
from syncinerary.config.solver import DAY_DURATION_CAP_HOURS, MEAL_WINDOWS, REQUIRED_MEALS
from syncinerary.domain.models import CandidatePlace, CandidateType

MEAL_BREAK_MINUTES = 60


def is_meal_candidate(candidate: CandidatePlace) -> bool:
    """Drinks-only nightlife is an ordinary visit, not a meal reservation."""
    return candidate.type is CandidateType.FOOD and candidate.category not in {
        "bar", "night_club",
    }


class TimedStop(Protocol):
    start_minute: int
    end_minute: int
    transit_from_prev_min: int
    meal_slot: str | None


class MealBreak(BaseModel):
    meal: str
    start_minute: int
    end_minute: int


def available_meal_breaks(
    stops: list[TimedStop], *, day_start: int, day_end: int,
    duration_cap_minutes: int = DAY_DURATION_CAP_HOURS * 60,
) -> list[MealBreak]:
    """Choose free meal hours within one capped span shared with the visits.

    Incoming transit is occupied time too. This also safely reads older
    itineraries: a day with no free hour never claims a reserved meal.
    Slide the active span forward if an early lunch would exclude dinner or
    a late pin. Prefer covering more meals, then the earliest feasible gaps.
    """
    occupied = sorted((s.start_minute - s.transit_from_prev_min, s.end_minute)
                      for s in stops)
    missing = [meal for meal in REQUIRED_MEALS
               if not any(s.meal_slot == meal for s in stops)]
    earliest = max(day_start, max((right for _, right in occupied), default=day_start)
                   - duration_cap_minutes)
    latest = min((left for left, _ in occupied), default=day_end)
    best: list[MealBreak] = []
    for span_start in range(ceil_slot(earliest), min(latest, day_end) + 1, SCHEDULE_QUANTUM_MINUTES):
        breaks = []
        for meal in missing:
            start, end = MEAL_WINDOWS[meal]
            cursor = ceil_slot(max(span_start, start * 60))
            limit = min(day_end, end * 60, span_start + duration_cap_minutes)
            for left, right in occupied:
                if cursor + MEAL_BREAK_MINUTES <= left:
                    break
                if right > cursor and left < cursor + MEAL_BREAK_MINUTES:
                    cursor = ceil_slot(right)
            if cursor + MEAL_BREAK_MINUTES <= limit:
                breaks.append(MealBreak(meal=meal, start_minute=cursor,
                                        end_minute=cursor + MEAL_BREAK_MINUTES))
        if len(breaks) > len(best):
            best = breaks
        if len(best) == len(missing):
            break
    return best
