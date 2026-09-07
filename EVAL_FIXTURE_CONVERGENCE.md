# Two eval fixtures do not converge, and what that costs

Written 2026-09-07, while merging `m7e-for-you-lane` into main. Companion to
CLAUDE.md section 12.3 (Feature 2).

The eval rail reported five quality regressions on that branch. All five came
from one hunk, and that hunk forbids nothing. The regression was the search
moving, not the plans getting worse. This is the record of the measurement, so
the next person who sees these fixtures move does not have to redo it.

---

## 1. What was reported

`python -m syncinerary.eval.runner` exited 1 on the branch tip. Ten of ten
fixtures passed feasibility. Five quality metrics dropped, across two fixtures:

| Fixture | Metric | main | branch |
|---|---|---|---|
| clean_5day_hokkaido | meal_coverage | 0.80 | 0.70 |
| clean_5day_hokkaido | worst_traveler_satisfaction | 0.92 | 0.88 |
| weather_storm_day3 | meal_coverage | 1.00 | 0.75 |
| weather_storm_day3 | weather_fit | 0.88 | 0.75 |
| weather_storm_day3 | worst_traveler_satisfaction | 0.96 | 0.87 |

Measured by running `--no-store` at `origin/main` and at the branch tip on one
machine, rather than by trusting the stored baseline, which was 26 commits old.

## 2. It is one hunk, and it is not the transit estimate

`b3d068d` changed two things: a fallback transit estimate in stage 2, and a
food-per-day ceiling in `assign_days`. Reverting each file separately and
re-running isolates it completely:

| | main | branch | minus food ceiling | minus transit estimate |
|---|---|---|---|---|
| clean/meal_coverage | 0.80 | 0.70 | 0.80 | 0.70 |
| storm/weather_fit | 0.875 | 0.75 | 0.875 | 0.75 |

The transit estimate accounts for none of the movement. The ceiling accounts
for all of it.

## 3. The ceiling forbids nothing either version was choosing

The ceiling is three food per day. Dumping the stage-1 buckets both ways:

```
with ceiling     clean: food/day=[2,3,2,1,2]   storm: food/day=[3,2,1,2]
without ceiling  clean: food/day=[0,2,3,3,2]   storm: food/day=[2,2,2,2]
```

No day in either run holds four. The constraint is not binding at either
solution, so it cannot have removed a plan the solver wanted. It still moved
five metrics.

## 4. Why: these two models terminate unconverged

Stage 1 for exactly these two fixtures ends at `FEASIBLE`, not `OPTIMAL`, with
`SOLVER_DETERMINISTIC_LIMIT` of 4.0 exhausted:

| Fixture | Objective | Best bound | Gap |
|---|---|---|---|
| clean_5day_hokkaido | 351,474 | 58,929 | about 83% |
| weather_storm_day3 | 1,138,085 | 1,032,658 | about 9% |

Adding a redundant constraint changes propagation and branching, so the plan
CP-SAT settles for shifts. Every other fixture reaches `OPTIMAL` and none of
them moved.

`platform_tag()` in `eval/runner.py` already names these same two as the pair
whose plans differ between instruction sets. That docstring and this document
are describing one underlying fact from two directions: an unconverged model
gives an answer that depends on how the search was steered, and a constraint,
a CPU, or a compiler all steer it.

## 5. The proof that it is search rather than quality

On `clean_5day_hokkaido`, by the solver's own objective:

- without the ceiling: 294,066
- with the ceiling: 351,474

The with-ceiling run settled for a worse plan that the ceiling never forbade,
since the no-ceiling answer holds at most three food on a day and so was
available to it. It simply was not reached inside the budget.

Raising `SOLVER_DETERMINISTIC_LIMIT` from 4 to 16 restores that fixture to
main's exact numbers, 0.80 and 0.92, with the whole suite still finishing in
26 seconds against the five-minute criterion. This was measured and then
reverted, because the limit is a product default and stage 1 on that fixture
goes from about 3 seconds to about 12, which `POST /plan` would pay.

## 6. The part that does not go away

`weather_storm_day3` does not recover with more budget, and moves
non-monotonically:

| Deterministic limit | meal_coverage | weather_fit | worst_traveler |
|---|---|---|---|
| 4 (current) | 0.750 | 0.750 | 0.870 |
| 16 | 0.625 | 0.750 | 0.826 |
| 64 | 0.750 | 0.875 | 0.870 |
| main at 4 | 1.000 | 0.875 | 0.957 |

Its solver objective improves monotonically across those same three runs:
1,138,085 then 1,131,491 then 1,125,189. So on this fixture the quality
metrics move against the objective the solver is optimizing. Better plans by
the model's own scoring score worse on the eval.

That is a gap in the eval rail rather than in `b3d068d`, and it is the one
finding here with a long shelf life, because Feature 2's whole claim is
answering "did this change help or hurt". A metric that disagrees with the
objective cannot answer it. Not chased yet.

## 7. What CI does and does not catch

An earlier draft of this section claimed CI "exits 0 without comparing
anything". That was wrong, and the correction matters, because it changes what
needs building.

CI does lose the commit-to-commit diff. The `eval` job brings up a fresh
Postgres service per run, so `previous_commit_sha` finds nothing and the runner
prints "No previous commit stored, so nothing to diff against". The line
reading "0.92 to 0.88" is a local-developer signal only.

CI does not lose quality gating. A fixture sets floors under any metric it
cares about in `expected.min_scores`, `score_expected_floors` checks them, and
those results are appended to the feasibility family, where any failure fails
the eval. Floors are absolute, so a fresh database costs them nothing. All
three sabotage modes fail the run with no baseline present:

```
--break fatigue-cap      exit=1   8/10 fixtures passed
--break must-go          exit=1   9/10
--break dietary-filter   exit=1   9/10
```

The real gap was calibration. `weather_storm_day3/meal_coverage` fell from
1.00 to 0.75 against a floor of 0.60, and cleared it with room to spare. Only
the 1.00 floors on `wishlist_explained` and `must_go_coverage` were tight.

That is now fixed for the fixtures where it can be. Eight of the ten reach
`OPTIMAL` on every solve, and section 4's argument runs backwards for them: a
converged model gives the same answer whatever steers the search, which is why
the runner's own docstring can say every optimal fixture is identical on every
architecture. Their floors sit 0.05 under measured, which is a real gate. The
two unconverged fixtures keep wide floors and say so in their own
`description`, because a tight floor there fails CI on unrelated work.

## 8. What was decided

The nine commits merged unchanged. The ceiling stays: it is non-binding on
these fixtures but it binds on the real trip that motivated it, where one day
was handed five restaurants and stage 2 could seat two.

Then the floors were calibrated, in `m7h-eval-floors`: tightened to 0.05 under
measured on the eight converged fixtures, added to the five disruption
fixtures, which had gated on no quality metric at all, and left wide on the
two unconverged ones.

Left open, in rough priority order:

1. Why `weather_storm_day3` scores against the objective (section 6). This is
   the one with the longest shelf life, because a metric that disagrees with
   the objective cannot answer the question Feature 2 exists to answer.
2. Whether stage 1 should converge on these two fixtures, by search budget or
   by a tighter formulation, so their numbers stop depending on how the search
   was steered (sections 4 and 5). Converging them is also what would let
   their floors be tightened like everything else.
3. Whether CI should carry a stored baseline so the diff line works there too
   (section 7). Lowest of the three: the floors gate without it, and a
   baseline would inherit the same noise that keeps two fixtures loose.
