# Syncinerary

Group Travel Agent OS. See `CLAUDE.md` for the full design brief.

This repo is currently at **M0 (Scaffold)**. See `CLAUDE.md` §13 for the milestone map.

## What M0 includes

- Docker compose: Postgres (with pgvector), Redis, Phoenix
- FastAPI app with `/health` and `/m0/noop` endpoints
- Empty LangGraph that emits an OTel span to Phoenix
- All pydantic domain models from `CLAUDE.md` §7
- Centralized config with defaults from `CLAUDE.md` §16
- iOS scaffold (SwiftUI) that calls `/health`

## M0 acceptance gate (run this to verify)

```bash
# 1. Copy env template
cp .env.example .env
# ANTHROPIC_API_KEY is not strictly needed for M0 (no LLM calls)

# 2. Bring up infra
docker compose up -d
docker compose ps              # all three services should be healthy

# 3. Install Python deps
pip install -e ".[dev]"

# 4. Run the API
uvicorn syncinerary.api.main:app --reload

# 5. Health check
curl http://localhost:8000/health
# -> {"status":"ok","milestone":"M0"}

# 6. Run the no-op graph (this emits a span to Phoenix)
curl -X POST http://localhost:8000/m0/noop \
  -H "Content-Type: application/json" \
  -d '{"destination":"Hokkaido","start_date":"2026-05-21","end_date":"2026-05-26"}'

# 7. Open Phoenix and look for the "noop_node" span
open http://localhost:6006

# 8. Run smoke test
pytest tests/test_m0_smoke.py
```

## M0 done when

- All three docker services healthy.
- `curl /health` returns ok.
- `curl /m0/noop` returns ok AND a `noop_node` span is visible in Phoenix.
- `pytest tests/test_m0_smoke.py` passes.
- iOS app launches and shows "Backend: ok (M0)".

## Next: M1

Thin vertical slice. See `CLAUDE.md` §13 Phase A → M1.

## Layout

```
syncinerary/
├── agents/graph.py         # M0: no-op LangGraph; real nodes from M1+
├── api/main.py             # FastAPI app (M0: /health, /m0/noop)
├── config/                 # Defaults from CLAUDE.md §16
├── domain/models.py        # Pydantic models from CLAUDE.md §7
├── obs/tracing.py          # OTel → Phoenix exporter
├── store/db.py             # Async SQLAlchemy engine
└── (harness, delegate, solver, eval, tools)  # Empty for M0; populated in M2+
ios/                        # SwiftUI scaffold (see ios/README.md)
docker/postgres-init.sql    # Enables pgvector extension
```
