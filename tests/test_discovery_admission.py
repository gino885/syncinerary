from datetime import date

import pytest

from syncinerary.agents.gather.admission import admit_place
from syncinerary.agents.gather.live import discover_candidates
from syncinerary.domain.models import Trip
from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput, ResolvedCity


def place(name, kind="tourist_attraction", **extra):
    return PlaceMatch(
        place_id=name, display_name=name, primary_type=kind, lat=35.68, lng=139.76, **extra
    )


@pytest.mark.parametrize(
    "name,kind,reason",
    [
        ("Tokyo Food", "restaurant", "generic_category_name"),
        ("東京美食", "restaurant", "generic_category_name"),
        ("东京美食", "restaurant", "generic_category_name"),
        ("Kyoto Nightlife", "bar", "generic_category_name"),
        ("Tokyo Night & Light", "tourist_attraction", "event_or_campaign"),
        ("東京五天四夜攻略", "tourist_attraction", "guide_or_collection"),
        ("Example", "mystery_business", "unsupported_place_type"),
        ("Tokyo", "locality", "administrative_area"),
        ("Pinky Tour - Paris", "tourist_attraction", "guide_or_collection"),
    ],
)
def test_rejects_non_places_even_with_provider_type(name, kind, reason):
    decision = admit_place(place(name, kind), destination=name.split()[0])
    assert not decision.accepted
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "name,kind",
    [
        ("Tokyo National Museum", "museum"),
        ("Shinjuku Golden-Gai", "tourist_attraction"),
        ("Tsukiji Outer Market", "market"),
        ("Sushi Dai", "japanese_restaurant"),
        ("Central Park", "park"),
        ("Louvre Museum", "art_museum"),
        ("Nakajima Park", "city_park"),
        ("Hachiko Statue", "sculpture"),
        ("Bukchon Hanok Village", "landmark"),
        ("Shiroi Koibito Park", "amusement_center"),
        ("Pont Alexandre III", "bridge"),
        ("Festival Walk", "shopping_mall"),
    ],
)
def test_specific_places_with_identity_evidence_remain_eligible(name, kind):
    decision = admit_place(
        place(name, kind, hours_by_weekday={"mon": [[9, 18]]}), destination="Tokyo"
    )
    assert decision.accepted
    assert decision.evidence_level == "places_strong"


def test_social_evidence_cannot_override_generic_identity():
    assert not admit_place(
        place("Tokyo Food", "restaurant"), destination="Tokyo", social_evidence=True
    ).accepted
    assert admit_place(
        place("Sushi Dai", "restaurant"), destination="Tokyo", social_evidence=True
    ).accepted
    assert not admit_place(place("Sushi Dai", "restaurant"), destination="Tokyo").accepted


async def test_rejected_attraction_never_seeds_meals_and_small_valid_deck_succeeds(monkeypatch):
    from syncinerary.agents.gather import live

    calls = []

    async def cities(_trip):
        return [
            ResolvedCity(
                query="Tokyo", place_id="tokyo", name="Tokyo", lat=35.68, lng=139.76, radius_km=30
            )
        ]

    async def no_social(*args):
        return []

    async def search(_tool, args, **kwargs):
        calls.append(args.query)
        return PlaceSearchOutput(
            matches=[
                place("Tokyo Night & Light"),
                place("Tokyo Food", "restaurant"),
                place("Tokyo National Museum", "museum", hours_by_weekday={"mon": [[9, 18]]}),
            ]
        )

    monkeypatch.setattr(live, "resolve_trip_cities", cities)
    monkeypatch.setattr(live, "discover_social_candidates", no_social)
    monkeypatch.setattr(live, "run_tool", search)
    trip = Trip(
        destination="Tokyo", days=1, start_date=date(2026, 9, 14), end_date=date(2026, 9, 14)
    )
    deck = await discover_candidates(trip)
    assert [c.name_canonical for c in deck] == ["Tokyo National Museum"]
    assert not any("near Tokyo Night" in q for q in calls)


def test_admission_release_gate_catches_invalid_cards_and_false_rejections():
    import json
    from pathlib import Path

    from syncinerary.eval.discovery import evaluate_admission

    fixtures = json.loads(Path("syncinerary/eval/discovery_regressions.json").read_text())
    report = evaluate_admission(fixtures)
    assert report["invalid_card_rate"] == 0
    assert report["false_rejections"] == 0
    # A mislabeled admission must fail the gate even if all other cases pass.
    valid = next(row for row in fixtures if row["expected_accepted"])
    assert evaluate_admission([{**valid, "expected_accepted": False}])["invalid_card_rate"] == 1
