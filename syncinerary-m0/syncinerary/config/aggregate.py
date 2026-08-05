"""Aggregate + shortlist defaults. See CLAUDE.md §16."""

DISLIKE_WEIGHT = 1.5
MUST_HAVE_WEIGHT = 0.3

SLOTS_PER_DAY = 6           # shortlist target_size = days * SLOTS_PER_DAY
MUST_GO_CAP_PER_DAY = 1     # so total must-go cap = days

SHORTLIST_CONFIRM_QUORUM = 0.50
