"""Resolve traveler-submitted place names into attributed candidates."""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.agents.gather.attachments import ExtractedPlaceMention
from syncinerary.config import settings
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    SocialPlatform,
    Source,
    SourceAttachment,
    Trip,
)
from syncinerary.harness import run_tool
from syncinerary.harness.wrapper import (
    LLMJSONSchemaFormat,
    LLMMessage,
    LLMOutputConfig,
    LLMRequest,
    MessagesClient,
    call_llm,
    make_messages_client,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    SourceAttachmentRepository,
)
from syncinerary.tools.fetch.social import (
    TikTokOEmbedInput,
    make_tiktok_oembed_tool,
)
from syncinerary.tools.places import PlaceMatch, PlaceSearchInput, make_place_search_tool

TEXT_EXTRACTION_PROMPT = """Extract place or restaurant names from a social caption.

Rules:
- Return only names supported by the supplied text.
- Preserve the original language of each name.
- Do not infer a destination from the creator, visual style, or general knowledge.
- An empty place_mentions list is correct when the caption identifies no place.
"""
PLATFORM_LABEL = {
    SocialPlatform.INSTAGRAM: "Instagram",
    SocialPlatform.TIKTOK: "TikTok",
    SocialPlatform.REDNOTE: "RedNote",
}

FOOD_PLACE_TYPES = {
    "bakery",
    "bar",
    "cafe",
    "coffee_shop",
    "food_court",
    "ice_cream_shop",
    "meal_delivery",
    "meal_takeaway",
    "restaurant",
}
LODGING_PLACE_TYPES = {
    "bed_and_breakfast",
    "campground",
    "extended_stay_hotel",
    "guest_house",
    "hostel",
    "hotel",
    "lodging",
    "motel",
    "resort_hotel",
}


class TextPlaceExtraction(BaseModel):
    language: str | None = None
    place_mentions: list[ExtractedPlaceMention] = Field(default_factory=list)


class TextPlaceExtractionUnavailable(RuntimeError):
    """A caption could not be converted into typed place evidence."""


async def extract_place_mentions(
    text: str,
    *,
    platform: SocialPlatform,
    client: MessagesClient | None = None,
) -> TextPlaceExtraction:
    caption = text.strip()
    if not caption:
        return TextPlaceExtraction()
    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=800,
            system=TEXT_EXTRACTION_PROMPT,
            output_config=LLMOutputConfig(
                effort="low",
                format=LLMJSONSchemaFormat(
                    schema_=TextPlaceExtraction.model_json_schema()
                ),
            ),
            messages=[
                LLMMessage(
                    role="user",
                    content=f"{PLATFORM_LABEL[platform]} caption:\n{caption}",
                )
            ],
        ),
        client=client or make_messages_client(),
        state={"node": "gather_personal_caption", "platform": platform.value},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise TextPlaceExtractionUnavailable(
            "Caption extraction was refused by the model"
        )
    content = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not content:
        raise TextPlaceExtractionUnavailable("Caption extraction returned no text")
    try:
        return TextPlaceExtraction.model_validate_json(content)
    except ValidationError as exc:
        raise TextPlaceExtractionUnavailable(
            f"Caption extraction returned invalid data: {exc}"
        ) from exc


def _candidate_type(place: PlaceMatch) -> CandidateType:
    types = set(place.types)
    if place.primary_type:
        types.add(place.primary_type)
    if types & FOOD_PLACE_TYPES:
        return CandidateType.FOOD
    if types & LODGING_PLACE_TYPES:
        return CandidateType.LODGING
    return CandidateType.ATTRACTION


async def resolve_named_attachment(
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    """Resolve an optional user-confirmed name without requiring image input."""
    place_name = attachment.metadata.get("submitted_place_name")
    if not isinstance(place_name, str) or not place_name.strip():
        return attachment

    return await _resolve_place_name(
        place_name.strip(),
        attachment=attachment,
        trip=trip,
        session=session,
    )


async def _resolve_place_name(
    place_name: str,
    *,
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    result = await run_tool(
        make_place_search_tool(),
        PlaceSearchInput(query=place_name, destination=trip.destination),
    )
    if not result.matches:
        return attachment

    match = result.matches[0]
    candidate = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id,
            type=_candidate_type(match),
            name_canonical=match.display_name,
            lat=match.lat,
            lng=match.lng,
            address=match.formatted_address,
            category=match.primary_type,
            sources=[
                Source(
                    type="personal",
                    subtype="user_paste",
                    by=attachment.traveler_id,
                    via=f"{attachment.platform.value}_link",
                )
            ],
            enrichment={
                "google_place_id": match.place_id,
                "attachment_id": str(attachment.id),
                "input_type": attachment.input_type.value,
                "platform": attachment.platform.value,
                "source_url": attachment.canonical_url,
                "platform_preview_url": attachment.metadata.get(
                    "platform_preview_url"
                ),
            },
        )
    )
    metadata = dict(attachment.metadata)
    metadata["candidate_id"] = str(candidate.id)
    updated = await SourceAttachmentRepository(session).mark_ready(
        attachment.id,
        metadata=metadata,
    )
    if updated is None:
        raise RuntimeError(f"attachment {attachment.id} disappeared during resolution")
    return updated


async def resolve_link_attachment(
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    """Use confirmed names first, then permitted platform metadata."""
    if attachment.metadata.get("submitted_place_name"):
        return await resolve_named_attachment(attachment, trip, session)
    if attachment.platform is not SocialPlatform.TIKTOK:
        return attachment
    if attachment.canonical_url is None:
        return attachment

    preview = await run_tool(
        make_tiktok_oembed_tool(),
        TikTokOEmbedInput(url=attachment.canonical_url),
    )
    metadata = {
        **attachment.metadata,
        "caption": preview.caption,
        "platform_author_name": preview.author_name,
        "platform_author_url": preview.author_url,
        "platform_preview_url": preview.thumbnail_url,
    }
    attachment = attachment.model_copy(update={"metadata": metadata})
    extraction = await extract_place_mentions(
        preview.caption,
        platform=attachment.platform,
    )
    if not extraction.place_mentions:
        updated = await SourceAttachmentRepository(session).record_metadata(
            attachment.id,
            metadata=metadata,
        )
        return updated or attachment
    return await _resolve_place_name(
        extraction.place_mentions[0].name,
        attachment=attachment,
        trip=trip,
        session=session,
    )


__all__ = [
    "TextPlaceExtraction",
    "TextPlaceExtractionUnavailable",
    "extract_place_mentions",
    "resolve_link_attachment",
    "resolve_named_attachment",
]
