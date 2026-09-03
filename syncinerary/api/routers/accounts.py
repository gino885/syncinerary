"""Stub identity and the trips an account belongs to.

CLAUDE.md section 15 allows a stub identity service and nothing more. There is
no password, no provider, and no verification: signing in with a handle claims
that handle. See GROUP_TRIP_PLAN.md section 2 for why that is enough for
invites and message authorship, and why it should not grow.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status

from syncinerary.api.deps import CurrentAccount, Session
from syncinerary.api.schemas import (
    AccountOut,
    SignInRequest,
    SignInResponse,
    TripSummaryOut,
)
from syncinerary.store.repositories import (
    AccountRepository,
    AccountSessionRepository,
    TravelerRepository,
    TripRepository,
)

router = APIRouter(tags=["accounts"])

_HANDLE = re.compile(r"^[a-z0-9_.-]{3,30}$")


@router.post("/auth/session", status_code=status.HTTP_201_CREATED)
async def sign_in(payload: SignInRequest, session: Session) -> SignInResponse:
    handle = payload.handle.strip().casefold()
    if not _HANDLE.match(handle):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Handle must be 3 to 30 characters: letters, digits, dot, dash, underscore",
        )
    account = await AccountRepository(session).upsert_by_handle(
        display_name=payload.display_name.strip(),
        handle=handle,
    )
    issued = await AccountSessionRepository(session).issue(account.id)
    return SignInResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        account=AccountOut.of(account),
    )


@router.get("/auth/me")
async def whoami(account: CurrentAccount) -> AccountOut:
    return AccountOut.of(account)


@router.get("/accounts/me/trips")
async def my_trips(account: CurrentAccount, session: Session) -> list[TripSummaryOut]:
    """Every trip this account is a traveler on, newest first.

    Replaces the iOS single-trip resume: with invites there is no longer one
    obvious trip to reopen.
    """
    travelers = await TravelerRepository(session).list_for_account(account.id)
    trips = TripRepository(session)
    summaries: list[TripSummaryOut] = []
    for traveler in travelers:
        trip = await trips.get(traveler.trip_id)
        if trip is None:
            continue
        members = await TravelerRepository(session).list_for_trip(trip.id)
        summaries.append(
            TripSummaryOut.of(trip, traveler_id=traveler.id, member_count=len(members))
        )
    summaries.sort(key=lambda summary: summary.start_date, reverse=True)
    return summaries


__all__ = ["router"]
