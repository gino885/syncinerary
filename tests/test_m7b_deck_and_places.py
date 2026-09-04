"""M7b: deck order actually reflects the lanes, and cities are not places."""
from __future__ import annotations

from itertools import pairwise
from uuid import uuid4

from syncinerary.agents.gather.deck import deck_lane, order_deck
from syncinerary.agents.gather.traits import is_visitable_place
from syncinerary.domain.models import CandidatePlace, CandidateType, Source

TRIP = uuid4()


def _card(
    name: str,
    *,
    lane: str | None = None,
    buzz: float | None = None,
    personal: bool = False,
) -> CandidatePlace:
    sources: list[Source] = []
    if personal:
        sources.append(Source(type="personal", subtype="user_paste", by=uuid4()))
    if buzz is not None:
        sources.append(Source(type="buzz", score=buzz, sources_count=1))
    if not sources:
        sources.append(Source(type="discovery", subtype="google_places"))
    return CandidatePlace(
        trip_id=TRIP,
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=43.0,
        lng=141.0,
        sources=sources,
        trending_signals={"selection_lane": lane} if lane else {},
    )


# ----- deck order -----


def test_the_deck_is_not_alphabetical():
    """The bug: order_by name_canonical meant the two-lane selection had no
    effect on anything a traveler actually saw."""
    cards = [
        _card("Zebra Park", buzz=2.0, lane="trending"),
        _card("Apple Cafe", buzz=0.1, lane="trending"),
    ]

    assert [c.name_canonical for c in order_deck(cards)] == [
        "Zebra Park",
        "Apple Cafe",
    ]


def test_for_you_cards_are_spread_rather_than_left_at_the_end():
    """Ordered by evidence alone they would all land behind the fatigue, and
    the lane that exists to carry interest matches would buy nothing."""
    cards = [_card(f"Trend {i}", buzz=3.0 - i * 0.1, lane="trending") for i in range(9)]
    cards += [_card(f"Gem {i}", buzz=0.2, lane="for_you") for i in range(3)]

    ordered = order_deck(cards)
    positions = [
        index
        for index, card in enumerate(ordered)
        if card.name_canonical.startswith("Gem")
    ]

    assert len(positions) == 3
    # Spread, not clumped: the first gem is in the opening third and they do
    # not sit next to each other.
    assert positions[0] < len(ordered) // 3
    assert all(b - a > 1 for a, b in pairwise(positions))


def test_a_travelers_own_attachment_leads():
    """Being asked to vote on the thing you added is the least surprising
    place to start."""
    cards = [
        _card("Big Buzz", buzz=9.0, lane="trending"),
        _card("Mine", personal=True),
    ]

    assert order_deck(cards)[0].name_canonical == "Mine"


def test_the_lane_is_read_from_provenance_not_guessed():
    assert deck_lane(_card("a", personal=True)) == "personal"
    assert deck_lane(_card("b", buzz=1.0, lane="for_you")) == "for_you"
    assert deck_lane(_card("c", buzz=1.0, lane="trending")) == "trending"
    assert deck_lane(_card("d")) == "foundation"


def test_ordering_is_stable_and_total():
    cards = [_card(f"C{i}", buzz=1.0, lane="trending") for i in range(20)]
    cards += [_card(f"F{i}") for i in range(20)]

    once = [c.name_canonical for c in order_deck(cards)]
    twice = [c.name_canonical for c in order_deck(cards)]

    assert once == twice
    assert len(once) == 40, "no card may be dropped or duplicated"
    assert len(set(once)) == 40


def test_an_empty_deck_is_fine():
    assert order_deck([]) == []


# ----- cities are not places -----


def test_a_city_is_not_a_visitable_place():
    """'Sapporo' geocoded, passed the city-boundary check, and became an
    attraction card. That is the bug this guard closes."""
    assert not is_visitable_place("locality", ["locality", "political"])
    assert not is_visitable_place(None, ["administrative_area_level_1", "political"])


def test_a_real_place_tagged_political_still_counts():
    """Parks and museums often carry `political` alongside their real type, so
    a bare membership test would throw away half the deck."""
    assert is_visitable_place("park", ["park", "political"])
    assert is_visitable_place("restaurant", ["restaurant", "food", "point_of_interest"])
    assert is_visitable_place("museum", ["museum", "tourist_attraction"])


def test_an_untyped_place_is_allowed_through():
    """Places sometimes returns nothing useful. Verification already happened
    upstream, so silence is not evidence of a city."""
    assert is_visitable_place(None, [])


# ----- an attachment resolves to the place, not the city it is in -----


