# Syncinerary iOS (SwiftUI)

## Local setup

The .xcodeproj is not committed; create it locally so the build settings match
your machine.

1. Open Xcode and create a new **iOS App** named `Syncinerary` in this directory
   (so you get `ios/Syncinerary.xcodeproj` and `ios/Syncinerary/...`).
   - Interface: SwiftUI
   - Language: Swift
   - Minimum deployment: iOS 17.0
2. Replace the generated `SyncineraryApp.swift` and `ContentView.swift` with the
   files already present in `Syncinerary/`.
3. Drag `Network/APIClient.swift` into the Xcode project (Copy items: off,
   Create groups).
4. Drag the `Models/`, `Navigation/`, `Design/`, and `Features/` folders into
   the Xcode project (Copy items: off, Create groups).
5. In `Info.plist`, add an `App Transport Security Settings` entry with
   `Allow Arbitrary Loads = YES` so the simulator can hit `http://localhost`.
6. Start the backend with `.venv/bin/uvicorn syncinerary.api.main:app --reload`.
7. Build and run on the iOS Simulator.

## M1 acceptance gate for iOS

- App launches without crash.
- TripCreate creates a Hokkaido trip and gathers its swipe deck.
- Swipe records like/dislike votes and builds the itinerary when complete.
- ItineraryView renders each day, transit legs, the narrative, and any
  wishlist-not-placed reasons.

## Physical device note

For testing on a physical iPhone, replace `localhost` in `APIClient.swift` with
your Mac's LAN IP (e.g. `192.168.1.42:8000`).
