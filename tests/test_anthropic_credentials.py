"""Account-owned Anthropic credentials and creator-funded trip execution."""

from __future__ import annotations

import base64
import os

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.asyncio


@pytest.fixture
def credential_keyring(monkeypatch):
    from syncinerary.config import settings

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(
        settings,
        "sync_credential_encryption_keys",
        SecretStr(f'{{"1":"{key}"}}'),
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "sync_credential_encryption_active_version",
        1,
        raising=False,
    )
    return key


async def test_credential_endpoints_require_authentication(client):
    endpoint = "/accounts/me/anthropic-key"

    assert (await client.get(endpoint)).status_code == 401
    assert (
        await client.put(
            endpoint,
            json={"api_key": "sk-ant-api03-not-a-real-key", "consent_to_anthropic": True},
        )
    ).status_code == 401
    assert (await client.delete(endpoint)).status_code == 401


async def test_account_can_store_replace_and_remove_credential_without_reading_it_back(
    signed_in_client,
    session,
    credential_keyring,
):
    from sqlalchemy import select

    from syncinerary.store import tables

    endpoint = "/accounts/me/anthropic-key"
    original = "sk-ant-api03-original-secret-value"
    replacement = "sk-ant-api03-replacement-secret-value"

    # The shared signed-in fixture carries a test-only key so legacy model
    # routes can exercise their stubs under the production BYOK rule.
    assert (await signed_in_client.delete(endpoint)).status_code == 204
    empty = await signed_in_client.get(endpoint)
    assert empty.status_code == 200
    assert empty.json() == {"configured": False, "last_four": None, "updated_at": None}

    rejected = await signed_in_client.put(
        endpoint,
        json={"api_key": original, "consent_to_anthropic": False},
    )
    assert rejected.status_code == 422
    assert original not in rejected.text

    saved = await signed_in_client.put(
        endpoint,
        json={"api_key": f" \n{original}\r\n ", "consent_to_anthropic": True},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True
    assert saved.json()["last_four"] == "alue"
    assert "api_key" not in saved.json()
    assert original not in saved.text

    row = await session.scalar(select(tables.AnthropicCredential))
    assert row is not None
    assert original.encode() not in row.ciphertext

    replaced = await signed_in_client.put(
        endpoint,
        json={"api_key": replacement, "consent_to_anthropic": True},
    )
    assert replaced.status_code == 200
    assert replaced.json()["last_four"] == "alue"
    row = await session.scalar(select(tables.AnthropicCredential))
    assert row is not None
    assert replacement.encode() not in row.ciphertext

    removed = await signed_in_client.delete(endpoint)
    assert removed.status_code == 204
    assert (await signed_in_client.get(endpoint)).json()["configured"] is False


async def test_ciphertext_is_bound_to_its_account_and_key_version(credential_keyring):
    from uuid import uuid4

    from syncinerary.security.credentials import CredentialCipher, CredentialDecryptionError

    cipher = CredentialCipher.from_settings()
    owner = uuid4()
    other = uuid4()
    encrypted = cipher.encrypt(owner, SecretStr("sk-ant-api03-test-secret"))

    assert cipher.decrypt(owner, encrypted).get_secret_value() == "sk-ant-api03-test-secret"
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(other, encrypted)
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(owner, encrypted.model_copy(update={"key_version": 999}))


async def test_harness_uses_scoped_key_and_restores_server_default(monkeypatch):
    from syncinerary.config import settings
    from syncinerary.harness import wrapper

    seen: list[str | None] = []

    class Client:
        def __init__(self, *, api_key=None):
            seen.append(api_key)
            self.messages = object()

    monkeypatch.setattr(settings, "anthropic_api_key", "server-default")
    monkeypatch.setattr(wrapper, "_anthropic_client_factory", Client)

    wrapper.make_messages_client()
    with wrapper.use_anthropic_api_key(SecretStr("creator-secret")):
        wrapper.make_messages_client()
    wrapper.make_messages_client()

    assert seen == ["server-default", "creator-secret", "server-default"]

    with wrapper.require_anthropic_api_key(None), pytest.raises(
        wrapper.CreatorCredentialUnavailable
    ):
        wrapper.make_messages_client()
    wrapper.make_messages_client()
    assert seen[-1] == "server-default"


async def test_gather_snapshot_records_creator_account_not_plaintext_key(
    signed_in_client,
    session,
    credential_keyring,
):
    from uuid import UUID

    from syncinerary.store.repositories import GatherRunRepository
    from tests.test_m7a_group_api import _auth, _owner_trip, _sign_in

    owner = await _sign_in(signed_in_client, display_name="Leader", handle="byok-owner")
    created = await _owner_trip(signed_in_client, owner)
    secret = "sk-ant-api03-owner-funded-trip-secret"
    stored = await signed_in_client.put(
        "/accounts/me/anthropic-key",
        headers=_auth(owner["token"]),
        json={"api_key": secret, "consent_to_anthropic": True},
    )
    assert stored.status_code == 200, stored.text

    started = await signed_in_client.post(
        f"/trips/{created['trip']['id']}/gather-runs",
        headers=_auth(owner["token"]),
    )
    assert started.status_code == 202, started.text
    run = await GatherRunRepository(session).get(UUID(started.json()["run_id"]))
    assert run.credential_account_id == UUID(owner["account"]["id"])
    assert secret not in run.model_dump_json()


async def test_creator_cannot_start_billable_discovery_without_a_key(client):
    from tests.test_m7a_group_api import _auth, _owner_trip, _sign_in

    owner = await _sign_in(client, display_name="Leader", handle="missing-byok")
    created = await _owner_trip(client, owner)

    response = await client.post(
        f"/trips/{created['trip']['id']}/gather-runs",
        headers=_auth(owner["token"]),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Add your Anthropic API key in AI access before starting discovery"
    )


async def test_durable_worker_scopes_creator_key_without_putting_it_in_the_job(
    monkeypatch,
):
    from contextlib import asynccontextmanager
    from datetime import date
    from types import SimpleNamespace
    from uuid import uuid4

    from syncinerary.domain.gather import GatherInput, GatherRun
    from syncinerary.domain.models import Trip
    from syncinerary.harness import wrapper
    from syncinerary.workers import gather as worker

    owner_id = uuid4()
    trip = Trip(
        destination="Tokyo",
        days=1,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
    )
    run = GatherRun(
        trip_id=trip.id,
        credential_account_id=owner_id,
        input_snapshot=GatherInput(
            trip=trip,
            travelers=[],
            constraints=[],
            attachments=[],
        ),
    )
    seen: list[str | None] = []

    class Credentials:
        def __init__(self, _session):
            pass

        async def reveal(self, account_id):
            assert account_id == owner_id
            return SecretStr("sk-ant-api03-worker-secret")

    class Accounts:
        def __init__(self, _session):
            pass

        async def missing_anthropic_consent_for_trip(self, _trip_id):
            return []

    class Client:
        def __init__(self, *, api_key=None):
            seen.append(api_key)
            self.messages = object()

    @asynccontextmanager
    async def scope():
        yield object()

    async def exercise_scope(_run, _graph):
        wrapper.make_messages_client()

    monkeypatch.setattr(worker, "AnthropicCredentialRepository", Credentials)
    monkeypatch.setattr(worker, "AccountRepository", Accounts)
    monkeypatch.setattr(worker, "session_scope", scope)
    monkeypatch.setattr(worker, "_execute_run", exercise_scope)
    monkeypatch.setattr(wrapper, "_anthropic_client_factory", Client)

    await worker.execute_run(run, SimpleNamespace())
    assert seen == ["sk-ant-api03-worker-secret"]


async def test_durable_worker_refuses_server_key_for_an_unconfigured_creator(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import date
    from uuid import uuid4

    from syncinerary.domain.gather import GatherInput, GatherRun
    from syncinerary.domain.models import Trip
    from syncinerary.workers import gather as worker

    trip = Trip(
        destination="Tokyo",
        days=1,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
    )
    run = GatherRun(
        trip_id=trip.id,
        credential_account_id=uuid4(),
        input_snapshot=GatherInput(
            trip=trip,
            travelers=[],
            constraints=[],
            attachments=[],
        ),
    )

    class Credentials:
        def __init__(self, _session):
            pass

        async def reveal(self, _account_id):
            return None

    class Accounts:
        def __init__(self, _session):
            pass

        async def missing_anthropic_consent_for_trip(self, _trip_id):
            return []

    @asynccontextmanager
    async def scope():
        yield object()

    monkeypatch.setattr(worker, "AnthropicCredentialRepository", Credentials)
    monkeypatch.setattr(worker, "AccountRepository", Accounts)
    monkeypatch.setattr(worker, "session_scope", scope)

    with pytest.raises(worker.CreatorCredentialUnavailable):
        await worker.execute_run(run, object())
