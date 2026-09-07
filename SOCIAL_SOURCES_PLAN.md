# Social sources: what is read today, what will be read, and the budget

Written 2026-09-02 on branch `m6-replan-hitl` (working tree also carries the
uncommitted M5a "source links" spec in `CLAUDE.md`). This file is the working
plan for making Instagram, TikTok, and RedNote content actually reach the
swipe card: the post link on the badge, the words from the post on the card,
and a bounded read of what a TikTok post contains. It stays in the repo as
the record of the investigation and the decisions; the durable spec lives in
`CLAUDE.md` sections 8.2, 8.5, and M5a.

## 1. Verification: what the gather does today

Checked against `syncinerary/agents/gather/social.py`,
`syncinerary/tools/fetch/social.py`, `syncinerary/agents/gather/personal.py`,
`syncinerary/api/schemas.py`, and the iOS views.

### 1.1 Are Instagram reels and TikTok really sources?

Yes, but only through a search index.

| Step | What happens | Where |
|---|---|---|
| Search | One Brave Web Search query per planned search, chosen adaptively from three intents (PLACES, FOOD, HIDDEN_GEMS) and capped at 8 per city: `site:instagram.com/reel`, `site:tiktok.com`, `site:xiaohongshu.com/discovery/item` (Mandarin query) | `agents/gather/social_search.py::plan_next_search`, `tools/fetch/social.py::_SEARCH_SCOPE`, `build_discovery_query` |
| Read | Only the search index `title` and `description` snippet of each result (roughly 150 to 250 characters). Nothing opens the post, the video, the audio, the frames, or the on-screen text | `DiscoveredSocialURL.indexed_text` |
| Extract | One cheap-model NER call per search over the numbered snippets | `social.py::extract_post_places` |
| Threshold | A name needs 3 distinct post URLs before it is geocoded | `is_eligible`, `BUZZ_MIN_SOURCE_COUNT` |
| Verify | Google Places text search inside the city | `discover_social_candidates` |
| Store | `enrichment.social_platforms`, `enrichment.social_post_urls`, `trending_signals`, one `buzz` source row | `to_candidate` |

Real data in the local database confirms both the wiring and its weakness:
715 candidate rows, 3 of them buzz cards, and those three are "Otaru",
"Otaru Canal", and "Sapporo". Two of the three are city names that the snippet
NER let through. Snippets are too thin to name a restaurant or a viewpoint
reliably, which is exactly what the richer read below is for.

### 1.2 Do we read the reel or the TikTok video now?

No. Depth of read per path today:

| Path | Instagram | TikTok | RedNote |
|---|---|---|---|
| Automatic buzz discovery | Brave snippet | Brave snippet (the official oEmbed caption is not fetched for discovered posts) | Brave snippet |
| Traveler-pasted link | Brave snippet for that URL | Official oEmbed: caption, author, cover thumbnail. The thumbnail is stored for display (`platform_preview_url`) and is never looked at by a model | Brave snippet for that URL |
| Traveler-uploaded screenshot | Vision OCR of the user's own image | same | same |

### 1.3 Is the link on the card, with the post's information?

No. The URLs exist in Postgres (`enrichment.social_post_urls` for buzz,
`enrichment.source_url` for pasted links) but never reach the client:

- `SourceBadgeOut` is `kind`, `label`, `contributor_name`. No URL, no platform.
- iOS `SourceBadgesView` renders a plain `Label`; nothing is tappable.
- The swipe card (`CandidateCardOut`) carries no description at all. The
  itinerary stop shows `source_description`, which for a buzz card is the
  Google editorial summary, not what the posts said.

So the M5a spec in `CLAUDE.md` (source links) is written but not built, and
"put the info from the source on the card" has no wire field to carry it.

## 2. What each platform permits (the constraint on "reading the video")

| Platform | Permitted read | Not permitted | Consequence |
|---|---|---|---|
| TikTok | Official oEmbed `https://www.tiktok.com/oembed?url=` with no key: `title` (the full caption), `author_name`, `author_url`, `thumbnail_url` (the cover frame). Documented at developers.tiktok.com/doc/embed-videos | Downloading the video or audio, scraping the page | We can read the caption and the cover frame. No transcript |
| Instagram | Meta oEmbed is tokenless for public posts since June 2026, but it no longer returns `thumbnail_url` or `author_name`, and Meta's terms say using its metadata or content "for any purpose other than providing a front-end view" is prohibited. Brave index snippets remain the only permitted text | Graph API on other people's media, page scraping, oEmbed data fed to a model | Instagram stays snippet-only. The link on the card is the honest way to let the traveler read the reel |
| RedNote | No official public read API. Brave index snippet only | Scraping | Snippet-only, link on the card |

