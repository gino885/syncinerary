# Syncinerary

Group Travel Agent OS. The canonical build brief is in `CLAUDE.md`.

The repository is currently at **M2: Reliability Harness**. The M1 vertical
slice plans a Hokkaido trip end to end, and M2 puts every existing LLM and
external tool call behind one reliability boundary.

## What works

- Create a trip, gather the Hokkaido candidate fixture, and swipe Like or
  Dislike.
- Deterministically aggregate votes and select the shortlist.
- Build a day-by-day route using Google walking and public transit durations.
- Generate the final itinerary narrative with Anthropic.
- Run the three-screen SwiftUI flow in the iPhone Simulator.
- Validate and repair typed tool arguments within a fixed attempt cap.
- Detect repeated state and equivalent tool-call cycles.
- Stop runs that exceed step or model-cost budgets while preserving an
  `agent_run` record with partial counters and a Phoenix trace ID.

## Local setup

Python 3.12 is required. Use the repository virtual environment rather than a
global interpreter.

```bash
uv venv --python 3.12
uv pip install -e '.[dev]'
cp .env.example .env
```

Set `GOOGLE_MAPS_API_KEY` and `ANTHROPIC_API_KEY` in `.env`, then start the
infrastructure and apply migrations:

```bash
docker compose up -d
.venv/bin/alembic upgrade head
```

Run the API:

```bash
.venv/bin/uvicorn syncinerary.api.main:app --reload
```

The health endpoint is `http://localhost:8000/health`. Phoenix is available at
`http://localhost:6006`.

## Verification

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check syncinerary tests
```

The GitHub workflow runs the same backend suite with Postgres and Redis. It
also rejects direct Anthropic, OpenAI, or LangChain provider imports from
`syncinerary/agents` and `syncinerary/tools`.

For the iOS setup and Simulator command, see `ios/README.md`.

## Layout

```text
syncinerary/
├── agents/              # LangGraph nodes and deterministic solver
├── api/                 # FastAPI routes and wire schemas
├── config/              # Environment-backed and domain defaults
├── domain/              # Pydantic state and persistence models
├── harness/             # M2 validation, loop, and budget boundary
├── obs/                 # OpenTelemetry and Phoenix integration
├── store/               # SQLAlchemy tables, repositories, and migrations
└── tools/               # Typed external integrations
ios/                     # SwiftUI app and API contract regression test
tests/                   # M0 through M2 acceptance and regression tests
```

The next milestone is M3, the full gather strategy with automatic discovery,
traveler links and screenshots, contributor provenance, source attribution,
and permitted card images.
