# M7k Routing Repair Architecture

Status: implemented. This describes the system as built, and the invariants
that must survive changes to it.

## The problem

Stage 1 assigns every shortlisted place to a day or to the wishlist, globally,
with the group's scores in its objective. Stage 2 then routes each day for
real: opening hours, transit, visit durations, the twelve hour clock.

Stage 1 judges a day by straight-line dispersion and a walking estimate, so it
cannot see what Stage 2 will refuse. Stage 2 can refuse a place but cannot move
it to another day. Until M7k those two facts met in the worst possible way: a
refusal was the end of the place, however much the group wanted it, and the
only reason it was refused might be that its first day assignment was poor.

The production path is `solver_node` -> `solve_full_routes`, which is also what
`rescue.py` and the eval harness call. The top-up loop in `solve_routes` is the
older M1/M3 entry point and has not been on the shipping path since M5.

## Responsibility split

```
Stage 1 (stage1_days.assign_days)      Stage 2 (stage2_route.solve_day)
- global day assignment                - visit order within a day
- candidate value trade-offs           - opening-hour feasibility
- move / drop / replace decisions      - transit and travel-time feasibility
- which places are worth the seats     - daily-clock feasibility
                                       - feasibility discovery
```

**Stage 2 discovers feasibility. Stage 1 decides what is worth keeping.**

Stage 2 has no notion of what a place is worth and must never be allowed to
decide, even accidentally. When two places cannot share a day, its circuit
seats one of them by position; if that choice reached the itinerary, seating
order would be deciding which of the group's places survives.

There is exactly one value model, the one Stage 1 already had: `not_placed`
costs `1_000_000 + vote_weight * vote_value`, from `CandidateScore.score`. The
repair layer reuses it (`repair.candidate_value`) and adds no second ranking.

## Learned facts

| Evidence | Learned fact | Stage 1 representation | Why it is sound |
|---|---|---|---|
| No arc between A and B in either direction, after the transit chain and its estimate | A and B cannot share any day | `assigned[A,d] + assigned[B,d] <= 1` for every d | A missing arc is a property of the pair and the map, not of a date. One direction present is enough to sequence them, so only pairs missing both count |
| `closed_on_available_days`, `no_meal_slot` | A cannot be on day d | `assigned[A,d] = 0` | Both are computed from the place's own hours against that date. Neither mentions another candidate, so neither can be an artifact of who shared the day |
| `no_day_fit` | at most k of this exact set can share day d | `sum(assigned[m,d] for m in members) <= k` | k is measured by re-solving the day under a maximize-seated-count objective, not inferred from which place was refused |
| A different visit order fixes the day | nothing | none | Stage 2 chooses order freely on every solve. Nothing to teach |
| A provider missed, and the estimate covered it | nothing | none | Refusal codes come from Stage 2's schedule model, which runs after the transit chain has applied its fallback. A provider miss is not a physical impossibility |

