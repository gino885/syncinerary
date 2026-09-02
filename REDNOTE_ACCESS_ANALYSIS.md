# RedNote access: content, likes, and comments

Written 2026-09-02. Companion to `SOCIAL_SOURCES_PLAN.md`, which covers all
three platforms. This one answers a narrower question that came up in review:
Codex said RedNote comment and engagement data is not reachably public, and
that a comment-level pipeline is a follow-up requiring permitted access. Is
that true, or is there a GitHub tool or a paid plan that solves it?

Short version: Codex's conclusion is correct, but it under-explained why. The
data is absolutely obtainable, cheaply, today. Every route that obtains it
either requires your own logged-in cookie or buys from a vendor whose business
model a Chinese court has already ruled unlawful. That is the finding, and it
is a legal finding rather than a technical one.

---

## 1. Why RedNote is different from TikTok and Instagram

The other two platforms give you a supported, unauthenticated read path.
TikTok publishes `tiktok.com/oembed`, which is where the caption, creator, and
cover frame in `tools/fetch/social.py` come from. Instagram publishes an embed
endpoint whose terms permit an embed view and nothing else, which is why the
code stops at the search snippet there.

RedNote publishes neither. There is no oEmbed, no public note API, and no
developer program that serves note content. `open.xiaohongshu.com` exists, but
it is a merchant and mini-program platform: order management, logistics,
storefronts, and one application per category per developer. It does not
expose note bodies, like counts, or comment threads to a third party, and
application requires a Chinese business entity. The one official surface that
does carry engagement data is 蒲公英 (Pugongying), the creator-marketing
platform, and it is scoped to influencer analytics for brands running paid
campaigns, not to places. Neither is a route to "what are people saying about
this ramen shop."

So every remaining route reads the web or app client directly, and that client
is defended.

### 1.1 The signing wall

Requests to RedNote's web and app endpoints carry `x-s`, `x-t`, and
`x-s-common` headers computed client-side by obfuscated JavaScript. The
signing function rotates on roughly a monthly cadence, with input
concatenation order and magic constants changing each time. When it rotates,
every scraper built on the old logic breaks until somebody re-derives it.

On top of signing, the search page presents a login wall. The Apify vendors
are explicit about this: without a session cookie, keyword search returns zero
cards. Creator profile reads work anonymously; search and comments generally
do not.

This is the crux. Reading RedNote comments at scale is not a matter of finding
the right library. It requires a live authenticated session belonging to a
real account, refreshed every few days, plus proxies, because the platform
throttles aggressively and rotates bans.

---

## 2. The four routes, and what each actually costs

### Route A: self-hosted open source

The GitHub ecosystem here is mature and it does work. The main projects:

| Project | What it gets | Auth model |
|---|---|---|
| `NanmiCoder/MediaCrawler` | Notes, keyword search, first and second level comments, creator pages, comment word clouds | QR login via Playwright, or CDP attach to your own Chrome to reuse an existing session. Evaluates the page's own JS to produce signatures instead of reimplementing them |
| `cv-cat/Spider_XHS` | Notes, search, user pages, bulk collection | Cookie from a logged-in browser |
| `ReaJason/xhs` | Python SDK over the web endpoints: notes, users, comments | Cookie plus a signing callback you must supply |
| `JoeanAmier/XHS-Downloader` | Media download from accounts, searches, collections | Cookie |
| `xpzouying/xiaohongshu-mcp` | MCP server fronting the above for agent use | Cookie |

Two things to notice.

First, MediaCrawler's approach is the clever one and also the most legally
exposed. Rather than reimplementing `x-s`, it drives a real browser and asks
the page to sign for it. That sidesteps the monthly-rotation maintenance
problem entirely. It also means every request is issued by a logged-in
account, which is precisely the conduct the courts in section 4 looked at.

Second, MediaCrawler's own README forbids what you would be doing with it. It
states the project is for learning and research and is
"禁止用于商业用途" (forbidden for commercial use). A portfolio project you
show to employers is a defensible grey area; a product is not. Either way you
would be shipping a dependency whose license terms you are outside of, and
that is a bad answer to an interview question about how you evaluate
dependencies.

