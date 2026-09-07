"""Run the adaptive social search against the real providers, and narrate it.

The loop decides its next query from what the last one found, so a failing run
is only debuggable if you can see each decision next to the evidence it was
made from. This prints, per iteration: what the planner chose and why, the
exact provider query, what came back at each stage, and how the state moved.

    python -m scripts.debug_social_search Sapporo --interests ramen,coffee,onsen

Nothing here is imported by the application. It makes real Brave, Anthropic,
and (with --verify) Google Places calls, so it costs money. Repeating a run
mostly replays the Redis cache; --max-searches keeps a first run cheap and
--no-cache forces fresh provider results.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from syncinerary.agents.gather import social as social_module
from syncinerary.agents.gather import social_read as social_read_module
from syncinerary.agents.gather.social_search import (
    SearchYield,
    lane_deficits,
)
from syncinerary.config import settings
from syncinerary.config.gather import (
    MAX_SEARCHES_PER_CITY,
    gather_max_steps,
    social_verify_budget,
)
from syncinerary.domain.models import AgentRun, Trip
from syncinerary.harness.wrapper import tracked_run
from syncinerary.store.redis import dispose_redis, get_redis
from syncinerary.tools.fetch.social import OPENING_SEQUENCE, SearchIntentType

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

YIELD_COLOR = {
    SearchYield.PRODUCTIVE: GREEN,
    SearchYield.DUPLICATE_HEAVY: YELLOW,
    SearchYield.NO_SEARCH_RESULTS: RED,
    SearchYield.NO_MENTIONS: RED,
    SearchYield.RESOLUTION_FAILURE: RED,
    SearchYield.PROVIDER_ERROR: RED,
}


def _c(text: str, colour: str, *, enabled: bool) -> str:
    return f"{colour}{text}{RESET}" if enabled else text


@dataclass
class MemoryRecorder:
    """Stands in for the Postgres run recorder.

    Budget accounting and loop detection are what the harness contributes to a
    real run, and both live in the ledger rather than the database, so this
    keeps them without needing a trip row to exist.
    """

    runs: dict[UUID, AgentRun] = field(default_factory=dict)

    async def start(self, *, trip_id: UUID, kind: str) -> AgentRun:
        run = AgentRun(trip_id=trip_id, kind=kind, status="running")
        self.runs[run.id] = run
        return run

    async def progress(
        self,
        run_id: UUID,
        *,
        status: str | None = None,
        step_count: int,
        token_cost: Decimal,
    ) -> None:
        run = self.runs[run_id]
        run.step_count = step_count
        run.token_cost = token_cost
        if status is not None:
            run.status = status


class Narrator:
    """Wraps the loop's own seams and prints what passes through them."""

    def __init__(self, *, colour: bool, show_posts: int) -> None:
        self.colour = colour
        self.show_posts = show_posts
        self.iteration = 0
        self.llm_calls = 0
        self.tool_calls = 0
        self._search_started = 0.0

    def out(self, text: str = "") -> None:
        print(text, flush=True)

    def paint(self, text: str, colour: str) -> str:
        return _c(text, colour, enabled=self.colour)

    # -- the planner's decision ------------------------------------------
    def wrap_planner(self, plan_next_search):
        def planned(state):
            intent = plan_next_search(state)
            self.iteration += 1
            if intent is None:
                return None
            self.out()
            self.out(
                self.paint(
                    f"── search {state.searches_used + 1}/{state.max_searches} "
                    + "─" * 46,
                    BOLD,
                )
            )
            self.out(
                f"  PLAN     {intent.platform.value} / "
                f"{intent.intent_type.value}   -> {intent.lane}   "
                f"({intent.specificity.value})"
            )
            self.out(f"  WHY      {self._why(state, intent)}")
            for line in self._supply_lines(state):
                self.out(line)
            return intent

        return planned

    def _why(self, state, intent) -> str:
        if state.intent_stats[intent.intent_type].searches == 0 and (
            state.searches_used < len(OPENING_SEQUENCE)
        ):
            return (
                f"opening sequence: {intent.intent_type.value} has not been asked "
                "yet, and both lanes need a source before anything adapts"
            )
        last = state.searched_queries[-1] if state.searched_queries else None
        if last is not None and last.intent.key == intent.key:
            return (
                f"last attempt returned {last.outcome.yield_type.value}; "
                "asking the same thing with fewer words"
            )
        if last is not None and last.outcome.yield_type is SearchYield.NO_MENTIONS:
            return "last search found posts that named no venue, moving to venue-bearing content"

        trending_supply, for_you_supply = state.lane_supply
        trending_target, for_you_target = state.lane_targets
        worst = lane_deficits(state)[0]
        if worst[0] > 0 and intent.intent_type in worst[2]:
            if worst[1] == "for_you":
                return (
                    f"For You has {for_you_supply} of {for_you_target} hidden-gem "
                    f"candidates; Trending has {trending_supply} of {trending_target}"
                )
            weakest = min(
                worst[2], key=lambda kind: state.intent_stats[kind].new_unique_places
            )
            return (
                f"Trending has {trending_supply} of {trending_target}, and "
                f"{weakest.value} has produced the least of its two sources"
            )
        return "both lanes are near target; topping up the weakest source"

    def _supply_lines(self, state) -> list[str]:
        trending_supply, for_you_supply = state.lane_supply
        trending_target, for_you_target = state.lane_targets
        places = state.intent_stats[SearchIntentType.PLACES]
        food = state.intent_stats[SearchIntentType.FOOD]
        gems = state.intent_stats[SearchIntentType.HIDDEN_GEMS]
        coverage = (
            " ".join(f"{name}={count}" for name, count in state.interest_coverage.items())
            or "no interests listed"
        )
        trending_line = (
            f"  TRENDING {trending_supply}/{trending_target}   "
            f"places_unique={places.new_unique_places} "
            f"places_mentions={places.extracted_mentions}   "
            f"food_unique={food.new_unique_places} "
            f"food_mentions={food.extracted_mentions}"
        )
        for_you_line = (
            f"  FOR YOU  {for_you_supply}/{for_you_target}   "
            f"hidden_gem_unique={gems.new_unique_places} "
            f"hidden_gem_mentions={gems.extracted_mentions}   "
            f"fit[{coverage}]"
        )
        platform_line = (
            f"  PLATFORM {self._platform_line(state)}  "
            f"low_yield_streak={state.consecutive_low_yield_searches}"
        )
        return [trending_line, for_you_line, platform_line]

    def _platform_line(self, state) -> str:
        return " ".join(
            f"{platform.value}={stats.new_unique_places}/{stats.searches}"
            for platform, stats in state.platform_stats.items()
        )

    # -- the provider search ---------------------------------------------
    def wrap_search(self, search):
        async def searched(platform, *, query, destination):
            self.out(f"  QUERY    {self.paint(query, BLUE)}")
            self._search_started = time.perf_counter()
            try:
                posts = await search(platform, query=query, destination=destination)
            except Exception as exc:
                elapsed = time.perf_counter() - self._search_started
                self.out(
                    "  SEARCH   "
                    + self.paint(f"{type(exc).__name__}: {exc}", RED)
                    + f"  ({elapsed:.1f}s)"
                )
                raise
            elapsed = time.perf_counter() - self._search_started
            self.out(f"  SEARCH   {len(posts)} posts  ({elapsed:.1f}s)")
            for post in posts[: self.show_posts]:
                engagement = ""
                if post.like_count is not None or post.comment_count is not None:
                    engagement = f"  [{post.like_count or 0} likes, {post.comment_count or 0} comments]"
                self.out(
                    f"             {DIM if self.colour else ''}"
                    f"{post.reference.canonical_url}{engagement}"
                    f"{RESET if self.colour else ''}"
                )
                snippet = " ".join(post.evidence_text.split())[:140]
                if snippet:
                    self.out(f"               {snippet}")
            if len(posts) > self.show_posts:
                self.out(f"             ... {len(posts) - self.show_posts} more")
            return posts

        return searched

    # -- extraction --------------------------------------------------------
    def wrap_extract(self, extract):
        async def extracted(posts, **kwargs):
            started = time.perf_counter()
            mentions = await extract(posts, **kwargs)
            elapsed = time.perf_counter() - started
            self.out(
                f"  EXTRACT  {len(mentions.mentions)} mentions from "
                f"{len(posts)} posts  ({elapsed:.1f}s)"
            )
            for mention in mentions.mentions[: self.show_posts]:
                name = mention.canonical_name or mention.name
                matched = ",".join(mention.matched_interests) or "-"
                highlight = (mention.highlight or "")[:70]
                self.out(
                    f"             {name}  fit={mention.interest_fit} "
                    f"matched=[{matched}]  {highlight}"
                )
            if len(mentions.mentions) > self.show_posts:
                self.out(f"             ... {len(mentions.mentions) - self.show_posts} more")
            return mentions

        return extracted

    # -- merge into the pool ----------------------------------------------
    def wrap_merge(self, merge_mentions):
        def merged(mined, mentions, posts, platform, **kwargs):
            before = len(mined)
            result = merge_mentions(mined, mentions, posts, platform, **kwargs)
            self.out(
                f"  MERGE    resolved={result.resolved} new={result.new_places} "
                f"rejected={result.rejected}  pool {before} -> {len(mined)}"
            )
            if result.new_place_keys:
                names = ", ".join(mined[key].name for key in result.new_place_keys)
                self.out(f"             + {names}")
            return result

        return merged

    # -- raw call accounting ------------------------------------------------
    def wrap_run_tool(self, run_tool):
        async def counted(tool, arguments, **kwargs):
            self.tool_calls += 1
            return await run_tool(tool, arguments, **kwargs)

        return counted

    def wrap_call_llm(self, call_llm):
        async def counted(request, **kwargs):
            self.llm_calls += 1
            return await call_llm(request, **kwargs)

        return counted


