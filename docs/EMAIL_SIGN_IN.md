# Email sign-in setup and verification

Email/password signup creates the account and signs in immediately. There is
no signup verification email, and the address remains unverified. Passwords
must contain 8 to 128 characters. Duplicate emails cannot replace an account
or password. Google and Apple options are described in [provider setup](SOCIAL_SIGN_IN.md).

Password recovery still requires an emailed 8-digit code proving mailbox
ownership. Codes expire after 15 minutes, work once, and are invalidated by a
resend. Reset revokes every session. A network error during restoration keeps
the device credential and offers retry; a rejected token returns to sign-in.

Passwords and short email codes use Argon2id (19 MiB, two iterations, one lane).
Opaque session tokens are SHA-256 hashed in Postgres and kept in iOS Keychain.
Redis limits login, email sending, and code attempts by email and client IP;
Redis failure fails authentication closed. Requests must use HTTPS outside
loopback testing. Configure uvicorn's trusted proxy addresses explicitly if
running behind a proxy; do not trust arbitrary forwarded IP headers.

These choices follow the [OWASP password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
and [password recovery guidance](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

## Optional email delivery for password recovery

Install updated dependencies and migrate before starting the API:

```bash
uv pip install -e '.[dev]'
docker compose up -d
.venv/bin/alembic upgrade head
```

Set these in the server's gitignored `.env`, using your provider's values:

```dotenv
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-provider-username
SMTP_PASSWORD=your-provider-secret
SMTP_FROM=Syncinerary <noreply@your-verified-domain.example>
```

Use `SMTP_SECURITY=tls` and port 465 if your provider requires implicit TLS.
Verify the sending domain with that provider. Restart the API after editing
configuration. No real provider was configured by this change. Missing delivery
configuration returns an actionable 503, never a successful fake email.
`plain` transport is restricted to a loopback-only test inbox.

Both you and your friend choose Create account and enter your own email/name
and password. You are signed in immediately. Returning users choose Sign in. Forgot
password sends a new code and lets the recipient set a replacement password.
Accounts left pending by the old verification flow can be recovered with
Forgot password once SMTP is configured. The old verification endpoint is retired.

## iPhone Password AutoFill

Create account starts with a blank email and name. The email input is tagged
as the account username, sign-in uses the existing-password type, and signup
and reset use the new-password type. The username field stays present during
password recovery so iOS can associate the credential fields.

Automatic password saving and domain-matched suggestions are deferred until
the Apple Developer setup is ready. Configure the Associated Domains
capability with `webcredentials:YOUR-HTTPS-DOMAIN`, then serve the matching
`webcredentials.apps` entry (`TEAM_ID.BUNDLE_ID`) at
`https://YOUR-HTTPS-DOMAIN/.well-known/apple-app-site-association` without
redirects. Use the actual signing team, bundle ID, and domain. No placeholder
entitlement is installed in the development app.

Validate saving and subsequent AutoFill on a signed physical iPhone with
Password AutoFill enabled. The app does not store raw passwords in defaults
or its session Keychain. See [Apple's associated-domain guide](https://developer.apple.com/documentation/xcode/supporting-associated-domains).

## Existing prototype identities

Migration `b138df027ec5` expires existing handle-only sessions. It preserves
accounts, trips, votes, and itineraries. A new email signup creates a new
identity; it does not claim an old handle or its trips. Rejoin a trip using an
existing invite where possible. Any transfer of an old leader account needs an
explicit administrator ownership check. The migration does not guess ownership.

## Repeat the checks

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check syncinerary tests
.venv/bin/python scripts/smoke_email_trip.py
```

The smoke script creates a disposable database, runs migration
upgrade/downgrade/upgrade, starts the real API plus a local SMTP inbox, verifies
three accounts, exercises reset/logout, then removes its services and database.
It sends no real email and calls no discovery vendors. `--hold` retains this
local sandbox until interrupted for simulator UI testing.

The checked-in account, itinerary, and preparation Swift tests cover API wire
contracts and view-model state transitions. Build the simulator app with normal
Xcode signing for Keychain tests; `CODE_SIGNING_ALLOWED=NO` is a compile check
and cannot establish that credentials persist across launches.

Email authentication does not complete the authorization audit of legacy trip
and WebSocket routes. Keep the backend private until that review, production
SMTP, HTTPS, backups, and real-device checks are complete. Hotel selection is
saved, but hotel-to-stop routing remains an existing separate gap.
