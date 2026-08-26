"""M2 typed tool validation and repair tests."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from syncinerary.harness import wrapper as wrapper_module
from syncinerary.harness.tool_guard import (
    ToolCallUnrecoverable,
    ToolDefinition,
    run_tool,
)


class DoubleInput(BaseModel):
    value: int = Field(gt=0)


class DoubleOutput(BaseModel):
    value: int


class StubRepairer:
    def __init__(self) -> None:
        self.errors: list[str] = []

    async def repair(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        validation_error: str,
        attempt: int,
    ) -> dict[str, Any]:
        assert tool_name == "double"
        assert arguments == {"value": 0}
        assert attempt == 1
        self.errors.append(validation_error)
        return {"value": 4}


async def test_invalid_tool_arguments_are_repaired_once_and_then_succeed():
    repairer = StubRepairer()
    calls: list[DoubleInput] = []

    async def double(value: DoubleInput) -> DoubleOutput:
        calls.append(value)
        return DoubleOutput(value=value.value * 2)

    result = await run_tool(
        ToolDefinition(
            name="double",
            input_model=DoubleInput,
            output_model=DoubleOutput,
            handler=double,
        ),
        {"value": 0},
        repairer=repairer,
    )

    assert result == DoubleOutput(value=8)
    assert calls == [DoubleInput(value=4)]
    assert len(repairer.errors) == 1


async def test_invalid_tool_arguments_stop_at_the_repair_cap():
    class BrokenRepairer:
        async def repair(self, **_kwargs: Any) -> dict[str, Any]:
            return {"value": -1}

    async def double(value: DoubleInput) -> DoubleOutput:
        return DoubleOutput(value=value.value * 2)

    with pytest.raises(ToolCallUnrecoverable, match="after 2 attempts"):
        await run_tool(
            ToolDefinition(
                name="double",
                input_model=DoubleInput,
                output_model=DoubleOutput,
                handler=double,
            ),
            {"value": 0},
            repairer=BrokenRepairer(),
        )


async def test_tool_internal_validation_error_is_not_treated_as_bad_arguments():
    class CountingRepairer:
        def __init__(self) -> None:
            self.calls = 0

        async def repair(self, **_kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return {"value": 2}

    repairer = CountingRepairer()

    async def broken_tool(_value: DoubleInput) -> DoubleOutput:
        return DoubleOutput.model_validate({"value": "not-an-integer"})

    with pytest.raises(ValidationError):
        await run_tool(
            ToolDefinition(
                name="broken",
                input_model=DoubleInput,
                output_model=DoubleOutput,
                handler=broken_tool,
            ),
            {"value": 1},
            repairer=repairer,
        )

    assert repairer.calls == 0


async def test_tool_validation_and_execution_attempts_are_added_to_the_span(
    monkeypatch,
):
    class FakeSpan:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        def add_event(self, name: str, attributes: dict[str, Any]) -> None:
            self.events.append((name, attributes))

    span = FakeSpan()
    monkeypatch.setattr(wrapper_module.trace, "get_current_span", lambda: span)

    async def double(value: DoubleInput) -> DoubleOutput:
        return DoubleOutput(value=value.value * 2)

    await run_tool(
        ToolDefinition(
            name="double",
            input_model=DoubleInput,
            output_model=DoubleOutput,
            handler=double,
        ),
        {"value": 0},
        repairer=StubRepairer(),
    )

    attempts = [attributes for name, attributes in span.events if name == "harness.attempt"]
    assert [attempt["status"] for attempt in attempts] == [
        "invalid_input",
        "executing",
        "succeeded",
    ]
    assert all(attempt["operation"] == "tool:double" for attempt in attempts)
