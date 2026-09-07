"""M7f: social discovery as a bounded adaptive search over three intents.

Discovery asks three different questions of the social corpus. PLACES and FOOD
ask what a destination is broadly known for and stock the Trending pool;
HIDDEN_GEMS asks for the less obvious places and stocks the For You pool. The
loop opens by asking all three, then spends what is left of a hard eight-search
ceiling on whichever lane is short.

These cover the two properties that matter: later searches depend on what
earlier ones found, and the two lanes are fed by different searches rather than
being one pool sorted two ways.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import httpx
import pytest

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather.social import MinedPlace, mine_city
from syncinerary.agents.gather.social_search import (
    SearchOutcome,
    SearchStats,
    SearchYield,
    SocialSearchState,
    StopReason,
    initialize_social_search_state,
    lane_deficits,
    plan_next_search,
    platform_priority,
    platforms_by_priority,
    update_search_state,
)
from syncinerary.config.gather import (
    MAX_ATTEMPTS_PER_SEMANTIC_INTENT,
    MAX_SEARCHES_PER_CITY,
)
from syncinerary.domain.models import SocialPlatform, Traveler, Trip
from syncinerary.tools.fetch.social import (
    OPENING_SEQUENCE,
    DiscoveredSocialURL,
    QuerySpecificity,
    SearchIntent,
    SearchIntentType,
    normalize_social_url,
)
from syncinerary.tools.places import ResolvedCity

INSTAGRAM = SocialPlatform.INSTAGRAM
TIKTOK = SocialPlatform.TIKTOK
REDNOTE = SocialPlatform.REDNOTE
PLACES = SearchIntentType.PLACES
FOOD = SearchIntentType.FOOD
GEMS = SearchIntentType.HIDDEN_GEMS


# ----- harness -------------------------------------------------------------


def _post(index: int, *, title: str = "A post about somewhere") -> DiscoveredSocialURL:
    return DiscoveredSocialURL(
        reference=normalize_social_url(
            f"https://www.tiktok.com/@creator/video/{7000000000 + index}"
        ),
        query="q",
        rank=1,
        title=title,
        description="A snippet the search index already publishes.",
    )


#: A search the index answered with posts that name no venue. Different from
#: an empty list, which is a search the index had nothing for at all.
NO_NAMES = object()


class FakeSocialWorld:
    """A destination whose searches can be scripted per iteration.

    The script is handed the intent as well as the platform, because what a
    destination has to say about food is not what it has to say about its
    quieter corners, and the whole point of the loop is to notice that.
    """

    def __init__(self, script, *, interests_of=None):
        self.script = script
        self.interests_of = interests_of or (lambda name: [])
        self.searches: list[tuple[SocialPlatform, str]] = []
        self.intents: list[tuple[SocialPlatform, SearchIntentType]] = []
        self.mentions_by_query: dict[str, list[str]] = {}
        self._intent_by_query: dict[str, SearchIntentType] = {}

    def bind(self, plan_next_search):
        """Record the planner's choice so the script can key on the intent."""

        def planned(state):
            intent = plan_next_search(state)
            self._pending = intent
            return intent

        return planned

    async def search(self, platform, *, query, destination):
        intent_type = self._pending.intent_type
        self._intent_by_query[query] = intent_type
        index = len(self.searches)
        self.searches.append((platform, query))
        self.intents.append((platform, intent_type))
        outcome = self.script(index, platform, intent_type)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is NO_NAMES:
            self.mentions_by_query[query] = []
            return [_post(index * 100 + n) for n in range(4)]
        self.mentions_by_query[query] = list(outcome)
        return [_post(index * 100 + n) for n in range(len(outcome))]

    async def extract(
        self, posts, *, platform, destination, interests=None, query=None, client=None
    ):
        from syncinerary.agents.gather.social import (
            SocialPlaceMention,
            SocialPlaceMentions,
        )

        names = self.mentions_by_query.get(query, [])
        return SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(
                    name=name,
                    post_index=min(number, len(posts)),
                    matched_interests=self.interests_of(name),
                )
                for number, name in enumerate(names, start=1)
            ]
        )

    def install(self, monkeypatch):
        monkeypatch.setattr(
            social_module, "plan_next_search", self.bind(social_module.plan_next_search)
        )
        monkeypatch.setattr(social_module, "_search_platform", self.search)
        monkeypatch.setattr(social_module, "extract_post_places", self.extract)
        return self

    def intents_of_type(self, intent_type: SearchIntentType) -> int:
        return sum(1 for _, found in self.intents if found is intent_type)


