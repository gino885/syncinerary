# iOS UI/UX overhaul: make planning feel like the trip

Written 2026-09-02 on `main` after the M5a merge. Scope: the SwiftUI app in
`ios/`. No backend behaviour changes, no new third-party frameworks; the app
stays on system components (Form, List, NavigationStack) with a design layer
on top. Guidance followed: `.agents/skills/swiftui-pro` (extract subviews into
their own files, `@Observable` view models, `sensoryFeedback`, Reduce Motion,
Dynamic Type, 44pt targets) and CLAUDE.md 9.2 (three vote buttons plus a
long-press must-have shortcut, used sparingly).

## 1. Where the app stands

| Screen | Today | Gap |
|---|---|---|
| Plan a trip | Plain Form. "Create trip" spins inside the button while the gather runs, often 30 to 90 seconds, with no words | The longest wait in the app has no feedback |
| Saved posts | Form with a URL field and a "Start swiping" button | Fine, but flat |
| Swipe | One static card in a ScrollView, three bordered buttons, a thin progress bar. No gesture, no transition between cards, no reaction to a vote | The heart of the product feels like a settings screen |
| Shortlist | List with plus and star icons | No sense of the group decision taking shape |
| Choose a stay | List of names. "Build itinerary" runs the solver and explainer with only a disabled button | Second longest wait, again silent |
| Itinerary | List of stops with times | The explainer narrative is fetched and never shown. Stops read as rows, not as a day |
| Everywhere | System blue, default fonts, no app icon, no accent, nothing remembered between launches | No identity; closing the app loses the trip |

## 2. Principles

1. Motion has a job: it tells you what just happened (a card flew off, a
   star lit up, the group agreed) and never plays on its own.
2. Playful, not childish: one emoji per idea, rounded type, warm accent,
   plain sentences.
3. Waiting is part of the show: every wait longer than a second gets a
   rotating line of what the agent is doing, in words a friend would use.
4. Respect the phone: Reduce Motion swaps flights and particles for fades,
   Dynamic Type is never overridden, every target is at least 44pt,
   VoiceOver gets custom actions where gestures are the primary control.
5. Stay native: Form and List underneath, custom views only where they earn
   it (the deck, the loader, the bursts, the timeline).

## 3. Work packages

### U1. Design system (`ios/Syncinerary/Design/`)

- `AppTheme`: colours (warm coral accent, teal secondary, sand and night
  backgrounds via the asset catalog so light and dark both work), spacing
  scale, corner radii, shadow, and named animations (`cardThrow`, `settle`,
  `pop`). `AppLayout` folds into it.
- `Assets.xcassets`: AccentColor plus brand colours; a generated app icon
  (route line and a heart, coral on cream) so the home screen is not blank.
- Root modifiers: `.fontDesign(.rounded)` and the accent tint applied once
  in `ContentView`.
- Small reusable views, one per file: `ChipView` (label plus emoji or symbol),
  `RoundActionButton` (the circular swipe buttons), `EmojiBurstView`,
  `FunLoadingView`, `StampView`.

### U2. Tinder-style swipe deck (`ios/Syncinerary/Features/Swipe/`)

- `SwipeDeckView` stacks the top three cards; the two behind are scaled and
  offset so the deck reads as a pile.
- `SwipeCardView` is the new card: photo hero with a gradient scrim, name and
  area over the photo, source badge chips (still links), the post's own
  sentence, the delegate badge, and duration and category chips. A "Details"
  button opens `CandidateDetailSheet`, which is today's full card (address,
  posts, dietary notice) in a sheet, so the card itself does not scroll and
  the drag owns the whole surface.
- Gesture: drag moves the card and rotates it (about one degree per 12pt,
  clamped). Stamps fade in with distance: "LIKE 👍" green on a right drag,
  "NOPE 👎" red on a left drag, "MUST GO ⭐" on an upward drag. Past the
  threshold (120pt, or a fast flick) the card flies off and the vote is cast;
  under it the card springs back.
- Buttons stay (CLAUDE.md 9.2): circular Nope, Note, Like. Long-press on Like
  remains the must-have shortcut, swipe up is its gesture twin, and a one-time
  hint under the deck says so.
- Reactions: an emoji burst on every decision (❤️ 🥰 ✨ 🍜 for like, 👋 💨 for
  nope, ⭐ 🌟 🚀 for must-go, 📝 for a note) rising from the card and fading in
  about a second, plus haptics via `sensoryFeedback` (impact for like and
  nope, success for must-go).
