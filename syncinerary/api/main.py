"""FastAPI entrypoint.

M2 keeps the M1 API surface and routes its external calls through the
reliability harness (CLAUDE.md §12.1):
- GET  /health                        Smoke test.
- POST /trips                         Create a trip plus its creator traveler.
- GET  /trips/{id}                    Trip detail.
- GET  /trips/{id}/candidates         The swipe deck (lodging excluded, §8.6).
- POST /trips/{id}/votes              One swipe: like or dislike.
- GET  /trips/{id}/votes/progress     How far through the deck a traveler is.
- POST /trips/{id}/gather             Run to the swipe interrupt.
- POST /trips/{id}/plan               Resume through solver and explainer.
- GET  /trips/{id}/itinerary          Read the active planned version.

Replan and the websocket land in M6.

Uses the `lifespan` async context manager, not `@app.on_event`, which is
deprecated in FastAPI 0.100+ (CLAUDE.md §14).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from syncinerary.agents.graph import dispose_graph, init_graph
from syncinerary.api.routers import (
    accounts,
    ai_credentials,
    booked_hotels,
    checklist,
    gather,
    group,
    itinerary_edits,
    replans,
    social_accounts,
    trips,
)
from syncinerary.config import settings
from syncinerary.obs.tracing import init_tracing
from syncinerary.store.db import dispose_engine, init_engine
from syncinerary.store.redis import dispose_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn configures only its own loggers, so without this the
    # application's own records never reach the terminal.
    logging.basicConfig(
        level=settings.sync_log_level.upper(),
        format="%(levelname)-7s %(name)s  %(message)s",
    )
    init_tracing()
    init_engine()
    init_redis()
    await init_graph()
    yield
    # Return pooled connections. Spans flush via BatchSpanProcessor.
    await dispose_graph()
    await dispose_redis()
    await dispose_engine()


app = FastAPI(title="Syncinerary", version="0.1.0+m2", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path.startswith("/auth/"):
        # FastAPI normally echoes invalid input, which can include passwords.
        return JSONResponse(status_code=422, content={
            "detail": "Check your email, name, 8-digit code and password length (8 to 128 characters)."
        })
    if request.url.path in {
        "/accounts/me/anthropic-key",
        "/accounts/me/delete",
    }:
        # The default validation body could echo the submitted credential.
        return JSONResponse(status_code=422, content={
            "detail": "Check the submitted fields and try again. Sensitive values are not echoed."
        })
    return await request_validation_exception_handler(request, error)


app.include_router(booked_hotels.router)
app.include_router(checklist.router)
app.include_router(accounts.router)
app.include_router(social_accounts.router)
app.include_router(ai_credentials.router)
app.include_router(ai_credentials.consent_router)
app.include_router(gather.router)
app.include_router(group.router)
app.include_router(trips.router)
app.include_router(replans.router)
app.include_router(itinerary_edits.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "milestone": "M2"}
