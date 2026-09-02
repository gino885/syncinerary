"""Running one fixture end to end and scoring what came back.

Two kinds of case, because the two things being measured are different:

- A **plan case** drives the deterministic pipeline directly. Consensus
  scoring, shortlist selection, then the two-stage solver. No database, no
  network, no model.
- A **replan case** has to seed an active itinerary first, because the rescue
  agent reads one out of Postgres. It plans, persists, injects the fixture's
  disruption, and scores the proposal that comes back.

Both write into the same `FixtureScores` shape, so the runner does not care
which kind it just ran.
"""
from __future__ import annotations

import time as _time
from contextlib import nullcontext
from datetime import time as clock_time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from syncinerary.agents.aggregate import score_candidates
from syncinerary.agents.gather.dietary import filter_dietary_conflicts
from syncinerary.agents.rescue import ReplanProposal, create_replan_proposal
from syncinerary.agents.shortlist import build_shortlist
from syncinerary.agents.solver.stage2_route import SolverOptions, SolverResult, solve_full_routes
from syncinerary.domain.models import (
    ItineraryNode,
    ItineraryStatus,
    ItineraryVersion,
    TripState,
)
from syncinerary.eval.disruption import inject
from syncinerary.eval.fixtures import LoadedFixture
from syncinerary.eval.providers import DistanceTransitProvider, FixtureAlternativeProvider
from syncinerary.eval.sabotage import Sabotage
from syncinerary.eval.scorers import (
    CheckResult,
    FixtureScores,
    HarnessObservations,
    score_expected_floors,
    score_feasibility,
    score_harness,
    score_quality,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    TravelerRepository,
    TripRepository,
)


class CaseOutcome(BaseModel):
    """One fixture's run: what it scored and how long it took."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    fixture: str
    kind: str
    scores: FixtureScores
    seconds: float
    #: Present on plan cases, for the optional narrative check.
    solver_result: SolverResult | None = None
    state: TripState | None = None
    shortlisted: list[UUID] = Field(default_factory=list)


def _plan_inputs(
    fixture: LoadedFixture,
    sabotage: Sabotage | None,
) -> tuple[TripState, list, list[UUID], set[UUID], set[UUID], dict[UUID, int]]:
    """Consensus scoring, then the shortlist, then the solver's pins.

    Returns the group's must-go set and the solver's separately. They differ
    only under the `must-go` sabotage, which models a solver that ignores
    pins the group did mark: the scorer still knows what was promised.
    """
    state = fixture.state()
    pool = state.candidates
    if not (sabotage and sabotage.skips_dietary_filter):
        pool = filter_dietary_conflicts(pool, state.constraints)

    scores = score_candidates(pool, state.votes, len(state.travelers))
    shortlisted, _excluded = build_shortlist(scores, state.trip.days)
    by_id = {candidate.id: candidate for candidate in pool}
    selected = [by_id[value] for value in shortlisted if value in by_id]

    must_go = {
        fixture.ids_by_slug[slug]
        for slug in fixture.spec.expected.must_go
        if fixture.ids_by_slug[slug] in by_id
    }
    solver_must_go = set() if (sabotage and sabotage.drops_must_go) else set(must_go)
    pinned = {
        fixture.ids_by_slug[slug]: day
        for slug, day in fixture.spec.expected.pinned_days.items()
        if fixture.ids_by_slug[slug] in by_id
    }

    state = state.model_copy(update={"candidate_scores": scores})
    return state, selected, shortlisted, must_go, solver_must_go, pinned


async def run_plan_case(
    fixture: LoadedFixture,
    *,
    sabotage: Sabotage | None = None,
) -> CaseOutcome:
    """Score the deterministic pipeline on one planning fixture."""
    started = _time.perf_counter()
    transit = DistanceTransitProvider()
    observations = HarnessObservations()
    state, selected, shortlisted, must_go, solver_must_go, pinned = _plan_inputs(fixture, sabotage)

    options = SolverOptions(
        day_start=clock_time(fixture.spec.day_start_hour),
        day_end=clock_time(fixture.spec.day_end_hour),
    )
    try:
        with (sabotage.applied() if sabotage else nullcontext()):
            result = await solve_full_routes(
                state,
                selected,
                transit,
                weather=fixture.weather,
                options=options,
                must_go_ids=solver_must_go,
                pinned_days=pinned,
            )
    except Exception as exc:  # noqa: BLE001 - a crash is a result to record, not a reason to stop the suite
        observations.errors.append(f"{type(exc).__name__}: {exc}")
        return CaseOutcome(
            fixture=fixture.spec.name,
            kind="plan",
            scores=FixtureScores(harness=score_harness(observations)),
            seconds=_time.perf_counter() - started,
        )

    observations.step_count = transit.request_count
    feasibility = score_feasibility(
        fixture,
        result,
        shortlisted=shortlisted,
        must_go_ids=must_go,
        pinned_days=pinned,
    )
    quality = score_quality(fixture, result, shortlisted=shortlisted, must_go_ids=must_go)
    feasibility += score_expected_floors(fixture, quality)

    return CaseOutcome(
        fixture=fixture.spec.name,
        kind="plan",
        scores=FixtureScores(
            feasibility=feasibility,
            quality=quality,
            harness=score_harness(observations),
        ),
        seconds=_time.perf_counter() - started,
        solver_result=result,
        state=state,
        shortlisted=shortlisted,
    )


async def _seed_active_itinerary(session: Any, fixture: LoadedFixture, result: SolverResult) -> tuple[ItineraryVersion, list[ItineraryNode]]:
    """Persist the planned itinerary so the rescue agent has one to read."""
    trip = await TripRepository(session).add(fixture.trip)
    await TravelerRepository(session).add_many(fixture.travelers)
    if fixture.constraints:
        await ConstraintRepository(session).add_many(fixture.constraints)
    # Spares are stored too: the rescue agent resolves alternatives against
    # the trip's candidate rows, so an alternative it has never seen cannot
    # be scheduled.
    await CandidatePlaceRepository(session).add_many(fixture.candidates)

    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1, status=ItineraryStatus.ACTIVE)
    )
    nodes = await ItineraryNodeRepository(session).add_many(
        [
            ItineraryNode(
                version_id=version.id,
                candidate_id=stop.candidate_id,
                day=route.day,
                start_time=clock_time(stop.start_minute // 60, stop.start_minute % 60),
                end_time=clock_time(stop.end_minute // 60, stop.end_minute % 60),
                transit_from_prev_min=stop.transit_from_prev_min,
                transit_from_prev_mode=stop.transit_from_prev_mode,
            )
            for route in result.routes
            for stop in sorted(route.stops, key=lambda item: item.start_minute)
        ]
    )
    return version, nodes


def _score_replan(
    fixture: LoadedFixture,
    proposal: ReplanProposal,
    old_nodes: list[ItineraryNode],
) -> tuple[list[CheckResult], list]:
    """F4's own acceptance criteria, as eval checks."""
    diff = proposal.diff
    expected_day = fixture.spec.expected.replan_day
    changed_days = {stop.day for stop in diff.added + diff.removed}
    changed_days |= {move.old_day for move in diff.moved} | {move.new_day for move in diff.moved}
    changed_days |= {change.day for change in diff.time_changed}

    checks = [
        CheckResult(
            name="proposal_is_pending",
            passed=proposal.event.status.value == "pending",
            detail=proposal.event.status.value,
        ),
        CheckResult(
            name="active_version_untouched",
            passed=proposal.version.parent_version_id is not None
            and proposal.version.status.value == "proposed",
            detail=proposal.version.status.value,
        ),
        CheckResult(
            name="proposal_changes_something",
            passed=bool(changed_days),
            detail="the disruption produced an identical itinerary" if not changed_days else "",
        ),
    ]
    if expected_day is not None:
        stray = sorted(changed_days - {expected_day})
        checks.append(
            CheckResult(
                name="only_affected_day_changed",
                passed=not stray,
                detail=f"also changed day(s) {', '.join(str(day + 1) for day in stray)}"
                if stray
                else "",
            )
        )

    # CLAUDE.md 12.2: the trace has to give at least one quantified reason,
    # or the approval screen is asking for trust it has not earned. Which
    # field carries it depends on what the agent did. An overslept trip is
    # repaired by moving the stops the group already chose, so nothing is
    # picked and the quantified reasoning lives on the rejections instead.
    trace = proposal.event.trace_json
    alternatives = [
        entry for entry in trace.get("alternatives_considered", []) if isinstance(entry, dict)
    ]
    chosen = [entry for entry in alternatives if entry.get("chosen")]

    def quantified(entries: list[dict[str, Any]], field: str) -> bool:
        return any(
            isinstance(entry.get(field), str)
            and any(character.isdigit() for character in entry[field])
            for entry in entries
        )

    if chosen:
        passed = quantified(chosen, "reason")
        detail = "" if passed else "the chosen alternative carries no number"
    elif alternatives:
        passed = quantified(alternatives, "rejected_reason")
        detail = "" if passed else "nothing was chosen and no rejection carries a number"
    else:
        # Nothing was even considered, so the trace has to at least say what
        # moved, or it explains nothing at all.
        passed = bool(trace.get("downstream_changes"))
        detail = "" if passed else "the trace records neither an alternative nor a change"
    checks.append(
        CheckResult(name="trace_gives_a_quantified_reason", passed=passed, detail=detail)
    )
    return checks, []


