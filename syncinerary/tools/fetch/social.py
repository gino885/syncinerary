"""Platform-safe social URL normalization and deterministic search queries."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import re
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from syncinerary.config import settings
from syncinerary.config.gather import (
    SOCIAL_COVER_MAX_BYTES,
    SOCIAL_COVER_OCR_MAX_IMAGES,
    SOCIAL_POST_READ_CACHE_TTL_SECONDS,
    SOCIAL_POST_READ_MAX_POSTS,
)
from syncinerary.domain.models import SocialPlatform
from syncinerary.harness import ToolDefinition
from syncinerary.store.redis import get_redis

BRAVE_SEARCH_CACHE_TTL_SECONDS = 86_400


class SocialSearchCache(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> object: ...


class SocialReferenceKind(StrEnum):
    POST = "post"
    SHORT_LINK = "short_link"
    SEARCH = "search"


class SocialReference(BaseModel):
    platform: SocialPlatform
    kind: SocialReferenceKind
    canonical_url: str
    platform_id: str

    @property
    def is_attachable(self) -> bool:
        return self.kind in {
            SocialReferenceKind.POST,
            SocialReferenceKind.SHORT_LINK,
        }


class BraveSocialSearchInput(BaseModel):
    """One search, already worded by build_discovery_query.

    The tool used to take a destination and compose three queries of its own,
    which meant the caller could not choose what to search next. Query wording
    is now the planner's decision (see agents/gather/social_search.py) and this
    layer does one external request, so the cache key is the request.
    """

    platform: SocialPlatform
    query: str = Field(min_length=1, max_length=400)
    # The provider's maximum. Cross-source counting only means something with
    # enough posts for a genuinely popular place to recur, and a larger page
    # costs the same one request as a small one.
    max_results: int = Field(default=20, ge=1, le=20)


class DiscoveredSocialURL(BaseModel):
    reference: SocialReference
    query: str
    rank: int = Field(ge=1)
    # Title and description as the search index already publishes them. For
    # Instagram and RedNote this is the only post text read: nothing logs in
    # and nothing fetches the post body from a platform that does not permit
    # it.
    title: str | None = None
    description: str | None = None
    # TikTok only, filled by agents/gather/social_read.py from the official
    # embed API: the caption, the creator, the cover frame, and the text the
    # cover frame shows. Never set for the other two platforms.
    caption: str | None = None
    author_name: str | None = None
    thumbnail_url: str | None = None
    cover_text: str | None = None
    # Only populated when the public search result labels a number as this
    # post's likes or comments. Account follower/total-like counts are not
    # treated as post engagement.
    like_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)

    @property
    def indexed_text(self) -> str:
        return "\n".join(part for part in (self.title, self.description) if part)

    @property
    def evidence_text(self) -> str:
        """Everything read about the post, labelled, without repeating a line.

        The search index often stores the caption as the description, so the
        same sentence would otherwise reach the extractor twice.
        """
        parts: list[str] = []
        seen: set[str] = set()
        for label, value in (
            ("Title", self.title),
            ("Snippet", self.description),
            ("Caption", self.caption),
            ("On screen", self.cover_text),
        ):
            cleaned = " ".join((value or "").split())
            if not cleaned or cleaned.casefold() in seen:
                continue
            seen.add(cleaned.casefold())
            parts.append(f"{label}: {cleaned}")
        return "\n".join(parts)


class BraveSocialSearchOutput(BaseModel):
    results: list[DiscoveredSocialURL]


class TikTokOEmbedInput(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SocialPostPreview(BaseModel):
    platform: SocialPlatform
    canonical_url: str
    platform_id: str
    caption: str
    author_name: str
    author_url: str
    thumbnail_url: str | None = None


def _unsupported() -> ValueError:
    return ValueError("expected a supported social URL")


def normalize_social_url(url: str) -> SocialReference:
    """Classify a supported public URL and remove share-tracking parameters."""
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _unsupported()

    host = parsed.hostname.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")

    if host == "instagram.com":
        match = re.fullmatch(r"/(reel|p)/([A-Za-z0-9_-]+)", path)
        if match is None:
            raise _unsupported()
        media_type, shortcode = match.groups()
        return SocialReference(
            platform=SocialPlatform.INSTAGRAM,
            kind=SocialReferenceKind.POST,
            canonical_url=f"https://www.instagram.com/{media_type}/{shortcode}/",
            platform_id=shortcode,
        )

    if host == "tiktok.com":
        video = re.fullmatch(r"/@([^/]+)/video/(\d+)", path)
        if video is not None:
            username, video_id = video.groups()
            return SocialReference(
                platform=SocialPlatform.TIKTOK,
                kind=SocialReferenceKind.POST,
                canonical_url=(
                    f"https://www.tiktok.com/@{username}/video/{video_id}"
                ),
                platform_id=video_id,
            )

        discovery = re.fullmatch(r"/discover/([A-Za-z0-9_-]+)", path)
        if discovery is not None:
            slug = discovery.group(1)
            return SocialReference(
                platform=SocialPlatform.TIKTOK,
                kind=SocialReferenceKind.SEARCH,
                canonical_url=f"https://www.tiktok.com/discover/{slug}",
                platform_id=slug,
            )
        raise _unsupported()

    if host == "xhslink.com":
        short_link = re.fullmatch(r"/(?:o|a)/([A-Za-z0-9_-]+)", path)
        if short_link is None:
            raise _unsupported()
        link_id = short_link.group(1)
        prefix = path.split("/", 2)[1]
        return SocialReference(
            platform=SocialPlatform.REDNOTE,
            kind=SocialReferenceKind.SHORT_LINK,
            canonical_url=f"https://xhslink.com/{prefix}/{link_id}",
            platform_id=link_id,
        )

    if host == "xiaohongshu.com":
        note = re.fullmatch(r"/(?:discovery/item|explore)/([A-Za-z0-9]+)", path)
        if note is None:
            raise _unsupported()
        note_id = note.group(1)
        return SocialReference(
            platform=SocialPlatform.REDNOTE,
            kind=SocialReferenceKind.POST,
            canonical_url=f"https://www.xiaohongshu.com/explore/{note_id}",
            platform_id=note_id,
        )

    raise _unsupported()


class SearchIntentType(StrEnum):
    """What a search is looking for, and therefore which lane it feeds.

    Three intents rather than a category taxonomy. PLACES and FOOD ask what a
    destination is broadly known for and stock the Trending pool; HIDDEN_GEMS
    asks a different question of the corpus and stocks the For You pool. That
    the lanes have different discovery sources, rather than one pool sorted
    two ways, is the point: a hidden gem is mentioned once by definition, so
    no reranking of a popularity-driven pool can surface it.

    Traveler interests deliberately do not appear here. They rank the For You
    pool rather than steering search, so provider cost stays flat whether a
    group listed two interests or twenty.
    """

    PLACES = "places"
    FOOD = "food"
    HIDDEN_GEMS = "hidden_gems"


#: Which lane each intent stocks. Provenance travels with the candidate, so a
#: place found by both a broad and a hidden-gem search is known to be both.
TRENDING_INTENTS = (SearchIntentType.PLACES, SearchIntentType.FOOD)
FOR_YOU_INTENTS = (SearchIntentType.HIDDEN_GEMS,)

#: The opening sequence. All three sources are established before the planner
#: starts reacting to what it found, so the first adaptive decision is made
#: with evidence about every lane rather than about one.
OPENING_SEQUENCE = (
    SearchIntentType.PLACES,
    SearchIntentType.FOOD,
    SearchIntentType.HIDDEN_GEMS,
)


class QuerySpecificity(StrEnum):
    """How narrowly one intent is worded.

    A search that returns nothing is usually over-specified rather than
    evidence that the place does not exist, so the fallback ladder removes
    words instead of adding them.
    """

    SPECIFIC = "specific"
    NORMAL = "normal"
    BROAD = "broad"


_BROADER_THAN: dict[QuerySpecificity, QuerySpecificity | None] = {
    QuerySpecificity.SPECIFIC: QuerySpecificity.NORMAL,
    QuerySpecificity.NORMAL: QuerySpecificity.BROAD,
    QuerySpecificity.BROAD: None,
}

# What each traveler interest looks like in a post's own words. Used to read
# preference fit off text that the extractor did not tag, never to build a
# query: interests do not steer search, they rank the For You pool.
SEARCH_TERM_MAP = {
    "hidden_gems": "hidden gems local spots",
    "local_food": "local food must eat",
    "street_food": "street food",
    "night_life": "nightlife bars",
    "nightlife": "nightlife bars",
    "coffee": "coffee cafes",
    "cafes": "coffee cafes",
    "onsen": "onsen hot springs",
    "hiking": "hiking trails",
    "nature": "nature scenery",
    "outdoors": "outdoor spots",
    "art": "art galleries",
    "history": "historic sites",
    "photography": "photo spots",
    "shopping": "shopping streets",
}


def interest_slug(interest: str) -> str:
    """Normalize a traveler interest to its lookup and dedup identity."""
    return re.sub(r"[\s\-]+", "_", interest.strip().casefold())


def interest_search_term(interest: str) -> str:
    """The words that indicate this interest in a post's text."""
    slug = interest_slug(interest)
    mapped = SEARCH_TERM_MAP.get(slug)
    if mapped is not None:
        return mapped
    return " ".join(interest.replace("_", " ").replace("-", " ").split())