def build_trip(city: str, *, days: int, country: str | None) -> Trip:
    start = datetime.now(tz=UTC).date() + timedelta(days=30)
    return Trip(
        destination=city,
        cities=[city],
        country=country,
        start_date=start,
        end_date=start + timedelta(days=days - 1),
        days=days,
    )


def install(narrator: Narrator, *, no_cache: bool) -> None:
    social_module.plan_next_search = narrator.wrap_planner(social_module.plan_next_search)
    social_module._search_platform = narrator.wrap_search(social_module._search_platform)
    social_module.extract_post_places = narrator.wrap_extract(
        social_module.extract_post_places
    )
    social_module.merge_mentions = narrator.wrap_merge(social_module.merge_mentions)
    social_module.run_tool = narrator.wrap_run_tool(social_module.run_tool)
    social_module.call_llm = narrator.wrap_call_llm(social_module.call_llm)
    social_read_module.run_tool = narrator.wrap_run_tool(social_read_module.run_tool)
    social_read_module.call_llm = narrator.wrap_call_llm(social_read_module.call_llm)

    if no_cache:
        # The tool factories default to the pooled Redis client, so the only
        # way past the cache is to hand them an explicit None.
        from syncinerary.tools.fetch import social as fetch_social

        original_search = fetch_social.make_brave_social_search_tool
        original_read = fetch_social.make_tiktok_post_read_tool

        def uncached_search(**kwargs):
            import httpx

            kwargs.setdefault("client", httpx.AsyncClient(timeout=20))
            return original_search(**{**kwargs, "cache": None})

        social_module.make_brave_social_search_tool = uncached_search
        social_read_module.make_tiktok_post_read_tool = lambda **kwargs: original_read(
            **{**kwargs, "cache": None}
        )


