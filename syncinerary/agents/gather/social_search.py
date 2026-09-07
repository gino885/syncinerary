"""The adaptive social search loop: state, outcome reading, and the planner.

Discovery used to compose nine queries up front and run all of them, which
meant it could not notice that one interest was already covered, another had
nothing, a platform was returning no usable posts, or that the last three
searches had found the same places. This module holds the state that makes
those things visible and the deterministic rules that pick the next search
from them.

Two boundaries matter here. The planner decides WHAT is missing and
build_discovery_query decides HOW to ask for it, so query wording never
becomes a decision surface. And no model plans: CLAUDE.md section 2 keeps
feasibility and final decisions in deterministic code, and a per-iteration LLM
planner would add a call, latency, and non-determinism to a set of rules that
are legible without one. plan_next_search is the seam where a model could
later be tried against real traces.

Nothing here calls a provider. agents/gather/social.py owns the loop body.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from syncinerary.config.gather import (
    COLD_START_MAX_SEARCHES,
    LOW_YIELD_NEW_PLACES,
    MAX_ATTEMPTS_PER_SEMANTIC_INTENT,
    MAX_CONSECUTIVE_DUPLICATE_HEAVY,
    MAX_CONSECUTIVE_LOW_YIELD,
    MAX_CONSECUTIVE_PROVIDER_ERRORS,
    MAX_SEARCHES_PER_CITY,
    PLATFORM_PROBE_MIN,
    lane_slots,
)
from syncinerary.domain.models import SocialPlatform
from syncinerary.tools.fetch.social import (
    FOR_YOU_INTENTS,
    OPENING_SEQUENCE,
    TRENDING_INTENTS,
    QuerySpecificity,
    SearchIntent,
    SearchIntentType,
    interest_search_term,
    interest_slug,
)

if TYPE_CHECKING:  # pragma: no cover - annotation only, avoids a cycle
    from syncinerary.agents.gather.social import MinedPlace

DISCOVERY_PLATFORMS = (
    SocialPlatform.INSTAGRAM,
    SocialPlatform.TIKTOK,
    SocialPlatform.REDNOTE,
)

# An interest with this many places behind it is covered well enough that
# preference fit stops being the scarce thing. Reported for the trace and used
# to rank For You; it never gates a search, because interests do not steer
# search in this design.
INTEREST_COVERAGE_TARGET = 3

# Intents whose posts tend to name a specific venue. A search that returned
# plenty of posts and no place names is answered by moving here, not by
# rewording the same question.
VENUE_BEARING_INTENTS = (SearchIntentType.FOOD, SearchIntentType.HIDDEN_GEMS)

IntentKey = tuple[str, str]

_INTENT_VALUES = {intent_type.value for intent_type in SearchIntentType}


class SearchYield(StrEnum):
    """Where a search stopped being useful.

    Collapsing all of these into "found no new places" is what made the old
    behaviour impossible to debug: a query the index had nothing for, a set of
    posts that named no venue, and a page of places already in the pool need
    three different responses.
    """

    PRODUCTIVE = "productive"
    DUPLICATE_HEAVY = "duplicate_heavy"
    NO_SEARCH_RESULTS = "no_search_results"
    NO_MENTIONS = "no_mentions"
    RESOLUTION_FAILURE = "resolution_failure"
    PROVIDER_ERROR = "provider_error"


class StopReason(StrEnum):
    TARGET_REACHED = "target_reached"
    SEARCH_BUDGET_REACHED = "search_budget_reached"
    LOW_YIELD = "low_yield"
    NO_SEARCH_ACTIONS_LEFT = "no_search_actions_left"
    # Not a statement about the search space, unlike the four above.
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True)
class SearchOutcome:
    """What happened at each stage of one search.

    The counts narrow from left to right, so the first one that is zero says
    which stage failed.
    """

    raw_results_count: int = 0
    readable_posts_count: int = 0
    extracted_mentions_count: int = 0
    resolved_places_count: int = 0
    new_unique_places_count: int = 0
    # Set when the provider itself failed. A timeout or a 503 is not evidence
    # that the search space is empty, so it is kept apart from a clean zero.
    provider_error: str | None = None

    @property
    def yield_type(self) -> SearchYield:
        if self.provider_error is not None:
            return SearchYield.PROVIDER_ERROR
        if self.raw_results_count == 0:
            return SearchYield.NO_SEARCH_RESULTS
        if self.extracted_mentions_count == 0:
            return SearchYield.NO_MENTIONS
        if self.resolved_places_count == 0:
            return SearchYield.RESOLUTION_FAILURE
        if self.new_unique_places_count == 0:
            return SearchYield.DUPLICATE_HEAVY
        return SearchYield.PRODUCTIVE

    @property
    def novelty_rate(self) -> float:
        if not self.resolved_places_count:
            return 0.0
        return self.new_unique_places_count / self.resolved_places_count


@dataclass(frozen=True)
class SearchAction:
    """One executed search: what it asked, how it was worded, what came back."""

    intent: SearchIntent
    query: str
    outcome: SearchOutcome


@dataclass
class SearchStats:
    """One counter set, kept per platform, per intent, and per pair.

    The pair matters on its own: a platform can be strong for food and useless
    for hidden gems, and a planner that only knows the platform average will
    keep spending on the combination that does not work.
    """

    searches: int = 0
    raw_results: int = 0
    extracted_mentions: int = 0
    resolved_places: int = 0
    new_unique_places: int = 0
    duplicate_places: int = 0

    @property
    def yield_per_search(self) -> float:
        return self.new_unique_places / max(self.searches, 1)

    @property
    def duplicate_rate(self) -> float:
        if not self.resolved_places:
            return 0.0
        return self.duplicate_places / self.resolved_places

    def record(self, outcome: SearchOutcome) -> None:
        self.searches += 1
        self.raw_results += outcome.raw_results_count
        self.extracted_mentions += outcome.extracted_mentions_count
        self.resolved_places += outcome.resolved_places_count
        self.new_unique_places += outcome.new_unique_places_count
        self.duplicate_places += max(
            0, outcome.resolved_places_count - outcome.new_unique_places_count
        )


# The old name, kept because platform-level stats are still a thing the
# planner reads.
PlatformSearchStats = SearchStats


@dataclass
class SocialSearchState:
    """Everything the planner is allowed to reason about for one city."""

    destination: str
    destination_local_name: str | None = None
    interests: list[str] = field(default_factory=list)
    # What the downstream pool wants, not a promise. Section 55: stopping short
    # of it on a saturated search space is a correct outcome.
    target_candidates: int = 0
    max_searches: int = MAX_SEARCHES_PER_CITY
    platforms: tuple[SocialPlatform, ...] = DISCOVERY_PLATFORMS

    # The same dict agents/gather/social.py merges mentions into, keyed by
    # canonical name, so supply here is the deduplicated pool and not a URL
    # count.
    discovered_places: dict[str, MinedPlace] = field(default_factory=dict)
    searched_queries: list[SearchAction] = field(default_factory=list)
    attempts_by_intent: dict[IntentKey, int] = field(default_factory=dict)
    interest_coverage: dict[str, int] = field(default_factory=dict)
    platform_stats: dict[SocialPlatform, SearchStats] = field(default_factory=dict)
    intent_stats: dict[SearchIntentType, SearchStats] = field(default_factory=dict)
    # Keyed by the pair, because a platform good for food can be useless for
    # hidden gems and the average hides that.
    platform_intent_stats: dict[tuple[SocialPlatform, SearchIntentType], SearchStats] = (
        field(default_factory=dict)
    )

    last_search_new_places: int = 0
    recent_new_place_counts: list[int] = field(default_factory=list)
    consecutive_low_yield_searches: int = 0
    consecutive_zero_yield_searches: int = 0
    consecutive_duplicate_heavy_searches: int = 0
    consecutive_provider_errors: int = 0
    stop_reason: StopReason | None = None

    # Thresholds travel with the state so a run can be configured rather than
    # the module patched, which is how the tests vary them.
    low_yield_new_places: int = LOW_YIELD_NEW_PLACES
    max_consecutive_low_yield: int = MAX_CONSECUTIVE_LOW_YIELD
    max_consecutive_duplicate_heavy: int = MAX_CONSECUTIVE_DUPLICATE_HEAVY
    max_consecutive_provider_errors: int = MAX_CONSECUTIVE_PROVIDER_ERRORS
    max_attempts_per_intent: int = MAX_ATTEMPTS_PER_SEMANTIC_INTENT
    cold_start_max_searches: int = COLD_START_MAX_SEARCHES
    platform_probe_min: int = PLATFORM_PROBE_MIN
    interest_coverage_target: int = INTEREST_COVERAGE_TARGET

    def __post_init__(self) -> None:
        for platform in self.platforms:
            self.platform_stats.setdefault(platform, SearchStats())
            for intent_type in SearchIntentType:
                self.platform_intent_stats.setdefault(
                    (platform, intent_type), SearchStats()
                )
        for intent_type in SearchIntentType:
            self.intent_stats.setdefault(intent_type, SearchStats())
        for interest in self.interests:
            self.interest_coverage.setdefault(interest, 0)

    @property
    def lane_targets(self) -> tuple[int, int]:
        """(trending, for_you) candidates this city is aiming for."""
        return lane_slots(self.target_candidates)

    @property
    def lane_supply(self) -> tuple[int, int]:
        """(trending, for_you) unique candidates, by how they were found.

        Supply, not allocation: a place both a broad and a hidden-gem search
        named counts for both lanes here, because it is genuine evidence for
        both. Which lane finally shows it is decided later, in
        select_social_candidates.
        """
        trending = for_you = 0
        for place in self.discovered_places.values():
            found_by = {
                SearchIntentType(value)
                for value in getattr(place, "intent_types", ())
                if value in _INTENT_VALUES
            }
            if found_by & set(TRENDING_INTENTS):
                trending += 1
            if found_by & set(FOR_YOU_INTENTS):
                for_you += 1
        return trending, for_you

    @property
    def searches_used(self) -> int:
        return len(self.searched_queries)

    @property
    def discovered_count(self) -> int:
        return len(self.discovered_places)

    def attempts_for(self, intent: SearchIntent) -> int:
        return self.attempts_by_intent.get(intent.key, 0)

    def has_run(self, intent: SearchIntent) -> bool:
        """True when this exact wording of this question has already run."""
        return any(
            action.intent.key == intent.key
            and action.intent.specificity is intent.specificity
            for action in self.searched_queries
        )

    def stop(self, reason: StopReason) -> None:
        self.stop_reason = reason


def initialize_social_search_state(
    *,
    destination: str,
    destination_local_name: str | None = None,
    interests: Sequence[str] = (),
    target_candidates: int = 0,
    max_searches: int = MAX_SEARCHES_PER_CITY,
    platforms: Sequence[SocialPlatform] = DISCOVERY_PLATFORMS,
    **thresholds: int,
) -> SocialSearchState:
    return SocialSearchState(
        destination=destination,
        destination_local_name=destination_local_name,
        interests=list(interests),
        target_candidates=target_candidates,
        max_searches=max_searches,
        platforms=tuple(platforms),
        **thresholds,
    )


def interests_in_text(text: str, interests: Sequence[str]) -> list[str]:
    """Interests the post's own words support, by their search vocabulary.

    A deterministic backstop for the interest tags the extractor reports: the
    coverage signal has to keep working when a batch comes back without them.
    """
    haystack = text.casefold()
    if not haystack:
        return []
    matched: list[str] = []
    for interest in interests:
        words = {
            word
            for term in (
                interest_search_term(interest),
                interest_slug(interest).replace("_", " "),
            )
            for word in term.casefold().split()
            if len(word) > 2
        }
        if any(word in haystack for word in words):
            matched.append(interest)
    return matched


def normalize_matched_interests(
    reported: Iterable[str],
    interests: Sequence[str],
) -> list[str]:
    """Keep only interests the group actually listed, in their own wording."""
    by_slug = {interest_slug(interest): interest for interest in interests}
    kept: list[str] = []
    for value in reported:
        interest = by_slug.get(interest_slug(value))
        if interest is not None and interest not in kept:
            kept.append(interest)
    return kept


def update_search_state(
    state: SocialSearchState,
    *,
    intent: SearchIntent,
    query: str,
    outcome: SearchOutcome,
    interest_hits: Mapping[str, int] | None = None,
) -> SocialSearchState:
    """Fold one search's result into the state the next decision reads."""
    state.attempts_by_intent[intent.key] = state.attempts_for(intent) + 1
    state.searched_queries.append(
        SearchAction(intent=intent, query=query, outcome=outcome)
    )

    for stats in (
        state.platform_stats.setdefault(intent.platform, SearchStats()),
        state.intent_stats.setdefault(intent.intent_type, SearchStats()),
        state.platform_intent_stats.setdefault(
            (intent.platform, intent.intent_type), SearchStats()
        ),
    ):
        stats.record(outcome)

    state.last_search_new_places = outcome.new_unique_places_count
    state.recent_new_place_counts.append(outcome.new_unique_places_count)

    for interest, count in (interest_hits or {}).items():
        state.interest_coverage[interest] = (
            state.interest_coverage.get(interest, 0) + count
        )

    if outcome.yield_type is SearchYield.PROVIDER_ERROR:
        # Section 38: the request failed, so it says nothing about the search
        # space and must not advance any exhaustion counter.
        state.consecutive_provider_errors += 1
        return state

    state.consecutive_provider_errors = 0
    if outcome.new_unique_places_count <= state.low_yield_new_places:
        state.consecutive_low_yield_searches += 1
    else:
        state.consecutive_low_yield_searches = 0
    if outcome.new_unique_places_count == 0:
        state.consecutive_zero_yield_searches += 1
    else:
        state.consecutive_zero_yield_searches = 0
    if outcome.yield_type is SearchYield.DUPLICATE_HEAVY:
        state.consecutive_duplicate_heavy_searches += 1
    else:
        state.consecutive_duplicate_heavy_searches = 0
    return state