async def test_a_caption_naming_a_city_and_a_place_resolves_to_the_place(
    client, monkeypatch
):
    """The walkthrough bug: a TikTok about miso ramen produced a card called
    "Sapporo".

    Two defects met here. The attachment prompt had no rule against cities
    while the social one did, and the resolver took place_mentions[0] and
    nothing else, so a caption yielding ['Sapporo', 'Ramen Alley'] gave the
    card the city. After M7b-2's guard it was worse: the city was rejected and
    the attachment died rather than falling through to the real place.
    """
    from syncinerary.agents.gather import personal as personal_module
    from syncinerary.agents.gather.attachments import ExtractedPlaceMention
    from syncinerary.agents.gather.personal import TextPlaceExtraction
    from syncinerary.tools.places import PlaceMatch

    async def caption(_attachment):
        return {"caption": "Best miso ramen in Sapporo, at Ramen Alley"}

    async def both_names(_text, *, platform=None):
        return TextPlaceExtraction(
            place_mentions=[
                ExtractedPlaceMention(name="Sapporo", evidence="in Sapporo"),
                ExtractedPlaceMention(name="Ramen Alley", evidence="at Ramen Alley"),
            ],
            short_description=None,
        )

    async def lookup(name, _trip):
        if name == "Sapporo":
            return (
                PlaceMatch(
                    place_id="city-sapporo",
                    display_name="Sapporo",
                    lat=43.06,
                    lng=141.35,
                    primary_type="locality",
                    types=["locality", "political"],
                ),
                "Sapporo",
            )
        return (
            PlaceMatch(
                place_id="ChIJ-ramen-alley",
                display_name="Ganso Ramen Yokocho",
                lat=43.055,
                lng=141.353,
                primary_type="ramen_restaurant",
                types=["ramen_restaurant", "restaurant"],
            ),
            "Sapporo",
        )

    monkeypatch.setattr(personal_module, "_read_public_metadata", caption)
    monkeypatch.setattr(personal_module, "extract_place_mentions", both_names)
    monkeypatch.setattr(personal_module, "_find_place_for_trip", lookup)

    created = await client.post(
        "/trips",
        json={
            "cities": ["Sapporo"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.tiktok.com/@creator/video/7459997680383560968",
        },
    )

    assert response.json()["status"] == "ready"
    cards = await client.get(f"/trips/{created.json()['trip']['id']}/candidates")
    names = [c["name_canonical"] for c in cards.json()]
    assert "Ganso Ramen Yokocho" in names
    assert "Sapporo" not in names, "the city must never become a card"


async def test_an_attachment_naming_only_a_city_fails_rather_than_carding_it(
    client, monkeypatch
):
    from syncinerary.agents.gather import personal as personal_module
    from syncinerary.agents.gather.attachments import ExtractedPlaceMention
    from syncinerary.agents.gather.personal import TextPlaceExtraction
    from syncinerary.tools.places import PlaceMatch

    async def caption(_attachment):
        return {"caption": "Sapporo is beautiful"}

    async def city_only(_text, *, platform=None):
        return TextPlaceExtraction(
            place_mentions=[ExtractedPlaceMention(name="Sapporo", evidence="Sapporo")],
            short_description=None,
        )

    async def lookup(_name, _trip):
        return (
            PlaceMatch(
                place_id="city-sapporo",
                display_name="Sapporo",
                lat=43.06,
                lng=141.35,
                primary_type="locality",
                types=["locality", "political"],
            ),
            "Sapporo",
        )

    monkeypatch.setattr(personal_module, "_read_public_metadata", caption)
    monkeypatch.setattr(personal_module, "extract_place_mentions", city_only)
    monkeypatch.setattr(personal_module, "_find_place_for_trip", lookup)

    created = await client.post(
        "/trips",
        json={
            "cities": ["Sapporo"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.tiktok.com/@creator/video/7459997680383560968",
        },
    )

    assert response.json()["status"] == "failed"
    cards = await client.get(f"/trips/{created.json()['trip']['id']}/candidates")
    assert cards.json() == []


def test_the_attachment_prompt_forbids_cities_like_the_social_one_does():
    """These two prompts drifted: the social NER banned cities and the
    attachment one did not, which is the whole bug."""
    from syncinerary.agents.gather.personal import TEXT_EXTRACTION_PROMPT
    from syncinerary.agents.gather.social import NER_PROMPT

    for prompt in (TEXT_EXTRACTION_PROMPT, NER_PROMPT):
        assert "whole cities" in prompt
        assert "Sapporo" in prompt, "the rule needs a concrete example to bite"
