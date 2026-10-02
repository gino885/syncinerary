"""Release-critical privacy consent and in-app account deletion."""

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from syncinerary.api.trip_membership import require_websocket_member
from syncinerary.store import tables

PASSWORD = "a long unique deletion passphrase"


async def _account(client, mail, name: str):
    email = f"release-{uuid4().hex}@example.com"
    registered = await client.post(
        "/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert registered.status_code == 201
    signed_in = await client.post(
        "/auth/session",
        json={"email": email, "password": PASSWORD},
    )
    assert signed_in.status_code == 201
    payload = signed_in.json()
    return payload["account"], {
        "Authorization": f"Bearer {payload['token']}"
    }


async def _trip_with_member(client, mail):
    owner, owner_headers = await _account(client, mail, "Owner")
    member, member_headers = await _account(client, mail, "Friend")
    created = await client.post(
        "/trips",
        headers=owner_headers,
        json={
            "cities": ["Tokyo"],
            "city_days": [2],
            "country": "Japan",
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
            "creator_name": "Owner",
        },
    )
    assert created.status_code == 201, created.text
    trip_id = created.json()["trip"]["id"]
    invite = await client.post(
        f"/trips/{trip_id}/invites",
        headers=owner_headers,
        json={},
    )
    assert invite.status_code == 201
    joined = await client.post(
        f"/invites/{invite.json()['code']}/join",
        headers=member_headers,
        json={"preference_tags": ["food", "art"]},
    )
    assert joined.status_code == 201
    return owner, owner_headers, member, member_headers, trip_id, joined.json()["traveler_id"]


async def test_each_account_controls_anthropic_data_sharing_consent(client, auth_mail):
    account, headers = await _account(client, auth_mail, "Mei")

    status = await client.get("/accounts/me/ai-consent", headers=headers)
    assert status.status_code == 200
    assert status.json() == {
        "anthropic": False,
        "policy_version": None,
        "granted_at": None,
    }

    granted = await client.put(
        "/accounts/me/ai-consent",
        headers=headers,
        json={"consent_to_anthropic": True},
    )
    assert granted.status_code == 200
    assert granted.json()["anthropic"] is True
    assert granted.json()["policy_version"]

    revoked = await client.delete("/accounts/me/ai-consent", headers=headers)
    assert revoked.status_code == 204
    assert (await client.get("/accounts/me/ai-consent", headers=headers)).json()[
        "anthropic"
    ] is False
    assert (await client.get("/auth/me", headers=headers)).json()["id"] == account["id"]


async def test_trip_ai_work_requires_every_account_member_consent(
    client,
    auth_mail,
    creator_anthropic_credential,
):
    _, owner_headers, _, member_headers, trip_id, _ = await _trip_with_member(
        client, auth_mail
    )
    await creator_anthropic_credential(trip_id)

    blocked = await client.post(
        f"/trips/{trip_id}/gather-runs",
        headers=owner_headers,
        json={},
    )
    assert blocked.status_code == 409
    assert "every trip member" in blocked.json()["detail"].lower()

    consented = await client.put(
        "/accounts/me/ai-consent",
        headers=member_headers,
        json={"consent_to_anthropic": True},
    )
    assert consented.status_code == 200
    started = await client.post(
        f"/trips/{trip_id}/gather-runs",
        headers=owner_headers,
        json={},
    )
    assert started.status_code == 202, started.text


async def test_account_deletion_reauthenticates_and_removes_joined_contributions(
    client,
    session,
    auth_mail,
    monkeypatch,
    tmp_path,
):
    from syncinerary.config import settings
    from syncinerary.domain.models import (
        AttachmentInputType,
        AttachmentStatus,
        SocialPlatform,
        SourceAttachment,
    )
    from syncinerary.store.repositories import SourceAttachmentRepository

    owner, _, member, member_headers, trip_id, member_traveler_id = (
        await _trip_with_member(client, auth_mail)
    )
    message = await client.post(
        f"/trips/{trip_id}/messages",
        headers=member_headers,
        json={"body": "My private contribution"},
    )
    assert message.status_code == 201
    monkeypatch.setattr(settings, "attachment_upload_dir", str(tmp_path))
    storage_key = f"{trip_id}/private.png"
    screenshot = tmp_path / storage_key
    screenshot.parent.mkdir(parents=True)
    screenshot.write_bytes(b"private screenshot")
    await SourceAttachmentRepository(session).add(
        SourceAttachment(
            trip_id=UUID(trip_id),
            traveler_id=UUID(member_traveler_id),
            platform=SocialPlatform.INSTAGRAM,
            input_type=AttachmentInputType.LINK,
            status=AttachmentStatus.READY,
            original_url="https://www.instagram.com/p/private/",
            canonical_url="https://www.instagram.com/p/private/",
            platform_id="private",
            screenshot_storage_key=storage_key,
        )
    )

    wrong = await client.post(
        "/accounts/me/delete",
        headers=member_headers,
        json={"current_password": "wrong password that is long enough", "confirmation": "DELETE"},
    )
    assert wrong.status_code == 401
    assert await session.get(tables.Account, member["id"]) is not None

    deleted = await client.post(
        "/accounts/me/delete",
        headers=member_headers,
        json={"current_password": PASSWORD, "confirmation": "DELETE"},
    )
    assert deleted.status_code == 204, deleted.text
    assert (await client.get("/auth/me", headers=member_headers)).status_code == 401
    assert await session.get(tables.Account, member["id"]) is None
    assert await session.get(tables.Trip, trip_id) is not None
    assert await session.get(tables.Account, owner["id"]) is not None
    assert await session.get(tables.Traveler, member_traveler_id) is None
    assert not screenshot.exists()
    bodies = list(
        await session.scalars(
            select(tables.TripMessage.body).where(tables.TripMessage.trip_id == trip_id)
        )
    )
    assert "My private contribution" not in bodies


async def test_deleting_creator_account_removes_owned_trips(client, session, auth_mail):
    owner, owner_headers, member, _, trip_id, _ = await _trip_with_member(
        client, auth_mail
    )

    deleted = await client.post(
        "/accounts/me/delete",
        headers=owner_headers,
        json={"current_password": PASSWORD, "confirmation": "DELETE"},
    )

    assert deleted.status_code == 204, deleted.text
    assert await session.get(tables.Account, owner["id"]) is None
    assert await session.get(tables.Trip, trip_id) is None
    assert await session.get(tables.Account, member["id"]) is not None


async def test_account_deletion_validation_never_echoes_password(client, auth_mail):
    _, headers = await _account(client, auth_mail, "Mei")
    secret = "do-not-echo-this-deletion-password"
    response = await client.post(
        "/accounts/me/delete",
        headers=headers,
        json={"current_password": secret, "confirmation": "not-delete"},
    )
    assert response.status_code == 422
    assert secret not in response.text


async def test_websocket_membership_requires_the_matching_bearer_session(
    client,
    session,
    auth_mail,
):
    _, owner_headers, _, member_headers, trip_id, member_traveler_id = (
        await _trip_with_member(client, auth_mail)
    )
    trip_id = UUID(trip_id)
    member_traveler_id = UUID(member_traveler_id)

    with pytest.raises(HTTPException) as missing:
        await require_websocket_member(
            session,
            trip_id=trip_id,
            traveler_id=member_traveler_id,
            authorization=None,
        )
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong_account:
        await require_websocket_member(
            session,
            trip_id=trip_id,
            traveler_id=member_traveler_id,
            authorization=owner_headers["Authorization"],
        )
    assert wrong_account.value.status_code == 403

    traveler = await require_websocket_member(
        session,
        trip_id=trip_id,
        traveler_id=member_traveler_id,
        authorization=member_headers["Authorization"],
    )
    assert traveler.id == member_traveler_id


async def test_trip_data_is_not_readable_by_an_outside_account(client, auth_mail):
    _, owner_headers = await _account(client, auth_mail, "Owner")
    _, outsider_headers = await _account(client, auth_mail, "Outsider")
    created = await client.post(
        "/trips",
        headers=owner_headers,
        json={
            "cities": ["Tokyo"],
            "city_days": [2],
            "country": "Japan",
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
            "creator_name": "Owner",
        },
    )
    assert created.status_code == 201
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    for path in (
        f"/trips/{trip_id}",
        f"/trips/{trip_id}/candidates",
        f"/trips/{trip_id}/lodging-options",
        f"/trips/{trip_id}/votes/progress?traveler_id={traveler_id}",
    ):
        missing = await client.get(path)
        outsider = await client.get(path, headers=outsider_headers)
        assert missing.status_code == 403, path
        assert outsider.status_code == 403, path