async def _run(world, monkeypatch, **kwargs) -> SocialSearchState:
    world.install(monkeypatch)
    options = {
        "destination": "Sapporo",
        "destination_local_name": "札幌",
        "interests": [],
        "target_candidates": 100,
    }
    options.update(kwargs)
    return await mine_city(**options)


def _places(*names: str) -> list[str]:
    return list(names)


def _state(**kwargs) -> SocialSearchState:
    options = {
        "destination": "Sapporo",
        "destination_local_name": "札幌",
        "target_candidates": 30,
    }
    options.update(kwargs)
    return initialize_social_search_state(**options)


class _FakePlace:
    """Stands in for a MinedPlace: only its provenance is read here."""

    def __init__(self, *intents: SearchIntentType) -> None:
        self.intent_types = [intent.value for intent in intents]


def _record(state, intent_type, *, platform=INSTAGRAM, new=4, **counts):
    outcome = SearchOutcome(
        raw_results_count=counts.get("raw", 20),
        readable_posts_count=counts.get("raw", 20),
        extracted_mentions_count=counts.get("mentions", new),
        resolved_places_count=counts.get("resolved", new),
        new_unique_places_count=new,
    )
    for index in range(new):
        state.discovered_places[f"{intent_type.value}-{len(state.discovered_places)}-{index}"] = (
            _FakePlace(intent_type)
        )
    update_search_state(
        state,
        intent=SearchIntent(platform=platform, intent_type=intent_type),
        query=f"{platform.value} {intent_type.value}",
        outcome=outcome,
    )
    return state


# ----- the opening sequence ------------------------------------------------


def test_the_first_three_searches_establish_all_three_sources():
    """Reacting after one search would mean deciding For You is short before
    ever having asked for a hidden gem."""
    state = _state()
    chosen: list[SearchIntentType] = []

    for _ in range(3):
        intent = plan_next_search(state)
        assert intent is not None
        chosen.append(intent.intent_type)
        _record(state, intent.intent_type, platform=intent.platform, new=4)

    assert chosen == list(OPENING_SEQUENCE)
    assert chosen == [PLACES, FOOD, GEMS]


def test_the_opening_searches_spread_across_platforms():
    """Three platforms probed in three searches, so the first adaptive
    decision has evidence about each rather than about one."""
    state = _state()
    platforms = []
    for _ in range(3):
        intent = plan_next_search(state)
        platforms.append(intent.platform)
        _record(state, intent.intent_type, platform=intent.platform, new=4)

    assert len(set(platforms)) == 3


async def test_a_live_run_opens_places_food_then_hidden_gems(monkeypatch):
    world = FakeSocialWorld(
        lambda index, platform, intent: _places(f"{intent.value}-{index}")
    )
    await _run(world, monkeypatch, target_candidates=3)

    assert [intent for _, intent in world.intents][:3] == [PLACES, FOOD, GEMS]


# ----- adapting to lane supply --------------------------------------------


def test_a_weak_for_you_lane_pulls_the_next_search_to_hidden_gems():
    state = _state(target_candidates=30)
    _record(state, PLACES, platform=INSTAGRAM, new=9)
    _record(state, FOOD, platform=TIKTOK, new=7)
    _record(state, GEMS, platform=REDNOTE, new=2)

    intent = plan_next_search(state)

    assert intent is not None
    assert intent.intent_type is GEMS, "trending is healthy, For You is not"
    assert intent.platform is not REDNOTE, "and RedNote has already been asked"


