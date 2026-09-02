"""The three scorer families from CLAUDE.md section 12.3.

| Family | Verdict | What it is for |
|---|---|---|
| Feasibility | pass or fail | A violated hard constraint fails the eval outright |
| Quality | scored 0 to 1 | Tracked across commits so a regression is visible |
| Harness health | pass or fail | The run itself behaved: no budget blown, no loop |

Every scorer here is deterministic. That is a deliberate constraint, not a
shortcut: this suite runs on every pull request and has five minutes to
answer whether a change made the agent better or worse, and a model-judged
metric would add latency, cost, and noise to exactly the signal being
measured. The one model-written artifact, the narrative, is checked for
groundedness against the itinerary rather than judged for style.

No LLM import belongs in this module (CLAUDE.md section 2).
"""
from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from syncinerary.agents.gather.dietary import hard_dietary_exclusions
from syncinerary.agents.solver.stage2_route import SolverResult
from syncinerary.config.solver import (
    DAILY_FATIGUE_BUDGET,
    DAY_DURATION_CAP_HOURS,
    REQUIRED_MEALS,
    WALKING_MINUTES_PER_DAY,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Vote,
    VoteSignal,
)
from syncinerary.eval.fixtures import WEEKDAYS, LoadedFixture

#: How much a quality metric may drop against the previous commit before the
#: runner calls it a regression. Small enough to catch a real change, loose
#: enough that solver tie-breaking noise does not fail a pull request.
QUALITY_TOLERANCE = 0.02


class CheckResult(BaseModel):
    """One pass-or-fail check, with enough detail to act on a failure."""

    name: str
    passed: bool
    detail: str = ""

    @property
    def line(self) -> str:
        return f"{'ok  ' if self.passed else 'FAIL'} {self.name}: {self.detail}".rstrip(": ")


class ScoreResult(BaseModel):
    """One measured ratio, between 0 and 1, higher is better."""

    name: str
    value: float = Field(ge=0.0, le=1.0)
    detail: str = ""


class FixtureScores(BaseModel):
    feasibility: list[CheckResult] = Field(default_factory=list)
    quality: list[ScoreResult] = Field(default_factory=list)
    harness: list[CheckResult] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.feasibility + self.harness)

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.feasibility + self.harness if not check.passed]

    def quality_map(self) -> dict[str, float]:
        return {score.name: round(score.value, 4) for score in self.quality}

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "feasibility": [check.model_dump() for check in self.feasibility],
            "quality": self.quality_map(),
            "harness": [check.model_dump() for check in self.harness],
        }


# ----------------------------------------------------------------- helpers


def _weekday_key(value: date) -> str:
    return WEEKDAYS[value.weekday()]


def _open_windows(candidate: CandidatePlace, day_date: date) -> list[list[int]]:
    return candidate.hours_by_weekday.get(_weekday_key(day_date), [])


def _placed_ids(result: SolverResult) -> set[UUID]:
    return {stop.candidate_id for route in result.routes for stop in route.stops}


def _liked_by_traveler(votes: list[Vote]) -> dict[UUID, set[UUID]]:
    liked: dict[UUID, set[UUID]] = {}
    positive = {VoteSignal.LIKE, VoteSignal.LIKE_WITH_NOTE, VoteSignal.MUST_HAVE}
    for vote in votes:
        if vote.signal in positive:
            liked.setdefault(vote.traveler_id, set()).add(vote.candidate_id)
    return liked


# ------------------------------------------------------------- feasibility


