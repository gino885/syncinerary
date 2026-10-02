# Trip preparation verification

September 23, 2026.

## Implemented

- One source-linked practical sentence beneath scheduled attractions and food
  stops, selected from saved place-specific social highlights. Original language,
  times and qualifications are retained. Truncated, overly long and generic
  evidence is omitted. No additional discovery or model call is introduced.
- Shared checklist, available in the draft group room and active itinerary.
  Hotel and inter-city transport checks are seeded at trip creation. Opening the
  checklist adds admission and reservation checks for applicable scheduled places.
  Manual add, rename, notes, completion and delete persist. Generated deletions
  are tombstones, so reopening cannot resurrect them. Revision checks prevent
  silent overwrites by another traveler. The API has its own response schema.
- Already-booked hotel entry accepts a name, supported Google Maps place URL or
  Maps short link. Provider results must be lodging in the selected trip city.
  The exact confirmed result is persisted with a booked flag, deduplicated by
  Google place ID and restored on reload. Redirects are restricted to supported
  Google hosts with a five-hop limit; provider credentials only go to Places.
- Build-setting backend URL is embedded in the app, including Release builds,
  and the local-network permission text is present. Xcode environment and
  UserDefaults overrides retain precedence.
- New interface strings have Traditional Chinese, Simplified Chinese and Japanese
  translations. Generated checklist titles follow the trip output locale.

## Checks

- Full backend suite: 855 passed in 136.01 seconds, with no skipped tests.
- Targeted integration checks cover source attribution, Chinese notes, preservation
  of decimal times, truncated evidence, shared edits, stale revisions, deletion
  suppression, nonmember/account/trip isolation, localized tasks, verified hotel
  identity/type/location/closure, redirect rejection, dedup and booked-state reload.
- Ruff and git diff --check passed.
- Checklist migration: upgrade head, downgrade base, upgrade head passed in an
  isolated temporary database. Only upgrade was applied to the developer database.
- Ten deterministic eval fixtures passed with --no-store. This mode does not
  execute the database approval path for disruption fixtures or call live models.
- Swift PreparationTests, APIContractTests and ManualItineraryTests passed.
- Shipping Debug iPhone simulator build passed. Built Info.plist contains the
  configured SyncAPIBaseURL. No Apple signing or TestFlight upload was performed.

## Visual review

Eighteen screenshots cover checklist, task editor, hotel entry, stop tips, draft
preparation and itinerary navigation in light, dark and accessibility3 text.
The previews use the shipping components in a temporary copy with fixture HTTP
responses. They are layout checks, not a live Google or two-device end-to-end run.
The isolated itinerary preview intentionally has no live WebSocket and displays
its reconnecting state.

Inspection prompted an inline checklist title, clearer hotel placeholder,
explicit large-text field label, and a booked-specific availability message.
No extra note container or progress banner was added. New controls use native
buttons with labels and at least 44pt targets. The stay selection transition
respects Reduce Motion. New task and note screens introduce no repeating motion.

## Limits and follow-up boundaries

- Live Google hotel lookup, physical-device networking, VoiceOver and Apple signing
  need a real-device trial. No new provider credentials or paid account were used.
- Tips depend on useful saved highlights; no video/audio transcription is added.
  Unassigned meal breaks still offer nearby restaurant search, since there is no
  chosen restaurant to support a specific dish recommendation.
- Hotel input records a traveler's booking statement, not reservation verification.
  It uses the existing single selected-hotel model. Multiple dated hotel stays
  and hotel-to-first/last-stop route anchoring are not implemented by this change;
  the existing solver does not consume selected_lodging as a routing anchor.
- Checklist suggestions are checks, not verified ticket requirements or purchases.
  A removed itinerary stop's existing task remains user-editable rather than
  silently deleting an item the group might already have acted on.
- Current sign-in remains the specification's stub identity. The launch guide
  recommends a private trial and identifies the work needed before public exposure.
