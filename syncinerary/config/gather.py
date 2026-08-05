"""Gather defaults. See CLAUDE.md §16. Override here, not inline in code."""

# Source mix (must sum to 1.0)
BACKBONE_RATIO = 0.40
BUZZ_RATIO = 0.40
PERSONAL_RATIO = 0.20

# Pool size: days * POOL_PER_DAY. Acceptable range: 5 to 8.
POOL_PER_DAY = 7

# Backbone mining
BACKBONE_FREQ_THRESHOLD = 0.30
BACKBONE_ARTICLES_MIN = 10
BACKBONE_ARTICLES_MAX = 20

# Buzz
BUZZ_MIN_SOURCE_COUNT = 3

# Personal
PROFILE_DRIVEN_CAP_PER_TRAVELER = 2

# Dedup
GEO_CLUSTER_RADIUS_M = 50
EMBEDDING_SIMILARITY_THRESHOLD = 0.90
