"""M3 social-source URL and discovery-query contracts."""
from __future__ import annotations

import httpx
import pytest

from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    BraveSocialSearchInput,
    SocialPlatform,
    SocialReferenceKind,
    TikTokOEmbedInput,
    build_discovery_queries,
    make_brave_social_search_tool,
    make_tiktok_oembed_tool,
    normalize_social_url,
    parse_public_engagement,
)


class FakeCache:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.last_key: str | None = None
        self.last_ttl: int | None = None

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.last_key = key
        self.last_ttl = ex


def test_instagram_reel_drops_share_tracking_from_canonical_url():
    reference = normalize_social_url(
        "https://www.instagram.com/reel/DcbEs5IpTCt/"
        "?igsi=MWFrdjFtbDB4eGg4cw=="
    )

    assert reference.platform is SocialPlatform.INSTAGRAM
    assert reference.kind is SocialReferenceKind.POST
    assert reference.platform_id == "DcbEs5IpTCt"
    assert reference.canonical_url == "https://www.instagram.com/reel/DcbEs5IpTCt/"


def test_rednote_short_share_link_is_an_attachable_unresolved_reference():
    reference = normalize_social_url("http://xhslink.com/o/8YJmF0qK4t")

    assert reference.platform is SocialPlatform.REDNOTE
    assert reference.kind is SocialReferenceKind.SHORT_LINK
    assert reference.platform_id == "8YJmF0qK4t"
    assert reference.canonical_url == "https://xhslink.com/o/8YJmF0qK4t"
    assert reference.is_attachable is True


def test_tiktok_discovery_page_is_search_input_not_user_attachment():
    reference = normalize_social_url(
        "https://www.tiktok.com/discover/"
        "the-next-station-is-shibuya-capcut-template"
    )

    assert reference.platform is SocialPlatform.TIKTOK
    assert reference.kind is SocialReferenceKind.SEARCH
    assert reference.is_attachable is False


def test_tiktok_video_url_is_attachable_and_canonical():
    reference = normalize_social_url(
        "https://www.tiktok.com/@traveler/video/7481234567890123456?is_from_webapp=1"
    )

    assert reference.platform is SocialPlatform.TIKTOK
    assert reference.kind is SocialReferenceKind.POST
    assert reference.platform_id == "7481234567890123456"
    assert reference.canonical_url == (
        "https://www.tiktok.com/@traveler/video/7481234567890123456"
    )
    assert reference.is_attachable is True


def test_rednote_discovery_queries_are_mandarin_first_and_deterministic():
    first = build_discovery_queries(
        SocialPlatform.REDNOTE,
        destination="Hokkaido",
        destination_localized="北海道",
    )
    second = build_discovery_queries(
        SocialPlatform.REDNOTE,
        destination="Hokkaido",
        destination_localized="北海道",
    )

    assert first == second
    assert first == ["北海道 必去景点 必吃美食 旅游攻略 探店"]
    assert all("Hokkaido" not in query for query in first)


def test_interests_refine_one_query_without_adding_provider_calls():
    queries = build_discovery_queries(
        SocialPlatform.INSTAGRAM,
        destination="Sapporo",
        interests=["ramen", "onsen", "coffee"],
    )

    assert queries == [
        "Sapporo must visit places must eat food travel guide ramen onsen"
    ]


def test_one_trip_uses_at_most_three_automatic_brave_searches():
    request_count = sum(
        len(
            build_discovery_queries(
                platform,
                destination="Sapporo",
                destination_localized="札幌" if platform is SocialPlatform.REDNOTE else None,
            )
        )
        for platform in SocialPlatform
    )

    assert request_count == 3


def test_rednote_discovery_requires_a_mandarin_destination_name():
    with pytest.raises(ValueError, match="localized destination"):
        build_discovery_queries(SocialPlatform.REDNOTE, destination="Hokkaido")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/reel/DcbEs5IpTCt/",
        "javascript:alert(1)",
        "https://www.tiktok.com/login",
    ],
)
def test_unknown_or_unsupported_social_urls_are_rejected(url):
    with pytest.raises(ValueError, match="supported social URL"):
        normalize_social_url(url)


async def test_brave_search_keeps_only_valid_platform_posts_and_deduplicates():
    seen_queries: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "test-key"
        query = request.url.params["q"]
        seen_queries.append(query)
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/"
                            "?igsi=tracking",
                            "title": "This transient snippet is not retained",
                        },
                        {
                            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
                            "title": "Duplicate",
                        },
                        {"url": "https://example.com/not-instagram"},
                    ]
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_brave_social_search_tool(client=client, api_key="test-key"),
            BraveSocialSearchInput(
                platform=SocialPlatform.INSTAGRAM,
                destination="Hokkaido",
                max_results_per_query=5,
            ),
        )

    assert seen_queries == [
        "site:instagram.com/reel Hokkaido must visit places must eat food travel guide",
    ]
    assert len(result.results) == 1
    assert result.results[0].reference.canonical_url == (
        "https://www.instagram.com/reel/DcbEs5IpTCt/"
    )
    assert result.results[0].query == seen_queries[0]
    assert "snippet" not in result.results[0].model_dump()


