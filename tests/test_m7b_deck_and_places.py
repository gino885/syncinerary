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
