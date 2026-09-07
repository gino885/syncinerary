"""M7g: the three languages this product runs on, kept apart.

Display language, output language, and search language are different things,
and the failure mode worth testing is any two of them merging. A Traditional
Chinese UI must not turn RedNote's Simplified search vocabulary into
Traditional, and a trip's narrative must not depend on whose phone asked for
it.
"""
from __future__ import annotations

from datetime import date

import pytest

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


@pytest.mark.parametrize("locale", ["en", "zh-Hant", "zh-Hans", "ja"])
def test_search_vocabulary_never_follows_the_output_language(locale):
    """The one that would quietly break retrieval.

    RedNote is searched in Simplified Chinese whoever is reading the result,
    and the English platforms stay English. build_discovery_query takes no
    locale at all, which is the enforcement: there is nothing to pass.
    """
    rednote = build_discovery_query(
        SearchIntent(
            platform=SocialPlatform.REDNOTE, intent_type=SearchIntentType.FOOD
        ),
        destination="Sapporo",
        destination_localized="札幌",
    )
    tiktok = build_discovery_query(
        SearchIntent(
            platform=SocialPlatform.TIKTOK, intent_type=SearchIntentType.FOOD
        ),
        destination="Sapporo",
    )

    assert rednote == "札幌 美食推荐 餐厅 咖啡店 探店"
    assert tiktok == "Sapporo best local food restaurants cafes must eat"


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
