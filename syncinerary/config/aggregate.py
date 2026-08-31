"""Aggregate + shortlist defaults. See CLAUDE.md §16."""

DISLIKE_WEIGHT = 1.5
MUST_HAVE_WEIGHT = 0.3

# Raised from the CLAUDE.md section 16 default of 6. Six slots a day could not
# hold three to five sights alongside lunch and dinner, so the shortlist was
# arriving at the solver already too small to build a full day from.
SLOTS_PER_DAY = 7           # shortlist target_size = days * SLOTS_PER_DAY
MUST_GO_CAP_PER_DAY = 1     # so total must-go cap = days

SHORTLIST_CONFIRM_QUORUM = 0.50
