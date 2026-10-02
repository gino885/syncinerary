from uuid import uuid4


async def test_signup_immediately_issues_session_without_email(client, auth_mail, session):
    from syncinerary.store.repositories.credentials import EmailAccountRepository

    email = f"signup-{uuid4().hex}@example.com"
    response = await client.post("/auth/register", json={
        "email": email, "display_name": "Mei", "password": "abcdefgh",
    })
    assert response.status_code == 201, response.text
    assert auth_mail == []
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    assert (await client.get("/auth/me", headers=headers)).json()["display_name"] == "Mei"
    credential = await EmailAccountRepository(session).credentials(email)
    assert credential.verified_at is None, "Skipping verification must not claim email ownership"
    assert credential.password_hash.startswith("$argon2id$")
    signed = await client.post("/auth/session", json={"email": email, "password": "abcdefgh"})
    assert signed.status_code == 201
    duplicate = await client.post("/auth/register", json={
        "email": email.upper(), "display_name": "Imposter", "password": "different password",
    })
    assert duplicate.status_code == 409
    assert (await client.get("/auth/me", headers=headers)).json()["display_name"] == "Mei"


async def test_signup_requires_password_and_rejects_legacy_code_path(client, auth_mail):
    for password in (None, "a" * 7, "a" * 129):
        payload = {"email": "new@example.com", "display_name": "Mei"}
        if password is not None:
            payload["password"] = password
        response = await client.post("/auth/register", json=payload)
        assert response.status_code == 422
    response = await client.post("/auth/verify", json={
        "email": "new@example.com", "code": "12345678", "password": "abcdefgh",
    })
    assert response.status_code == 410


async def test_old_pending_signup_requires_mailbox_recovery(client, auth_mail, session):
    from syncinerary.store.repositories.credentials import EmailAccountRepository

    email = f"pending-{uuid4().hex}@example.com"
    await EmailAccountRepository(session).register(email, "Existing name")
    signup = await client.post("/auth/register", json={
        "email": email, "display_name": "Unproven name", "password": "abcdefgh",
    })
    assert signup.status_code == 409
    assert auth_mail == []
    assert (await client.post("/auth/password/forgot", json={"email": email})).status_code == 202
    reset = await client.post("/auth/password/reset", json={
        "email": email, "code": auth_mail[-1][1], "password": "abcdefgh",
    })
    assert reset.status_code == 200
    signed = await client.post("/auth/session", json={"email": email, "password": "abcdefgh"})
    assert signed.status_code == 201
    assert signed.json()["account"]["display_name"] == "Existing name"
