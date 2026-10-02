"""Opt-in live Reel discovery evaluation, without creating or changing trips.

    .venv/bin/python -m scripts.evaluate_reels --mode search
    .venv/bin/python -m scripts.evaluate_reels --mode deck --cities Tokyo --locales zh-Hant

Both modes use configured providers and may incur cost. Deck mode additionally
uses Anthropic and Google, under the normal harness budgets. Each result is
written immediately so a later provider failure does not erase earlier evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.debug_social_search import MemoryRecorder
from syncinerary.agents.gather.cities import resolve_trip_cities
from syncinerary.agents.gather.live import discover_candidates
from syncinerary.agents.gather.source_mix import has_reel, source_mix_report
from syncinerary.config import settings
from syncinerary.config.gather import gather_max_steps
from syncinerary.config.locales import normalize_output_locale
from syncinerary.domain.city_plan import city_day_counts
from syncinerary.domain.models import SocialPlatform, Trip
from syncinerary.harness import run_tool, tracked_run
from syncinerary.store.redis import dispose_redis
from syncinerary.tools.fetch.social import (
    BraveSocialSearchInput,
    SearchIntent,
    SearchIntentType,
    build_discovery_query,
    make_brave_social_search_tool,
)


async def evaluate(args) -> list[dict]:
    reports = []

    def save(row):
        reports.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")

    try:
        for city in args.cities:
            for locale in args.locales:
                started = time.perf_counter()
                if args.mode == "search":
                    from syncinerary.agents.gather.social import translate_destination_to_mandarin
                    local_name = await translate_destination_to_mandarin(city) if locale.startswith("zh") else city
                    for kind in ("web", "videos"):
                        query = build_discovery_query(
                            SearchIntent(
                                platform=SocialPlatform.INSTAGRAM, intent_type=SearchIntentType.FOOD
                            ),
                            destination=city,
                            destination_localized=local_name,
                            output_locale=locale,
                        )
                        result = await run_tool(
                            make_brave_social_search_tool(),
                            BraveSocialSearchInput(
                                platform=SocialPlatform.INSTAGRAM,
                                query=query,
                                search_kind=kind,
                                search_lang=normalize_output_locale(locale).lower(),
                            ),
                        )
                        save(
                            {
                                "city": city,
                                "locale": locale,
                                "surface": kind,
                                "query": query,
                                "posts": len(result.results),
                                "readable_characters": sum(
                                    len(p.evidence_text) for p in result.results
                                ),
                            }
                        )
                    continue
                names = city.split(",")
                if args.days < len(names):
                    raise ValueError("At least one day per city is required")
                start = datetime.now(UTC).date() + timedelta(days=14)
                trip = Trip(
                    destination=city,
                    cities=names,
                    country=args.country,
                    days=args.days,
                    city_days=[int(n) for n in args.city_days.split(",")] if args.city_days else [],
                    start_date=start,
                    end_date=start + timedelta(days=args.days - 1),
                    output_locale=locale,
                )
                async with tracked_run(
                    trip_id=trip.id,
                    kind="evaluate_reels",
                    recorder=MemoryRecorder(),
                    max_steps=gather_max_steps(
                        default_max_steps=settings.sync_max_steps, days=args.days, cities=len(names)
                    ),
                ) as ledger:
                    cities = await resolve_trip_cities(trip)
                    trip = trip.model_copy(
                        update={"resolved_cities": [c.model_dump(mode="json") for c in cities]}
                    )
                    cards = await discover_candidates(trip, [])
                    report = source_mix_report(cards)
                    save(
                        {
                            "city": city,
                            "locale": locale,
                            "days": args.days,
                            "city_days": city_day_counts(trip),
                            "run_at": datetime.now(UTC).isoformat(),
                            "source_mix": report.model_dump(),
                            "elapsed_seconds": round(time.perf_counter() - started, 2),
                            "harness_steps": ledger.budget.step_count,
                            "model_cost_usd": str(ledger.budget.token_cost_usd),
                            "embed_playback_tested": False,
                            "cards": [
                                {
                                    "name": c.name_canonical,
                                    "type": c.type.value,
                                    "city": c.enrichment.get("city"),
                                    "reel": has_reel(c),
                                    "lane": c.trending_signals.get("selection_lane"),
                                    "posts": c.enrichment.get("social_post_urls", []),
                                }
                                for c in cards
                            ],
                        }
                    )
    finally:
        await dispose_redis()
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["search", "deck"], default="search")
    parser.add_argument(
        "--cities",
        nargs="+",
        default=["Tokyo", "Sapporo", "Atami"],
        help="Use comma-separated names within one argument for a multi-city trip",
    )
    parser.add_argument("--locales", nargs="+", default=["en", "zh-Hant"])
    parser.add_argument("--country", default="Japan")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--city-days", help="Reviewed days per city, for example 3,1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    reports = asyncio.run(evaluate(args))
    return int(
        any(
            not row["source_mix"]["visible"]["target_met"]
            for row in reports
            if "source_mix" in row
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
