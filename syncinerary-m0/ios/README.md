# Syncinerary iOS (SwiftUI)

## M0 setup

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
4. In `Info.plist`, add an `App Transport Security Settings` entry with
   `Allow Arbitrary Loads = YES` so the simulator can hit `http://localhost`.
5. Build and run on the iOS Simulator. The app should show:
   ```
   Backend: ok (M0)
   ```

## M0 acceptance gate for iOS

- App launches without crash.
- It hits `GET http://localhost:8000/health`.
- It renders the response.

Real trip / swipe / shortlist / itinerary / replan screens land from M1 onward
(see `CLAUDE.md` §13).

## Physical device note

For testing on a physical iPhone, replace `localhost` in `APIClient.swift` with
your Mac's LAN IP (e.g. `192.168.1.42:8000`).
