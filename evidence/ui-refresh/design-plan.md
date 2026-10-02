# A brighter trip, September 18, 2026

Audience: friends turning saved posts into plans they can change together.
Home's job is to open or start a trip. The itinerary answers what happens when.
The editor changes that plan; preview and approval remain explicit.

## Tokens and composition

Six core colors: ice canvas #F2F5FF / #10182B, white surface #FFFFFF / #1C2740,
navy ink #17233D / #F4F6FF, slate secondary #56617B / #ADB9D0,
cobalt action #3452DF / #B4C0FF, lemon day marker #FBE587 in both modes.
Lemon uses navy text in both modes. Cobalt uses white text in light mode and
navy in dark mode. Keep rose for errors/likes, green for confirmation and
violet for must-go as existing semantic distinctions.

Rounded bold system display, readable system body, monospaced digits for times.
Remove the default serif and double-border stamp treatment. Keep compatibility
names in the shared styles to avoid rewriting unrelated feature logic.

Home: big left-aligned invitation, actual destination cards, one solid primary
action. Itinerary: selected date moves across a compact filled tab strip;
lemon day numbers identify the actual sequence; time columns use cobalt.
Editor: surfaced native rows, time-first stop labels, primary preview anchored
above the bottom safe area so it stays reachable while editing long lists.
Stop form: the real place name as the heading, grouped native timing controls.
Place picker: clear search and post inputs with readable selectable results.
Review: unchanged diff structure, rounded type, one filled approval action.

Signature: a lemon day marker plus cobalt timetable. This encodes the trip's
real day sequence, with no invented maps or decorative statistics.

## Motion

Small spring press feedback on primary and round actions; spring selection on
date tabs; animated additions/removals and numeric time updates in the editor;
selection haptics on date changes and edits. No perpetual floating decorations.
Reduce Motion replaces movement with short fades and disables scale/rotation
feedback. Native list drag animation remains owned by the system.

## Critique before code

A generic neon gradient dashboard would compete with the places and posts.
Use flat high-contrast surfaces and spend the bright yellow only on actual day
markers. Reject slogans, emoji labels, hero cards on forms and ornamental
badges. Remove the old double borders; do not add another accessory in their
place. The forms keep native controls and scrolling at accessibility sizes.

## Verification plan

Build the shipping app; exercise existing Swift request/draft tests. Inspect
real view renders of home, setup, itinerary, editor, stop, picker, review and
swipe controls in light, dark and accessibility sizes. Check Reduce Motion's
code paths and record color contrast. Fixture previews must remain outside
the shipping source tree.
