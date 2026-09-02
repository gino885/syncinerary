# Syncinerary iOS (SwiftUI)

## Local setup

Open `ios/Syncinerary.xcodeproj` in Xcode. The shared project and scheme are
tracked, and the app targets iOS 17 or later.

1. Start the backend with `.venv/bin/uvicorn syncinerary.api.main:app --reload`.
   Gather needs `GOOGLE_MAPS_API_KEY`, `BRAVE_SEARCH_API_KEY`, and
   `ANTHROPIC_API_KEY`. Provider failures are returned instead of being hidden
   as an empty social result.
2. Build and run on the iOS Simulator.

## Current acceptance gate for iOS

- App launches without crash.
- TripCreate accepts up to four typed cities in one country, with at least one
  trip day per city, and gathers a city-scoped swipe deck.
- The saved-post step accepts Instagram, TikTok, and RedNote links without
  requiring a picture upload.
- A link that cannot reveal its place can be submitted again after adding the
  place or restaurant name.
- Swipe cards show permitted place photos and identify who attached a source.
- Swipe records like/dislike votes and builds the itinerary when complete.
- ItineraryView renders each day, transit legs, the narrative, and any
  wishlist-not-placed reasons.
- The planner aims for lunch and dinner when suitable selected restaurants are
  open inside the user's day window.
- Thin days are topped up only with nearby cards the group selected. Excluded
  swipe cards never reappear in the itinerary.

## Search scope

The prototype plans up to four cities in one country. A gather uses one
automatic Brave search per city for Instagram, TikTok, and RedNote. The result
for the same city, platform, and interests is cached for 24 hours. TikTok
posts are then read through the official embed API (caption, creator, cover
frame) in one batched call per city, and the text on the cover frames is
transcribed in one vision call; both are capped in `config/gather.py` and
cached. Instagram and RedNote stay at the search snippet. Automated tests use
local stubs and do not spend provider requests.

One useful post can introduce a place. Instagram and TikTok searches target
must-visit and must-eat content; RedNote searches use Mandarin `必去`, `必吃`,
`攻略`, and `探店` terms. Explicit post likes and comments rank a result higher
when the public snippet includes them. Results without visible metrics are
labelled "Found on" rather than presented as popular.

Source badges on swipe cards and itinerary stops link out to the post that
named the place (or to the place's Google Maps page), the platform's own app
when installed and Safari otherwise. The post is never rendered in the app. A
card also lists every post behind it under "From the posts", with what each
one said.

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
