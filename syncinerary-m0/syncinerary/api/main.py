"""FastAPI entrypoint.

M0 surface (CLAUDE.md §13 Phase A):
- GET  /health        Smoke test.
- POST /m0/noop       Build a TripState and run the no-op graph. Verifies that
                      LangGraph -> OpenInference -> OTel -> Phoenix is wired
                      end to end.

Real endpoints (trips, votes, shortlist, replan, websocket) land in M1+.

Note: uses the `lifespan` async context manager, not `@app.on_event`. The
latter is deprecated in FastAPI 0.100+ (see CLAUDE.md §14 conventions).
"""
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from syncinerary.agents.graph import run_noop
from syncinerary.domain.models import Trip, TripState
from syncinerary.obs.tracing import init_tracing


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_tracing()
    yield
    # Shutdown (nothing to release in M0; spans flush via BatchSpanProcessor)


app = FastAPI(title="Syncinerary", version="0.1.0-M0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "milestone": "M0"}


class NoopRequest(BaseModel):
    destination: str = "Hokkaido"
    start_date: date = date(2026, 5, 21)
    end_date: date = date(2026, 5, 26)


@app.post("/m0/noop")
async def m0_noop(req: NoopRequest) -> dict[str, str]:
    days = (req.end_date - req.start_date).days + 1
    trip = Trip(
        destination=req.destination,
        start_date=req.start_date,
        end_date=req.end_date,
        days=days,
    )
    state = TripState(trip=trip)
    await run_noop(state)
    return {
        "status": "ok",
        "trip_id": str(trip.id),
        "note": "Check Phoenix at http://localhost:6006 for the graph span.",
    }
