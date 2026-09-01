"""M6 rescue discovery stays local, open, and inside hard constraints."""
from __future__ import annotations

from datetime import date, time

from syncinerary.agents.rescue_alternatives import (
    AlternativeSearchRequest,
    GooglePlacesAlternativeProvider,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
    Trip,
)
from syncinerary.harness import ToolDefinition
from syncinerary.tools.places import (
    PlaceMatch,
    PlaceSearchInput,
    PlaceSearchOutput,
    ResolvedCity,
)


async def test_google_rescue_search_keeps_only_nearby_open_hard_constraint_matches():
    city = ResolvedCity(
        query="Sapporo",
        place_id="sapporo",
        name="Sapporo",
        lat=43.0618,
        lng=141.3545,
        radius_km=18,
        country="Japan",
        country_code="JP",
    )
    trip = Trip(
        destination="Sapporo",
        cities=["Sapporo"],
        country="Japan",
        resolved_cities=[city.model_dump(mode="json")],
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        days=1,
    )
    anchor = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.FOOD,
        name_canonical="Original lunch",
        lat=43.062,
        lng=141.355,
    )
    captured: list[PlaceSearchInput] = []

    async def search(value: PlaceSearchInput) -> PlaceSearchOutput:
        captured.append(value)
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="nearby-vegan",
                    display_name="Nearby vegan cafe",
                    lat=43.063,
                    lng=141.356,
                    primary_type="vegan_restaurant",
                    types=["restaurant", "vegan_restaurant"],
                    hours_by_weekday={"tue": [[9, 18]]},
                ),
                PlaceMatch(
                    place_id="known-conflict",
                    display_name="Nearby steak house",
                    lat=43.064,
                    lng=141.357,
                    primary_type="steak_house",
                    types=["restaurant", "steak_house"],
                    hours_by_weekday={"tue": [[9, 18]]},
                ),
                PlaceMatch(
                    place_id="closed",
                    display_name="Closed cafe",
                    lat=43.065,
                    lng=141.358,
                    primary_type="cafe",
                    types=["cafe"],
                    hours_by_weekday={"tue": [[18, 22]]},
                ),
                PlaceMatch(
                    place_id="far-away",
                    display_name="Far away cafe",
                    lat=43.25,
                    lng=141.60,
                    primary_type="cafe",
                    types=["cafe"],
                    hours_by_weekday={"tue": [[9, 18]]},
                ),
            ]
        )

    provider = GooglePlacesAlternativeProvider(
        search_tool=ToolDefinition(
            name="stub_places",
            input_model=PlaceSearchInput,
            output_model=PlaceSearchOutput,
            handler=search,
        )
    )
    candidates = await provider.discover(
        AlternativeSearchRequest(
            trip=trip,
            affected_date=date(2026, 9, 1),
            needed_at=time(12),
            anchors=[anchor],
            constraints=[
                Constraint(
                    trip_id=trip.id,
                    type="dietary",
                    value={"excludes": ["meat"]},
                    priority=1,
                    kind=ConstraintKind.HARD,
                )
            ],
            limit=8,
        )
    )

    assert [candidate.name_canonical for candidate in candidates] == [
        "Nearby vegan cafe"
    ]
    assert captured[0].query == "restaurants near Original lunch"
    assert captured[0].destination == "Sapporo"
    assert captured[0].included_type == "restaurant"
    assert captured[0].location_bias is not None
    assert captured[0].location_bias.radius_m == 12_000
