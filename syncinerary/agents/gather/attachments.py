"""Vision extraction for traveler-submitted social screenshots."""
from __future__ import annotations

import base64

from pydantic import BaseModel, Field, ValidationError

from syncinerary.config import settings
from syncinerary.domain.models import SocialPlatform
from syncinerary.harness.wrapper import (
    LLMBase64ImageSource,
    LLMImageBlock,
    LLMJSONSchemaFormat,
    LLMMessage,
    LLMOutputConfig,
    LLMRequest,
    LLMTextBlock,
    MessagesClient,
    call_llm,
    make_messages_client,
    strict_json_schema,
)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024

SYSTEM_PROMPT = """Extract travel evidence visible in a user-submitted social screenshot.

Rules:
- Transcribe only text that is visible. Preserve its original language.
- Extract a place name only when the screenshot provides evidence for it.
- Never guess a location from visual style, landmarks, or general knowledge.
- Keep the evidence for each place short and quote or closely paraphrase the screenshot.
- An empty place_mentions list is correct when no place can be identified.
"""


class ExtractedPlaceMention(BaseModel):
    name: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class ScreenshotExtraction(BaseModel):
    raw_text: str
    language: str | None = None
    place_mentions: list[ExtractedPlaceMention] = Field(default_factory=list)


class ScreenshotExtractionUnavailable(RuntimeError):
    """The screenshot could not be converted into typed evidence."""


async def extract_screenshot(
    image: bytes,
    *,
    media_type: str,
    platform: SocialPlatform,
    client: MessagesClient | None = None,
) -> ScreenshotExtraction:
    if media_type not in SUPPORTED_IMAGE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES))
        raise ValueError(f"screenshot must be one of: {supported}")
    if not image:
        raise ValueError("screenshot cannot be empty")
    if len(image) > MAX_SCREENSHOT_BYTES:
        raise ValueError("screenshot exceeds the 10 MB limit")

    encoded = base64.standard_b64encode(image).decode("ascii")
    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            output_config=LLMOutputConfig(
                # No effort setting: the cheap model rejects the parameter, and
                # this is extraction rather than reasoning so there is nothing
                # to tune. See config/explain.py for the model that does use it.
                format=LLMJSONSchemaFormat(
                    schema_=strict_json_schema(ScreenshotExtraction)
                ),
            ),
            messages=[
                LLMMessage(
                    role="user",
                    content=[
                        LLMImageBlock(
                            source=LLMBase64ImageSource(
                                media_type=media_type,
                                data=encoded,
                            )
                        ),
                        LLMTextBlock(
                            text=(
                                f"This screenshot came from {platform.value}. "
                                "Extract its visible travel evidence."
                            )
                        ),
                    ],
                )
            ],
        ),
        client=client or make_messages_client(),
        state={"node": "gather_attachment", "platform": platform.value},
    )

    if getattr(response, "stop_reason", None) == "refusal":
        raise ScreenshotExtractionUnavailable(
            "Screenshot extraction was refused by the model"
        )
    text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not text:
        raise ScreenshotExtractionUnavailable("Screenshot extraction returned no text")
    try:
        return ScreenshotExtraction.model_validate_json(text)
    except ValidationError as exc:
        raise ScreenshotExtractionUnavailable(
            f"Screenshot extraction returned invalid data: {exc}"
        ) from exc


__all__ = [
    "MAX_SCREENSHOT_BYTES",
    "ExtractedPlaceMention",
    "ScreenshotExtraction",
    "ScreenshotExtractionUnavailable",
    "extract_screenshot",
]