def test_a_weak_trending_lane_pulls_the_next_search_to_the_weaker_of_its_two():
    state = _state(target_candidates=30)
    _record(state, PLACES, platform=INSTAGRAM, new=1)
    _record(state, FOOD, platform=TIKTOK, new=9)
    _record(state, GEMS, platform=REDNOTE, new=9)

    intent = plan_next_search(state)

    assert intent is not None
    assert intent.intent_type is PLACES, "places is the shortfall, not food"


def test_the_lane_choice_follows_the_deficit_not_the_raw_count():
    """For You's target is smaller, so a fraction rather than a count is what
    stops the bigger lane permanently outranking it."""
    state = _state(target_candidates=30)
    _record(state, PLACES, platform=INSTAGRAM, new=10)
    _record(state, FOOD, platform=TIKTOK, new=10)
    _record(state, GEMS, platform=REDNOTE, new=1)

    worst = lane_deficits(state)[0]

    assert worst[1] == "for_you"


async def test_later_searches_depend_on_what_earlier_ones_found(monkeypatch):
    """The proof that the loop is adaptive rather than a precomputed list."""

    def script(index, platform, intent):
        if intent is GEMS:
            return _places(*[f"Quiet {index}-{n}" for n in range(6)])
        return _places(f"Busy {index}")

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=30)

    ordered = [intent for _, intent in world.intents]
    assert ordered[:3] == [PLACES, FOOD, GEMS]
    # Trending stayed thin and For You filled, so the run swung back to the
    # broad intents rather than asking for more gems.
    assert set(ordered[3:]) <= {PLACES, FOOD}
    assert state.lane_supply[1] >= 6


# ----- lane separation survives the loop ----------------------------------


async def test_the_lanes_are_stocked_by_different_searches(monkeypatch):
    def script(index, platform, intent):
        prefix = {PLACES: "Sight", FOOD: "Diner", GEMS: "Quiet"}[intent]
        return _places(*[f"{prefix} {index}-{n}" for n in range(3)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=100)

    gems = [
        place
        for place in state.discovered_places.values()
        if place.is_hidden_gem
    ]
    broad = [
        place
        for place in state.discovered_places.values()
        if not place.is_hidden_gem
    ]
    assert gems and broad
    assert all(place.name.startswith("Quiet") for place in gems)
    assert not any(place.name.startswith("Quiet") for place in broad)


async def test_a_place_both_kinds_of_search_found_keeps_both_provenances(monkeypatch):
    def script(index, platform, intent):
        return _places("Nijo Market")

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=100)

    place = state.discovered_places["nijo market"]
    assert set(place.intent_types) >= {PLACES.value, GEMS.value}
    assert place.is_hidden_gem is True


# ----- the ceiling and the cost -------------------------------------------


