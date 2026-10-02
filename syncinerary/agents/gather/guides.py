"""Bounded RedNote guide baseline from permitted search-index text.

A guide's title is not a place. Every mention retained here must be present
in the cited post's available text; unavailable full note bodies are never
fetched or treated as if they had been read.
"""

from __future__ import annotations

import unicodedata

from opentelemetry import trace

from syncinerary.agents.gather.admission import admit_place, name_rejection
from syncinerary.agents.gather.progress import report_progress
from syncinerary.agents.gather.social import (
    SocialPlaceMentions,
    _search_platform,
    extract_post_places,
    merge_mentions,
    to_candidate,
)
from syncinerary.domain.city_plan import city_day_counts
from syncinerary.domain.models import CandidatePlace, SocialPlatform, Source, Trip
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import DiscoveredSocialURL
from syncinerary.tools.places import (
    PlaceSearchBias,
    PlaceSearchInput,
    ResolvedCity,
    make_place_search_tool,
)

MAX_GUIDES = 3


def guide_query(cities: list[str], days: int) -> str:
    if not cities or days < 1:
        raise ValueError("Guide search requires cities and an inclusive day count")
    return f"{' '.join(cities)} {days}天{days - 1}夜攻略"


def grounded_mentions(
    mentions: SocialPlaceMentions, posts: list[DiscoveredSocialURL], destination: str
) -> SocialPlaceMentions:
    accepted = []
    for mention in mentions.mentions:
        if not 1 <= mention.post_index <= len(posts) or name_rejection(mention.name, destination):
            continue
        text = unicodedata.normalize("NFKC", posts[mention.post_index - 1].evidence_text)
        name = unicodedata.normalize("NFKC", mention.name).strip()
        offset = text.casefold().find(name.casefold())
        if not name or offset < 0:
            continue
        # Bound the retained evidence around the literal name, rather than
        # trusting a model-written explanation as source evidence.
        excerpt = text[max(0, offset - 25) : offset + len(name) + 60]
        accepted.append(mention.model_copy(update={"highlight": excerpt[:120]}))
    return SocialPlaceMentions(mentions=accepted)


def coverage(candidates: list[CandidatePlace], city: str) -> set[str]:
    categories = set()
    for candidate in candidates:
        if candidate.enrichment.get("city") != city:
            continue
        kind = candidate.category or ""
        if candidate.trending_signals.get("selection_lane") == "for_you":
            categories.add("low_key")
        if kind in {"bar", "pub", "wine_bar", "night_club", "performing_arts_theater"}:
            categories.add("evening")
        if kind in {"market", "shopping_mall", "plaza", "historical_place"}:
            categories.add("walking_area")
        if kind in {"cafe", "coffee_shop", "bakery"}:
            categories.add("cafe")
        elif candidate.type.value == "food":
            categories.add("food")
        elif kind in {
            "park",
            "city_park",
            "state_park",
            "national_park",
            "beach",
            "garden",
            "hiking_area",
            "natural_feature",
        }:
            categories.add("nature")
        else:
            categories.add("core")
    return categories


async def discover_guide_baseline(
    trip: Trip, cities: list[ResolvedCity], local_names: list[str], budget: int
) -> tuple[list[CandidatePlace], int]:
    day_counts = city_day_counts(trip)
    # Keep most verification slots for the adaptive lanes, including hidden gems.
    remaining = min(budget, max(3, trip.days * 2))
    initial_budget = remaining
    pool: dict[str, CandidatePlace] = {}
    seen_names: set[tuple[str, str]] = set()

    async def search(query: str, scoped_cities: list[ResolvedCity]):
        nonlocal remaining
        await report_progress("guide_baseline", " / ".join(c.name for c in scoped_cities))
        posts = (
            await _search_platform(
                SocialPlatform.REDNOTE, query=query, destination=trip.destination,
                output_locale=trip.output_locale,
            )
        )[:MAX_GUIDES]
        mentions = await extract_post_places(
            posts,
            platform=SocialPlatform.REDNOTE,
            destination=" / ".join(c.name for c in scoped_cities),
            query=query,
        )
        mentions = grounded_mentions(mentions, posts, trip.destination)
        mined = {}
        merge_mentions(mined, mentions, posts, SocialPlatform.REDNOTE)
        for name in mined.values():
            for city in scoped_cities:
                key = (name.name.casefold(), city.name)
                if key in seen_names or remaining <= 0:
                    continue
                seen_names.add(key)
                remaining -= 1
                result = await run_tool(
                    make_place_search_tool(),
                    PlaceSearchInput(
                        query=name.name,
                        destination=city.name,
                        city_center=PlaceSearchBias(lat=city.lat, lng=city.lng),
                        city_radius_km=city.radius_km,
                    ),
                )
                if not result.matches:
                    continue
                place = result.matches[0]
                decision = admit_place(
                    place, destination=city.name, city=city, social_evidence=True
                )
                if not decision.accepted:
                    continue
                candidate = to_candidate(place, name, trip, city=city)
                sources = [
                    Source(
                        type="buzz",
                        subtype="rednote_guide",
                        via="rednote_search",
                        url=post.url,
                        query=next(
                            (p.query for p in posts if p.reference.canonical_url == post.url), query
                        ),
                        guide_rank=post.rank,
                        mention_text=post.highlight,
                    )
                    for post in name.posts
                ]
                candidate = candidate.model_copy(
                    update={
                        "sources": sources,
                        "enrichment": {
                            **candidate.enrichment,
                            "guide_coverage": sorted(coverage([candidate], city.name)),
                        },
                        "trending_signals": {**candidate.trending_signals, "guide_baseline": True},
                    }
                )
                existing = pool.get(place.place_id)
                if existing:
                    sources = list(existing.sources)
                    sources.extend(s for s in candidate.sources if s not in sources)
                    candidate = existing.model_copy(update={"sources": sources})
                pool[place.place_id] = candidate
                break

    await search(guide_query(local_names, trip.days), cities)
    for city, local_name, days in zip(cities, local_names, day_counts, strict=True):
        categories = coverage(list(pool.values()), city.name)
        count = sum(c.enrichment.get("city") == city.name for c in pool.values())
        if remaining > 0 and (count < days * 2 or not {"core", "food"} <= categories):
            query = guide_query([local_name], days)
            # Single-city primary is already exactly this query.
            if query != guide_query(local_names, trip.days):
                await search(query, [city])
        categories = coverage(list(pool.values()), city.name)
        trace.get_current_span().set_attribute(
            f"gather.guide.{city.name}.coverage", sorted(categories)
        )
    # Independent corroboration leads the baseline, followed by category breadth.
    ranked = sorted(
        pool.values(),
        key=lambda c: (-len({s.url for s in c.sources}), c.category or "", c.name_canonical),
    )
    return ranked, initial_budget - remaining
