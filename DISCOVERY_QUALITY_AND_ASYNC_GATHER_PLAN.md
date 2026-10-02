# Discovery quality and asynchronous gather plan

## Purpose

This plan addresses five problems observed in the Tokyo, Kamakura, and Atami trip created on 2026-09-12:

1. Google Places results that are concepts, campaigns, events, or generic category names can become swipe cards even though they are not useful itinerary stops.
2. Discovery does not begin with a broad itinerary guide that establishes the places most travelers should consider before the adaptive searches look for food, hidden gems, and personalized choices.
3. Trip creation waits for the entire gather graph inside one HTTP request. A successful trip can therefore be reported as failed when the iOS request times out before the server finishes.
4. Discovery starts too early. The group needs time to join and contribute links before the leader deliberately starts card discovery.
5. Solver output exposes minute-level times such as `10:13`, which creates false precision and makes the itinerary harder to scan.

The target behavior is a deck made only of specific, independently visitable places. For Chinese UI, RedNote long-form itineraries matching the user's selected cities and trip duration should establish baseline coverage, and adaptive Instagram, RedNote, and TikTok searches should add current, low-key, food, nightlife, and personalized options. A trip should exist as a collaborative room before discovery begins. Gathering starts only when the leader confirms that the group is ready, and it continues independently of one mobile HTTP connection. Published itinerary times use 30-minute boundaries.

## Evidence from the reported trip

The two incorrect cards were stored as Google-only fallback candidates:

| Card | Google type | Discovery query | Missing evidence |
|---|---|---|---|
| `東京夜晚與燈光` / `Tokyo Night & Light` | `tourist_attraction` | `top tourist attractions in Tokyo` | No social source and no source description |
| `東京美食` / `Tokyo Food` | `restaurant` | `restaurants near Tokyo Night & Light` | No social source, no source description, and opening hours were assumed |

The first weak result became a cluster anchor. The nearby-meal search then used that name and admitted the second weak result. One false positive therefore generated another.

The relevant behavior is in `syncinerary/agents/gather/live.py`:

- `discover_candidates()` adds every destination-search result returned by Google when its place ID is new.
- `candidate_from_place()` assigns any non-food, non-lodging primary type to `ATTRACTION`.
- Cluster meal searches trust previously admitted attractions as anchors.
- The Google fallback path does not apply a shared candidate-admissibility gate before inserting results.

The social path calls `is_visitable_place()`, but that function currently rejects only administrative areas. A Google label such as `tourist_attraction` or `restaurant` is therefore sufficient even when the result name is a generic concept.

## Workstream 1: candidate admissibility

### Product rule

A swipe card must identify one specific place a traveler can intentionally navigate to and visit. Search relevance and a Google Place ID are necessary verification signals, but neither one alone makes a result suitable for the deck.

Reject candidates representing:

- Generic category concepts, such as `Tokyo Food`, `Kyoto Nightlife`, or `Seoul Shopping`.
- Campaigns, festivals, projection programs, temporary promotions, and other events unless event support is deliberately added as a separate product type.
- Search collections, guide titles, tour packages, listicles, and itinerary titles.
- Administrative regions and an entire city, neighborhood, or district presented as one stop.
- Results with no stable visitor-facing identity even if Google classifies them as a restaurant or tourist attraction.

Allow real areas only when the product deliberately supports them as navigable experiences, such as a named shopping street, market, beach, park, or historic district. These should have a stable map destination and an appropriate place type.

### Shared validation stage

Add one deterministic `candidate_admissibility` stage after provider resolution and before a candidate enters `by_place_id`. All automatic sources must pass through it: social, Google fallback, profile-driven discovery, and nearby meal expansion.

The stage should return a structured result rather than a boolean:

```text
CandidateAdmission
  accepted: bool
  reason_code: specific enum
  evidence: provider fields used for the decision
```

Initial reason codes:

- `administrative_area`
- `generic_category_name`
- `guide_or_collection`
- `event_or_campaign`
- `unsupported_place_type`
- `insufficient_identity`
- `outside_city`
- `accepted`

### Deterministic checks

Apply these checks before any model-assisted check:

