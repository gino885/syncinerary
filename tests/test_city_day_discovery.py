"""City time budgets and user-language searches define the candidate deck."""

from datetime import date
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from syncinerary.api.schemas import TripCreateRequest
from syncinerary.domain.models import SocialPlatform, Trip
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    BraveSocialSearchInput,
    SearchIntent,
    SearchIntentType,
    build_discovery_query,
    make_brave_social_search_tool,
)


def trip(**changes):
    return Trip(**{
        "destination": "Tokyo / Atami / Kamakura",
        "cities": ["Tokyo", "Atami", "Kamakura"],
        "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 5),
        "days": 5, "city_days": [3, 1, 1], **changes,
    })


def test_city_days_define_candidate_and_meal_demand():
    from syncinerary.domain.city_plan import city_day_counts

    assert city_day_counts(trip()) == [3, 1, 1]
    assert city_day_counts(trip(city_days=[], priority_city_index=1)) == [2, 2, 1]


@pytest.mark.parametrize("days", [[3, 1], [4, 1, 1], [3, 2, 0], [3, -1, 3], [3, True, 1]])
def test_invalid_city_day_allocations_are_rejected(days):
    with pytest.raises(ValidationError):
        trip(city_days=days)


async def test_api_persists_and_returns_city_days(client, session):
    from syncinerary.store.repositories import TripRepository
    from tests.test_m7a_group_api import _sign_in
    signed = await _sign_in(client, display_name="Leader", handle="citydays")
    client.headers["Authorization"] = f"Bearer {signed['token']}"
    response = await client.post("/trips", json={
        "cities": ["Tokyo", "Atami", "Kamakura"], "country": "Japan",
        "start_date": "2026-10-01", "end_date": "2026-10-05", "creator_name": "Leader",
        "city_days": [3, 1, 1], "priority_city_index": 0,
    })
    assert response.status_code == 201, response.text
    saved = response.json()["trip"]
    assert saved["city_days"] == [3, 1, 1]
    assert saved["priority_city_index"] == 0
    stored = await TripRepository(session).get(UUID(saved["id"]))
    assert stored.city_days == [3, 1, 1]


def test_api_rejects_allocation_for_wrong_city_list():
    with pytest.raises(ValidationError):
        TripCreateRequest(cities=["Tokyo", "Atami"], country="Japan", city_days=[3, 1, 1],
                          creator_name="Leader", start_date="2026-10-01", end_date="2026-10-05")


def test_api_rejects_duplicate_cities_after_whitespace_normalization():
    with pytest.raises(ValidationError):
        TripCreateRequest(cities=["New York", "New  York"], country="United States",
                          city_days=[1, 1], creator_name="Leader",
                          start_date="2026-10-01", end_date="2026-10-02")


def test_scheduler_keeps_user_city_days_even_when_tokyo_has_more_candidates():
    from syncinerary.agents.solver.stage1_days import _allowed_days_by_city, assign_days_by_city
    from tests.test_reels_discovery import card

    cards = [card(i, reel=True) for i in range(20)]
    cards[-2].enrichment["city"] = "Atami"
    cards[-1].enrichment["city"] = "Kamakura"
    itinerary = trip(city_days=[1, 3, 1])
    allowed = _allowed_days_by_city(cards, itinerary)
    assert allowed[cards[0].id] == [0]
    assert allowed[cards[-2].id] == [1, 2, 3]
    assert allowed[cards[-1].id] == [4]
    buckets = assign_days_by_city(cards, itinerary.days, itinerary.cities, itinerary.city_days)
    assert len(buckets) == 5
    assert cards[-2] in [card for bucket in buckets[1:4] for card in bucket]
    assert cards[-1] in buckets[4]


def test_combined_ratio_passes_despite_low_reel_share_in_small_city():
    from syncinerary.agents.gather.source_mix import source_mix_report
    from tests.test_reels_discovery import card

    cards = [card(i, reel=i < 20 or i >= 32) for i in range(40)]
    for i, c in enumerate(cards):
        c.enrichment["city"] = "Tokyo" if i < 24 else "Atami" if i < 32 else "Kamakura"
    report = source_mix_report(cards)
    assert report.visible.reel_share == pytest.approx(28 / 40)
    assert report.visible.target_met
    assert not report.by_city["Atami"].target_met