- Optimistic advance: the next card is promoted the moment the top card
  flies; the vote posts in the background and a failure puts the card back
  with an alert.
- Progress: a "12 of 40" pill and the bar; the end of the deck is a
  celebration (`VotingCompleteView`) with a confetti burst and the shortlist
  button.
- VoiceOver: the card is one element with custom actions Like, Dislike, Must
  go, Add note, and Details; stamps and particles are hidden from it. Reduce
  Motion: no rotation or flight, cards crossfade, bursts become one emoji
  that fades.

### U3. Fun loading (`FunLoadingView` + `LoadingScript`)

One component, many scripts. It shows a big emoji that gently bobs, a line
that crossfades every 2.4 seconds, and a subtitle with what is at stake. Lines
mention the city when they can.

- Gathering (new `GatheringView` on its own route after trip creation, so the
  form no longer blocks): "Asking TikTok what's hot in Sapporo 🔥", "Reading
  the captions so you don't have to 📱", "Counting how many posts agree ✅",
  "Checking Google Maps that these places exist 🗺️", "Filtering out the
  tourist traps 🪤", "Sniffing out breakfast spots 🥐", "Making sure nothing
  is closed on Tuesdays 🚪", "Shuffling the good stuff to the top 🔀".
- Shortlist: "Tallying the votes 🗳️", "Finding what everyone agreed on 🤝",
  "Politely ignoring the dislikes 🙈".
- Stay: "Comparing pillows 🛏️", "Finding a bed near the action 📍".
- Plan (overlay on the stay screen while the solver runs): "Checking the
  forecast ☔", "Asking the solver nicely 🧮", "Keeping your must-gos safe ⭐",
  "Timing lunch for when you're actually hungry 🍜", "Measuring walks in
  coffee breaks ☕", "Writing your trip story ✍️".
- Deck and itinerary loads: two short scripts.

Errors keep their alerts; the loader never hides a failure.

### U4. Screen polish

- Plan a trip: hero header ("Where to? ✈️"), section icons, large prominent
  submit, and a "Continue planning" section listing recent trips.
- Recent trips: `RecentTripsStore` keeps every session the app created in
  UserDefaults (trip summary, traveler id, day window). Reopening the app
  offers them; tapping one fetches the trip's current status and jumps to the
  right step (swipe, shortlist, stay, itinerary). This is also how the UI is
  verified below without paying for a new gather.
- Saved posts: platform chips (Instagram, TikTok, RedNote) and status chips
  on attached rows.
- Shortlist: a summary card ("14 going, 3 must-go, 1 of 2 confirmed"),
  sections "Going 🎉" and "More ideas 💡", source chips on rows, a star that
  pops when marked, swipe actions to add, remove, and star.
- Choose a stay: card rows with a bed emoji, price shown as dots, selection
  that animates, trip dates in the header.
- Itinerary: the narrative in a "Your trip in a nutshell ✨" card at the top,
  day headers with the weekday, stops on a timeline (time column, dot and
  line), transit legs with a mode icon and minutes, meal emoji on food stops,
  wishlist reasons with an icon each.
- Replan review: colour-coded sections keep their meaning; the sheet gets
  detents and a clear "nothing changes until you approve" banner.
- Empty and error states keep `ContentUnavailableView` with warmer copy.

### U5. Accessibility and motion, applied everywhere

Reduce Motion read from the environment in every animated view; no fixed font
sizes; all buttons carry text labels even when shown as icons; colours are
never the only signal (stamps carry words, must-go has a star, transit has a
symbol).

### U6. Verification

- `xcodebuild` for the simulator after each package; the Swift contract test
  for every model change.
- Run on the booted iPhone 16e against the local backend, resuming the
  existing "Hokkaido" swiping trip and a "Lisbon, Porto" active trip from the
  database, and screenshot: the deck mid-drag with a stamp, a like burst, the
  gathering loader, the itinerary timeline, the shortlist summary.
- Dynamic Type at an accessibility size and Reduce Motion on, one pass each.

## 4. Order and done criteria

U1 → U2 → U3 → U4 → U5 (folded into each) → U6 throughout.

Done when: a card can be dragged and thrown with stamps, bursts, and haptics,
and the buttons still work; every wait over a second shows rotating lines;
the itinerary shows the narrative and a timeline; a closed app can resume a
trip; the app builds for the simulator with no warnings in new files; Reduce
Motion and a large Dynamic Type size both look intentional.

