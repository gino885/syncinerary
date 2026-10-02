# Trip-wide Reel coverage and city days

Updated September 18, 2026, following the owner correction and implementation.
This replaces the earlier multilingual recovery proposal.

## Accepted behavior

The target is **unique Reel-backed candidate cards / all unique visible swipe
candidate cards >= 60% across the trip**. Lodging is separate from the swipe
deck. A place with multiple source posts counts once. Report automatic and
attachment-inclusive shares separately; the visible share is the primary ratio.
Per-city ratios are diagnostic, not individual pass/fail requirements.

City days determine demand: eight automatic candidate cards and at least two
food options per city-day, with attraction coverage also reserved. Three Tokyo
days and one Atami day therefore request 24 and eight cards respectively.
This supplies choices for lunch and dinner; actual meal suitability, opening
hours and dietary constraints still determine whether a restaurant can fill
a scheduled meal. Personal recommendations retain their existing additive
behavior and are included in the visible ratio.

The setup form now includes whole days per city and an optional Main city.
Suggested days are balanced, with remainder days assigned to the main city
first. Explicit days override the suggestion. Days must sum to the inclusive
trip dates, with at least one day per city. Both scheduling paths use this
allocation. Card selection preserves the city allotments and interleaves cities
so a richer search index cannot take over another city's slots.

The third city earlier written as “kamahara” remains unconfirmed. Kamakura is
used only in synthetic regression fixtures and component screenshots. No
actual trip was created or city selected on the user's behalf.

## Language rule

Search only in the selected user/trip language on every platform, including
RedNote. English uses English queries; Chinese uses Chinese queries. There is
no destination-language or multilingual recovery. Japanese terms are used only
when the selected language is Japanese. Proper names may keep their established
spelling; changing a search query never translates the underlying video.

Brave supports multiple search languages, so English defaults do not mean an
English-only index. Requests now explicitly set `search_lang` to `en`,
`zh-hans`, `zh-hant`, or `ja`, and `country=ALL`. The cache includes the language.
The official [Brave API reference](https://api-dashboard.search.brave.com/api-reference/web/search/get)
and the saved [schema evidence](evidence/reels/brave-language-schema.json)
support these request parameters. Query language and provider filtering improve
retrieval alignment but do not prove a Reel's spoken language; no audio-language
classifier or transcription is part of this change.

## Recovery within existing limits

Search and verification demand follow city days. Smaller allocations are
searched first. Their remaining trip-wide Reel deficit and unused verification
capacity can flow to later, larger allocations. Main city breaks equal-day
ordering ties. Recovery uses the larger city's existing card slots, preserving
the smaller city's meals and place needs.

The eight-search per-city limit, two attempts per platform/intent, and
40-verification trip limit remain. The three-platform opening also remains.
Google Places checks social discoveries and fills missing coverage after social
search. It does not count as Reel evidence. Exhausted searches retain an honest
shortfall; the deck is not shrunk to make the percentage pass.

This is sequential redistribution, not a fully interleaved city coordinator.
It can recover deficits in cities visited later by the search process, but does
not revisit an already exhausted city. Existing saved trips without explicit
city days remain readable and retain their legacy scheduler allocation; newly
created trips persist an explicit or suggested allocation.

## Live validation

Two four-day Tokyo/Atami runs used days `[3, 1]`, no attachments or profile
preferences, and the real configured providers. Both returned exactly 24 Tokyo
and eight Atami candidates. No saved trips or candidate rows were created.

| Language | Reel-backed / all cards | Tokyo Reels | Atami Reels | Google-only cards | Result |
|---|---:|---:|---:|---:|---|
| English | 16/32 (50%) | 11/24 | 5/8 | 9/32 | 4 Reels short |
| Traditional Chinese | 14/32 (43.75%) | 10/24 | 4/8 | 16/32 | 6 Reels short |

The 60% target requires 20 Reels for these 32-card decks. Neither run met it.
Tokyo hit the eight-search limit in both; the Chinese run also used all 40
verification attempts. These are measured shortfalls, not evidence of a
universal 60% result. The earlier single-city 16-card samples are not a matched
baseline for these larger, explicitly language-filtered trips.

[Raw results](evidence/reels/city-days-user-language.json) retain card names,
city, Reel provenance, source mix and model costs. Model cost was $0.180575 for
English and $0.376725 for Chinese, excluding Brave and Google charges. Reel
player availability was not tested. Search output can vary over time.

A next retrieval experiment should measure accepted, unique Reel additions per
query and then compare shorter same-language variants, evidence-based venue
queries, and an Instagram-first opening within the same request budget. Keep
the user's language fixed and compare full decks at the assigned city sizes.
Raising limits would be a separate policy change, not a hidden fallback.

## Verification and rollout

- Full backend suite: 815 passed, no skips. Ruff and whitespace checks passed.
- Deterministic planning evaluation: 10/10 fixtures passed, without model calls.
- Swift API contract and city-day view-model tests passed; iOS simulator build passed.
- City-day component inspected in light, dark and maximum accessibility text sizes.
- Additive database migration `f019a7c35b82` applied locally and tested through
  upgrade, full downgrade and upgrade on a disposable database.

The work is in the local working tree. No commit, merge or deployment was made.
