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
for the same city, platform, and interests is cached for 24 hours. Automated
tests use local stubs and do not spend provider requests.

For the full product, city combinations should be suggested from trip length
and real transit time: one city for 1 to 3 days, up to two nearby cities for 4
to 6 days, and up to three for longer trips. The traveler can change the
suggestion before gathering begins.

Trip setup also accepts comma-separated interests and foods to avoid. Known
hard conflicts are removed from the swipe deck, while restaurants with unknown
dietary details remain visible with a confirmation reminder. After voting, the
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

## Physical device note

For testing on a physical iPhone, replace `localhost` in `APIClient.swift` with
your Mac's LAN IP (e.g. `192.168.1.42:8000`).