async def test_a_productive_city_never_exceeds_the_search_ceiling(monkeypatch):
    def script(index, platform, intent):
        return _places(*[f"Place {index}-{n}" for n in range(5)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=10_000)

    assert state.searches_used == MAX_SEARCHES_PER_CITY
    assert state.stop_reason is StopReason.SEARCH_BUDGET_REACHED
    assert len(world.searches) <= MAX_SEARCHES_PER_CITY


@pytest.mark.parametrize("interest_count", [2, 20])
async def test_provider_cost_does_not_scale_with_the_interest_count(
    monkeypatch, interest_count
):
    """Interests rank the For You lane; they never create a search of their
    own, which is what keeps cost flat as a group lists more of them."""

    def script(index, platform, intent):
        return _places(*[f"Place {index}-{n}" for n in range(5)])

    world = FakeSocialWorld(script)
    await _run(
        world,
        monkeypatch,
        interests=[f"interest_{n}" for n in range(interest_count)],
        target_candidates=10_000,
    )

    assert len(world.searches) <= MAX_SEARCHES_PER_CITY
    assert {intent for _, intent in world.intents} <= set(OPENING_SEQUENCE)


async def test_stops_early_when_both_lanes_reach_their_targets(monkeypatch):
    def script(index, platform, intent):
        return _places(*[f"{intent.value} {index}-{n}" for n in range(6)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=12)

    assert state.stop_reason is StopReason.TARGET_REACHED
    assert state.searches_used < MAX_SEARCHES_PER_CITY


async def test_stops_after_repeated_low_yield_before_the_ceiling(monkeypatch):
    known = _places("A", "B", "C", "D")

    def script(index, platform, intent):
        return known if index == 0 else known[:2]

    world = FakeSocialWorld(script)
    state = await _run(
        world, monkeypatch, target_candidates=10_000, max_consecutive_low_yield=2
    )

    assert state.stop_reason is StopReason.LOW_YIELD
    assert state.searches_used < MAX_SEARCHES_PER_CITY


# ----- failure recovery ----------------------------------------------------


async def test_one_empty_search_does_not_end_discovery(monkeypatch):
    def script(index, platform, intent):
        return [] if index == 0 else _places(*[f"Place {index}-{n}" for n in range(6)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=12)

    assert state.searches_used >= 2
    assert state.discovered_count >= 6


def test_an_empty_intent_is_retried_with_fewer_words():
    state = _state()
    _record(state, PLACES, platform=INSTAGRAM, new=3)
    _record(state, FOOD, platform=TIKTOK, new=3)
    update_search_state(
        state,
        intent=SearchIntent(platform=REDNOTE, intent_type=GEMS),
        query="札幌 小众 宝藏",
        outcome=SearchOutcome(),
    )

    intent = plan_next_search(state)

    assert intent is not None
    assert intent.intent_type is GEMS
    assert intent.platform is REDNOTE
    assert intent.specificity is QuerySpecificity.NORMAL, "broader, not narrower"


async def test_retries_for_one_question_are_bounded(monkeypatch):
    """Three wordings of a question the corpus cannot answer is two too many."""

    def script(index, platform, intent):
        return [] if intent is GEMS else _places(f"Place {index}")

    world = FakeSocialWorld(script)
    await _run(world, monkeypatch, target_candidates=10_000)

    attempts = Counter(world.intents)
    gem_attempts = {
        platform: count
        for (platform, intent), count in attempts.items()
        if intent is GEMS
    }
    assert gem_attempts
    assert max(gem_attempts.values()) <= MAX_ATTEMPTS_PER_SEMANTIC_INTENT


async def test_a_platform_switch_recovers_an_intent(monkeypatch):
    """One platform having nothing about hidden gems says nothing about the
    others, so the question moves rather than being abandoned."""
    barren: SocialPlatform | None = None
    asked: list[SocialPlatform] = []

    def script(index, platform, intent):
        nonlocal barren
        if intent is not GEMS:
            return _places(*[f"Place {index}-{n}" for n in range(4)])
        if barren is None:
            barren = platform
        asked.append(platform)
        if platform is barren:
            return []
        return _places(*[f"Quiet {index}-{n}" for n in range(5)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=10_000)

    assert len(set(asked)) > 1, "the question moved to another platform"
    assert state.lane_supply[1] > 0, "and the lane was filled"


def test_posts_that_name_no_venue_move_to_venue_bearing_content():
    state = _state()
    _record(state, PLACES, platform=INSTAGRAM, new=3)
    update_search_state(
        state,
        intent=SearchIntent(platform=TIKTOK, intent_type=FOOD),
        query="tiktok food",
        outcome=SearchOutcome(raw_results_count=20, readable_posts_count=20),
    )

    intent = plan_next_search(state)

    assert intent is not None
    assert intent.intent_type in {FOOD, GEMS}


async def test_the_loop_records_where_each_search_actually_failed(monkeypatch):
    def script(index, platform, intent):
        if index == 0:
            return []
        if index == 1:
            return NO_NAMES
        return _places(*[f"Place {index}-{n}" for n in range(6)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=6)

    kinds = [action.outcome.yield_type for action in state.searched_queries]
    assert kinds[0] is SearchYield.NO_SEARCH_RESULTS
    assert kinds[1] is SearchYield.NO_MENTIONS
    assert state.searched_queries[1].outcome.raw_results_count > 0


async def test_a_provider_error_does_not_look_like_exhaustion(monkeypatch):
    def script(index, platform, intent):
        if index == 0:
            return httpx.ConnectTimeout("brave timed out")
        return _places(*[f"Place {index}-{n}" for n in range(7)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=7)

    assert state.searched_queries[0].outcome.yield_type is SearchYield.PROVIDER_ERROR
    assert state.consecutive_low_yield_searches == 0
    assert state.discovered_count >= 7


async def test_a_provider_that_never_answers_ends_the_run_early(monkeypatch):
    def script(index, platform, intent):
        return httpx.ConnectTimeout("brave timed out")

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch)

    assert state.stop_reason is StopReason.PROVIDER_UNAVAILABLE
    assert state.searches_used < MAX_SEARCHES_PER_CITY


# ----- per-intent statistics ----------------------------------------------


def test_a_platform_is_judged_per_intent_not_on_its_average():
    """A platform can be strong for food and useless for hidden gems, and an
    average hides exactly that."""
    state = _state()
    state.platform_intent_stats[(TIKTOK, FOOD)] = SearchStats(
        searches=2, new_unique_places=16
    )
    state.platform_intent_stats[(TIKTOK, GEMS)] = SearchStats(
        searches=2, new_unique_places=0
    )
    state.platform_intent_stats[(INSTAGRAM, GEMS)] = SearchStats(
        searches=1, new_unique_places=4
    )

    # Written off for gems, and only for gems. An averaged platform score
    # could not hold both of these at once.
    written_off_for_gems = platform_priority(state, TIKTOK, GEMS)[0]
    written_off_for_food = platform_priority(state, TIKTOK, FOOD)[0]

    assert written_off_for_gems == 1
    assert written_off_for_food == 0
    assert platforms_by_priority(state, intent_type=GEMS)[-1] is TIKTOK


async def test_statistics_are_kept_per_intent(monkeypatch):
    def script(index, platform, intent):
        count = {PLACES: 5, FOOD: 3, GEMS: 1}[intent]
        return _places(*[f"{intent.value} {index}-{n}" for n in range(count)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=10_000)

    assert state.intent_stats[PLACES].new_unique_places > (
        state.intent_stats[GEMS].new_unique_places
    )
    assert sum(stats.searches for stats in state.intent_stats.values()) == (
        state.searches_used
    )
    assert state.intent_stats[GEMS].duplicate_rate == 0.0


# ----- RedNote language ----------------------------------------------------


async def test_every_rednote_query_uses_the_mandarin_destination(monkeypatch):
    def script(index, platform, intent):
        return _places(f"Place {index}")

    world = FakeSocialWorld(script)
    await _run(world, monkeypatch, target_candidates=10_000)

    rednote = [query for platform, query in world.searches if platform is REDNOTE]
    assert rednote
    assert all(query.startswith("札幌 ") for query in rednote)
    assert not any("Sapporo" in query for query in rednote)


async def test_rednote_drops_out_without_a_mandarin_name(monkeypatch):
    def script(index, platform, intent):
        return _places(f"Place {index}")

    world = FakeSocialWorld(script)
    await _run(
        world, monkeypatch, destination_local_name=None, target_candidates=10_000
    )

    assert REDNOTE not in {platform for platform, _ in world.searches}


# ----- caching -------------------------------------------------------------


async def test_a_repeated_gather_adds_no_provider_requests():
    """Cache identity is the query, so a variable number of iterations still
    reuses whatever an earlier run already paid for."""
    from syncinerary.harness import run_tool
    from syncinerary.tools.fetch.social import (
        BraveSocialSearchInput,
        make_brave_social_search_tool,
    )

    class FakeCache:
        def __init__(self):
            self.values: dict[str, str] = {}

        async def get(self, key):
            return self.values.get(key)

        async def set(self, key, value, *, ex):
            self.values[key] = value

    calls = 0
    cache = FakeCache()

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"web": {"results": []}}, request=request)

    plan = [
        (INSTAGRAM, "Sapporo must visit places things to do attractions sightseeing"),
        (TIKTOK, "Sapporo best local food restaurants cafes must eat"),
        (REDNOTE, "札幌 小众 宝藏"),
    ]

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool = make_brave_social_search_tool(
            client=client, api_key="test-key", cache=cache
        )
        for platform, query in plan:
            await run_tool(tool, BraveSocialSearchInput(platform=platform, query=query))
        after_first = calls
        for platform, query in reversed(plan):
            await run_tool(tool, BraveSocialSearchInput(platform=platform, query=query))

    assert after_first == len(plan)
    assert calls == after_first


# ----- the whole loop, end to end -----------------------------------------


def _trip() -> Trip:
    return Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        resolved_cities=[
            ResolvedCity(
                query="Sapporo",
                place_id="city-sapporo",
                name="Sapporo",
                lat=43.0618,
                lng=141.3545,
                radius_km=25,
                country="Japan",
                country_code="JP",
            ).model_dump(mode="json")
        ],
        timezone="Asia/Tokyo",
        start_date=date(2026, 9, 27),
        end_date=date(2026, 10, 1),
        days=5,
    )


async def test_the_deck_carries_the_lane_and_the_searches_that_found_it(monkeypatch):
    trip = _trip()
    travelers = [
        Traveler(trip_id=trip.id, name="Gino", profile={"interests": ["coffee"]})
    ]

    def script(index, platform, intent):
        if intent is GEMS:
            return _places("Quiet Kissaten")
        return _places(f"Busy {index}")

    world = FakeSocialWorld(
        script,
        interests_of=lambda name: ["coffee"] if name == "Quiet Kissaten" else [],
    )
    world.install(monkeypatch)

    async def fake_translate(destination, *, client=None):
        return "札幌"

    async def fake_run_tool(_tool, arguments, **_kwargs):
        from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput

        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=f"ChIJ-{arguments.query}",
                    display_name=arguments.query,
                    lat=43.06,
                    lng=141.35,
                    primary_type="cafe",
                    types=["cafe"],
                )
            ]
        )

    monkeypatch.setattr(
        social_module, "translate_destination_to_mandarin", fake_translate
    )
    monkeypatch.setattr(social_module, "run_tool", fake_run_tool)

    candidates = await social_module.discover_social_candidates(trip, travelers)

    by_name = {c.name_canonical: c for c in candidates}
    gem = by_name["Quiet Kissaten"]
    assert gem.trending_signals["selection_lane"] == "for_you"
    assert "hidden_gems" in gem.trending_signals["discovery_intents"]
    busy = next(c for name, c in by_name.items() if name.startswith("Busy"))
    assert busy.trending_signals["selection_lane"] == "trending"
    assert "hidden_gems" not in busy.trending_signals["discovery_intents"]


async def test_mining_stays_the_supply_stage_and_verification_stays_after_it(
    monkeypatch,
):
    """Google verification is deliberately outside the loop, where the two-lane
    selection decides which mined names are worth paying for."""

    def script(index, platform, intent):
        return _places(*[f"Place {index}-{n}" for n in range(4)])

    world = FakeSocialWorld(script)
    state = await _run(world, monkeypatch, target_candidates=10_000)

    assert all(
        isinstance(place, MinedPlace) for place in state.discovered_places.values()
    )
    assert state.discovered_count > 0