Running cost, from the practitioner write-ups: 8 to 16 hours initial build,
$50 to $200 a month in residential proxies, 4 to 8 hours of repair work one to
two times a month when signing rotates, and 1 to 2 hours a week of ongoing
babysitting. Call it $400 to $1000 a month in loaded engineering time for a
feature that is one of three inputs to one of six pipeline stages.

### Route B: unofficial hosted APIs, per-request billing

These vendors run route A for you and sell it as REST. No cookie of yours, no
proxy management, no signing maintenance.

| Vendor | Endpoints relevant to us | Price | Notes |
|---|---|---|---|
| TikHub | Note detail, comments, search, trending keywords, user profile, plus PGY creator analytics. App V2 and Web V3 series | $0.01 per request, flat, no volume discount under 1M/mo | $0.05 free signup credit, no card. 10 req/s default, 20 req/s for $5/mo up to 100 req/s for $55/mo |
| Rnote | 22+ endpoints across notes, comments, search, products, topics, PGY | $0.01 per request, billed per success | Free credits on signup. No compliance statement published |

Both state they return only publicly visible data and push responsibility for
storage and use onto you. Neither claims a license from RedNote, because
neither has one.

### Route C: unofficial hosted APIs, per-result billing

Apify hosts several actors. Same underlying technique, different meter.

| Actor | Price | Cookie needed |
|---|---|---|
| `zhorex/rednote-xiaohongshu-scraper` | $0.06 per post, $0.03 per comment, $0.12 per profile, $0.15 per video, $0.0125 startup | Search needs a `cookieString`; anonymous search returns nothing at no charge |
| `technicaldost/xiaohongshu-rednote-scraper` | $3.00 per 1,000 notes, $0.005 per comment, no start fee | Strongly recommended, search shows a login wall without it |

Reported reliability is 88.8% success with a 1.6 hour issue response on the
first, 100% run success on the second, with the caveat that it depends on
cookie freshness.

Note what the per-result meter does to a comment-heavy workload. A comments
endpoint call on TikHub returns a page of comments for one cent. Apify's
zhorex actor charges three cents per comment. For twenty comments that is
$0.01 against $0.60, a 60x difference. If comment text is the goal,
per-request billing wins by more than an order of magnitude.

### Route D: licensed Chinese analytics platforms

千瓜 (Qiangua), 新红 (Xinhong, from Newrank), 灰豚, 飞瓜. These are the
platforms Chinese brand teams actually use, with note search, creator
rankings, comment sentiment, and campaign tracking. Reported data depth ranks
千瓜 > 灰豚 > 蝉妈妈/新红.

They are seat-licensed SaaS dashboards sold to brands, not developer APIs.
Pulling their data into a product means either manual export or scraping your
own vendor. And as section 4 shows, at least one of them was the defendant.

---

## 3. What this costs Syncinerary specifically

Current config: `MAX_SOCIAL_PLACES_PER_CITY = 12`,
`SOCIAL_POST_READ_MAX_POSTS = 20`, up to 4 cities per trip.

Per trip on a per-request vendor, assuming one search per city, note detail on
the posts read, and one comment page for the twelve places that reach the
deck:

| Call | Count | At $0.01 |
|---|---|---|
| Search | 4 | $0.04 |
| Note detail | 80 | $0.80 |
| Comment pages | 48 | $0.48 |
| Total | 132 | **$1.32** |

On the zhorex per-result meter the same trip is roughly $4.80 in posts plus
$28.80 in comments if each page yields twenty. Not viable.

Two project-specific catches:

**The step cap.** `SYNC_MAX_STEPS` is 50 and gather already runs about 47
steps. 132 additional external calls does not fit. `gather_max_steps()`
already reserves headroom for Google verification per social place; a RedNote
detail pass needs the same treatment, or it needs to be a batched fan-out that
counts as one harness step. This is a real design constraint, not a footnote.

**The schema is already ready.** `MinedPost` in
`agents/gather/social.py:163` carries optional `like_count` and
`comment_count`, `buzz_score` at line 219 applies a logarithmic engagement
boost when they are present, and `ranked_posts` at line 179 sorts posts with
explicit engagement ahead of those without. Codex built the receiving end
correctly. Only the supply is missing. If you ever add a permitted source,
it plugs in without touching the scoring.

