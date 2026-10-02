from fastapi import APIRouter, Request

from syncinerary.api import email_auth, social_auth
from syncinerary.api.auth_schemas import SocialSignInRequest
from syncinerary.api.deps import Session
from syncinerary.api.schemas import AccountOut, SignInResponse
from syncinerary.store.repositories import AccountSessionRepository
from syncinerary.store.repositories.social_accounts import SocialAccountRepository

router = APIRouter(tags=["accounts"])


@router.post("/auth/{provider}/challenge")
async def challenge(provider: social_auth.Provider, request: Request) -> dict[str, str]:
    host = request.client.host if request.client else "unknown"
    await email_auth.rate_limit(request, host, "login")
    return await social_auth.challenge(provider)


@router.post("/auth/{provider}/session", status_code=201)
async def sign_in(provider: social_auth.Provider, payload: SocialSignInRequest,
                  request: Request, session: Session) -> SignInResponse:
    await email_auth.rate_limit(request, payload.nonce, "login")
    claims = await social_auth.verify_identity(provider, payload.id_token.get_secret_value(), payload.nonce)
    name = (claims.get("name") if provider == "google" else payload.display_name) or "Traveler"
    name = name.strip()[:60] if isinstance(name, str) else "Traveler"
    account = await SocialAccountRepository(session).sign_in(provider, claims["sub"], name or "Traveler")
    issued = await AccountSessionRepository(session).issue(account.id)
    return SignInResponse(token=issued.token, expires_at=issued.expires_at, account=AccountOut.of(account))
