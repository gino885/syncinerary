"""M5 candidate effort and weather traits."""

from syncinerary.agents.gather.traits import fatigue_cost, is_weather_dependent
from syncinerary.domain.models import CandidateType


def test_meals_are_low_fatigue_even_when_the_place_type_is_generic():
    assert fatigue_cost(CandidateType.FOOD, "restaurant", []) == 1


def test_parks_are_low_fatigue_and_weather_dependent():
    assert fatigue_cost(CandidateType.ATTRACTION, "park", []) == 1
    assert is_weather_dependent("park", []) is True


def test_hikes_are_high_fatigue_and_weather_dependent():
    assert fatigue_cost(CandidateType.ATTRACTION, "hiking_area", []) == 3
    assert is_weather_dependent("hiking_area", []) is True


def test_unknown_attractions_keep_the_medium_default():
    assert fatigue_cost(CandidateType.ATTRACTION, "cultural_landmark", []) == 2
    assert is_weather_dependent("cultural_landmark", []) is False
