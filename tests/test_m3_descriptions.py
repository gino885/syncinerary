"""Short, source-aware copy for itinerary stops."""
from datetime import time
from uuid import uuid4

from syncinerary.api.schemas import ItineraryStopOut
from syncinerary.domain.models import CandidatePlace, ItineraryNode, Source


def _node(candidate_id):
    return ItineraryNode(
        version_id=uuid4(),
        candidate_id=candidate_id,
        day=0,
        start_time=time(9),
        end_time=time(10),
    )


def test_itinerary_stop_uses_the_social_source_description():
    candidate = CandidatePlace(
        trip_id=uuid4(),
        type="attraction",
        name_canonical="Otaru Canal",
        lat=43.1987,
        lng=140.9947,
        sources=[Source(type="personal", subtype="user_paste", via="tiktok_link")],
        enrichment={
            "platform": "tiktok",
            "source_description": "Blue-hour reflections make this canal especially cinematic.",
        },
    )

    stop = ItineraryStopOut.of(_node(candidate.id), candidate)

    assert stop.description == (
        "Blue-hour reflections make this canal especially cinematic."
    )
    assert stop.description_source == "TikTok"


def test_itinerary_stop_builds_short_copy_from_google_place_details():
    candidate = CandidatePlace(
        trip_id=uuid4(),
        type="food",
        name_canonical="Soup Curry GARAKU",
        lat=43.0576,
        lng=141.3544,
        area="Sapporo Chuo",
        category="restaurant",
        enrichment={"google_place_id": "ChIJ-garaku"},
    )

    stop = ItineraryStopOut.of(_node(candidate.id), candidate)

    assert stop.description == "A local food stop worth arriving hungry for."
    assert stop.description_source == "Google Places"


def test_itinerary_stop_keeps_generated_copy_brief():
    candidate = CandidatePlace(
        trip_id=uuid4(),
        type="attraction",
        name_canonical="A Place",
        lat=43.0,
        lng=141.0,
        sources=[Source(type="backbone")],
        enrichment={"source_description": "word " * 100},
    )

    stop = ItineraryStopOut.of(_node(candidate.id), candidate)

    assert stop.description is not None
    assert len(stop.description) <= 120
    assert not stop.description.endswith(" ")
