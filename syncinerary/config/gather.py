"""Gather defaults. See CLAUDE.md §16. Override here, not inline in code."""

# Automatic social share. The remaining pool is the Google Places foundation.
# Personal attachments are additive and never displaced.
BUZZ_RATIO = 0.40

# Pool size: days * POOL_PER_DAY. Acceptable range: 5 to 8.
# At the top of that range so the shortlist can fill complete days.
POOL_PER_DAY = 8

# Buzz
BUZZ_MIN_SOURCE_COUNT = 3

# Personal
PROFILE_DRIVEN_CAP_PER_TRAVELER = 2

# Dedup
GEO_CLUSTER_RADIUS_M = 50
EMBEDDING_SIMILARITY_THRESHOLD = 0.90
