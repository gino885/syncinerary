"""The iOS planning flow keeps preferences and swipe corrections usable."""
from pathlib import Path

IOS_SOURCE = Path(__file__).parents[1] / "ios" / "Syncinerary"


def _source(relative_path: str) -> str:
    return (IOS_SOURCE / relative_path).read_text()


def test_trip_setup_opens_a_tag_picker_instead_of_comma_separated_fields():
    source = _source("Features/TripCreate/TripCreateView.swift")

    assert "PreferencePickerSheet" in source
    assert 'TextField("Interests:' not in source
    assert 'TextField("Foods to avoid:' not in source


def test_swipe_flow_exposes_previous_on_the_deck_and_completion_screen():
    swipe = _source("Features/Swipe/SwipeView.swift")
    header = _source("Features/Swipe/SwipeProgressHeader.swift")
    complete = _source("Features/Swipe/VotingCompleteView.swift")

    assert "onPrevious: showPrevious" in swipe
    assert 'Button("Previous"' in header
    assert ".disabled(!canGoBack)" in header
    assert 'Button("Review last card"' in complete


def test_swipe_reaction_is_one_charm_not_a_screen_wide_particle_burst():
    swipe = _source("Features/Swipe/SwipeView.swift")
    complete = _source("Features/Swipe/VotingCompleteView.swift")
    decision = _source("Features/Swipe/SwipeDecision.swift")

    assert "DecisionCharmView" in swipe
    assert "SymbolBurstView" not in swipe
    assert "SymbolBurstView" not in complete
    assert "reactionSymbol" in decision
    assert "burstSymbols" not in decision
