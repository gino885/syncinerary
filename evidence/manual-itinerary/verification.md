# Manual itinerary editing verification

September 18, 2026.

## Automated checks

Full backend suite: **835 passed** in 145.01 seconds, including **20 manual
itinerary checks**. Raw output: backend-tests.log. The focused-tests.log file
records the earlier 19-test pass before the final concurrent-version test.

- Backend regression tests cover add, remove, day/time/duration edits, exact
  selections, Adjust this day, approval and API reload, rejection, empty days,
  unchanged prior versions, fixed reservations, foreign candidates, city
  conflicts, dietary conflicts, closed venues, overlap, transit gaps, provider
  failure, pending proposals, stale versions (including a version change during
  transit validation), legacy city allocation and original duration limits.
- Search tests establish that results remain ephemeral until selection,
  forged selections fail, repeat selections deduplicate, and account-bound
  travelers cannot be impersonated without signing in.
- Swift ManualItineraryTests passed: exact request encoding, user_request
  decoding, reorder/remove, reservation protection, immutable original plan
  and retaining draft state after API failure.
- Existing Swift APIContractTests passed.
- The shipping iOS Debug simulator build passed. The only reported warning is
  Xcode's skipped AppIntents metadata extraction because no AppIntents framework
  dependency exists.
- Deterministic evaluation: 10/10 fixtures passed with --no-store and no model
  calls. No previous stored commit was available for comparative scoring.
- Ruff and git diff --check passed.

## Visual checks

Inspected screenshots of the five affected screens in normal light, normal
dark and accessibility-extra-large text using iPhone 17 Pro / iOS 26.3.
See ui-plan.md and screenshots/. The QA app was built from a temporary copy of
the real views with fixture responses. It was not shipped or connected to live
providers. The temporary simulator was removed after verification.

## Limits

Provider calls in the new API tests use deterministic doubles. This change has
not been verified through a live Google/transit/social-provider editing session,
a physical device, VoiceOver navigation, or an automated UI tap-through. The
existing provider integrations are reused. Unknown place hours and dietary
information retain the existing planner's limitations.

No new schema migration, dependency, commit or deployment was made for manual
editing. Prior discovery and UI work remains in the shared working tree.
