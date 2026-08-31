"""Trip setup, saved-post collection, and swipe voting.

The router keeps the client-facing trip flow together: create a trip, attach
personal sources, read the attributed deck, and swipe it. Shortlist
confirmation and replan arrive in later milestones.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from syncinerary.agents.delegate.note import NoteParsingUnavailable, parse_vote_note
from syncinerary.agents.gather.attachments import (
    MAX_SCREENSHOT_BYTES,
    SUPPORTED_IMAGE_TYPES,
    ScreenshotExtractionUnavailable,
    extract_screenshot,
)
from syncinerary.agents.gather.cities import (
    CityOutsideCountry,
    UnknownCity,
    destination_label,
    normalize_city_names,
    resolve_cities,
    resolve_timezone,
)
from syncinerary.agents.gather.dietary import filter_dietary_conflicts
from syncinerary.agents.gather.personal import resolve_link_attachment
from syncinerary.agents.graph import get_graph, graph_config
from syncinerary.agents.solver.lodging import rank_lodging_options
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
    LodgingOptionOut,
    LodgingSelectionRequest,
    PlanRequest,
    PlanResponse,
    ShortlistConfirmRequest,
    ShortlistEditRequest,
    ShortlistOut,
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
from syncinerary.config.aggregate import MUST_GO_CAP_PER_DAY
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    CandidateType,
    Constraint,
    ConstraintKind,
    ShortlistState,
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
    CandidateBadgeRepository,
    CandidatePlaceRepository,
    ConstraintRepository,
    ItineraryNodeRepository,
    ItineraryVersionRepository,
    ShortlistStateRepository,
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
from syncinerary.tools.timezone import TimezoneUnavailable

router = APIRouter(prefix="/trips", tags=["trips"])


async def _load_trip(session: Session, trip_id: UUID) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No trip {trip_id}")
    return trip


async def _load_trip_traveler(
    session: Session,
    trip_id: UUID,
    traveler_id: UUID,
) -> Traveler:
    traveler = await TravelerRepository(session).get(traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {traveler_id} is not on trip {trip_id}",
        )
    return traveler


def _shortlist_out(shortlist, traveler_count: int) -> ShortlistOut:
    required = max(1, ceil(traveler_count * 0.5))
    return ShortlistOut(
        trip_id=shortlist.trip_id,
        selected_candidate_ids=shortlist.selected_candidate_ids,
        must_go_candidate_ids=shortlist.must_go_candidate_ids,
        wishlist_excluded_ids=shortlist.wishlist_excluded_ids,
        confirmed_by=shortlist.confirmed_by,
        confirmed_at=shortlist.confirmed_at,
        confirmations_required=required,
        traveler_count=traveler_count,
        is_confirmed=(
            shortlist.confirmed_at is not None
            and len(set(shortlist.confirmed_by)) >= required
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trip(payload: TripCreateRequest, session: Session) -> TripCreatedResponse:
    """Create a trip and its creator traveler.

    `days` is derived here and stored (§7 calls it derived but persisted):
    every downstream default is expressed as a multiple of it, so recomputing
    it in three places would be three chances to disagree. Inclusive of both
    end dates, so 21 to 25 May is 5 days, not 4.
    """
    days = (payload.end_date - payload.start_date).days + 1

    cities = normalize_city_names(payload.cities)
    if not cities:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Enter at least one city to search",
        )
    if len(cities) > days:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A trip needs at least one day per city",
        )

    # Resolved here rather than during gather so a misspelled city comes back
    # while the traveler is still looking at the form.
    try:
        resolved = await resolve_cities(cities, payload.country)
        timezone = await resolve_timezone(resolved[0])
    except (CityOutsideCountry, UnknownCity) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
        ) from exc
    except TimezoneUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    trip = await TripRepository(session).add(
        Trip(
            destination=destination_label([city.name for city in resolved]),
            cities=[city.name for city in resolved],
            country=payload.country,
            resolved_cities=[city.model_dump(mode="json") for city in resolved],
            timezone=timezone,
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
            profile=(
                {"interests": payload.creator_interests}
                if payload.creator_interests
                else {}
            ),
        )
    )
    if payload.creator_dietary_excludes:
        await ConstraintRepository(session).add(
            Constraint(
                trip_id=trip.id,
                traveler_id=traveler.id,
                type="dietary",
                value={"excludes": payload.creator_dietary_excludes},
                priority=10,
                kind=ConstraintKind.HARD,
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
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    candidates = filter_dietary_conflicts(candidates, constraints)
    travelers = await TravelerRepository(session).list_for_trip(trip_id)
    contributor_names = {traveler.id: traveler.name for traveler in travelers}
    delegate_badges = (
        await CandidateBadgeRepository(session).list_for_traveler_on_trip(traveler_id)
        if traveler_id is not None
        else []
    )
    delegate_badge_by_candidate = {
        badge.candidate_id: badge for badge in delegate_badges
    }
    return [
        CandidateCardOut.of(
            candidate,
            viewer_id=traveler_id,
            contributor_names=contributor_names,
            constraints=constraints,
            delegate_badge=delegate_badge_by_candidate.get(candidate.id),
        )
        for candidate in candidates
    ]


@router.get("/{trip_id}/lodging-options")
async def lodging_options(trip_id: UUID, session: Session) -> list[LodgingOptionOut]:
    """Return up to three deterministic hotel comparisons for this trip."""
    trip = await _load_trip(session, trip_id)
    repo = CandidatePlaceRepository(session)
    lodging = await repo.list_by_type(trip_id, CandidateType.LODGING)
    activities = await repo.list_swipeable(trip_id)
    return [
        LodgingOptionOut.of(candidate, trip)
        for candidate in rank_lodging_options(lodging, activities)
    ]


@router.post("/{trip_id}/lodging-selection")
async def select_lodging(
    trip_id: UUID,
    payload: LodgingSelectionRequest,
    session: Session,
) -> LodgingOptionOut:
    """Persist the group's chosen hotel as a hard solver anchor."""
    trip = await _load_trip(session, trip_id)
    traveler = await TravelerRepository(session).get(payload.traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {payload.traveler_id} is not on trip {trip_id}",
        )
    candidate = await CandidatePlaceRepository(session).get(payload.candidate_id)
    if (
        candidate is None
        or candidate.trip_id != trip_id
        or candidate.type is not CandidateType.LODGING
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Lodging {payload.candidate_id} is not in trip {trip_id}",
        )
    await ConstraintRepository(session).set_group_constraint(
        trip_id,
        constraint_type="selected_lodging",
        value={"candidate_id": str(candidate.id)},
        priority=100,
        kind=ConstraintKind.HARD,
    )
    return LodgingOptionOut.of(candidate, trip)


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

    note_parsed = None
    if payload.signal.value == VoteSignal.LIKE_WITH_NOTE.value:
        try:
            note_parsed = await parse_vote_note(payload.note_text or "")
        except NoteParsingUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    vote = await VoteRepository(session).upsert(
        Vote(
            candidate_id=payload.candidate_id,
            traveler_id=payload.traveler_id,
            signal=VoteSignal(payload.signal.value),
            note_text=payload.note_text,
            note_parsed=note_parsed,
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

    traveler = await TravelerRepository(session).get(traveler_id)
    if traveler is None or traveler.trip_id != trip_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Traveler {traveler_id} is not on trip {trip_id}",
        )

    deck = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    constraints = await ConstraintRepository(session).list_for_trip(trip_id)
    deck = filter_dietary_conflicts(deck, constraints)
    deck_ids = {c.id for c in deck}
    votes = await VoteRepository(session).list_for_traveler(traveler_id)
    voted = sum(1 for v in votes if v.candidate_id in deck_ids)

    return VoteProgressOut(
        total_candidates=len(deck),
        voted=voted,
        remaining=len(deck) - voted,
    )


@router.get("/{trip_id}/shortlist")
async def get_shortlist(trip_id: UUID, session: Session) -> ShortlistOut:
    await _load_trip(session, trip_id)
    shortlist = await ShortlistStateRepository(session).get_for_trip(trip_id)
    if shortlist is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Shortlist has not been built")
    traveler_count = await TravelerRepository(session).count_for_trip(trip_id)
    return _shortlist_out(shortlist, traveler_count)


@router.post("/{trip_id}/shortlist/build")
async def build_trip_shortlist(trip_id: UUID, session: Session) -> ShortlistOut:
    """Resume consensus scoring and stop before scheduling for group review."""
    await _load_trip(session, trip_id)
    graph = get_graph()
    config = graph_config(trip_id)
    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status.HTTP_409_CONFLICT, "Gather must run before shortlisting")

    if snapshot.next == ("aggregate",):
        await graph.ainvoke(None, config)
    elif snapshot.next not in {("solver",), ()}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Trip is not ready to build a shortlist",
        )

    shortlist = await ShortlistStateRepository(session).get_for_trip(trip_id)
    if shortlist is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Planner produced no shortlist",
        )
    await TripRepository(session).set_status(trip_id, TripStatus.SHORTLISTING)
    traveler_count = await TravelerRepository(session).count_for_trip(trip_id)
    return _shortlist_out(shortlist, traveler_count)


