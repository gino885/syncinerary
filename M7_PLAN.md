# M7: the eval harness (Feature 2)

Written 2026-09-02 on `main`, straight after the UI work merged. Scope is
`syncinerary/eval/`, its fixtures, a runner, and a CI job. No behaviour
changes anywhere else; the harness only reads.

CLAUDE.md calls this the interview headline: it closes the trace to eval to
fix loop, and it must answer "did this change make the agent better or worse"
inside five minutes.

## 1. What already exists

- `syncinerary/eval/` is an empty package.
- `eval_scenario` and `eval_result` tables exist, with
  `EvalScenarioRepository` and `EvalResultRepository`, including
  `list_for_commit` and `previous_commit_sha`. The diff-vs-last-commit
  requirement is already supported by the store.
- The deterministic core is callable without a database:
  `score_candidates`, `build_shortlist`, and `solve_full_routes(state,
  candidates, transit_provider, weather=..., must_go_ids=..., pinned_days=...,
  weights=...)`.
- The replan path is not: `create_replan_proposal(session, ...)` needs a
  database, and the existing M6 tests drive it with `StubTransit` and
  `StubAlternatives` against the test Postgres.
- CI already runs Postgres and Redis as services.

## 2. The decision that shapes everything: no LLM in the default run

Two acceptance criteria are in tension with LLM-judged metrics: five minutes
end to end, and CI runs the eval on every PR. An LLM judge adds latency, a
per-PR bill, and non-determinism to a suite whose whole job is detecting
regressions.

So the default run is entirely deterministic:

- **Every scorer that gates CI is deterministic.** Feasibility and harness
  health are pass/fail from the solver output and the harness ledger.
  Quality is a set of measured ratios, not judgements.
- **The narrative is scored, but not by a model.** Faithfulness becomes a
  grounded-claims check: does the narrative name a place that is not in the
  itinerary, and does it cover every day. That is the failure mode that
  matters, and it needs no judge.
- **The model-judged path is opt-in.** `--with-llm` runs the real explainer
  and, when `deepeval` is installed, its faithfulness metric over the
  narrative against the itinerary as context. It is not in CI and it is not
  in the five-minute budget.

This is the same LLM-versus-deterministic boundary as CLAUDE.md section 2,
applied to the eval harness itself: the model writes, deterministic code
decides whether the run passed.

## 3. Fixtures

Ten JSON files in `syncinerary/eval/fixtures/`, each one a trip, its
travelers, constraints, candidates and votes, plus expectations. Candidates
carry only what the solver reads, so a fixture is legible in a diff.

| Fixture | What it holds the line on |
|---|---|
| `clean_5day_hokkaido` | The baseline. Five days, a full pool, no conflicts |
| `vegetarian_conflict` | A hard dietary exclusion the deck must not place |
| `budget_tight` | A daily budget that bites, so price has to matter |
| `weather_storm_day3` | Outdoor-heavy pool, rain on day 3 |
| `group_split` | Two factions with opposing votes, to watch the worst-off traveler |
| `disruption_reservation_cancelled` | One per F4 trigger. Each seeds an active |
| `disruption_transit_delay` | itinerary, injects its disruption, and scores |
| `disruption_overslept` | the proposal: the affected day is repaired, the |
| `disruption_place_closed` | rest of the trip is untouched, and the trace |
| `disruption_weather` | gives a quantified reason |

## 4. Modules

- `eval/fixtures.py` loads a JSON fixture into typed domain objects and
  builds the `TripState`. Fixture parsing is strict: an unknown key is an
  error, because a silently ignored field is a silently skipped assertion.
- `eval/providers.py` holds the deterministic stand-ins: a transit provider
  whose durations are a fixed function of distance, so a route's transit
  total is reproducible, and an alternatives provider that returns the
  fixture's own spare candidates.
- `eval/disruption.py` has one injector per `trigger_type`, each turning a
  fixture's `disruption` block into the `trigger_payload` the rescue agent
  expects, resolved against the seeded itinerary's real node ids.
- `eval/scorers.py` holds the three families described below.
- `eval/runner.py` runs everything, writes `eval_result` rows, prints the
  table and the diff, and sets the exit code.

## 5. The three scorer families

**Feasibility, pass/fail. Any failure fails the eval.**

- No candidate with a hard dietary conflict is placed.
- Every must-go candidate is placed.
- Per-day fatigue stays within the budget.
- Every stop sits inside its opening hours for that weekday.
- Every stop starts no earlier than the previous end plus transit.
- Every day fits the trip's window and the active-hours cap.
- Pinned and fixed anchors keep their day and time.
- No candidate is placed twice.

**Quality, scored 0 to 1 and regression-tracked.**

- `must_go_coverage`: placed must-gos over must-gos.
- `worst_traveler_satisfaction`: the minimum, across travelers, of the share
  of that traveler's liked shortlist that got placed. Consensus fairness is
  about the worst-off person, so the metric is a minimum, not a mean.
- `meal_coverage`: lunch and dinner present per day.
- `transit_efficiency`: transit minutes against a per-day allowance.
- `weather_fit`: outdoor stops that avoided the rainy days.
- `wishlist_explained`: unplaced shortlisted cards that carry a reason code.
- `narrative_grounded`: only in `--with-llm` runs.

**Harness health, pass/fail.**

- No run exceeded its step or cost budget.
- No `NoProgress` or `ToolCycle` on a benign fixture.
- No tool call left unrecovered.

## 6. Runner behaviour

```
python -m syncinerary.eval.runner
```

Prints a row per fixture with its feasibility verdict and quality scores,
then an aggregate, then the diff against the previous commit's stored run.
Exit code is non-zero when any feasibility or harness check fails, or when a
quality metric drops by more than a small tolerance against the previous
commit. Flags: `--with-llm`, `--fixture NAME`, `--no-store`, `--json`.

The previous commit's numbers come from `eval_result`, keyed by commit SHA,
which is what makes the diff work in CI where there is no prior local state.

## 7. CI

A second job in `.github/workflows/ci.yml`, after the tests, with the same
Postgres and Redis services. It applies migrations and runs the eval. The job
fails the PR on any feasibility regression, which is the acceptance criterion.

## 8. Proving it catches a regression

The acceptance criterion asks for a deliberately bad change to show a
measurable regression. `--break` takes a named sabotage, applies it in
memory for that run only, and is never used by CI:

- `fatigue-cap` raises the daily fatigue budget so days overload.
- `dietary-filter` stops filtering hard dietary conflicts.
- `must-go` drops must-go pinning.

Each should turn a green run red, and the report should say which check
caught it.

## 9. Decisions taken without asking

1. The default run makes no model calls, for the reasons in section 2. The
   model-judged path exists behind a flag.
2. Fixtures are hand-written JSON, not captured from live runs. A captured
   fixture would drift with the providers and stop being a fixed yardstick.
3. The runner needs Postgres, like the test suite, because storing results
   by commit is what the diff requires. `--no-store` runs without it.
4. Quality metrics are tracked with a tolerance rather than a hard floor, so
   normal noise does not fail a PR while a real drop does.
