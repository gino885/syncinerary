"""Trip setup, saved-post collection, and swipe voting.

The router keeps the client-facing trip flow together: create a trip, attach
personal sources, read the attributed deck, and swipe it. Shortlist
confirmation and replan arrive in later milestones.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from syncinerary.agents.gather.attachments import (
    MAX_SCREENSHOT_BYTES,
    SUPPORTED_IMAGE_TYPES,
    ScreenshotExtractionUnavailable,
    extract_screenshot,
)
from syncinerary.agents.gather.personal import resolve_link_attachment
from syncinerary.agents.graph import get_graph, graph_config
from syncinerary.api.deps import Session
from syncinerary.api.schemas import (
    AttachmentLinkRequest,
    CandidateCardOut,
    CandidatePhotoAttributionOut,
    CandidatePhotoOut,
    GatherResponse,
    ItineraryDayOut,
    ItineraryOut,
    ItineraryStopOut,
    PlanRequest,
    PlanResponse,
    SourceAttachmentOut,
    TripCreatedResponse,
    TripCreateRequest,
    TripOut,
    VoteOut,
    VoteProgressOut,
    VoteRequest,
    WishlistNotPlacedOut,
)
from syncinerary.config import settings
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    SourceAttachment,
    Traveler,
    Trip,
    TripState,
    TripStatus,
    Vote,
    VoteSignal,
)
from syncinerary.harness import run_tool, tracked_run
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    ConstraintRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    SourceAttachmentRepository,
    TravelerRepository,
    TripRepository,
    VoteRepository,
    WishlistNotPlacedRepository,
)
from syncinerary.tools.fetch.social import SocialReferenceKind, normalize_social_url
from syncinerary.tools.places import (
    PlacePhotoInput,
    PlaceSearchInput,
    make_place_photo_tool,
    make_place_search_tool,
)

router = APIRouter(prefix="/trips", tags=["trips"])


async def _load_trip(session: Session, trip_id: UUID) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No trip {trip_id}")
    return trip


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trip(payload: TripCreateRequest, session: Session) -> TripCreatedResponse:
    """Create a trip and its creator traveler.

    `days` is derived here and stored (§7 calls it derived but persisted):
    every downstream default is expressed as a multiple of it, so recomputing
    it in three places would be three chances to disagree. Inclusive of both
    end dates, so 21 to 25 May is 5 days, not 4.
    """
    days = (payload.end_date - payload.start_date).days + 1

    trip = await TripRepository(session).add(
        Trip(
            destination=payload.destination,
            start_date=payload.start_date,
            end_date=payload.end_date,
            days=days,
            status=TripStatus.SETUP,
        )
    )
    traveler = await TravelerRepository(session).add(
        Traveler(
            trip_id=trip.id,
            name=payload.creator_name,
            home_city=payload.creator_home_city,
        )
    )
    # created_by points at the traveler and carries no FK, since traveler
    # points back at the trip (see store/tables.py).
    trip = await TripRepository(session).set_created_by(trip.id, traveler.id)

    return TripCreatedResponse(trip=TripOut.of(trip), traveler_id=traveler.id)


@router.get("/{trip_id}")
async def get_trip(trip_id: UUID, session: Session) -> TripOut:
    return TripOut.of(await _load_trip(session, trip_id))


@router.get("/{trip_id}/candidates")
async def list_candidates(
    trip_id: UUID,
    session: Session,
    traveler_id: UUID | None = None,
) -> list[CandidateCardOut]:
    """The swipe deck.

    Lodging is excluded. §8.6 makes it solver-driven after shortlist
    confirmation, not something the group swipes.
    """
    await _load_trip(session, trip_id)
    if traveler_id is not None:
        viewer = await TravelerRepository(session).get(traveler_id)
        if viewer is None or viewer.trip_id != trip_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Traveler {traveler_id} is not on trip {trip_id}",
            )
    candidates = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    travelers = await TravelerRepository(session).list_for_trip(trip_id)
    contributor_names = {traveler.id: traveler.name for traveler in travelers}
    return [
        CandidateCardOut.of(
            candidate,
            viewer_id=traveler_id,
            contributor_names=contributor_names,
        )
        for candidate in candidates
    ]


@router.get("/{trip_id}/candidates/{candidate_id}/photo")
async def candidate_photo(
    trip_id: UUID,
    candidate_id: UUID,
    response: Response,
    session: Session,
) -> CandidatePhotoOut:
    """Fetch a fresh Places photo and its attribution for one visible card."""
    trip = await _load_trip(session, trip_id)
    candidate = await CandidatePlaceRepository(session).get(candidate_id)
    if candidate is None or candidate.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Candidate {candidate_id} is not in trip {trip_id}",
        )

    preview_url = candidate.enrichment.get("platform_preview_url")
    preview_provider = candidate.enrichment.get("platform")
    if (
        isinstance(preview_url, str)
        and preview_url.startswith("https://")
        and preview_provider in {"instagram", "tiktok", "rednote"}
    ):
        response.headers["Cache-Control"] = "no-store"
        return CandidatePhotoOut(
            provider=preview_provider,
            photo_url=preview_url,
        )

    place_id = candidate.enrichment.get("google_place_id")
    if not isinstance(place_id, str) or not place_id:
        search_result = await run_tool(
            make_place_search_tool(),
            PlaceSearchInput(
                query=candidate.name_canonical,
                destination=trip.destination,
            ),
        )
        if not search_result.matches:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No matching Google place was found for this card",
            )
        place_id = search_result.matches[0].place_id

    photo = await run_tool(
        make_place_photo_tool(),
        PlacePhotoInput(place_id=place_id),
    )
    if photo.photo_url is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This place has no permitted photo",
        )
    response.headers["Cache-Control"] = "no-store"
    return CandidatePhotoOut(
        photo_url=photo.photo_url,
        width_px=photo.width_px,
        height_px=photo.height_px,
        attributions=[
            CandidatePhotoAttributionOut(
                display_name=item.display_name,
                uri=item.uri,
                photo_uri=item.photo_uri,
            )
            for item in photo.attributions
        ],
    )


@router.post(
    "/{trip_id}/attachments/links",
    status_code=status.HTTP_201_CREATED,
)
async def attach_link(
    trip_id: UUID,
    payload: AttachmentLinkRequest,
    session: Session,
) -> SourceAttachmentOut:
    """Store one traveler-submitted social post with explicit provenance."""
    trip = await _load_trip(session, trip_id)
    traveler = await TravelerRepository(session).get(payload.traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {payload.traveler_id} is not on trip {trip_id}",
        )

    try:
        reference = normalize_social_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if reference.kind is SocialReferenceKind.SEARCH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Attach a specific post URL, not a search or discovery page",
        )

    attachment_repo = SourceAttachmentRepository(session)
    attachment = await attachment_repo.find_link(
        trip_id=trip_id,
        traveler_id=traveler.id,
        canonical_url=reference.canonical_url,
    )
    if attachment is not None:
        if attachment.status is AttachmentStatus.READY:
            return SourceAttachmentOut.of(attachment, traveler)
        if payload.place_name is not None:
            metadata = dict(attachment.metadata)
            metadata["submitted_place_name"] = payload.place_name
            attachment = (
                await attachment_repo.record_metadata(
                    attachment.id,
                    metadata=metadata,
                )
                or attachment
            )
        attachment = await resolve_link_attachment(attachment, trip, session)
        return SourceAttachmentOut.of(attachment, traveler)

    attachment = await attachment_repo.add(
        SourceAttachment(
            trip_id=trip_id,
            traveler_id=traveler.id,
            platform=reference.platform,
            input_type=AttachmentInputType.LINK,
            status=AttachmentStatus.PENDING,
            original_url=payload.url,
            canonical_url=reference.canonical_url,
            platform_id=reference.platform_id,
            metadata=(
                {"submitted_place_name": payload.place_name.strip()}
                if payload.place_name is not None
                else {}
            ),
        )
    )
    attachment = await resolve_link_attachment(attachment, trip, session)
    return SourceAttachmentOut.of(attachment, traveler)


@router.post("/{trip_id}/attachments/{attachment_id}/screenshot")
async def attach_screenshot(
    trip_id: UUID,
    attachment_id: UUID,
    traveler_id: Annotated[UUID, Form()],
    screenshot: Annotated[UploadFile, File()],
    session: Session,
) -> SourceAttachmentOut:
    """Add user-provided visual evidence without fetching protected content."""
    await _load_trip(session, trip_id)
    traveler = await TravelerRepository(session).get(traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {traveler_id} is not on trip {trip_id}",
        )
    attachment = await SourceAttachmentRepository(session).get(attachment_id)
    if (
        attachment is None
        or attachment.trip_id != trip_id
        or attachment.traveler_id != traveler_id
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Attachment {attachment_id} is not owned by this traveler",
        )

    media_type = screenshot.content_type or ""
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Screenshot must be JPEG, PNG, GIF, or WebP",
        )
    image = await screenshot.read(MAX_SCREENSHOT_BYTES + 1)
    if len(image) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "Screenshot exceeds the 10 MB limit",
        )

    try:
        extraction = await extract_screenshot(
            image,
            media_type=media_type,
            platform=attachment.platform,
        )
    except ScreenshotExtractionUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }[media_type]
    storage_key = f"{trip_id}/{attachment_id}{extension}"
    target = Path(settings.attachment_upload_dir) / storage_key
    await anyio.to_thread.run_sync(target.parent.mkdir, 0o755, True, True)
    await anyio.to_thread.run_sync(target.write_bytes, image)

    updated = await SourceAttachmentRepository(session).record_screenshot(
        attachment_id,
        storage_key=storage_key,
        extracted_text=extraction.raw_text,
        metadata={
            **attachment.metadata,
            "screenshot": extraction.model_dump(mode="json"),
        },
    )
    if updated is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Attachment {attachment_id} disappeared during processing",
        )
    return SourceAttachmentOut.of(updated, traveler)


@router.post("/{trip_id}/votes", status_code=status.HTTP_201_CREATED)
async def cast_vote(trip_id: UUID, payload: VoteRequest, session: Session) -> VoteOut:
    """Record one swipe.

    M1 accepts like and dislike only; the request schema rejects anything
    else with a 422 before reaching here.

    Re-voting on the same card replaces the earlier vote rather than adding
    one, so a traveler who changes their mind still counts once in §10.1.
    """
    await _load_trip(session, trip_id)

    traveler = await TravelerRepository(session).get(payload.traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {payload.traveler_id} is not on trip {trip_id}",
        )

    candidate = await CandidatePlaceRepository(session).get(payload.candidate_id)
    if candidate is None or candidate.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Candidate {payload.candidate_id} is not in trip {trip_id}",
        )

    vote = await VoteRepository(session).upsert(
        Vote(
            candidate_id=payload.candidate_id,
            traveler_id=payload.traveler_id,
            signal=VoteSignal(payload.signal.value),
        )
    )

    # First vote moves the trip out of setup. Status is advisory in M1; the
    # pipeline does not gate on it until the shortlist screen lands in M4.
    trip = await TripRepository(session).get(trip_id)
    if trip is not None and trip.status is TripStatus.SETUP:
        await TripRepository(session).set_status(trip_id, TripStatus.SWIPING)

    return VoteOut.of(vote)


@router.get("/{trip_id}/votes/progress")
async def vote_progress(
    trip_id: UUID, traveler_id: UUID, session: Session
) -> VoteProgressOut:
    """How far through the deck one traveler is. The iOS swipe screen uses
    this to decide when to offer planning."""
    await _load_trip(session, trip_id)

    deck = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    deck_ids = {c.id for c in deck}
    votes = await VoteRepository(session).list_for_traveler(traveler_id)
    voted = sum(1 for v in votes if v.candidate_id in deck_ids)

    return VoteProgressOut(
        total_candidates=len(deck),
        voted=voted,
        remaining=len(deck) - voted,
    )


@router.post("/{trip_id}/gather")
async def gather_trip(trip_id: UUID, session: Session) -> GatherResponse:
    """Run the graph to its swipe interrupt and return the deck size."""
    trip = await _load_trip(session, trip_id)
    graph = get_graph()
    config = graph_config(trip_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        travelers = await TravelerRepository(session).list_for_trip(trip_id)
        constraints = await ConstraintRepository(session).list_for_trip(trip_id)
        await graph.ainvoke(
            TripState(trip=trip, travelers=travelers, constraints=constraints),
            config,
        )

    deck = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    await TripRepository(session).set_status(trip_id, TripStatus.SWIPING)
    return GatherResponse(deck_size=len(deck))


@router.post("/{trip_id}/plan")
async def plan_trip(
    trip_id: UUID,
    payload: PlanRequest,
    session: Session,
) -> PlanResponse:
    """Resume after swiping and run through the explainer."""
    await _load_trip(session, trip_id)
    graph = get_graph()
    config = graph_config(trip_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Gather must run before planning",
        )

    if snapshot.next:
        await graph.aupdate_state(
            config,
            {"day_start": payload.day_start, "day_end": payload.day_end},
        )
        async with tracked_run(trip_id=trip_id, kind="plan"):
            result = await graph.ainvoke(None, config)
        state = TripState.model_validate(result)
    else:
        state = TripState.model_validate(snapshot.values)

    version = state.current_itinerary
    if version is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Planner produced no version")

    nodes = await ItineraryNodeRepository(session).list_for_version(version.id)
    await TripRepository(session).set_status(trip_id, TripStatus.ACTIVE)
    return PlanResponse(
        version_id=version.id,
        version_no=version.version_no,
        placed_stops=len(nodes),
        narrative=state.narrative,
    )


@router.get("/{trip_id}/itinerary")
async def get_itinerary(
    trip_id: UUID,
    session: Session,
    traveler_id: UUID | None = None,
) -> ItineraryOut:
    trip = await _load_trip(session, trip_id)
    versions = ItineraryVersionRepository(session)
    version = await versions.get_active(trip_id) or await versions.get_latest(trip_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No itinerary has been planned")

    nodes = await ItineraryNodeRepository(session).list_for_version(version.id)
    wishlist = await WishlistNotPlacedRepository(session).list_for_version(version.id)
    candidate_ids = [node.candidate_id for node in nodes] + [
        item.candidate_id for item in wishlist
    ]
    candidates = await CandidatePlaceRepository(session).list_by_ids(candidate_ids)
    by_id = {candidate.id: candidate for candidate in candidates}

    nodes_by_day: dict[int, list[ItineraryStopOut]] = {}
    travelers = await TravelerRepository(session).list_for_trip(trip_id)
    contributor_names = {traveler.id: traveler.name for traveler in travelers}
    for node in nodes:
        nodes_by_day.setdefault(node.day, []).append(
            ItineraryStopOut.of(
                node,
                by_id.get(node.candidate_id),
                viewer_id=traveler_id,
                contributor_names=contributor_names,
            )
        )

    narrative = None
    snapshot = await get_graph().aget_state(graph_config(trip_id))
    if snapshot.values:
        narrative = TripState.model_validate(snapshot.values).narrative

    return ItineraryOut(
        version_id=version.id,
        version_no=version.version_no,
        status=version.status,
        days=[
            ItineraryDayOut(
                day=day,
                date=trip.start_date + timedelta(days=day),
                stops=nodes_by_day.get(day, []),
            )
            for day in range(trip.days)
        ],
        narrative=narrative,
        wishlist_not_placed=[
            WishlistNotPlacedOut.of(item, by_id.get(item.candidate_id))
            for item in wishlist
        ],
    )
