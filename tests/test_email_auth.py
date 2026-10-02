"""Password identity and recovery, using a real DB and captured recovery delivery."""
from uuid import uuid4

PASSWORD = "a long unique test passphrase"


async def register(client, mail, password=PASSWORD):
    email = f"qa-{uuid4().hex}@example.com"
    before = len(mail)
    response = await client.post("/auth/register", json={
        "email": email, "display_name": "Mei", "password": password,
    })
    assert response.status_code == 201, response.text
    assert len(mail) == before
    return email


async def login(client, email, password=PASSWORD):
    return await client.post("/auth/session", json={"email": email, "password": password})


async def test_password_sign_in_and_logout(client, auth_mail):
    email = await register(client, auth_mail)
    assert (await login(client, email, "wrong password that is long enough")).status_code == 401
    signed = await login(client, email.upper())
    assert signed.status_code == 201, signed.text
    headers = {"Authorization": f"Bearer {signed.json()['token']}"}
    assert (await client.get("/auth/me", headers=headers)).json()["display_name"] == "Mei"
    assert (await client.delete("/auth/session", headers=headers)).status_code == 204
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_reset_revokes_all_sessions_and_is_single_use(client, auth_mail):
    email = await register(client, auth_mail)
    tokens = [(await login(client, email)).json()["token"] for _ in range(2)]
    sent = await client.post("/auth/password/forgot", json={"email": email})
    assert sent.status_code == 202
    new_password = "a different long test passphrase"
    payload = {"email": email, "code": auth_mail[-1][1], "password": new_password}
    reset = await client.post("/auth/password/reset", json=payload)
    assert reset.status_code == 200, reset.text
    assert (await client.post("/auth/password/reset", json=payload)).status_code == 400
    assert (await login(client, email)).status_code == 401
    assert (await login(client, email, new_password)).status_code == 201
    for token in tokens:
        assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_unknown_email_cannot_reset_or_claim_legacy_handle(client, auth_mail):
    unknown = await client.post("/auth/password/forgot", json={"email": "unknown@example.com"})
    assert unknown.status_code == 202
    assert auth_mail == []
    assert (await client.post("/auth/session", json={"display_name": "Mei", "handle": "mei"})).status_code == 422
    assert (await client.post("/auth/password/reset", json={
        "email": "unknown@example.com", "code": "12345678", "password": PASSWORD,
    })).status_code == 400


