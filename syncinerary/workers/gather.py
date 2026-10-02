"""Run with `.venv/bin/python -m syncinerary.workers.gather`.

Postgres is both the durable queue and the ownership authority. No dual write
between a database record and a broker can strand a queued run. Each process
runs one graph at a time; add processes to increase throughput.
"""

import asyncio
import logging
from contextlib import nullcontext, suppress

from syncinerary.agents.gather.live import LiveDiscoveryInsufficient
from syncinerary.agents.gather.personal import resolve_link_attachment
from syncinerary.agents.gather.progress import progress_sink
from syncinerary.agents.graph import dispose_graph, graph_config, init_graph
from syncinerary.ai_credentials import AnthropicConsentUnavailable
from syncinerary.config import settings
from syncinerary.config.gather import gather_max_steps
from syncinerary.domain.gather import GatherRun
from syncinerary.domain.models import AttachmentStatus, TripState, TripStatus
from syncinerary.harness import (
    CreatorCredentialUnavailable,
    tracked_run,
    use_anthropic_api_key,
)
from syncinerary.obs.tracing import get_tracer, init_tracing
from syncinerary.store.db import dispose_engine, init_engine, session_scope
from syncinerary.store.redis import dispose_redis, init_redis
from syncinerary.store.repositories import (
    AccountRepository,
    AnthropicCredentialRepository,
    CandidatePlaceRepository,
    GatherRunRepository,
    SourceAttachmentRepository,
    TripRepository,
)
from syncinerary.store.repositories.gather import check_ownership, own_gather

logger = logging.getLogger(__name__)


async def execute_run(run: GatherRun, graph) -> None:
    credential_scope = nullcontext()
    if run.credential_account_id is not None:
        async with session_scope() as session:
            missing = await AccountRepository(
                session
            ).missing_anthropic_consent_for_trip(run.trip_id)
            if missing:
                raise AnthropicConsentUnavailable(
                    "Every trip member must approve Anthropic data sharing"
                )
            api_key = await AnthropicCredentialRepository(session).reveal(
                run.credential_account_id
            )
        if api_key is None:
            raise CreatorCredentialUnavailable("Trip creator has no Anthropic credential")
        credential_scope = use_anthropic_api_key(api_key)
    with credential_scope, get_tracer().start_as_current_span(
        "gather.run",
        attributes={
            "trip_id": str(run.trip_id),
            "run_id": str(run.id),
            "gather.snapshot.members": len(run.input_snapshot.travelers),
            "gather.snapshot.links": len(run.input_snapshot.attachments),
        },
    ):
        await _execute_run(run, graph)


async def _execute_run(run: GatherRun, graph) -> None:
    """Resume only gather/badges; never cross the human swipe interrupt."""
    snapshot = run.input_snapshot
    config = graph_config(run.trip_id)
    checkpoint = await graph.aget_state(config)
    from opentelemetry import trace

    trace.get_current_span().set_attribute("gather.resumed_checkpoint", bool(checkpoint.values))
    if checkpoint.values and checkpoint.next not in {("gather",), ("badges",), ("aggregate",)}:
        raise RuntimeError("Unexpected checkpoint during discovery")
    async with tracked_run(
        trip_id=run.trip_id,
        kind="gather",
        max_steps=gather_max_steps(
            default_max_steps=settings.sync_max_steps,
            days=snapshot.trip.days,
            cities=max(1, len(snapshot.trip.cities)),
        ),
    ):
        if not checkpoint.values:
            for attachment in snapshot.attachments:
                async with session_scope() as session:
                    saved = await SourceAttachmentRepository(session).get(attachment.id)
                    if saved is not None and saved.status is AttachmentStatus.PENDING:
                        await resolve_link_attachment(attachment, snapshot.trip, session)
            await graph.ainvoke(
                TripState(
                    trip=snapshot.trip,
                    travelers=snapshot.travelers,
                    constraints=snapshot.constraints,
                ),
                config,
            )
        elif checkpoint.next != ("aggregate",):
            await graph.ainvoke(None, config)
    checkpoint = await graph.aget_state(config)
    if checkpoint.next != ("aggregate",):
        raise RuntimeError("Discovery did not reach the swipe checkpoint")
    async with session_scope() as session:
        deck = await CandidatePlaceRepository(session).list_swipeable(run.trip_id)
        if not deck:
            raise LiveDiscoveryInsufficient("No usable places")
        await TripRepository(session).set_status(run.trip_id, TripStatus.SWIPING)
        await GatherRunRepository(session).change(
            run.id, status="completed", phase="deck_build", deck_size=len(deck), error_code=None
        )


async def work_one(graph) -> bool:
    async with session_scope() as session:
        pending = await GatherRunRepository(session).pending()
    for candidate in pending:
        async with own_gather(candidate.trip_id) as ownership:
            if ownership is None:
                continue
            async with session_scope() as session:
                run = await GatherRunRepository(session).get(candidate.id)
                if run.status not in {"queued", "running"}:
                    continue
                run = await GatherRunRepository(session).change(run.id, status="running")
            units = run.completed_units

            async def progress(phase, city, run=run):
                nonlocal units
                units += 1
                async with session_scope() as session:
                    await GatherRunRepository(session).change(
                        run.id, phase=phase, city=city, completed_units=units
                    )

            async def heartbeat(run=run):
                while True:
                    await asyncio.sleep(10)
                    # A disconnected lock connection must never reconnect and
                    # pretend it still owns the advisory lock.
                    if ownership.invalidated:
                        raise RuntimeError("Worker ownership connection lost")
                    await check_ownership(ownership)
                    async with session_scope() as session:
                        await GatherRunRepository(session).change(run.id)

            token = progress_sink.set(progress)
            execution = asyncio.create_task(execute_run(run, graph))
            pulse = asyncio.create_task(heartbeat())
            try:
                done, _ = await asyncio.wait(
                    {execution, pulse}, return_when=asyncio.FIRST_COMPLETED
                )
                if execution in done:
                    await execution
                else:
                    # Ownership/heartbeat failure is recoverable. Stop all
                    # work before releasing the lock and keep the durable job
                    # running so another process can resume its checkpoint.
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                    return True
            except asyncio.CancelledError:
                # Remain running: another worker resumes after lock release.
                raise
            except Exception as exc:  # noqa: BLE001 - persist sanitized job failure at worker boundary
                execution.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await execution
                # No exception text is persisted: SDK failures may contain URLs
                # with credentials or private request bodies.
                code = (
                    "no_usable_places"
                    if isinstance(exc, LiveDiscoveryInsufficient)
                    else "consent_required"
                    if isinstance(exc, AnthropicConsentUnavailable)
                    else "credential_missing"
                    if isinstance(exc, CreatorCredentialUnavailable)
                    else "provider_failure"
                )
                logger.error(
                    "Gather failed trip=%s run=%s type=%s", run.trip_id, run.id, type(exc).__name__
                )
                async with session_scope() as session:
                    await GatherRunRepository(session).change(
                        run.id, only_status="running", status="failed", error_code=code
                    )
            finally:
                execution.cancel()
                pulse.cancel()
                await asyncio.gather(execution, pulse, return_exceptions=True)
                progress_sink.reset(token)
            return True
    return False


async def main():
    logging.basicConfig(level=logging.INFO)
    init_tracing()
    init_engine()
    init_redis()
    graph = await init_graph()
    try:
        while True:
            if not await work_one(graph):
                await asyncio.sleep(2)
    finally:
        await dispose_graph()
        await dispose_redis()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