Anything else Stage 2 reports (`fatigue_overflow`, and Stage 1's own reasons)
teaches nothing.

A candidate already in a known incompatible pair is never given a unary block.
The pair constraint says the same thing more precisely and leaves the choice of
survivor to Stage 1; a block would hand it back to seating order. Must-go and
pinned candidates are never blocked at all.

## The capacity probe

`no_day_fit` means the clock ran out around a whole combination. It names a
victim because Stage 2 has to refuse somebody, and that victim is chosen by its
circuit rather than by worth. Two tempting shortcuts are both wrong:

- Turning it into `A != Thursday` is too strong and lets seating order pick the
  victim.
- Reading `sum <= seated_count` off the plan is unsound, because Stage 2 will
  trade one stop for a required meal (`required_meal_penalty` exceeds
  `unplaced_penalty` by design), so the seated count can be below the true
  maximum.

So the day is measured. `solve_day(..., count_placements_only=True)` re-solves
the same day, against the same transit matrix, under a dedicated objective:

```python
model.maximize(sum(active.values()))
```

It answers only **how many members of this exact set can physically fit**. It
does not optimize preference, value, meal coverage, transit, start times, or
any other soft term, and it does not answer which members should survive.

A dedicated objective rather than a reweighted one, deliberately. Seated count
does dominate the planning objective today, because `unplaced_penalty` is sized
as `max_transit_cost + max_start_cost + 1`, but nothing in the code enforces
that relationship and a future weight would break repair soundness silently.

The probe costs one CP-SAT solve and **no transit lookup**: the day's arcs are
already in hand from the solve that produced the refusal.

**The result is used only when the search proved it** (`DayRoute.proven`, set
from an `OPTIMAL` or `INFEASIBLE` status). A count the solver ran out of time
to verify may be below the truth, and a capacity learned from it would forbid
Stage 1 an arrangement that actually fits, which is the exact failure this loop
exists to prevent.

### Capacity facts are scoped to the set that was probed

```
Probe {A, B, C, D} on Thursday -> at most 3

Learn:      A + B + C + D <= 3   on Thursday
Never:      Thursday holds at most 3
```

Another set, `{A, B, X, Y}`, may well seat all four, and the constraint must
not forbid it. `assign_days` names the members in the constraint for exactly
this reason. A capacity whose limit is below what pinned candidates already
occupy on that day is dropped rather than enforced, so a learned fact can never
make the model infeasible against a decision the group made.

## The repair loop

```
Stage 1 assignment
  -> route every day (Stage 2)
  -> classify each refusal
  -> probe the days that reported a combination failure
  -> learn facts
  -> re-run Stage 1 with them
  -> re-route only the days whose membership changed
  -> keep the best plan seen, by value
  repeat
```

A round that does not improve the trip does **not** end the loop. It still
teaches the next probe the capacity of the day it has just built, and a
measured case reached five placed of five exactly two rounds after a round that
looked like a waste. The best plan seen is tracked and returned, so exploring
can never cost the trip anything.

Plans are compared on `PlanValue`: retained user value first, then placed
count, then transit. Value before count is the point. A twelve stop itinerary
holding the group's best places beats a fourteen stop one that bought its extra
rows by dropping them.

### Bounds (`config/solver.py`)

| Constant | Value | What it bounds |
|---|---|---|
| `REPAIR_MAX_ROUNDS` | 6 | Stage 1 re-solves. Higher than it looks like it needs, because a probe can only measure the day-set it was just given, so a trip whose days all need re-sizing learns one at a time |
| `REPAIR_MAX_DAY_SOLVES` | 12 | Extra Stage 2 solves across the whole loop. **The limit that actually binds**, because each one is a transit lookup and a harness step |
| `REPAIR_MAX_REPLACEMENTS` | 4 | Reserve candidates admitted per trip |

The loop terminates on any of: the round cap, the day-solve cap, no new fact
learned, or Stage 1 returning an assignment identical to the current one. A
fully feasible plan produces no refusals, so it exits on the first round having
spent zero day solves and zero lookups. Re-learning a fact already known does
not count as new, so repeated identical facts cannot cycle.

## Reserve candidates

`shortlist_state.wishlist_excluded_ids`, in the order aggregate ranked them.
They exist to fill a hole, not to make an itinerary look fuller. The order of
preference is:

```
1. Stage 2 reorders the day            (free, every solve)
2. Stage 1 moves an original to another day
3. Stage 1 reshuffles originals globally
4. Stage 1 drops the lowest-value original, only if unavoidable
5. a reserve is admitted into a genuine hole
```

A "hole" is a selected place that no day can hold: blocked on every trip day,
or left unplaced by Stage 1 for `closed_on_available_days`. A place merely
squeezed out by capacity is not a hole, because the same capacity would squeeze
out its replacement.

Two guards keep a reserve from displacing an original. Its not-placed penalty
sits below every selected candidate's by more than the largest the
per-candidate terms can ever add, derived from the model rather than picked, so
the ordering holds at any trip length. And the number that may be placed is
capped at the number of holes.

## Known risks

**Incremental per-set learning.** Capacity facts name their members, so a trip
with several badly sized days learns one set per round. It terminated well
inside the caps in every case measured, but a pathological trip will stop at a
bound with the best plan found rather than the global optimum. That is the
intended failure mode: bounded, and never worse than the plain Stage 1 plan.

**Runtime.** Probe and re-solve cost latency on difficult trips. The full test
suite went from 54s to about 110s and the eval suite from 12s to about 30s,
both well inside their gates (the eval budget is five minutes; the five-day
replan gate is ten seconds and runs in about one). A healthy trip must remain
free: zero repair rounds, zero extra day solves, zero extra lookups. There is a
test asserting exactly that, including lookup-count equality.

Worth watching in production:

```
repair_rounds                 p50 / p95
extra_day_solves              p50 / p95
repair latency                p50 / p95
% trips hitting the round cap
% trips hitting the day-solve cap
% trips using a reserve candidate
% of selected-place value retained
```

**Explanation precision.** A place that is open but unreachable from everything
else on its day currently surfaces under the capacity path rather than under a
reason naming unreachability. It is moved correctly; only the wording is less
specific than it could be. Reason codes (`cross_day_repair_exhausted`,
`lower_marginal_utility_than_conflicting_place`) are stable across the API and
iOS and are not renamed for documentation tidiness.

**API visibility.** The repair ledger reaches OTel spans and the itinerary
version's `objective_breakdown`. It is not exposed to the client, so "why was
this moved" stops at the trace.

## Files

| File | Role |
|---|---|
| `agents/solver/repair.py` | Policy only: fact types, classification, budget, ledger, plan value, reserve selection. Not a second route solver |
| `agents/solver/stage1_days.py` | `assign_days` accepts `blocked_days`, `incompatible_pairs`, `day_capacities`, `reserve_ids`, `replacement_budget` |
| `agents/solver/stage2_route.py` | The loop, the probe, and `count_placements_only` on `solve_day` |
| `config/solver.py` | The three bounds |
| `tests/test_m7k_routing_repair.py` | The invariants above, as tests |
