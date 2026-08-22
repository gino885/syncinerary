"""FastAPI entrypoint.

M1 surface (CLAUDE.md §13 Phase A):
- GET  /health                        Smoke test.
- POST /trips                         Create a trip plus its creator traveler.
- GET  /trips/{id}                    Trip detail.
- GET  /trips/{id}/candidates         The swipe deck (lodging excluded, §8.6).
- POST /trips/{id}/votes              One swipe: like or dislike.
- GET  /trips/{id}/votes/progress     How far through the deck a traveler is.

Planning endpoints arrive with the graph wiring in M1-9; replan and the
websocket land in M6.

Uses the `lifespan` async context manager, not `@app.on_event`, which is
deprecated in FastAPI 0.100+ (CLAUDE.md §14).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from syncinerary.api.routers import trips
from syncinerary.obs.tracing import init_tracing
from syncinerary.store.db import dispose_engine, init_engine
from syncinerary.store.redis import dispose_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_tracing()
    init_engine()
    init_redis()
    yield
    # Return pooled connections. Spans flush via BatchSpanProcessor.
    await dispose_redis()
    await dispose_engine()


app = FastAPI(title="Syncinerary", version="0.1.0+m1", lifespan=lifespan)
app.include_router(trips.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "milestone": "M1"}
