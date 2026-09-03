"""Invites, joining, and the trip message thread.

GROUP_TRIP_PLAN.md sections 4 to 7. Two things to keep in mind when editing:

- Message bodies are untrusted user content. Nothing here interprets a message
  as an instruction; the only structured thing taken from one is a URL, which
  the existing social parser has to recognize before it goes anywhere.
- An invite code is shareable, so anything reachable with only a code must be
  safe to show whoever holds it. The preview is deliberately thin.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError

from syncinerary.agents.gather.personal import resolve_link_attachment
from syncinerary.api.chat_ws import publish_trip_message, stream_trip_messages
from syncinerary.api.deps import CurrentAccount, Session
from syncinerary.api.schemas import (
    InviteCreateRequest,
    InviteOut,
    InvitePreviewOut,
    JoinTripRequest,
    JoinTripResponse,
    PostMessageRequest,
    TripMessageOut,
    TripOut,
)
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    SourceAttachment,
    Traveler,
    TripMessage,
    TripMessageKind,
)
from syncinerary.store.db import session_scope
from syncinerary.store.redis import get_redis
from syncinerary.store.repositories import (
    SourceAttachmentRepository,
    TravelerRepository,
    TripInviteRepository,
    TripMessageRepository,
    TripRepository,
)
from syncinerary.tools.fetch.social import SocialReferenceKind, normalize_social_url

router = APIRouter(tags=["group"])

# Deliberately permissive: whether a URL is usable is decided by
# normalize_social_url, not by this pattern. Its only job is to find
# candidates in prose.
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')]+")


def _now() -> datetime:
    return datetime.now(UTC)


async def _require_membership(
    session: Session,
    *,
    trip_id: UUID,
    account_id: UUID,
) -> Traveler:
    """Only members of a trip may invite to it, read it, or post in it."""
    traveler = await TravelerRepository(session).find_for_account_on_trip(
        trip_id=trip_id, account_id=account_id
    )
    if traveler is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Join this trip first")
    return traveler


# ----- invites -----


@router.post("/trips/{trip_id}/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    trip_id: UUID,
    payload: InviteCreateRequest,
    account: CurrentAccount,
    session: Session,
) -> InviteOut:
    traveler = await _require_membership(
        session, trip_id=trip_id, account_id=account.id
    )
    invite = await TripInviteRepository(session).create_for_trip(
        trip_id=trip_id,
        created_by_traveler_id=traveler.id,
        max_uses=payload.max_uses,
    )
    return InviteOut.of(invite)


@router.get("/trips/{trip_id}/invites")
async def list_invites(
    trip_id: UUID,
    account: CurrentAccount,
    session: Session,
) -> list[InviteOut]:
    await _require_membership(session, trip_id=trip_id, account_id=account.id)
    invites = await TripInviteRepository(session).list_for_trip(trip_id)
    return [InviteOut.of(invite) for invite in invites]


@router.delete("/trips/{trip_id}/invites/{code}")
async def revoke_invite(
    trip_id: UUID,
    code: str,
    account: CurrentAccount,
    session: Session,
) -> InviteOut:
    await _require_membership(session, trip_id=trip_id, account_id=account.id)
    invites = TripInviteRepository(session)
    invite = await invites.find_by_code(code)
    if invite is None or invite.trip_id != trip_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such invite for this trip")
    revoked = await invites.revoke(invite.id)
    return InviteOut.of(revoked or invite)


@router.get("/invites/{code}")
async def preview_invite(code: str, session: Session) -> InvitePreviewOut:
    """Readable with only the code, so it stays thin on purpose.

    Enough to decide whether to join, and nothing about the candidate pool or
    the thread, which a forwarded code should not expose.
    """
    invite = await TripInviteRepository(session).find_by_code(code)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown invite code")
    trip = await TripRepository(session).get(invite.trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That trip no longer exists")
    members = await TravelerRepository(session).list_for_trip(trip.id)
    usable = invite.is_usable(now=_now())
    reason = None
    if not usable:
        if invite.revoked_at is not None:
            reason = "This invite was turned off"
        elif invite.expires_at <= _now():
            reason = "This invite has expired"
        else:
            reason = "This invite has been used up"
    return InvitePreviewOut(
        trip=TripOut.of(trip),
        member_names=[member.name for member in members],
        usable=usable,
        reason=reason,
    )


@router.post("/invites/{code}/join", status_code=status.HTTP_201_CREATED)
async def join_trip(
    code: str,
    payload: JoinTripRequest,
    account: CurrentAccount,
    session: Session,
) -> JoinTripResponse:
    invites = TripInviteRepository(session)
    invite = await invites.find_by_code(code)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown invite code")
    trip = await TripRepository(session).get(invite.trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That trip no longer exists")

    travelers = TravelerRepository(session)
    # Re-opening the invite link must not spend a use or hit the unique
    # constraint, so an existing member short-circuits before the claim.
    existing = await travelers.find_for_account_on_trip(
        trip_id=trip.id, account_id=account.id
    )
    if existing is not None:
        return JoinTripResponse(
            trip=TripOut.of(trip), traveler_id=existing.id, already_member=True
        )

    if await invites.claim(invite.id) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This invite is no longer usable: it expired, was turned off, or is full",
        )

    traveler = await travelers.add(
        Traveler(
            trip_id=trip.id,
            name=payload.name or account.display_name,
            home_city=payload.home_city,
            account_id=account.id,
            # Section 4: tags are required, because a member with an empty
            # profile scores 0 on interest_fit and contributes nothing to the
            # For You lane.
            profile={"interests": payload.preference_tags},
        )
    )
    return JoinTripResponse(
        trip=TripOut.of(trip), traveler_id=traveler.id, already_member=False
    )


# ----- the thread -----


async def _attach_first_supported_url(
    body: str,
    *,
    trip,
    traveler: Traveler,
    session: Session,
) -> UUID | None:
    """Turn a pasted post link into a user_paste attachment.

    Only URLs the social parser already normalizes become attachments, so a
    message cannot introduce a tracking-parameter link or an unsupported host.
    Anything else stays plain text.
    """
    attachments = SourceAttachmentRepository(session)
    for raw in _URL_IN_TEXT.findall(body):
        try:
            reference = normalize_social_url(raw)
        except ValueError:
            continue
        if reference.kind is SocialReferenceKind.SEARCH:
            continue
        existing = await attachments.find_link(
            trip_id=trip.id,
            traveler_id=traveler.id,
            canonical_url=reference.canonical_url,
        )
        if existing is not None:
            return existing.id
        attachment = await attachments.add(
            SourceAttachment(
                trip_id=trip.id,
                traveler_id=traveler.id,
                platform=reference.platform,
                input_type=AttachmentInputType.LINK,
                status=AttachmentStatus.PENDING,
                original_url=raw,
                canonical_url=reference.canonical_url,
                platform_id=reference.platform_id,
            )
        )
        attachment = await resolve_link_attachment(attachment, trip, session)
        return attachment.id
    return None


@router.get("/trips/{trip_id}/messages")
async def list_messages(
    trip_id: UUID,
    account: CurrentAccount,
    session: Session,
) -> list[TripMessageOut]:
    await _require_membership(session, trip_id=trip_id, account_id=account.id)
    messages = await TripMessageRepository(session).list_for_trip(trip_id)
    members = {
        member.id: member.name
        for member in await TravelerRepository(session).list_for_trip(trip_id)
    }
    return [
        TripMessageOut.of(message, author_name=members.get(message.traveler_id))
        for message in messages
    ]


@router.post("/trips/{trip_id}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(
    trip_id: UUID,
    payload: PostMessageRequest,
    account: CurrentAccount,
    session: Session,
) -> TripMessageOut:
    traveler = await _require_membership(
        session, trip_id=trip_id, account_id=account.id
    )
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such trip")

    attachment_id = await _attach_first_supported_url(
        payload.body, trip=trip, traveler=traveler, session=session
    )
    message = await TripMessageRepository(session).add(
        TripMessage(
            trip_id=trip_id,
            traveler_id=traveler.id,
            body=payload.body,
            kind=(
                TripMessageKind.LINK
                if attachment_id is not None
                else TripMessageKind.TEXT
            ),
            link_attachment_id=attachment_id,
        )
    )
    out = TripMessageOut.of(message, author_name=traveler.name)
    try:
        await publish_trip_message(get_redis(), out)
    except RedisError:
        # The message is already durable. A dead pub/sub means other clients
        # get it on their next fetch rather than losing it.
        pass
    return out


@router.websocket("/trips/{trip_id}/chat/ws")
async def chat_websocket(
    websocket: WebSocket,
    trip_id: UUID,
    traveler_id: UUID,
) -> None:
    async with session_scope() as session:
        trip = await TripRepository(session).get(trip_id)
        traveler = await TravelerRepository(session).get(traveler_id)
        if trip is None or traveler is None or traveler.trip_id != trip_id:
            await websocket.close(code=1008, reason="Trip membership required")
            return
    try:
        await stream_trip_messages(websocket, get_redis(), trip_id)
    except WebSocketDisconnect:
        return


__all__ = ["router"]
