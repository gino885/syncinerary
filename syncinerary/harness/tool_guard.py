"""Typed tool validation and bounded argument repair."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from syncinerary.config.harness import REPAIR_ATTEMPT_CAP


class ToolCallUnrecoverable(RuntimeError):
    """Tool arguments or output stayed invalid through the repair cap."""


class ToolRepairer(Protocol):
    async def repair(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        validation_error: str,
        attempt: int,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[Any]]


async def run_tool(
    tool: ToolDefinition,
    arguments: BaseModel | Mapping[str, Any],
    *,
    repairer: ToolRepairer | None = None,
    state: Any = None,
) -> BaseModel:
    """Validate, execute, and validate a tool within the repair cap.

    The cap counts the initial validation as attempt one, so the configured
    value of two permits one model repair, matching CLAUDE.md section 12.1.
    """
    from syncinerary.harness.wrapper import before_call, log_attempt

    original = (
        arguments.model_dump(mode="json")
        if isinstance(arguments, BaseModel)
        else dict(arguments)
    )
    candidate = original
    last_error: ValidationError | None = None

    for attempt in range(1, REPAIR_ATTEMPT_CAP + 1):
        try:
            validated = tool.input_model.model_validate(candidate)
        except ValidationError as exc:
            last_error = exc
            log_attempt(
                operation=f"tool:{tool.name}",
                attempt=attempt,
                status="invalid_input",
                error=str(exc),
            )
            if attempt == REPAIR_ATTEMPT_CAP or repairer is None:
                break
            candidate = dict(
                await repairer.repair(
                    tool_name=tool.name,
                    arguments=original,
                    validation_error=str(exc),
                    attempt=attempt,
                )
            )
            continue

        await before_call(
            operation=f"tool:{tool.name}",
            arguments=validated.model_dump(mode="json"),
            state=state,
            tool_name=tool.name,
        )
        log_attempt(
            operation=f"tool:{tool.name}",
            attempt=attempt,
            status="executing",
        )
        try:
            raw_result = await tool.handler(validated)
        except Exception as exc:
            log_attempt(
                operation=f"tool:{tool.name}",
                attempt=attempt,
                status="failed",
                error=type(exc).__name__,
            )
            raise

        try:
            result = tool.output_model.model_validate(raw_result)
        except ValidationError as exc:
            log_attempt(
                operation=f"tool:{tool.name}",
                attempt=attempt,
                status="invalid_output",
                error=str(exc),
            )
            raise ToolCallUnrecoverable(
                f"tool {tool.name!r} returned invalid output: {exc}"
            ) from exc
        log_attempt(
            operation=f"tool:{tool.name}",
            attempt=attempt,
            status="succeeded",
        )
        return result

    assert last_error is not None
    raise ToolCallUnrecoverable(
        f"tool {tool.name!r} arguments stayed invalid after "
        f"{REPAIR_ATTEMPT_CAP} attempts: {last_error}"
    ) from last_error


__all__ = [
    "ToolCallUnrecoverable",
    "ToolDefinition",
    "ToolRepairer",
    "run_tool",
]