## 5. Decisions taken without asking

1. No fourth "must-go" button. CLAUDE.md 9.2 says the must-have signal is a
   long-press shortcut to reserve sparingly, so it stays a shortcut (long
   press or swipe up) with a hint, not a headline control.
2. Card details move to a sheet so the drag gesture owns the card. Nothing
   is removed; it is one tap further.
3. Recent trips live on the device only. There is no auth yet (CLAUDE.md
   15), so a server-side trip list would show everyone's trips.
4. Warm coral accent and rounded type. Easy to change in `AppTheme` and the
   asset catalog if you want another identity.
5. Optimistic voting. The deck moves before the server answers; a failed vote
   puts the card back.

## 6. Status, 2026-09-02

Built on branch `ui-ux-overhaul` (uncommitted, on top of the M5a merge) and
verified in the iPhone 16e simulator against the local backend, resuming two
existing trips from the database so no new gather was paid for.

| Package | State | Notes |
|---|---|---|
| U1 design system | done | `AppTheme`, asset catalog with light and dark brand colours, generated app icon, chips, round buttons, stamps, emoji bursts, fun loader |
| U2 Tinder-style deck | done | Drag with tilt and stamps, fly-off past the threshold or on a button, spring back under it, three-card pile that peeks, optimistic voting with a put-back on failure, photo prefetch, VoiceOver custom actions, Reduce Motion fades |
| U3 fun loading | done | Gathering has its own screen and script; shortlist, stay, plan, deck, and itinerary waits have scripts too |
| U4 screen polish | done | Home hero and "Continue planning", saved-posts platform chips and status chips, shortlist summary card, sections, star bounce and swipe actions, stay rows with selection animation, itinerary narrative card (folds when long), day headers with weekdays, timeline rows, transit legs, meal chips, wishlist icons |
| U5 accessibility | done | Dynamic Type checked at accessibility extra large, dark mode checked, chips shrink instead of overflowing, hint and subtitle step aside at large sizes |
| U6 verification | done with one gap | Screens captured at default size, large type, and dark mode; the drag gesture itself could not be exercised because the simulator MCP integration would not attach (see below), so the swipe was verified by reading the code and by the button path, which drives the same flight |

Two environment facts worth knowing:

- The Claude Code simulator integration refuses to attach and asks for
  `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`, although
  `xcode-select -p` already reports that path. Screens were driven with
  `xcrun simctl` instead (launch arguments open any screen; see the iOS README
  development knobs).
- On this macOS 15 host the iOS 26.3 simulator draws every emoji as a "?"
  box, in Safari too, so it is the runtime and not the app. Emoji stay where
  they are decorative; anything that carries meaning uses SF Symbols.

Not done, by choice: no fourth must-go button (kept as a shortcut), no
server-side trip list (no auth yet), no undo (votes are final in the API).

## 7. Redesign: the departure board

Written 2026-09-02 after the first pass was judged, correctly, to look
generated. Checked against `.agents/skills/ios-design-taste` section 1: the
first pass had a cream ground, a coral accent, an emoji-and-paragraph hero
card on every screen, pill chips on every row, "From X" captions with
sparkles, and everything centred. Six of the nine tells.

### Subject and the one idea

Friends plan a trip from the posts they send each other; a solver turns the
group's votes into days. The world's materials are departure boards, boarding
passes, luggage tags, and photo prints. The one idea: **the app is a
departure board**. Signage type, one signal colour, figures in a monospaced
grid, and photos as the only decoration. Playfulness stays in moments (the
loading board, the bursts, the end of the deck); the chrome is quiet.

### Tokens

| Token | Light | Dark | Used for |
|---|---|---|---|
| Ink | `#121212` | `#F2F2EE` | text, day bands, primary button text on Signal |
| Paper | `#FFFFFF` | `#0F0F0F` | ground |
| Slate | `#6A6B6E` | `#9A9B9E` | secondary text, meta lines |
| Hairline | `#DADAD6` | `#2A2A2A` | timetable rules only |
| Signal | `#FFC72C` | `#FFC72C` | the accent: primary button, progress, must-go, selection |
| Go / Stop | `#1F9D55` / `#D9342B` | same | like and dislike, semantic only |

Type: display is the system face condensed and bold, uppercase with tracking
for eyebrows and large for titles ("WHERE TO", "DAY 1"); body is the system
face at default; utility is the system monospaced face with tabular digits
for times, dates, counts, and codes ("08:00", "1 / 40", "SUN 27 SEP").

