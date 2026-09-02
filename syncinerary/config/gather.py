"""Gather defaults. See CLAUDE.md §16. Override here, not inline in code."""

import math

# Automatic social share. The app aims for a social-majority deck, then fills
# any evidence shortfall from the Google Places foundation. Personal links are
# additive and never displaced.
BUZZ_RATIO = 0.60

# Pool size: days * POOL_PER_DAY. Acceptable range: 5 to 8.
# At the top of that range so the shortlist can fill complete days.
POOL_PER_DAY = 8

# One strong post may introduce a place. Search rank and any explicitly
# published post engagement determine priority; Google Places remains the
# reality and city-boundary check before the place reaches the deck.
BUZZ_MIN_SOURCE_COUNT = 1

# Two-lane selection, see SOCIAL_TWO_LANE_PLAN.md. Budgets derive from the pool
# the trip actually needs rather than from a flat per-city cap: the pool is the
# same size whether the trip visits one city or four, so reserving a fixed
# quota per city sized the spend to the wrong thing.
#
# Discovery keeps every place a listicle names, so recall stays high and the
# discrimination happens here instead.
MINED_NAMES_MAX = 100
SOCIAL_VERIFY_BUDGET_MAX = 40
# Share of mined names that resolve to a real place inside the city. Selection
# over-selects by the inverse so geocoding losses do not starve the deck.
VERIFY_YIELD = 0.75
TRENDING_LANE_RATIO = 0.70
# Ordinal floor on the 0..3 interest scale: at least a clear match. An ordinal
# needs no calibration, unlike a cosine threshold.
MIN_INTEREST_FIT = 2


def social_target(*, days: int) -> int:
    """Social cards the pool wants, before geocoding losses."""
    return math.ceil(days * POOL_PER_DAY * BUZZ_RATIO)


def social_verify_budget(*, days: int) -> int:
    """Google Places reality checks to spend on social names for one trip."""
    return min(
        SOCIAL_VERIFY_BUDGET_MAX,
        math.ceil(social_target(days=days) / VERIFY_YIELD),
    )


def lane_slots(budget: int) -> tuple[int, int]:
    """Split a verification budget into (trending, for_you) slots."""
    trending = math.ceil(budget * TRENDING_LANE_RATIO)
    return trending, budget - trending


def gather_max_steps(*, default_max_steps: int, days: int) -> int:
    """Reserve one bounded Google reality check per verification slot."""
    return default_max_steps + social_verify_budget(days=days)

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