def available_platforms(state: SocialSearchState) -> list[SocialPlatform]:
    """Platforms this city can actually be searched on.

    RedNote drops out without a Mandarin destination name rather than falling
    back to the English one, which would search a different corpus.
    """
    return [
        platform
        for platform in state.platforms
        if platform is not SocialPlatform.REDNOTE or state.destination_local_name
    ]


def is_buildable(state: SocialSearchState, intent: SearchIntent) -> bool:
    """Whether a query exists for this intent without inventing language."""
    if intent.platform is not SocialPlatform.REDNOTE:
        return True
    return bool(state.destination_local_name)


def is_available(state: SocialSearchState, intent: SearchIntent) -> bool:
    """Whether the planner may still spend a search on this intent."""
    return (
        is_buildable(state, intent)
        and not state.has_run(intent)
        and state.attempts_for(intent) < state.max_attempts_per_intent
    )


def rank_undercovered_interests(state: SocialSearchState) -> list[str]:
    """Least-covered interests first.

    Reported in the trace and used to rank For You. It does not choose a
    search: interests steer ranking in this design, not discovery, which is
    what keeps provider cost flat as a group lists more of them.
    """
    return sorted(
        state.interests,
        key=lambda interest: (
            state.interest_coverage.get(interest, 0),
            state.interests.index(interest),
        ),
    )


