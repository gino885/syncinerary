"""M7: the eval harness holds its own acceptance criteria (CLAUDE.md 12.3).

These are tests of the harness, not of the planner. The planner's behaviour
is what the harness measures; what has to be true here is that the harness
parses fixtures strictly, injects every trigger, scores what it claims to
score, and turns red when the planner is broken on purpose.
"""
from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest

from syncinerary.domain.models import ItineraryNode, ReplanTrigger
from syncinerary.eval import sabotage as sabotage_module
from syncinerary.eval.cases import run_plan_case
from syncinerary.eval.disruption import INJECTORS, DisruptionNotApplicable, inject, target_node
from syncinerary.eval.fixtures import (
    FIXTURE_DIR,
    DisruptionSpec,
    fixture_paths,
    load_all,
    load_by_name,
    parse_fixture,
)
from syncinerary.eval.providers import DistanceTransitProvider, leg_minutes
from syncinerary.eval.scorers import (
    CheckResult,
    FixtureScores,
    HarnessObservations,
    score_harness,
    score_narrative,
)
from syncinerary.tools.transit import TransitLocation

# ----------------------------------------------------------------- fixtures


def test_ten_fixtures_ship_and_every_one_parses():
    """CLAUDE.md 12.3 asks for at least ten."""
    paths = fixture_paths()
    assert len(paths) >= 10, [path.name for path in paths]
    for path in paths:
        parse_fixture(path)


def test_every_f4_trigger_has_a_disruption_fixture():
    """One fixture per trigger type, except `other`, which has no product path."""
    triggers = {
        fixture.spec.disruption.trigger
        for fixture in load_all()
        if fixture.spec.disruption is not None
    }
    expected = {
        trigger.value for trigger in ReplanTrigger if trigger is not ReplanTrigger.OTHER
    }
    assert expected <= triggers


def test_an_unknown_key_in_a_fixture_is_an_error(tmp_path: Path):
    """A silently ignored field is a silently skipped assertion."""
    spec = json.loads((FIXTURE_DIR / "group_split.json").read_text())
    spec["expected"]["must_inculde"] = ["chuo-sight-0a"]  # deliberate typo
    path = tmp_path / "group_split.json"
    path.write_text(json.dumps(spec))

    with pytest.raises(Exception, match="must_inculde|extra"):
        parse_fixture(path)


def test_a_fixture_referring_to_an_unknown_candidate_is_an_error(tmp_path: Path):
    spec = json.loads((FIXTURE_DIR / "group_split.json").read_text())
    spec["expected"]["must_go"] = ["no-such-place"]
    path = tmp_path / "group_split.json"
    path.write_text(json.dumps(spec))

    with pytest.raises(ValueError, match="unknown candidate"):
        parse_fixture(path)


def test_fixture_ids_are_stable_across_loads():
    """A stored eval_result is only comparable if the ids do not move."""
    first = load_by_name("group_split")
    second = load_by_name("group_split")
    assert first.ids_by_slug == second.ids_by_slug
    assert first.trip.id == second.trip.id


def test_spares_stay_out_of_the_swipe_pool():
    fixture = load_by_name("disruption_place_closed")
    assert fixture.spares, "a disruption fixture needs replan stock"
    pool_ids = {candidate.id for candidate in fixture.pool}
    assert not pool_ids & {candidate.id for candidate in fixture.spares}


def test_a_rainy_fixture_day_is_rainy_to_the_solver_and_the_scorer():
    """Probability and weather code have to agree, or the two disagree."""
    fixture = load_by_name("weather_storm_day3")
    rainy = [day for day in fixture.weather.days if day.is_rainy]
    assert len(rainy) == 1
    assert rainy[0].precipitation_probability_max >= 90


# ---------------------------------------------------------------- providers


def test_transit_minutes_come_from_distance_not_a_constant():
    near = leg_minutes(
        TransitLocation(lat=43.060, lng=141.354),
        TransitLocation(lat=43.062, lng=141.356),
    )
    far = leg_minutes(
        TransitLocation(lat=43.060, lng=141.354),
        TransitLocation(lat=43.198, lng=140.994),
    )
    assert near[0] < far[0]
    assert near[1].value == "walking"
    assert far[1].value == "transit"


async def test_the_transit_provider_answers_every_pair_once():
    from syncinerary.tools.transit import PairwiseTransitRequest

    locations = [
        TransitLocation(lat=43.06 + index / 1000, lng=141.35) for index in range(4)
    ]
    provider = DistanceTransitProvider()
    matrix = await provider.prefetch_pairwise(
        PairwiseTransitRequest(locations=locations, departure_window="2026-09-27T09")
    )
    assert len(matrix.legs) == 4 * 3
    assert provider.request_count == 1


# --------------------------------------------------------------- injectors


def _nodes() -> list[ItineraryNode]:
    from uuid import UUID

    return [
        ItineraryNode(
            id=UUID(f"10000000-0000-0000-0000-{index:012d}"),
            version_id=UUID("20000000-0000-0000-0000-000000000001"),
            candidate_id=UUID(f"30000000-0000-0000-0000-{index:012d}"),
            day=0,
            start_time=time(9 + index * 2),
            end_time=time(10 + index * 2),
        )
        for index in range(3)
    ]


def test_every_trigger_has_an_injector():
    assert set(INJECTORS) == set(ReplanTrigger)


@pytest.mark.parametrize(
    ("trigger", "extra", "key"),
    [
        ("reservation_cancelled", {}, "node_id"),
        ("place_closed", {}, "node_id"),
        ("transit_delay", {"delay_minutes": 40}, "node_id"),
        ("weather", {}, "day"),
        ("overslept", {"at": "11:00"}, "day"),
        ("other", {}, "affected_node_ids"),
    ],
)
def test_each_injector_produces_the_payload_the_agent_expects(trigger, extra, key):
    spec = DisruptionSpec(trigger=trigger, day=0, stop_index=1, **extra)
    resolved_trigger, payload = inject(spec, _nodes())
    assert resolved_trigger is ReplanTrigger(trigger)
    assert key in payload