class SearchIntent(BaseModel):
    """What to search for, separate from how the query is worded.

    The planner produces intents; build_discovery_query turns one into a
    provider query. Keeping the two apart is what makes the loop testable and
    stops query wording from becoming a decision surface.
    """

    model_config = ConfigDict(frozen=True)

    platform: SocialPlatform
    intent_type: SearchIntentType
    specificity: QuerySpecificity = QuerySpecificity.SPECIFIC

    @property
    def key(self) -> tuple[str, str]:
        """Semantic identity. Wording is deliberately absent, so two
        differently worded attempts at one question count as one question."""
        return (self.platform.value, self.intent_type.value)

    @property
    def lane(self) -> str:
        return "for_you" if self.intent_type in FOR_YOU_INTENTS else "trending"

    def broadened(self) -> SearchIntent | None:
        """The same question asked with fewer words, or None at the floor."""
        wider = _BROADER_THAN[self.specificity]
        if wider is None:
            return None
        return self.model_copy(update={"specificity": wider})


_ENGLISH_QUERIES: dict[tuple[SearchIntentType, QuerySpecificity], str] = {
    (SearchIntentType.PLACES, QuerySpecificity.SPECIFIC): (
        "{destination} must visit places things to do attractions sightseeing"
    ),
    (SearchIntentType.PLACES, QuerySpecificity.NORMAL): (
        "{destination} must visit places things to do"
    ),
    (SearchIntentType.PLACES, QuerySpecificity.BROAD): "{destination} things to do",
    (SearchIntentType.FOOD, QuerySpecificity.SPECIFIC): (
        "{destination} best local food restaurants cafes must eat"
    ),
    (SearchIntentType.FOOD, QuerySpecificity.NORMAL): (
        "{destination} best local food restaurants"
    ),
    (SearchIntentType.FOOD, QuerySpecificity.BROAD): "{destination} food",
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.SPECIFIC): (
        "{destination} hidden gems local spots underrated places"
    ),
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.NORMAL): (
        "{destination} local favorites less touristy places"
    ),
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.BROAD): "{destination} local spots",
}