@router.put("/{trip_id}/shortlist")
async def edit_shortlist(
    trip_id: UUID,
    payload: ShortlistEditRequest,
    session: Session,
) -> ShortlistOut:
    """Replace the editable shortlist and invalidate earlier acknowledgments."""
    trip = await _load_trip(session, trip_id)
    await _load_trip_traveler(session, trip_id, payload.traveler_id)
    current = await ShortlistStateRepository(session).get_for_trip(trip_id)
    if current is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Shortlist has not been built")

    selected = payload.selected_candidate_ids
    must_go = payload.must_go_candidate_ids
    if len(set(selected)) != len(selected) or len(set(must_go)) != len(must_go):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Candidate ids must be unique")
    if not set(must_go).issubset(selected):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Must-go cards must also be selected",
        )
    if len(must_go) > trip.days * MUST_GO_CAP_PER_DAY:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This trip can mark at most {trip.days * MUST_GO_CAP_PER_DAY} must-go cards",
        )

    candidates = await CandidatePlaceRepository(session).list_swipeable(trip_id)
    all_ids = [candidate.id for candidate in candidates]
    if not set(selected).issubset(all_ids):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Shortlist contains a card outside this trip",
        )
    selected_set = set(selected)
    ranked_ids = list(
        dict.fromkeys(
            [
                *current.selected_candidate_ids,
                *current.wishlist_excluded_ids,
                *all_ids,
            ]
        )
    )
    selection_changed = (
        selected != current.selected_candidate_ids
        or must_go != current.must_go_candidate_ids
    )
    saved = await ShortlistStateRepository(session).upsert(
        ShortlistState(
            trip_id=trip_id,
            selected_candidate_ids=selected,
            must_go_candidate_ids=must_go,
            confirmed_by=current.confirmed_by if not selection_changed else [],
            confirmed_at=current.confirmed_at if not selection_changed else None,
            wishlist_excluded_ids=[
                candidate_id
                for candidate_id in ranked_ids
                if candidate_id not in selected_set
            ],
        )
    )
    await TripRepository(session).set_status(trip_id, TripStatus.SHORTLISTING)
    return _shortlist_out(saved, await TravelerRepository(session).count_for_trip(trip_id))