Signature element: the **board**. Black bands with condensed white type mark
each day; the loading screen is a board whose rows flip; the progress mark
on the deck is a Signal tag reading "1 / 40".

### Second-pass critique

- Light mode is white, black, and yellow: wayfinding, not one of the three
  clusters. Dark mode is black with a yellow accent, which sits next to the
  "near-black with one pop" cluster. Kept because departure boards are black
  with amber, so it is grounded in the subject rather than borrowed; the
  yellow is used as a surface (tags, bands, buttons) rather than a text pop.
- Hairlines appear only between timetable rows, never as decoration, and
  columns stay wide. No broadsheet.
- No emoji in chrome. Emoji remain in loading lines and bursts, which is what
  was asked for and where they read as moments.
- Corner radius: photos and the primary button keep a small radius; tags,
  bands, and rows are square. Not one radius everywhere.

### Screens, one line each

- Plan a trip: "WHERE TO" in condensed caps, then the form with placeholders
  doing the explaining, no hero card. Saved trips as tickets: destination in
  condensed caps, dates in mono, a small Signal tab for the stage.
- Finding places: full-screen board, black, rows of yellow condensed text
  flipping through what the agent is doing.
- Saved posts: an eyebrow, one line, the field. Attached posts as rows with
  the platform in mono caps and the state in words.
- Swipe: the photo is the card; a white stub at the bottom holds the name in
  condensed caps, "Park · 90 min" in mono, and the source as a mono link.
  Stamps are Signal and Ink boxes in condensed caps. The like button is the
  one Signal circle on screen.
- Shortlist: a black board line "14 GOING · 2 MUST-GO · 1/2 CONFIRMED", then
  plain rows; a must-go is a Signal star, nothing else on the row changes.
- Stay: rows with the name, town, price as mono "$$", the pick as a Signal
  square.
- Itinerary: "IN SHORT" eyebrow over the narrative; each day a black band;
  stops as a timetable, mono times left, hairline between stops, transit as
  "12 MIN WALK" in mono between them.

### Copy

Every explanatory sentence goes unless it changes what a tap does. Kept:
photo attribution, the availability note, the quorum rule on the shortlist,
the swipe hint (one line, once). Loading scripts trimmed to six lines each.

## 8. Redesign status, 2026-09-02

Built on `ui-ux-overhaul` (uncommitted) and captured in the iPhone 16e
simulator against the local backend, light and dark, default and
accessibility text sizes.

- Every screen now draws from `AppTheme` and `AppType`: ink, paper, slate,
  hairline, one signal yellow, condensed signage for titles and bands, the
  monospaced face for every figure.
- Words cut: the hero paragraphs, section footers, "From X" captions, and
  chip labels are gone; placeholders explain the fields; the swipe hint is
  one monospaced line shown once.
- Structure now differs per screen: a form with tickets, a black board while
  gathering, a photo print with a stub on the deck, a board line over the
  shortlist, a checklist for the stay, a timetable for the itinerary.
- Emoji survive only in the loading lines and the bursts.
- Fixed along the way: the yellow tag bled into the status bar (SwiftUI's
  `background` ignores safe-area edges by default), eyebrows at a zero row
  inset lost their first glyph, full-width buttons in plain lists touched the
  screen edges, and a trip reopened at the shortlist step failed because the
  server only builds a shortlist once (the app now reads it back instead).
- New project skill `.agents/skills/ios-design-taste` records the tells to
  avoid and the plan-then-critique process, and CLAUDE.md section 18 lists
  it.

## 9. Second redesign: the trip journal

The board was rejected, correctly: black-and-yellow with monospace and hard
edges is the "anti-slop" cluster, which the community `design-anti-slop`
skill warns has become its own attractor. Swapping one cluster for another is
not a design decision, and none of it said travel.

### The three layers, checked deepest first

- **Conceptual.** The app's claim is not "plan a trip". It is: the places
  come from posts your friends actually sent, and every card can prove where
  it came from. The design should make provenance and group approval visible.
  This is what the board never expressed.
- **Structural.** Each screen is a different kind of page in one document: a
  cover, a page being written, a photo taped in, a ledger, a timetable.
- **Visual.** Falls out of the above rather than driving it.

### The idea

**The trip is a document you collect.** A journal with photos taped in,
stamped as the group decides. The signature element is the **stamp**: every
decision lands as a rubber stamp at an angle, in stamp ink. Liked, passed,
must go, confirmed. The swipe gesture already throws a card, so the stamp is
the motion and the identity at once, not decoration applied afterwards.