# Measured against Brave for Sapporo under the note-path scope: these wordings
# returned 9, 20 and 20 notes, while longer piles of qualifiers returned zero.
# Chinese travel notes are tagged tersely, so an English-shaped query with five
# modifiers matches nothing at all.
_MANDARIN_QUERIES: dict[tuple[SearchIntentType, QuerySpecificity], str] = {
    (SearchIntentType.PLACES, QuerySpecificity.SPECIFIC): (
        "{destination} 必去景点 旅游攻略"
    ),
    (SearchIntentType.PLACES, QuerySpecificity.NORMAL): "{destination} 必去景点",
    (SearchIntentType.PLACES, QuerySpecificity.BROAD): "{destination} 景点",
    (SearchIntentType.FOOD, QuerySpecificity.SPECIFIC): (
        "{destination} 美食推荐 餐厅 咖啡店 探店"
    ),
    (SearchIntentType.FOOD, QuerySpecificity.NORMAL): "{destination} 美食推荐 餐厅",
    (SearchIntentType.FOOD, QuerySpecificity.BROAD): "{destination} 美食",
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.SPECIFIC): (
        "{destination} 小众 宝藏"
    ),
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.NORMAL): "{destination} 小众 打卡",
    (SearchIntentType.HIDDEN_GEMS, QuerySpecificity.BROAD): "{destination} 小众",
}


