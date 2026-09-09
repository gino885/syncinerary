"""The shipped iOS catalog stays complete for Traditional Chinese."""
from __future__ import annotations

import json
from pathlib import Path

IOS_SOURCE = Path(__file__).parents[1] / "ios" / "Syncinerary"
CATALOG = IOS_SOURCE / "Localizable.xcstrings"


def _strings() -> dict[str, object]:
    return json.loads(CATALOG.read_text())["strings"]


def test_every_catalog_entry_has_a_traditional_chinese_translation():
    missing = [
        key
        for key, entry in _strings().items()
        if not entry.get("localizations", {})
        .get("zh-Hant", {})
        .get("stringUnit", {})
        .get("value")
    ]

    assert missing == []


def test_computed_ui_wording_is_editable_in_the_catalog():
    required_keys = {
        "%@ by %@",
        "%@, opens Google Maps",
        "%lld of %lld confirmations",
        "%lld of %lld left",
        "%lld travellers",
        "%lldd · %@",
        "1 traveller",
        "approx. public transit",
        "approx. walk",
        "Breakfast",
        "Card %lld of %lld",
        "Could not add that place.",
        "Could not join. Try again.",
        "Could not load the thread.",
        "Could not make an invite code. Try again.",
        "Could not reach the trip server. Check the connection and try again.",
        "Dinner",
        "Dietary details are unverified. Confirm with the restaurant.",
        "Fits the updated day.",
        "Google Places · %@",
        "Late start",
        "Lunch",
        "Message not sent. Try again.",
        "No cards",
        "No trip found for that code.",
        "Place closed",
        "public transit",
        "Reservation cancelled",
        "Room availability is not verified. Confirm dates with the hotel before booking.",
        "Someone",
        "That invite code doesn't match a trip. Ask for a new one.",
        "That one isn't in this trip's cities",
        "The server returned status %lld.",
        "This %@ post doesn't name a place",
        "Transit delay",
        "Trip change",
        "Try another name",
        "Warning: %@",
        "Weather change",
        "What place is it?",
        "%@ won't open to us",
    }

    assert sorted(required_keys - _strings().keys()) == []


def test_every_preference_tag_has_editable_chinese_wording_in_the_catalog():
    source = (IOS_SOURCE / "Models" / "PreferenceCatalog.swift").read_text()
    keys = [
        line.split('title: "', 1)[1].split('"', 1)[0]
        for line in source.splitlines()
        if 'title: "' in line
    ]
    catalog = _strings()

    assert keys
    assert all(
        catalog[key]["localizations"]["zh-Hant"]["stringUnit"]["value"]
        for key in keys
    )


def test_preference_views_render_localized_titles_but_send_stable_values():
    button = (
        IOS_SOURCE / "Features" / "TripCreate" / "PreferenceTagButton.swift"
    ).read_text()
    selection = (IOS_SOURCE / "Models" / "PreferenceSelection.swift").read_text()

    assert "Text(tag.localizedTitle)" in button
    assert "$0.localizedTitle" in selection
    assert "values(in:" in selection
