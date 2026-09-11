from datetime import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from syncinerary.domain.models import CandidatePlace, CandidateType, ItineraryNode


def test_transit_link_has_both_endpoints_and_public_transit_mode():
    from syncinerary.api.itinerary_details import directions_url
    origin = CandidatePlace(trip_id=uuid4(), type=CandidateType.ATTRACTION,
                            name_canonical="A", lat=35, lng=139)
    destination = origin.model_copy(update={"name_canonical": "B", "lat": 35.01})
    params = parse_qs(urlparse(directions_url(origin, destination, "transit_estimated")).query)
    assert params["origin"] == ["35.0,139.0"]
    assert params["destination"] == ["35.01,139.0"]
    assert params["travelmode"] == ["transit"]


def test_meal_options_are_near_a_scheduled_stop_and_never_overlap_transit():
    from syncinerary.api.itinerary_details import meal_breaks_for_day
    from syncinerary.api.schemas import ItineraryStopOut
    place = CandidatePlace(trip_id=uuid4(), type=CandidateType.ATTRACTION,
                           name_canonical="Museum", lat=35, lng=139)
    node = ItineraryNode(version_id=uuid4(), candidate_id=place.id, day=0,
                         start_time=time(10), end_time=time(12))
    stop = ItineraryStopOut.of(node, place)
    breaks = meal_breaks_for_day([stop], {place.id: place}, day_start=480, day_end=1260)
    assert breaks[0].start_time == time(12)
    assert breaks[0].end_time == time(13)
    assert "35.0" in breaks[0].nearby_url
    assert {b.meal for b in breaks} == {"lunch", "dinner"}


def test_bar_is_not_reported_as_dinner_and_custom_cap_is_used():
    from syncinerary.api.itinerary_details import meal_breaks_for_day
    from syncinerary.api.schemas import ItineraryStopOut
    place = CandidatePlace(trip_id=uuid4(), type=CandidateType.FOOD, category="bar",
                           name_canonical="Quiet bar", lat=35, lng=139)
    node = ItineraryNode(version_id=uuid4(), candidate_id=place.id, day=0,
                         start_time=time(18), end_time=time(19))
    stop = ItineraryStopOut.of(node, place)
    assert stop.meal_slot is None
    breaks = meal_breaks_for_day([stop], {place.id: place}, day_start=480, day_end=1260,
                                 duration_cap_minutes=180)
    assert [b.meal for b in breaks] == ["dinner"]
    assert breaks[0].start_time >= time(16)


def test_empty_day_reserves_meals_near_the_destination_city():
    from syncinerary.api.itinerary_details import meal_breaks_for_day
    breaks = meal_breaks_for_day(
        [], {}, day_start=480, day_end=1260, fallback_query="Tokyo",
    )
    assert {item.meal for item in breaks} == {"lunch", "dinner"}
    assert all("Tokyo" in item.nearby_url for item in breaks)
