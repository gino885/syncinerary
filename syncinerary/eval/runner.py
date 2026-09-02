"""The eval harness entry point (CLAUDE.md section 12.3, Feature 2).

    python -m syncinerary.eval.runner

Runs every fixture, prints a verdict per fixture and an aggregate, diffs the
quality metrics against the previous commit's stored run, and exits non-zero
when something regressed. That last part is the whole point: this exists to
answer "did the change I just made help or hurt", in one command, before the
change is merged.

Results are stored in `eval_result` keyed by commit SHA, which is what makes
the diff work in CI, where there is no prior local state to compare against.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from syncinerary.domain.models import EvalResult, EvalScenario
from syncinerary.eval import sabotage as sabotage_module
from syncinerary.eval.cases import CaseOutcome, run_plan_case, run_replan_case
from syncinerary.eval.fixtures import LoadedFixture, load_all, load_by_name
from syncinerary.eval.scorers import QUALITY_TOLERANCE, score_narrative
from syncinerary.store.repositories import EvalResultRepository, EvalScenarioRepository

BANNER = "Syncinerary eval"


def commit_sha() -> str:
    """The commit under test. `unknown` when git is not available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    return result.stdout.strip() or "unknown"


@dataclass
class RunOptions:
    fixture: str | None = None
    store: bool = True
    with_llm: bool = False
    sabotage: str | None = None
    as_json: bool = False
    tolerance: float = QUALITY_TOLERANCE


@asynccontextmanager
async def _maybe_session(enabled: bool):
    """A throwaway database session for one disruption fixture.

    Disruption fixtures need Postgres because the rescue agent reads the
    active itinerary out of it, but nothing they write should survive: the
    trip they seed exists only so the rescue agent has something to replan.
    So the work happens inside one transaction that is always rolled back,
    the same trick the test suite uses. Two consequences worth having: a
    second eval run cannot collide with the first one's rows, and running
    the eval never leaves anything behind in a developer's database.

    `eval_result` rows are the exception, and they are written through their
    own committed session in `store_results`.
    """
    if not enabled:
        yield None
        return
    from sqlalchemy.ext.asyncio import AsyncSession

    from syncinerary.store.db import make_engine

    engine = make_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


async def _run_one(
    fixture: LoadedFixture,
    *,
    options: RunOptions,
    session: Any,
) -> CaseOutcome:
    sabotage = sabotage_module.get(options.sabotage) if options.sabotage else None

    if fixture.spec.is_disruption:
        if session is None:
            outcome = await run_plan_case(fixture, sabotage=sabotage)
            return outcome.model_copy(update={"kind": "replan (plan only, no database)"})
        return await run_replan_case(session, fixture, sabotage=sabotage)

    outcome = await run_plan_case(fixture, sabotage=sabotage)
    if options.with_llm and outcome.solver_result is not None and outcome.state is not None:
        narrative = await _narrative(outcome)
        if narrative is not None:
            outcome.scores.quality.append(
                score_narrative(fixture, narrative, outcome.solver_result)
            )
    return outcome