async def run_replan_case(
    session: Any,
    fixture: LoadedFixture,
    *,
    sabotage: Sabotage | None = None,
) -> CaseOutcome:
    """Plan, persist, disrupt, and score the proposal."""
    started = _time.perf_counter()
    observations = HarnessObservations()
    plan = await run_plan_case(fixture, sabotage=sabotage)
    if plan.solver_result is None:
        return plan.model_copy(update={"kind": "replan"})

    transit = DistanceTransitProvider()
    try:
        _, nodes = await _seed_active_itinerary(session, fixture, plan.solver_result)
        assert fixture.spec.disruption is not None
        trigger, payload = inject(fixture.spec.disruption, nodes)
        proposal = await create_replan_proposal(
            session,
            trip_id=fixture.trip.id,
            trigger_type=trigger,
            trigger_payload=payload,
            transit_provider=transit,
            alternative_provider=FixtureAlternativeProvider(fixture.spares),
        )
    except Exception as exc:  # noqa: BLE001 - same: one broken fixture must not end the run
        observations.errors.append(f"{type(exc).__name__}: {exc}")
        return CaseOutcome(
            fixture=fixture.spec.name,
            kind="replan",
            scores=FixtureScores(
                feasibility=plan.scores.feasibility,
                quality=plan.scores.quality,
                harness=score_harness(observations),
            ),
            seconds=_time.perf_counter() - started,
        )

    observations.step_count = transit.request_count
    replan_checks, _ = _score_replan(fixture, proposal, nodes)
    return CaseOutcome(
        fixture=fixture.spec.name,
        kind="replan",
        scores=FixtureScores(
            feasibility=plan.scores.feasibility + replan_checks,
            quality=plan.scores.quality,
            harness=score_harness(observations),
        ),
        seconds=_time.perf_counter() - started,
        solver_result=plan.solver_result,
        state=plan.state,
        shortlisted=plan.shortlisted,
    )


__all__ = ["CaseOutcome", "run_plan_case", "run_replan_case"]