def platform_priority(
    state: SocialSearchState,
    platform: SocialPlatform,
    intent_type: SearchIntentType | None = None,
) -> tuple[int, int, float, int]:
    """Least-spent first, with proven duds pushed to the back.

    Spreading the early budget across platforms is what tells the run which of
    them are indexed for this city, and one platform's silence says nothing
    about another's. When an intent is given the judgement is made on that
    pair's own record, because a platform strong for food can be useless for
    hidden gems.
    """
    if intent_type is None:
        stats = state.platform_stats.get(platform, SearchStats())
    else:
        stats = state.platform_intent_stats.get((platform, intent_type), SearchStats())
    unproductive = int(
        stats.searches >= state.platform_probe_min and stats.new_unique_places == 0
    )
    base_index = (
        state.platforms.index(platform)
        if platform in state.platforms
        else len(state.platforms)
    )
    return (unproductive, stats.searches, -stats.yield_per_search, base_index)


def platforms_by_priority(
    state: SocialSearchState,
    candidates: Sequence[SocialPlatform] | None = None,
    intent_type: SearchIntentType | None = None,
) -> list[SocialPlatform]:
    pool = list(candidates) if candidates is not None else available_platforms(state)
    return sorted(
        pool, key=lambda platform: platform_priority(state, platform, intent_type)
    )


