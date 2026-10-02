"""Membership check for preparation, including account-bound travelers."""

from uuid import UUID

from fastapi import HTTPException

from syncinerary.api.deps import Session, current_account
from syncinerary.domain.models import Account, Traveler, Trip
from syncinerary.store.repositories import TravelerRepository, TripRepository


async def require_member(
    session: Session, trip_id: UUID, traveler_id: UUID, account: Account | None
) -> Trip:
    trip = await TripRepository(session).get(trip_id)
    member = await TravelerRepository(session).get(traveler_id)
    if trip is None or member is None or member.trip_id != trip_id:
        raise HTTPException(403, "Join this trip first")
    if member.account_id is not None and (account is None or member.account_id != account.id):
        raise HTTPException(403, "Sign in as this trip member")
    return trip


async def require_account_member_for_owned_trip(
    session: Session,
    trip_id: UUID,
    account: Account | None,
) -> Trip:
    """Require sign-in for account-owned trips while retaining legacy fixtures."""
    trip = await TripRepository(session).get(trip_id)
    if trip is None:
        raise HTTPException(404, "Trip not found")
    members = await TravelerRepository(session).list_for_trip(trip_id)
    is_account_owned = any(member.account_id is not None for member in members)
    if is_account_owned and (
        account is None or all(member.account_id != account.id for member in members)
    ):
        raise HTTPException(403, "Sign in as a member of this trip")
    return trip


async def require_websocket_member(
    session: Session,
    *,
    trip_id: UUID,
    traveler_id: UUID,
    authorization: str | None,
) -> Traveler:
    """Authenticate a socket and bind its traveler identity to that account."""
    account = await current_account(session, authorization)
    member = await TravelerRepository(session).get(traveler_id)
    if (
        member is None
        or member.trip_id != trip_id
        or member.account_id != account.id
    ):
        raise HTTPException(403, "Sign in as this trip member")
    return member