@router.post("/{trip_id}/shortlist/confirm")
async def confirm_shortlist(
    trip_id: UUID,
    payload: ShortlistConfirmRequest,
    session: Session,
) -> ShortlistOut:
    """Acknowledge the current shortlist and close it once quorum is met."""
    await _load_trip(session, trip_id)
    await _load_trip_traveler(session, trip_id, payload.traveler_id)
    repo = ShortlistStateRepository(session)
    current = await repo.get_for_trip_for_update(trip_id)
    if current is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Shortlist has not been built")

    confirmed_by = list(dict.fromkeys([*current.confirmed_by, payload.traveler_id]))
    traveler_count = await TravelerRepository(session).count_for_trip(trip_id)
    required = max(1, ceil(traveler_count * 0.5))
    confirmed_at = None
    if len(confirmed_by) >= required:
        confirmed_at = current.confirmed_at or datetime.now(UTC)
    saved = await repo.upsert(
        current.model_copy(
            update={"confirmed_by": confirmed_by, "confirmed_at": confirmed_at}
        )
    )
    return _shortlist_out(saved, traveler_count)


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
        try:
            async with tracked_run(trip_id=trip_id, kind="gather"):
                await graph.ainvoke(
                    TripState(trip=trip, travelers=travelers, constraints=constraints),
                    config,
                )
        except UnknownCity as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
            ) from exc

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

    shortlist = await ShortlistStateRepository(session).get_for_trip(trip_id)
    if shortlist is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Build and confirm the shortlist before planning",
        )
    traveler_count = await TravelerRepository(session).count_for_trip(trip_id)
    if not _shortlist_out(shortlist, traveler_count).is_confirmed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The shortlist has not reached confirmation quorum",
        )
    if snapshot.next:
        if snapshot.next != ("solver",):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Build the shortlist before planning",
            )
        constraints = await ConstraintRepository(session).list_for_trip(trip_id)
        await graph.aupdate_state(
            config,
            {
                "day_start": payload.day_start,
                "day_end": payload.day_end,
                "constraints": constraints,
                "shortlist": shortlist,
            },
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
