"""Verify provider-signed identities and consume short-lived, single-use nonces."""
import hashlib
import json
import secrets
from typing import Literal

import httpx
import jwt
from fastapi import HTTPException
from redis.exceptions import RedisError

from syncinerary.config import settings
from syncinerary.store.redis import get_redis

Provider = Literal["google", "apple"]
_KEY_URLS = {
    "google": "https://www.googleapis.com/oauth2/v3/certs",
    "apple": "https://appleid.apple.com/auth/keys",
}
_ISSUERS = {
    "google": ["https://accounts.google.com", "accounts.google.com"],
    "apple": ["https://appleid.apple.com"],
}


def client_id(provider: Provider) -> str:
    value = getattr(settings, f"{provider}_oauth_client_id").strip()
    if not value or (provider == "apple" and not settings.apple_oauth_client_secret.get_secret_value()):
        raise HTTPException(503, f"{provider.title()} sign-in is not configured yet. Use email for now.")
    return value


async def revoke_apple(authorization_code: str | None, subject: str, nonce: str) -> None:
    """Exchange a fresh deletion authorization, then revoke its Apple grant."""
    if not authorization_code:
        raise HTTPException(401, "Confirm your Apple account again to delete your account.")
    credentials = {
        "client_id": client_id("apple"),
        "client_secret": settings.apple_oauth_client_secret.get_secret_value(),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://appleid.apple.com/auth/token", data={
                **credentials, "code": authorization_code, "grant_type": "authorization_code",
            })
            response.raise_for_status()
            result = response.json()
            claims = await token_claims("apple", result["id_token"], nonce)
            if claims["sub"] != subject:
                raise HTTPException(401, "Confirm the same Apple account again.")
            refresh_token = result["refresh_token"]
            if not isinstance(refresh_token, str) or not refresh_token:
                raise ValueError("Missing Apple refresh token")
            revoked = await client.post("https://appleid.apple.com/auth/revoke", data={
                **credentials, "token": refresh_token, "token_type_hint": "refresh_token",
            })
            revoked.raise_for_status()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(503, "Could not disconnect Apple. Try deleting your account again.") from exc


def nonce_key(provider: Provider, nonce: str) -> str:
    digest = hashlib.sha256(nonce.encode()).hexdigest()
    return f"auth:oauth:{provider}:nonce:{digest}"


async def challenge(provider: Provider) -> dict[str, str]:
    audience = client_id(provider)
    nonce = secrets.token_urlsafe(32)
    try:
        await get_redis().set(nonce_key(provider, nonce), "1", ex=300, nx=True)
    except RedisError as exc:
        raise HTTPException(503, "Sign-in is temporarily unavailable. Try again shortly.") from exc
    return {"nonce": nonce, "client_id": audience}


async def provider_keys(provider: Provider) -> dict:
    cache_key = f"auth:oauth:{provider}:jwks"
    cached = await get_redis().get(cache_key)
    if cached:
        return json.loads(cached)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(_KEY_URLS[provider])
        response.raise_for_status()
        keys = response.json()
    await get_redis().set(cache_key, json.dumps(keys), ex=300)
    return keys


async def token_claims(provider: Provider, id_token: str, nonce: str) -> dict:
    audience = client_id(provider)
    try:
        # Fixed URLs and algorithm: never follow token-supplied jku/x5u values.
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256":
            raise jwt.InvalidTokenError()
        keyset = jwt.PyJWKSet.from_dict(await provider_keys(provider))
        key = keyset[header.get("kid", "")]
        claims = jwt.decode(id_token, key.key, algorithms=["RS256"],
                            audience=audience, issuer=_ISSUERS[provider],
                            options={"require": ["sub", "iss", "aud", "exp", "iat", "nonce"]})
        if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 255:
            raise jwt.InvalidTokenError()
        if not isinstance(claims["nonce"], str) or not secrets.compare_digest(claims["nonce"], nonce):
            raise jwt.InvalidTokenError()
        if claims.get("azp", audience) != audience:
            raise jwt.InvalidTokenError()
        return claims
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Sign-in expired or could not be verified. Try again.") from exc
    except (httpx.HTTPError, RedisError) as exc:
        raise HTTPException(503, "Sign-in is temporarily unavailable. Try again shortly.") from exc


async def verify_identity(provider: Provider, id_token: str, nonce: str) -> dict:
    claims = await token_claims(provider, id_token, nonce)
    try:
        if not await get_redis().getdel(nonce_key(provider, nonce)):
            raise HTTPException(401, "Sign-in expired or could not be verified. Try again.")
    except RedisError as exc:
        raise HTTPException(503, "Sign-in is temporarily unavailable. Try again shortly.") from exc
    return claims
