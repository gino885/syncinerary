"""Deterministic loop and repeated-tool-call detection."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

from pydantic import BaseModel


class NoProgress(RuntimeError):
    """The relevant state slice repeated without progress."""


class ToolCycle(RuntimeError):
    """The same tool received equivalent arguments too many times."""


def _canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


class LoopDetector:
    def __init__(
        self,
        *,
        window_size: int,
        repeat_threshold: int,
        tool_repeat_threshold: int | None = None,
    ) -> None:
        if tool_repeat_threshold is None:
            tool_repeat_threshold = repeat_threshold
        if min(window_size, repeat_threshold, tool_repeat_threshold) < 1:
            raise ValueError("loop detector thresholds must be positive")
        if window_size < max(repeat_threshold, tool_repeat_threshold):
            raise ValueError("window_size must cover both repeat thresholds")
        self.window_size = window_size
        self.repeat_threshold = repeat_threshold
        self.tool_repeat_threshold = tool_repeat_threshold
        self._state_hashes: deque[str] = deque(maxlen=window_size)
        self._tool_hashes: deque[str] = deque(maxlen=window_size)

    def observe_state(self, state: Any) -> None:
        fingerprint = _canonical(state)
        self._state_hashes.append(fingerprint)
        repeats = self._state_hashes.count(fingerprint)
        if repeats >= self.repeat_threshold:
            raise NoProgress(
                f"state repeated {repeats} times within the last "
                f"{self.window_size} steps"
            )

    def observe_tool(self, tool_name: str, arguments: Any) -> None:
        fingerprint = _canonical({"tool": tool_name, "arguments": arguments})
        self._tool_hashes.append(fingerprint)
        repeats = self._tool_hashes.count(fingerprint)
        if repeats >= self.tool_repeat_threshold:
            raise ToolCycle(
                f"tool {tool_name!r} repeated equivalent arguments "
                f"{repeats} times"
            )


__all__ = ["LoopDetector", "NoProgress", "ToolCycle"]
