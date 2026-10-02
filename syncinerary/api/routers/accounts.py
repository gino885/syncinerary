"""Account identity and the trips an account belongs to."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response

from syncinerary.agents.graph import get_graph
from syncinerary.api import email_auth, social_auth
from syncinerary.api.auth_schemas import (
    CodeRequest,
    DeleteAccountRequest,
    EmailRequest,
    RegisterRequest,
    SignInRequest,
)
from syncinerary.api.deps import CurrentAccount, Session
from syncinerary.api.schemas import AccountOut, SignInResponse, TripSummaryOut
from syncinerary.config import settings
from syncinerary.store.repositories import (
    AccountRepository,
    AccountSessionRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.store.repositories.credentials import EmailAccountRepository
from syncinerary.store.repositories.social_accounts import SocialAccountRepository

router = APIRouter(tags=["accounts"])
_NOTICE = {"message": "If this email is eligible, a code has been sent. Check your inbox."}


@router.post("/auth/register", status_code=201)
async def register(payload: RegisterRequest, request: Request, session: Session) -> SignInResponse:
    await email_auth.rate_limit(request, payload.email, "register")
    repo = EmailAccountRepository(session)
    digest = await email_auth.hash_password(payload.password)
    account = await repo.create_password_account(payload.email, payload.display_name, digest)
    if account is None:
        raise HTTPException(409, "This email already has an account. Sign in or reset your password.")
    issued = await AccountSessionRepository(session).issue(account.id)
    return SignInResponse(token=issued.token, expires_at=issued.expires_at, account=AccountOut.of(account))


@router.post("/auth/verify")
async def verify(payload: CodeRequest, request: Request, session: Session) -> dict[str, bool]:
    raise HTTPException(410, "Email verification is no longer required. Update the app to create an account.")


@router.post("/auth/password/forgot", status_code=202)
async def forgot(payload: EmailRequest, request: Request, session: Session) -> dict[str, str]:
    await email_auth.rate_limit(request, payload.email, "send")
    code = f"{secrets.randbelow(100_000_000):08d}"
    digest = await email_auth.hash_password(code)
    if await EmailAccountRepository(session).set_code(payload.email, "reset", digest):
        await email_auth.send_code(payload.email, code, "reset")
    return _NOTICE


@router.post("/auth/password/reset")
async def reset(payload: CodeRequest, request: Request, session: Session) -> dict[str, bool]:
    await finish_code(payload, request, session, "reset")
    return {"reset": True}


async def finish_code(payload: CodeRequest, request: Request, session: Session, purpose: str) -> None:
    await email_auth.rate_limit(request, payload.email, "code")
    repo = EmailAccountRepository(session)
    digest = await repo.active_code(payload.email, purpose)
    valid = await email_auth.check_password(payload.code, digest)
    if not valid:
        raise HTTPException(400, "Code expired or incorrect. Request a new code.")
    encoded = await email_auth.hash_password(payload.password)
    credential = await repo.consume_code(payload.email, purpose, digest, encoded)
    if credential is None:
        raise HTTPException(400, "Code expired or incorrect. Request a new code.")
    await AccountSessionRepository(session).revoke_all(credential.account_id)


@router.post("/auth/session", status_code=201)
async def sign_in(payload: SignInRequest, request: Request, session: Session) -> SignInResponse:
    await email_auth.rate_limit(request, payload.email, "login")
    repo = EmailAccountRepository(session)
    credential = await repo.credentials(payload.email)
    valid = await email_auth.check_password(payload.password, credential.password_hash if credential else None)
    if not valid or not credential:
        raise HTTPException(401, "Email or password is incorrect.")
    # A reset may have completed while hashing. Lock and recheck before
    # issuing a session so its revocation cannot miss this new session.
    current = await repo.credentials(payload.email, lock=True)
    if current is None or current.password_hash != credential.password_hash:
        raise HTTPException(401, "Your password changed. Sign in again.")
    account = await repo.get(current.account_id)
    issued = await AccountSessionRepository(session).issue(account.id)
    return SignInResponse(token=issued.token, expires_at=issued.expires_at, account=AccountOut.of(account))


@router.delete("/auth/session", status_code=204)
async def sign_out(session: Session, authorization: Annotated[str | None, Header()] = None) -> Response:
    # Idempotent even after expiry; revoke only the token supplied by this device.
    if authorization and authorization.lower().startswith("bearer "):
        await AccountSessionRepository(session).revoke(authorization.split(" ", 1)[1].strip())
    return Response(status_code=204)


@router.get("/auth/me")
async def whoami(account: CurrentAccount) -> AccountOut:
    return AccountOut.of(account)


@router.post("/accounts/me/delete", status_code=204)
async def delete_account(
    payload: DeleteAccountRequest,
    account: CurrentAccount,
    session: Session,
    request: Request,
) -> Response:
    await email_auth.rate_limit(request, str(account.id), "login")
    if account.auth_provider == "email":
        credentials = await EmailAccountRepository(session).credentials_for_account(account.id, lock=True)
        valid = await email_auth.check_password(
            payload.current_password.get_secret_value() if payload.current_password else "",
            credentials.password_hash if credentials else None,
        )
    elif payload.social_identity is not None:
        proof = payload.social_identity
        claims = await social_auth.verify_identity(
            account.auth_provider, proof.id_token.get_secret_value(), proof.nonce,
        )
        valid = await SocialAccountRepository(session).matches(account.id, account.auth_provider, claims["sub"])
        if valid and account.auth_provider == "apple":
            await social_auth.revoke_apple(
                proof.authorization_code.get_secret_value() if proof.authorization_code else None,
                claims["sub"], proof.nonce,
            )
    else:
        valid = False
    if not valid:
        raise HTTPException(401, "Confirm your identity using this account's sign-in method.")
    accounts = AccountRepository(session)
    storage_keys = await accounts.attachment_storage_keys_for_account(account.id)
    trip_ids = await accounts.delete_personal_data(account.id)
    storage_root = Path(settings.attachment_upload_dir).resolve()
    for storage_key in storage_keys:
        target = (storage_root / storage_key).resolve()
        if target.is_relative_to(storage_root):
            target.unlink(missing_ok=True)
    try:
        checkpointer = get_graph().checkpointer
    except RuntimeError:
        checkpointer = None
    if checkpointer is not None:
        for trip_id in trip_ids:
            await checkpointer.adelete_thread(str(trip_id))
    return Response(status_code=204)


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