def score_feasibility(
    fixture: LoadedFixture,
    result: SolverResult,
    *,
    shortlisted: list[UUID],
    must_go_ids: set[UUID],
    pinned_days: dict[UUID, int],
) -> list[CheckResult]:
    """Hard constraints. Any failure here fails the whole eval."""
    by_id = {candidate.id: candidate for candidate in fixture.candidates}
    placed = _placed_ids(result)
    checks: list[CheckResult] = []

    # A candidate on two days is not a scheduling preference, it is a bug.
    seen: list[UUID] = [stop.candidate_id for route in result.routes for stop in route.stops]
    duplicates = {value for value in seen if seen.count(value) > 1}
    checks.append(
        CheckResult(
            name="no_duplicate_stops",
            passed=not duplicates,
            detail=", ".join(fixture.slugs(sorted(duplicates, key=str))),
        )
    )

    exclusions = hard_dietary_exclusions(fixture.constraints)
    conflicts = [
        candidate_id
        for candidate_id in placed
        if (candidate := by_id.get(candidate_id)) is not None
        and candidate.type is CandidateType.FOOD
        and exclusions.intersection(tag.casefold() for tag in candidate.dietary_tags)
    ]
    checks.append(
        CheckResult(
            name="no_hard_dietary_conflict",
            passed=not conflicts,
            detail=", ".join(fixture.slugs(sorted(conflicts, key=str))),
        )
    )

    missing_must_go = sorted(must_go_ids - placed, key=str)
    checks.append(
        CheckResult(
            name="must_go_placed",
            passed=not missing_must_go,
            detail=", ".join(fixture.slugs(missing_must_go)),
        )
    )

    over_budget: list[str] = []
    for route in result.routes:
        load = sum(
            by_id[stop.candidate_id].fatigue_cost
            for stop in route.stops
            if stop.candidate_id in by_id
        )
        if load > DAILY_FATIGUE_BUDGET:
            over_budget.append(f"day {route.day + 1} at {load}")
    checks.append(
        CheckResult(
            name="fatigue_within_budget",
            passed=not over_budget,
            detail=f"cap {DAILY_FATIGUE_BUDGET}; " + ", ".join(over_budget) if over_budget else "",
        )
    )

    closed: list[str] = []
    for route in result.routes:
        day_date = fixture.trip.start_date + timedelta(days=route.day)
        for stop in route.stops:
            candidate = by_id.get(stop.candidate_id)
            if candidate is None:
                continue
            windows = _open_windows(candidate, day_date)
            if not windows:
                closed.append(f"{fixture.slugs_by_id.get(candidate.id)} (shut that weekday)")
                continue
            fits = any(
                start * 60 <= stop.start_minute and stop.end_minute <= end * 60
                for start, end in (window[:2] for window in windows)
            )
            if not fits:
                closed.append(fixture.slugs_by_id.get(candidate.id, str(candidate.id)))
    checks.append(
        CheckResult(name="stops_within_opening_hours", passed=not closed, detail=", ".join(closed))
    )

    overlaps: list[str] = []
    for route in result.routes:
        ordered = sorted(route.stops, key=lambda stop: stop.start_minute)
        for previous, current in pairwise(ordered):
            earliest = previous.end_minute + current.transit_from_prev_min
            if current.start_minute < earliest:
                overlaps.append(
                    f"day {route.day + 1}: {fixture.slugs_by_id.get(current.candidate_id)} "
                    f"starts {earliest - current.start_minute} min too early"
                )
    checks.append(
        CheckResult(name="transit_time_respected", passed=not overlaps, detail="; ".join(overlaps))
    )

    window_start = fixture.spec.day_start_hour * 60
    window_end = fixture.spec.day_end_hour * 60
    outside: list[str] = []
    too_long: list[str] = []
    for route in result.routes:
        if not route.stops:
            continue
        first = min(stop.start_minute for stop in route.stops)
        last = max(stop.end_minute for stop in route.stops)
        if first < window_start or last > window_end:
            outside.append(f"day {route.day + 1}")
        if last - first > DAY_DURATION_CAP_HOURS * 60:
            too_long.append(f"day {route.day + 1} at {(last - first) // 60}h")
    checks.append(
        CheckResult(name="days_within_window", passed=not outside, detail=", ".join(outside))
    )
    checks.append(
        CheckResult(
            name="days_within_active_cap",
            passed=not too_long,
            detail=f"cap {DAY_DURATION_CAP_HOURS}h; " + ", ".join(too_long) if too_long else "",
        )
    )

    misplaced = [
        fixture.slugs_by_id.get(candidate_id, str(candidate_id))
        for candidate_id, day in pinned_days.items()
        for route in result.routes
        for stop in route.stops
        if stop.candidate_id == candidate_id and route.day != day
    ]
    checks.append(
        CheckResult(name="pinned_days_honoured", passed=not misplaced, detail=", ".join(misplaced))
    )

    expected = fixture.spec.expected
    wanted = {fixture.ids_by_slug[slug] for slug in expected.must_include}
    banned = {fixture.ids_by_slug[slug] for slug in expected.must_exclude}
    checks.append(
        CheckResult(
            name="expected_includes_present",
            passed=wanted <= placed,
            detail=", ".join(fixture.slugs(sorted(wanted - placed, key=str))),
        )
    )
    checks.append(
        CheckResult(
            name="expected_excludes_absent",
            passed=not (banned & placed),
            detail=", ".join(fixture.slugs(sorted(banned & placed, key=str))),
        )
    )
    return checks


