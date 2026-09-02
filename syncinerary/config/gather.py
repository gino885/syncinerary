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

# Social post reading (SOCIAL_SOURCES_PLAN.md section 5). TikTok is the only
# platform whose official embed API returns a caption and a cover frame, so
# these bound how much of that is read per city. Instagram and RedNote stay
# at the search-index snippet; nothing here changes that.
SOCIAL_POST_READ_MAX_POSTS = 20
SOCIAL_COVER_OCR_ENABLED = True
SOCIAL_COVER_OCR_MAX_IMAGES = 12
SOCIAL_COVER_MAX_BYTES = 1_500_000
SOCIAL_POST_READ_CACHE_TTL_SECONDS = 86_400
SOCIAL_COVER_TEXT_CACHE_TTL_SECONDS = 7 * 86_400
