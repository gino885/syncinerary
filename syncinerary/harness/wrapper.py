"""Single execution boundary for every LLM and tool call."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from syncinerary.config import settings
from syncinerary.config.harness import (
    LOOP_HASH_REPEAT_THRESHOLD,
    NO_PROGRESS_WINDOW,
    TOOL_ARG_CYCLE_THRESHOLD,
)
from syncinerary.domain.models import AgentRun
from syncinerary.harness.budget import BudgetExceeded, RunBudget, TokenPricing
from syncinerary.harness.loop_detector import LoopDetector, NoProgress, ToolCycle
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import AgentRunRepository


class LLMTextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class LLMBase64ImageSource(BaseModel):
    type: Literal["base64"] = "base64"
    media_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"]
    data: str = Field(min_length=1)


class LLMImageBlock(BaseModel):
    type: Literal["image"] = "image"
    source: LLMBase64ImageSource


LLMContentBlock = Annotated[LLMTextBlock | LLMImageBlock, Field(discriminator="type")]


class LLMMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str | list[LLMContentBlock]


class LLMJSONSchemaFormat(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["json_schema"] = "json_schema"
    schema_: dict[str, Any] = Field(alias="schema")


class LLMOutputConfig(BaseModel):
    effort: str | None = Field(default=None, min_length=1)
    format: LLMJSONSchemaFormat | None = None


class LLMRequest(BaseModel):
    model: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    system: str
    messages: list[LLMMessage]
    output_config: LLMOutputConfig | None = None

    def provider_kwargs(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude_none=True, by_alias=True)


class LLMUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class UsageUnavailable(RuntimeError):
    """The provider response could not be safely charged to the run budget."""


class MessagesClient(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[Any]]


def _trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None


class PostgresRunRecorder:
    """Persist counters in short transactions outside external API calls."""

    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory or session_scope

    async def start(self, *, trip_id: UUID, kind: str) -> AgentRun:
        async with self._session_factory() as session:
            return await AgentRunRepository(session).add(
                AgentRun(
                    trip_id=trip_id,
                    kind=kind,
                    status="running",
                    trace_id=_trace_id(),
                )
            )

    async def progress(
        self,
        run_id: UUID,
        *,
        status: str | None = None,
        step_count: int,
        token_cost: Decimal,
    ) -> None:
        async with self._session_factory() as session:
            updated = await AgentRunRepository(session).record_progress(
                run_id,
                status=status,
                step_count=step_count,
                token_cost=token_cost,
            )
            if updated is None:
                raise RuntimeError(f"agent run {run_id} disappeared during execution")


@dataclass
class RunLedger:
    run_id: UUID
    recorder: PostgresRunRecorder
    budget: RunBudget
    detector: LoopDetector

    async def _persist(self, *, status: str | None = None) -> None:
        await self.recorder.progress(
            self.run_id,
            status=status,
            step_count=self.budget.step_count,
            token_cost=self.budget.token_cost_usd,
        )

    async def before_call(
        self,
        *,
        operation: str,
        arguments: Any,
        state: Any,
        tool_name: str | None,
    ) -> None:
        try:
            self.budget.charge_step()
            if state is not None:
                self.detector.observe_state(state)
            if tool_name is not None:
                self.detector.observe_tool(tool_name, arguments)
        finally:
            await self._persist()

    async def record_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        pricing: TokenPricing,
    ) -> None:
        try:
            self.budget.charge_tokens(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                pricing=pricing,
            )
        finally:
            await self._persist()


_current_run: ContextVar[RunLedger | None] = ContextVar("harness_run", default=None)


async def before_call(
    *,
    operation: str,
    arguments: Any,
    state: Any = None,
    tool_name: str | None = None,
) -> None:
    ledger = _current_run.get()
    if ledger is not None:
        await ledger.before_call(
            operation=operation,
            arguments=arguments,
            state=state,
            tool_name=tool_name,
        )


def log_attempt(
    *,
    operation: str,
    attempt: int,
    status: str,
    error: str | None = None,
) -> None:
    """Attach one bounded attempt record to the active OTel span."""
    attributes: dict[str, str | int] = {
        "operation": operation,
        "attempt": attempt,
        "status": status,
    }
    if error is not None:
        attributes["error"] = error[:1000]
    trace.get_current_span().add_event("harness.attempt", attributes=attributes)


def make_messages_client() -> MessagesClient:
    """Construct the provider client inside the mandatory harness boundary."""
    from anthropic import AsyncAnthropic

    api_key = settings.anthropic_api_key or None
    return AsyncAnthropic(api_key=api_key).messages


async def call_llm(
    request: LLMRequest,
    *,
    client: MessagesClient | None = None,
    pricing: TokenPricing | None = None,
    state: Any = None,
) -> Any:
    """Execute one typed LLM request and account for its actual usage."""
    await before_call(
        operation=f"llm:{request.model}",
        arguments=request.model_dump(mode="json"),
        state=state,
    )
    operation = f"llm:{request.model}"
    log_attempt(operation=operation, attempt=1, status="executing")
    try:
        response = await (client or make_messages_client()).create(
            **request.provider_kwargs()
        )
    except Exception as exc:
        log_attempt(
            operation=operation,
            attempt=1,
            status="failed",
            error=type(exc).__name__,
        )
        raise
    ledger = _current_run.get()
    if ledger is not None:
        try:
            usage = LLMUsage.model_validate(
                getattr(response, "usage", None),
                from_attributes=True,
            )
        except ValidationError as exc:
            log_attempt(
                operation=operation,
                attempt=1,
                status="invalid_usage",
                error=str(exc),
            )
            raise UsageUnavailable(f"model usage is missing or invalid: {exc}") from exc
        pricing = pricing or TokenPricing(
            input_usd_per_million=settings.sync_llm_input_usd_per_million,
            output_usd_per_million=settings.sync_llm_output_usd_per_million,
        )
        log_attempt(operation=operation, attempt=1, status="succeeded")
        await ledger.record_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            pricing=pricing,
        )
    else:
        log_attempt(operation=operation, attempt=1, status="succeeded")
    return response


@asynccontextmanager
async def tracked_run(
    *,
    trip_id: UUID,
    kind: str,
    max_steps: int | None = None,
    max_token_cost_usd: Decimal | None = None,
    recorder: PostgresRunRecorder | None = None,
) -> AsyncIterator[RunLedger]:
    """Create a durable run row and bind accounting to the current task."""
    recorder = recorder or PostgresRunRecorder()
    tracer = trace.get_tracer("syncinerary.harness")
    with tracer.start_as_current_span(f"harness.{kind}") as span:
        span.set_attribute("trip_id", str(trip_id))
        span.set_attribute("run.kind", kind)
        run = await recorder.start(trip_id=trip_id, kind=kind)
        span.set_attribute("run_id", str(run.id))
        ledger = RunLedger(
            run_id=run.id,
            recorder=recorder,
            budget=RunBudget(
                max_steps=max_steps if max_steps is not None else settings.sync_max_steps,
                max_token_cost_usd=(
                    max_token_cost_usd
                    if max_token_cost_usd is not None
                    else settings.sync_max_tokens_usd
                ),
            ),
            detector=LoopDetector(
                window_size=NO_PROGRESS_WINDOW,
                repeat_threshold=LOOP_HASH_REPEAT_THRESHOLD,
                tool_repeat_threshold=TOOL_ARG_CYCLE_THRESHOLD,
            ),
        )
        token = _current_run.set(ledger)
        try:
            yield ledger
        except BudgetExceeded:
            await ledger._persist(status="budget_exceeded")
            raise
        except NoProgress:
            await ledger._persist(status="no_progress")
            raise
        except ToolCycle:
            await ledger._persist(status="tool_cycle")
            raise
        except Exception:
            await ledger._persist(status="failed")
            raise
        else:
            await ledger._persist(status="ok")
        finally:
            _current_run.reset(token)


__all__ = [
    "LLMBase64ImageSource",
    "LLMContentBlock",
    "LLMImageBlock",
    "LLMJSONSchemaFormat",
    "LLMMessage",
    "LLMOutputConfig",
    "LLMRequest",
    "LLMTextBlock",
    "LLMUsage",
    "MessagesClient",
    "PostgresRunRecorder",
    "UsageUnavailable",
    "before_call",
    "call_llm",
    "log_attempt",
    "make_messages_client",
    "tracked_run",
]
