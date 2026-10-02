# Use Syncinerary with a friend on iPhone

Two things must be running: an installed iOS app on each phone, and one shared
backend. Both apps must point to the same backend. The trip invite code joins a
trip; it does not install the app. Both iPhones need iOS 17 or later.

## 1. Start the backend on this Mac

In Terminal:

```bash
cd /Users/gino/syncinerary
docker compose up -d
.venv/bin/alembic upgrade head
.venv/bin/uvicorn syncinerary.api.main:app --host 0.0.0.0 --port 8000
```

Leave that terminal running. In a second terminal:

```bash
cd /Users/gino/syncinerary
.venv/bin/python -m syncinerary.workers.gather
```

The worker is required for Find places / discovery. Docker alone starts the
database, Redis and tracing, not the API or discovery worker. Keep the Mac awake.
The API and worker read the same root `.env`. Live discovery requires valid
`ANTHROPIC_API_KEY`, `GOOGLE_MAPS_API_KEY`, and `BRAVE_SEARCH_API_KEY`. Keep all
provider credentials on the Mac/backend, never in the iOS app or a shared link.

Find the Mac's Wi-Fi address in System Settings > Wi-Fi > Details > TCP/IP.
For example, if it is `192.168.1.42`, open
`http://192.168.1.42:8000/health` in Safari on both phones. A JSON response means
the phones can reach the API. Use the actual address, not this example.

