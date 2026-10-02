from datetime import date, time

import pytest
from pydantic import ValidationError

from syncinerary.agents.solver.stage2_route import SolverOptions, solve_day
from syncinerary.api.schemas import PlanRequest
from tests.test_m1_solver import _matrix, _place


def test_half_hour_grid_buffers_exact_transit_and_rounds_occupancy_up():
    first = _place("First", 43, 141, duration=43)
    second = _place("Second", 43.001, 141.001, duration=61)
    route = solve_day(
        [first, second],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=_matrix([first, second], {("First", "Second"): 13}),
        options=SolverOptions(day_start=time(8), day_end=time(11)),
        required_candidate_ids={first.id, second.id},
        fixed_start_minutes={first.id: 480},
    )
    assert len(route.stops) == 2
    assert all(s.start_minute % 30 == s.end_minute % 30 == 0 for s in route.stops)
    assert route.stops[1].start_minute >= route.stops[0].end_minute + 13
    assert route.stops[1].transit_from_prev_min == 13


def test_opening_at_quarter_past_uses_next_half_hour():
    candidate = _place("Museum", 43, 141).model_copy(
        update={"hours_by_weekday": {"thu": [[10.25, 12]]}}
    )
    route = solve_day([candidate], day=0, trip_date=date(2026, 5, 21), transit=_matrix([candidate]))
    assert route.stops[0].start_minute == 630


def test_manual_pin_and_api_window_reject_unsupported_minutes():
    with pytest.raises(ValidationError):
        PlanRequest(day_start=time(8, 13))
    candidate = _place("Museum", 43, 141)
    with pytest.raises(ValueError, match="30"):
        solve_day(
            [candidate],
            day=0,
            trip_date=date(2026, 5, 21),
            transit=_matrix([candidate]),
            fixed_start_minutes={candidate.id: 493},
        )


def test_fixed_half_hour_edit_and_meal_breaks_remain_on_grid():
    from syncinerary.agents.solver.meal_breaks import available_meal_breaks

    candidate = _place("Museum", 43, 141, duration=43)
    options = SolverOptions()
    route = solve_day(
        [candidate],
        day=0,
        trip_date=date(2026, 5, 21),
        transit=_matrix([candidate]),
        fixed_start_minutes={candidate.id: 630},
    )
    assert route.stops[0].start_minute == 630
    assert route.stops[0].end_minute == 690
    breaks = available_meal_breaks(
        route.stops, day_start=options.day_start.hour * 60, day_end=options.day_end.hour * 60
    )
    assert breaks
    assert all(b.start_minute % 30 == b.end_minute % 30 == 0 for b in breaks)


async def test_replan_persists_half_hour_clocks(session):
    from syncinerary.agents.rescue import create_replan_proposal
    from syncinerary.domain.models import ReplanTrigger
    from syncinerary.store.repositories import ItineraryNodeRepository
    from tests.test_m6_rescue import StubAlternatives, StubTransit, _seed_scheduled_trip

    trip, _, old_nodes = await _seed_scheduled_trip(session, days=1)
    proposal = await create_replan_proposal(
        session,
        trip_id=trip.id,
        trigger_type=ReplanTrigger.PLACE_CLOSED,
        trigger_payload={"node_id": str(old_nodes[0].id)},
        transit_provider=StubTransit(),
        alternative_provider=StubAlternatives(),
    )
    nodes = await ItineraryNodeRepository(session).list_for_version(proposal.version.id)
    assert nodes
    assert all(n.start_time.minute in {0, 30} and n.end_time.minute in {0, 30} for n in nodes)
