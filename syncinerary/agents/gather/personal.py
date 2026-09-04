"""Resolve traveler-submitted place names into attributed candidates."""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from syncinerary.agents.gather.attachments import ExtractedPlaceMention
from syncinerary.agents.gather.cities import search_bias, trip_cities
from syncinerary.agents.gather.dietary import dietary_tags_from_place_types
from syncinerary.agents.gather.social_read import read_cover_text_for_url
from syncinerary.agents.gather.traits import fatigue_cost, is_visitable_place, is_weather_dependent
from syncinerary.config import settings
from syncinerary.config.gather import (
    PROFILE_DRIVEN_CAP_PER_TRAVELER,
    SOCIAL_COVER_OCR_ENABLED,
)
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    SocialPlatform,
    Source,
    SourceAttachment,
    Traveler,
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
    strict_json_schema,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    SourceAttachmentRepository,
)
from syncinerary.tools.fetch.social import (
    SocialLinkMetadataInput,
    TikTokOEmbedInput,
    make_social_link_metadata_tool,
    make_tiktok_oembed_tool,
)
from syncinerary.tools.places import (
    PlaceMatch,
    PlaceSearchBias,
    PlaceSearchInput,
    make_place_search_tool,
)

TEXT_EXTRACTION_PROMPT = """Extract place or restaurant names from a social caption.

Rules:
- Return only names supported by the supplied text.
- Skip countries, prefectures, districts, and whole cities. Only name places a
  traveler can actually go: a restaurant, a park, a museum, a shop, a landmark.
  A city name on its own, such as "Sapporo", is never a place. A caption
  reading "Best miso ramen in Sapporo, at Ramen Alley" names Ramen Alley.
- Order the list with the most specific place first. The first name that
  resolves is the one the traveler sees.
- Preserve the original language of each name.
- Do not infer a destination from the creator, visual style, or general knowledge.
- An empty place_mentions list is correct when the caption identifies no place.
- short_description is one lively sentence of at most 120 characters, based only on
  the caption. Omit it when the caption has no useful place detail.
- Do not include hashtags, handles, engagement prompts, or unsupported claims in
  short_description.
"""
PROFILE_SUGGESTION_PROMPT = """Suggest real places matching traveler interests.

Rules:
- Use only the destination and interests supplied by the user.
- Return at most two specific place names per traveler.
- Do not invent a traveler or change a traveler_id.
- A Google Places lookup will reject places that are not real or outside the city.
- Return an empty place_names list when the profile has no useful interests.
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
    short_description: str | None = Field(default=None, max_length=120)
    place_mentions: list[ExtractedPlaceMention] = Field(default_factory=list)


class TravelerProfileSuggestions(BaseModel):
    traveler_id: str
    place_names: list[str] = Field(default_factory=list)


class ProfileSuggestionBatch(BaseModel):
    travelers: list[TravelerProfileSuggestions] = Field(default_factory=list)


class TravelerProfileInput(BaseModel):
    traveler_id: str
    interests: list[str] = Field(default_factory=list)


class ProfileSuggestionInput(BaseModel):
    destination: str
    travelers: list[TravelerProfileInput] = Field(default_factory=list)


class PublicMetadataUnavailable(RuntimeError):
    """We could not look the post up, as opposed to looking and finding nothing.

    The difference decides whether the attachment is terminal. A missing Brave
    key is a deployment problem that a re-run fixes, so the attachment stays
    pending. A lookup that ran and returned nothing will return nothing next
    time too, so that one is failed with a reason.
    """


class TextPlaceExtractionUnavailable(RuntimeError):
    """A caption could not be converted into typed place evidence."""


async def _find_place_for_trip(
    place_name: str,
    trip: Trip,
) -> tuple[PlaceMatch, str | None] | None:
    """Find a named place inside one of the trip's selected cities."""
    cities = trip_cities(trip)
    if not cities:
        result = await run_tool(
            make_place_search_tool(),
            PlaceSearchInput(query=place_name, destination=trip.destination),
        )
        return (result.matches[0], None) if result.matches else None

    for city in cities:
        result = await run_tool(
            make_place_search_tool(),
            PlaceSearchInput(
                query=place_name,
                destination=city.name,
                location_bias=search_bias(city),
                city_center=PlaceSearchBias(lat=city.lat, lng=city.lng),
                city_radius_km=city.radius_km,
            ),
        )
        if result.matches:
            return result.matches[0], city.name
    return None


