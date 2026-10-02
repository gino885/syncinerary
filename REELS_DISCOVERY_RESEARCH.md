# More Reels in discovery

Research date: September 16, 2026. The proposal below was subsequently approved
and implemented. See `evidence/reels/README.md` for live measurements and limits.

The requested outcome is more than 50% Reels content and fewer plain Google results. This proposal interprets Reels as Instagram Reels, and the percentage as the share of unique, visible swipe cards supported by a relevant Reel. TikTok videos and RedNote notes remain useful but do not count toward that Instagram metric.

## Findings before implementation

- `syncinerary/config/gather.py` already sets `BUZZ_RATIO = 1.0` and prioritizes Instagram. Raising the social ceiling cannot solve the shortage.
- `syncinerary/tools/fetch/social.py::_search_brave` queries Brave's web index with `site:instagram.com/reel`. It requests one page of at most 20 results, including extra snippets. It does not use Brave's video index or paginate. Social search currently uses Brave, while Google Places supplies verification and fallback places.
- Instagram extraction receives indexed titles and usable snippets. The spec records truncated titles and repeated profile text in an earlier Sapporo sample. More returned URLs will not necessarily produce more identifiable venues.
- `syncinerary/agents/gather/social_search.py::plan_next_search` stops on combined lane supply, not verified Instagram Reel coverage. RedNote and TikTok can satisfy its targets while Reel coverage remains low.
- Verification happens after city mining. Rejected names do not trigger a second discovery pass within that city loop.
- All social sources share a maximum of 40 verification attempts. For Chinese locales, `discover_social_candidates` lets RedNote guides use up to one third first and deducts actual guide attempts from the remaining allocation.
- `discover_candidates` puts social candidates ahead of general fallback, but adds Google-only food and attraction options to cover category shortages. There is no explicit Reel share constraint on the final deck.

These findings describe the code, not the measured source mix of a current production trip.

## Source options

| Option | What it provides | Assessment |
|---|---|---|
| Brave Video Search | A dedicated video index with site operators, pagination, country/language controls, and freshness filters | First experiment. Reuses the existing provider integration, subject to account access. Instagram coverage and extraction yield need measurement. |
| SerpApi Google Short Videos | A separate short-video search surface returning links, titles, channels, and other video metadata | Optional comparison source. It remains Google-dependent and is a third-party service, so it does not achieve independence from Google. |
| Connected Instagram travel creators | Official access to media from professional accounts that authorize the app | Stronger long-term candidate for richer evidence and repeatable destination coverage. Requires creator participation and appropriate app access. |
| Meta Business Discovery / hashtagged media | Meta documents professional-account metadata and hashtagged-media capabilities through Facebook Login | Investigate after confirming current permissions and permitted use for this travel product. Do not assume an unrestricted public Reels search API. |
| Traveler-supplied Reel links and context | High-intent recommendations supplied by the group | Useful additional supply. A link alone may still lack sufficient public text to identify a venue. |