# ------------------------------------------------------------------ quality


def score_quality(
    fixture: LoadedFixture,
    result: SolverResult,
    *,
    shortlisted: list[UUID],
    must_go_ids: set[UUID],
) -> list[ScoreResult]:
    """Measured ratios, tracked across commits rather than gated."""
    by_id = {candidate.id: candidate for candidate in fixture.candidates}
    placed = _placed_ids(result)
    scores: list[ScoreResult] = []

    if must_go_ids:
        covered = len(must_go_ids & placed)
        scores.append(
            ScoreResult(
                name="must_go_coverage",
                value=covered / len(must_go_ids),
                detail=f"{covered}/{len(must_go_ids)}",
            )
        )

    # Consensus fairness is about the person who did worst, so this is a
    # minimum over travelers rather than a mean: a plan that delights three
    # people and strands the fourth is not a fair plan (CLAUDE.md 12.3).
    liked = _liked_by_traveler(fixture.votes)
    shortlist_set = set(shortlisted)
    shares: list[tuple[str, float]] = []
    for traveler in fixture.travelers:
        wanted = liked.get(traveler.id, set()) & shortlist_set
        if not wanted:
            continue
        shares.append((traveler.name, len(wanted & placed) / len(wanted)))
    if shares:
        worst_name, worst = min(shares, key=lambda entry: entry[1])
        scores.append(
            ScoreResult(
                name="worst_traveler_satisfaction",
                value=worst,
                detail=f"{worst_name} at {worst:.0%}",
            )
        )

    wanted_meals = len(result.routes) * len(REQUIRED_MEALS)
    if wanted_meals:
        scores.append(
            ScoreResult(
                name="meal_coverage",
                value=result.meal_coverage_count / wanted_meals,
                detail=f"{result.meal_coverage_count}/{wanted_meals} lunches and dinners",
            )
        )

    # An allowance rather than a target: a day that uses none of its walking
    # budget scores 1, a day that doubles it scores 0.
    if result.routes:
        allowance = WALKING_MINUTES_PER_DAY * len(result.routes)
        used = result.total_transit_minutes
        scores.append(
            ScoreResult(
                name="transit_efficiency",
                value=max(0.0, min(1.0, 1 - used / (allowance * 2))),
                detail=f"{used} min against a {allowance} min allowance",
            )
        )

    rainy = {
        index
        for index, day in enumerate(fixture.weather.days)
        if day.is_rainy
    }
    outdoor_stops = [
        (route.day, stop.candidate_id)
        for route in result.routes
        for stop in route.stops
        if (candidate := by_id.get(stop.candidate_id)) is not None and candidate.weather_dependent
    ]
    if rainy and outdoor_stops:
        dry = sum(1 for day, _ in outdoor_stops if day not in rainy)
        scores.append(
            ScoreResult(
                name="weather_fit",
                value=dry / len(outdoor_stops),
                detail=f"{dry}/{len(outdoor_stops)} exposed stops kept off rainy days",
            )
        )

    # Every shortlisted card the solver could not place has to say why, or
    # the itinerary cannot answer "where did my favourite go" (section 10.3).
    unplaced = result.wishlist(shortlisted)
    expected_unplaced = [value for value in shortlisted if value not in placed]
    if expected_unplaced:
        explained = sum(1 for item in unplaced if item.reason_code)
        scores.append(
            ScoreResult(
                name="wishlist_explained",
                value=min(1.0, explained / len(expected_unplaced)),
                detail=f"{explained}/{len(expected_unplaced)} carry a reason",
            )
        )
    return scores