async def discover_profile_candidates(
    trip: Trip,
    travelers: list[Traveler],
    *,
    client: MessagesClient | None = None,
) -> list[CandidatePlace]:
    """Batch profiles once, cap each traveler, then verify every name."""
    profiled = [
        traveler
        for traveler in travelers
        if isinstance(traveler.profile.get("interests"), list)
        and any(str(item).strip() for item in traveler.profile["interests"])
    ]
    if not profiled:
        return []

    response = await call_llm(
        LLMRequest(
            model=settings.sync_cheap_model,
            max_tokens=1200,
            system=PROFILE_SUGGESTION_PROMPT,
            output_config=LLMOutputConfig(
                format=LLMJSONSchemaFormat(
                    schema_=strict_json_schema(ProfileSuggestionBatch)
                )
            ),
            messages=[
                LLMMessage(
                    role="user",
                    content=ProfileSuggestionInput(
                        destination=trip.destination,
                        travelers=[
                            TravelerProfileInput(
                                traveler_id=str(traveler.id),
                                interests=[
                                    str(item).strip()
                                    for item in traveler.profile["interests"]
                                    if str(item).strip()
                                ],
                            )
                            for traveler in profiled
                        ]
                    ).model_dump_json(),
                )
            ],
        ),
        client=client or make_messages_client(),
        state={"node": "gather_profile", "trip_id": str(trip.id)},
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return []
    content = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ).strip()
    if not content:
        return []
    try:
        suggestions = ProfileSuggestionBatch.model_validate_json(content)
    except ValidationError:
        return []

    by_id = {str(traveler.id): traveler for traveler in profiled}
    by_place_id: dict[str, CandidatePlace] = {}
    counts_by_traveler: dict[str, int] = {}
    names_by_traveler: dict[str, set[str]] = {}
    for suggestion in suggestions.travelers:
        traveler = by_id.get(suggestion.traveler_id)
        if traveler is None:
            continue
        seen_names = names_by_traveler.setdefault(suggestion.traveler_id, set())
        names: list[str] = []
        for raw_name in suggestion.place_names:
            if (
                counts_by_traveler.get(suggestion.traveler_id, 0)
                == PROFILE_DRIVEN_CAP_PER_TRAVELER
            ):
                break
            name = raw_name.strip()
            key = name.casefold()
            if not name or key in seen_names:
                continue
            seen_names.add(key)
            names.append(name)
            counts_by_traveler[suggestion.traveler_id] = (
                counts_by_traveler.get(suggestion.traveler_id, 0) + 1
            )

        for name in names:
            found = await _find_place_for_trip(name, trip)
            if found is None:
                continue
            match, city_name = found
            source = Source(
                type="personal",
                subtype="profile_driven",
                by=traveler.id,
                via="traveler_profile",
            )
            existing = by_place_id.get(match.place_id)
            if existing is not None:
                by_place_id[match.place_id] = existing.model_copy(
                    update={"sources": [*existing.sources, source]}
                )
                continue
            place_types = [*match.types]
            if match.primary_type:
                place_types.append(match.primary_type)
            candidate_type = _candidate_type(match)
            by_place_id[match.place_id] = CandidatePlace(
                trip_id=trip.id,
                type=candidate_type,
                name_canonical=match.display_name,
                lat=match.lat,
                lng=match.lng,
                address=match.formatted_address,
                area=match.area,
                hours_by_weekday=match.hours_by_weekday,
                price_tier=match.price_tier or 2,
                duration_estimate_min=(75 if candidate_type is CandidateType.FOOD else 60),
                dietary_tags=dietary_tags_from_place_types(place_types),
                weather_dependent=is_weather_dependent(match.primary_type, match.types),
                fatigue_cost=fatigue_cost(
                    candidate_type,
                    match.primary_type,
                    match.types,
                ),
                category=match.primary_type,
                sources=[source],
                enrichment={
                    "google_place_id": match.place_id,
                    "city": city_name,
                    "discovery_provider": "profile_driven_google_verification",
                    "source_description": match.editorial_summary,
                },
            )
    return list(by_place_id.values())


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
                # No effort setting: the cheap model rejects the parameter, and
                # this is extraction rather than reasoning so there is nothing
                # to tune. See config/explain.py for the model that does use it.
                format=LLMJSONSchemaFormat(
                    schema_=strict_json_schema(TextPlaceExtraction)
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


async def _resolve_first_resolvable(
    place_names: list[str],
    *,
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    """Take the first name that is a real, visitable place in this trip.

    A caption reading "Best miso ramen in Sapporo, at Ramen Alley" yields both
    names, and taking only the first gave the card the city. Skipping past a
    name that does not resolve is also what keeps a rejected city from burning
    the whole attachment, which is what the visitable-place guard did to it
    before this.
    """
    for place_name in place_names:
        found = await _find_place_for_trip(place_name, trip)
        if found is None or not is_visitable_place(
            found[0].primary_type, list(found[0].types)
        ):
            continue
        return await _create_candidate_for(
            found, place_name=place_name, attachment=attachment, trip=trip, session=session
        )
    return await _fail(
        attachment,
        session,
        reason=FAILURE_PLACE_NOT_IN_TRIP,
        metadata={**attachment.metadata, "unresolved_place_names": place_names},
    )


async def _resolve_place_name(
    place_name: str,
    *,
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    """One confirmed name. Shares the iterating path so both behave alike."""
    return await _resolve_first_resolvable(
        [place_name], attachment=attachment, trip=trip, session=session
    )


async def _create_candidate_for(
    found: tuple[PlaceMatch, str],
    *,
    place_name: str,
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    match, city_name = found
    place_types = [*match.types]
    if match.primary_type:
        place_types.append(match.primary_type)
    candidate_type = _candidate_type(match)
    candidate = await CandidatePlaceRepository(session).add(
        CandidatePlace(
            trip_id=trip.id,
            type=candidate_type,
            name_canonical=match.display_name,
            lat=match.lat,
            lng=match.lng,
            address=match.formatted_address,
            category=match.primary_type,
            dietary_tags=dietary_tags_from_place_types(place_types),
            weather_dependent=is_weather_dependent(match.primary_type, match.types),
            fatigue_cost=fatigue_cost(
                candidate_type,
                match.primary_type,
                match.types,
            ),
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
                "city": city_name,
                "attachment_id": str(attachment.id),
                "input_type": attachment.input_type.value,
                "platform": attachment.platform.value,
                "source_url": attachment.canonical_url,
                "platform_preview_url": attachment.metadata.get(
                    "platform_preview_url"
                ),
                "source_description": attachment.metadata.get("short_description"),
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


async def _read_public_metadata(attachment: SourceAttachment) -> dict[str, Any]:
    """Whatever each platform permits us to read about one shared post.

    TikTok publishes oEmbed, so that is used and it carries a thumbnail and an
    author. Instagram and RedNote publish neither an open oEmbed endpoint nor
    anything we may fetch directly (CLAUDE.md section 15 rules out logging in
    and scraping), so those fall back to the title and description a search
    index has already published for the URL. That is thinner but it is enough
    to name a place, which is all this step needs.
    """
    url = attachment.canonical_url
    if url is None:
        return {}

    if attachment.platform is SocialPlatform.TIKTOK:
        try:
            preview = await run_tool(
                make_tiktok_oembed_tool(), TikTokOEmbedInput(url=url)
            )
        except httpx.HTTPStatusError as exc:
            # A live paste of a deleted or private video 400s here, and an
            # uncaught raise took the whole POST /messages down with it, so the
            # message itself was never stored. A link the group cannot read is
            # a card that needs a name, not a server error.
            if exc.response.status_code < 500:
                return {}
            raise PublicMetadataUnavailable(
                f"TikTok oEmbed is unavailable ({exc.response.status_code})"
            ) from exc
        except httpx.HTTPError as exc:
            # Transport failure rather than a verdict about the post: keep the
            # attachment retryable.
            raise PublicMetadataUnavailable("TikTok oEmbed could not be reached") from exc
        return {
            "caption": preview.caption,
            "platform_author_name": preview.author_name,
            "platform_author_url": preview.author_url,
            "platform_preview_url": preview.thumbnail_url,
        }

    if not settings.brave_search_api_key:
        raise PublicMetadataUnavailable(
            "BRAVE_SEARCH_API_KEY is not configured, so link metadata cannot be read"
        )

    indexed = await run_tool(
        make_social_link_metadata_tool(),
        SocialLinkMetadataInput(url=url),
    )
    if not indexed.indexed_text.strip():
        return {}
    return {
        "caption": indexed.indexed_text,
        "platform_metadata_source": "public_search_index",
    }


async def _read_tiktok_cover_text(attachment: SourceAttachment) -> str | None:
    """Cover-frame text for a pasted TikTok link, when there is a cover to read."""
    if (
        attachment.platform is not SocialPlatform.TIKTOK
        or attachment.canonical_url is None
        or not SOCIAL_COVER_OCR_ENABLED
        or not attachment.metadata.get("platform_preview_url")
    ):
        return None
    return await read_cover_text_for_url(attachment.canonical_url)


# Why a link could not become a card. The traveler sees these, so each one
# has to imply what they can do next, and NEEDS_PLACE_NAME is the common case:
# Instagram and RedNote permalinks are almost never in a search index, and
# section 15 rules out reading the post itself, so the only way forward is for
# the person who pasted it to say what place it is.
FAILURE_NEEDS_PLACE_NAME = "needs_place_name"
FAILURE_NO_PLACE_IN_TEXT = "no_place_named_in_post"
FAILURE_PLACE_NOT_IN_TRIP = "place_not_found_in_trip_cities"


async def _fail(
    attachment: SourceAttachment,
    session: AsyncSession,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> SourceAttachment:
    updated = await SourceAttachmentRepository(session).mark_failed(
        attachment.id,
        metadata=metadata if metadata is not None else dict(attachment.metadata),
        reason=reason,
    )
    return updated or attachment


async def resolve_link_attachment(
    attachment: SourceAttachment,
    trip: Trip,
    session: AsyncSession,
) -> SourceAttachment:
    """Use confirmed names first, then permitted platform metadata.

    Every path out of here is terminal. An attachment that cannot be resolved
    is marked failed with a reason rather than left pending, because pending
    reads as "still working" to both the UI and the next gather.
    """
    if attachment.metadata.get("submitted_place_name"):
        return await resolve_named_attachment(attachment, trip, session)
    if attachment.canonical_url is None:
        return await _fail(attachment, session, reason=FAILURE_NEEDS_PLACE_NAME)

    try:
        public = await _read_public_metadata(attachment)
    except PublicMetadataUnavailable:
        # Retryable: leave it pending so configuring the key and re-running
        # picks it up, rather than burning the attachment on a config gap.
        return attachment
    if not public.get("caption"):
        return await _fail(attachment, session, reason=FAILURE_NEEDS_PLACE_NAME)

    metadata = {**attachment.metadata, **public}
    attachment = attachment.model_copy(update={"metadata": metadata})
    preview_caption = public["caption"]
    extraction = await extract_place_mentions(
        preview_caption,
        platform=attachment.platform,
    )
    if extraction.short_description:
        metadata["short_description"] = extraction.short_description
        attachment = attachment.model_copy(update={"metadata": metadata})
    if not extraction.place_mentions:
        # A TikTok cover frame often carries the title the caption left out.
        # One bounded vision read, only on the path that would otherwise end
        # in "type the place name and add again".
        cover_text = await _read_tiktok_cover_text(attachment)
        if cover_text:
            metadata["cover_text"] = cover_text
            attachment = attachment.model_copy(update={"metadata": metadata})
            extraction = await extract_place_mentions(
                f"{preview_caption}\nOn screen: {cover_text}",
                platform=attachment.platform,
            )
            if extraction.short_description and not metadata.get("short_description"):
                metadata["short_description"] = extraction.short_description
                attachment = attachment.model_copy(update={"metadata": metadata})
    if not extraction.place_mentions:
        return await _fail(
            attachment,
            session,
            reason=FAILURE_NO_PLACE_IN_TEXT,
            metadata=metadata,
        )
    return await _resolve_first_resolvable(
        [mention.name for mention in extraction.place_mentions],
        attachment=attachment,
        trip=trip,
        session=session,
    )


__all__ = [
    "FAILURE_NEEDS_PLACE_NAME",
    "FAILURE_NO_PLACE_IN_TEXT",
    "FAILURE_PLACE_NOT_IN_TRIP",
    "ProfileSuggestionBatch",
    "ProfileSuggestionInput",
    "PublicMetadataUnavailable",
    "TextPlaceExtraction",
    "TextPlaceExtractionUnavailable",
    "discover_profile_candidates",
    "extract_place_mentions",
    "resolve_link_attachment",
    "resolve_named_attachment",
]