def _first_available(
    state: SocialSearchState,
    intent_type: SearchIntentType,
    *,
    by_pair: bool = True,
) -> SearchIntent | None:
    """The best unused platform for this intent.

    by_pair ranks on that platform's record for this intent specifically,
    which is what the adaptive phase wants. The opening ranks on overall
    spend instead, so the three opening searches land on three different
    platforms and the first adaptive decision has evidence about each.
    """
    order = platforms_by_priority(
        state, intent_type=intent_type if by_pair else None
    )
    for platform in order:
        intent = SearchIntent(platform=platform, intent_type=intent_type)
        if is_available(state, intent):
            return intent
    return None


def _opening_intent(state: SocialSearchState) -> SearchIntent | None:
    """PLACES, then FOOD, then HIDDEN_GEMS, before anything adapts.

    All three sources are established first so the first adaptive decision is
    made with evidence about both lanes. Reacting after one search would mean
    deciding that For You is short before ever having asked for a hidden gem.
    """
    for intent_type in OPENING_SEQUENCE:
        if state.intent_stats[intent_type].searches:
            continue
        intent = _first_available(state, intent_type, by_pair=False)
        if intent is not None:
            return intent
    return None


def _cold_start_intent(state: SocialSearchState) -> SearchIntent | None:
    """Nothing found anywhere yet: simplify the question, do not narrow it.

    Specializing on an empty state asks a harder question than the one that
    already failed, so the recovery is fewer words and another platform. The
    rounds are bounded by cold_start_max_searches, because a city that answers
    no opening query on any platform will not answer six more inventive ones.
    """
    for platform in platforms_by_priority(state):
        for intent_type in OPENING_SEQUENCE:
            for specificity in (QuerySpecificity.NORMAL, QuerySpecificity.BROAD):
                intent = SearchIntent(
                    platform=platform,
                    intent_type=intent_type,
                    specificity=specificity,
                )
                if is_available(state, intent):
                    return intent
    return None


