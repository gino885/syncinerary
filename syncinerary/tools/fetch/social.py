"""Platform-safe social URL normalization and deterministic search queries."""
from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.domain.models import SocialPlatform
from syncinerary.harness import ToolDefinition


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
    max_results_per_query: int = Field(default=5, ge=1, le=20)


class DiscoveredSocialURL(BaseModel):
    reference: SocialReference
    query: str
    rank: int = Field(ge=1)


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
) -> list[str]:
    """Build a small, stable platform-native query set for one destination."""
    destination = destination.strip()
    if not destination:
        raise ValueError("destination cannot be empty")

    if platform is SocialPlatform.REDNOTE:
        if destination_localized is None or not destination_localized.strip():
            raise ValueError("RedNote discovery requires a localized destination")
        local = destination_localized.strip()
        return [
            f"{local}旅游攻略",
            f"{local}小众景点",
            f"{local}必吃美食",
            f"{local}自由行",
            f"{local}避雷",
        ]

    if platform is SocialPlatform.INSTAGRAM:
        return [
            f"{destination} travel reels",
            f"{destination} hidden gems",
            f"{destination} food guide",
        ]

    return [
        f"{destination} travel",
        f"{destination} hidden gems",
        f"{destination} food guide",
    ]


_SEARCH_SCOPE = {
    SocialPlatform.INSTAGRAM: "site:instagram.com/reel",
    SocialPlatform.TIKTOK: "site:tiktok.com/@",
    SocialPlatform.REDNOTE: "site:xiaohongshu.com",
}


async def _search_brave(
    value: BraveSocialSearchInput,
    *,
    client: httpx.AsyncClient,
    api_key: str,
) -> BraveSocialSearchOutput:
    if not api_key:
        raise RuntimeError("BRAVE_SEARCH_API_KEY is required for social discovery")

    queries = build_discovery_queries(
        value.platform,
        destination=value.destination,
        destination_localized=value.destination_localized,
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
                )
            )

    return BraveSocialSearchOutput(results=results)


def make_brave_social_search_tool(
    *,
    client: httpx.AsyncClient | None = None,
    api_key: str | None = None,
) -> ToolDefinition:
    """Create the harness tool, allowing an injected client for boundary tests."""
    resolved_key = settings.brave_search_api_key if api_key is None else api_key

    async def search(value: BraveSocialSearchInput) -> BraveSocialSearchOutput:
        if client is not None:
            return await _search_brave(value, client=client, api_key=resolved_key)
        async with httpx.AsyncClient(timeout=20) as owned_client:
            return await _search_brave(
                value,
                client=owned_client,
                api_key=resolved_key,
            )

    return ToolDefinition(
        name="brave_social_search",
        input_model=BraveSocialSearchInput,
        output_model=BraveSocialSearchOutput,
        handler=search,
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
    "BraveSocialSearchInput",
    "BraveSocialSearchOutput",
    "DiscoveredSocialURL",
    "SocialPlatform",
    "SocialPostPreview",
    "SocialReference",
    "SocialReferenceKind",
    "TikTokOEmbedInput",
    "build_discovery_queries",
    "make_brave_social_search_tool",
    "make_tiktok_oembed_tool",
    "normalize_social_url",
]