Brave documents `/res/v1/videos/search`, site-specific search, and pagination. A reasonable experiment is to compare identical city and intent queries against the existing web endpoint. Freshness is an index signal and must not be relabeled as a verified post publication date. [Brave Video Search documentation](https://api-dashboard.search.brave.com/app/documentation/video-search/get-started)

SerpApi documents `engine=google_short_videos`, site operators, and result metadata. It should be evaluated on incremental verified places, not on how many thumbnails it returns. No media download is needed for this comparison. [SerpApi Short Videos documentation](https://serpapi.com/google-short-videos-api)

Meta's official Postman collection describes professional-account media access, hashtagged media, and other professional-account metadata. Facebook Login requires a linked Page; Instagram Login does not. These routes have different capabilities and must not be treated as interchangeable. The collection does not establish authorization for an arbitrary public travel-content corpus. [Meta's official Instagram API collection](https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00)

The detailed Business Discovery, hashtag-search, and public-content-access pages returned the actual fetch error `(429) Too Many Requests`. Their current detailed permission requirements remain unverified in this research. No authenticated Meta requests were made.

## Recommended product target

Aim for 60% Reel-backed cards, providing a buffer above the requested strict majority. A proposed starting mix is 60% Instagram Reels, 20% other social content, and at most 20% Google-only fallback, when sufficient eligible supply exists. These are proposed operating targets, not measured achievable rates.

For a 40-card deck:

- Minimum strict majority: 21 cards with relevant Instagram Reel evidence.
- Operating target: 24 such cards.
- A card with several Reels counts once. The same Reel supporting multiple genuinely named venues does not become multiple independent sources.
- A Google-verified social recommendation remains social-backed. Verification is distinct from discovery origin.
- An unrelated Reel attached to a Google result does not qualify.
- Measure the visible deck after deduplication and dietary filtering. Exclude lodging, which is outside swipe. Report automatic-only and attachment-inclusive shares separately so user contributions cannot conceal weak automatic discovery.
- Track successful Reel display separately from Reel-backed provenance. A valid link is not proof that an embed plays in the app.

Also track Google-only share and Google discovery calls separately. A deck may look social while still requiring many Google searches. Google verification calls should remain a separate category.

## Changes most likely to help

1. **Measure the current funnel.** Record unique Reel URLs, posts with readable venue evidence, extracted names, verified places, accepted cards, and final visible Reel share by city and category. Record rejection and fallback reasons.
2. **Compare dedicated video search.** Keep the existing web search as the baseline. Add a bounded second page only when the first page contributes new useful evidence. Deduplicate by canonical post URL across sources before extraction. Preserve the current output-language rules.
3. **Search for missing coverage.** When food or hidden-gem coverage is short, direct remaining Instagram searches there before asking Google for generic replacements. Reuse the existing semantic intents; do not simply multiply every query template.
4. **Feed verification results back into discovery.** Stop when verified supply meets category, city, lane, and Reel goals, or when the explicit cost and exhaustion limits are reached. Raw extracted names are not enough.
5. **Protect the Reel verification allocation.** RedNote guide coverage should not consume the attempts needed to test the requested Reel majority. Reallocate within a declared budget first; increase the ceiling only with measured cost and yield evidence.
6. **Select the deck with an explicit Reel target.** Preserve hidden gems, food coverage, city boundaries, personal attachments, and admission standards. Count again after final filtering. Do not remove useful non-Reel cards solely to manufacture a passing percentage. A shortfall must remain a reported shortfall.
7. **Build repeatable creator supply.** Pilot connected local travel creators for a few destinations. This offers a route away from repeated search-index discovery, provided the authorized fields and retention rules fit the product. Reusable destination evidence requires explicit storage permission and revalidation of availability.

The budget arithmetic matters: at the configured expected verification yield of 75%, 24 Reel-backed places require about 32 Reel verification attempts. If a Chinese-language trip spends all 13 available guide attempts from the 40-attempt ceiling, only 27 remain for all adaptive platforms. At that assumed yield, even allocating all 27 to Instagram gives about 20 verified Reel places. This is illustrative planning arithmetic, not a measured yield or a hard upper bound on actual successes.

## Bounded validation before rollout

Compare Tokyo, Sapporo, and a smaller destination such as Atami, with Chinese and English output and both single-city and multi-city trips. Keep input profiles and budgets fixed across the current pipeline and proposed variant.

Report per trip, rather than only averaging across destinations:

- Final Reel-backed share, other-social share, and Google-only share.
- Number of admissible unique cards, with city, food, attraction, and hidden-gem coverage.
- Distinct supporting creators and posts, so a single listicle does not conceal narrow supply.
- New verified Reel-backed places per search and per verification attempt.
- Provider calls, model cost, elapsed time, and the reason each run stopped.
- Reel link availability and actual embed success as separate measurements.

The source-mix goal passes only when the final relevant deck exceeds 50% without invalid places, duplicate padding, or lost required coverage. A general claim that this works across destinations requires live results, including sparse cities. Subsequent experiments and their shortfalls are recorded in `evidence/reels/README.md`.

Recommended first implementation scope: source-mix instrumentation, a Brave video-search comparison, and verification-aware Reel targeting. Treat official creator integration as a separate access-dependent workstream. Keep Google Places for reality checks, lodging, and measured coverage gaps.
