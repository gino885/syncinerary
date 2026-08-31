"""Structured parsing for free-text like-with-note votes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from syncinerary.config import settings
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

NOTE_MAX_TOKENS = 500

SYSTEM_PROMPT = """Parse one traveler's note attached to a positive vote.

Choose exactly one kind. Use self_handles_meal when the traveler will arrange
their own food and include the alternative. Use short_visit when they require
a visit cap. Use conditional for weather_good, time_of_day, or
group_consensus. Use raw when none fits. Preserve the traveler's meaning and
never add a condition they did not state. Every field is required by the JSON
schema; set fields that do not apply to null."""


class ParsedVoteNote(BaseModel):
    kind: Literal["self_handles_meal", "short_visit", "conditional", "raw"]
    self_handles_meal: bool | None
    alternative: str | None = Field(max_length=100)
    requires_short_visit: bool | None
    max_minutes: int | None
    conditional_on: Literal["weather_good", "time_of_day", "group_consensus"] | None
    condition_detail: str | None = Field(max_length=200)
    raw: str | None = Field(max_length=1_000)

    def normalized(self, original: str) -> dict[str, object]:
        if self.kind == "self_handles_meal":
            if self.self_handles_meal is True and self.alternative:
                return {
                    "self_handles_meal": True,
                    "alternative": self.alternative,
                }
        elif self.kind == "short_visit":
            if self.requires_short_visit is True and self.max_minutes is not None:
                return {
                    "requires_short_visit": True,
                    "max_minutes": max(1, self.max_minutes),
                }
        elif self.kind == "conditional" and self.conditional_on is not None:
            result: dict[str, object] = {"conditional_on": self.conditional_on}
            if self.condition_detail:
                result["condition_detail"] = self.condition_detail
            return result
        return {"raw": self.raw or original}


class NoteParsingUnavailable(RuntimeError):
    """The delegate did not return a usable structured note."""


async def parse_vote_note(
    note: str,
    *,
    client: MessagesClient | None = None,
) -> dict[str, object]:
    cleaned = note.strip()
    if not cleaned:
        raise ValueError("A like with note requires text")

    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=NOTE_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config=LLMOutputConfig(
                format=LLMJSONSchemaFormat(schema_=strict_json_schema(ParsedVoteNote))
            ),
            messages=[LLMMessage(role="user", content=cleaned)],
        ),
        client=client or make_messages_client(),
        state={"node": "delegate_note_parser"},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise NoteParsingUnavailable("Delegate note request was refused")

    content = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not content:
        raise NoteParsingUnavailable("Delegate returned no note data")
    try:
        parsed = ParsedVoteNote.model_validate_json(content)
    except Exception as exc:
        raise NoteParsingUnavailable(f"Delegate returned invalid note data: {exc}") from exc
    return parsed.normalized(cleaned)


__all__ = ["NoteParsingUnavailable", "ParsedVoteNote", "parse_vote_note"]
