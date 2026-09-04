"""M3: Instagram, TikTok, and RedNote actually feeding the candidate pool.

The platform tools existed on this branch but nothing called them, so the pool
was a Google Places search and nothing else. These cover the wiring: profile
driven queries, content-first eligibility, engagement ranking, geocoding as
the reality check, and provider failure behavior.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather.social import (
    MinedPlace,
    MinedPost,
    SocialPlaceMention,
    SocialPlaceMentions,
    allocate_city_budget,
    discover_social_candidates,
    is_eligible,
    merge_into_pool,
    merge_mentions,
    score_places,
    select_social_candidates,
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

    assert len(base) == 3
    assert len(personalised) == 3
    # Interests refine the broad angle only, so the other two stay stable and
    # the provider cost does not scale with how much a group listed.
    assert personalised[0] == (
        "Hokkaido must visit places must eat food travel guide ramen onsen"
    )
    assert personalised[1:] == base[1:]


def test_rednote_interests_refine_the_single_localized_query():
    queries = build_discovery_queries(
        SocialPlatform.REDNOTE,
        destination="Hokkaido",
        destination_localized="北海道",
        interests=["拉麵"],
    )

    assert queries[0] == "北海道 必去景点 必吃美食 旅游攻略 探店 拉麵"
    assert len(queries) == 3


# ----- content-first eligibility -----


def test_one_independent_post_is_enough_before_google_verification():
    mined: dict[str, MinedPlace] = {}
    posts = [_tiktok(1)]
    merge_mentions(
        mined,
        SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(name="Ramen Yokocho", post_index=1),
            ]
        ),
        posts,
        SocialPlatform.TIKTOK,
    )

    kept = score_places(mined)

    assert [place.name for place in kept] == ["Ramen Yokocho"]
    assert kept[0].mention_count == 1
    assert kept[0].buzz_score > 0


def test_explicit_post_engagement_strengthens_a_place_score():
    quiet_post = _tiktok(1)
    popular_post = _tiktok(2).model_copy(
        update={"like_count": 12_400, "comment_count": 380}
    )
    quiet = MinedPlace(name="Quiet", post_urls=[quiet_post.reference.canonical_url])
    popular: dict[str, MinedPlace] = {}
    merge_mentions(
        popular,
        SocialPlaceMentions(
            mentions=[SocialPlaceMention(name="Popular", post_index=1)]
        ),
        [popular_post],
        SocialPlatform.TIKTOK,
    )

    assert popular["popular"].buzz_score > quiet.buzz_score
    assert popular["popular"].has_explicit_engagement is True


def test_the_highest_engagement_post_becomes_the_candidate_source_link():
    mined: dict[str, MinedPlace] = {}
    quiet = _post("https://www.instagram.com/reel/AbCdEfG1/")
    popular = _tiktok(2).model_copy(
        update={"like_count": 12_400, "comment_count": 380}
    )
    merge_mentions(
        mined,
        SocialPlaceMentions(
            mentions=[SocialPlaceMention(name="Ramen Yokocho", post_index=1)]
        ),
        [quiet],
        SocialPlatform.INSTAGRAM,
    )
    merge_mentions(
        mined,
        SocialPlaceMentions(
            mentions=[SocialPlaceMention(name="Ramen Yokocho", post_index=1)]
        ),
        [popular],
        SocialPlatform.TIKTOK,
    )
    place = PlaceMatch(
        place_id="ChIJ-ramen",
        display_name="Sapporo Ramen Yokocho",
        lat=43.055,
        lng=141.353,
        primary_type="restaurant",
        types=["restaurant"],
    )

    candidate = to_candidate(place, mined["ramen yokocho"], _trip())

    assert candidate.enrichment["social_post_urls"][0] == (
        popular.reference.canonical_url
    )
    assert candidate.enrichment["social_posts"][0]["like_count"] == 12_400


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

    async def fake_extract(_posts, *, platform, destination, interests=None, client=None):
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


async def test_multilingual_aliases_count_together_after_google_resolves_them(
    monkeypatch,
):
    trip = _trip()
    posts_by_platform = {
        SocialPlatform.TIKTOK: [
            _tiktok(1, title="Hakodate Morning Market food tour")
        ],
        SocialPlatform.INSTAGRAM: [
            _post(
                "https://www.instagram.com/reel/AbCdEfG1/",
                title="Morning Market Hakodate",
            )
        ],
        SocialPlatform.REDNOTE: [
            _post(
                "https://www.xiaohongshu.com/explore/5eeca1ba0000000001000ccc",
                title="函館朝市",
            )
        ],
    }
    names = {
        SocialPlatform.TIKTOK: "Hakodate Morning Market",
        SocialPlatform.INSTAGRAM: "Morning Market Hakodate",
        SocialPlatform.REDNOTE: "函館朝市",
    }

    async def fake_search(platform, *, destination, interests):
        return posts_by_platform[platform]

    async def fake_extract(_posts, *, platform, destination, interests=None, client=None):
        return SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(
                    name=names[platform],
                    canonical_name="Hakodate Morning Market",
                    post_index=1,
                )
            ]
        )

    geocode_queries = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        geocode_queries.append(arguments.query)
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="ChIJ-hakodate-market",
                    display_name="Hakodate Morning Market",
                    lat=41.772,
                    lng=140.724,
                    primary_type="market",
                    types=["market"],
                )
            ]
        )

    monkeypatch.setattr(social_module, "_search_platform", fake_search)
    monkeypatch.setattr(social_module, "extract_post_places", fake_extract)
    monkeypatch.setattr(social_module, "run_tool", fake_run_tool)

    candidates = await discover_social_candidates(trip, [])

    assert [candidate.name_canonical for candidate in candidates] == [
        "Hakodate Morning Market"
    ]
    candidate = candidates[0]
    assert candidate.sources[0].sources_count == 3
    assert candidate.enrichment["social_platforms"] == [
        "instagram",
        "tiktok",
        "rednote",
    ]
    assert len(candidate.enrichment["social_post_urls"]) == 3
    assert geocode_queries == ["Hakodate Morning Market"]


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


def test_a_single_mention_can_introduce_a_place():
    assert is_eligible(MinedPlace(name="One off", platforms=["tiktok"], post_urls=["a"]))


def test_enough_posts_on_one_platform_qualifies():
    assert is_eligible(
        MinedPlace(name="Ramen Alley", platforms=["tiktok"], post_urls=["a", "b", "c"])
    )


def test_two_posts_do_not_need_cross_platform_confirmation():
    assert is_eligible(
        MinedPlace(
            name="Otaru Canal",
            platforms=["instagram", "tiktok"],
            post_urls=["a", "b"],
        )
    )


def test_more_independent_posts_rank_ahead_without_cross_platform_requirement():
    mined = {
        "one": MinedPlace(name="One platform", platforms=["tiktok"], post_urls=["a", "b", "c", "d"]),
        "two": MinedPlace(
            name="Two platforms",
            platforms=["tiktok", "instagram"],
            post_urls=["e", "f", "g"],
        ),
    }

    assert [place.name for place in score_places(mined)] == [
        "One platform",
        "Two platforms",
    ]


# ----- two-lane selection (SOCIAL_TWO_LANE_PLAN.md) -----


def _mined(name: str, urls: list[str], *, fit: int = 0, authors: list[str] | None = None) -> MinedPlace:
    posts = [
        MinedPost(
            platform="tiktok",
            url=url,
            rank=index + 1,
            interest_fit=fit,
            author_name=authors[index] if authors else None,
        )
        for index, url in enumerate(urls)
    ]
    return MinedPlace(name=name, platforms=["tiktok"], post_urls=list(urls), posts=posts)


def _listicle(count: int) -> list[MinedPlace]:
    """One post naming `count` places, which is what a listicle video is."""
    return [_mined(f"Zed Place {index}", ["https://www.tiktok.com/@a/video/1"]) for index in range(count)]


def test_a_listicle_does_not_capture_the_deck_alphabetically():
    """The bug this lane split exists to fix.

    Ten places from one video all score log(2) and used to be cut by name, so
    the deck became one creator's opinion in alphabetical order.
    """
    better = _mined(
        "Zzz Cafe",
        ["https://www.tiktok.com/@a/video/1", "https://www.tiktok.com/@b/video/2"],
        authors=["a", "b"],
    )
    places = [*_listicle(10), better]

    selected = select_social_candidates(places, budget=3)

    # Last alphabetically, first on evidence.
    assert selected[0].place.name == "Zzz Cafe"


def test_independent_sources_outrank_repeated_mentions_from_one_post():
    """The property, not the arithmetic: log(mentions) alone cannot tell a
    listicle entry from an independently corroborated place."""
    one_video = _mined("From one video", ["https://www.tiktok.com/@a/video/1"])
    two_creators = _mined(
        "From two creators",
        ["https://www.tiktok.com/@a/video/1", "https://www.tiktok.com/@b/video/2"],
        authors=["a", "b"],
    )

    assert two_creators.independent_source_count == 2
    assert one_video.independent_source_count == 1
    ranked = select_social_candidates([one_video, two_creators], budget=2)
    assert ranked[0].place.name == "From two creators"


def test_a_single_mention_matching_interests_reaches_the_deck():
    """A hidden gem is mentioned once by definition, so a popularity sort can
    never surface it. That is the whole point of the second lane."""
    gem = _mined("Quiet Kissaten", ["https://www.tiktok.com/@c/video/9"], fit=3)
    places = [*_listicle(10), gem]

    selected = select_social_candidates(places, budget=5)

    chosen = {choice.place.name: choice.lane for choice in selected}
    assert chosen["Quiet Kissaten"] == "for_you"


def test_a_group_with_no_interests_gets_a_full_trending_deck():
    places = _listicle(10)

    selected = select_social_candidates(places, budget=6)

    assert len(selected) == 6
    assert {choice.lane for choice in selected} == {"trending"}


def test_an_unfilled_interest_lane_is_backfilled_rather_than_left_short():
    """Only one place clears the fit floor, so the other lane slots must not
    simply vanish from the budget."""
    gem = _mined("Quiet Kissaten", ["https://www.tiktok.com/@c/video/9"], fit=3)
    weak = _mined("Loose Match", ["https://www.tiktok.com/@d/video/8"], fit=1)
    places = [*_listicle(10), gem, weak]

    selected = select_social_candidates(places, budget=10)

    assert len(selected) == 10
    lanes = [choice.lane for choice in selected]
    assert lanes.count("for_you") == 1
    assert "Loose Match" not in {
        choice.place.name for choice in selected if choice.lane == "for_you"
    }


def test_selection_never_exceeds_or_undershoots_the_budget():
    places = _listicle(40)
    assert len(select_social_candidates(places, budget=12)) == 12
    assert len(select_social_candidates(places[:3], budget=12)) == 3
    assert select_social_candidates(places, budget=0) == []


def test_city_budget_is_shared_out_and_never_starves_a_city():
    assert sum(allocate_city_budget([1, 1, 1], 32)) == 32
    assert min(allocate_city_budget([1, 1, 1, 1], 32)) >= 1
    # A city with more trip days earns more of the budget.
    weighted = allocate_city_budget([4, 1, 1], 32)
    assert weighted[0] > weighted[1]
    # Budget smaller than the city count still gives what it can, not fractions.
    assert allocate_city_budget([1, 1, 1], 2) == [1, 1, 0]


def test_the_selection_lane_reaches_the_card():
    place = PlaceMatch(
        place_id="ChIJ-kissaten",
        display_name="Quiet Kissaten",
        lat=43.055,
        lng=141.353,
        primary_type="cafe",
        types=["cafe"],
    )
    gem = _mined("Quiet Kissaten", ["https://www.tiktok.com/@c/video/9"], fit=3)

    candidate = to_candidate(place, gem, _trip(), lane="for_you")

    assert candidate.trending_signals["selection_lane"] == "for_you"
    assert candidate.trending_signals["interest_score"] == 3
    assert candidate.trending_signals["independent_source_count"] == 1


# ----- the supply-limited regime, which is the normal one -----


def test_for_you_still_fills_when_supply_is_below_the_trending_quota():
    """The bug that made the lane dead in production.

    Mining a city yields about nine eligible names while the budget is
    thirty-two, so trending's quota alone exceeded the entire supply. Drawing
    trending first took every place and For You chose from an empty list, even
    though places had cleared the interest bar. Every earlier test had more
    places than slots, which is the regime that never happens.
    """
    places = [_mined(f"Popular {i}", [f"u{i}"]) for i in range(6)]
    places += [_mined(f"Suits us {i}", [f"g{i}"], fit=3) for i in range(3)]

    selected = select_social_candidates(places, budget=32)

    lanes = Counter(choice.lane for choice in selected)
    assert lanes["for_you"] > 0, "nine places, twenty-three trending slots"
    assert len(selected) == 9, "every mined place is still verified"


def test_lanes_are_sized_against_supply_not_against_the_budget():
    """Slot counts taken from the budget describe places that do not exist."""
    places = [_mined(f"P{i}", [f"u{i}"], fit=3 if i < 4 else 0) for i in range(10)]

    selected = select_social_candidates(places, budget=32)
    lanes = Counter(choice.lane for choice in selected)

    # 10 available -> 7 trending, 3 for you, rather than 23 and 9.
    assert lanes["trending"] == 7
    assert lanes["for_you"] == 3


def test_for_you_draws_before_trending():
    """Order decides whether the lane gets anything at all when supply is
    short, so it is the behaviour worth pinning, not an implementation
    detail."""
    strong = _mined("Everyone posts this", ["a", "b", "c"], authors=["a", "b", "c"])
    quiet = _mined("Quiet Kissaten", ["d"], fit=3)
    # Sized like a real city. Below four places the 70/30 split rounds the
    # For You lane away entirely, which is a rounding question rather than
    # the ordering question this test is about.
    filler = [_mined(f"Filler {i}", [f"f{i}"]) for i in range(8)]

    selected = select_social_candidates([strong, quiet, *filler], budget=32)

    lane_of = {choice.place.name: choice.lane for choice in selected}
    assert lane_of["Quiet Kissaten"] == "for_you"
    assert lane_of["Everyone posts this"] == "trending"


def test_no_interest_matches_still_spends_the_run():
    places = [_mined(f"P{i}", [f"u{i}"]) for i in range(8)]

    selected = select_social_candidates(places, budget=32)

    assert len(selected) == 8
    assert {choice.lane for choice in selected} == {"trending"}


def test_the_search_asks_three_different_questions():
    """One query returned about nine names for a whole city. The angles have
    to differ in kind, because asking the same thing three ways returns the
    same posts."""
    queries = build_discovery_queries(
        SocialPlatform.TIKTOK, destination="Sapporo", interests=["coffee"]
    )

    assert len(queries) == 3
    assert len(set(queries)) == 3
    assert all("Sapporo" in query for query in queries)
