"""Reel coverage is measured on real cards, not search rows or source labels."""

from uuid import uuid4

import httpx
import pytest

from syncinerary.agents.gather.live import limit_social_pool
from syncinerary.agents.gather.social import MinedPlace, MinedPost
from syncinerary.agents.gather.social_search import (
    SearchOutcome,
    initialize_social_search_state,
    plan_next_search,
    update_search_state,
)
from syncinerary.domain.models import CandidatePlace, CandidateType, SocialPlatform, Source
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    BraveSocialSearchInput,
    SearchIntent,
    SearchIntentType,
    make_brave_social_search_tool,
)


def card(index, *, reel=False, personal=False, gem=False, kind=CandidateType.ATTRACTION):
    url = f"https://www.instagram.com/reel/clip{index}/"
    return CandidatePlace(
        trip_id=uuid4(),
        type=kind,
        name_canonical=f"Venue {index}",
        lat=35 + index * 0.01,
        lng=139,
        sources=[Source(type="personal", subtype="user_paste", url=url)]
        if personal
        else [
            Source(type="buzz" if reel else "discovery", subtype=None if reel else "google_places")
        ],
        enrichment={
            "google_place_id": str(index),
            "city": "Tokyo",
            "social_posts": [{"platform": "instagram", "url": url}] if reel else [],
        },
        trending_signals={"selection_lane": "for_you" if gem else "trending"},
    )


def test_source_mix_deduplicates_and_separates_user_links_from_automatic_evidence():
    from syncinerary.agents.gather.source_mix import source_mix_report

    reel = card(1, reel=True)
    plain = card(2)
    report = source_mix_report(
        [
            reel,
            reel.model_copy(update={"id": uuid4()}),
            plain,
            card(3, personal=True),
            card(4, reel=True, kind=CandidateType.LODGING),
        ]
    )
    assert report.visible.total == 3
    assert report.visible.reels == 2
    assert report.visible.reel_share == pytest.approx(2 / 3)
    assert report.automatic.total == 2
    assert report.automatic.reels == 1
    assert not report.automatic.majority_met  # Exactly 50% is insufficient.
    assert report.automatic.google_only == 1


def test_profile_and_fake_reel_urls_do_not_count_as_reel_evidence():
    from syncinerary.agents.gather.source_mix import source_mix_report

    cards = [card(i, reel=True) for i in range(3)]
    for candidate, url in zip(
        cards,
        [
            "https://www.instagram.com/p/post1/",
            "https://www.instagram.com/creator/reels/",
            "https://instagram.com.attacker.test/reel/clip1/",
        ],
        strict=True,
    ):
        candidate.enrichment["social_posts"] = [{"platform": "instagram", "url": url}]
    report = source_mix_report(cards)
    assert report.visible.reels == 0
    assert report.visible.other_social == 3
    assert not source_mix_report([]).visible.majority_met


def test_automatic_report_ignores_attached_links_on_google_cards_and_counts_place_ids_once():
    from syncinerary.agents.gather.source_mix import source_mix_report

    first = card(1)
    first.sources.append(
        Source(
            type="personal", subtype="user_paste", url="https://www.instagram.com/reel/attached/"
        )
    )
    alias = first.model_copy(update={"id": uuid4(), "name_canonical": "Another listing", "lat": 36})
    report = source_mix_report([first, alias])
    assert report.automatic.total == 1
    assert report.automatic.google_only == 1
    assert report.automatic.reels == 0
    assert report.visible.reels == 1
    assert report.by_city["Tokyo"].total == 1


def test_reel_preference_keeps_hidden_gem_slots_and_does_not_shrink_a_thin_deck():
    cards = [card(i, gem=i < 3) for i in range(10)]
    cards += [card(i + 10, reel=True, gem=i < 2) for i in range(8)]
    selected = limit_social_pool(cards, 10)
    assert len(selected) == 10
    assert sum(bool(c.enrichment["social_posts"]) for c in selected) >= 6
    assert sum(c.trending_signals["selection_lane"] == "for_you" for c in selected) == 3
    assert len(limit_social_pool(cards[:10], 10)) == 10


