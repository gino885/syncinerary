"""Explainer defaults.

Not in the CLAUDE.md §16 table, but kept here rather than inline for the same
reason: these are knobs, and knobs belong in config/.
"""

# The narrative is a few short paragraphs, so it does not need a large budget.
# Well under the ~16000 non-streaming ceiling where SDK HTTP timeouts start.
EXPLAIN_MAX_TOKENS = 2000

# low | medium | high | xhigh | max. The explainer receives an itinerary that
# is already decided (§2: it never decides anything), so it is describing, not
# reasoning. Low effort suits that and keeps the per-run cost down.
EXPLAIN_EFFORT = "low"