def build_discovery_query(
    intent: SearchIntent,
    *,
    destination: str,
    destination_localized: str | None = None,
) -> str:
    """Word one search intent as a provider query for its platform.

    Deterministic on purpose: the planner decides what is missing, this decides
    how to ask for it, and no model writes a query. RedNote is searched in the
    destination's Mandarin name, which is a hard requirement rather than a
    preference: the English name returns a different corpus entirely.
    """
    destination = destination.strip()
    if not destination:
        raise ValueError("destination cannot be empty")

    if intent.platform is SocialPlatform.REDNOTE:
        if destination_localized is None or not destination_localized.strip():
            raise ValueError("RedNote discovery requires a localized destination")
        name = destination_localized.strip()
        template = _MANDARIN_QUERIES[(intent.intent_type, intent.specificity)]
    else:
        name = destination
        template = _ENGLISH_QUERIES[(intent.intent_type, intent.specificity)]

    return " ".join(template.format(destination=name).split())


_HTML_TAG = re.compile(r"<[^>]+>")
# Snippets that are the site talking about itself rather than about the post.
# Instagram never publishes post text in its search-index description: over 60
# rows, every reel carried the @reel profile chrome (a follower count and an
# empty quoted caption) and every /p/ post carried the logged-out wall copy.
# Both are byte identical across results, so they say nothing about any single
# post, and the logged-out one is the more damaging of the two: it is long
# enough to look like content, which made a pasted photo-post link register as
# having readable text when it had none.
_EMPTY_CAPTION = re.compile(r':\s*""\s*$')
_PLATFORM_CHROME = re.compile(
    r"(?:log in to instagram|create an account or log in"
    r"|share what you're into with the people who get you)",
    re.IGNORECASE,
)


def clean_snippet(value: object) -> str | None:
    """Turn one Brave field into the text a reader would actually see.

    Brave returns HTML: entities are escaped, and the terms that matched the
    query are wrapped in <strong>. Those matched terms are very often the
    venue name, so left alone the extractor is asked to find places in
    "<strong>Hill of the Buddha</strong>" and the quote characters in a
    caption arrive as &quot;. Tags are stripped before entities are decoded,
    so a literal &lt;strong&gt; inside a caption survives as text.
    """
    if not isinstance(value, str):
        return None
    text = " ".join(html.unescape(_HTML_TAG.sub("", value)).split())
    return text or None


def post_snippet(value: object) -> str | None:
    """The description, or None when it is not about this post.

    Instagram publishes two such strings and no post text at all: the @reel
    profile chrome on every reel, and the logged-out wall copy on every /p/
    post. Measured over one gather, the reel chrome was one distinct string
    across thirty-four rows against twelve distinct across fifteen TikTok rows,
    and it spent about half the extraction payload. The post keeps its title,
    which for Instagram is the only signal there is.
    """
    text = clean_snippet(value)
    if text is None or _EMPTY_CAPTION.search(text) or _PLATFORM_CHROME.search(text):
        return None
    return text


_ENGLISH_ENGAGEMENT_PATTERNS = {
    "like": re.compile(r"(?<![\w.])(\d[\d,.]*\s*[KMB]?)\s+likes?\b", re.IGNORECASE),
    "comment": re.compile(
        r"(?<![\w.])(\d[\d,.]*\s*[KMB]?)\s+comments?\b", re.IGNORECASE
    ),
}
_CHINESE_ENGAGEMENT_PATTERNS = {
    "like": re.compile(r"(?:点赞\s*([\d,.]+\s*[万亿]?)|([\d,.]+\s*[万亿]?)\s*点赞)"),
    "comment": re.compile(r"(?:评论\s*([\d,.]+\s*[万亿]?)|([\d,.]+\s*[万亿]?)\s*评论)"),
}


