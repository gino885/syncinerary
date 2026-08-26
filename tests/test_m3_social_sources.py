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
)


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
    assert first == [
        "北海道旅游攻略",
        "北海道小众景点",
        "北海道必吃美食",
        "北海道自由行",
        "北海道避雷",
    ]
    assert all("Hokkaido" not in query for query in first)


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
        "site:instagram.com/reel Hokkaido travel reels",
        "site:instagram.com/reel Hokkaido hidden gems",
        "site:instagram.com/reel Hokkaido food guide",
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
        "site:xiaohongshu.com 北海道旅游攻略",
        "site:xiaohongshu.com 北海道小众景点",
        "site:xiaohongshu.com 北海道必吃美食",
        "site:xiaohongshu.com 北海道自由行",
        "site:xiaohongshu.com 北海道避雷",
    ]


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
