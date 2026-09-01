"""LLM-selected weights for the deterministic solver's soft objective."""
from __future__ import annotations

import json
from typing import Any

from syncinerary.config import settings
from syncinerary.domain.models import ConstraintKind, SolverObjectiveWeights, TripState
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

SOFTPREF_MAX_TOKENS = 500

SYSTEM_PROMPT = """Choose relative weights for a group trip scheduler.

Return integers from 0 to 100. Higher means the scheduler should care more
about that soft preference. Hard constraints are enforced separately and can
never be relaxed. Use the group's stated soft constraints and parsed vote
notes. Keep every weight nonzero unless the group explicitly says it does not
care about that factor. Do not propose places or schedule anything."""


class SoftPreferenceUnavailable(RuntimeError):
    """The preference model did not return usable bounded weights."""


def _has_preferences(state: TripState) -> bool:
    return any(
        constraint.kind is ConstraintKind.SOFT for constraint in state.constraints
    ) or any(vote.note_parsed for vote in state.votes)


def build_softpref_prompt(state: TripState) -> str:
    payload = {
        "destination": state.trip.destination,
        "days": state.trip.days,
        "soft_constraints": [
            {
                "type": constraint.type,
                "value": constraint.value,
                "priority": constraint.priority,
                "traveler_id": str(constraint.traveler_id)
                if constraint.traveler_id
                else None,
            }
            for constraint in state.constraints
            if constraint.kind is ConstraintKind.SOFT
        ],
        "parsed_vote_notes": [
            {
                "candidate_id": str(vote.candidate_id),
                "traveler_id": str(vote.traveler_id),
                "note": vote.note_parsed,
            }
            for vote in state.votes
            if vote.note_parsed
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def generate_solver_weights(
    state: TripState,
    *,
    client: MessagesClient | None = None,
) -> SolverObjectiveWeights:
    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=SOFTPREF_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config=LLMOutputConfig(
                format=LLMJSONSchemaFormat(
                    schema_=strict_json_schema(SolverObjectiveWeights)
                )
            ),
            messages=[LLMMessage(role="user", content=build_softpref_prompt(state))],
        ),
        client=client or make_messages_client(),
        state={"node": "softpref", "trip_id": str(state.trip.id)},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise SoftPreferenceUnavailable("Soft preference request was refused")
    content = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not content:
        raise SoftPreferenceUnavailable("Soft preference request returned no data")
    try:
        return SolverObjectiveWeights.model_validate_json(content)
    except Exception as exc:
        raise SoftPreferenceUnavailable(
            f"Soft preference request returned invalid data: {exc}"
        ) from exc


async def softpref_node(
    state: TripState,
    *,
    client: MessagesClient | None = None,
) -> dict[str, Any]:
    """Return a partial state update without changing the checkpoint input."""
    if not _has_preferences(state):
        return {"solver_weights": SolverObjectiveWeights()}
    return {"solver_weights": await generate_solver_weights(state, client=client)}


__all__ = [
    "SoftPreferenceUnavailable",
    "build_softpref_prompt",
    "generate_solver_weights",
    "softpref_node",
]