1. Preserve the existing city-boundary validation.
2. Reject administrative-only place types.
3. Maintain explicit allowlists for restaurants and supported attraction types. Do not classify every unknown primary type as an attraction.
4. Normalize the result name and reject `destination + generic noun` patterns in English, Simplified Chinese, and Traditional Chinese. The generic vocabulary should include food, restaurants, nightlife, lights, attractions, sightseeing, travel, guide, itinerary, shopping, and equivalent Chinese terms.
5. Reject unsupported event-oriented types and names. Event support should require dates, venue, and a separate event model.
6. Require a stable Google Place ID, coordinates, and a visitor-facing display name.
7. Mark missing hours as unknown. Do not treat invented default hours as evidence that a business is valid.

Name matching is a high-precision guard, not the whole validator. It must not reject legitimate names merely because they contain a city name. For example, `Tokyo National Museum` has a specific institution noun and should pass, while `Tokyo Food` should fail.

### Evidence strength

Record an admission evidence level in candidate enrichment:

- `social_and_places`: named by a social source and resolved by Google.
- `places_strong`: Google-only, but supported type plus strong identity metadata.
- `places_weak`: Google-only with missing description, missing hours, generic naming, or an unknown type.

Only the first two levels may enter the swipe deck. A weak result can be retained in diagnostic output but must not count toward pool size.

Useful strong-identity signals include a supported primary type, real opening hours for businesses, website or phone metadata, user rating count, business status, and an editorial summary. Extend the Places field mask only with fields actually used by the admission decision.

### Prevent false-positive propagation

Only an admitted, non-event attraction may become a density-cluster anchor. Nearby restaurant queries must also validate their returned places independently. If an anchor is rejected later, discard candidates whose only discovery reason was proximity to that anchor and recompute the cluster.

### Deck behavior

- Do not fill a numeric deck target with weak candidates.
- A smaller high-quality deck is preferable to cards that are not usable places.
- Report per-city shortages so later fallback searches can try another source or wording.
- Keep rejected candidates out of the swipe count and itinerary solver.

## Workstream 2: RedNote city-guide baseline

### Goal

For Chinese UI, use RedNote long-form itinerary posts as a coverage seed before adaptive discovery. The search must reflect both the cities and the total number of days the user entered. It must not assume every trip is five days or run a separate five-day query for every city. A matching multi-city guide often captures route order and transfer expectations as well as named places. The guide itself is evidence, not a candidate card.

### Search sequence

For the complete trip:

1. Translate every canonical city name to the commonly used Simplified Chinese name for RedNote search.
2. Build the primary query from the ordered city list and the inclusive trip length entered by the user.
3. Run the primary multi-city guide query before the adaptive loop. For a single-city trip, use that one city with the same total day count.
4. Retrieve a small bounded set of high-ranking guide notes.
5. Measure whether each requested city appears in the extracted route and whether the guide provides enough named places for the days allocated to that city.
6. Only when a city is missing or thin, issue one city-specific fallback query using that city's allocated number of days.
7. Extract every explicitly named visitable place while preserving the note URL and the sentence or snippet that mentioned it.
8. Deduplicate names across guides.
9. Resolve each name through Google Places and run the shared candidate-admissibility stage.
10. Add accepted places to a `guide_baseline` pool with RedNote provenance.

Suggested bounded query templates:

```text
{城市1} {城市2} {城市3} {N}天{N-1}夜攻略
{城市1} {城市2} {N}天自由行 路線
{城市} {該城市分配天數}天攻略
```

Examples:

```text
東京 鎌倉 熱海 5天4夜攻略
東京 鎌倉 熱海 5天自由行 路線
鎌倉 2天攻略
```

Do not multiply all templates unconditionally. Start with the query matching the user's actual ordered cities and total trip length, measure coverage, and issue city-specific queries only for missing cities or categories. Preserve the city order from user input because it can carry route intent.

### Coverage model

Track guide coverage separately from popularity and personalization:

- Core sights
- Neighborhood or walking area
- Local food or market
- Cafe or breakfast option
- Evening or nightlife option
- Nature or scenic stop
- Low-key recommendation

The baseline should establish breadth. It must not dominate final ranking merely because one guide names many places. After verification:

- Reserve baseline slots for independently corroborated core places.
- Continue the existing social priority of Instagram, RedNote, then TikTok for additional discovery.
- Preserve a separate low-key lane so the deck includes places outside the repeated must-visit set.
- Use traveler interests for ranking rather than changing the baseline query into a narrow personalized query.

