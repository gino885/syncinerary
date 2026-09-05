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
    SearchIntent,
    SearchIntentType,
    SocialLinkMetadataInput,
    build_discovery_query,
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


def _stub_translation(monkeypatch, value: str | None = "北海道") -> None:
    """Skip the one Mandarin-name call the city loop makes before planning."""

    async def fake_translate(destination, *, client=None):
        return value

    monkeypatch.setattr(
        social_module, "translate_destination_to_mandarin", fake_translate
    )


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


def test_interests_rank_the_for_you_lane_rather_than_steering_search():
    """Interests used to be stapled onto the query, and later drove searches of
    their own. Both made provider cost scale with how much a group listed.

    They now rank the hidden-gem pool instead, so the query set is fixed at
    three intents whatever the group said it likes.
    """
    queries = {
        build_discovery_query(
            SearchIntent(
                platform=SocialPlatform.INSTAGRAM, intent_type=intent_type
            ),
            destination="Hokkaido",
        )
        for intent_type in SearchIntentType
    }

    assert len(queries) == 3
    assert not any("coffee" in query for query in queries)
    assert not any("ramen" in query for query in queries)


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

    async def fake_search(_platform, *, query, destination):
        return posts

    async def fake_extract(
        _posts, *, platform, destination, interests=None, query=None, client=None
    ):
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
    _stub_translation(monkeypatch)

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

    async def fake_search(platform, *, query, destination):
        return posts_by_platform[platform]

    async def fake_extract(
        _posts, *, platform, destination, interests=None, query=None, client=None
    ):
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
    _stub_translation(monkeypatch)

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

    async def exploding_search(platform, *, query, destination):
        raise RuntimeError("BRAVE_SEARCH_API_KEY is required for social discovery")

    monkeypatch.setattr(social_module, "_search_platform", exploding_search)
    _stub_translation(monkeypatch)

    with pytest.raises(RuntimeError, match="BRAVE_SEARCH_API_KEY"):
        await discover_social_candidates(trip, [])


async def test_rednote_searches_use_the_mandarin_destination_name(monkeypatch):
    """The translation now happens once per city, before the loop plans.

    The planner has to know whether RedNote can be searched at all, and
    RedNote without the Mandarin name searches a different corpus.
    """
    queries: list[tuple[SocialPlatform, str]] = []

    async def fake_search(platform, *, query, destination):
        queries.append((platform, query))
        return []

    monkeypatch.setattr(social_module, "_search_platform", fake_search)
    _stub_translation(monkeypatch)

    await discover_social_candidates(_trip(), [])

    rednote = [query for platform, query in queries if platform is SocialPlatform.REDNOTE]
    assert rednote, "RedNote must still take part in automatic discovery"
    assert all(query.startswith("北海道 ") for query in rednote)
    assert not any("Hokkaido" in query for query in rednote)


async def test_rednote_is_skipped_when_no_mandarin_name_is_available(monkeypatch):
    """Silently searching xiaohongshu.com in English would be worse than not
    searching it at all."""
    queries: list[SocialPlatform] = []

    async def fake_search(platform, *, query, destination):
        queries.append(platform)
        return []

    monkeypatch.setattr(social_module, "_search_platform", fake_search)
    _stub_translation(monkeypatch, value=None)

    await discover_social_candidates(_trip(), [])

    assert queries, "the other platforms still run"
    assert SocialPlatform.REDNOTE not in queries


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


def _mined(
    name: str,
    urls: list[str],
    *,
    fit: int = 0,
    authors: list[str] | None = None,
    intent: SearchIntentType = SearchIntentType.PLACES,
) -> MinedPlace:
    """A mined place, with the search intent that found it.

    The intent is what decides the lane now, so it belongs in the fixture
    rather than being inferred from the score.
    """
    posts = [
        MinedPost(
            platform="tiktok",
            url=url,
            rank=index + 1,
            interest_fit=fit,
            author_name=authors[index] if authors else None,
            intent_type=intent.value,
        )
        for index, url in enumerate(urls)
    ]
    return MinedPlace(name=name, platforms=["tiktok"], post_urls=list(urls), posts=posts)


def _gem(name: str, urls: list[str], **kwargs) -> MinedPlace:
    return _mined(name, urls, intent=SearchIntentType.HIDDEN_GEMS, **kwargs)


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


def test_the_lanes_are_fed_by_different_searches_not_by_different_sorts():
    """The property the whole design rests on.

    Trending comes from the places and food searches, For You from the
    hidden-gem search. One pool sorted two ways would make the lanes cosmetic,
    because a place named once by one creator cannot out-rank a popular one on
    any popularity-derived weighting.
    """
    popular = [_mined(f"Popular {i}", [f"u{i}", f"v{i}"]) for i in range(6)]
    gems = [_gem(f"Quiet {i}", [f"g{i}"]) for i in range(3)]

    selected = select_social_candidates([*popular, *gems], budget=9)

    lanes = {choice.place.name: choice.lane for choice in selected}
    assert all(lanes[f"Quiet {i}"] == "for_you" for i in range(3))
    assert all(lanes[f"Popular {i}"] == "trending" for i in range(6))


def test_a_single_mention_from_the_hidden_gem_search_reaches_the_deck():
    """A hidden gem is mentioned once by definition, so a popularity sort can
    never surface it. Asking for it explicitly is what makes it reachable."""
    gem = _gem("Quiet Kissaten", ["https://www.tiktok.com/@c/video/9"], fit=3)
    places = [*_listicle(10), gem]

    selected = select_social_candidates(places, budget=5)

    chosen = {choice.place.name: choice.lane for choice in selected}
    assert chosen["Quiet Kissaten"] == "for_you"


