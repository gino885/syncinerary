import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def identity_keys(monkeypatch):
    from pydantic import SecretStr

    from syncinerary.api import social_auth
    from syncinerary.config import settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public.update(kid="test-key", alg="RS256", use="sig")

    async def keys(provider):
        return {"keys": [public]}

    monkeypatch.setattr(social_auth, "provider_keys", keys)
    monkeypatch.setattr(settings, "google_oauth_client_id", "test.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "apple_oauth_client_id", "com.test.syncinerary")
    monkeypatch.setattr(settings, "apple_oauth_client_secret", SecretStr("test-client-secret"))
    return key


def token(key, provider, issued_nonce, **overrides):
    claims = {
        "iss": "https://accounts.google.com" if provider == "google" else "https://appleid.apple.com",
        "aud": "test.apps.googleusercontent.com" if provider == "google" else "com.test.syncinerary",
        "sub": "stable-subject", "iat": int(time.time()), "exp": int(time.time()) + 300,
        "nonce": issued_nonce, "name": "Mei", "email": "mei@example.com", "email_verified": True,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


async def challenge(client, provider):
    response = await client.post(f"/auth/{provider}/challenge")
    assert response.status_code == 200, response.text
    return response.json()["nonce"]


@pytest.mark.parametrize("provider", ["google", "apple"])
async def test_social_identity_is_stable_single_use_and_never_linked_by_email(
    client, auth_mail, identity_keys, provider,
):
    existing = await client.post("/auth/register", json={
        "email": "mei@example.com", "display_name": "Email account", "password": "abcdefgh",
    })
    assert existing.status_code == 201
    nonce = await challenge(client, provider)
    payload = {"nonce": nonce, "id_token": token(identity_keys, provider, nonce), "display_name": "Mei"}
    first = await client.post(f"/auth/{provider}/session", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["account"]["id"] != existing.json()["account"]["id"]
    assert first.json()["account"]["auth_provider"] == provider
    assert (await client.post(f"/auth/{provider}/session", json=payload)).status_code == 401
    nonce = await challenge(client, provider)
    second = await client.post(f"/auth/{provider}/session", json={
        "nonce": nonce, "id_token": token(identity_keys, provider, nonce, email="changed@example.com"),
    })
    assert second.status_code == 201
    assert second.json()["account"]["id"] == first.json()["account"]["id"]
    assert auth_mail == []


@pytest.mark.parametrize("overrides", [
    {"aud": "other-app"}, {"iss": "https://attacker.example"},
    {"exp": 1}, {"nonce": "wrong-nonce"}, {"sub": ""},
])
async def test_provider_rejects_invalid_identity(client, auth_mail, identity_keys, overrides):
    nonce = await challenge(client, "google")
    response = await client.post("/auth/google/session", json={
        "nonce": nonce, "id_token": token(identity_keys, "google", nonce, **overrides),
    })
    assert response.status_code == 401


async def test_forgery_and_unissued_nonce_rejected(client, auth_mail, identity_keys):
    nonce = await challenge(client, "apple")
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    response = await client.post("/auth/apple/session", json={
        "nonce": nonce, "id_token": token(attacker_key, "apple", nonce),
    })
    assert response.status_code == 401
    nonce = uuid4().hex
    response = await client.post("/auth/apple/session", json={
        "nonce": nonce, "id_token": token(identity_keys, "apple", nonce),
    })
    assert response.status_code == 401


async def test_provider_not_configured_is_explicit(client, auth_mail, monkeypatch):
    from syncinerary.config import settings
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    response = await client.post("/auth/google/challenge")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


async def test_social_deletion_requires_same_provider_subject(client, auth_mail, identity_keys):
    nonce = await challenge(client, "google")
    signed = await client.post("/auth/google/session", json={
        "nonce": nonce, "id_token": token(identity_keys, "google", nonce),
    })
    headers = {"Authorization": f"Bearer {signed.json()['token']}"}
    wrong_password = await client.post("/accounts/me/delete", headers=headers, json={
        "confirmation": "DELETE", "current_password": "abcdefgh",
    })
    assert wrong_password.status_code == 401
    for subject, status in [("different-person", 401), ("stable-subject", 204)]:
        nonce = await challenge(client, "google")
        response = await client.post("/accounts/me/delete", headers=headers, json={
            "confirmation": "DELETE", "social_identity": {
                "nonce": nonce, "id_token": token(identity_keys, "google", nonce, sub=subject),
            },
        })
        assert response.status_code == status, response.text
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


@pytest.mark.parametrize("same_identity", [True, False])
async def test_apple_revocation_checks_exchanged_identity(identity_keys, monkeypatch, same_identity):
    import httpx
    from fastapi import HTTPException

    from syncinerary.api import social_auth

    requests = []
    nonce = "n" * 43

    def respond(request):
        requests.append(request)
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={
                "refresh_token": "test-refresh-token",
                "id_token": token(identity_keys, "apple", nonce,
                                  sub="stable-subject" if same_identity else "other-person"),
            })
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(social_auth.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    if same_identity:
        await social_auth.revoke_apple("fresh-authorization", "stable-subject", nonce)
        assert requests[-1].url.path == "/auth/revoke"
        assert b"test-refresh-token" in requests[-1].content
    else:
        with pytest.raises(HTTPException) as error:
            await social_auth.revoke_apple("fresh-authorization", "stable-subject", nonce)
        assert error.value.status_code == 401
        assert len(requests) == 1, "Never revoke an unrelated Apple identity"


async def test_provider_does_not_echo_oversized_identity_token(client):
    secret = "private-identity-token" * 900
    response = await client.post("/auth/google/session", json={"id_token": secret, "nonce": "n" * 43})
    assert response.status_code == 422
    assert "private-identity-token" not in response.text
