"""Gather stage.

M1 ships one source: a hand-written fixture (fixture.py). M3 adds
backbone.py, buzz.py, personal.py, dedup.py and enrich.py per CLAUDE.md §8.
"""
from syncinerary.agents.gather.fixture import (
    FixtureNotFound,
    gather_node,
    load_candidates,
)

__all__ = ["FixtureNotFound", "gather_node", "load_candidates"]