---

## 4. The legal picture, which is the part that decides this

Two Chinese judgments matter, and they cut in different directions.

**Xingyin (Xiaohongshu) v. Xiamen Guqiao.** Xiamen Intermediate Court in
September 2022, affirmed by the Fujian High Court in January 2024. Guqiao
shipped bulk downloader tools. The court split the conduct: the video tool,
which modified MD5 values to strip watermarks and evade detection, was unfair
competition. The bulk image download function, on its own, was not. Damages
¥150,000. The useful signal here is that bulk collection of public content was
not by itself the violation. Circumvention was.

**Xiaohongshu v. Chanmama (蝉妈妈).** Filed July 2022, final judgment April
2025, Hangzhou Intermediate Court. Per news reporting, the court found the
defendant rotated user IDs and accelerated IP rotation to bypass Xiaohongshu's
technical protection measures, harvested account information, published
content, and browse and like data, then processed and resold it. Held to be
unfair competition. ¥4.9 million in damages, plus orders to delete the data
and publish a statement.

That second case is the one that governs this decision, because the conduct it
describes is not adjacent to routes A, B, and C. It is exactly those routes.
Rotating identities and IPs to get past technical measures is what MediaCrawler
does when it drives a logged-in browser through a proxy pool. Processing and
reselling the result is the entire business of TikHub, Rnote, and the Apify
actors. A vendor's "we only return publicly available data" line did not save
Chanmama, and there is no reason to think it would save the next one.

This maps directly onto your own `CLAUDE.md` section 15, which puts
"unauthorized scraping of Xiaohongshu... including login automation,
access-control bypass, or collection that violates platform terms" out of
scope, and permits "configured official APIs and platform-permitted public
metadata access." Every route above fails that test. Route A fails on login
automation. Routes B and C fail because they are login automation performed by
somebody else, and you would be knowingly buying the output.

Worth stating plainly since this is a portfolio piece: the interview risk is
asymmetric. Nobody will fault you for a card that says "3 posts mention this
place" instead of "1,247 likes." Someone will absolutely ask where the like
count came from, and "a reseller that got sued for ¥4.9M for exactly this"
is a bad answer to give a company's engineering team.

---

## 5. Recommendation

Keep Codex's position. Extend the reasoning in `CLAUDE.md` so the next person
does not re-litigate it, because the surface answer ("just use a scraper")
looks obviously correct until you read the case law.

Concretely:

1. **Do not buy engagement or comment data for RedNote.** Not from a vendor,
   not from a self-hosted crawler. Keep RedNote at the search-index snippet,
   where it is today.

2. **Rank on evidence, not on engagement.** `buzz_score` already degrades
   gracefully when `like_count` and `comment_count` are `None`. Mention count
   across independent posts is a defensible ranking signal on its own, and it
   is honest. Leave the optional fields in place for TikTok and Instagram,
   which can legitimately fill some of them.

3. **Say so in the UI.** The 🔥 badge should say what it knows. "Mentioned in
   3 posts" is a claim you can defend and link out to under M5a. "1.2k likes"
   is not. This is the same principle already applied to dietary tags in
   section 8.6, where unknown information is never presented as safe.

4. **Record the follow-up honestly.** Comment-level RedNote mining is not
   blocked on engineering effort. It is blocked on a data license that
   RedNote does not currently sell for this use case. Frame it that way in
   the roadmap rather than as a technical TODO, because a technical TODO
   invites somebody to solve it with a scraper.

5. **If the engagement signal genuinely matters later**, the only clean path
   is a commercial data agreement with Xiaohongshu, or Pugongying access under
   a Chinese business entity for the creator-scoped subset. Both are business
   development, not engineering. Neither is worth it for a portfolio project.

The one thing worth reconsidering is scope rather than method. If the goal is
"what do travelers actually say about this place," Google Places reviews are
already licensed, already in the stack, already city-verified, and already
carry text and rating counts. That gets you most of the signal RedNote
comments would provide, from a source with terms you are inside of.
