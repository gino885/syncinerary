"""M5a: reading what TikTok permits about a discovered post, within budget.

The buzz path used to read only the search-index snippet of a post. These
cover the bounded read that now sits behind it: one batched tool call per
city for captions and cover frames, one vision call for the text on those
frames, caches that make a repeat gather free, and the per-post evidence that
ends up on the card. Every provider is a local stub; nothing here spends a
request.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather import social_read
from syncinerary.agents.gather.social import (
    MinedPlace,
    SocialPlaceMention,
    SocialPlaceMentions,
    merge_into_pool,
    merge_mentions,
    to_candidate,
)
from syncinerary.agents.gather.social_read import (
    cover_text_cache_key,
    extract_cover_texts,
    read_cover_text_for_url,
    read_tiktok_posts,
)
from syncinerary.config.gather import (
    SOCIAL_COVER_OCR_MAX_IMAGES,
    SOCIAL_COVER_TEXT_CACHE_TTL_SECONDS,
    SOCIAL_POST_READ_CACHE_TTL_SECONDS,
)
from syncinerary.domain.models import CandidatePlace, CandidateType, SocialPlatform, Source, Trip
from syncinerary.harness import ToolDefinition, run_tool
from syncinerary.tools.fetch.social import (
    CoverImage,
    DiscoveredSocialURL,
    TikTokPostRead,
    TikTokPostReadBatchInput,
    TikTokPostReadBatchOutput,
    make_tiktok_post_read_tool,
    normalize_social_url,
)
from syncinerary.tools.places import PlaceMatch

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _video(index: int) -> str:
    return f"https://www.tiktok.com/@traveler/video/{7480000000000000000 + index}"


def _post(url: str, *, rank: int = 1, **fields) -> DiscoveredSocialURL:
    return DiscoveredSocialURL(
        reference=normalize_social_url(url),
        query="site:tiktok.com Sapporo travel food guide",
        rank=rank,
        **fields,
    )


class FakeCache:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.sets: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.sets.append((key, value, ex))


class StubMessages:
    def __init__(self, text: str, *, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = (
            []
            if self.stop_reason == "refusal"
            else [SimpleNamespace(type="text", text=self.text)]
        )
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


def _oembed_transport(
    *,
    covers: dict[str, bytes] | None = None,
    missing: set[str] = frozenset(),
    seen: list[str] | None = None,
) -> httpx.MockTransport:
    covers = covers or {}

    def respond(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if request.url.path == "/oembed":
            post_url = request.url.params["url"]
            if post_url in missing:
                return httpx.Response(404, json={"message": "gone"}, request=request)
            video_id = post_url.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "title": f"Caption for {video_id} #sapporo",
                    "author_name": "Travel Notes",
                    "author_url": "https://www.tiktok.com/@traveler",
                    "thumbnail_url": f"https://cdn.example.test/{video_id}.jpeg",
                    "html": "<blockquote>not retained</blockquote>",
                },
                request=request,
            )
        body = covers.get(url)
        if body is None:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "image/jpeg"},
            request=request,
        )

    return httpx.MockTransport(respond)


# ----- the batched read tool -----


async def test_batch_read_keeps_order_and_downloads_only_requested_covers():
    seen: list[str] = []
    covers = {f"https://cdn.example.test/{_video(i).rsplit('/', 1)[-1]}.jpeg": JPEG for i in (1, 2)}
    async with httpx.AsyncClient(transport=_oembed_transport(covers=covers, seen=seen)) as client:
        result = await run_tool(
            make_tiktok_post_read_tool(client=client),
            TikTokPostReadBatchInput(
                urls=[_video(2), _video(1)],
                cover_urls=[_video(1) + "?is_from_webapp=1"],
            ),
        )

    assert [post.canonical_url for post in result.posts] == [_video(2), _video(1)]
    second, first = result.posts
    assert first.caption.startswith("Caption for")
    assert first.author_name == "Travel Notes"
    assert first.cover_image is not None
    assert first.cover_image.media_type == "image/jpeg"
    assert base64.standard_b64decode(first.cover_image.data) == JPEG
    assert second.cover_image is None and second.cover_error is None
    assert sum(url.endswith(".jpeg") for url in seen) == 1
    assert result.failed == []


async def test_a_removed_video_is_recorded_not_fatal():
    async with httpx.AsyncClient(transport=_oembed_transport(missing={_video(1)})) as client:
        result = await run_tool(
            make_tiktok_post_read_tool(client=client),
            TikTokPostReadBatchInput(urls=[_video(1), _video(2)]),
        )

    assert [post.error for post in result.posts] == ["oembed_http_404", None]
    assert [post.canonical_url for post in result.failed] == [_video(1)]


async def test_a_cover_over_the_byte_cap_is_skipped_with_a_reason():
    video_id = _video(1).rsplit("/", 1)[-1]
    covers = {f"https://cdn.example.test/{video_id}.jpeg": JPEG * 100}
    async with httpx.AsyncClient(transport=_oembed_transport(covers=covers)) as client:
        result = await run_tool(
            make_tiktok_post_read_tool(client=client),
            TikTokPostReadBatchInput(
                urls=[_video(1)],
                cover_urls=[_video(1)],
                max_cover_bytes=len(JPEG),
            ),
        )

    post = result.posts[0]
    assert post.error is None
    assert post.cover_image is None
    assert post.cover_error == "cover_too_large"


async def test_a_cover_that_is_not_an_image_is_skipped():
    video_id = _video(1).rsplit("/", 1)[-1]
    covers = {f"https://cdn.example.test/{video_id}.jpeg": b"<html>login wall</html>"}

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oembed":
            return _oembed_transport(covers=covers).handler(request)
        return httpx.Response(
            200,
            content=covers[str(request.url)],
            headers={"content-type": "text/html"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_tiktok_post_read_tool(client=client),
            TikTokPostReadBatchInput(urls=[_video(1)], cover_urls=[_video(1)]),
        )

    assert result.posts[0].cover_image is None
    assert result.posts[0].cover_error == "cover_not_an_image"


async def test_metadata_is_cached_per_post_and_a_cache_hit_makes_no_request():
    seen: list[str] = []
    cache = FakeCache()
    async with httpx.AsyncClient(transport=_oembed_transport(seen=seen)) as client:
        tool = make_tiktok_post_read_tool(client=client, cache=cache)
        await run_tool(tool, TikTokPostReadBatchInput(urls=[_video(1)]))
        again = await run_tool(tool, TikTokPostReadBatchInput(urls=[_video(1)]))

    assert len(seen) == 1
    assert again.posts[0].caption.startswith("Caption for")
    key, _, ttl = cache.sets[0]
    assert key.startswith("social:tiktok:post:v1:")
    assert ttl == SOCIAL_POST_READ_CACHE_TTL_SECONDS


async def test_a_failed_read_is_not_cached():
    cache = FakeCache()
    async with httpx.AsyncClient(transport=_oembed_transport(missing={_video(1)})) as client:
        await run_tool(
            make_tiktok_post_read_tool(client=client, cache=cache),
            TikTokPostReadBatchInput(urls=[_video(1)]),
        )

    assert cache.sets == []


async def test_a_non_tiktok_url_in_the_batch_is_an_error_entry_without_a_request():
    seen: list[str] = []
    async with httpx.AsyncClient(transport=_oembed_transport(seen=seen)) as client:
        result = await run_tool(
            make_tiktok_post_read_tool(client=client),
            TikTokPostReadBatchInput(
                urls=[
                    "https://www.instagram.com/reel/DcbEs5IpTCt/",
                    "https://www.tiktok.com/discover/sapporo",
                ]
            ),
        )

    assert [post.error for post in result.posts] == ["not_a_tiktok_post"] * 2
    assert seen == []


# ----- cover-frame text -----


def _cover(index: int) -> tuple[int, CoverImage]:
    return index, CoverImage(media_type="image/jpeg", data=base64.standard_b64encode(JPEG).decode())


async def test_cover_text_is_one_multimodal_call_with_numbered_images():
    stub = StubMessages(
        '{"covers":[{"image_index":1,"on_screen_text":"  Top 5   ramen in Sapporo "},'
        '{"image_index":2,"on_screen_text":""},'
        '{"image_index":9,"on_screen_text":"not one of ours"}]}'
    )

    texts = await extract_cover_texts([_cover(1), _cover(2)], destination="Sapporo", client=stub)

    assert texts == {1: "Top 5 ramen in Sapporo", 2: ""}
    assert len(stub.calls) == 1
    sent = stub.calls[0]
    content = sent["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "image", "text", "image", "text"]
    assert content[0]["text"] == "Image 1:"
    assert content[1]["source"]["media_type"] == "image/jpeg"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "never guess a location" in sent["system"]


async def test_cover_text_refuses_more_images_than_the_cap():
    stub = StubMessages('{"covers":[]}')
    images = [_cover(index) for index in range(1, SOCIAL_COVER_OCR_MAX_IMAGES + 2)]

    with pytest.raises(ValueError, match="cover images per call"):
        await extract_cover_texts(images, destination="Sapporo", client=stub)
    assert stub.calls == []


async def test_a_refused_cover_read_is_an_empty_result_not_a_crash():
    stub = StubMessages("", stop_reason="refusal")

    assert await extract_cover_texts([_cover(1)], destination="Sapporo", client=stub) == {}


async def test_invalid_cover_text_is_not_hidden_as_no_text():
    stub = StubMessages('{"covers":"nope"}')

    with pytest.raises(ValueError, match="invalid data"):
        await extract_cover_texts([_cover(1)], destination="Sapporo", client=stub)


# ----- the orchestration around both -----


def _fake_read_tool(reads: dict[str, TikTokPostRead], calls: list[TikTokPostReadBatchInput]):
    async def handler(value: TikTokPostReadBatchInput) -> TikTokPostReadBatchOutput:
        calls.append(value)
        return TikTokPostReadBatchOutput(posts=[reads[url] for url in value.urls])

    return ToolDefinition(
        name="tiktok_post_read_batch",
        input_model=TikTokPostReadBatchInput,
        output_model=TikTokPostReadBatchOutput,
        handler=handler,
    )


def _read(url: str, *, cover: bool = False, error: str | None = None) -> TikTokPostRead:
    reference = normalize_social_url(url)
    if error is not None:
        return TikTokPostRead(
            canonical_url=reference.canonical_url,
            platform_id=reference.platform_id,
            error=error,
        )
    return TikTokPostRead(
        canonical_url=reference.canonical_url,
        platform_id=reference.platform_id,
        caption=f"Caption {reference.platform_id}",
        author_name="Travel Notes",
        thumbnail_url=f"https://cdn.example.test/{reference.platform_id}.jpeg",
        cover_image=_cover(1)[1] if cover else None,
    )


async def test_read_enriches_posts_and_skips_covers_already_transcribed():
    calls: list[TikTokPostReadBatchInput] = []
    cache = FakeCache()
    cache.values[cover_text_cache_key(_video(2))] = "Otaru canal at night"
    reads = {
        _video(1): _read(_video(1), cover=True),
        _video(2): _read(_video(2)),
        _video(3): _read(_video(3), error="oembed_http_404"),
    }
    stub = StubMessages('{"covers":[{"image_index":1,"on_screen_text":"Best soup curry"}]}')
    posts = [
        _post(_video(1), rank=1, title="snippet one"),
        _post(_video(2), rank=2, title="snippet two"),
        _post(_video(3), rank=3, title="snippet three"),
    ]

    enriched = await read_tiktok_posts(
        posts,
        destination="Sapporo",
        tool=_fake_read_tool(reads, calls),
        cache=cache,
        client=stub,
        ocr_enabled=True,
    )

    # One batched read for the city, covers only for the post not yet cached.
    assert len(calls) == 1
    assert calls[0].urls == [_video(1), _video(2), _video(3)]
    assert calls[0].cover_urls == [_video(1), _video(3)]
    # One vision call, for the one cover that came back.
    assert len(stub.calls) == 1

    first, second, third = enriched
    assert first.caption == f"Caption {normalize_social_url(_video(1)).platform_id}"
    assert first.author_name == "Travel Notes"
    assert first.cover_text == "Best soup curry"
    assert second.cover_text == "Otaru canal at night"
    # A post the embed API could not serve keeps exactly the snippet it had.
    assert third.caption is None and third.cover_text is None
    assert third.title == "snippet three"
    assert [post.rank for post in enriched] == [1, 2, 3]
    assert cache.sets == [
        (cover_text_cache_key(_video(1)), "Best soup curry", SOCIAL_COVER_TEXT_CACHE_TTL_SECONDS)
    ]


async def test_ocr_off_means_no_downloads_no_vision_and_no_cache_reads():
    calls: list[TikTokPostReadBatchInput] = []
    cache = FakeCache()
    stub = StubMessages('{"covers":[]}')
    reads = {_video(1): _read(_video(1), cover=True)}

    enriched = await read_tiktok_posts(
        [_post(_video(1))],
        destination="Sapporo",
        tool=_fake_read_tool(reads, calls),
        cache=cache,
        client=stub,
        ocr_enabled=False,
    )

    assert calls[0].cover_urls == []
    assert stub.calls == []
    assert cache.sets == []
    assert enriched[0].caption is not None


async def test_empty_input_costs_nothing():
    calls: list[TikTokPostReadBatchInput] = []

    assert await read_tiktok_posts([], destination="Sapporo", tool=_fake_read_tool({}, calls)) == []
    assert calls == []


async def test_a_pasted_link_reads_its_cover_through_the_same_path():
    calls: list[TikTokPostReadBatchInput] = []
    cache = FakeCache()
    stub = StubMessages('{"covers":[{"image_index":1,"on_screen_text":"Otaru Canal night walk"}]}')
    reads = {_video(1): _read(_video(1), cover=True)}

    text = await read_cover_text_for_url(
        _video(1) + "?is_from_webapp=1",
        tool=_fake_read_tool(reads, calls),
        cache=cache,
        client=stub,
    )

    assert text == "Otaru Canal night walk"
    assert calls[0].urls == [_video(1)]


# ----- evidence and per-post details on the card -----


def test_evidence_text_labels_parts_and_drops_a_snippet_equal_to_the_caption():
    post = _post(
        _video(1),
        title="Sapporo ramen",
        description="Best   ramen in Sapporo #food",
        caption="best ramen in sapporo #food",
        cover_text="Top 5 ramen",
    )

    assert post.evidence_text == (
        "Title: Sapporo ramen\nSnippet: Best ramen in Sapporo #food\nOn screen: Top 5 ramen"
    )
    assert post.indexed_text == "Sapporo ramen\nBest   ramen in Sapporo #food"


def test_mentions_carry_each_posts_words_and_the_length_cap_is_enforced():
    posts = [
        _post(_video(1), rank=1, author_name="Travel Notes"),
        _post(_video(2), rank=2),
    ]
    long_highlight = "The broth simmers for two days and the counter seats eight " * 4
    mentions = SocialPlaceMentions(
        mentions=[
            SocialPlaceMention(name="Ramen Shingen", post_index=1, highlight=long_highlight),
            SocialPlaceMention(name="Ramen Shingen", post_index=2, highlight="   "),
        ]
    )

    mined = merge_mentions({}, mentions, posts, SocialPlatform.TIKTOK)

    place = mined["ramen shingen"]
    assert [post.url for post in place.posts] == place.post_urls == [_video(1), _video(2)]
    assert place.posts[0].author_name == "Travel Notes"
    assert place.posts[0].highlight.endswith("...")
    assert len(place.posts[0].highlight) <= 120
    assert place.posts[1].highlight is None
    assert place.highlight == place.posts[0].highlight


def test_the_card_keeps_every_post_and_the_best_ranked_quote():
    trip = Trip(destination="Hokkaido", start_date="2026-09-27", end_date="2026-09-28", days=2)
    mined = MinedPlace(
        name="Ramen Shingen",
        platforms=["tiktok", "instagram"],
        post_urls=[_video(1), "https://www.instagram.com/reel/DcbEs5IpTCt/"],
        queries=["q"],
    )
    mined.posts = [
        social_module.MinedPost(platform="tiktok", url=_video(1), rank=1, highlight=None),
        social_module.MinedPost(
            platform="instagram",
            url="https://www.instagram.com/reel/DcbEs5IpTCt/",
            rank=3,
            highlight="Miso broth worth the queue.",
        ),
    ]
    place = PlaceMatch(
        place_id="ChIJ-shingen",
        display_name="Ramen Shingen",
        lat=43.05,
        lng=141.35,
        primary_type="ramen_restaurant",
        types=["restaurant"],
    )

    candidate = to_candidate(place, mined, trip)

    assert candidate.type is CandidateType.FOOD
    assert candidate.enrichment["social_highlight"] == "Miso broth worth the queue."
    assert [post["url"] for post in candidate.enrichment["social_posts"]] == mined.post_urls

    pool = {
        "ChIJ-shingen": CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.FOOD,
            name_canonical="Ramen Shingen",
            lat=43.05,
            lng=141.35,
            sources=[Source(type="discovery", subtype="google_places")],
            enrichment={"google_place_id": "ChIJ-shingen"},
        )
    }
    merge_into_pool(pool, [candidate])
    merged = pool["ChIJ-shingen"]
    assert merged.enrichment["social_highlight"] == "Miso broth worth the queue."
    assert len(merged.enrichment["social_posts"]) == 2


async def test_platform_search_reads_tiktok_posts_and_leaves_the_others_alone(monkeypatch):
    read_calls: list[tuple[list[DiscoveredSocialURL], str]] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        if arguments.platform is SocialPlatform.TIKTOK:
            return SimpleNamespace(results=[_post(_video(1))])
        return SimpleNamespace(
            results=[
                DiscoveredSocialURL(
                    reference=normalize_social_url("https://www.instagram.com/reel/DcbEs5IpTCt/"),
                    query="q",
                    rank=1,
                )
            ]
        )

    async def fake_read(posts, *, destination, **_kwargs):
        read_calls.append((posts, destination))
        return [post.model_copy(update={"caption": "read"}) for post in posts]

    monkeypatch.setattr(social_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(social_module, "read_tiktok_posts", fake_read)
    monkeypatch.setattr(social_read, "read_tiktok_posts", fake_read)

    tiktok = await social_module._search_platform(
        SocialPlatform.TIKTOK, destination="Sapporo", interests=[]
    )
    instagram = await social_module._search_platform(
        SocialPlatform.INSTAGRAM, destination="Sapporo", interests=[]
    )

    assert [destination for _, destination in read_calls] == ["Sapporo"]
    assert tiktok[0].caption == "read"
    assert instagram[0].caption is None


# ----- a pasted TikTok link whose caption names nothing -----


async def test_a_placeless_tiktok_caption_falls_back_to_the_cover_frame(
    client,
    session,
    monkeypatch,
):
    from syncinerary.agents.gather import personal as personal_module
    from syncinerary.agents.gather.attachments import ExtractedPlaceMention
    from syncinerary.agents.gather.personal import TextPlaceExtraction
    from syncinerary.store.repositories import CandidatePlaceRepository
    from syncinerary.tools.fetch.social import SocialPostPreview
    from syncinerary.tools.places import PlaceSearchOutput

    extraction_inputs: list[str] = []

    async def fake_run_tool(tool, arguments, **_kwargs):
        if tool.name == "tiktok_oembed":
            return SocialPostPreview(
                platform=SocialPlatform.TIKTOK,
                canonical_url=arguments.url,
                platform_id="1234567890",
                caption="wait for it 😍 #hokkaido",
                author_name="Traveler",
                author_url="https://www.tiktok.com/@traveler",
                thumbnail_url="https://p16-sign.tiktokcdn-us.com/preview.jpeg",
            )
        assert tool.name == "google_places_text_search"
        assert arguments.query == "Otaru Canal"
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="ChIJ-otaru",
                    display_name="Otaru Canal",
                    lat=43.1987,
                    lng=140.9947,
                    primary_type="tourist_attraction",
                )
            ]
        )

    async def fake_extract(text, *, platform, client=None):
        extraction_inputs.append(text)
        if "On screen:" not in text:
            return TextPlaceExtraction(language="en")
        return TextPlaceExtraction(
            language="en",
            short_description="A canal walk that looks best after dark.",
            place_mentions=[
                ExtractedPlaceMention(name="Otaru Canal", evidence="OTARU CANAL NIGHT WALK")
            ],
        )

    async def fake_cover_text(url, **_kwargs):
        assert url == "https://www.tiktok.com/@traveler/video/1234567890"
        return "OTARU CANAL NIGHT WALK"

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(personal_module, "extract_place_mentions", fake_extract)
    monkeypatch.setattr(personal_module, "read_cover_text_for_url", fake_cover_text)
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "https://www.tiktok.com/@traveler/video/1234567890",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "ready"
    # Caption first, then caption plus cover text: two extractions, one read.
    assert len(extraction_inputs) == 2
    assert extraction_inputs[1].endswith("On screen: OTARU CANAL NIGHT WALK")
    candidates = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    assert candidates[0].name_canonical == "Otaru Canal"
    assert candidates[0].enrichment["source_url"] == (
        "https://www.tiktok.com/@traveler/video/1234567890"
    )
    assert candidates[0].enrichment["source_description"] == (
        "A canal walk that looks best after dark."
    )
