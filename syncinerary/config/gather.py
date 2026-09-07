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
# Split between the two lanes. Trending draws on two search intents and For
# You on one, so the larger share follows the deeper supply rather than a
# judgement that popular places matter more.
TRENDING_LANE_RATIO = 0.70


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


# --- Adaptive social search (SOCIAL_ADAPTIVE_SEARCH_PLAN) --------------------
#
# Discovery searches one query at a time and decides the next one from what the
# previous ones found. MAX_SEARCHES_PER_CITY is a hard resource ceiling, not a
# target: an easy city should stop at three or four. It sits below the nine
# requests the old fixed plan spent unconditionally, so the adaptive loop
# cannot cost more than what it replaced. The opening three searches establish
# PLACES, FOOD and HIDDEN_GEMS; the remaining five go to whichever lane is
# short.
MAX_SEARCHES_PER_CITY = 8

# A search adding at most this many unique places is low yield.
LOW_YIELD_NEW_PLACES = 1
# Three rather than two, because a single empty search is usually a badly
# worded query rather than an empty search space, and the planner is allowed
# one broader retry plus a platform switch before giving up on a question.
MAX_CONSECUTIVE_LOW_YIELD = 3
# Places resolving but every one already known is different evidence: the
# angle is saturated, which is a stronger signal than a query that found
# nothing, so it stops the run sooner.
MAX_CONSECUTIVE_DUPLICATE_HEAVY = 2
# A dead provider is not an empty search space, so it never advances the
# exhaustion counters. It still ends the run rather than spending the ceiling.
MAX_CONSECUTIVE_PROVIDER_ERRORS = 3
# One question, at most one broader retry, then move the question elsewhere.
MAX_ATTEMPTS_PER_SEMANTIC_INTENT = 2
# Searches a platform gets before its zero yield is treated as evidence
# about the platform rather than about one query.
PLATFORM_PROBE_MIN = 2
# Searches allowed while nothing at all has been found. A city that answers
# no broad query on any platform gets a bounded round of simpler wordings and
# then stops, rather than spending the ceiling on ever more arbitrary variants.
COLD_START_MAX_SEARCHES = 6

# Harness steps one iteration can charge: the search, the batched TikTok post
# read, the cover-frame vision call, and the extraction.
SOCIAL_SEARCH_STEPS_PER_ITERATION = 4


def social_search_max_steps(*, cities: int) -> int:
    """Worst-case harness steps the adaptive loop can charge for a trip."""
    return max(1, cities) * MAX_SEARCHES_PER_CITY * SOCIAL_SEARCH_STEPS_PER_ITERATION


def gather_max_steps(*, default_max_steps: int, days: int, cities: int = 1) -> int:
    """Reserve the search ceiling and one Google reality check per slot.

    Verification tracks trip size because the pool is the same size whatever
    the city count. Mining tracks city count because a post about one city is
    not evidence about another, so each city runs its own search loop.
    """
    return (
        default_max_steps
        + social_verify_budget(days=days)
        + social_search_max_steps(cities=cities)
    )

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
