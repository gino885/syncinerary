"""OpenTelemetry tracing, exporting to Phoenix via OTLP/gRPC.

M0 acceptance gate: a no-op LangGraph run produces a visible span in Phoenix
(UI on :6006). This is the trace -> eval -> fix loop's first link; F2 (see
CLAUDE.md §12) extends it with regression-tracked scorers later.

Observability model (see CLAUDE.md §14):
- LangGraph node executions and Anthropic SDK calls are AUTO-instrumented via
  OpenInference. You do not write manual spans for those; they show up in
  Phoenix automatically with prompt, response, model, token count, latency.
- Manual `tracer.start_as_current_span` is reserved for domain-level spans
  that add attributes not derivable from auto-instrumentation (e.g. a
  trip-scoped operation span with trip_id).
"""
from openinference.instrumentation.anthropic import AnthropicInstrumentor
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from syncinerary.config import settings

_initialized = False


def init_tracing() -> None:
    """Configure the global OTel provider and wire auto-instrumentation.

    Idempotent: safe to call from lifespan startup and from module-level code
    without producing duplicate exporters.
    """
    global _initialized
    if _initialized:
        return

    resource = Resource.create({"service.name": settings.phoenix_project_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.phoenix_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrumentation: LangGraph runs on LangChain internals, so the
    # LangChain instrumentor captures every node execution. Anthropic
    # instrumentor captures every LLM call regardless of caller (LangGraph
    # node, harness wrapper, or direct SDK use).
    LangChainInstrumentor().instrument()
    AnthropicInstrumentor().instrument()

    _initialized = True


def get_tracer() -> trace.Tracer:
    """Return the domain tracer. Only use for spans that add attributes
    beyond what auto-instrumentation already captures."""
    if not _initialized:
        init_tracing()
    return trace.get_tracer("syncinerary")
