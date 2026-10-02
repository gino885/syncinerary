# Email sign-in and verification

Audience: friends opening a shared travel plan on iPhone. The screen's job is to establish a verified account and return to the intended trip.

Reuse the app's light/dark asset tokens: Canvas (#F2F5FF), Ink (#17233D), Faded (#56617B), Accent (#3452DF), Surface (#FFFFFF), semantic Stamp for errors. Rounded heavy display, system body, monospaced digits only for the email code. Verify actual asset values during visual review.

Layout: a left-aligned app title, a compact sign-in/create-account choice, persistent field labels, a full-width action, and a password-reset action. A scroll view keeps the form reachable above the keyboard and at accessibility sizes. Verification and reset use an eight-digit email code entered in the app; passwords never appear in email. An accepted invite stays pending through the entire flow. Restore has a loading state and an explicit retry screen so offline launches do not discard credentials.

Critique: remove the earlier decorative ruled-paper treatment. No hero illustration, emoji, gradient, repeated cards, or promises of secure/public readiness. The signature is the invite-aware heading, returning people to their friends' trip. Spend cobalt on the primary action. Motion is only the existing button feedback and respects Reduce Motion. Errors use text as well as color; all targets are at least 44pt. Password fields support Password AutoFill, email uses the email keyboard, and verification uses one-time-code autofill.

Acceptance: verify email before login, reject wrong passwords, single-use expiring codes, rate limits, server logout and reset revocation; preserve saved sessions on connection errors; prevent duplicate submits and stale completions after logout. Exercise signup, verification, sign-in, invite/join and checklist sharing through HTTP with real Postgres/Redis and a local SMTP inbox. Exercise scheduling via the existing real solver/graph integration tests with vendor fixtures. Inspect light, dark and accessibility screenshots. External email delivery and physical-device testing remain separate checks.
