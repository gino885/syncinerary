# M1 Handoff

Point-in-time state of the `m1-vertical-slice` branch. Delete this file when
M1 merges to `main`. Durable instructions live in `AGENTS.md`; the spec is
`CLAUDE.md`.

Branch: `m1-vertical-slice`, 13 commits ahead of `main`, working tree clean,
HEAD `a14b5be`.
Tests: **153 total, all passing** (59 run without Postgres; the other 94 skip
with a clear message when it is down).
Lint: ruff clean.

## 1. Step status

`CLAUDE.md` §13 M1 has 10 steps. The owner and I split them into commits:

| Step | What | Commit | State |
|---|---|---|---|
| 0 | venv 3.12, deps, `agents/` layout fix | `e98dabe` | done |
| 1 | Alembic migrations, full §7 schema | `3562f89` `554156d` `66dff66` | done, 10 tests |
| 2 | Repositories for all 14 tables | `e0c82c4` `1d8d31c` `fe957ee` `072cd7f` | done, 48 tests |
| 3 | Hokkaido fixture + gather node | `134d7b2` | done, 16 tests |
| 4 | Swipe API | `7d04738` | done, 23 tests |
| 5 | Aggregate (§10.1) | `df8276e` | done, 18 tests |
| 6 | Shortlist auto top-N (§10.2) | `9f295c7` | done, 17 tests |
| 7 | Transit tool + single-stage solver | none | **BLOCKED, see §3** |
| 8 | Explain node | `a14b5be` | code done, 20 tests, **unverified against live API** |
| 9 | LangGraph wiring | none | not started, depends on step 7 |
| 10 | Three iOS screens | none | not started |
| 11 | Run acceptance, open PR | none | not started |

## 2. Decisions the owner made during this work

These are not in `CLAUDE.md` and were settled by asking. Do not relitigate.

1. **Module layout follows §6, not the M0 scaffold.** `solver/` and
   `delegate/` moved from top-level into `agents/`. §6 is canonical; moving
   at M5 would have cost every import in the solver.
2. **One `StateGraph` with `interrupt_after=["gather"]`**, backed by
   `AsyncPostgresSaver`, rather than two separate graphs. The swipe is a
   human break between gather and aggregate, and this is the same mechanism
   M6's HITL gate will need. `thread_id` is the `trip_id`.
   Consequence accepted by the owner: a second connection stack (psycopg3
   alongside asyncpg), and the checkpointer's own tables managed by
   `saver.setup()` rather than by alembic, because copying another package's
   schema into our migrations drifts on upgrade.
3. **`constraint` table renamed `trip_constraint`.** Reserved word.
4. **Transit for M1** was left open: the owner said "tell me when you get
   there and I will put the API key in `.env`." See §3.

## 3. Blockers, both waiting on the owner

### 3a. `GOOGLE_MAPS_API_KEY` is empty

Needed for step 7a. The owner explicitly asked to be told when the work
reached this point rather than have a mock chosen for them.

A flat 30-minute mock (the original plan) makes the solver's
"minimize transit" objective a **constant**: 6 stops = 5 legs = 150 minutes
regardless of order, so ordering is driven only by opening hours and the
route can zig-zag between cities. Two alternatives were put to the owner:
a haversine-over-assumed-speed mock (deterministic, no key, produces varied
values so clustering actually happens), or a real key. **The owner chose to
supply a real key.** Confirm before starting 7a.

### 3b. `ANTHROPIC_API_KEY` is the placeholder string

`.env` literally contains `sk-ant-...` copied from `.env.example`. A real
call returns:

```
anthropic.AuthenticationError: Error code: 401 - {'type': 'error', 'error':
{'type': 'authentication_error', 'message': 'invalid x-api-key'},
'request_id': 'req_011CdkdCitkH8tZm4oPSqoty'}
```

Step 8 is committed and its 20 tests pass, but they all run against a stub
client. The request shape is correct per the current API reference and the
error path is typed and tested, but **it has never been exercised against
the real API.** Once a key is in place, run one live call before trusting it.

### Open question the owner has not answered

§16 pins `SYNC_LLM_MODEL` to `claude-opus-4-7`. That is a valid, active model,
but `claude-opus-5` is current at the same pricing and is a drop-in swap. It
was raised and **not** changed, because §16 says defaults change in
`CLAUDE.md` before code. If the owner wants the bump, edit the §16 table and
`config/__init__.py` together.

## 4. Remaining work

### Step 7a: `syncinerary/tools/transit/`

Needs the Google key first. Build:

- A pluggable interface (§15 requires the tool layer stay swappable) returning
  a pydantic model, not a dict (§14).
- Google Directions client: request, parse
  `routes[0].legs[0].duration.value`, handle non-`OK` statuses
  (`ZERO_RESULTS`, `OVER_QUERY_LIMIT`) as typed errors.
