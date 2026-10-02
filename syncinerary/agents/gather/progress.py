"""Optional job progress sink, inherited by graph tasks through contextvars."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar

progress_sink: ContextVar[Callable[[str, str | None], Awaitable[None]] | None] = ContextVar(
    "gather_progress_sink",
    default=None,
)


async def report_progress(phase: str, city: str | None = None) -> None:
    sink = progress_sink.get()
    if sink is not None:
        await sink(phase, city)
