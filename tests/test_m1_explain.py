"""M1-8: the itinerary explainer.

No test here calls the real API. The client is a stub, which keeps the suite
free, offline and deterministic, and lets us assert on the exact request shape,
which is the part most likely to break: SYNC_LLM_MODEL rejects several
parameters that older models accept.
"""
from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from syncinerary.agents import explain as explain_module
from syncinerary.agents.explain import (
    ExplainUnavailable,
    build_prompt,
    explain_node,
    generate_narrative,
)
from syncinerary.config.explain import EXPLAIN_EFFORT, EXPLAIN_MAX_TOKENS
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    ItineraryNode,
    ItineraryVersion,
    Trip,
    TripState,
    WishlistNotPlaced,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    TripRepository,
    WishlistNotPlacedRepository,
)


class StubMessages:
    """Records the request and returns a canned response."""

    def __init__(self, text: str = "A pleasant five days.", stop_reason: str = "end_turn"):
        self.calls: list[dict] = []
        self._text = text
        self._stop_reason = stop_reason

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self._stop_reason,
            content=[SimpleNamespace(type="text", text=self._text)],
        )


class ExplodingMessages:
    async def create(self, **kwargs):
        raise RuntimeError("connection reset")


def _trip(days: int = 2) -> Trip:
    return Trip(
        destination="Hokkaido",
        start_date=date(2026, 5, 21),
        end_date=date(2026, 5, 22),
        days=days,
    )


def _place(name: str, area: str | None = None, category: str | None = None) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=43.06,
        lng=141.35,
        area=area,
        category=category,
    )


def _node(candidate_id, day: int, start: time, end: time, transit: int = 0) -> ItineraryNode:
    return ItineraryNode(
        version_id=uuid4(),
        candidate_id=candidate_id,
        day=day,
        start_time=start,
        end_time=end,
        transit_from_prev_min=transit,
    )


# ----- prompt -----


def test_prompt_lists_every_stop_with_its_time():
    trip = _trip()
    canal = _place("Otaru Canal", area="Otaru", category="historic")
    park = _place("Odori Park", area="Sapporo Chuo", category="park")
    nodes = [
        _node(canal.id, 0, time(9, 0), time(10, 30)),
        _node(park.id, 0, time(11, 15), time(12, 15), transit=45),
    ]

    prompt = build_prompt(trip, nodes, [canal, park])

    assert "Otaru Canal" in prompt
    assert "Odori Park" in prompt
    assert "09:00-10:30" in prompt
    assert "11:15-12:15" in prompt
    assert "45 min" in prompt


def test_prompt_carries_the_weekday_because_hours_depend_on_it():
    prompt = build_prompt(_trip(), [_node(uuid4(), 0, time(9, 0), time(10, 0))], [])
    # 21 May 2026 is a Thursday.
    assert "Thursday" in prompt
    assert "2026-05-21" in prompt


def test_prompt_groups_by_day_and_orders_by_time():
    trip = _trip()
    a, b, c = _place("Aaa"), _place("Bbb"), _place("Ccc")
    nodes = [
        _node(c.id, 1, time(9, 0), time(10, 0)),
        _node(b.id, 0, time(14, 0), time(15, 0)),
        _node(a.id, 0, time(9, 0), time(10, 0)),
    ]

    prompt = build_prompt(trip, nodes, [a, b, c])

    assert prompt.index("Day 1") < prompt.index("Day 2")
    assert prompt.index("Aaa") < prompt.index("Bbb") < prompt.index("Ccc")


def test_prompt_omits_transit_for_the_first_stop_of_a_day():
    trip = _trip()
    place = _place("Odori Park")
    prompt = build_prompt(trip, [_node(place.id, 0, time(9, 0), time(10, 0))], [place])
    assert "min from the previous stop" not in prompt


