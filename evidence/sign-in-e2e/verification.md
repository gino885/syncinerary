# Verification, September 23, 2026

## Changes

Replaced handle-only login with verified email/password accounts, SMTP codes,
password reset, hashed passwords/codes/session storage, rate limits and
server-side logout. An old handle cannot be claimed by a new email account.
The migration preserves trip data and expires old handle-only sessions.

Reworked the iOS form with explicit sign-in/create/verify/reset states,
Password AutoFill, code autofill, loading indicators, guarded submissions,
localized copy, scrollable keyboard-safe fields and large-text controls.
Transient restore failures keep the credential and offer retry; 401 clears it.
The trips board exposes sign-out and shows loading errors instead of silently
presenting an empty list.

## Results

- Backend: **862 passed, zero skipped**, 150.62 seconds. Real Docker Postgres
  and Redis running. Full final output: `/tmp/syncinerary-auth-pytest-final.log`.
- Ruff and `git diff --check`: pass.
- Deterministic itinerary scenarios: **10/10 passed**, 31.16 seconds. Includes
  meals, fatigue, weather and disruption cases. No model/provider calls.
- Swift: **six suites passed**: API contracts, manual itinerary draft lifecycle,
  checklist/booked-hotel state, account lifecycle, city days and gather lifecycle.
- Shipping simulator build: normal signing succeeds. An unsigned compile also
  succeeds, but is not sufficient to verify Keychain behavior.
- New migration: full head/base/head round trip passed in a disposable database.
  Developer database upgraded to `b138df027ec5`; never downgraded.
- Real HTTP + local SMTP: created three verified users, received and consumed
  email codes, signed in, reset password, invalidated the old session/password,
  and revoked a session on logout. See `http-auth-journey.json` and
  `scripts/smoke_email_trip.py`. SMTP accepted example.com test recipients only.
- Simulator UI against that real local API: typed the test account, signed in,
  reached Trips, terminated/relaunched the signed app, confirmed automatic
  session restoration, then signed out and returned to the email form. API logs
  confirm GET /auth/me after relaunch and DELETE /auth/session on sign-out.
- Verified-account integration journey: create Tokyo/Atami/Kamakura trip with
  2/1/1 days, anonymous invite preview, friend joins, shared checklist generation,
  friend edits/completes an item, owner reads the persisted change, stale update
  rejected (409), outsider impersonating a member rejected (403). City resolution
  is a fixture in this test; storage, authentication and API logic are real.
- UI: 18 fixture screenshots covering sign-in, register, verify, forgot, reset
  and restore-retry in light/dark/accessibility3. These are visual fixtures, not
  claims that every screen was navigated through the live API. Visual review
  corrected email-placeholder link styling, truncated verification email and
  unscaled segmented controls at accessibility sizes. Forms scroll to actions;
  labels persist and button feedback respects Reduce Motion.

## Bugs found and fixed

1. Restore deleted the saved credential on any network error.
2. Keyboard submission could start concurrent sign-in requests.
3. The old identity endpoint let anyone reuse a known handle.
4. Default validation responses could echo invalid passwords. Auth validation
   now returns a safe message without submitted values.
5. Trip-loading errors were hidden on the trips board.
6. A 401 while loading trips did not return the user to sign-in.

The initial unsigned simulator app lost credentials on relaunch. The normally
signed simulator build retains them. Use normal simulator signing for this check.

## Boundaries and remaining work

- Configure a real SMTP provider and verified sending address before real
  signups work. No real verification email was sent to a person.
- Physical iPhones, Apple provisioning/TestFlight and external email delivery
  remain untested in this run.
- Live Google/Brave/Anthropic trip testing was rejected by automatic approval
  review because it sends test details externally and can incur charges. The
  requested specific user approval has not arrived; no live run was executed.
  Consequently this run does not establish current Reel coverage or live hotel
  lookup success.
- Legacy trip and WebSocket routes still need a complete authorization pass
  before public hosting. For example, existing read/vote/replan handlers are
  not all bound to CurrentAccount. Email authentication alone does not close
  those pre-existing gaps. Keep the backend private.
- Booked hotel selection is persisted; hotel-to-stop route anchoring remains
  a known separate limitation.
- New email accounts do not inherit old prototype accounts' trips. Any transfer
  needs an explicit ownership check; no insecure automatic claim path was added.

No public deployment, real booking, payment, commit, or Apple upload was made.

Cleanup confirmed: the disposable API, SMTP inbox, database and dedicated
simulator were removed. Existing Docker infrastructure was left running.
