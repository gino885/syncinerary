"""M4 shortlist editing, must-go marking, and confirmation quorum."""
from __future__ import annotations

from datetime import date

from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ShortlistState,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ShortlistStateRepository,
    TravelerRepository,
    TripRepository,
)


async def _shortlist_scenario(session, *, days: int = 2, traveler_count: int = 3):
    trip = await TripRepository(session).add(
        Trip(
            destination="Sapporo",
            cities=["Sapporo"],
            country="Japan",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, days),
            days=days,
        )
    )
    travelers = [
        await TravelerRepository(session).add(
            Traveler(trip_id=trip.id, name=f"Traveler {index}")
        )
        for index in range(traveler_count)
    ]
    candidates = [
        await CandidatePlaceRepository(session).add(
            CandidatePlace(
                trip_id=trip.id,
                type=CandidateType.ATTRACTION,
                name_canonical=f"Place {index}",
                lat=43.05 + index * 0.001,
                lng=141.35,
            )
        )
        for index in range(5)
    ]
    await ShortlistStateRepository(session).upsert(
        ShortlistState(
            trip_id=trip.id,
            selected_candidate_ids=[candidate.id for candidate in candidates[:3]],
            wishlist_excluded_ids=[candidate.id for candidate in candidates[3:]],
        )
    )
    return trip, travelers, candidates


async def test_editing_shortlist_tracks_removed_and_added_cards(client, session):
    trip, travelers, candidates = await _shortlist_scenario(session)

    response = await client.put(
        f"/trips/{trip.id}/shortlist",
        json={
            "traveler_id": str(travelers[0].id),
            "selected_candidate_ids": [
                str(candidates[0].id),
                str(candidates[2].id),
                str(candidates[3].id),
            ],
            "must_go_candidate_ids": [str(candidates[3].id)],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_candidate_ids"] == [
        str(candidates[0].id),
        str(candidates[2].id),
        str(candidates[3].id),
    ]
    assert body["must_go_candidate_ids"] == [str(candidates[3].id)]
    assert body["wishlist_excluded_ids"] == [
        str(candidates[1].id),
        str(candidates[4].id),
    ]
    assert body["confirmed_by"] == []
    assert body["is_confirmed"] is False


async def test_edit_rejects_must_go_outside_selection_and_over_day_cap(client, session):
    trip, travelers, candidates = await _shortlist_scenario(session, days=2)
    base = {
        "traveler_id": str(travelers[0].id),
        "selected_candidate_ids": [str(candidate.id) for candidate in candidates[:3]],
    }

    outside = await client.put(
        f"/trips/{trip.id}/shortlist",
        json={**base, "must_go_candidate_ids": [str(candidates[4].id)]},
    )
    over_cap = await client.put(
        f"/trips/{trip.id}/shortlist",
        json={
            **base,
            "must_go_candidate_ids": [str(candidate.id) for candidate in candidates[:3]],
        },
    )

    assert outside.status_code == 422
    assert over_cap.status_code == 422


async def test_half_the_group_must_confirm_and_duplicate_confirm_is_idempotent(
    client,
    session,
):
    trip, travelers, _candidates = await _shortlist_scenario(
        session,
        traveler_count=3,
    )

    first = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[0].id)},
    )
    duplicate = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[0].id)},
    )
    second = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[1].id)},
    )

    assert first.status_code == 200
    assert first.json()["confirmations_required"] == 2
    assert first.json()["is_confirmed"] is False
    assert len(duplicate.json()["confirmed_by"]) == 1
    assert second.json()["is_confirmed"] is True
    assert second.json()["confirmed_at"] is not None


async def test_edit_after_confirmation_clears_old_acknowledgments(client, session):
    trip, travelers, candidates = await _shortlist_scenario(
        session,
        traveler_count=1,
    )
    confirmed = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[0].id)},
    )
    assert confirmed.json()["is_confirmed"] is True

    edited = await client.put(
        f"/trips/{trip.id}/shortlist",
        json={
            "traveler_id": str(travelers[0].id),
            "selected_candidate_ids": [
                str(candidates[0].id),
                str(candidates[1].id),
            ],
            "must_go_candidate_ids": [],
        },
    )

    assert edited.json()["confirmed_by"] == []
    assert edited.json()["confirmed_at"] is None
    assert edited.json()["is_confirmed"] is False


async def test_no_op_edit_preserves_another_travelers_confirmation(client, session):
    trip, travelers, candidates = await _shortlist_scenario(
        session,
        traveler_count=3,
    )
    first = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[0].id)},
    )
    assert first.json()["confirmed_by"] == [str(travelers[0].id)]

    unchanged = await client.put(
        f"/trips/{trip.id}/shortlist",
        json={
            "traveler_id": str(travelers[1].id),
            "selected_candidate_ids": [str(candidate.id) for candidate in candidates[:3]],
            "must_go_candidate_ids": [],
        },
    )
    second = await client.post(
        f"/trips/{trip.id}/shortlist/confirm",
        json={"traveler_id": str(travelers[1].id)},
    )

    assert unchanged.json()["confirmed_by"] == [str(travelers[0].id)]
    assert second.json()["is_confirmed"] is True
    assert second.json()["confirmed_by"] == [
        str(travelers[0].id),
        str(travelers[1].id),
    ]