def test_prompt_is_byte_identical_across_runs():
    """F2 replay compares explainer output; a wobbling prompt would make a
    model change indistinguishable from a prompt change."""
    trip = _trip()
    place = _place("Otaru Canal", area="Otaru")
    nodes = [_node(place.id, 0, time(9, 0), time(10, 30))]
    renders = {build_prompt(trip, nodes, [place]) for _ in range(5)}
    assert len(renders) == 1


def test_prompt_survives_a_candidate_it_cannot_resolve():
    prompt = build_prompt(_trip(), [_node(uuid4(), 0, time(9, 0), time(10, 0))], [])
    assert "Unknown place" in prompt


def test_prompt_includes_quantified_wishlist_reasons():
    trip = _trip()
    museum = _place("Otaru Music Box Museum")
    version_id = uuid4()
    wishlist = [
        WishlistNotPlaced(
            version_id=version_id,
            candidate_id=museum.id,
            reason_code="fatigue_overflow",
            reason_text=(
                "Otaru Music Box Museum costs 3 fatigue points, but every open "
                "day was already at the 8-point fatigue cap."
            ),
        )
    ]

    prompt = build_prompt(trip, [], [museum], wishlist)

    assert "Wishlist not placed:" in prompt
    assert "Otaru Music Box Museum" in prompt
    assert "3 fatigue points" in prompt
    assert "8-point fatigue cap" in prompt


# ----- the request shape -----


async def test_request_uses_the_configured_model():
    from syncinerary.config import settings

    stub = StubMessages()
    place = _place("Otaru Canal")
    await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    assert stub.calls[0]["model"] == settings.sync_llm_model


async def test_request_sends_no_sampling_parameters():
    """temperature, top_p and top_k were removed on the configured model and
    now return a 400. This is the single most likely way to break the call."""
    stub = StubMessages()
    place = _place("Otaru Canal")
    await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    sent = stub.calls[0]
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in sent


async def test_request_sends_no_thinking_budget():
    """budget_tokens was removed on the configured model; depth is effort."""
    stub = StubMessages()
    place = _place("Otaru Canal")
    await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    sent = stub.calls[0]
    assert "thinking" not in sent
    assert sent["output_config"] == {"effort": EXPLAIN_EFFORT}
    assert sent["max_tokens"] == EXPLAIN_MAX_TOKENS


async def test_request_ends_on_a_user_turn():
    """Assistant-turn prefill returns a 400 on the configured model."""
    stub = StubMessages()
    place = _place("Otaru Canal")
    await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    messages = stub.calls[0]["messages"]
    assert messages[-1]["role"] == "user"
    assert all(m["role"] != "assistant" for m in messages)


async def test_system_prompt_forbids_changing_the_plan():
    """§2: the explainer is the last step and never decides anything."""
    stub = StubMessages()
    place = _place("Otaru Canal")
    await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    system = stub.calls[0]["system"]
    assert "already decided" in system
    assert "Never suggest adding, removing, reordering, or retiming" in system
    assert "Never invent" in system
    assert "untrusted data" in system


# ----- responses -----


async def test_narrative_comes_back_as_text():
    stub = StubMessages(text="  Day one starts in Otaru.  ")
    place = _place("Otaru Canal")
    narrative = await generate_narrative(
        _trip(), [_node(place.id, 0, time(9, 0), time(10, 0))], [place], client=stub
    )
    assert narrative == "Day one starts in Otaru."


async def test_an_empty_itinerary_needs_no_model_call():
    stub = StubMessages()
    narrative = await generate_narrative(_trip(), [], [], client=stub)
    assert stub.calls == []
    assert "No stops were scheduled" in narrative


async def test_a_refusal_is_not_mistaken_for_a_narrative():
    """A declined request returns HTTP 200 with an empty content list, so
    stop_reason has to be checked before content is read."""

    class RefusingMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])

    place = _place("Otaru Canal")
    with pytest.raises(ExplainUnavailable, match="refused"):
        await generate_narrative(
            _trip(),
            [_node(place.id, 0, time(9, 0), time(10, 0))],
            [place],
            client=RefusingMessages(),
        )