Nothing permits pulling a transcript, so "reading the video" for this product
means: caption plus cover frame for TikTok, and the search snippet for the
other two, with the post itself one tap away.

## 3. Target state after this work

| Path | Instagram | TikTok | RedNote |
|---|---|---|---|
| Automatic buzz discovery | Brave snippet, link on card | Brave snippet + oEmbed caption + author + cover-frame on-screen text (vision OCR), link on card | Brave snippet, link on card |
| Traveler-pasted link | unchanged | caption first; cover-frame OCR only as a fallback when the caption names no place | unchanged |

Every card shows, in addition to the badge link:

- `description`: one grounded sentence from the top post for a buzz card
  (LLM highlight, quoted or closely paraphrased from that post's text), else the
  existing Google or caption description.
- `description_source`: "TikTok", "Instagram Reel", "RedNote", or "Google".
- `source_posts`: every post behind a buzz card, each with platform, URL,
  author (TikTok only), and its highlight, so the count on the badge can be
  checked against the posts.

The LLM boundary does not move: the model transcribes and names, code counts,
thresholds, geocodes, orders, and decides.

## 4. Work packages

### WP1. TikTok post read tool (batched, cached, one harness step)

`tools/fetch/social.py`

- `TikTokPostReadBatchInput(urls: list[str], max_posts, include_cover: bool)`.
- `TikTokPostRead(canonical_url, platform_id, caption, author_name, author_url,
  thumbnail_url, cover_image: {media_type, data_base64} | None, error | None)`.
- Concurrency 4, per-post timeout 10 s, cover download capped at 1.5 MB and
  jpeg/png/webp only. A removed video (404) or a bad cover is recorded as
  `error` on that post and never fails the batch; the batch raises only when
  the input is invalid. Counts of failures go on the span.
- Redis cache per post, 24 h (`social:tiktok:post:v1:<sha>`), so a re-gather or
  a second traveler's gather costs nothing.
- Registered as `ToolDefinition("tiktok_post_read_batch")` so the whole batch is
  one `run_tool` step.

### WP2. Cover-frame OCR (one cheap-model call, cached, capped)

`agents/gather/social_read.py` (new)

- `extract_cover_text(posts) -> {post_index: on_screen_text}`: one
  `SYNC_CHEAP_MODEL` call carrying up to `SOCIAL_COVER_OCR_MAX_IMAGES` images,
  structured output, prompt rules copied from `attachments.py`: transcribe
  visible text only, keep the original language, never guess a location from
  scenery or style.
- Redis cache per post URL, 7 days (`social:cover_text:v1:<sha>`).
- `SOCIAL_COVER_OCR_ENABLED = True` in `config/gather.py`; off means no vision
  call and no thumbnail download.

### WP3. Richer evidence into NER, per-post highlights out

`tools/fetch/social.py`, `agents/gather/social.py`

- `DiscoveredSocialURL` gains optional `caption`, `author_name`,
  `thumbnail_url`, `cover_text`; `evidence_text` joins snippet, caption, and
  cover text without repeating the same line.
- NER output gains an optional `highlight` per mention (at most 120
  characters, drawn only from that post). This is the "info from the source".
- `MinedPlace` keeps `posts: list[MinedPost]` (platform, url, rank, author,
  highlight) alongside `post_urls`; posts stay in search-rank order so "the
  highest-ranked URL" is deterministic.
- `to_candidate` writes `enrichment.social_posts` and
  `enrichment.social_highlight`; `merge_into_pool` and `dedup._merge` keep them.
- NER prompt tightened: a mention must be a specific visitable place, and the
  model is told the snippet may be followed by a caption and on-screen text.

### WP4. Source links and source info on the wire (this is M5a)

`api/schemas.py`

- `SourceBadgeOut` += `url: str | None`, `platform: str | None`.
  - trending: first post URL and its platform label.
  - discovered: Google Maps place page from `google_place_id` using the
    documented Maps URLs form
    `https://www.google.com/maps/search/?api=1&query=<name>&query_place_id=<id>`.
  - attached_by_you / attached_by_group: `enrichment.source_url`; a screenshot
    attachment has none and stays plain text.
  - Social URLs are re-run through `normalize_social_url` at output time, so a
    row that somehow holds a tracking link or an unsupported host renders with
    no link rather than a bad one.
- New `SourcePostOut(platform, label, url, author_name, highlight)`;
  `CandidateCardOut.source_posts` and `ItineraryStopOut.source_posts`.
- `CandidateCardOut.description` and `description_source`, sharing the
  itinerary's description logic, with the social highlight preferred for buzz
  cards.
- No change to `sources` or `enrichment` exposure: raw provenance stays behind
  the display-safe schema (existing test keeps asserting that).

### WP5. iOS

- `SourceBadge` += `url`, `platform`; `SourceBadgesView` renders a `Link` when
  a URL is present (the system hands a TikTok or Instagram URL to the installed
  app, otherwise Safari) with accessibility label
  "<label>, opens the post" or ", opens Google Maps". No URL means the same
  plain label as today.
- `SourcePost` model; `CandidateCard` += `description`, `descriptionSource`,
  `sourcePosts`; `ItineraryStop` += `sourcePosts`.
- `CandidateCardView` shows the description with its source and a "From the
  posts" list of links; `ItineraryStopRow` shows the same list compactly.
- `APIContractTests.swift` covers the new fields; verified with the `swiftc`
  contract build from `ios/README.md` and an `xcodebuild` simulator build.

### WP6. Pasted TikTok link fallback

`agents/gather/personal.py`

- When the oEmbed caption names no place and a cover thumbnail exists, run the
  cover OCR on that one image and retry the caption extraction on the on-screen
  text. One extra call, only on the path that today ends in "Type the place
  name above, then add again".

### WP7. Config, docs, tests

- `config/gather.py`: `SOCIAL_COVER_OCR_ENABLED`, `SOCIAL_COVER_OCR_MAX_IMAGES`,
  `SOCIAL_POST_READ_MAX_POSTS`, cache TTLs.
- `CLAUDE.md` section 8.2: a short "what is read per platform" table matching
  section 3 above, so the spec and the code agree.
- Tests (pytest, stubs only, no provider spend):
  - tool: valid posts kept, per-post 404 skipped, cover size cap, cache hit
    skips HTTP, batch is one tool call.
  - OCR: one LLM call for N images, disabled flag makes zero calls, cache hit
    makes zero calls, refusal is a typed empty result.
  - social: TikTok evidence text includes caption and cover text; highlights
    land on `enrichment.social_posts`; post order is deterministic; the
    `merge_into_pool` and dedup paths keep posts; a 12-post city still costs
    exactly one read step and one OCR step.
  - schemas: each badge kind links to the right URL, a missing URL is `None`,
    a tracking URL is refused, `source_posts` lists every post, description
    prefers the social highlight.
  - personal: pasted TikTok link with a placeless caption falls back to cover
    OCR and resolves.
  - iOS contract test decodes `url`, `platform`, `source_posts`, `description`.

## 5. Budget

### 5.1 Per gather, per city (worst case, caps at defaults)

| Item | Today | After | Cost |
|---|---|---|---|
| Brave queries | 3 | 3 | unchanged, 24 h cache. Existing free plan 2,000/month; new plans get about 1,000 queries of credit |
| TikTok oEmbed requests | 0 | at most 20 | free, no key, 24 h cache |
| Cover downloads | 0 | at most 20, 1.5 MB each | free |
| Vision OCR calls | 0 | 1 call, at most 12 images by default | about 1.3K input tokens per image: roughly 16K tokens, about $0.02 at Haiku list price |
| NER calls | 3 | 3 | TikTok input grows about 2 to 4x, still under 10K tokens |
| Harness steps | about 47 for one city, five days, two travelers | +2 per city | see 5.2 |

Pasted TikTok link: +1 vision call only when the caption names no place.

### 5.2 Step cap is the tight budget, not dollars

`SYNC_MAX_STEPS=50` counts every tool call and LLM call in one tracked run,
and the gather run also includes the badge node. Estimate for one city, five
days, two travelers, before this work:

| Source of steps | Count |
|---|---|
| city resolve + timezone | 2 |
| destination searches | 9 |
| per-cluster meal searches | up to 10 |
| Brave searches + RedNote translation | 4 |
| NER | up to 3 |
| buzz geocoding | up to 12 |
| profile suggestions + verification | up to 5 |
| badge generation | 2 |
| Total | about 47 |

Two cities already exceed 50 on paper. This work adds 2 steps per city by
batching (one read step, one OCR step) instead of 20 to 40. The recorded
`agent_run` rows hold no gather runs, so the estimate could not be checked
against a real run. Recommendation: raise `SYNC_MAX_STEPS` to 100 in `.env`
(`.env` is yours, so it is not changed here). The dollar cap `$2.00` is not at
risk: the harness prices every call at Opus rates ($5 / $25 per million), so a
Haiku OCR call is over-charged 5x in the ledger, which errs on the safe side.

### 5.3 Controls added

| Control | Default | Effect |
|---|---|---|
| `SOCIAL_POST_READ_MAX_POSTS` | 20 | posts per city sent to the TikTok read |
| `SOCIAL_COVER_OCR_ENABLED` | True | off means no downloads and no vision call |
| `SOCIAL_COVER_OCR_MAX_IMAGES` | 12 | images per OCR call, in search-rank order |
| `SOCIAL_COVER_MAX_BYTES` | 1.5 MB | per cover download |
| Post read cache | 24 h | Redis, per post |
| Cover text cache | 7 days | Redis, per post |

## 6. Decisions taken without asking (change them here before the code lands)

1. TikTok cover-frame OCR is on by default. It reads a platform-provided
   public preview through the official embed API, the same class of data the
   product already displays. It is the only permitted way to "read" any part
   of the video. `SOCIAL_COVER_OCR_ENABLED=False` turns it off.
2. Instagram is not read more deeply than the search snippet, because Meta's
   oEmbed terms forbid feeding its data to anything but an embed view.
3. Per-post failures inside the TikTok batch are skipped and counted, not
   raised, because a deleted video is normal. A missing or refused provider at
   the search stage still raises, as before.
4. `.env` is not modified. The step cap recommendation in 5.2 is yours to apply.
5. Nothing is committed. All work stays in the working tree on
   `m6-replan-hitl` until you say where it should live (a separate `m5a`
   branch would match the one-milestone-per-branch convention).

## 7. Sequence

1. This plan.
2. Backend: config, WP1 tool, WP2 OCR, WP3 social wiring, WP4 schemas, WP6
   fallback, tests, `ruff`.
3. iOS: models, views, contract test, `xcodebuild` simulator build.
4. `CLAUDE.md` 8.2 table and README notes.
5. Final report with what was verified against stubs versus live providers.

Done when: the pytest suite and the Swift contract test pass; a buzz card in
the deck and on the itinerary carries a tappable link to the post that named
it plus a description quoted from that post; a TikTok gather reads captions
and cover text in exactly two harness steps per city; and turning the OCR flag
off produces a gather with zero vision calls.

## 8. Status, 2026-09-02

Built and verified with stubs (no provider spend in tests):

| Package | State | Evidence |
|---|---|---|
| WP1 batched TikTok read tool | done | `tests/test_m5a_social_read.py`: order, per-post 404, byte cap, non-image cover, cache hit, failed read not cached, non-TikTok URL refused without a request |
| WP2 cover-frame OCR | done | one multimodal call, image cap, refusal, invalid output surfaced, flag off means zero images even if a read carried one |
| WP3 evidence into NER, per-post highlights | done | evidence text labels and dedup, highlight length cap, `social_posts` and `social_highlight` on the candidate and through `merge_into_pool` |
| WP4 links and posts on the wire | done | `tests/test_m5a_source_links.py`: every badge kind, plain text when no URL, search pages and unsupported hosts dropped, older rows still list posts, deck and itinerary agree |
| WP5 iOS | done | `SourceBadge.url/platform`, `SourcePost`, `SourceBadgesView` links out, `SourcePostsView`, card description; Swift contract test passes |
| WP6 pasted TikTok fallback | done | placeless caption reads the cover once, then resolves |
| WP7 config, docs | done | `config/gather.py` knobs, `CLAUDE.md` 8.2 table, iOS README |

Backend: 455 tests pass (424 before this work), `ruff` clean.

Not verified against the live providers inside the test suite, by design.
Smoke-tested by hand on 2026-09-02 against one public TikTok post
(`@biteswithlily/video/7512478468400090389`, a Sapporo ramen video): the
official embed API returned the full caption naming three restaurants and the
creator, the cover frame downloaded and the vision call transcribed its title
("Eating ramen for 24 hours"), and NER returned exactly those three places
with no city-name leak. Highlights were empty because that caption only names
places, which is the intended behaviour. Total spend: two Haiku calls, well
under one cent.
