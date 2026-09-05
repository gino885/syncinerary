"""M3 social-source URL and discovery-query contracts."""
from __future__ import annotations

import httpx
import pytest

from syncinerary.config.gather import MAX_SEARCHES_PER_CITY
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    OPENING_SEQUENCE,
    BraveSocialSearchInput,
    QuerySpecificity,
    SearchIntent,
    SearchIntentType,
    SocialPlatform,
    SocialReferenceKind,
    TikTokOEmbedInput,
    build_discovery_query,
    clean_snippet,
    make_brave_social_search_tool,
    make_tiktok_oembed_tool,
    normalize_social_url,
    parse_public_engagement,
    post_snippet,
)


def _intent(platform, intent_type=SearchIntentType.PLACES, **kwargs) -> SearchIntent:
    return SearchIntent(platform=platform, intent_type=intent_type, **kwargs)


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
    intent = _intent(SocialPlatform.REDNOTE)
    first = build_discovery_query(
        intent, destination="Hokkaido", destination_localized="北海道"
    )
    second = build_discovery_query(
        intent, destination="Hokkaido", destination_localized="北海道"
    )

    assert first == second
    assert first == "北海道 必去景点 旅游攻略"


def test_every_rednote_intent_and_wording_stays_in_mandarin():
    """The language guarantee is per query, not per intent.

    Adaptive search can reach any intent at any specificity, so the check has
    to cover the whole grid rather than the three queries the old plan built.
    """
    queries = [
        build_discovery_query(
            _intent(SocialPlatform.REDNOTE, intent_type, specificity=specificity),
            destination="Hokkaido",
            destination_localized="北海道",
        )
        for intent_type in SearchIntentType
        for specificity in QuerySpecificity
    ]

    assert all(query.startswith("北海道 ") for query in queries)
    assert not any("Hokkaido" in query for query in queries)
    assert not any(query.isascii() for query in queries)


def test_the_three_search_intents_ask_genuinely_different_questions():
    """PLACES and FOOD stock Trending; HIDDEN_GEMS stocks For You.

    If two of them returned the same query the lanes would share a source,
    which is the thing this design exists to avoid.
    """
    queries = {
        intent_type: build_discovery_query(
            _intent(SocialPlatform.TIKTOK, intent_type), destination="Sapporo"
        )
        for intent_type in SearchIntentType
    }

    assert len(set(queries.values())) == 3
    assert "attractions" in queries[SearchIntentType.PLACES]
    assert "restaurants" in queries[SearchIntentType.FOOD]
    assert "hidden gems" in queries[SearchIntentType.HIDDEN_GEMS]
    assert all("Sapporo" in query for query in queries.values())


def test_hidden_gems_is_a_search_of_its_own_not_a_ranking_tweak():
    """It has to be asked for explicitly, because a place few people posted
    about cannot be reached by reranking a popularity-driven pool."""
    gems = _intent(SocialPlatform.INSTAGRAM, SearchIntentType.HIDDEN_GEMS)
    places = _intent(SocialPlatform.INSTAGRAM, SearchIntentType.PLACES)

    assert gems.lane == "for_you"
    assert places.lane == "trending"
    assert gems.key != places.key
    assert SearchIntentType.HIDDEN_GEMS in OPENING_SEQUENCE


def test_the_fallback_ladder_removes_words_rather_than_adding_them():
    """Over-specification is the common search failure, so broadening a failed
    intent has to make the query shorter."""
    intent = _intent(SocialPlatform.INSTAGRAM)
    ladder = []
    while intent is not None:
        ladder.append(build_discovery_query(intent, destination="Sapporo"))
        intent = intent.broadened()

    assert len(ladder) == 3
    lengths = [len(query.split()) for query in ladder]
    assert lengths == sorted(lengths, reverse=True)
    assert ladder[-1] == "Sapporo things to do"


def test_a_semantic_intent_ignores_wording_and_specificity():
    """Two wordings of one question must not count as two questions."""
    specific = _intent(SocialPlatform.TIKTOK, SearchIntentType.HIDDEN_GEMS)
    broader = specific.broadened()

    assert specific.key == broader.key
    assert specific.key == ("tiktok", "hidden_gems")
    assert build_discovery_query(
        specific, destination="Sapporo"
    ) != build_discovery_query(broader, destination="Sapporo")


def test_one_city_never_exceeds_the_brave_search_ceiling():
    """A cost bound, not a plan.

    Eight is the absolute per-city Brave budget, below the nine the old fixed
    plan spent every time. Discovery is adaptive and should normally stop well
    before reaching it; this protects provider cost and does not prescribe how
    many searches must run. The loop that has to respect it is covered in
    test_m7f_adaptive_social_search.py.
    """
    assert MAX_SEARCHES_PER_CITY == 8
    assert len(OPENING_SEQUENCE) < MAX_SEARCHES_PER_CITY