async def flush_cache() -> int:
    redis = get_redis()
    removed = 0
    async for key in redis.scan_iter(match="social:brave:*"):
        await redis.delete(key)
        removed += 1
    return removed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city", help="a single city, e.g. Sapporo")
    parser.add_argument("--country", default=None)
    parser.add_argument("--interests", default="", help="comma separated")
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument(
        "--max-searches",
        type=int,
        default=MAX_SEARCHES_PER_CITY,
        help="lower this to keep a debugging run cheap",
    )
    parser.add_argument("--target", type=int, default=None, help="override the supply target")
    parser.add_argument("--no-cache", action="store_true", help="ignore cached Brave results")
    parser.add_argument("--flush-cache", action="store_true", help="delete cached Brave results first")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="also run selection and the Google Places reality check",
    )
    parser.add_argument("--posts", type=int, default=3, help="posts and mentions to print per search")
    parser.add_argument("--no-colour", action="store_true")
    parser.add_argument("--phoenix", action="store_true", help="also export spans to Phoenix")
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("BRAVE_SEARCH_API_KEY", settings.brave_search_api_key),
            ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        )
        if not value
    ]
    if missing:
        print(f"missing required env: {', '.join(missing)}", file=sys.stderr)
        return 2

    if args.phoenix:
        from syncinerary.obs.tracing import init_tracing

        init_tracing()

    if args.flush_cache:
        print(f"flushed {await flush_cache()} cached Brave responses")

    interests = [item.strip() for item in args.interests.split(",") if item.strip()]
    narrator = Narrator(colour=not args.no_colour, show_posts=args.posts)
    install(narrator, no_cache=args.no_cache)

    trip = build_trip(args.city, days=args.days, country=args.country)
    budget = social_verify_budget(days=args.days)
    target = args.target if args.target is not None else budget

    print(f"{BOLD if not args.no_colour else ''}city{RESET if not args.no_colour else ''}      {args.city}")
    print(f"interests {interests or '(none)'}")
    print(f"target    {target} social candidates   ceiling {args.max_searches} searches")
    print(f"budget    {gather_max_steps(default_max_steps=settings.sync_max_steps, days=args.days)} harness steps")

    recorder = MemoryRecorder()
    started = time.perf_counter()
    state = None
    try:
        async with tracked_run(
            trip_id=trip.id,
            kind="debug_social_search",
            max_steps=gather_max_steps(
                default_max_steps=settings.sync_max_steps, days=args.days
            ),
            recorder=recorder,
        ) as ledger:
            local_name = await social_module.translate_destination_to_mandarin(args.city)
            print(f"mandarin  {local_name}")
            state = await social_module.mine_city(
                destination=args.city,
                destination_local_name=local_name,
                interests=interests,
                target_candidates=target,
                max_searches=args.max_searches,
            )

            print()
            print(_c("── stop " + "─" * 52, BOLD, enabled=not args.no_colour))
            print(f"  reason        {state.stop_reason.value}")
            print(f"  searches      {state.searches_used}/{args.max_searches}")
            print(f"  unique places {state.discovered_count} (target {target})")
            print(
                f"  trending      {state.lane_supply[0]} of {state.lane_targets[0]} "
                "(from places + food)"
            )
            print(
                f"  for you       {state.lane_supply[1]} of {state.lane_targets[1]} "
                "(from hidden gems)"
            )
            print(f"  preference    {state.interest_coverage}")
            for intent_type, stats in state.intent_stats.items():
                print(
                    f"    {intent_type.value:<12} searches={stats.searches} "
                    f"mentions={stats.extracted_mentions} "
                    f"unique={stats.new_unique_places} "
                    f"dup_rate={stats.duplicate_rate:.2f}"
                )
            print()
            for index, action in enumerate(state.searched_queries, start=1):
                colour = YIELD_COLOR.get(action.outcome.yield_type, "")
                label = _c(
                    f"{action.outcome.yield_type.value:<18}",
                    colour,
                    enabled=not args.no_colour,
                )
                print(
                    f"  {index}. {action.intent.platform.value:<9} "
                    f"{action.intent.intent_type.value:<12} "
                    f"{action.intent.lane:<9} {label} "
                    f"raw={action.outcome.raw_results_count:<3} "
                    f"mentions={action.outcome.extracted_mentions_count:<3} "
                    f"new={action.outcome.new_unique_places_count}"
                )

            if args.verify:
                print()
                print(_c("── verification " + "─" * 44, BOLD, enabled=not args.no_colour))
                kept = social_module.score_places(state.discovered_places)
                selected = social_module.select_social_candidates(kept, budget=budget)
                print(f"  eligible {len(kept)}  selected {len(selected)}")
                cities = await social_module.resolve_trip_cities(trip)
                candidates = await social_module.discover_social_candidates(
                    trip, [], cities
                )
                for candidate in candidates:
                    lane = candidate.trending_signals.get("selection_lane")
                    found_by = ",".join(
                        candidate.trending_signals.get("discovery_intents", [])
                    )
                    print(
                        f"  {candidate.name_canonical}  [{lane}]  "
                        f"found_by={found_by}  {candidate.type.value}"
                    )

            print()
            print(f"  harness steps {ledger.budget.step_count}")
            print(f"  model cost    ${ledger.budget.token_cost_usd:.4f}")
            print(f"  tool calls    {narrator.tool_calls}   llm calls {narrator.llm_calls}")
            print(f"  wall clock    {time.perf_counter() - started:.1f}s")
    except Exception as exc:
        print()
        print(_c(f"RUN FAILED  {type(exc).__name__}: {exc}", RED, enabled=not args.no_colour))
        raise
    finally:
        with contextlib.suppress(Exception):
            await dispose_redis()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