### Provenance

Extend source metadata so a card can explain why it exists:

```text
type: buzz
subtype: rednote_guide
via: rednote_search
url: canonical note URL
query: query that found the note
guide_rank: provider rank
mention_text: bounded supporting excerpt or paraphrase
```

The current `Source` model cannot retain a URL, query, or guide role directly. Add typed fields or a dedicated normalized source table rather than hiding all provenance in unrelated enrichment keys. Preserve multiple guide sources during deduplication.

### Guard against guide-title cards

The extraction prompt and deterministic validator must explicitly distinguish:

- A guide title: `東京五天四夜攻略`: never a card.
- A category heading: `東京美食`: never a card.
- A named place listed inside the guide: `築地場外市場`: eligible after Places verification.

Add the source post's index to every extracted mention and reject any model output that cannot be traced to text in that post.

## Workstream 3: collaborative setup and asynchronous gather lifecycle

### Current failure

`TripCreateViewModel.createTrip()` currently performs two operations inside one `do/catch`:

1. `POST /trips`
2. `POST /trips/{id}/gather`

The iOS session waits up to 180 seconds for request data. A three-city gather can perform many sequential Brave, social metadata, image, Google Places, and model calls and exceed that limit. The server may complete and persist the deck after iOS has already displayed `要求逾時`.

Because both calls share one catch block, a gather timeout is presented as `無法建立行程` even though the trip already exists. The database record from the reported case was created successfully and later reached `swiping`.

There is also duplicate ownership: the creation view calls `gather`, then `GatheringView.task` calls `gather` again after navigation.

### Required product flow

Discovery must not start immediately after trip creation. The intended flow is:

```text
Create trip shell
  -> Invite members
  -> Members join the group room
  -> Everyone can paste social links
  -> Leader reviews readiness
  -> Leader presses Start discovery
  -> Server reads group links and searches external sources
  -> Group swipes the resulting cards
  -> Confirm shortlist
  -> Build itinerary
```

The initial trip shell needs only the destination cities, travel dates or inclusive day count, and creator identity required for ownership. Preferences may be collected during the group preparation stage so each member can contribute their own interests and dietary constraints before discovery starts.

All joined members may attach links in the group room before the start action. A link should show who submitted it and its processing state, but pre-start processing must remain bounded to metadata capture, safety checks, canonical URL normalization, and caching. It must not populate or expose the swipe deck yet.

Only the trip leader can press `開始找地點`. The confirmation view should show:

- Joined members and who has completed preferences.
- Number of links contributed by the group and any links that could not be read.
- Selected cities and trip dates.
- A clear statement that discovery will combine group links with Instagram, RedNote, TikTok, and last-resort Google results.

Starting discovery freezes the input snapshot for that gather run: member preferences, submitted links, cities, and dates. New links posted while a run is active belong to a later refresh unless the leader explicitly starts another discovery version. This makes one run deterministic and prevents a moving input set from changing cards halfway through voting.

### Trip lifecycle

Represent the flow with explicit server states rather than inferring it from whether candidates exist:

```text
draft -> gathering -> swiping -> discussing -> planning -> active
```

- `draft`: members may join, edit their own preferences, and attach links. No automatic search is running.
- `gathering`: leader has started discovery and the input snapshot is fixed for this run.
- `swiping`: a usable deck is ready.
- Later states keep their existing meanings.

The start endpoint must authorize the caller as leader and atomically move `draft` to `gathering` while creating the gather run. Repeated taps return the same active run. A non-leader receives a clear authorization error and the UI keeps the room in `draft`.

### Target API

Make gather a persistent server-side job with idempotent start and status endpoints:

```http
POST /trips/{trip_id}/gather-runs
202 Accepted
{
  "run_id": "uuid",
  "status": "queued"
}

GET /trips/{trip_id}/gather-runs/current
200 OK
{
  "run_id": "uuid",
  "status": "queued|running|completed|failed",
  "phase": "guide_baseline|social_search|place_verification|deck_build",
  "city": "Kamakura",
  "completed_units": 7,
  "total_units": null,
  "deck_size": null,
  "error_code": null,
  "retryable": false,
  "updated_at": "..."
}
```