This also answers the conceptual layer: a stamp is evidence that someone
decided something, which is what this product is about.

### Tokens

| Token | Light | Dark | Role |
|---|---|---|---|
| Paper | `#F0EFE9` | `#16181C` | ground, a stone paper with a green-grey cast, not warm cream |
| Ink | `#1D2B4F` | `#E9E7DF` | text, an indigo pen rather than black |
| Faded | `#6E7180` | `#94968F` | secondary text, faded ink |
| Rule | `#D8D6CD` | `#2C2F33` | ledger hairlines |
| Stamp | `#D2452B` | `#E85A3F` | vermilion: liked, primary actions, the trending mark |
| Jade | `#1F7A5C` | `#35A37C` | entry-stamp green: confirmed, selected, gone-through |
| Violet | `#6A4FA3` | `#9A7FD1` | second stamp ink: must-go |

Three inks, not one accent, because a passport page has several and the app
has several kinds of approval. Semantic and identity colour are the same
thing here, which is the point.

Type:

- **Display: Instrument Serif**, bundled (SIL OFL, licence kept beside the
  file). High-contrast, slightly odd, and rare in generated work. Place
  names, screen titles, the loading line.
- **Body: the system face.** It is a good face and, inside an iOS app, not a
  tell.
- **Figures: the system monospaced face**, uppercase with tracking, for
  times, dates, counts, and stamp text.

### Second-pass critique

- Paper plus a serif display is adjacent to the warm-editorial cluster. The
  paper is pushed cool and green-grey rather than cream, the accent is a hot
  vermilion rather than muted terracotta, and there are three stamp inks
  rather than one accent. The stamps are what make it read as a passport
  rather than a Substack.
- Instrument Serif does a lot of work. Kept, because it is the one bold move
  and everything around it stays quiet, but it is used only for names and
  titles, never for body text or labels.
- Angled stamps risk cuteness. They appear only on decisions, at most one per
  card, and they respect Reduce Motion by fading rather than thudding.
- No emoji in chrome. They stay in the loading lines and the bursts.

### Screens

- **Cover.** "Where to" in Instrument Serif over the form. Saved trips are
  journal entries, each with the stamp of its stage.
- **Finding places.** A paper page, not a black screen: the current line set
  large in the serif, previous lines fading above it like a page being
  written.
- **Swipe.** The photo taped to paper with the name in serif on the stub
  below. Stamps land at an angle in stamp ink.
- **Shortlist.** A ledger: ruled rows, a violet star stamp for must-go, the
  group's tally as a stamped line rather than a black band.
- **Stay.** Ledger rows with a jade stamp box for the chosen one.
- **Itinerary.** Journal pages: a stamped date for each day, then a timetable
  with monospaced times and hairline rules.

## 10. Journal status, 2026-09-02

Built on `ui-ux-overhaul` and captured in the iPhone 16e simulator in light,
dark, and at an accessibility text size.

- **Typeface bundled.** Instrument Serif (SIL OFL, licence kept beside the
  files in `Design/Fonts`) is registered through `UIAppFonts` and carries
  every place name and screen title. Body stays on the system face, figures
  on the system monospaced face.
- **Stamps are real.** `StampMark` and `StampView` print the app's approvals:
  liked, passed, must go, confirmed, and each trip's stage. They appear on
  the saved-trip rows, the day headers, the end of the deck, and ride in with
  the drag on the deck itself.
- **Three inks, not one accent.** Vermilion for likes and what other people
  are posting about, jade for anything settled, violet for must-go. Semantic
  colour and identity colour are the same thing, which is the point.
- **One page treatment.** `journalPage()` and `journalRow()` put every screen
  and every row on the same paper, so nothing falls back to the system's
  grouped grey.

### What community skills changed about the approach

The three-layer taxonomy from `design-anti-slop` is why this pass started
with what the app claims rather than with a palette, and its "not a pendulum"
warning is what identified the black-and-yellow board as a second default
rather than a fix. Both are now recorded in
`.agents/skills/ios-design-taste`, section 0, with the sources listed at the
end of that file.

### One incident worth recording

Part-way through this pass a `git checkout -- Features` reverted eighteen
tracked screen files to their pre-redesign state, because none of this work
had been committed. The files were rewritten and the work is intact, but the
branch is committed now rather than left in the working tree.
