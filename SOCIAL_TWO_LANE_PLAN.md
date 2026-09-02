# Two-lane social selection

Written 2026-09-02. Extends `SOCIAL_SOURCES_PLAN.md`. The durable spec lands in
`CLAUDE.md` section 8.2 and 8.5 once this is built.

## 1. The problem

`eligible_places()` ranks by popularity alone:

```
buzz_score = log(mentions + 1) * (1 + log1p(engagement)/10)
sort by (-buzz_score, -platform_count, -mention_count, name)
```

Two consequences.

**A hidden gem cannot surface.** A place matching a traveler's stated interests
but mentioned once is indistinguishable from any other one-mention place.
Traveler interests reach the search query (`traveler_interests()`,
social.py:230) but have zero influence on ranking.

**A listicle can capture the deck.** `BUZZ_MIN_SOURCE_COUNT` is 1, so a "10
spots in Sapporo" video yields 10 eligible places, each with
`mention_count = 1`, each scoring `log(2) = 0.693`. All tie. Platform count
and mention count also tie. The sort falls through to `place.name`, so the
deck is one creator's opinion in alphabetical order.

## 2. Decisions

### 2.1 interest_fit comes from the existing NER call, not embeddings

No embedding infrastructure exists. `dedup.py:9` states embedding similarity
is unimplemented; `EMBEDDING_SIMILARITY_THRESHOLD` is aspirational. Adding
cosine similarity means a new vendor (Anthropic publishes no embeddings API),
a new key, and a new harness-wrapped tool, for one ranking signal.

The NER call at `social.py:309` already reads every post's text, once per
platform per city. `traveler_interests()` is already computed before it runs.
Passing the interests into that prompt and asking for a fit judgment per
mention costs zero additional calls.

The scale is an ordinal 0 to 3, not a float:

| Value | Meaning |
|---|---|
| 0 | Post says nothing connecting this place to any stated interest |
| 1 | Loose or generic connection |
| 2 | Clear match to a stated interest |
| 3 | Strong, specific match quoted from the post |

Small integer scales are far more stable across model calls than a float, and
a threshold on an ordinal needs no calibration. This is the direct answer to
the `MIN_INTEREST_SCORE = 0.55` problem: on a cosine scale that number is
unknowable without a labelled set; on this scale "at least a clear match"
is self-defining.

Section 2 of CLAUDE.md holds: the model produces the signal, deterministic
code does the selecting.

### 2.2 Place-level score is the max over its mentions

One strong piece of evidence justifies a For You card. The card then shows the
highlight from that same post, so the badge and the quote agree.

### 2.3 Lane labels

`✨ For You`, not `💎 Hidden Gem`. The lane is selected on interest match, and
we cannot measure obscurity. Naming it "hidden gem" would claim evidence we do
not have, the same error as printing a like count we never measured.

### 2.4 No per-post extraction cap

Discovery optimizes for recall. All 10 places from a listicle are extracted.
Filtering happens at selection.

The listicle problem is not solved by capping extraction or by penalizing
listicle places. It is solved by counting independent sources, because all 10
of those places share one URL and therefore have
`independent_source_count = 1`. Section 2.5.

### 2.5 independent_source_count already exists

`merge_mentions` (social.py:387) skips a URL already on the place, so
`mention_count` is already a unique-URL count. This is formalized as a named
property rather than reimplemented.

One genuine refinement: three posts by the same creator are weaker evidence
than three creators. `MinedPost.author_name` is populated, so
`independent_author_count` becomes a tiebreak above alphabetical.

## 3. Numbers

Budgets derive from the pool the trip actually needs, rather than being flat
per-city caps. `MAX_SOCIAL_PLACES_PER_CITY = 12` scales with city count, so a
4-city trip reserves 48 verification calls while a 1-city trip reserves 12,
neither related to how many cards the pool wants.

```
social_target  = ceil(days * POOL_PER_DAY * BUZZ_RATIO)
verify_budget  = min(SOCIAL_VERIFY_BUDGET_MAX, ceil(social_target / VERIFY_YIELD))
```

| Constant | Value | Why |
|---|---|---|
| `MINED_NAMES_MAX` | 100 | First round across the whole trip |
| `SOCIAL_VERIFY_BUDGET_MAX` | 40 | Ceiling on Google Places verification calls per trip |
| `VERIFY_YIELD` | 0.75 | Observed share of mined names that resolve inside the city. Over-selection covers the rest |
| `TRENDING_LANE_RATIO` | 0.70 | Of the verification budget |
| `MIN_INTEREST_FIT` | 2 | Ordinal floor for the For You lane |

Worked example, 5 days, 2 cities:

```
social_target = ceil(5 * 8 * 0.60) = 24
verify_budget = min(40, ceil(24 / 0.75)) = 32
  trending    = ceil(32 * 0.70) = 23
  for_you     = 32 - 23 = 9
```

For a 4-city trip this spends 32 verification calls where the current code
would spend 48, so the step cap gets easier, not harder.
`gather_max_steps()` changes from `city_count * 12` to the trip-level
`verify_budget`.

### 3.1 Allocation across cities

Mining stays per city, because a post about one city is not evidence about
another. Selection becomes trip-level, because the pool budget is trip-level.

The verification budget is allocated to cities in proportion to their trip
days, floor of 1, largest remainder for the leftovers. A city with 4 of 6 trip
days should contribute more cards than a city with 1.

## 4. Selection algorithm

```
per city:  SEARCH -> READ -> EXTRACT -> MERGE       (unchanged)

per trip:
  score_places()             buzz_score, interest_score, independent counts
  select_social_candidates()
      1. drop places with no resolvable name
      2. allocate verify_budget across cities by trip days
      3. per city:
           trending = rank by (-buzz, -independent_sources, -authors,
                               -interest, name) take trending slots
           remaining = places not in trending
           for_you  = [p for p in remaining if p.interest_score >= MIN_INTEREST_FIT]
                      rank by (-interest, -buzz, -independent_sources, name)
                      take for_you slots
           backfill unused for_you slots from trending remainder, and
           unused trending slots from for_you remainder
      4. attach selection_lane to each
  VERIFY  (Google Places, unchanged)
  take verified survivors up to social_target
```

Backfill runs in both directions so the budget is always spent. A trip whose
travelers listed no interests degrades cleanly to a pure trending deck.

`eligible_places()` is split, per the TODO: `score_places()` computes,
`select_social_candidates()` chooses. Testable separately.

## 5. Selection metadata

Each selected place carries why it was chosen, so the UI badge is read from
data rather than recomputed:

```python
trending_signals = {
    ...existing...,
    "selection_lane": "trending" | "for_you",
    "interest_score": 0..3,
    "independent_source_count": int,
    "independent_author_count": int,
}
```

The `✨ For You` badge renders from `selection_lane`. Under M5a it links to the
post whose highlight earned the match, which is the same post whose text the
card already shows.

## 6. Tests

- A listicle: one post naming 10 places must not fill the deck alphabetically.
- Ordering property, not absolute values, per the M7-7 lesson: a place with
  two independent posts outranks a place with two mentions from one post.
- No interests on any traveler degrades to a trending-only deck of the right
  size.
- Fewer than the lane quota clear `MIN_INTEREST_FIT`: budget still fully spent
  via backfill.
- Budget allocation across a 3-city trip with uneven day counts sums to
  `verify_budget` and gives every city at least 1.
- A place whose interest_score is 3 but mention_count is 1 reaches the deck,
  which is the whole point.
