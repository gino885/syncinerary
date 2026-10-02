# UI refresh verification

September 18, 2026.

## Scope

Shared color assets, semantic typography, primary and round button treatments,
decision labels, home, setup progress, itinerary tabs/day markers/stop surfaces,
and itinerary editing forms. Manual editing and backend behavior remain intact.
No new production dependency, provider call, database change or deployment.

The design replaces serif display and double-border primary actions with rounded
system type and filled actions. Native controls and clear approval wording remain.
Preview changes stays at the bottom of the editor with a scrollable draft above.

## Checks

- Shipping iOS Debug simulator build passed.
- Swift APIContractTests passed.
- Swift ManualItineraryTests passed, including draft preservation, reorder,
  fixed reservations and exact request encoding.
- git diff --check passed.
- day-selection.mp4 records the actual shared date selector transitioning
  between fixture days. Sampled frames confirm the moving selection and fades.
- Twenty foreground/background pairs measured above 4.5:1. See contrast.md.
- Nine representative screens rendered in light, dark and accessibility-extra-
  large text: home, setup, itinerary, editor, stop form, place picker, review,
  swipe components and loading. See screenshots/.
- Reduce Motion code review: no new press scaling, marker rotation, matched
  geometry travel, numeric rolling or editor row movement when it is enabled.
  Native list drag behavior is controlled by iOS. Selection haptics remain.

## Visual critique

Long names and times wrap without overlapping. At large sizes the day heading
and time columns stack, horizontal date navigation scrolls, and the preview
action stays reachable. Inspection prompted removal of a blank itinerary section
and stronger placeholder contrast in the edit-place and trip-setup fields.
The changed forms add no new decorative hero, gradient, slogan or icon badges.
Native dark form rows retain system surfaces; timetable cards use the shared
navy surface. The contrast checks cover app-defined colors, not disabled controls.

## Limits

Screenshots and animation demonstration use isolated fixture data in a temporary
copy of the actual components. No mock or preview-only network code ships.
These are layout and component-motion checks, not an automated end-to-end tap
session. Haptics, VoiceOver navigation and motion comfort need physical-device
review. Backend tests were not repeated for this presentation-only change.