def _last_informative_action(state: SocialSearchState) -> SearchAction | None:
    for action in reversed(state.searched_queries):
        if action.outcome.provider_error is None:
            return action
    return None


def _recovery_intent(state: SocialSearchState) -> SearchIntent | None:
    """React to how the previous search failed, not merely that it did.

    A query the index had nothing for is usually over-specified, so the same
    question is asked with fewer words. Posts that named no venue are a
    different problem and rewording will not fix it: the intent moves to
    content that tends to carry venue names.
    """
    action = _last_informative_action(state)
    if action is None:
        return None
    kind = action.outcome.yield_type

    if kind is SearchYield.NO_MENTIONS:
        for intent_type in VENUE_BEARING_INTENTS:
            intent = SearchIntent(
                platform=action.intent.platform, intent_type=intent_type
            )
            if is_available(state, intent):
                return intent

    if kind in {SearchYield.NO_SEARCH_RESULTS, SearchYield.NO_MENTIONS}:
        wider = action.intent.broadened()
        if wider is not None and is_available(state, wider):
            return wider
    return None


def lane_deficits(state: SocialSearchState) -> list[tuple[float, str, tuple[SearchIntentType, ...]]]:
    """Each lane's shortfall as a fraction of its target, worst first.

    A fraction rather than a count, so the smaller For You target is not
    permanently outranked by Trending simply for being smaller.
    """
    trending_target, for_you_target = state.lane_targets
    trending_supply, for_you_supply = state.lane_supply
    lanes = [
        (
            _deficit(for_you_supply, for_you_target),
            "for_you",
            FOR_YOU_INTENTS,
        ),
        (
            _deficit(trending_supply, trending_target),
            "trending",
            TRENDING_INTENTS,
        ),
    ]
    lanes.sort(key=lambda lane: -lane[0])
    return lanes