def test_the_injector_points_at_the_stop_the_fixture_names():
    """Positional, so a fixture survives the solver reordering a day."""
    node = target_node(DisruptionSpec(trigger="place_closed", day=0, stop_index=2), _nodes())
    assert node.start_time == time(13)


def test_an_impossible_disruption_is_refused_rather_than_silently_empty():
    with pytest.raises(DisruptionNotApplicable):
        target_node(DisruptionSpec(trigger="place_closed", day=0, stop_index=9), _nodes())
    with pytest.raises(DisruptionNotApplicable, match="starts before"):
        inject(DisruptionSpec(trigger="overslept", day=0, at="06:00"), _nodes())


# ----------------------------------------------------------------- scorers


def test_a_failing_check_fails_the_fixture_but_a_low_score_does_not():
    """Feasibility gates; quality is tracked."""
    from syncinerary.eval.scorers import ScoreResult

    scores = FixtureScores(
        feasibility=[CheckResult(name="ok", passed=True)],
        quality=[ScoreResult(name="meal_coverage", value=0.0)],
        harness=[CheckResult(name="ok", passed=True)],
    )
    assert scores.passed

    scores.feasibility.append(CheckResult(name="fatigue_within_budget", passed=False))
    assert not scores.passed
    assert [check.name for check in scores.failures] == ["fatigue_within_budget"]


def test_harness_health_reports_a_blown_budget():
    checks = score_harness(HarnessObservations(budget_exceeded=True, step_count=51))
    failed = [check.name for check in checks if not check.passed]
    assert failed == ["within_budget"]


async def test_narrative_scoring_punishes_a_place_that_is_not_in_the_trip():
    fixture = load_by_name("group_split")
    outcome = await run_plan_case(fixture)
    assert outcome.solver_result is not None

    placed = [
        candidate.name_canonical
        for candidate in fixture.candidates
        if candidate.id
        in {stop.candidate_id for route in outcome.solver_result.routes for stop in route.stops}
    ]
    honest = score_narrative(fixture, " and ".join(placed), outcome.solver_result)
    invented = score_narrative(
        fixture,
        " and ".join(placed) + " and the Sapporo Space Elevator",
        outcome.solver_result,
    )
    assert honest.value == pytest.approx(1.0)

    absent = next(
        candidate.name_canonical
        for candidate in fixture.candidates
        if candidate.name_canonical not in placed
    )
    hallucinated = score_narrative(fixture, f"{placed[0]} and {absent}", outcome.solver_result)
    assert hallucinated.value < honest.value
    # A name the fixture has never heard of is not punished: only claims
    # about places this trip actually knows about can be checked.
    assert invented.value == pytest.approx(honest.value)


# ------------------------------------------------- the suite catches damage


async def test_the_baseline_fixture_passes_every_check():
    outcome = await run_plan_case(load_by_name("clean_5day_hokkaido"))
    assert outcome.scores.passed, [check.line for check in outcome.scores.failures]


@pytest.mark.parametrize(
    ("name", "fixture", "expected_check"),
    [
        ("fatigue-cap", "weather_storm_day3", "fatigue_within_budget"),
        ("dietary-filter", "vegetarian_conflict", "no_hard_dietary_conflict"),
    ],
)
async def test_a_deliberate_break_turns_the_run_red(name, fixture, expected_check):
    """CLAUDE.md 12.3: a bad change has to show as a measurable regression."""
    loaded = load_by_name(fixture)
    clean = await run_plan_case(loaded)
    assert clean.scores.passed, [check.line for check in clean.scores.failures]

    broken = await run_plan_case(loaded, sabotage=sabotage_module.get(name))
    assert not broken.scores.passed
    assert expected_check in {check.name for check in broken.scores.failures}


def test_every_sabotage_is_named_and_described():
    for key, value in sabotage_module.SABOTAGES.items():
        assert value.name == key
        assert value.description


def test_an_unknown_sabotage_is_refused():
    with pytest.raises(KeyError, match="Unknown sabotage"):
        sabotage_module.get("make-it-worse")


# ------------------------------------------------------------------ runtime


async def test_a_planning_fixture_finishes_well_inside_the_suite_budget():
    """The whole suite has five minutes; no single plan may eat it."""
    outcome = await run_plan_case(load_by_name("group_split"))
    assert outcome.seconds < 30


def test_the_solver_search_is_bounded():
    """Found by this harness: an unbounded CP-SAT solve hung a 5-day plan."""
    from syncinerary.agents.solver import stage1_days, stage2_route
    from syncinerary.config.solver import SOLVER_TIME_LIMIT_SECONDS

    assert SOLVER_TIME_LIMIT_SECONDS > 0
    for module in (stage1_days, stage2_route):
        source = Path(module.__file__).read_text()
        assert source.count("solver.parameters.max_time_in_seconds") == source.count(
            "solver = cp_model.CpSolver()"
        ), f"{module.__name__} has an unbounded solve"


def test_the_eval_package_imports_no_llm_sdk():
    """CLAUDE.md 2: scoring is deterministic. The runner may reach for the
    explainer under `--with-llm`, but it does so lazily and by name."""
    import ast

    for path in Path("syncinerary/eval").glob("*.py"):
        tree = ast.parse(path.read_text())
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.col_offset == 0:
                roots.add(node.module.split(".")[0])
        assert not roots & {"anthropic", "langchain_anthropic", "openai"}, path.name