For the installed app, prefer the Mac's `.local` hostname (step 2). If you use
an HTTP numeric IP address, iOS 17+ may also require an explicit ATS exception
for that exact IP under `NSAppTransportSecurity > NSExceptionDomains` with
`NSExceptionAllowsInsecureHTTPLoads = YES`. Do not disable ATS globally. HTTPS
or the supported `.local` development address avoids that IP-specific setup.
See [Apple's local networking policy](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking).

Both phones and the Mac must be on the same trusted Wi-Fi. Avoid a guest Wi-Fi
that isolates devices. Allow incoming connections for the Python server if
macOS asks. Do not forward router ports. Only the API port is needed by phones;
Postgres, Redis and Phoenix are not phone-facing services.

## 2. Install the app from Xcode for development

1. Open `ios/Syncinerary.xcodeproj` in Xcode.
2. Sign in to your Apple Account under Xcode > Settings > Apple Accounts.
3. Select the Syncinerary target > Signing & Capabilities. Enable automatic
   signing, choose your team and use your own unique Bundle Identifier, for
   example `com.yourname.syncinerary`.
4. In Terminal run `scutil --get LocalHostName` to find the Mac's local name.
   Under target Build Settings, search for `SYNC_API_BASE_URL`. Set **both Debug
   and Release** to `http://YOUR-MAC-NAME.local:8000`, using the returned name.
   First verify that same `.local` URL plus `/health` opens in iPhone Safari. This setting is now embedded in the app's Info.plist
   so it still works when launched from the Home Screen. An Xcode Run scheme
   environment variable only affects Xcode launches; remove an old override.
5. Connect your iPhone to the Mac, unlock it, trust the computer, and choose it
   as the Xcode run destination. Enable Settings > Privacy & Security >
   Developer Mode if prompted, restart, then press Run in Xcode.
6. Allow Syncinerary's Local Network permission on the phone. If denied, enable
   it in Settings > Privacy & Security > Local Network.

Apple supports personal on-device development without a paid membership, but
Personal Team provisioning expires after seven days and is intended for
personal use. A friend with their own Mac can build with their own Personal
Team and use your backend URL. For convenient friend distribution, use the
TestFlight path below, or a paid team's registered-device development build.
See [Apple's device-running guide](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)
and [membership comparison](https://developer.apple.com/support/compare-memberships/).

## 3. Join the same trip

1. Email signup needs no email delivery setup. See [account setup](EMAIL_SIGN_IN.md)
   for optional password recovery and [provider setup](SOCIAL_SIGN_IN.md) for Google/Apple. Each person creates an account with their own email and password and is signed in immediately.
2. Create the trip on one phone, choose the cities/days, and open Invite friends.
3. Share the trip code/link. On the other phone choose Join trip and enter it.
4. Both add preferences and saved posts. The leader starts discovery.
5. Vote on places, confirm the shortlist, choose a stay or enter a booked hotel,
   then build the itinerary. The shared Checklist is available in preparation
   and from the itinerary toolbar. Pull to refresh it after your friend edits.

Sign-in uses email/password or a configured Google/Apple provider. Use HTTPS for real accounts;
the HTTP addresses above are local connectivity checks. Trip REST and
WebSocket access is bound to the signed-in member. Existing handle-only
sessions expire on migration; see the email guide before expecting a new
email account to inherit an old trip.

## 4. Use it from different locations during a private trial

A private network connection can keep using this Mac as the backend, so you do
not need to publish the prototype API. One option is Tailscale on the Mac and
both phones, with your friend invited to your private network.

After installing and signing in, run the API as in step 1 and run:

```bash
tailscale serve --bg http://127.0.0.1:8000
```

Follow Tailscale's HTTPS setup prompt. Use the exact `https://…ts.net` URL it
prints as `SYNC_API_BASE_URL`, rebuild/install the app, and test `/health` from
each phone with Tailscale connected. Your network's access policy must allow
the friend to reach this Mac's HTTPS service. Use **Serve**, which is private,
rather than Funnel, which publishes a service to the internet. The Mac, API,
worker and Docker must all remain running. This is guidance; no Tailscale
account, device sharing or server exposure has been configured by this change.
See [Tailscale's private development-server guide](https://tailscale.com/docs/use-cases/application-testing/share-local-dev-server-with-team).

## 5. Convenient installation with TestFlight

TestFlight distributes the iOS app; it does not host the Python backend.
You need an Apple Developer Program membership, currently US$99 per year or
local equivalent. Your friend only needs the TestFlight app and an invitation.
See [Apple membership details](https://developer.apple.com/programs/whats-included/).

1. Enroll, then use that paid team in Xcode Signing & Capabilities.
2. Register your Bundle ID and create the matching iOS app in App Store Connect.
3. Set the Release `SYNC_API_BASE_URL` to the intended stable HTTPS backend.
   A LAN address only works on that LAN. A private Tailscale address only works
   for phones permitted to access that private network.
4. Choose a generic iOS device destination in Xcode, then Product > Archive.
5. In Organizer, choose Distribute App > App Store Connect and upload. Increment
   the build number for later uploads.
6. In App Store Connect > TestFlight, complete the test information and export
   compliance questions accurately. Create an external testing group and add
   your friend's email. Submit the build for Beta App Review as required.
7. After approval, your friend accepts the invitation in TestFlight. Repeat the
   shared-trip steps above. TestFlight builds are time-limited, so upload new
   builds during an ongoing trial.

External TestFlight review needs a backend Apple can access and clear test
instructions; a VPN-only service is not automatically accessible to reviewers.
For a private VPN trial, a paid registered-device development build may be more
practical until a review-accessible deployment is ready. Do not grant your
friend App Store Connect administration merely to install the app.
See [Apple's external tester guide](https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers).

## 6. When you want the Mac to be off

Deploy these services together to an always-on environment:

- Python 3.12 API: `uvicorn syncinerary.api.main:app --host 0.0.0.0 --port 8000`.
- Separate supervised worker: `python -m syncinerary.workers.gather`.
- Persistent Postgres with pgvector and Redis on a private network.
- HTTPS reverse proxy with WebSocket support, a stable hostname, and a request
  timeout that permits planning (the iOS planning request permits 180 seconds).
- Database migrations before traffic, backend-only environment secrets, and
  durable database backups. Phoenix, if enabled, stays private.

The current Docker Compose file is for local development; it exposes database
and tracing ports and contains development database credentials. Do not publish
it unchanged. Account sign-in, authentication rate limits, trip-scoped
REST authorization, and authenticated WebSockets are implemented. A public
rollout still needs password-recovery email delivery, HTTPS, monitoring, backups, and
the deployment checks in [the production runbook](PRODUCTION_DEPLOYMENT.md).

No Apple account signing, cloud deployment, public tunnel, or invitation has
been performed automatically.