async def _narrative(outcome: CaseOutcome) -> str | None:
    """Run the real explainer. Only reached under `--with-llm`."""
    from syncinerary.agents.explain import generate_narrative

    assert outcome.state is not None and outcome.solver_result is not None
    try:
        return await generate_narrative(outcome.state, outcome.solver_result)
    except Exception as exc:  # noqa: BLE001 - a refusal or a missing key is not a crash
        print(f"  narrative unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


async def run(options: RunOptions) -> tuple[list[CaseOutcome], dict[str, Any]]:
    fixtures = (
        [load_by_name(options.fixture)] if options.fixture else load_all()
    )
    if not fixtures:
        raise SystemExit("No fixtures found")

    chosen = sabotage_module.get(options.sabotage) if options.sabotage else None
    if chosen is not None:
        print(f"!! sabotage active: {chosen.name} ({chosen.description})\n")

    started = time.perf_counter()
    outcomes: list[CaseOutcome] = []
    for fixture in fixtures:
        # One session per fixture, so a replan fixture's seeded trip cannot
        # collide with the next one's.
        async with _maybe_session(options.store) as session:
            outcomes.append(await _run_one(fixture, options=options, session=session))
    elapsed = time.perf_counter() - started

    summary: dict[str, Any] = {
        "commit": commit_sha(),
        "sabotage": options.sabotage,
        "seconds": round(elapsed, 2),
        "fixtures": len(outcomes),
        "passed": sum(1 for outcome in outcomes if outcome.scores.passed),
    }
    return outcomes, summary


# ------------------------------------------------------------------ storage


async def store_results(outcomes: list[CaseOutcome], sha: str) -> None:
    """Write one `eval_result` per fixture, upserting the scenario row."""
    from syncinerary.store.db import session_scope

    async with session_scope() as session:
        scenarios = EvalScenarioRepository(session)
        results = EvalResultRepository(session)
        for outcome in outcomes:
            scenario = await scenarios.get_by_name(outcome.fixture)
            if scenario is None:
                scenario = await scenarios.add(
                    EvalScenario(
                        name=outcome.fixture,
                        fixture={"name": outcome.fixture, "kind": outcome.kind},
                        expected={},
                    )
                )
            await results.add(
                EvalResult(
                    scenario_id=scenario.id,
                    commit_sha=sha,
                    scores=outcome.scores.as_dict(),
                    passed=outcome.scores.passed,
                )
            )


async def previous_quality(sha: str) -> dict[str, dict[str, float]] | None:
    """The previous commit's quality numbers, by fixture name."""
    from syncinerary.store.db import session_scope

    async with session_scope() as session:
        results = EvalResultRepository(session)
        previous_sha = await results.previous_commit_sha(sha)
        if previous_sha is None:
            return None
        scenarios = {
            scenario.id: scenario.name for scenario in await EvalScenarioRepository(session).list_all()
        }
        by_fixture: dict[str, dict[str, float]] = {}
        for result in await results.list_for_commit(previous_sha):
            name = scenarios.get(result.scenario_id)
            if name is not None:
                by_fixture[name] = dict(result.scores.get("quality", {}))
        return by_fixture or None


# ------------------------------------------------------------------ output


def print_report(
    outcomes: list[CaseOutcome],
    summary: dict[str, Any],
    previous: dict[str, dict[str, float]] | None,
    tolerance: float,
) -> list[str]:
    """Print the report. Returns the regressions found, as readable lines."""
    print(f"{BANNER} at {summary['commit'][:12]}\n")
    regressions: list[str] = []

    for outcome in outcomes:
        verdict = "PASS" if outcome.scores.passed else "FAIL"
        print(f"{verdict}  {outcome.fixture}  ({outcome.kind}, {outcome.seconds:.1f}s)")
        for failure in outcome.scores.failures:
            print(f"        {failure.line}")

        prior = (previous or {}).get(outcome.fixture, {})
        for score in outcome.scores.quality:
            was = prior.get(score.name)
            arrow = ""
            if was is not None:
                delta = score.value - was
                if delta < -tolerance:
                    arrow = f"  regressed from {was:.2f}"
                    regressions.append(
                        f"{outcome.fixture}/{score.name}: {was:.2f} to {score.value:.2f}"
                    )
                elif delta > tolerance:
                    arrow = f"  improved from {was:.2f}"
            print(f"        {score.name:30} {score.value:.2f}  {score.detail}{arrow}")
        print()

    print(
        f"{summary['passed']}/{summary['fixtures']} fixtures passed "
        f"in {summary['seconds']}s"
    )
    if previous is None:
        print("No previous commit stored, so nothing to diff against.")
    elif regressions:
        print(f"\n{len(regressions)} quality regression(s):")
        for line in regressions:
            print(f"  {line}")
    else:
        print("No quality regressions against the previous commit.")
    return regressions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m syncinerary.eval.runner",
        description="Run the eval fixtures and report against the previous commit.",
    )
    parser.add_argument("--fixture", help="run one fixture by name")
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="do not touch Postgres; disruption fixtures run their planning half only",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="also run the explainer and score the narrative for groundedness",
    )
    parser.add_argument(
        "--break",
        dest="sabotage",
        choices=sorted(sabotage_module.SABOTAGES),
        help="apply a named deliberate breakage, to prove the harness catches it",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=QUALITY_TOLERANCE,
        help=f"quality drop allowed before it counts as a regression (default {QUALITY_TOLERANCE})",
    )
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = RunOptions(
        fixture=args.fixture,
        store=not args.no_store,
        with_llm=args.with_llm,
        sabotage=args.sabotage,
        as_json=args.as_json,
        tolerance=args.tolerance,
    )

    outcomes, summary = await run(options)

    previous: dict[str, dict[str, float]] | None = None
    if options.store:
        previous = await previous_quality(summary["commit"])
        # A sabotaged run is a demonstration, not a measurement, so it never
        # becomes the baseline the next run compares against.
        if options.sabotage is None:
            await store_results(outcomes, summary["commit"])

    if options.as_json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "fixtures": [
                        {
                            "name": outcome.fixture,
                            "kind": outcome.kind,
                            "seconds": round(outcome.seconds, 2),
                            **outcome.scores.as_dict(),
                        }
                        for outcome in outcomes
                    ],
                },
                indent=2,
            )
        )
        regressions = []
    else:
        regressions = print_report(outcomes, summary, previous, options.tolerance)

    failed = summary["passed"] != summary["fixtures"]
    return 1 if failed or regressions else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
