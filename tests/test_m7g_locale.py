"""M7g: locale follows the group creator across the shared trip.

The creator's display language chooses the language of shared trip output and
social discovery. The agent's instructions stay in English, and RedNote keeps
the Simplified Chinese vocabulary that retrieves its note corpus.
"""
from __future__ import annotations

from datetime import date

import pytest

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather.social import discover_social_candidates
from syncinerary.agents.gather.social_search import initialize_social_search_state
from syncinerary.config.locales import (
    DEFAULT_OUTPUT_LOCALE,
    SUPPORTED_OUTPUT_LOCALES,
    language_name,
    normalize_output_locale,
)
from syncinerary.domain.models import SocialPlatform, Trip
from syncinerary.tools.fetch.social import (
    SearchIntent,
    SearchIntentType,
    build_discovery_query,
)
from syncinerary.tools.places import ResolvedCity


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("zh-Hant", "zh-Hant"),
        ("zh-Hant-TW", "zh-Hant"),
        ("zh-Hans", "zh-Hans"),
        ("en-GB", "en"),
        ("fr", DEFAULT_OUTPUT_LOCALE),
        (None, DEFAULT_OUTPUT_LOCALE),
        ("", DEFAULT_OUTPUT_LOCALE),
    ],
)
def test_a_locale_resolves_to_something_the_server_can_write(given, expected):
    assert normalize_output_locale(given) == expected


def test_a_bare_chinese_tag_does_not_guess_a_script():
    """zh alone does not say Traditional or Simplified, and picking one for a
    reader who wanted the other is worse than falling back."""
    assert normalize_output_locale("zh") == DEFAULT_OUTPUT_LOCALE


def test_traditional_and_simplified_are_not_interchangeable():
    assert SUPPORTED_OUTPUT_LOCALES["zh-Hant"] != SUPPORTED_OUTPUT_LOCALES["zh-Hans"]
    assert "繁體" in language_name("zh-Hant")
    assert "简体" in language_name("zh-Hans")


def test_a_trip_carries_its_own_output_language():
    """Persisted on the trip, because the group reads one narrative and it
    cannot depend on which traveler's device triggered the plan."""
    trip = Trip(
        destination="Sapporo",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 4),
        days=4,
        output_locale="zh-Hant",
    )

    assert trip.output_locale == "zh-Hant"
    assert Trip(
        destination="Sapporo",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 4),
        days=4,
    ).output_locale == "en"


@pytest.mark.parametrize("locale", ["zh-Hant", "zh-Hans"])
def test_chinese_creator_uses_chinese_social_searches(locale):
    """Chinese queries retrieve Chinese posts and video captions."""
    rednote = build_discovery_query(
        SearchIntent(
            platform=SocialPlatform.REDNOTE, intent_type=SearchIntentType.FOOD
        ),
        destination="Sapporo",
        destination_localized="札幌",
        output_locale=locale,
    )
    tiktok = build_discovery_query(
        SearchIntent(
            platform=SocialPlatform.TIKTOK, intent_type=SearchIntentType.FOOD
        ),
        destination="Sapporo",
        destination_localized="札幌",
        output_locale=locale,
    )

    assert rednote == "札幌 美食推荐 餐厅 咖啡店 探店"
    assert tiktok == "札幌 美食推荐 餐厅 咖啡店 探店"


def test_english_creator_keeps_english_searches_off_rednote():
    tiktok = build_discovery_query(
        SearchIntent(
            platform=SocialPlatform.TIKTOK, intent_type=SearchIntentType.FOOD
        ),
        destination="Sapporo",
        destination_localized="札幌",
        output_locale="en",
    )

    assert tiktok == "Sapporo best local food restaurants cafes must eat"


async def test_discovery_uses_the_creator_language_saved_on_the_trip(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_translate(destination: str, **_kwargs) -> str:
        return "札幌"

    async def fake_mine_city(**kwargs):
        seen.update(kwargs)
        return initialize_social_search_state(
            destination=kwargs["destination"],
            destination_local_name=kwargs["destination_local_name"],
            interests=kwargs["interests"],
            target_candidates=kwargs["target_candidates"],
        )

    monkeypatch.setattr(
        social_module, "translate_destination_to_mandarin", fake_translate
    )
    monkeypatch.setattr(social_module, "mine_city", fake_mine_city)

    trip = Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 4),
        days=4,
        output_locale="zh-Hant",
    )
    city = ResolvedCity(
        query="Sapporo",
        name="Sapporo",
        place_id="sapporo",
        country="Japan",
        lat=43.0618,
        lng=141.3545,
        radius_km=25,
    )

    await discover_social_candidates(trip, [], [city])

    assert seen["output_locale"] == "zh-Hant"


def test_place_names_keep_their_canonical_and_original_forms():
    """Localizing display must not overwrite the name a traveler will need to
    show a driver or read on a sign."""
    from syncinerary.domain.models import CandidatePlace, CandidateType

    place = CandidatePlace(
        trip_id=Trip(
            destination="Sapporo",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 4),
            days=4,
        ).id,
        type=CandidateType.ATTRACTION,
        name_canonical="Shiroi Koibito Park",
        name_original_lang="白い恋人パーク",
        lat=43.08,
        lng=141.28,
    )

    assert place.name_canonical == "Shiroi Koibito Park"
    assert place.name_original_lang == "白い恋人パーク"