def test_city_selection_caps_tokyo_and_keeps_meals_in_every_city():
    from syncinerary.agents.gather.live import select_trip_pool
    from tests.test_reels_discovery import card

    cards = []
    for offset, city in enumerate(trip().cities):
        for i in range(40):
            c = card(offset * 100 + i, reel=city != "Atami" and i < 30)
            c.enrichment["city"] = city
            c.type = "food" if i % 3 == 0 else "attraction"
            # Assignment does not validate/coerce the enum.
            from syncinerary.domain.models import CandidateType
            c.type = CandidateType(c.type)
            cards.append(c)
    result = select_trip_pool(cards, trip(), trip().cities)
    assert len(result) == 40
    for city, days in zip(trip().cities, [3, 1, 1], strict=True):
        group = [c for c in result if c.enrichment["city"] == city]
        assert len(group) == days * 8
        assert sum(c.type.value == "food" for c in group) >= days * 2


def test_english_rednote_query_does_not_switch_to_chinese():
    query = build_discovery_query(
        SearchIntent(platform=SocialPlatform.REDNOTE, intent_type=SearchIntentType.FOOD),
        destination="Atami", destination_localized="热海", output_locale="en",
    )
    assert "Atami" in query
    assert not any("\u3400" <= c <= "\u9fff" for c in query)


@pytest.mark.parametrize("language", ["en", "zh-hant", "zh-hans"])
async def test_brave_explicitly_requests_the_selected_language(language):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"web": {"results": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await run_tool(make_brave_social_search_tool(client=client, api_key="test"),
                       BraveSocialSearchInput(platform=SocialPlatform.INSTAGRAM,
                                              query="test", search_lang=language))
    assert seen[0].url.params["search_lang"] == language
    assert seen[0].url.params["country"] == "ALL"


@pytest.mark.parametrize("small_city_reels, expected_tokyo_target", [(5, 19), (8, 18)])
async def test_trip_reel_shortfall_moves_to_larger_city_without_increasing_small_city_cards(
    monkeypatch, small_city_reels, expected_tokyo_target,
):
    from syncinerary.agents.gather import social
    from syncinerary.agents.gather.social_search import initialize_social_search_state
    from syncinerary.tools.places import ResolvedCity
    from tests.test_reels_discovery import card

    cities = [ResolvedCity(name=n, query=n, place_id=n, lat=35 + i, lng=139, radius_km=25)
              for i, n in enumerate(trip().cities)]
    supplied = {}
    observed = {}
    for i, city in enumerate(cities):
        supplied[city.name] = []
        for j in range(small_city_reels if city.name == "Kamakura" else 0):
            c = card(i * 100 + j, reel=True)
            c.enrichment["city"] = city.name
            supplied[city.name].append(c)
        if city.name == "Kamakura":
            from syncinerary.domain.models import CandidateType
            for j in range(2):
                c = card(900 + j, reel=False)
                c.type = CandidateType.FOOD
                c.enrichment["city"] = city.name
                supplied[city.name].append(c)

    async def mine(**kwargs):
        observed[kwargs["destination"]] = (kwargs["target_candidates"], kwargs["reel_target"])
        return initialize_social_search_state(destination=kwargs["destination"], target_candidates=kwargs["target_candidates"])

    async def update(self, state, **kwargs):
        self.refresh(state)

    async def forbidden_translation(*args, **kwargs):
        raise AssertionError("English discovery must not translate cities to Chinese")

    monkeypatch.setattr(social, "mine_city", mine)
    monkeypatch.setattr(social.CityVerification, "update", update)
    monkeypatch.setattr(social.CityVerification, "candidates", lambda self, state: supplied[self.city.name])
    monkeypatch.setattr(social, "translate_destination_to_mandarin", forbidden_translation)
    await social.discover_social_candidates(trip(priority_city_index=0), [], cities)
    assert observed["Atami"][0] == 8
    assert observed["Kamakura"][0] == 8
    # The smaller city's non-Reel meals reserve two of its eight cards.
    assert observed["Tokyo"] == (24, expected_tokyo_target)