def _compact_count(value: str) -> int:
    cleaned = value.replace(",", "").replace(" ", "").upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "万": 10_000, "亿": 100_000_000}
    multiplier = multipliers.get(cleaned[-1], 1)
    number = cleaned[:-1] if multiplier != 1 else cleaned
    return round(float(number) * multiplier)


def parse_public_engagement(text: str) -> tuple[int | None, int | None]:
    """Read explicitly labelled post likes/comments from a public snippet.

    Requiring a space before English labels deliberately ignores compact
    account statistics such as ``26.4MLikes`` that TikTok search snippets
    commonly show next to follower totals.
    """
    values: dict[str, int | None] = {"like": None, "comment": None}
    for signal in values:
        match = _ENGLISH_ENGAGEMENT_PATTERNS[signal].search(text)
        raw = match.group(1) if match is not None else None
        if raw is None:
            chinese = _CHINESE_ENGAGEMENT_PATTERNS[signal].search(text)
            if chinese is not None:
                raw = chinese.group(1) or chinese.group(2)
        if raw is not None:
            values[signal] = _compact_count(raw)
    return values["like"], values["comment"]


# Whether to scope by host or by path is per platform, and measured rather
# than assumed. "site:tiktok.com/@" matched nothing at all, so TikTok uses the
# host and normalize_social_url drops the /discover/ pages it also returns.
#
# RedNote is the opposite, and the host scope was silently costing the platform
# every one of its searches. Measured against Brave for Sapporo, the host scope
# returns 20 rows of which 12 to 15 are /mobile/question/ Q&A pages plus
# /mobile/tags/, /user/profile/ and the bare /explore/ feed, and 0 to 5 are
# actual notes; the note-path scope returns 6 to 20 rows that are all notes.
# Discovery therefore searches the note path. normalize_social_url still
# accepts /explore/<id> as well, so a traveler pasting either shape is
# unaffected: this narrows what discovery searches, not what the app accepts.
_SEARCH_SCOPE = {
    SocialPlatform.INSTAGRAM: "site:instagram.com/reel",
    SocialPlatform.TIKTOK: "site:tiktok.com",
    SocialPlatform.REDNOTE: "site:xiaohongshu.com/discovery/item",
}


async def _search_brave(
    value: BraveSocialSearchInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
    cache: SocialSearchCache | None = None,
) -> BraveSocialSearchOutput:
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is required for social discovery")

    scoped_query = f"{_SEARCH_SCOPE[value.platform]} {value.query.strip()}"
    # Cache identity is the external request, nothing about the loop that
    # produced it. A given query costs the provider once however many
    # iterations ago the planner decided to ask it.
    cache_digest = hashlib.sha256(
        f"{scoped_query}\n{value.max_results}".encode()
    ).hexdigest()
    cache_key = f"social:brave:v3:{cache_digest}"
    if cache is not None:
        cached = await cache.get(cache_key)
        if cached is not None:
            return BraveSocialSearchOutput.model_validate_json(cached)
    seen: set[str] = set()
    results: list[DiscoveredSocialURL] = []

    response = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        params={"q": scoped_query, "count": value.max_results},
    )
    response.raise_for_status()
    rows = response.json().get("web", {}).get("results", [])
    for rank, row in enumerate(rows, start=1):
        try:
            reference = normalize_social_url(row.get("url", ""))
        except (TypeError, ValueError):
            continue
        if (
            reference.platform is not value.platform
            or reference.kind is not SocialReferenceKind.POST
            or reference.canonical_url in seen
        ):
            continue
        seen.add(reference.canonical_url)
        title = clean_snippet(row.get("title"))
        description = post_snippet(row.get("description"))
        engagement_text = "\n".join(
            part for part in (title, description) if isinstance(part, str)
        )
        like_count, comment_count = parse_public_engagement(engagement_text)
        results.append(
            DiscoveredSocialURL(
                reference=reference,
                query=scoped_query,
                rank=rank,
                title=title,
                description=description,
                like_count=like_count,
                comment_count=comment_count,
            )
        )

    # Explicit post engagement is stronger evidence than search position.
    # When the index exposes no metric, preserve its deterministic rank.
    results.sort(
        key=lambda post: (
            -(post.like_count is not None or post.comment_count is not None),
            -((post.like_count or 0) + 4 * (post.comment_count or 0)),
            post.rank,
            post.reference.canonical_url,
        )
    )
    output = BraveSocialSearchOutput(results=results)
    if cache is not None:
        await cache.set(
            cache_key,
            output.model_dump_json(),
            ex=BRAVE_SEARCH_CACHE_TTL_SECONDS,
        )
    return output


