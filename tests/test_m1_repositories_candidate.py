"""M1-2b: candidate place, vote and badge repositories against real Postgres."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from syncinerary.domain.models import (
    BadgeType,
    CandidateBadge,
    CandidatePlace,
    CandidateType,
    Source,
    Traveler,
    Trip,
    Vote,
    VoteSignal,
)
from syncinerary.store.repositories import (
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    TravelerRepository,
    TripRepository,
    VoteRepository,
)


async def _trip(session) -> Trip:
    return await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )


def _place(trip_id, name: str, kind: CandidateType = CandidateType.ATTRACTION) -> CandidatePlace:
    return CandidatePlace(
        trip_id=trip_id,
        type=kind,
        name_canonical=name,
        lat=43.06,
        lng=141.35,
        category="temple",
    )


async def test_candidate_round_trips_with_every_field(session):
    trip = await _trip(session)
    repo = CandidatePlaceRepository(session)

    place = CandidatePlace(
        trip_id=trip.id,
        type=CandidateType.FOOD,
        name_canonical="Sapporo Ramen Yokocho",
        name_original_lang="さっぽろラーメン横丁",
        lat=43.0554,
        lng=141.3540,
        address="Minami 5 Nishi 3, Chuo-ku, Sapporo",
        area="Susukino",
        hours_by_weekday={"mon": [[11, 23]], "tue": [[11, 23]]},
        price_tier=2,
        duration_estimate_min=45,
        dietary_tags=["vegetarian_option"],
        weather_dependent=False,
        reservation_required=False,
        fatigue_cost=1,
        category="ramen",
        enrichment={"why_loved": "dense alley of tiny counters"},
        trending_signals={"mentions": 12},
    )
    saved = await repo.add(place)
    fetched = await repo.get(saved.id)

    assert fetched is not None
    assert fetched.name_original_lang == "さっぽろラーメン横丁"
    assert fetched.hours_by_weekday == {"mon": [[11, 23]], "tue": [[11, 23]]}
    assert fetched.dietary_tags == ["vegetarian_option"]
    assert fetched.enrichment == {"why_loved": "dense alley of tiny counters"}
    assert fetched.lat == 43.0554


async def test_sources_survive_the_jsonb_round_trip(session):
    """§8.4: one place mentioned by three sources keeps all three entries."""
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    repo = CandidatePlaceRepository(session)

    place = _place(trip.id, "Otaru Canal")
    place.sources = [
        Source(type="backbone", score=0.75, articles_count=12),
        Source(type="buzz", score=0.62, sources_count=4),
        Source(type="personal", subtype="user_paste", by=traveler.id, via="instagram_link"),
    ]
    saved = await repo.add(place)
    fetched = await repo.get(saved.id)

    assert fetched is not None
    assert [s.type for s in fetched.sources] == ["backbone", "buzz", "personal"]
    assert fetched.sources[0].articles_count == 12
    # The traveler uuid went into JSONB as a string and must come back a UUID.
    assert fetched.sources[2].by == traveler.id


async def test_lodging_is_gathered_but_kept_out_of_the_swipe_deck(session):
    """CLAUDE.md §8.6: lodging is solver-driven, never swiped."""
    trip = await _trip(session)
    repo = CandidatePlaceRepository(session)
    await repo.add_many(
        [
            _place(trip.id, "Mount Moiwa", CandidateType.ATTRACTION),
            _place(trip.id, "Nijo Market", CandidateType.FOOD),
            _place(trip.id, "JR Tower Hotel", CandidateType.LODGING),
        ]
    )

    assert len(await repo.list_for_trip(trip.id)) == 3
    swipeable = await repo.list_swipeable(trip.id)
    assert {c.name_canonical for c in swipeable} == {"Mount Moiwa", "Nijo Market"}
    assert len(await repo.list_by_type(trip.id, CandidateType.LODGING)) == 1


async def test_list_by_ids_preserves_caller_order(session):
    """The shortlist is ordered (§7) and SQL makes no promise for IN."""
    trip = await _trip(session)
    repo = CandidatePlaceRepository(session)
    saved = await repo.add_many([_place(trip.id, n) for n in ("Aaa", "Bbb", "Ccc", "Ddd")])

    wanted = [saved[3].id, saved[0].id, saved[2].id]
    got = await repo.list_by_ids(wanted)
    assert [c.id for c in got] == wanted


async def test_list_by_ids_is_empty_for_empty_input(session):
    assert await CandidatePlaceRepository(session).list_by_ids([]) == []


async def test_add_many_writes_the_whole_pool(session):
    trip = await _trip(session)
    repo = CandidatePlaceRepository(session)
    await repo.add_many([_place(trip.id, f"Place {i}") for i in range(40)])
    assert await repo.count_for_trip(trip.id) == 40


async def test_revoting_replaces_rather_than_duplicates(session):
    """A traveler who revisits a card must not count twice in §10.1."""
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    place = await CandidatePlaceRepository(session).add(_place(trip.id, "Mount Moiwa"))
    repo = VoteRepository(session)

    first = await repo.upsert(
        Vote(candidate_id=place.id, traveler_id=traveler.id, signal=VoteSignal.LIKE)
    )
    second = await repo.upsert(
        Vote(candidate_id=place.id, traveler_id=traveler.id, signal=VoteSignal.DISLIKE)
    )

    votes = await repo.list_for_candidate(place.id)
    assert len(votes) == 1
    assert votes[0].signal is VoteSignal.DISLIKE
    # Identity is preserved: the row keeps the id it was first written with.
    assert votes[0].id == first.id
    assert second.id == first.id


async def test_note_and_parsed_note_round_trip(session):
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    place = await CandidatePlaceRepository(session).add(_place(trip.id, "Nijo Market"))
    repo = VoteRepository(session)

    saved = await repo.upsert(
        Vote(
            candidate_id=place.id,
            traveler_id=traveler.id,
            signal=VoteSignal.LIKE_WITH_NOTE,
            note_text="I can grab a convenience store meal",
            note_parsed={"self_handles_meal": True, "alternative": "convenience_store"},
        )
    )
    fetched = await repo.list_for_candidate(place.id)
    assert fetched[0].id == saved.id
    assert fetched[0].note_text == "I can grab a convenience store meal"
    assert fetched[0].note_parsed == {
        "self_handles_meal": True,
        "alternative": "convenience_store",
    }


async def test_note_parsed_stays_null_for_a_plain_like(session):
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    place = await CandidatePlaceRepository(session).add(_place(trip.id, "Mount Moiwa"))
    repo = VoteRepository(session)

    await repo.upsert(
        Vote(candidate_id=place.id, traveler_id=traveler.id, signal=VoteSignal.LIKE)
    )
    vote = (await repo.list_for_candidate(place.id))[0]
    assert vote.note_text is None
    assert vote.note_parsed is None


async def test_votes_for_a_trip_join_through_candidates(session):
    """Vote has no trip_id of its own (§7)."""
    trip_a = await _trip(session)
    trip_b = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip_a.id, name="Ana"))
    other = await TravelerRepository(session).add(Traveler(trip_id=trip_b.id, name="Bo"))
    places = CandidatePlaceRepository(session)
    repo = VoteRepository(session)

    place_a = await places.add(_place(trip_a.id, "Mount Moiwa"))
    place_b = await places.add(_place(trip_b.id, "Otaru Canal"))
    await repo.upsert(
        Vote(candidate_id=place_a.id, traveler_id=traveler.id, signal=VoteSignal.LIKE)
    )
    await repo.upsert(Vote(candidate_id=place_b.id, traveler_id=other.id, signal=VoteSignal.LIKE))

    for_a = await repo.list_for_trip(trip_a.id)
    assert len(for_a) == 1
    assert for_a[0].candidate_id == place_a.id


async def test_two_travelers_vote_independently_on_one_card(session):
    trip = await _trip(session)
    travelers = TravelerRepository(session)
    ana = await travelers.add(Traveler(trip_id=trip.id, name="Ana"))
    bo = await travelers.add(Traveler(trip_id=trip.id, name="Bo"))
    place = await CandidatePlaceRepository(session).add(_place(trip.id, "Mount Moiwa"))
    repo = VoteRepository(session)

    await repo.upsert(Vote(candidate_id=place.id, traveler_id=ana.id, signal=VoteSignal.LIKE))
    await repo.upsert(Vote(candidate_id=place.id, traveler_id=bo.id, signal=VoteSignal.DISLIKE))

    assert len(await repo.list_for_candidate(place.id)) == 2
    assert len(await repo.list_for_traveler(ana.id)) == 1


async def test_badges_are_scoped_to_one_traveler(session):
    """§9.1: a traveler sees their own badges, never anyone else's."""
    trip = await _trip(session)
    travelers = TravelerRepository(session)
    ana = await travelers.add(Traveler(trip_id=trip.id, name="Ana"))
    bo = await travelers.add(Traveler(trip_id=trip.id, name="Bo"))
    place = await CandidatePlaceRepository(session).add(
        _place(trip.id, "Nijo Market", CandidateType.FOOD)
    )
    repo = CandidateBadgeRepository(session)

    await repo.add(
        CandidateBadge(
            candidate_id=place.id,
            traveler_id=ana.id,
            badge_type=BadgeType.WARNING,
            badge_text="Seafood-heavy, you marked vegetarian",
            reasoning="Ana's profile lists a vegetarian dietary constraint.",
        )
    )
    await repo.add(
        CandidateBadge(
            candidate_id=place.id,
            traveler_id=bo.id,
            badge_type=BadgeType.CONFIRM,
            badge_text="Matches your interest in seafood markets",
            reasoning="Bo listed seafood markets as an interest.",
        )
    )

    assert len(await repo.list_for_candidate(place.id)) == 2

    ana_badges = await repo.list_for_traveler_on_trip(ana.id)
    assert len(ana_badges) == 1
    assert ana_badges[0].badge_type is BadgeType.WARNING
    assert "vegetarian" in ana_badges[0].badge_text


async def test_deleting_a_candidate_cascades_to_its_votes(session):
    trip = await _trip(session)
    traveler = await TravelerRepository(session).add(Traveler(trip_id=trip.id, name="Ana"))
    places = CandidatePlaceRepository(session)
    place = await places.add(_place(trip.id, "Mount Moiwa"))
    votes = VoteRepository(session)
    await votes.upsert(
        Vote(candidate_id=place.id, traveler_id=traveler.id, signal=VoteSignal.LIKE)
    )

    assert await places.delete(place.id) == 1
    await session.flush()
    assert await votes.list_for_candidate(place.id) == []


async def test_get_returns_none_for_unknown_candidate(session):
    assert await CandidatePlaceRepository(session).get(uuid4()) is None
