"""M3: Instagram, TikTok, and RedNote actually feeding the candidate pool.

The platform tools existed on this branch but nothing called them, so the pool
was a Google Places search and nothing else. These cover the wiring: profile
driven queries, the cross-source threshold, geocoding as the reality check,
and the graceful degradation that keeps a missing key from failing a gather.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather.social import (
    MinedPlace,
    SocialPlaceMention,
    SocialPlaceMentions,
    discover_social_candidates,
    eligible_places,
    is_eligible,
    merge_into_pool,
    merge_mentions,
    to_candidate,
    traveler_interests,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    SocialPlatform,
    Source,
    Traveler,
    Trip,
)
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    DiscoveredSocialURL,
    SocialLinkMetadataInput,
    build_discovery_queries,
    make_social_link_metadata_tool,
    normalize_social_url,
)
from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput, ResolvedCity


def _trip() -> Trip:
    city = ResolvedCity(
        query="Hokkaido",
        place_id="city-hokkaido",
        name="Hokkaido",
        lat=43.0618,
        lng=141.3545,
        radius_km=25,
        country="Japan",
        country_code="JP",
    )
    return Trip(
        destination="Hokkaido",
        cities=["Hokkaido"],
        country="Japan",
        resolved_cities=[city.model_dump(mode="json")],
        timezone="Asia/Tokyo",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 10, 1),
        days=5,
    )


def _post(url: str, *, query: str = "q", title: str | None = None) -> DiscoveredSocialURL:
    return DiscoveredSocialURL(
        reference=normalize_social_url(url),
        query=query,
        rank=1,
        title=title,
        description="A snippet the search index already publishes.",
    )


def _tiktok(index: int, **kwargs) -> DiscoveredSocialURL:
    return _post(f"https://www.tiktok.com/@creator/video/{7000000000 + index}", **kwargs)


class StubMessages:
    def __init__(self, text: str) -> None:
        self.text = text

    async def create(self, **_kwargs):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=self.text)],
        )


# ----- personalised queries -----


def test_traveler_interests_are_collected_in_order_without_duplicates():
    trip_id = uuid4()
    travelers = [
        Traveler(trip_id=trip_id, name="Gino", profile={"interests": ["ramen", "onsen"]}),
        Traveler(trip_id=trip_id, name="Mei", profile={"interests": ["onsen", "pottery"]}),
        Traveler(trip_id=trip_id, name="Sam", profile={}),
    ]

    assert traveler_interests(travelers) == ["ramen", "onsen", "pottery"]


def test_interests_refine_the_base_query_without_adding_requests():
    base = build_discovery_queries(SocialPlatform.INSTAGRAM, destination="Hokkaido")
    personalised = build_discovery_queries(
        SocialPlatform.INSTAGRAM,
        destination="Hokkaido",
        interests=["ramen", "onsen"],
    )

    assert len(base) == 1
    assert personalised == ["Hokkaido travel food guide ramen onsen"]


def test_rednote_interests_refine_the_single_localized_query():
    queries = build_discovery_queries(
        SocialPlatform.REDNOTE,
        destination="Hokkaido",
        destination_localized="北海道",
        interests=["拉麵"],
    )

    assert queries == ["北海道旅游美食攻略 拉麵"]


# ----- the cross-source threshold -----


def test_a_place_needs_the_configured_number_of_posts_before_it_is_geocoded():
    mined: dict[str, MinedPlace] = {}
    posts = [_tiktok(index) for index in range(3)]
    merge_mentions(
        mined,
        SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(name="Ramen Yokocho", post_index=1),
                SocialPlaceMention(name="Ramen Yokocho", post_index=2),
                SocialPlaceMention(name="Ramen Yokocho", post_index=3),
                SocialPlaceMention(name="One off cafe", post_index=1),
            ]
        ),
        posts,
        SocialPlatform.TIKTOK,
    )

    kept = eligible_places(mined)

    assert [place.name for place in kept] == ["Ramen Yokocho"]
    assert kept[0].mention_count == 3
    assert kept[0].buzz_score > 0


def test_the_same_post_is_never_counted_twice_for_one_place():
    mined: dict[str, MinedPlace] = {}
    posts = [_tiktok(0)]
    for _ in range(3):
        merge_mentions(
            mined,
            SocialPlaceMentions(
                mentions=[SocialPlaceMention(name="Ramen Yokocho", post_index=1)]
            ),
            posts,
            SocialPlatform.TIKTOK,
        )

    assert mined["ramen yokocho"].mention_count == 1


def test_mentions_across_platforms_accumulate_onto_one_place():
    mined: dict[str, MinedPlace] = {}
    merge_mentions(
        mined,
        SocialPlaceMentions(mentions=[SocialPlaceMention(name="Ramen Yokocho", post_index=1)]),
        [_tiktok(1)],
        SocialPlatform.TIKTOK,
    )
    merge_mentions(
        mined,
        SocialPlaceMentions(mentions=[SocialPlaceMention(name="ramen yokocho", post_index=1)]),
        [_post("https://www.instagram.com/reel/AbCdEfG1/")],
        SocialPlatform.INSTAGRAM,
    )

    place = mined["ramen yokocho"]
    assert place.mention_count == 2
    assert place.platforms == ["tiktok", "instagram"]


def test_a_mention_pointing_past_the_post_list_is_ignored():
    mined: dict[str, MinedPlace] = {}
    merge_mentions(
        mined,
        SocialPlaceMentions(mentions=[SocialPlaceMention(name="Nowhere", post_index=9)]),
        [_tiktok(1)],
        SocialPlatform.TIKTOK,
    )

    assert mined == {}


async def test_invalid_social_extraction_is_not_hidden_as_no_mentions():
    with pytest.raises(ValueError, match="invalid data"):
        await social_module.extract_post_places(
            [_tiktok(1)],
            platform=SocialPlatform.TIKTOK,
            destination="Hokkaido",
            client=StubMessages("not JSON"),
        )


# ----- geocoding is the reality check -----


async def test_discovery_drops_names_google_cannot_resolve(monkeypatch):
    trip = _trip()
    posts = [_tiktok(index) for index in range(3)]

    async def fake_search(_platform, *, destination, interests):
        return posts

    async def fake_extract(_posts, *, platform, destination, client=None):
        if platform is not SocialPlatform.TIKTOK:
            return SocialPlaceMentions()
        return SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(name="Ramen Yokocho", post_index=index)
                for index in (1, 2, 3)
            ]
            + [
                SocialPlaceMention(name="Imaginary Tower", post_index=index)
                for index in (1, 2, 3)
            ]
        )

    async def fake_run_tool(_tool, arguments, **_kwargs):
        if arguments.query == "Ramen Yokocho":
            return PlaceSearchOutput(
                matches=[
                    PlaceMatch(
                        place_id="ChIJ-ramen",
                        display_name="Sapporo Ramen Yokocho",
                        lat=43.055,
                        lng=141.353,
                        primary_type="restaurant",
                        types=["restaurant"],
                    )
                ]
            )
        return PlaceSearchOutput(matches=[])

    monkeypatch.setattr(social_module, "_search_platform", fake_search)
    monkeypatch.setattr(social_module, "extract_post_places", fake_extract)
    monkeypatch.setattr(social_module, "run_tool", fake_run_tool)

    candidates = await discover_social_candidates(trip, [])

    assert [candidate.name_canonical for candidate in candidates] == [
        "Sapporo Ramen Yokocho"
    ]
    candidate = candidates[0]
    assert candidate.type is CandidateType.FOOD
    assert [source.type for source in candidate.sources] == ["buzz"]
    assert candidate.sources[0].sources_count == 3
    assert candidate.enrichment["city"] == "Hokkaido"
    assert candidate.enrichment["social_platforms"] == ["tiktok"]
    assert len(candidate.enrichment["social_post_urls"]) == 3


async def test_a_platform_failure_is_not_hidden_as_an_empty_result(monkeypatch):
    trip = _trip()

    async def exploding_search(platform, *, destination, interests):
        raise RuntimeError("BRAVE_SEARCH_API_KEY is required for social discovery")

    monkeypatch.setattr(social_module, "_search_platform", exploding_search)

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await discover_social_candidates(trip, [])


async def test_rednote_automatic_search_translates_the_destination_to_mandarin(
    monkeypatch,
):
    captured = None

    async def fake_translate(destination, *, client=None):
        assert destination == "Hokkaido"
        return "北海道"

    async def fake_run_tool(_tool, arguments, **_kwargs):
        nonlocal captured
        captured = arguments
        return SimpleNamespace(results=[])

    monkeypatch.setattr(
        social_module,
        "translate_destination_to_mandarin",
        fake_translate,
    )
    monkeypatch.setattr(social_module, "run_tool", fake_run_tool)

    await social_module._search_platform(
        SocialPlatform.REDNOTE,
        destination=_trip().destination,
        interests=[],
    )

    assert captured.destination_localized == "北海道"


# ----- one card, both provenances -----


def test_a_place_found_by_both_paths_keeps_one_card_and_both_sources():
    trip = _trip()
    discovered = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.FOOD,
        name_canonical="Sapporo Ramen Yokocho",
        lat=43.055,
        lng=141.353,
        sources=[Source(type="discovery", subtype="google_places")],
        enrichment={"google_place_id": "ChIJ-ramen", "source_description": "Alley of ramen."},
    )
    pool = {"ChIJ-ramen": discovered}

    social = to_candidate(
        PlaceMatch(
            place_id="ChIJ-ramen",
            display_name="Sapporo Ramen Yokocho",
            lat=43.055,
            lng=141.353,
            primary_type="restaurant",
            types=["restaurant"],
        ),
        MinedPlace(
            name="拉麵橫丁",
            platforms=["tiktok", "rednote"],
            post_urls=["a", "b", "c"],
            queries=["q"],
        ),
        trip,
    )

    merge_into_pool(pool, [social])

    assert len(pool) == 1
    merged = pool["ChIJ-ramen"]
    assert [source.type for source in merged.sources] == ["discovery", "buzz"]
    assert merged.enrichment["social_platforms"] == ["tiktok", "rednote"]
    # The richer description already on the card survives the merge.
    assert merged.enrichment["source_description"] == "Alley of ramen."


# ----- Instagram and RedNote links resolve without scraping -----


async def test_an_instagram_link_reads_its_public_indexed_metadata():
    url = "https://www.instagram.com/reel/AbCdEfG1/"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "https://www.instagram.com/reel/AbCdEfG1/"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": url,
                            "title": "Otaru Canal at night",
                            "description": "Warehouses lit along the water.",
                        }
                    ]
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        metadata = await run_tool(
            make_social_link_metadata_tool(client=client, api_key="test-key"),
            SocialLinkMetadataInput(url=url),
        )

    assert metadata.platform is SocialPlatform.INSTAGRAM
    assert metadata.title == "Otaru Canal at night"
    assert "Otaru Canal at night" in metadata.indexed_text


async def test_a_link_the_index_has_never_seen_returns_empty_text():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        metadata = await run_tool(
            make_social_link_metadata_tool(client=client, api_key="test-key"),
            SocialLinkMetadataInput(url="https://www.xiaohongshu.com/explore/abc123"),
        )

    assert metadata.platform is SocialPlatform.REDNOTE
    assert metadata.indexed_text == ""


async def test_link_metadata_requires_a_configured_key():
    tool = make_social_link_metadata_tool(api_key="")

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await run_tool(
            tool,
            SocialLinkMetadataInput(url="https://www.instagram.com/reel/AbCdEfG1/"),
        )


# ----- what counts as independent evidence -----


def test_a_single_mention_is_never_enough():
    assert not is_eligible(MinedPlace(name="One off", platforms=["tiktok"], post_urls=["a"]))


def test_enough_posts_on_one_platform_qualifies():
    assert is_eligible(
        MinedPlace(name="Ramen Alley", platforms=["tiktok"], post_urls=["a", "b", "c"])
    )


def test_two_posts_on_two_platforms_do_not_bypass_the_source_threshold():
    """The documented rule still requires three independent source posts."""
    assert not is_eligible(
        MinedPlace(
            name="Otaru Canal",
            platforms=["instagram", "tiktok"],
            post_urls=["a", "b"],
        )
    )


def test_cross_platform_places_are_geocoded_before_single_platform_ones():
    mined = {
        "one": MinedPlace(name="One platform", platforms=["tiktok"], post_urls=["a", "b", "c", "d"]),
        "two": MinedPlace(
            name="Two platforms",
            platforms=["tiktok", "instagram"],
            post_urls=["e", "f", "g"],
        ),
    }

    assert [place.name for place in eligible_places(mined)] == [
        "Two platforms",
        "One platform",
    ]
