# App Store release packet

This is the working release checklist for Syncinerary. It separates completed
engineering work from tasks that require the owner's Apple account, cloud
account, legal choices, or ongoing operations.

## Implemented in the product

- Verified email accounts, secure password hashing, Keychain session storage,
  logout, password reset, and in-app account deletion.
- Creator-owned Anthropic keys encrypted with AES-256-GCM and never returned
  to the app after saving.
- A separate, versioned Anthropic data-sharing choice for every account in a
  trip. AI work is blocked until every account member has opted in.
- A clear in-app disclosure naming Anthropic and the categories of trip data
  that may be sent.
- A privacy policy link, support link, privacy manifest, and required-reason
  declaration for UserDefaults.
- Production traces hide prompt and response content by default.
- Authenticated WebSockets that bind the requested traveler to the bearer
  session.
- A Release build guard that rejects localhost, HTTP backend origins, the
  local bundle identifier, and non-HTTPS legal URLs.
- A production container and separate API, migration, and worker runbook.

## Blocking before App Store review

1. **User-generated content moderation.** The private trip thread allows
   people to post messages and links. Apple Guideline 1.2 requires real
   filtering, reporting with timely operator response, and user blocking.
   Build that system and staff its response workflow, or remove the chat and
   other free-form member posting from the App Store version. A report button
   without an operational response process is not enough.
2. **Creator API key business model.** Apple Guideline 3.1.1 requires in-app
   purchase when an external mechanism unlocks digital app functionality. A
   third-party API key may be reviewed as such a mechanism even though the app
   does not sell the key or link to a purchase page. Before public submission,
   obtain written App Review guidance for this exact flow or move to a
   developer-funded Anthropic account with StoreKit for any paid consumer
   tier. Keep the creator-key implementation only if that review path is
   accepted. Explain the business model precisely in Review Notes.
3. **Public backend.** Deploy the API, worker, PostgreSQL, Redis, email, HTTPS,
   private networking, backups, monitoring, and secret management described
   in `PRODUCTION_DEPLOYMENT.md`. Keep it available throughout review.
4. **Public legal pages and contact.** Publish the privacy policy and support
   page at stable HTTPS URLs controlled by the developer. Confirm the support
   route provides a monitored way to contact a person. Replace the current
   repository URLs in the Release build if the repository is not public and
   durable.
5. **Apple identity.** Join the Apple Developer Program, create a unique
   production Bundle ID, choose the signing team, and create the App Store
   Connect app record. The current `com.local.syncinerary` identifier is only
   for development and the Release guard rejects it.
6. **Review access.** Create a fictional reviewer account and a second trip
   member account. Preconfigure a reviewable trip and fund a restricted
   Anthropic key with a low spending limit. Never submit a real user's data.
7. **On-device release testing.** Exercise sign-up, email delivery, joining,
   every AI consent state, discovery, voting, itinerary creation, account
   deletion, poor networks, relaunch, and the full chat moderation flow on a
   physical iPhone against production.
8. **Operational promises.** Configure the stated 30-day backup expiration,
   support response process, incident response, credential rotation, and
   account-deletion verification. Policy text must match actual operations.

## Suggested App Store metadata

**Name:** Syncinerary

**Subtitle:** Plan trips together

**Primary category:** Travel

**Secondary category:** Productivity

**Promotional text:** Turn a group's saved places, preferences, and votes into
one practical shared itinerary.

**Description:**

Syncinerary helps friends plan a trip without losing the places everyone
saved. Create a trip, invite your group, add preferences and travel links,
then compare places and vote together. Syncinerary builds a day-by-day plan
with travel time, meal breaks, hotel context, and a shared preparation
checklist.

AI planning is optional and transparent. Every trip member decides whether
their trip information may be processed by Anthropic. The trip creator
supplies the Anthropic API key used for the group's planning requests.

**Keywords:** group travel,itinerary,trip planner,travel planning,voting,
checklist,saved places

**What’s New for 1.0:** Plan a group trip from invite through itinerary with
shared preferences, place voting, preparation checklists, and explicit AI
privacy controls.

Do not describe this build as a beta or prototype in App Store metadata.
TestFlight is the beta channel.

## App privacy answers

Use these as a starting point, then verify them against the deployed services
and every enabled SDK in the submitted binary.

| Data type | Linked to user | Tracking | Purpose |
| --- | --- | --- | --- |
| Name | Yes | No | App Functionality |
| Email Address | Yes | No | App Functionality |
| User ID | Yes | No | App Functionality |
| Sensitive Info | Yes | No | App Functionality |
| Photos or Videos | Yes | No | App Functionality |
| Other User Content | Yes | No | App Functionality |
| Search History | Yes | No | App Functionality |
| Product Interaction | Yes | No | App Functionality |
| Other Data Types | Yes | No | App Functionality |

The app does not currently declare tracking, advertising, precise location,
contacts, payment information, diagnostics tied to identity, or an advertising
identifier. Change the answers if production analytics, crash reporting, or
other SDKs collect additional data.

## Review notes draft

Syncinerary is an invite-only collaborative travel planner. Reviewers need two
verified accounts to exercise member-specific AI consent. We provide both
accounts below and a prepared trip.

AI planning uses Anthropic. Before a model request, the app explains which
trip data may be shared and requires a separate choice from every account
member. The creator supplies the encrypted Anthropic API key and pays the
provider directly. Revoking any member's choice blocks future AI requests for
that trip. Account deletion is under Account, Delete account.

Reviewer account 1: `[ADD FICTIONAL EMAIL]`

Reviewer account 2: `[ADD FICTIONAL EMAIL]`

Password: `[ADD REVIEW-ONLY PASSWORD]`

Prepared trip and test steps: `[ADD FINAL STEPS AFTER PRODUCTION SMOKE TEST]`

Content moderation contact and response workflow:
`[ADD AFTER GUIDELINE 1.2 SYSTEM IS OPERATIONAL]`

## Screenshots

Use fictional trip and account data. Capture the actual app in use, not only
the sign-in or splash screen. A strong sequence is:

1. Group trip room with members and preparation progress.
2. Saved places and discovery progress.
3. Place voting card with meaningful source context.
4. Day-by-day itinerary with travel and meal timing.
5. Shared checklist or AI privacy choice.

Capture every required iPhone display size in App Store Connect. Do not show a
real email, API key, private message, or third-party content you lack rights to
use in marketing.

## TestFlight and submission sequence

1. Replace the Bundle ID and choose the paid team.
2. Set Release `SYNC_API_BASE_URL`, `SYNC_PRIVACY_POLICY_URL`, and
   `SYNC_SUPPORT_URL` to stable HTTPS URLs.
3. Increment `CURRENT_PROJECT_VERSION` for every uploaded build.
4. Archive with a generic iOS device destination and upload through Xcode
   Organizer.
5. Complete export-compliance, age-rating, content-rights, App Privacy, and
   availability questions accurately.
6. Add internal testers first, then submit an external TestFlight group for
   Beta App Review.
7. Resolve crash, privacy, moderation, and reviewer-access findings before
   submitting version 1.0 for App Review.

Official references: [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/),
[account deletion](https://developer.apple.com/support/offering-account-deletion-in-your-app),
[privacy details](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy),
and [submission overview](https://developer.apple.com/app-store/submitting/).