async def test_invalid_inputs_and_rate_limit(client, auth_mail):
    email = await register(client, auth_mail)
    await client.post("/auth/password/forgot", json={"email": email})
    code = auth_mail[-1][1]
    weak = await client.post("/auth/password/reset", json={"email": email, "code": code, "password": "short"})
    assert weak.status_code == 422
    for _ in range(5):
        bad = await client.post("/auth/password/reset", json={
            "email": email, "code": "00000000" if code != "00000000" else "11111111", "password": PASSWORD,
        })
        assert bad.status_code == 400
    blocked = await client.post("/auth/password/reset", json={"email": email, "code": code, "password": PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


async def test_eight_character_password_supports_signup_reset_and_deletion(client, auth_mail):
    email = await register(client, auth_mail, "abcdefgh")
    assert (await login(client, email, "abcdefgh")).status_code == 201
    await client.post("/auth/password/forgot", json={"email": email})
    for invalid in ("a" * 7, "a" * 129):
        response = await client.post("/auth/password/reset", json={
            "email": email, "code": auth_mail[-1][1], "password": invalid,
        })
        assert response.status_code == 422
    reset = await client.post("/auth/password/reset", json={
        "email": email, "code": auth_mail[-1][1], "password": "12345678",
    })
    assert reset.status_code == 200, reset.text
    signed = await login(client, email, "12345678")
    assert signed.status_code == 201, signed.text
    deleted = await client.post("/accounts/me/delete", json={
        "current_password": "12345678", "confirmation": "DELETE",
    }, headers={"Authorization": f"Bearer {signed.json()['token']}"})
    assert deleted.status_code == 204, deleted.text


async def test_auth_validation_never_echoes_password(client):
    response = await client.post("/auth/session", json={"email": "invalid", "password": "do-not-echo-this-secret" * 20})
    assert response.status_code == 422
    assert "do-not-echo-this-secret" not in response.text


async def test_reset_resend_expiry_and_hashes(client, session, auth_mail):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, update

    from syncinerary.store import tables
    from syncinerary.store.repositories import AccountSessionRepository

    email = await register(client, auth_mail)
    await client.post("/auth/password/forgot", json={"email": email})
    old_code = auth_mail[-1][1]
    await client.post("/auth/password/forgot", json={"email": email})
    fresh = auth_mail[-1][1]
    if old_code != fresh:
        assert (await client.post("/auth/password/reset", json={"email": email, "code": old_code, "password": PASSWORD})).status_code == 400
    await session.execute(update(tables.Account).where(tables.Account.email == email).values(reset_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert (await client.post("/auth/password/reset", json={"email": email, "code": fresh, "password": PASSWORD})).status_code == 400
    await client.post("/auth/password/forgot", json={"email": email})
    assert (await client.post("/auth/password/reset", json={"email": email, "code": auth_mail[-1][1], "password": PASSWORD})).status_code == 200
    signed = await login(client, email)
    row = await session.scalar(select(tables.Account).where(tables.Account.email == email))
    assert row.password_hash.startswith("$argon2id$") and PASSWORD not in row.password_hash
    assert row.reset_digest is None
    stored = (await session.scalars(select(tables.AccountSession.token).where(tables.AccountSession.account_id == row.id))).all()
    assert AccountSessionRepository.digest(signed.json()["token"]) in stored
    assert signed.json()["token"] not in stored
    sent = len(auth_mail)
    duplicate = await client.post("/auth/register", json={"email": email, "display_name": "Attacker", "password": "other password"})
    assert duplicate.status_code == 409 and len(auth_mail) == sent
    assert (await login(client, email)).json()["account"]["display_name"] == "Mei"


async def test_registered_friends_share_preparation(client, auth_mail):
    people = []
    for _ in range(3):
        email = await register(client, auth_mail)
        people.append({"Authorization": f"Bearer {(await login(client, email)).json()['token']}"})
    owner, friend, outsider = people
    created = await client.post("/trips", headers=owner, json={
        "cities": ["Tokyo", "Atami", "Kamakura"], "city_days": [2, 1, 1],
        "country": "Japan", "start_date": "2026-10-01", "end_date": "2026-10-04", "creator_name": "Mei",
    })
    assert created.status_code == 201, created.text
    trip = created.json()["trip"]["id"]
    member = created.json()["traveler_id"]
    invited = await client.post(f"/trips/{trip}/invites", headers=owner, json={})
    assert invited.status_code == 201, invited.text
    code = invited.json()["code"]
    assert (await client.get(f"/invites/{code}")).status_code == 200
    joined = await client.post(f"/invites/{code}/join", headers=friend, json={"preference_tags": ["food", "scenery"]})
    assert joined.status_code == 201, joined.text
    friend_member = joined.json()["traveler_id"]
    path = f"/trips/{trip}/checklist"
    rows = (await client.post(path + "/prepare", headers=owner, json={"traveler_id": member})).json()
    assert len(rows) >= 3
    added = await client.post(path, headers=owner, json={"traveler_id": member, "title": "Save train tickets"})
    assert added.status_code == 201
    item = added.json()
    payload = {"traveler_id": friend_member, "title": item["title"], "notes": "Saved", "completed": True, "revision": item["revision"]}
    edited = await client.put(path + f"/{item['id']}", headers=friend, json=payload)
    assert edited.status_code == 200
    assert (await client.put(path + f"/{item['id']}", headers=friend, json=payload)).status_code == 409
    assert (await client.post(path + "/prepare", headers=outsider, json={"traveler_id": member})).status_code == 403
    refreshed = (await client.post(path + "/prepare", headers=owner, json={"traveler_id": member})).json()
    assert any(x["id"] == item["id"] and x["completed"] for x in refreshed)
    assert any(x["id"] == trip for x in (await client.get("/accounts/me/trips", headers=friend)).json())
