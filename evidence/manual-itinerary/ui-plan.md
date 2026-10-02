# Manual itinerary editing UI

The existing trip journal remains the destination. Add a plain Edit plan toolbar
action and Add a place under each day. Editing opens a native list with the same
day picker, stop rows and half-hour controls. The primary action is Preview
changes; the existing diff sheet owns approval. A stop editor changes day,
start time and duration. Search and saved-place selection are separate from
clock editing, so picking a place never silently saves the plan.

Reuse Canvas, Surface, Ink, Faded, Jade and Stamp asset colors with their existing
light/dark values. Use system body text for names and form labels, the existing
monospaced time style for clocks, and existing day-heading typography. No new
color or font system. The editable timetable is the defining visual element.

Critique: avoid a second hero card, a completion meter or provider badges. Native
list editing expresses reorder/remove and native form fields express time.
Errors stay with the edit; the itinerary remains visible after cancel. Reserve
red for removal and keep Preview changes as the single primary action. Use
scrolling layouts, explicit VoiceOver labels, native minimum touch targets and
no new custom animation. Verify light, dark and accessibility text sizes.

## Visual verification

Inspected all five changed screens in normal light, normal dark, and
accessibility-extra-large text on the iPhone 17 Pro / iOS 26.3 simulator.
Screenshots are in screenshots/. Long names wrap; time changes show both start
and end values; the empty itinerary day keeps its Add a place action. Native
lists scroll at large text sizes, and confirmation controls remain available.
The large-text editor prioritizes Cancel and Preview changes when the navigation
title no longer fits. No decorative badges or header card were added to the
editing forms. Existing itinerary and review styling remains intact.

The snapshots are isolated renders of the real components with fixture network
responses. They establish layout behavior, not live search, VoiceOver navigation
or an automated end-to-end tap test. Draft state and API transitions are covered
separately by Swift and backend tests.