def make_brave_social_search_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
    cache: SocialSearchCache | None = None,
) -> ToolDefinition:
    """Create the search tool with pooled production cache dependencies."""
    resolved_key = settings.brave_search_api_key if api_key is None else api_key

    async def search(value: BraveSocialSearchInput) -> BraveSocialSearchOutput:
        if client is not None:
            return await _search_brave(
                value,
                client=client,
                api_key=resolved_key,
                cache=cache,
            )
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _search_brave(
                value,
                client=owned_client,
                api_key=resolved_key,
                cache=cache if cache is not None else get_redis(),
            )

    return ToolDefinition(
        name="brave_social_search",
        input_model=BraveSocialSearchInput,
        output_model=BraveSocialSearchOutput,
        handler=search,
    )


class SocialLinkMetadataInput(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SocialLinkMetadata(BaseModel):
    """Public search-index metadata for one post URL."""

    platform: SocialPlatform
    canonical_url: str
    platform_id: str
    title: str | None = None
    description: str | None = None

    @property
    def indexed_text(self) -> str:
        return "\n".join(part for part in (self.title, self.description) if part)


async def _lookup_link_metadata(
    value: SocialLinkMetadataInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> SocialLinkMetadata:
    """Read one post's public title and description out of the search index.

    Instagram and RedNote have no open oEmbed endpoint, and CLAUDE.md section
    15 rules out logging in or scraping them. Asking a search API what it has
    already indexed for a URL the traveler chose to share stays inside
    platform-permitted public metadata access.
    """
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is required for link metadata")

    reference = normalize_social_url(value.url)
    response = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        params={"q": reference.canonical_url, "count": 5},
    )
    response.raise_for_status()
    for row in response.json().get("web", {}).get("results", []):
        try:
            found = normalize_social_url(row.get("url", ""))
        except (TypeError, ValueError):
            continue
        if found.canonical_url != reference.canonical_url:
            continue
        return SocialLinkMetadata(
            platform=reference.platform,
            canonical_url=reference.canonical_url,
            platform_id=reference.platform_id,
            title=clean_snippet(row.get("title")),
            description=post_snippet(row.get("description")),
        )

    return SocialLinkMetadata(
        platform=reference.platform,
        canonical_url=reference.canonical_url,
        platform_id=reference.platform_id,
    )


def make_social_link_metadata_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    resolved_key = settings.brave_search_api_key if api_key is None else api_key

    async def lookup(value: SocialLinkMetadataInput) -> SocialLinkMetadata:
        if client is not None:
            return await _lookup_link_metadata(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _lookup_link_metadata(
                value,
                client=owned_client,
                api_key=resolved_key,
            )

    return ToolDefinition(
        name="social_link_metadata",
        input_model=SocialLinkMetadataInput,
        output_model=SocialLinkMetadata,
        handler=lookup,
    )


async def _fetch_tiktok_oembed(
    value: TikTokOEmbedInput,
    *,
    client: httpx.AsyncClient,
) -> SocialPostPreview:
    reference = normalize_social_url(value.url)
    if (
        reference.platform is not SocialPlatform.TIKTOK
        or reference.kind is not SocialReferenceKind.POST
    ):
        raise ValueError("oEmbed requires a specific TikTok post URL")

    response = await client.get(
        "https://www.tiktok.com/oembed",
        params={"url": reference.canonical_url},
    )
    response.raise_for_status()
    data = response.json()
    return SocialPostPreview(
        platform=SocialPlatform.TIKTOK,
        canonical_url=reference.canonical_url,
        platform_id=reference.platform_id,
        caption=data["title"],
        author_name=data["author_name"],
        author_url=data["author_url"],
        thumbnail_url=data.get("thumbnail_url"),
    )


def make_tiktok_oembed_tool(
    *,
    client: httpx.AsyncClient | None = None,
) -> ToolDefinition:
    async def fetch(value: TikTokOEmbedInput) -> SocialPostPreview:
        if client is not None:
            return await _fetch_tiktok_oembed(value, client=client)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _fetch_tiktok_oembed(value, client=owned_client)

    return ToolDefinition(
        name="tiktok_oembed",
        input_model=TikTokOEmbedInput,
        output_model=SocialPostPreview,
        handler=fetch,
    )


class TikTokPostReadBatchInput(BaseModel):
    """One read of a city's discovered TikTok posts, as one harness step."""

    urls: list[str] = Field(min_length=1, max_length=SOCIAL_POST_READ_MAX_POSTS)
    # Posts whose cover frame should be downloaded as well. The caller keeps
    # this to the posts whose on-screen text is not already cached, so a
    # repeated gather downloads nothing.
    cover_urls: list[str] = Field(
        default_factory=list,
        max_length=SOCIAL_COVER_OCR_MAX_IMAGES,
    )
    max_cover_bytes: int = Field(default=SOCIAL_COVER_MAX_BYTES, ge=1)


class CoverImage(BaseModel):
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    data: str = Field(min_length=1)


class TikTokPostRead(BaseModel):
    """What the official embed API says about one post, or why it could not."""

    canonical_url: str
    platform_id: str
    caption: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    thumbnail_url: str | None = None
    cover_image: CoverImage | None = None
    cover_error: str | None = None
    error: str | None = None


class TikTokPostReadBatchOutput(BaseModel):
    posts: list[TikTokPostRead]

    @property
    def failed(self) -> list[TikTokPostRead]:
        return [post for post in self.posts if post.error is not None]


_COVER_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_POST_READ_CONCURRENCY = 4
_POST_READ_TIMEOUT_SECONDS = 10


def _sniff_image_type(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _https_url(value: object) -> str | None:
    text = _optional_text(value)
    return text if text is not None and text.startswith("https://") else None


async def _download_cover(
    url: str,
    *,
    client: httpx.AsyncClient,
    max_bytes: int,
) -> tuple[CoverImage | None, str | None]:
    """Fetch a cover frame under a hard byte cap, or say why it was skipped."""
    chunks: list[bytes] = []
    total = 0
    header_type = ""
    try:
        async with client.stream("GET", url, timeout=_POST_READ_TIMEOUT_SECONDS) as response:
            if response.status_code != 200:
                return None, f"cover_http_{response.status_code}"
            header_type = (
                response.headers.get("content-type", "").split(";")[0].strip().lower()
            )
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    return None, "cover_too_large"
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        return None, f"cover_{type(exc).__name__}"

    body = b"".join(chunks)
    if not body:
        return None, "cover_empty"
    media_type = _sniff_image_type(body[:12]) or (
        header_type if header_type in _COVER_MEDIA_TYPES else None
    )
    if media_type is None:
        return None, "cover_not_an_image"
    return (
        CoverImage(
            media_type=media_type,
            data=base64.standard_b64encode(body).decode("ascii"),
        ),
        None,
    )


def _post_read_cache_key(canonical_url: str) -> str:
    digest = hashlib.sha256(canonical_url.encode()).hexdigest()
    return f"social:tiktok:post:v1:{digest}"


async def _read_tiktok_metadata(
    reference: SocialReference,
    *,
    client: httpx.AsyncClient,
    cache: SocialSearchCache | None,
) -> TikTokPostRead:
    key = _post_read_cache_key(reference.canonical_url)
    if cache is not None:
        cached = await cache.get(key)
        if cached is not None:
            return TikTokPostRead.model_validate_json(cached)

    base = {
        "canonical_url": reference.canonical_url,
        "platform_id": reference.platform_id,
    }
    try:
        response = await client.get(
            "https://www.tiktok.com/oembed",
            params={"url": reference.canonical_url},
            timeout=_POST_READ_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return TikTokPostRead(**base, error=f"oembed_{type(exc).__name__}")
    if response.status_code != 200:
        return TikTokPostRead(**base, error=f"oembed_http_{response.status_code}")
    try:
        data = response.json()
    except ValueError:
        return TikTokPostRead(**base, error="oembed_invalid_json")
    if not isinstance(data, dict):
        return TikTokPostRead(**base, error="oembed_invalid_json")

    read = TikTokPostRead(
        **base,
        caption=_optional_text(data.get("title")),
        author_name=_optional_text(data.get("author_name")),
        author_url=_https_url(data.get("author_url")),
        thumbnail_url=_https_url(data.get("thumbnail_url")),
    )
    # Only a successful read is cached: a transient failure must not be
    # remembered for a day.
    if cache is not None:
        await cache.set(
            key,
            read.model_dump_json(),
            ex=SOCIAL_POST_READ_CACHE_TTL_SECONDS,
        )
    return read


async def _read_tiktok_posts(
    value: TikTokPostReadBatchInput,
    *,
    client: httpx.AsyncClient,
    cache: SocialSearchCache | None = None,
) -> TikTokPostReadBatchOutput:
    """Read every post in the batch, recording per-post failures in place.

    A removed video or an expired cover URL is normal, so one bad post never
    fails the batch. Results keep the input order, which is the search rank
    the caller relies on.
    """
    semaphore = asyncio.Semaphore(_POST_READ_CONCURRENCY)
    cover_wanted: set[str] = set()
    for url in value.cover_urls:
        try:
            cover_wanted.add(normalize_social_url(url).canonical_url)
        except ValueError:
            continue

    async def read_one(url: str) -> TikTokPostRead:
        try:
            reference = normalize_social_url(url)
        except ValueError:
            return TikTokPostRead(canonical_url=url, platform_id="", error="not_a_tiktok_post")
        if (
            reference.platform is not SocialPlatform.TIKTOK
            or reference.kind is not SocialReferenceKind.POST
        ):
            return TikTokPostRead(
                canonical_url=reference.canonical_url,
                platform_id=reference.platform_id,
                error="not_a_tiktok_post",
            )
        async with semaphore:
            read = await _read_tiktok_metadata(reference, client=client, cache=cache)
            if (
                read.error is None
                and read.thumbnail_url is not None
                and reference.canonical_url in cover_wanted
            ):
                cover, cover_error = await _download_cover(
                    read.thumbnail_url,
                    client=client,
                    max_bytes=value.max_cover_bytes,
                )
                read = read.model_copy(
                    update={"cover_image": cover, "cover_error": cover_error}
                )
        return read

    posts = await asyncio.gather(*(read_one(url) for url in value.urls))
    return TikTokPostReadBatchOutput(posts=list(posts))


def make_tiktok_post_read_tool(
    *,
    client: httpx.AsyncClient | None = None,
    cache: SocialSearchCache | None = None,
) -> ToolDefinition:
    """The batched read as one tool, so a city costs one harness step."""

    async def read(value: TikTokPostReadBatchInput) -> TikTokPostReadBatchOutput:
        if client is not None:
            return await _read_tiktok_posts(value, client=client, cache=cache)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _read_tiktok_posts(
                value,
                client=owned_client,
                cache=cache if cache is not None else get_redis(),
            )

    return ToolDefinition(
        name="tiktok_post_read_batch",
        input_model=TikTokPostReadBatchInput,
        output_model=TikTokPostReadBatchOutput,
        handler=read,
    )


__all__ = [
    "BRAVE_SEARCH_CACHE_TTL_SECONDS",
    "FOR_YOU_INTENTS",
    "OPENING_SEQUENCE",
    "SEARCH_TERM_MAP",
    "TRENDING_INTENTS",
    "BraveSocialSearchInput",
    "BraveSocialSearchOutput",
    "CoverImage",
    "DiscoveredSocialURL",
    "QuerySpecificity",
    "SearchIntent",
    "SearchIntentType",
    "SocialLinkMetadata",
    "SocialLinkMetadataInput",
    "SocialPlatform",
    "SocialPostPreview",
    "SocialReference",
    "SocialReferenceKind",
    "TikTokOEmbedInput",
    "TikTokPostRead",
    "TikTokPostReadBatchInput",
    "TikTokPostReadBatchOutput",
    "build_discovery_query",
    "clean_snippet",
    "interest_search_term",
    "interest_slug",
    "make_brave_social_search_tool",
    "make_social_link_metadata_tool",
    "make_tiktok_oembed_tool",
    "make_tiktok_post_read_tool",
    "normalize_social_url",
    "post_snippet",
]