def test_preference_fit_ranks_the_for_you_lane_but_does_not_gate_it():
    """Fit orders the hidden gems; it does not decide which are gems.

    A group that listed no interests still gets a For You lane, because the
    lane's membership comes from how the candidates were found.
    """
    match = _gem("Roastery", ["a"], fit=3)
    loose = _gem("Old Shrine", ["b"], fit=1)
    none = _gem("Back Alley", ["c"], fit=0)

    selected = select_social_candidates([match, loose, none], budget=3)

    assert [choice.lane for choice in selected] == ["for_you"] * 3
    assert [choice.place.name for choice in selected] == [
        "Roastery",
        "Old Shrine",
        "Back Alley",
    ]


def test_a_hidden_gem_still_needs_evidence_behind_it():
    """Least popular is not the goal. Between two gems the group has no stated
    interest in, the better evidenced one goes first."""
    corroborated = _gem("Two creators", ["a", "b"], authors=["a", "b"])
    single = _gem("One post", ["c"])

    selected = select_social_candidates([single, corroborated], budget=2)

    assert selected[0].place.name == "Two creators"


def test_a_place_both_searches_found_keeps_both_provenances():
    """Overlap after dedupe is evidence, not a conflict, so it survives."""
    place = _mined("Nijo Market", ["a"])
    place.posts.append(
        MinedPost(
            platform="instagram",
            url="b",
            rank=1,
            intent_type=SearchIntentType.HIDDEN_GEMS.value,
        )
    )
    place.post_urls.append("b")

    assert place.intent_types == ["places", "hidden_gems"]
    assert place.is_hidden_gem is True
    # For You claims it: a hidden-gem search naming it is the rarer evidence,
    # and trending has the deeper pool to draw from.
    assert select_social_candidates([place], budget=1)[0].lane == "for_you"


def test_a_group_with_no_hidden_gems_found_gets_a_full_trending_deck():
    places = _listicle(10)

    selected = select_social_candidates(places, budget=6)

    assert len(selected) == 6
    assert {choice.lane for choice in selected} == {"trending"}


def test_an_unfilled_lane_is_backfilled_rather_than_left_short():
    """Only one hidden gem was found, so the other For You slots must not
    simply vanish from the budget."""
    gem = _gem("Quiet Kissaten", ["https://www.tiktok.com/@c/video/9"], fit=3)
    places = [*_listicle(10), gem]

    selected = select_social_candidates(places, budget=10)

    assert len(selected) == 10
    lanes = [choice.lane for choice in selected]
    assert lanes.count("for_you") == 1
    # A backfilled card never claims a lane its search never asked for.
    assert all(
        choice.place.is_hidden_gem
        for choice in selected
        if choice.lane == "for_you"
    )


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

    Mining a city yields far fewer eligible names than the budget, so
    trending's quota alone exceeded the entire supply. Drawing trending first
    took every place and For You chose from an empty list. Every earlier test
    had more places than slots, which is the regime that never happens.
    """
    places = [_mined(f"Popular {i}", [f"u{i}"]) for i in range(6)]
    places += [_gem(f"Quiet {i}", [f"g{i}"], fit=3) for i in range(3)]

    selected = select_social_candidates(places, budget=32)

    lanes = Counter(choice.lane for choice in selected)
    assert lanes["for_you"] == 3, "nine places, twenty-three trending slots"
    assert len(selected) == 9, "every mined place is still verified"


def test_lanes_are_sized_against_supply_not_against_the_budget():
    """Slot counts taken from the budget describe places that do not exist."""
    places = [_mined(f"P{i}", [f"u{i}"]) for i in range(7)]
    places += [_gem(f"G{i}", [f"g{i}"]) for i in range(3)]

    selected = select_social_candidates(places, budget=32)
    lanes = Counter(choice.lane for choice in selected)

    # 10 available -> 7 trending, 3 for you, rather than 23 and 9.
    assert lanes["trending"] == 7
    assert lanes["for_you"] == 3


def test_for_you_draws_before_trending():
    """Order decides whether the lane gets anything at all when supply is
    short, so it is the behaviour worth pinning."""
    strong = _mined("Everyone posts this", ["a", "b", "c"], authors=["a", "b", "c"])
    quiet = _gem("Quiet Kissaten", ["d"], fit=3)
    filler = [_mined(f"Filler {i}", [f"f{i}"]) for i in range(8)]

    selected = select_social_candidates([strong, quiet, *filler], budget=32)

    lane_of = {choice.place.name: choice.lane for choice in selected}
    assert lane_of["Quiet Kissaten"] == "for_you"
    assert lane_of["Everyone posts this"] == "trending"


def test_no_hidden_gems_still_spends_the_run():
    places = [_mined(f"P{i}", [f"u{i}"]) for i in range(8)]

    selected = select_social_candidates(places, budget=32)

    assert len(selected) == 8
    assert {choice.lane for choice in selected} == {"trending"}


def test_the_three_intents_ask_different_questions():
    """Asking the same thing three ways returns the same posts, so the intents
    the planner can choose from have to differ in kind, not in wording."""
    queries = [
        build_discovery_query(
            SearchIntent(platform=SocialPlatform.TIKTOK, intent_type=intent_type),
            destination="Sapporo",
        )
        for intent_type in SearchIntentType
    ]

    assert len(set(queries)) == len(queries)
    assert all("Sapporo" in query for query in queries)