The start request uses the authenticated caller; the server verifies that caller is the trip leader. Starting gather for a trip that already has a queued or running job must return that job. Starting it after completion must return the completed job and deck size. Concurrent requests must never run two graphs for the same trip.

### Persistence and worker behavior

Add a persistent `gather_run` record with a uniqueness rule allowing at most one active run per trip. Store status, phase, progress, timestamps, retry count, and a sanitized failure code. Use the existing LangGraph checkpointer for graph progress and a worker backed by the existing Redis/Postgres infrastructure for execution. Do not use an in-process FastAPI background task as the final design because process restart would lose ownership of the job.

The worker should:

1. Claim a queued run atomically.
2. Resume from the existing graph checkpoint when possible.
3. Update phase and heartbeat after bounded units of work.
4. Mark completion only after candidates are committed and trip status is `swiping`.
5. Mark technical provider failures separately from an intentionally small but valid deck.
6. Permit a bounded retry without creating a second trip or duplicate candidate set.

### iOS flow

Trip creation should only create the trip shell and return its session. It should then navigate to a group preparation room, not `GatheringView`.

The group preparation room owns invites, member readiness, link attachments, and the leader-only start button. After the leader starts discovery, `GatheringView` becomes the single owner of observing the run:

1. Receive the run created by the leader's start action or load the current run after relaunch.
2. Poll the status endpoint with a modest backoff, or subscribe to an existing authenticated progress channel.
3. Render the server phase and current city.
4. Resume polling after app suspension, navigation, or relaunch.
5. Navigate to swipe only after `completed` with a nonzero usable deck.
6. Show `旅程已建立，但找地點時發生問題` for gather failure. Reserve `無法建立行程` for failure of `POST /trips` itself.

Each mobile request should finish quickly. A 15–30 second transport timeout is then sufficient because the long-running work no longer occupies the connection.

## Workstream 4: 30-minute itinerary times

### Product rule

Every user-visible itinerary start and end time must land on a 30-minute boundary. Valid examples are `10:00`, `10:30`, `11:00`, and `11:30`. Times such as `10:13` or `14:47` must never be published.

Transit estimates may retain minute-level precision internally for feasibility and route comparison. The solver must add enough buffer and then choose displayable stop boundaries on the 30-minute grid. Simply rounding the finished itinerary in the UI is unsafe because it can create overlaps, violate opening hours, or hide insufficient transfer time.

### Solver constraints

Introduce one scheduling quantum:

```text
SCHEDULE_QUANTUM_MINUTES = 30
```

Apply it inside route construction:

1. Constrain every scheduled stop start to a multiple of 30 minutes from midnight.
2. Represent visit durations in 30-minute quanta by rounding required occupancy up, not down.
3. Keep actual transit duration, then round the next feasible arrival boundary up to the next 30-minute slot.
4. Align meal-break starts and ends to the same grid.
5. Align user-selected day start and day end to 30-minute increments in the iOS picker and validate them again on the API boundary.
6. Preserve exact provider transit minutes in metadata so the UI can still say, for example, `約 13 分鐘車程`; only itinerary clock times use the grid.
7. Apply the same rule to replans and manual time edits so later operations cannot reintroduce odd-minute schedules.

If an attraction opens at `10:15`, schedule it at `10:30`. If a 13-minute journey follows a stop ending at `10:00`, the next stop starts no earlier than `10:30`. The unused minutes are intentional breathing room.

## Implementation order

1. Add regression fixtures reproducing `Tokyo Night & Light` and `Tokyo Food` with their observed Google types and missing metadata.
2. Introduce the shared admission result and deterministic rejection reasons.
3. Apply admission before inserting Google fallback results and before choosing cluster anchors.
4. Apply the same stage to social and profile-resolved candidates.
5. Change trip creation to produce a `draft` room, add leader authorization, and support pre-start group link collection.
6. Add dynamic multi-city, trip-length RedNote guide search, extraction, provenance, and coverage accounting.
7. Add gather-run persistence and worker execution using a frozen input snapshot.
8. Move the start action to the leader's group room and remove both automatic and duplicate gather calls.
9. Add progress UI, relaunch recovery, and precise localized errors.
10. Constrain solver, meal breaks, manual edits, and replans to a 30-minute output grid.
11. Instrument quality and latency, then compare against the current fixture set and several live trips.

## Acceptance criteria

