# Verification record

Verified locally on October 2, 2026, for the combined product changes and
recruiter README. This records reproducible development checks, not a production
deployment or a live-provider end-to-end run.

## Results

| Check | Result |
|---|---|
| Python suite | 914 passed, no skips, in 153.46 seconds |
| Ruff | Passed for `syncinerary` and `tests` |
| Alembic | Upgrade to head, downgrade to base, upgrade to head passed |
| Swift contract and view-model programs | All 10 passed |
| Xcode Debug Simulator build | Passed with code signing disabled |
| Deterministic itinerary evaluation | 10/10 fixtures passed in 28.22 seconds |
| Discovery admission evaluation | 14 cases; zero invalid admissions and zero false rejections |
| Deliberate fatigue-cap break | Evaluation failed with exit code 1, as expected |

Timing is a single local run, not a performance benchmark. Tests used a separate
PostgreSQL database with pgvector and the local Redis service. The migration
round trip ran only against that disposable database, never the app database.

## Reproduce

Install the development dependencies and start Docker as described in the
[root README](../README.md#run-locally). Use an empty, disposable PostgreSQL
database if you want to repeat the destructive migration round trip. Point
`DATABASE_URL` at that database before running:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade base
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check syncinerary tests
.venv/bin/python -m syncinerary.eval.runner --no-store
.venv/bin/python -m syncinerary.eval.discovery
```

Prove the evaluation can detect a broken constraint:

```bash
.venv/bin/python -m syncinerary.eval.runner --break fatigue-cap --no-store
```

That command is expected to fail. The normal run passed all ten fixtures;
there was no previous stored commit in the disposable database, so this run
did not measure a cross-commit quality improvement.

On macOS with Xcode:

```bash
bash scripts/test_ios.sh
xcodebuild -project ios/Syncinerary.xcodeproj -scheme Syncinerary \
  -configuration Debug -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/syncinerary-verification-build \
  CODE_SIGNING_ALLOWED=NO build
```

The Swift runner covers API contracts, account lifecycle, Anthropic credentials,
chat routing, city-day allocation, gather lifecycle, manual itinerary drafts,
preparation/checklists, privacy controls, and chat request recovery. It compiles
and runs local test executables; it is not an automated UI tap-through suite.

## Scope and limits

- Backend provider tests use controlled responses. No live discovery, paid
  model evaluation, real OAuth login, or email-provider delivery was run here.
- Existing screenshots use fixture data and retain their original dates. See
  [UI verification](../evidence/ui-refresh/verification.md) and
  [discovery evidence](../evidence/reels/README.md) for their separate scope.
- The build was a Debug Simulator build. App Store signing, release hosting,
  physical-device AutoFill, VoiceOver interaction, and haptics remain unverified
  by this check.
- No user trips or votes were regenerated. Local `.env` credentials, generated
  caches, and build products are excluded from version control.
