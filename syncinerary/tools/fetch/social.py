"""Platform-safe social URL normalization and deterministic search queries."""
from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
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
    platform: SocialPlatform
    destination: str = Field(min_length=1)
    destination_localized: str | None = None
    # Traveler interests, so discovery reflects what this group actually likes
    # rather than the same generic destination feed for everyone.
    interests: list[str] = Field(default_factory=list, max_length=8)
    # The provider's maximum. Cross-source counting only means something with
    # enough posts for a genuinely popular place to recur, and a larger page
    # costs the same one request as a small one.
    max_results_per_query: int = Field(default=20, ge=1, le=20)


class DiscoveredSocialURL(BaseModel):
    reference: SocialReference
    query: str
    rank: int = Field(ge=1)
    # Title and description as the search index already publishes them. This
    # is the only post text read: nothing logs in and nothing fetches the
    # post body from a platform that does not permit it.
    title: str | None = None
    description: str | None = None

    @property
    def indexed_text(self) -> str:
        return "\n".join(part for part in (self.title, self.description) if part)


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


def build_discovery_queries(
    platform: SocialPlatform,
    *,
    destination: str,
    destination_localized: str | None = None,
    interests: list[str] | None = None,
) -> list[str]:
    """Build one stable platform-native query for one selected city.

    One query per platform makes the provider budget explicit. At most two
    traveler interests refine that query without creating more API calls.
    """
    destination = destination.strip()
    if not destination:
        raise ValueError("destination cannot be empty")

    cleaned_interests: list[str] = []
    seen_interests: set[str] = set()
    for interest in interests or []:
        cleaned = interest.strip()
        if not cleaned or cleaned.casefold() in seen_interests:
            continue
        seen_interests.add(cleaned.casefold())
        cleaned_interests.append(cleaned)
        if len(cleaned_interests) == 2:
            break

    suffix = "" if not cleaned_interests else f" {' '.join(cleaned_interests)}"
    if platform is SocialPlatform.REDNOTE:
        if destination_localized is None or not destination_localized.strip():
            raise ValueError("RedNote discovery requires a localized destination")
        local = destination_localized.strip()
        return [f"{local}旅游美食攻略{suffix}"]

    return [f"{destination} travel food guide{suffix}"]


# Scoped to the host, not to a path prefix: "site:tiktok.com/@" matched nothing
# at all, so TikTok contributed zero posts. The host scope returns both videos
# and /discover/ pages, and normalize_social_url drops the latter.
_SEARCH_SCOPE = {
    SocialPlatform.INSTAGRAM: "site:instagram.com/reel",
    SocialPlatform.TIKTOK: "site:tiktok.com",
    SocialPlatform.REDNOTE: "site:xiaohongshu.com",
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

    cache_payload = value.model_dump_json()
    cache_digest = hashlib.sha256(cache_payload.encode()).hexdigest()
    cache_key = f"social:brave:v1:{cache_digest}"
    if cache is not None:
        cached = await cache.get(cache_key)
        if cached is not None:
            return BraveSocialSearchOutput.model_validate_json(cached)

    queries = build_discovery_queries(
        value.platform,
        destination=value.destination,
        destination_localized=value.destination_localized,
        interests=value.interests,
    )
    seen: set[str] = set()
    results: list[DiscoveredSocialURL] = []

    for query in queries:
        scoped_query = f"{_SEARCH_SCOPE[value.platform]} {query}"
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            params={"q": scoped_query, "count": value.max_results_per_query},
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
            results.append(
                DiscoveredSocialURL(
                    reference=reference,
                    query=scoped_query,
                    rank=rank,
                    title=row.get("title"),
                    description=row.get("description"),
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
            title=row.get("title"),
            description=row.get("description"),
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


__all__ = [
    "BRAVE_SEARCH_CACHE_TTL_SECONDS",
    "BraveSocialSearchInput",
    "BraveSocialSearchOutput",
    "DiscoveredSocialURL",
    "SocialLinkMetadata",
    "SocialLinkMetadataInput",
    "SocialPlatform",
    "SocialPostPreview",
    "SocialReference",
    "SocialReferenceKind",
    "TikTokOEmbedInput",
    "build_discovery_queries",
    "make_brave_social_search_tool",
    "make_social_link_metadata_tool",
    "make_tiktok_oembed_tool",
    "normalize_social_url",
]
