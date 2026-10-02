"""Shared preparation survives edits, re-opening, and untrusted source input."""

from datetime import date, time
from uuid import uuid4

import pytest

from syncinerary.api.schemas import ItineraryStopOut
from syncinerary.domain.models import CandidatePlace, CandidateType, ItineraryNode, Traveler, Trip
from syncinerary.store.repositories import TravelerRepository, TripRepository


def candidate(**updates):
    return CandidatePlace(
        trip_id=uuid4(),
        name_canonical="Cafe",
        type=CandidateType.FOOD,
        lat=35.0,
        lng=139.0,
        **updates,
    )


def stop_for(place):
    return ItineraryStopOut.of(
        ItineraryNode(
            version_id=uuid4(),
            candidate_id=place.id,
            day=0,
            order_in_day=0,
            start_time=time(12),
            end_time=time(13),
        ),
        place,
    )


def test_social_tip_is_concise_and_attributed():
    place = candidate(
        enrichment={
            "social_posts": [
                {
                    "url": "https://www.instagram.com/reel/abc123/",
                    "platform": "instagram",
                    "highlight": "Order the sesame noodles. The decor is lovely.",
                }
            ]
        }
    )
    tip = stop_for(place).social_tip
    assert tip.text == "Order the sesame noodles."
    assert tip.kind == "food"
    assert tip.url == "https://www.instagram.com/reel/abc123/"


@pytest.mark.parametrize("highlight", ["Beautiful and amazing!", "", "Book " + "x" * 250])
def test_no_filler_or_truncated_advice(highlight):
    place = candidate(
        enrichment={
            "social_posts": [
                {
                    "url": "https://www.instagram.com/reel/abc123/",
                    "platform": "instagram",
                    "highlight": highlight,
                }
            ]
        }
    )
    assert stop_for(place).social_tip is None


def test_chinese_tip_keeps_original_language():
    place = candidate(
        enrichment={
            "social_posts": [
                {
                    "url": "https://www.instagram.com/reel/abc123/",
                    "platform": "instagram",
                    "highlight": "推薦點海鹽布丁。店內很漂亮。",
                }
            ]
        }
    )
    assert stop_for(place).social_tip.text == "推薦點海鹽布丁。"


def test_no_tip_from_google_or_untrusted_url():
    place = candidate(
        enrichment={
            "source_description": "Order the noodles.",
            "social_posts": [{"url": "https://evil.invalid/", "highlight": "Order the noodles."}],
        }
    )
    assert stop_for(place).social_tip is None


async def setup_trip(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Tokyo, Atami",
            cities=["Tokyo", "Atami"],
            city_days=[2, 1],
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            days=3,
        )
    )
    member = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Gino"))
    return trip, member


async def test_checklist_edits_completion_and_deletion_survive_refresh(client, session):
    trip, member = await setup_trip(session)
    base = f"/trips/{trip.id}/checklist"
    body = {"traveler_id": str(member.id)}
    initial = await client.post(base + "/prepare", json=body)
    assert initial.status_code == 200, initial.text
    items = initial.json()
    assert any("Tokyo" in x["title"] and "Atami" in x["title"] for x in items)
    item = items[0]
    updated = await client.put(
        base + f"/{item['id']}",
        json={
            **body,
            "revision": item["revision"],
            "title": "Train tickets saved",
            "notes": "Confirmation in my email",
            "completed": True,
        },
    )
    assert updated.status_code == 200, updated.text
    stale = await client.put(
        base + f"/{item['id']}",
        json={
            **body,
            "revision": item["revision"],
            "title": "Old edit",
            "notes": "",
            "completed": False,
        },
    )
    assert stale.status_code == 409
    second = items[1]
    deleted = await client.delete(
        base + f"/{second['id']}", params={**body, "revision": second["revision"]}
    )
    assert deleted.status_code == 200
    refreshed = (await client.post(base + "/prepare", json=body)).json()
    saved = next(x for x in refreshed if x["id"] == item["id"])
    assert saved["completed"] and saved["title"] == "Train tickets saved"
    assert not any(x["id"] == second["id"] for x in refreshed)
    added = await client.post(
        base, json={**body, "title": "Bring camera", "notes": "Charge battery"}
    )
    assert added.status_code == 201
    assert added.json()["source_key"] is None


async def test_checklist_rejects_nonmember_and_blank_title(client, session):
    trip, member = await setup_trip(session)
    base = f"/trips/{trip.id}/checklist"
    denied = await client.post(base + "/prepare", json={"traveler_id": str(uuid4())})
    assert denied.status_code == 403
    bad = await client.post(base, json={"traveler_id": str(member.id), "title": "   "})
    assert bad.status_code == 422


def test_ticket_suggestions_are_localized_and_only_for_relevant_venues():
    from syncinerary.domain.checklist_suggestions import suggestions

    trip = Trip(
        destination="東京",
        cities=["東京"],
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        days=1,
        output_locale="zh-Hant",
    )
    museum = candidate(category="museum").model_copy(
        update={"name_canonical": "美術館", "type": CandidateType.ATTRACTION}
    )
    park = candidate(category="park")
    food = candidate(reservation_required=True).model_copy(update={"name_canonical": "餐廳"})
    items = suggestions(trip, [museum, park, food])
    assert [i.title for i in items] == [
        "確認住宿預訂",
        "確認門票／預約：美術館",
        "確認餐廳訂位：餐廳",
    ]
    assert all(i.completed is False for i in items)


async def test_checklist_rejects_other_trips_item_and_bound_account(client, session):
    from syncinerary.domain.models import Account
    from syncinerary.store.repositories import AccountRepository

    trip, member = await setup_trip(session)
    other, other_member = await setup_trip(session)
    items = (
        await client.post(
            f"/trips/{trip.id}/checklist/prepare", json={"traveler_id": str(member.id)}
        )
    ).json()
    denied = await client.put(
        f"/trips/{other.id}/checklist/{items[0]['id']}",
        json={
            "traveler_id": str(other_member.id),
            "title": "Cross-trip edit",
            "revision": 1,
            "completed": True,
        },
    )
    assert denied.status_code == 409
    account = await AccountRepository(session).add(
        Account(display_name="Bound", handle=uuid4().hex)
    )
    bound = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Bound", account_id=account.id)
    )
    denied = await client.post(
        f"/trips/{trip.id}/checklist/prepare", json={"traveler_id": str(bound.id)}
    )
    assert denied.status_code == 403


def test_truncated_source_is_not_completed_as_advice():
    place = candidate(
        enrichment={
            "social_posts": [
                {
                    "url": "https://www.instagram.com/reel/abc123/",
                    "platform": "instagram",
                    "highlight": "Book tickets only if...",
                }
            ]
        }
    )
    assert stop_for(place).social_tip is None


def test_tip_preserves_decimal_times_and_qualifications():
    place = candidate(
        enrichment={
            "social_posts": [
                {
                    "url": "https://www.instagram.com/reel/abc123/",
                    "platform": "instagram",
                    "highlight": "Arrive at 5.30 p.m. before the last admission. Beautiful views.",
                }
            ]
        }
    )
    assert stop_for(place).social_tip.text == "Arrive at 5.30 p.m. before the last admission."
