"""Deliberate breakage, for proving the harness detects a regression.

CLAUDE.md section 12.3 asks for evidence that a bad change shows up as a
measurable regression. Claiming a suite would catch a bug is not evidence;
running it against a broken build is. These are the breakages, named so a
report can say which one was applied and which check caught it.

Nothing here is reachable from the application. A sabotage is passed
explicitly into an eval run through `--break`, never read from the
environment, and CI never sets it.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class Sabotage:
    """One named way to make the planner worse."""

    name: str
    description: str
    #: Raise the daily fatigue budget so days can overload.
    fatigue_budget: int | None = None
    #: Stop filtering food that violates a hard dietary exclusion.
    skips_dietary_filter: bool = False
    #: Ignore must-go pins.
    drops_must_go: bool = False

    @contextmanager
    def applied(self) -> Iterator[None]:
        """Patch the breakage in, then put everything back.

        The flag-shaped breakages are read where they are used; this handles
        the one that has to reach into a module constant. Keeping it here
        rather than in the runner means `--break` and a test calling a case
        directly behave identically, which is the only way the "a bad change
        turns the run red" claim can be tested at all.
        """
        from syncinerary.agents.solver import stage1_days

        original = stage1_days.DAILY_FATIGUE_BUDGET
        if self.fatigue_budget is not None:
            stage1_days.DAILY_FATIGUE_BUDGET = self.fatigue_budget
        try:
            yield
        finally:
            stage1_days.DAILY_FATIGUE_BUDGET = original


SABOTAGES: dict[str, Sabotage] = {
    "fatigue-cap": Sabotage(
        name="fatigue-cap",
        description="Raise the daily fatigue budget from 8 to 99, so days overload",
        fatigue_budget=99,
    ),
    "dietary-filter": Sabotage(
        name="dietary-filter",
        description="Stop removing food that violates a hard dietary exclusion",
        skips_dietary_filter=True,
    ),
    "must-go": Sabotage(
        name="must-go",
        description="Ignore the group's must-go pins",
        drops_must_go=True,
    ),
}


def get(name: str) -> Sabotage:
    if name not in SABOTAGES:
        known = ", ".join(sorted(SABOTAGES))
        raise KeyError(f"Unknown sabotage {name!r}. Known: {known}")
    return SABOTAGES[name]


__all__ = ["SABOTAGES", "Sabotage", "get"]
