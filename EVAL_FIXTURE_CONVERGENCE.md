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

## 6. The part that did not go away, and what it turned out to be

Updated 2026-09-07, later the same day. This section originally recorded that
`weather_storm_day3` did not recover with more search budget, moved
non-monotonically, and scored against the objective the solver optimises. That
was all true, and the cause was not the one section 4 implies.

Sweeping the CP-SAT random seed over twelve runs made it measurable. The
stage-1 objective spread across those twelve plans was 1.8 per cent, while
meal coverage ranged from 0.625 to 1.000, and the correlation between them was
`r = +0.38`: if anything, the better the objective, the worse the meal
coverage.

Then the decisive measurement. Stage 1 returned the same answer every time,
twenty-two places and eight restaurants on every seed, and every stop stage 2
dropped was a restaurant. Meal coverage turned out to be predictable exactly,
on eight seeds out of eight, from a property of the day assignment alone:

    meal coverage = per day, the number of lunches and dinners fillable by
                    distinct restaurants that day holds, over days times two

Stage 2 was never losing meals. It was seating every meal its day made
seatable, and proving that optimal each time. A day handed two dinner-only
restaurants has lost its lunch before stage 2 starts, and `FOOD_PER_DAY_MAX`
could not see that, because counting restaurants is not the same question as
asking which meals they can serve.

So the divergence was not noise and not the search. Stage 1 chose the thing
the metric measures, and had no term for it.

The fix is in `m7i-stage1-meal-awareness`: stage 1 now computes, per candidate
per day, which required meals that restaurant could actually sit inside, and
carries one bool per day per meal whose subset constraints are Hall's
condition over the meals, so a day cannot claim a lunch it has no distinct
restaurant to serve. Uncovered meals are penalised in the objective, above
dispersion and well below the flat cost of leaving a candidate unplaced.

What that produced, measured the same way:

| | before | after |
|---|---|---|
| storm meal coverage, 12 seeds | 0.625 to 1.000 | 1.000 on every seed |
| storm worst-traveler, 12 seeds | 0.826 to 0.957 | 0.957 on every seed |
| clean meal coverage, 12 seeds | moved | 0.900 on every seed |
| clean worst-traveler, 12 seeds | moved | 0.960 on every seed |
| storm transit efficiency | `r = -0.37`, unrelated | `r = -0.94`, tracks the objective |

More of the trip also survives: `group_split` routes 15 of 15 candidates
rather than 13, `clean_5day_hokkaido` 25 of 26 rather than 23, and
`weather_storm_day3` 22 of 23 rather than 20. The worst-off traveler improved
on every fixture, because the metric counts placed cards that traveler liked.

The two models still terminate at `FEASIBLE`. That is the surprise worth
keeping: convergence and metric stability are separable. The numbers were not
unstable because the search stopped early, they were unstable because the
objective was indifferent to them, and a search wandering a plateau reports
whichever corner it stopped in. Give the objective an opinion and every
near-optimal plan agrees, unconverged or not.

It also settles the architecture caveat for these metrics.
`clean_5day_hokkaido` was the original example, 0.80 meal coverage on arm64
against 0.70 on x86-64. It now scores 0.90 and 0.96 on both. Transit
efficiency still differs by architecture on that fixture, 0.56 against 0.43,
which is why it carries no floor there.

What is left on `weather_storm_day3` is `weather_fit`, which still moves
between 0.875 and 1.000, one exposed stop, at `r = +0.52`. Stage 1 does carry
a weather term, so this is a weighting question rather than a blind spot, and
it is one stop rather than a quarter of the meals.

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

Then section 6 was chased down and fixed, in `m7i-stage1-meal-awareness`, and
the floors re-baselined against the better numbers it produced. Two fixture
assumptions broke in the process and both were real signals rather than
breakage: `group_split` stopped leaving any candidate unplaced, which retired
its `wishlist_explained` floor and moved one narrative test onto a fixture
that still leaves a place out.

Left open, in rough priority order:

1. `weather_fit` on `weather_storm_day3`, the one metric section 6 did not
   settle. One exposed stop, and a weighting question rather than a blind
   spot.
2. `group_split` no longer makes the solver choose. It routes all fifteen of
   its candidates, so the two opposing factions it was written to represent
   never actually contend, and `worst_traveler_satisfaction` reads 1.00
   because everyone got everything. The fixture needs more candidates than the
   trip can hold to test what its name claims.
3. Whether stage 1 should converge on the two hard fixtures at all. Less
   urgent than it looked: their metrics are stable and architecture-stable
   without it, so this now only buys a provable optimum rather than a
   trustworthy number.
4. Whether CI should carry a stored baseline so the diff line works there too
   (section 7). The floors gate without it.