# ---------------------------------------------------------- harness health


class HarnessObservations(BaseModel):
    """What the run reported about itself, collected by the runner."""

    budget_exceeded: bool = False
    loop_detected: bool = False
    unrecovered_tool_error: str | None = None
    step_count: int = 0
    max_steps: int = 0
    errors: list[str] = Field(default_factory=list)


def score_harness(observations: HarnessObservations) -> list[CheckResult]:
    return [
        CheckResult(
            name="within_budget",
            passed=not observations.budget_exceeded,
            detail=f"{observations.step_count} steps" if observations.step_count else "",
        ),
        CheckResult(
            name="no_loop_detected",
            passed=not observations.loop_detected,
        ),
        CheckResult(
            name="no_unrecovered_tool_error",
            passed=observations.unrecovered_tool_error is None,
            detail=observations.unrecovered_tool_error or "",
        ),
        CheckResult(
            name="run_completed",
            passed=not observations.errors,
            detail="; ".join(observations.errors),
        ),
    ]


# ------------------------------------------------- expectations and floors


def score_expected_floors(fixture: LoadedFixture, quality: list[ScoreResult]) -> list[CheckResult]:
    """A fixture may set a floor under any quality metric it cares about."""
    measured = {score.name: score.value for score in quality}
    checks: list[CheckResult] = []
    for name, floor in sorted(fixture.spec.expected.min_scores.items()):
        value = measured.get(name)
        if value is None:
            checks.append(
                CheckResult(
                    name=f"floor:{name}",
                    passed=False,
                    detail="the fixture sets a floor for a metric this run did not measure",
                )
            )
            continue
        checks.append(
            CheckResult(
                name=f"floor:{name}",
                passed=value >= floor,
                detail=f"{value:.2f} against a floor of {floor:.2f}",
            )
        )
    return checks


# --------------------------------------------------------------- narrative


def score_narrative(fixture: LoadedFixture, narrative: str, result: SolverResult) -> ScoreResult:
    """Groundedness, not style: does the narrative name places that are not
    in the itinerary.

    This is the failure that matters for an explainer whose whole job is to
    describe a decision someone else already made. It needs no judge, so it
    can run wherever the narrative exists.
    """
    by_id = {candidate.id: candidate for candidate in fixture.candidates}
    placed_names = {
        by_id[stop.candidate_id].name_canonical.casefold()
        for route in result.routes
        for stop in route.stops
        if stop.candidate_id in by_id
    }
    absent_names = {
        candidate.name_canonical.casefold()
        for candidate in fixture.candidates
        if candidate.name_canonical.casefold() not in placed_names
    }
    body = narrative.casefold()
    invented = sorted(name for name in absent_names if name in body)
    mentioned = sum(1 for name in placed_names if name in body)
    if not placed_names:
        return ScoreResult(name="narrative_grounded", value=0.0, detail="nothing was placed")
    grounded = mentioned / len(placed_names)
    penalty = min(1.0, len(invented) / max(1, len(placed_names)))
    return ScoreResult(
        name="narrative_grounded",
        value=max(0.0, grounded - penalty),
        detail=(
            f"{mentioned}/{len(placed_names)} placed stops named"
            + (f"; invented {', '.join(invented[:3])}" if invented else "")
        ),
    )


__all__ = [
    "QUALITY_TOLERANCE",
    "CheckResult",
    "FixtureScores",
    "HarnessObservations",
    "ScoreResult",
    "score_expected_floors",
    "score_feasibility",
    "score_harness",
    "score_narrative",
    "score_quality",
]
