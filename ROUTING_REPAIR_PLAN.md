# M7k: Stop a bad day assignment from costing a place its seat

## 1. The architecture that is actually there

```
aggregate.score_candidates      -> CandidateScore.score per candidate, ranked
shortlist.build_shortlist       -> selected = top days*6, excluded = the rest
solver_node                     -> loads ONLY selected_candidate_ids
solve_full_routes               -> assign_days(...)  then  _solve_one_day per day
                                   and then it returns
```

`solve_full_routes` is the production path: `solver_node`, `rescue.py`, and the
eval harness all call it. It runs Stage 1 exactly once, routes each day exactly
once, and stops. There is no feedback of any kind.

The top-up loop everyone remembers (`_offers_for_day`, `_is_better`,
`TOPUP_MAX_ROUNDS`) lives in `solve_routes`, which is the older M1/M3 entry
point and is now reachable **only from tests**. Nothing in production has run it
since M5 replaced it. That is the single most important finding here: the
repair machinery people assume exists is dead code on the shipping path.

### Answers to the specific questions

| Question | Answer |
|---|---|
| Are Stage 1 assignments fixed? | Yes, absolutely, on the production path |
| Can Stage 2 move a place to another day? | No. `solve_day` is per-day and its only lever is dropping a stop |
| Does rescue only work within a day? | F4 rescue rebuilds one day, and internally calls `solve_full_routes` on a one-day trip, so it inherits the same dead end |
| Where is user priority? | `CandidateScore.score` on `TripState.candidate_scores`, plus shortlist order, plus `must_go_candidate_ids`. Stage 1 already prices it: `not_placed` costs `1_000_000 + vote_weight * vote_value` |
| Can dropped Stage 2 places be replaced from a larger pool? | No. `solver_node` loads only `selected_candidate_ids`; `wishlist_excluded_ids` is written at shortlist time and never read again |
| Can routing feasibility flow back upstream? | No. `DayRoute.unplaced` goes into `wishlist_not_placed` and is only ever rendered |

### The part the prompt gets wrong, in our favour

Stage 1 is **already a global cross-day model**: `assigned[(candidate, day)]`
plus `not_placed[candidate]`, with per-day capacity, fatigue, walking, a food
ceiling, and Hall conditions over the meals. It already prefers moving a place
to another day over dropping it, and it already drops the lower-scoring of two
conflicting places, because the not-placed penalty carries the vote score.

So the failure mode is not "Stage 1 cannot express cross-day repair". It is
**Stage 1 optimizes over a model that does not know what Stage 2 will refuse**.
Stage 1 measures a day by straight-line dispersion and a nearest-neighbour
walking estimate. Stage 2 measures it by real opening hours, real transit and a
twelve-hour clock. When Stage 2 refuses, nobody tells Stage 1.

## 2. Recommendation: hybrid, weighted to the solver

Not a hand-written local-search of reorders, moves and swaps: that would
reimplement, worse, the cross-day reasoning Stage 1 already does correctly, and
it would need a second priority model exactly where the prompt says not to
invent one.

Not a monolithic CP-SAT either: real transit is not knowable before a day's
membership is chosen, so a single model would need the full pairwise matrix for
every candidate on every day, which is the API bill this repo has spent two
milestones avoiding.

**A bounded feedback loop that re-runs the existing Stage 1 with what Stage 2
learned.** One round is:

```
route the days           -> Stage 2 refusals, each attached to a specific day
learn (candidate, day) blocks from those refusals
re-run assign_days with the blocks           <- cross-day repair happens HERE
re-route only the days whose membership changed
keep the round only if trip value strictly improved
```

Every repair operation the prompt lists falls out of that:

| Prompt's operation | Where it happens |
|---|---|
| reorder within a day | Stage 2's circuit already chooses order freely, every solve |
| insert at a different position | same, it is the same variable |
| move to another day | Stage 1 re-solve with the block |
| swap across days | Stage 1 re-solve, it is one model, both moves are free |
| move a small cluster | same, no special case needed |
| remove lowest marginal value | Stage 1's `not_placed` penalty, already score-weighted |
| pull the next-best reserve | reserve candidates injected into the re-solve |
| rerun affected days | membership diff, unchanged days keep their route |

## 3. What must be built

1. `assign_days(..., blocked_days=..., reserve_ids=..., replacement_budget=...)`.
   Blocks are one `model.add(assigned[(i, d)] == 0)`, the same mechanism the
   opening-hours filter already uses. A block is never applied to a must-go or
   pinned candidate's required day.
2. Reserve candidates get a not-placed penalty strictly below every selected
   candidate's, so a reserve is dropped before any selected place, and their
   placed count is capped at the number of holes. The discount is derived from
   the model's own maximum per-candidate terms rather than picked, so it holds
   for a trip of any length.
3. `agents/solver/repair.py`: the policy, with no orchestration. Ledger and
   counters, the budget, learning blocks from refusals, the trip value
   function, bucket-change classification, reserve selection.
4. The loop itself in `solve_full_routes`, where `_solve_one_day` lives.
5. `solver_node` loads `wishlist_excluded_ids` and passes it as the reserve.

Bounds: `REPAIR_MAX_ROUNDS`, `REPAIR_MAX_DAY_SOLVES` (a hard ceiling on extra
Stage 2 calls, because each is a harness step), `REPAIR_MAX_REPLACEMENTS`.

## 4. What must not move

- The transit chain. A provider failing is not a fact about the world. Blocks
  are learned from Stage 2's own reason codes, which are computed from the
  schedule model, never from provider status, so an estimated leg produces a
  block only when the day genuinely does not fit around it.
- Stage 1's constraints, the food ceiling, fatigue, walking, meals.
- `solve_routes` and its top-up, left exactly as it is.
- Provider names stay out of the user-facing transport mode.

## 5. Files

`agents/solver/repair.py` (new), `agents/solver/stage1_days.py`,
`agents/solver/stage2_route.py`, `config/solver.py`, `domain/models.py`
(ledger on the result), `tests/test_m7k_routing_repair.py` (new).