### Candidate quality

- `Tokyo Food` is rejected as `generic_category_name` even when Google returns type `restaurant`.
- `Tokyo Night & Light` is rejected as `event_or_campaign` or `insufficient_identity` under the current place-only product scope.
- A rejected attraction can never seed a nearby restaurant query.
- `Tokyo National Museum`, `Shinjuku Golden-Gai`, a named restaurant, and a named market remain eligible.
- Unknown Google primary types do not automatically become attractions.
- Rejected candidates never count toward deck capacity or solver coverage.

### RedNote baseline

- Chinese UI uses a Simplified Chinese RedNote guide query containing every user-selected city in input order and the actual inclusive trip length.
- A three-day trip never defaults to a five-day query, and a five-day multi-city trip never treats every city as a separate five-day stay.
- A city-specific fallback uses the number of days allocated to that city.
- A guide title or category heading never becomes a card.
- Each accepted card extracted from a guide has a canonical note URL and traceable mention evidence.
- A five-day single-city fixture obtains verified candidates across core sights, food, and at least one non-core category before adaptive fallback.
- Multi-city allocation does not spend a full unbounded five-day search budget on every city.

### Gather lifecycle

- `POST /trips` returns without waiting for discovery.
- A newly created trip remains in `draft` and performs no automatic card search.
- Every joined member can submit links while the trip is in `draft`.
- Only the leader can start discovery.
- The gather run uses a frozen snapshot of members, preferences, links, cities, and dates.
- Closing and reopening the app during gather resumes the same run.
- Repeated start requests do not execute duplicate graphs.
- A gather lasting more than five minutes does not produce a mobile transport timeout.
- A completed server run transitions the trip to swipe even if the initiating client disconnected.
- Creation errors and discovery errors use different localized messages.

### Schedule granularity

- Every stop and meal break starts and ends on minute `00` or `30`.
- Exact transit minutes remain available and are never rounded down for feasibility.
- Opening at `10:15` produces an earliest scheduled start of `10:30`.
- A replan and a manual edit preserve the same 30-minute grid.
- The iOS time picker cannot submit unsupported minute values.

## Tests and evaluation

Add focused tests rather than relying only on prompt behavior:

- Unit tests for multilingual generic-name detection and supported place types.
- Unit tests for admission evidence levels and rejection reason codes.
- Pipeline tests proving rejected candidates do not become anchors or nearby meal seeds.
- Extraction tests where one RedNote guide contains real places plus guide headings and category labels.
- Query tests covering one city, multiple cities, different trip lengths, and city-specific fallback allocation.
- Dedup tests preserving multiple guide URLs for the same place.
- Authorization tests proving members can add links but only the leader can start gather.
- Snapshot tests proving links added after start do not mutate the active run.
- API concurrency tests starting gather twice for one trip.
- Worker restart and checkpoint-resume tests.
- iOS view-model tests distinguishing trip-creation failure, active gather, gather failure, and completion.
- Solver tests asserting `start_minute % 30 == 0` and `end_minute % 30 == 0` for normal plans, meal breaks, replans, and fixed-time edits.
- An evaluation metric for invalid-card rate, measured as cards lacking one specific navigable identity. The release threshold should be zero on the regression fixtures.

## Observability

Record these counters and timings per city and source:

- Search results retrieved
- Names extracted
- Places resolved
- Candidates accepted and rejected by reason code
- Guide-baseline category coverage
- Weak Google fallback rate
- Gather phase duration
- Total gather duration
- Duplicate start requests coalesced
- Runs resumed from checkpoints
- Time from trip creation to leader start
- Members and links included in each frozen input snapshot
- Schedule buffer introduced by 30-minute quantization

Logs must include trip ID, run ID, source, city, query intent, and rejection reason without storing private tokens or full copyrighted post content.

## Rollout

Run the new validator in shadow mode first and compare accepted/rejected candidates without changing decks. Review false positives and false negatives across Tokyo, Kamakura, Atami, Sapporo, and at least two non-Japanese destinations. Then enable rejection for high-confidence rules, enable the RedNote guide baseline for Chinese UI, and finally switch iOS to asynchronous gather after the status API and worker are stable.

Do not delete existing trips or candidates as part of rollout. New gather runs use the new policy; old decks can be regenerated explicitly when needed.
