# Reel discovery implementation and live evidence

September 16, 2026. Measurements use the uncommitted working tree. These are
individual live samples, with non-deterministic extraction and provider data,
not a statistically controlled A/B test or a guarantee for every destination.

## Implemented behavior

- A 60% Reel target drives automatic discovery. The reported acceptance flag
  requires strictly more than 50% of unique swipe cards.
- Production search uses Instagram-scoped Brave web results. A video-search
  adapter is available for comparison, with separate cache identities for
  endpoint and page. Video search returned zero usable Instagram posts in all
  six sampled city/query pairs across the initial and template comparisons,
  so it is not the production default.
- Short English Instagram queries replace long lists of synonyms. Chinese
  wording continues to follow the trip locale.
- A full first page that contributes more than one new place can earn one
  second page, replacing the broader retry. Repeated post URLs within that
  intent are excluded before second-page extraction. The eight-search city
  ceiling and two-attempt semantic-intent ceiling remain unchanged.
- Verification runs during discovery. Accepted places, city/category coverage,
  and Reel coverage inform subsequent searches. Failed names are checked once;
  names resolving to the same place contribute one card.
- Guide verification leaves capacity for the expected Reel target. Initial
  verification allocations still follow trip size. Low measured yield can
  expand them within the existing 40-attempt trip ceiling, including guides.
  The harness reserves that ceiling but charges only actual calls.
- Reel preference applies within the existing Trending and For You slots.
  Food coverage and quality admission checks remain in effect. A sparse city
  can still return a useful deck below the Reel goal; that is a reported miss.
- Final metrics exclude lodging and run after dietary filtering. Visible and
  automatic-only shares are separate, with per-city and per-category automatic
  breakdowns. User links cannot inflate automatic coverage. Google discovery,
  lodging, and social verification calls are separately logged/traced.

## Evidence files

| File | What was measured |
|---|---|
| `search-comparison.json` | The original English FOOD templates through web and video endpoints, with post counts and available text lengths |
| `tokyo-zh.json` | Initial verification-aware run with the original 22-attempt allocation: 7/16 Reels, 9/16 Google-only |
| `tokyo-zh-adaptive.json` | After allowing unused verification capacity: 12/16 Reels, 3/16 Google-only, 86.71 seconds, $0.261275 reported model cost |
| `english-decks.json` | Before pagination: Sapporo, Atami, and a Tokyo/Atami trip in English |
| `paginated-english-decks.json` | Pagination alone, with the original long English templates |
| `short-query-english-decks.json` | Final short English query templates plus bounded pagination |
| `final-tokyo-zh.json` | Final implementation in Traditional Chinese, including bounded pagination |

## September 16 implementation samples

Each trip requested two days and returned 16 non-lodging cards. No attached
links contributed to these results, so visible and automatic shares match.

| City | Locale | Reel-backed cards | Google-only cards | Strict majority |
|---|---|---|---|---|
| Tokyo | English | 11/16 (68.75%) | 3/16 (18.75%) | Pass |
| Sapporo | English | 11/16 (68.75%) | 5/16 (31.25%) | Pass |
| Atami | English | 4/16 (25%) | 10/16 (62.5%) | Miss |
| Tokyo | Traditional Chinese | 10/16 (62.5%) | 6/16 (37.5%) | Pass |

Other social sources account for the remaining cards where these shares do
not add to 100%. Atami remains below the goal. The sampled search supply and
accepted places were insufficient within the existing limits. Broader coverage
will need additional source supply; this change does not establish a universal
Reel majority or reduce the deck to conceal a miss.

The earlier Tokyo Chinese improvement preceded pagination. It should not be presented
as a measurement of the final query strategy. Likewise, an earlier failed
sample is retained rather than overwritten by a later success.

Costs in these files are the harness's model-cost accounting. They exclude
Brave and Google charges. Cached provider responses may reduce billed requests;
`harness_steps` counts logical tool/model calls, not a provider invoice.

## Reproduce

These commands make live provider calls and may incur cost. They use configured
credentials without printing them. Deck mode uses the normal model-cost and
step limits, creates no saved trips, and stores no candidate rows.

```bash
.venv/bin/python -m scripts.evaluate_reels --mode search --locales en --output /tmp/reel-search.json
.venv/bin/python -m scripts.evaluate_reels --mode deck --cities Tokyo Sapporo Atami --locales en zh-Hant --output /tmp/reel-decks.json
.venv/bin/python -m scripts.evaluate_reels --mode deck --cities Tokyo,Atami --days 2 --locales en --output /tmp/reel-multicity.json
```

Deck mode exits nonzero if any sampled trip falls below the trip-wide 60% Reel target.
Each completed case is saved before the next starts. Provider exceptions abort
with their actual error rather than producing a synthetic successful result.
The script evaluates groups with no attachments, profiles, or dietary exclusions;
production metrics include filtering and report attached content separately.

The normal deterministic eval runner continues to make no model calls. All 14
admission cases and all 10 itinerary fixtures passed after the discovery change.
The final full Python suite passed all 797 tests with no skips; Ruff and
`git diff --check` also passed.
Reel playback inside iOS was not tested, and these percentages measure source
evidence rather than successful video embeds. No Meta creator API integration
or video download was added.

## September 18 city-day and selected-language validation

`city-days-user-language.json` records the current Tokyo/Atami four-day runs
with explicit `[3, 1]` allocation. Both retain 24 Tokyo and eight Atami cards.
English reached 16/32 Reels (50%); Traditional Chinese reached 14/32 (43.75%).
Both miss the 20-Reel target. These runs use explicit Brave language settings
and are not a matched A/B comparison with the earlier two-day samples.

```bash
.venv/bin/python -m scripts.evaluate_reels --mode deck --cities Tokyo,Atami --days 4 --city-days 3,1 --locales en zh-Hant --output /tmp/city-days-reels.json
```

`city-days-light.png`, `city-days-dark.png`, and `city-days-accessibility.png`
show the actual city-day component in an isolated simulator preview. Kamakura
is fixture data, not confirmation of the owner's third city. The current
backend suite passed 815 tests and the deterministic planner passed 10 fixtures.
See [the revised implementation report](../../REELS_RECOVERY_PROPOSAL.md) for
accepted behavior, retained limits, live shortfalls and rollout status.