- Cache keyed `(origin_place_id, dest_place_id, mode, departure_window)` per
  §11.2. Redis is already running and unused so far.
- Pairwise prefetch for a day's candidates: O(n²), ~36 calls/day, ~180/trip
  for a 5-day trip. Well inside the free tier.

Test the parser against a recorded real response, not an invented one. That
was the whole reason for asking for the key.

### Step 7b: `syncinerary/agents/solver/stage2_route.py`

OR-Tools CP-SAT. **No LLM import** (§2, AST-tested elsewhere; add the same
test here).

M1 scope per §13: opening hours + transit only. Explicitly **skip** weather,
fatigue, diversity, dispersion, and Stage-1 day assignment.

- Day assignment for M1 is a placeholder: sort the shortlist by score
  descending and chunk it evenly into `trip.days` buckets of 5-6. Mark it
  `TODO(M5): replaced by stage1_days.py`.
- Per day, decide visit order + `start_time`/`end_time`.
- Hard constraints: candidate open at its slot (`hours_by_weekday` keyed by
  the real weekday of that trip date), no arrival before
  `prev_end + transit_minutes(prev, this)`, total active day ≤
  `DAY_DURATION_CAP_HOURS` (12, `config/solver.py`).
- Objective: minimize total transit.
- Persist an `ItineraryVersion` + `ItineraryNode` rows via the repositories.
  Remember the chain is append-only: write a new version, never edit one.
- Anything shortlisted but unplaced goes to `wishlist_not_placed` with a
  `reason_code` (§10.3). `WishlistNotPlacedRepository` already exists.

### Step 9: `syncinerary/agents/graph.py`

Replace the M0 no-op node with the real pipeline. Single `StateGraph`:

```
gather -> aggregate -> shortlist -> solver -> explain
```

compiled with `interrupt_after=["gather"]` and an `AsyncPostgresSaver`,
`thread_id = str(trip.id)`. Call `await saver.setup()` in the FastAPI
lifespan (`api/main.py` already uses the lifespan context manager, not
`@app.on_event`).

Node functions all exist and are individually tested: `gather_node`,
`aggregate_node`, `shortlist_node`, `explain_node`. Only the solver node is
missing.

Endpoints to add (the iOS screens in step 10 need these; nothing is built
against them yet, so the shape is still yours to set):

- `POST /trips/{id}/gather`: run to the interrupt, return the deck size.
- `POST /trips/{id}/plan`: resume from the interrupt through explain.
- `GET  /trips/{id}/itinerary`: days, ordered stops with times, transit
  minutes, the narrative, and the wishlist-not-placed reasons.

Add an end-to-end test that walks the whole thing.

### Step 10: iOS

Three screens: TripCreate, Swipe (two buttons only), ItineraryView.
`ios/Syncinerary/Network/APIClient.swift` exists with a `health()` call and
plain `URLSession`. **Extend it. Do not add a networking framework.** That is an explicit
instruction from the owner.

Consult the `swiftui-pro` skill for modern API usage. Note `ios/README.md`:
the `.xcodeproj` is deliberately not committed and is created locally.

### Step 11: acceptance

Run the `CLAUDE.md` §13 M1 "Done when" checklist yourself and paste the real
output to the owner. The bar is: *one user can create a Hokkaido 5-day trip,
swipe ~30 candidates, and get an itinerary back end to end.* Then open the PR
to `main`.

## 5. Things worth knowing before you touch the existing code

- The fixture (`syncinerary/tools/fetch/hokkaido_fixture.json`) has 47
  candidates: 30 attractions, 12 food, 5 lodging. Every source score is
  hand-authored with `articles_count: null`, because §8.1 defines
  `backbone_score` as a mined frequency and these were not mined. A test
  asserts `articles_count` stays null so nothing downstream reads a made-up
  number as real. M3 replaces the whole file.
- Lodging is gathered and stored but excluded from the swipe deck and from
  aggregate scoring (§8.6). It is exempt from the `days * POOL_PER_DAY` pool
  cap for the same reason: it is not competing for pool slots.
- `must_have` is computed and carried through the aggregator with its weight
  forced to `0.0` (`M1_MUST_HAVE_WEIGHT`), rather than deleted. §13 says M1
  ignores it; M4 turns it on by changing one constant instead of reshaping a
  model the shortlist and solver already read.
- Shortlist follows §10.2 literally: top-N regardless of score. On a small
  pool that can shortlist a card the group disliked. That is deliberate and
  pinned by a test. The design's remedy is M4's confirmation screen, not a
  score floor invented here.
- `shortlist_state.confirmed_by` stays empty and `confirmed_at` stays null in
  M1. There is no confirmation step yet, so writing a timestamp would assert
  a group approval that never happened.
- Votes upsert on `(candidate_id, traveler_id)`. Not in §7, added because a
  swipe deck lets someone revisit a card and the §10.1 aggregator would
  otherwise count one person twice.
