# Syncinerary iOS (SwiftUI)

## Local setup

Open `ios/Syncinerary.xcodeproj` in Xcode. The shared project and scheme are
tracked, and the app targets iOS 17 or later.

1. Start the backend with `.venv/bin/python -m syncinerary.api.server`.
   Live discovery needs `GOOGLE_MAPS_API_KEY`, `BRAVE_SEARCH_API_KEY`, and a
   configured encryption keyring. The creator saves their Anthropic key in
   AI access; every member grants consent. Follow the
   [BYOK setup guide](../docs/ANTHROPIC_BYOK.md). A server `ANTHROPIC_API_KEY`
   does not replace the creator's key for an account-owned trip.
2. Start the durable discovery worker with `.venv/bin/python -m syncinerary.workers.gather`.
3. Build and run on the iOS Simulator.

## Current acceptance gate for iOS

- App launches without crash.
- TripCreate accepts up to four typed cities in one country, with at least one
  trip day per city, and creates a draft group room. Only the leader starts discovery.
- The saved-post step accepts Instagram, TikTok, and RedNote links without
  requiring a picture upload.
- A link that cannot reveal its place can be submitted again after adding the
  place or restaurant name.
- Swipe cards show permitted place photos and identify who attached a source.
- Swipe records like/dislike votes and builds the itinerary when complete.
- ItineraryView renders each day, transit legs, the narrative, and any
  wishlist-not-placed reasons.
- The planner schedules selected restaurants at meal times, or reserves lunch
  and dinner breaks with nearby restaurant search links inside the day window.
  Breakfast is optional. Transit legs link to Google Maps directions.
- Thin days are topped up only with nearby cards the group selected. Excluded
  swipe cards never reappear in the itinerary.

## Search scope

The prototype plans up to four cities in one country. Gather searches each
city adaptively: one Brave query at a time, at most eight per city, from three
intents. PLACES and FOOD ask what the city is broadly known for and stock the
Trending lane; HIDDEN_GEMS asks for the quieter, less touristy places and
stocks the For You lane. The first three searches ask all three, on three
different platforms; the rest go to whichever lane is short. Traveler
interests rank the For You lane rather than adding searches, so a group that
lists twenty interests costs no more than one that lists two. Each query and
platform is cached for 24 hours. TikTok posts are then read through the
official embed API (caption, creator, cover frame) in one batched call per
search, and the text on the cover frames is transcribed in one vision call;
both are capped in `config/gather.py` and cached. Instagram and RedNote use
the indexed description and additional search snippets when available. Discovery
prefers Instagram, then RedNote, then TikTok; Google Places discovery fills
remaining quantity or category gaps after the social search budget. Google
still verifies locations and provides place details and lodging. Automated tests use local stubs and do not spend
provider requests.

One useful post can introduce a place. RedNote searches both public note paths.
Search wording and the provider language follow the creator's stored trip
language on every platform. Chinese trips also require meaningful Chinese
text in the original public metadata; a translated card is not evidence of a
Chinese source. This does not determine the spoken language of a video. Explicit
post likes and comments rank a result higher when the public snippet includes
them. Results without visible metrics are labelled "Found on" rather than
presented as popular.