def test_rednote_discovery_requires_a_mandarin_destination_name():
    with pytest.raises(ValueError, match="localized destination"):
        build_discovery_query(_intent(SocialPlatform.REDNOTE), destination="Hokkaido")


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
                query="Hokkaido must visit places must eat food travel guide",
                max_results=5,
            ),
        )

    # One planned search is one provider request: the tool no longer composes
    # queries of its own, so the caller decides what and how often to ask.
    assert seen_queries == [
        "site:instagram.com/reel Hokkaido must visit places must eat food travel guide"
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
                query=build_discovery_query(
                    _intent(SocialPlatform.REDNOTE),
                    destination="Hokkaido",
                    destination_localized="北海道",
                ),
            ),
        )

    # Scoped to the note path, not the host: the host scope returns mostly
    # /mobile/question/ and /mobile/tags/ pages, which are not posts, so
    # RedNote contributed nothing at all through it.
    assert seen_queries == [
        "site:xiaohongshu.com/discovery/item 北海道 必去景点 旅游攻略"
    ]
    # Mandarin only: an English angle here would return the wrong internet.
    assert not any("must visit" in q for q in seen_queries)


def test_brave_highlight_markup_is_stripped_before_extraction():
    """Brave wraps the terms that matched the query in <strong>, and those are
    very often the venue name, so the tags have to go before the extractor
    reads the text."""
    assert clean_snippet(
        "Jangan sampe skip ke <strong>Hill of the Buddha</strong>!"
    ) == "Jangan sampe skip ke Hill of the Buddha!"


def test_html_entities_are_decoded_into_the_characters_they_stand_for():
    assert clean_snippet("Caf&eacute; &amp; bar &#39;Kissa&#39;") == "Café & bar 'Kissa'"
    assert clean_snippet(None) is None
    assert clean_snippet("   ") is None


def test_an_instagram_reels_profile_chrome_is_not_treated_as_post_text():
    """Instagram serves the same @reel profile description for every reel.

    Measured over one gather it was a single distinct string across every
    Instagram row, so it carries no information about any of them and cost
    about half the extraction payload. The post keeps its title.
    """
    chrome = "9M seguidores, 30 siguiendo, 5 publicaciones - @reel en Instagram: &quot;&quot;"

    assert post_snippet(chrome) is None


def test_instagrams_logged_out_wall_copy_is_not_treated_as_post_text():
    """The second of Instagram's two chrome strings, and the more damaging.

    Every /p/ photo post carries it, and it is long enough to look like
    content, so a pasted photo-post link registered as having readable text
    when it had none and was never sent back for a place name.
    """
    wall = (
        "Create an account or log in to Instagram - Share what you're into "
        "with the people who get you."
    )

    assert post_snippet(wall) is None


def test_a_real_caption_survives_the_snippet_cleanup():
    """The empty-caption rule must not swallow a snippet that has one."""
    caption = "3413 Likes, 36 Comments. TikTok video from Syafiq: &quot;best ramen&quot;"

    assert post_snippet(caption) == (
        '3413 Likes, 36 Comments. TikTok video from Syafiq: "best ramen"'
    )


async def test_search_results_reach_the_extractor_without_markup_or_chrome():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
                            "title": "Cinderella Tan | Must Visit Caf&eacute;s in "
                            "<strong>Sapporo</strong>",
                            "description": "9M seguidores, 30 siguiendo, 5 "
                            "publicaciones - @reel en Instagram: &quot;&quot;",
                        }
                    ]
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_brave_social_search_tool(client=client, api_key="test-key"),
            BraveSocialSearchInput(
                platform=SocialPlatform.INSTAGRAM, query="Sapporo cafes"
            ),
        )

    post = result.results[0]
    assert post.title == "Cinderella Tan | Must Visit Cafés in Sapporo"
    assert post.description is None
    assert post.evidence_text == (
        "Title: Cinderella Tan | Must Visit Cafés in Sapporo"
    )


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
                query="Sapporo must eat food",
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
            query="Sapporo must visit places",
        )
        await run_tool(tool, value)
        after_first = calls
        await run_tool(tool, value)

    # Cache identity is the external request, so an adaptive loop reaching the
    # same query on a later iteration still pays for it once.
    assert after_first == 1
    assert calls == after_first
    assert cache.last_ttl == 86_400
    assert cache.last_key is not None
    assert cache.last_key.startswith("social:brave:v3:")


async def test_brave_search_stops_clearly_when_the_key_is_missing():
    tool = make_brave_social_search_tool(api_key="")

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await run_tool(
            tool,
            BraveSocialSearchInput(
                platform=SocialPlatform.TIKTOK,
                query="Hokkaido travel",
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