async def test_an_empty_response_is_an_error_not_an_empty_narrative():
    class SilentMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(stop_reason="end_turn", content=[])

    place = _place("Otaru Canal")
    with pytest.raises(ExplainUnavailable, match="no text"):
        await generate_narrative(
            _trip(),
            [_node(place.id, 0, time(9, 0), time(10, 0))],
            [place],
            client=SilentMessages(),
        )


async def test_a_transport_failure_surfaces_as_a_typed_error():
    place = _place("Otaru Canal")
    with pytest.raises(ExplainUnavailable, match="connection reset"):
        await generate_narrative(
            _trip(),
            [_node(place.id, 0, time(9, 0), time(10, 0))],
            [place],
            client=ExplodingMessages(),
        )


# ----- the node -----


async def test_explain_node_narrates_the_committed_itinerary(session, monkeypatch):
    trip = await TripRepository(session).add(_trip())
    place = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Canal",
            lat=43.19,
            lng=140.99,
            area="Otaru",
        )
    )
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    await ItineraryNodeRepository(session).add(
        ItineraryNode(
            version_id=version.id,
            candidate_id=place.id,
            day=0,
            start_time=time(9, 0),
            end_time=time(10, 30),
        )
    )
    skipped = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Music Box Museum",
            lat=43.19,
            lng=141.00,
        )
    )
    await WishlistNotPlacedRepository(session).add(
        WishlistNotPlaced(
            version_id=version.id,
            candidate_id=skipped.id,
            reason_code="fatigue_overflow",
            reason_text=(
                "Otaru Music Box Museum costs 3 fatigue points, but every open "
                "day was already at the 8-point fatigue cap."
            ),
        )
    )

    stub = StubMessages(text="You start beside the Otaru Canal.")
    _use_test_session(monkeypatch, session)
    monkeypatch.setattr(explain_module, "_make_client", lambda: stub)

    result = await explain_node(TripState(trip=trip))

    assert result == {"narrative": "You start beside the Otaru Canal."}
    assert "Otaru Canal" in stub.calls[0]["messages"][0]["content"]
    assert "Otaru Music Box Museum" in stub.calls[0]["messages"][0]["content"]
    assert "8-point fatigue cap" in stub.calls[0]["messages"][0]["content"]


async def test_explain_node_returns_none_when_nothing_was_planned(session, monkeypatch):
    trip = await TripRepository(session).add(_trip())
    _use_test_session(monkeypatch, session)

    result = await explain_node(TripState(trip=trip))

    assert result == {"narrative": None}


async def test_explain_node_returns_a_partial_dict_only(session, monkeypatch):
    trip = await TripRepository(session).add(_trip())
    _use_test_session(monkeypatch, session)
    state = TripState(trip=trip)

    result = await explain_node(state)

    assert set(result) == {"narrative"}
    assert state.narrative is None


async def test_explain_node_failure_is_not_swallowed(session, monkeypatch):
    """A placeholder narrative on failure would make a broken LLM path look
    healthy in F2's output. M2's harness owns retry, not this node."""
    trip = await TripRepository(session).add(_trip())
    place = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id,
            type=CandidateType.ATTRACTION,
            name_canonical="Otaru Canal",
            lat=43.19,
            lng=140.99,
        )
    )
    version = await ItineraryVersionRepository(session).add(
        ItineraryVersion(trip_id=trip.id, version_no=1)
    )
    await ItineraryNodeRepository(session).add(
        ItineraryNode(
            version_id=version.id,
            candidate_id=place.id,
            day=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )
    )
    _use_test_session(monkeypatch, session)
    monkeypatch.setattr(explain_module, "_make_client", ExplodingMessages)

    with pytest.raises(ExplainUnavailable):
        await explain_node(TripState(trip=trip))


def _use_test_session(monkeypatch, session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _scope():
        yield session

    monkeypatch.setattr(explain_module, "session_scope", _scope)