async def test_video_search_parses_top_level_results_and_isolates_page_and_surface_cache():
    calls = []

    class Cache:
        def __init__(self):
            self.data = {}

        async def get(self, key):
            return self.data.get(key)

        async def set(self, key, value, *, ex):
            self.data[key] = value

    def respond(request):
        calls.append(request)
        rows = [
            {
                "url": "https://www.instagram.com/reel/clip1/?utm_source=x",
                "title": "A &amp; B cafe",
                "description": "Visit <strong>A &amp; B</strong>",
                "video": {"creator": "Local creator", "views": 123},
                "thumbnail": {"src": "https://example.test/private-image"},
            },
            {"url": "https://www.instagram.com/reel/clip1/", "title": "Duplicate"},
            {"url": "https://www.youtube.com/shorts/other", "title": "Excluded"},
        ]
        return httpx.Response(
            200,
            json={"results": rows} if "/videos/" in request.url.path else {"web": {"results": []}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = make_brave_social_search_tool(client=client, api_key="test", cache=Cache())
        base = {"platform": SocialPlatform.INSTAGRAM, "query": "Tokyo cafes"}
        video = await run_tool(tool, BraveSocialSearchInput(**base, search_kind="videos"))
        web = await run_tool(tool, BraveSocialSearchInput(**base))
        await run_tool(tool, BraveSocialSearchInput(**base, search_kind="videos", offset=1))
        await run_tool(tool, BraveSocialSearchInput(**base, search_kind="videos"))
    assert len(calls) == 3
    assert calls[0].url.path.endswith("/videos/search")
    assert "extra_snippets" not in calls[0].url.params
    assert len(video.results) == 1
    assert video.results[0].title == "A & B cafe"
    assert video.results[0].description == "Visit A & B"
    assert video.results[0].author_name == "Local creator"
    assert video.results[0].thumbnail_url is None
    assert video.results[0].like_count is None
    assert web.results == []


def test_verified_reel_deficit_keeps_searching_after_other_social_fills_raw_target():
    state = initialize_social_search_state(
        destination="Tokyo",
        destination_local_name="东京",
        target_candidates=4,
        reel_target=2,
        verified_lane_supply=(3, 1),
        verified_reels=0,
    )
    for kind, platform in zip(SearchIntentType, SocialPlatform, strict=True):
        intent = SearchIntent(platform=platform, intent_type=kind)
        update_search_state(
            state, intent=intent, query=kind.value, outcome=SearchOutcome(new_unique_places_count=3)
        )
        state.discovered_places[kind.value] = MinedPlace(
            name=kind.value,
            posts=[
                MinedPost(
                    platform="rednote", url="https://example.test", rank=1, intent_type=kind.value
                )
            ],
        )
    next_search = plan_next_search(state)
    assert next_search is not None
    assert next_search.platform is SocialPlatform.INSTAGRAM
    state.verified_reels = 2
    assert plan_next_search(state) is None
    assert state.stop_reason.value == "target_reached"


def test_guide_budget_leaves_room_for_the_reel_target_without_raising_total_cap():
    from syncinerary.config.gather import guide_verify_budget, reel_target, social_verify_budget

    assert reel_target(days=5) == 24
    assert guide_verify_budget(days=5) == 8
    assert social_verify_budget(days=5) == 40


async def test_verification_failures_drive_another_search_and_duplicate_places_count_once(
    monkeypatch,
):
    from datetime import date

    from syncinerary.agents.gather import social
    from syncinerary.domain.models import Trip
    from syncinerary.tools.fetch.social import DiscoveredSocialURL, normalize_social_url
    from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput, ResolvedCity

    trip = Trip(
        destination="Tokyo", days=1, start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)
    )
    city = ResolvedCity(query="Tokyo", place_id="city", name="Tokyo", lat=35, lng=139, radius_km=25)
    queried = []
    searches = []

    async def search(platform, *, query, destination, output_locale="en"):
        searches.append(platform)
        return [
            DiscoveredSocialURL(
                reference=normalize_social_url(
                    f"https://www.instagram.com/reel/clip{len(searches)}/"
                ),
                query=query,
                rank=1,
                title="Named places",
            )
        ]

    async def extract(posts, **kwargs):
        names = ["Rejected venue"] if len(searches) == 1 else ["Real venue", "Alias venue"]
        return social.SocialPlaceMentions(
            mentions=[social.SocialPlaceMention(name=n, post_index=1) for n in names]
        )

    async def verify(tool, args, **kwargs):
        queried.append(args.query)
        return PlaceSearchOutput(
            matches=[]
            if args.query == "Rejected venue"
            else [
                PlaceMatch(
                    place_id="same-real-place",
                    display_name="Real venue",
                    lat=35,
                    lng=139,
                    primary_type="cafe",
                    types=["cafe"],
                )
            ]
        )

    monkeypatch.setattr(social, "_search_platform", search)
    monkeypatch.setattr(social, "extract_post_places", extract)
    monkeypatch.setattr(social, "run_tool", verify)
    verification = social.CityVerification(trip=trip, city=city, budget=4)
    state = await social.mine_city(
        destination="Tokyo",
        destination_local_name=None,
        interests=[],
        target_candidates=2,
        reel_target=2,
        verification=verification,
        max_searches=6,
    )
    await verification.update(state, final=True)
    assert len(searches) > 1
    assert queried.count("Rejected venue") == 1
    assert verification.attempts <= 4
    assert state.verified_reels == 1
    assert len(verification.candidates(state)) == 1
    assert state.stop_reason.value != "target_reached"


def test_low_verification_yield_can_use_remaining_ceiling_without_exceeding_it():
    from datetime import date

    from syncinerary.agents.gather.social import CityVerification
    from syncinerary.domain.models import Trip
    from syncinerary.tools.places import ResolvedCity

    trip = Trip(
        destination="Tokyo", days=2, start_date=date(2026, 10, 1), end_date=date(2026, 10, 2)
    )
    city = ResolvedCity(query="Tokyo", place_id="city", name="Tokyo", lat=35, lng=139, radius_km=25)
    verification = CityVerification(trip=trip, city=city, budget=3, ceiling=5)
    verification.matches = {"failed1": None, "failed2": None, "failed3": None}
    state = initialize_social_search_state(destination="Tokyo", reel_target=2)
    verification.refresh(state)
    assert verification.budget == 5
    assert not state.verification_exhausted
    verification.matches.update({"failed4": None, "failed5": None})
    verification.refresh(state)
    assert state.verification_exhausted
    assert verification.budget == 5


def test_only_a_full_productive_page_is_paginated():
    from syncinerary.agents.gather.social_search import search_page

    state = initialize_social_search_state(destination="Tokyo")
    intent = SearchIntent(platform=SocialPlatform.INSTAGRAM, intent_type=SearchIntentType.FOOD)
    update_search_state(
        state,
        intent=intent,
        query="Tokyo cafes",
        outcome=SearchOutcome(raw_results_count=20, new_unique_places_count=4),
    )
    assert search_page(state, intent.broadened(), "Tokyo food") == ("Tokyo cafes", 1)
    thin = initialize_social_search_state(destination="Tokyo")
    update_search_state(
        thin,
        intent=intent,
        query="Tokyo cafes",
        outcome=SearchOutcome(raw_results_count=3, new_unique_places_count=1),
    )
    assert search_page(thin, intent.broadened(), "Tokyo food") == ("Tokyo food", 0)


def test_instagram_english_searches_use_short_intent_queries():
    from syncinerary.tools.fetch.social import build_discovery_query

    queries = [
        build_discovery_query(
            SearchIntent(platform=SocialPlatform.INSTAGRAM, intent_type=kind), destination="Sapporo"
        )
        for kind in SearchIntentType
    ]
    assert queries == ["Sapporo sightseeing", "Sapporo restaurants", "Sapporo hidden gems"]
