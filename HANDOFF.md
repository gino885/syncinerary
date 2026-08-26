# M1 Handoff

Point-in-time state of the `m1-vertical-slice` branch. Delete this file when
M1 merges to `main`. Durable instructions live in `AGENTS.md`; the spec is
`CLAUDE.md`.

Branch: `m1-vertical-slice`, 23 commits ahead of `main` after this handoff
update.
Tests: **181 total, all passing** with Postgres running. Ruff is clean. The
Swift API contract regression test passes, and the Swift 6 iOS Simulator
build succeeds.

The owner's `.DS_Store` and installed-skill edits in `CLAUDE.md` remain
uncommitted. The local `ios/Syncinerary.xcodeproj` and `Info.plist` are also
uncommitted by design, per `ios/README.md`.

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
| 7 | Transit tool + single-stage solver | `1791180` `d25fbb6` | done, live Google route verified |
| 8 | Explain node | `a14b5be` | done, live Anthropic response verified |
| 9 | LangGraph wiring | `7593723` `688669a` | done, real Postgres checkpointer verified |
| 10 | Three iOS screens | `cb0a81d` `22cc36d` `7ddfd84` | done, Simulator flow verified |
| 11 | Run acceptance, open PR | none | acceptance done, PR pending |

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
4. **Transit mode:** walk for pairs at or below 2 km; use public transit for
   longer pairs.
5. **Daily planning window:** default to 08:00 through 20:00 and let the user
   adjust it when creating the trip.
6. **M3 gathering provenance:** run automatic discovery alongside traveler
   links and screenshots. Cards must identify who attached user-submitted
   content and show a permitted attributed image or the standard placeholder.

## 3. Resolved external dependencies

- `GOOGLE_MAPS_API_KEY` is configured. A live walking route returned 578
  seconds, and Redis showed the expected miss-then-hit cache behavior.
- `ANTHROPIC_API_KEY` is configured. The explainer returned a live narrative
  using the model pinned in §16.

No external dependency remains blocked.

## 4. Remaining work

Open the M1 pull request to `main`. The real acceptance evidence is:

- Backend acceptance trip `d3843c5f-cc55-44b9-b60c-e4ee832e5389` produced
  a five-day itinerary with 12 placed stops and a live 1,103-character
  narrative.
- The owner completed the same flow in the iPhone 16e Simulator for trip
  `F693F066-0E5A-43D9-AD3C-26A37047EDC2`: create, gather, candidate deck,
  all swipe votes, plan, and itinerary retrieval returned successful HTTP
  responses.
- Backend suite: 181 passed. Ruff: clean. Swift API contract test: passed.
  Swift 6 iOS Simulator build: succeeded.

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