Source badges on swipe cards and itinerary stops link out to the post that
named the place (or to the place's Google Maps page), the platform's own app
when installed and Safari otherwise. Public Instagram Reels can also load in
Instagram's own embedded player after a tap; availability depends on Instagram.
The embed does not extract or transcribe the video's audio or frames. A card
also lists every post behind it under "From the posts", with its evidence summary.
Cards translate display text into the trip's output language while retaining
the original evidence, including cards attached or gathered earlier.

For the full product, city combinations should be suggested from trip length
and real transit time: one city for 1 to 3 days, up to two nearby cities for 4
to 6 days, and up to three for longer trips. The traveler can change the
suggestion before gathering begins.

Trip setup opens a tag sheet for interests and foods to avoid. Known hard
conflicts are removed from the swipe deck, while restaurants with unknown
dietary details remain visible with a confirmation reminder. Travelers can
return to earlier swipe cards and replace a mistaken vote. After voting, the
prototype compares up to three Google Places lodging results before planning.

Run the Swift API contract regression test from the repository root:

To run all ten contract and view-model test programs together:

```bash
bash scripts/test_ios.sh
```

To run only the API contract checks:

```bash
xcrun swiftc -parse-as-library \
  -module-cache-path /tmp/syncinerary-swift-module-cache \
  ios/Syncinerary/Models/*.swift \
  ios/Syncinerary/Network/*.swift \
  ios/Tests/APIContractTests.swift \
  -o /tmp/syncinerary-api-contract-tests
/tmp/syncinerary-api-contract-tests
```

## Development knobs

All three are read from the environment or from UserDefaults, so they can be
set as launch arguments in the scheme or through `xcrun simctl`:

| Knob | Effect |
|---|---|
| `SYNC_API_BASE_URL` | Backend origin, default `http://localhost:8000`. On a physical iPhone set it to your Mac's LAN IP, for example `http://192.168.1.42:8000` |
| `SYNC_RESUME_TRIP_ID` | Reopens that saved trip at launch, at the step the server reports |
| `SYNC_RESUME_ROUTE` | With the above, forces the step: `gathering`, `savedPosts`, `swipe`, `shortlist`, `lodging`, or `itinerary` |

Example, to open the deck of a saved trip in the simulator:

```bash
xcrun simctl launch booted com.local.syncinerary -SYNC_RESUME_TRIP_ID <trip uuid> -SYNC_RESUME_ROUTE swipe
```

Saved trips live in UserDefaults under `recentTripSessions` (see
`RecentTripsStore`); the "Continue planning" section on the first screen lists
them.

## Simulator rendering

On a macOS 15 host, the iOS 26 simulator can draw emoji in SwiftUI text as
question-mark boxes. Loading states, swipe feedback, badges, meals, and
transit therefore use SF Symbols rather than runtime emoji glyphs.

## Durable discovery worker

New trips require sign-in and open a draft group room. Run the worker beside
uvicorn using the same environment and database:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m syncinerary.workers.gather
```

The leader starts discovery from the group room. The app polls short status
requests and may be closed while the worker runs. After a crash, a running job
becomes eligible for checkpoint recovery after its heartbeat is 60 seconds old.
A provider failure exposes a sanitized error and allows at most two leader retries.
The worker does not launch inside FastAPI. Production must supervise this process
with the same restart policy as the API.

## Edit a generated itinerary

Use Edit plan in the itinerary toolbar, Add a place under a day, or a stop's
Edit action. The draft supports saved places, verified place search and the
existing social-link attachment flow. Preview changes checks exact times;
Adjust this day can reschedule the selected day's places. Both open the
existing review sheet, where Use this plan activates the proposed version.
Cancel and Keep current plan leave the active itinerary unchanged.

Run the manual draft and request-contract regression checks:

```bash
xcrun swiftc -parse-as-library \
  -module-cache-path /tmp/syncinerary-swift-module-cache \
  ios/Syncinerary/Models/*.swift \
  ios/Syncinerary/Network/*.swift \
  ios/Syncinerary/Features/Itinerary/ManualItineraryViewModel.swift \
  ios/Tests/ManualItineraryTests.swift \
  -o /tmp/syncinerary-manual-itinerary-tests
/tmp/syncinerary-manual-itinerary-tests
```

## Trip preparation and iPhone trials

The shared Checklist opens from the draft group room and itinerary toolbar.
Base tasks are seeded at trip creation; scheduled ticket/reservation checks are
added when opening the checklist. Renaming, completing and deleting tasks is
persistent. Pull to refresh changes from another traveler.

The Stay screen accepts an already-booked hotel by name or Google Maps link.
Choose a trip city, search, and confirm the exact result. This records your
booking statement and selected hotel; no room booking is made or verified.
Practical stop and food tips use intact saved social highlights with a source
link; no useful evidence means no extra tip.

For installing on real phones and inviting a friend, follow
[the iPhone testing guide](../docs/IPHONE_TESTING.md). Set `SYNC_API_BASE_URL`
in the target's Build Settings for both Debug and Release. The value is
embedded in the installed app; Xcode Run environment overrides remain useful
for development but do not configure a TestFlight launch.

Preparation regression checks:

```bash
xcrun swiftc -parse-as-library -module-cache-path /tmp/syncinerary-swift-module-cache \
  ios/Syncinerary/Models/*.swift ios/Syncinerary/Network/*.swift \
  ios/Syncinerary/Features/Checklist/ChecklistViewModel.swift \
  ios/Syncinerary/Features/Lodging/LodgingViewModel.swift \
  ios/Tests/PreparationTests.swift -o /tmp/syncinerary-preparation-tests
/tmp/syncinerary-preparation-tests
```

## Account access

See [email configuration and migration notes](../docs/EMAIL_SIGN_IN.md).
Handle-only login is disabled. Email signup signs in immediately without a
verification code. Google and Apple buttons use [provider configuration](../docs/SOCIAL_SIGN_IN.md).
Password reset and server-side logout are available. Network failures preserve the saved session.

```bash
xcrun swiftc -parse-as-library -module-cache-path /tmp/syncinerary-swift-module-cache \
  ios/Syncinerary/Models/*.swift ios/Syncinerary/Network/*.swift \
  ios/Syncinerary/Features/Account/AccountStore.swift \
  ios/Syncinerary/Features/Account/SignInMode.swift \
  ios/Syncinerary/Features/Account/SignInViewModel.swift \
  ios/Tests/AccountTests.swift -o /tmp/syncinerary-account-tests
/tmp/syncinerary-account-tests
```
