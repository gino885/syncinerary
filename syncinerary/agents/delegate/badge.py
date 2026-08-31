"""Per-traveler candidate fit badges generated in one cheap-model batch."""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from syncinerary.config import settings
from syncinerary.domain.models import (
    BadgeType,
    CandidateBadge,
    CandidatePlace,
    Constraint,
    Traveler,
    TripState,
)
from syncinerary.harness.wrapper import (
    LLMJSONSchemaFormat,
    LLMMessage,
    LLMOutputConfig,
    LLMRequest,
    MessagesClient,
    call_llm,
    make_messages_client,
    strict_json_schema,
)
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import (
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    ConstraintRepository,
    TravelerRepository,
)

BADGE_MAX_TOKENS = 4_096

SYSTEM_PROMPT = """You annotate travel cards for one traveler.

Return one decision for every candidate id in the input. Use warning only for
a hard constraint or an important soft constraint conflict. Use confirm only
for a strong, explicit profile match. Otherwise return null for badge_type,
badge_text, and reasoning. Never remove, rank, vote on, or invent a card.
Badge text must be short, direct, and written to the traveler. Reasoning may be
one sentence and must cite only facts present in the input."""


class BadgeDecision(BaseModel):
    candidate_id: UUID
    badge_type: Literal["warning", "confirm"] | None
    badge_text: str | None = Field(max_length=100)
    reasoning: str | None = Field(max_length=400)


class BadgeDecisionBatch(BaseModel):
    decisions: list[BadgeDecision]


class BadgeGenerationUnavailable(RuntimeError):
    """The delegate did not return a usable badge batch."""


def _prompt(
    traveler: Traveler,
    candidates: list[CandidatePlace],
    constraints: list[Constraint],
) -> str:
    scoped_constraints = [
        constraint
        for constraint in constraints
        if constraint.traveler_id in {None, traveler.id}
    ]
    payload = {
        "traveler": {
            "name": traveler.name,
            "home_city": traveler.home_city,
            "profile": traveler.profile,
        },
        "constraints": [
            {
                "type": constraint.type,
                "value": constraint.value,
                "priority": constraint.priority,
                "kind": constraint.kind.value,
            }
            for constraint in scoped_constraints
        ],
        "candidates": [
            {
                "candidate_id": str(candidate.id),
                "name": candidate.name_canonical,
                "type": candidate.type.value,
                "area": candidate.area,
                "category": candidate.category,
                "dietary_tags": candidate.dietary_tags,
                "weather_dependent": candidate.weather_dependent,
                "reservation_required": candidate.reservation_required,
            }
            for candidate in candidates
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


async def generate_badges_for_traveler(
    traveler: Traveler,
    candidates: list[CandidatePlace],
    constraints: list[Constraint],
    *,
    client: MessagesClient | None = None,
) -> list[CandidateBadge]:
    """Generate zero or one badge per card using one call for the traveler."""
    if not candidates:
        return []

    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=BADGE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config=LLMOutputConfig(
                format=LLMJSONSchemaFormat(
                    schema_=strict_json_schema(BadgeDecisionBatch)
                )
            ),
            messages=[
                LLMMessage(
                    role="user",
                    content=_prompt(traveler, candidates, constraints),
                )
            ],
        ),
        client=client or make_messages_client(),
        state={"node": "delegate_badges", "traveler_id": str(traveler.id)},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise BadgeGenerationUnavailable("Delegate badge request was refused")

    content = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not content:
        raise BadgeGenerationUnavailable("Delegate returned no badge data")

    try:
        batch = BadgeDecisionBatch.model_validate_json(content)
    except Exception as exc:
        raise BadgeGenerationUnavailable(f"Delegate returned invalid badge data: {exc}") from exc

    candidate_ids = {candidate.id for candidate in candidates}
    badges: list[CandidateBadge] = []
    seen: set[UUID] = set()
    for decision in batch.decisions:
        if decision.candidate_id not in candidate_ids or decision.candidate_id in seen:
            continue
        seen.add(decision.candidate_id)
        if decision.badge_type is None:
            continue
        if not decision.badge_text or not decision.reasoning:
            continue
        badges.append(
            CandidateBadge(
                candidate_id=decision.candidate_id,
                traveler_id=traveler.id,
                badge_type=BadgeType(decision.badge_type),
                badge_text=decision.badge_text,
                reasoning=decision.reasoning,
            )
        )
    return badges


async def badge_node(state: TripState) -> dict[str, Any]:
    """Generate all traveler badges after gather and before the swipe pause."""
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("delegate.badges") as span:
        span.set_attribute("trip_id", str(trip.id))
        span.set_attribute("model_id", settings.sync_cheap_model)

        # End the read transaction before any external model call. The final
        # replacement is a separate, short write transaction.
        async with session_scope() as session:
            travelers = await TravelerRepository(session).list_for_trip(trip.id)
            candidates = await CandidatePlaceRepository(session).list_swipeable(trip.id)
            constraints = await ConstraintRepository(session).list_for_trip(trip.id)

        badges: list[CandidateBadge] = []
        for traveler in travelers:
            badges.extend(
                await generate_badges_for_traveler(
                    traveler,
                    candidates,
                    constraints,
                )
            )

        async with session_scope() as session:
            saved = await CandidateBadgeRepository(session).replace_for_trip(
                trip.id,
                badges,
            )

        span.set_attribute("delegate.traveler_count", len(travelers))
        span.set_attribute("delegate.candidate_count", len(candidates))
        span.set_attribute("delegate.badge_count", len(saved))
        return {"badges": saved}


__all__ = [
    "BadgeDecision",
    "BadgeDecisionBatch",
    "BadgeGenerationUnavailable",
    "badge_node",
    "generate_badges_for_traveler",
]