def _deficit(supply: int, target: int) -> float:
    if target <= 0:
        return 0.0
    return max(0.0, (target - supply) / target)


def _lane_gap_intent(state: SocialSearchState) -> SearchIntent | None:
    """Search whichever lane is furthest from what it needs.

    This is the whole adaptive step. Trending and For You have different
    sources, so "which lane is short" answers "what should be searched next"
    directly, without a taxonomy of angles in between.
    """
    for deficit, _lane, intent_types in lane_deficits(state):
        if deficit <= 0:
            continue
        # Within a lane, the intent that has produced least so far.
        ordered = sorted(
            intent_types,
            key=lambda intent_type: (
                state.intent_stats[intent_type].new_unique_places,
                state.intent_stats[intent_type].searches,
                OPENING_SEQUENCE.index(intent_type),
            ),
        )
        for intent_type in ordered:
            intent = _first_available(state, intent_type)
            if intent is not None:
                return intent
    return None


def _any_remaining_intent(state: SocialSearchState) -> SearchIntent | None:
    """Both lanes are at target but budget remains: keep the weakest topped up."""
    for intent_type in sorted(
        OPENING_SEQUENCE,
        key=lambda value: state.intent_stats[value].new_unique_places,
    ):
        intent = _first_available(state, intent_type)
        if intent is not None:
            return intent
    return None


def plan_next_search(state: SocialSearchState) -> SearchIntent | None:
    """The one next search most likely to add candidates, or None to stop.

    Deterministic and side-effect free apart from recording why it stopped.
    """
    if state.searches_used >= state.max_searches:
        state.stop(StopReason.SEARCH_BUDGET_REACHED)
        return None
    if state.target_candidates and all(
        deficit <= 0 for deficit, _lane, _types in lane_deficits(state)
    ):
        state.stop(StopReason.TARGET_REACHED)
        return None
    if state.consecutive_provider_errors >= state.max_consecutive_provider_errors:
        state.stop(StopReason.PROVIDER_UNAVAILABLE)
        return None

    # The opening sequence sits above the exhaustion checks on purpose. Two
    # empty searches at the start are evidence about two queries, and a lane
    # nothing has ever been asked for cannot be called exhausted.
    opening = _opening_intent(state)
    if opening is not None:
        return opening

    if (
        not state.discovered_places
        and state.searches_used < state.cold_start_max_searches
    ):
        cold = _cold_start_intent(state)
        if cold is not None:
            return cold
        state.stop(StopReason.NO_SEARCH_ACTIONS_LEFT)
        return None

    if state.consecutive_low_yield_searches >= state.max_consecutive_low_yield:
        state.stop(StopReason.LOW_YIELD)
        return None
    if (
        state.consecutive_duplicate_heavy_searches
        >= state.max_consecutive_duplicate_heavy
    ):
        state.stop(StopReason.LOW_YIELD)
        return None

    recovery = _recovery_intent(state)
    if recovery is not None:
        return recovery

    gap = _lane_gap_intent(state)
    if gap is not None:
        return gap

    remaining = _any_remaining_intent(state)
    if remaining is not None:
        return remaining

    state.stop(StopReason.NO_SEARCH_ACTIONS_LEFT)
    return None


__all__ = [
    "DISCOVERY_PLATFORMS",
    "FOR_YOU_INTENTS",
    "INTEREST_COVERAGE_TARGET",
    "OPENING_SEQUENCE",
    "TRENDING_INTENTS",
    "VENUE_BEARING_INTENTS",
    "IntentKey",
    "PlatformSearchStats",
    "QuerySpecificity",
    "SearchAction",
    "SearchIntent",
    "SearchIntentType",
    "SearchOutcome",
    "SearchStats",
    "SearchYield",
    "SocialSearchState",
    "StopReason",
    "available_platforms",
    "initialize_social_search_state",
    "interests_in_text",
    "is_available",
    "is_buildable",
    "lane_deficits",
    "normalize_matched_interests",
    "plan_next_search",
    "platform_priority",
    "platforms_by_priority",
    "rank_undercovered_interests",
    "update_search_state",
]