async def test_brave_rednote_search_uses_only_mandarin_queries():
    seen_queries: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["q"])
        return httpx.Response(200, json={"web": {"results": []}}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await run_tool(
            make_brave_social_search_tool(client=client, api_key="test-key"),
            BraveSocialSearchInput(
                platform=SocialPlatform.REDNOTE,
                destination="Hokkaido",
                destination_localized="北海道",
            ),
        )

    assert seen_queries == [
        "site:xiaohongshu.com 北海道 必去景点 必吃美食 旅游攻略 探店",
    ]


def test_public_engagement_requires_explicit_like_and_comment_labels():
    assert parse_public_engagement(
        "12.4K Likes, 380 Comments. Save this Sapporo food tour."
    ) == (12_400, 380)
    # This is an account-level TikTok total, not engagement on this post.
    assert parse_public_engagement("485.6KFollowers · 26.4MLikes") == (None, None)
    assert parse_public_engagement("点赞 2.1万 · 评论 846") == (21_000, 846)


async def test_brave_results_with_visible_post_engagement_rank_first():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://www.tiktok.com/@one/video/7000000001",
                            "title": "Sapporo places",
                            "description": "A useful city guide.",
                        },
                        {
                            "url": "https://www.tiktok.com/@two/video/7000000002",
                            "title": "Sapporo must eats",
                            "description": "12.4K Likes, 380 Comments.",
                        },
                    ]
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_brave_social_search_tool(client=client, api_key="test-key"),
            BraveSocialSearchInput(
                platform=SocialPlatform.TIKTOK,
                destination="Sapporo",
            ),
        )

    assert [post.reference.platform_id for post in result.results] == [
        "7000000002",
        "7000000001",
    ]
    assert result.results[0].like_count == 12_400
    assert result.results[0].comment_count == 380


async def test_brave_search_reuses_a_cached_city_platform_result():
    calls = 0
    cache = FakeCache()

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"web": {"results": []}}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = make_brave_social_search_tool(
            client=client,
            api_key="test-key",
            cache=cache,
        )
        value = BraveSocialSearchInput(
            platform=SocialPlatform.TIKTOK,
            destination="Sapporo",
        )
        await run_tool(tool, value)
        await run_tool(tool, value)

    assert calls == 1
    assert cache.last_ttl == 86_400
    assert cache.last_key is not None
    assert cache.last_key.startswith("social:brave:v2:")


async def test_brave_search_stops_clearly_when_the_key_is_missing():
    tool = make_brave_social_search_tool(api_key="")

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await run_tool(
            tool,
            BraveSocialSearchInput(
                platform=SocialPlatform.TIKTOK,
                destination="Hokkaido",
            ),
        )


async def test_tiktok_oembed_returns_only_official_public_preview_fields():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["url"] == (
            "https://www.tiktok.com/@traveler/video/7481234567890123456"
        )
        return httpx.Response(
            200,
            json={
                "title": "小樽运河的夜景 #北海道",
                "author_name": "Travel Notes",
                "author_url": "https://www.tiktok.com/@traveler",
                "thumbnail_url": "https://example.cdn.test/cover.jpeg",
                "html": "<blockquote>not retained</blockquote>",
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_tiktok_oembed_tool(client=client),
            TikTokOEmbedInput(
                url=(
                    "https://www.tiktok.com/@traveler/video/7481234567890123456"
                    "?is_from_webapp=1"
                )
            ),
        )

    assert result.platform is SocialPlatform.TIKTOK
    assert result.canonical_url == (
        "https://www.tiktok.com/@traveler/video/7481234567890123456"
    )
    assert result.caption == "小樽运河的夜景 #北海道"
    assert result.author_name == "Travel Notes"
    assert result.thumbnail_url == "https://example.cdn.test/cover.jpeg"
    assert "html" not in result.model_dump()


async def test_tiktok_oembed_rejects_discovery_pages_before_network_call():
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="specific TikTok post"):
            await run_tool(
                make_tiktok_oembed_tool(client=client),
                TikTokOEmbedInput(
                    url=(
                        "https://www.tiktok.com/discover/"
                        "the-next-station-is-shibuya-capcut-template"
                    )
                ),
            )

    assert calls == 0
