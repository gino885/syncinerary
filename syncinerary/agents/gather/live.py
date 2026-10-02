"""Live candidate discovery backed by Google Places search results."""
from __future__ import annotations

import logging
from typing import Any

from syncinerary.agents.gather.admission import admit_place, supported_candidate_type
from syncinerary.agents.gather.cities import (
    resolve_trip_cities,
    search_bias,
)
from syncinerary.agents.gather.dedup import dedup_candidates, merge_candidate_evidence
from syncinerary.agents.gather.dietary import (
    dietary_tags_from_place_types,
    filter_dietary_conflicts,
)
from syncinerary.agents.gather.localization import localize_candidates
from syncinerary.agents.gather.personal import discover_profile_candidates
from syncinerary.agents.gather.progress import report_progress
from syncinerary.agents.gather.social import (
    discover_social_candidates,
    merge_into_pool,
)
from syncinerary.agents.gather.source_mix import has_reel, record_source_mix
from syncinerary.agents.gather.traits import fatigue_cost, is_weather_dependent
from syncinerary.config.gather import BUZZ_RATIO, POOL_PER_DAY, lane_slots
from syncinerary.config.solver import (
    ATTRACTIONS_PER_DAY_MIN,
    FOOD_PER_DAY_TARGET,
    MEALS_PER_DAY_MIN,
    MIN_STOPS_PER_DAY,
    NEARBY_WALKING_KM,
)
from syncinerary.domain.city_plan import city_day_counts
from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Source,
    Traveler,
    Trip,
    TripState,
)
from syncinerary.harness import run_tool
from syncinerary.obs.tracing import get_tracer
from syncinerary.store.db import session_scope
from syncinerary.store.repositories import CandidatePlaceRepository
from syncinerary.tools.places import (
    PlaceMatch,
    PlaceSearchBias,
    PlaceSearchInput,
    ResolvedCity,
    make_place_search_tool,
)
from syncinerary.tools.transit import TransitLocation, haversine_km

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
logger = logging.getLogger(__name__)
# A discovery cluster must be dense under the same walking rule the router
# uses. A larger radius grouped stops that had neither a walking estimate nor
# a public-transit route, so the pool looked full while the itinerary was not.
_DENSE_CLUSTER_RADIUS_KM = NEARBY_WALKING_KM

_FOOD_TYPES = {
    "bakery",
    "bar",
    "cafe",
    "coffee_shop",
    "food_court",
    "ice_cream_shop",
    "market",
    "restaurant",
    "steak_house",
}
_LODGING_TYPES = {
    "bed_and_breakfast",
    "campground",
    "extended_stay_hotel",
    "guest_house",
    "hostel",
    "hotel",
    "lodging",
    "motel",
    "resort_hotel",
}
class LiveDiscoveryInsufficient(RuntimeError):
    """Live providers returned too few real places for a useful swipe pool."""


def build_search_queries(destination: str) -> list[str]:
    """Use several real search intents so the pool can fill complete days."""
    cleaned = destination.strip()
    if not cleaned:
        raise ValueError("destination cannot be empty")
    return [
        f"top tourist attractions in {cleaned}",
        f"museums and cultural attractions in {cleaned}",
        f"parks scenic spots and viewpoints in {cleaned}",
        f"local restaurants and food markets in {cleaned}",
        f"cafes and bakeries for breakfast in {cleaned}",
        f"dinner restaurants and izakaya in {cleaned}",
        f"shopping streets and walkable neighborhoods in {cleaned}",
        f"family activities and hidden gems in {cleaned}",
        f"well located hotels in {cleaned}",
    ]


# Meal intents searched around each day's centre, so every day has real
# options for each meal rather than one shared restaurant list for the region.
# Breakfast is left untyped on purpose: strict "restaurant" filtering drops the
# bakeries and coffee shops that actually serve it.
CLUSTER_FOOD_QUERIES: tuple[tuple[str, str | None], ...] = (
    ("restaurants near {anchor}", "restaurant"),
    ("breakfast cafes and bakeries near {anchor}", None),
)


def _candidate_type(place: PlaceMatch) -> CandidateType:
    kind = supported_candidate_type(place)
    if kind is None:
        raise ValueError(f"Unsupported place type: {place.primary_type}")
    return kind


def _duration_minutes(candidate_type: CandidateType, primary_type: str | None) -> int:
    if candidate_type is CandidateType.FOOD:
        return 75
    if primary_type in {"museum", "art_gallery", "amusement_park", "zoo"}:
        return 120
    if is_weather_dependent(primary_type, ()):
        return 90
    return 60


def _hours(place: PlaceMatch) -> dict[str, list[list[int]]]:
    if place.hours_by_weekday:
        return place.hours_by_weekday
    return {}


def _nearest_city(lat: float, lng: float, cities: list[ResolvedCity]) -> ResolvedCity:
    """Which of the trip's cities a day cluster sits in."""
    return min(
        cities,
        key=lambda city: haversine_km(
            TransitLocation(lat=lat, lng=lng),
            TransitLocation(lat=city.lat, lng=city.lng),
        ),
    )


def candidate_from_place(
    place: PlaceMatch,
    trip: Trip,
    query: str,
    *,
    city: ResolvedCity | None = None,
) -> CandidatePlace:
    candidate_type = _candidate_type(place)
    place_types = [*place.types]
    if place.primary_type:
        place_types.append(place.primary_type)
    return CandidatePlace(
        trip_id=trip.id,
        type=candidate_type,
        name_canonical=place.display_name,
        lat=place.lat,
        lng=place.lng,
        address=place.formatted_address,
        area=place.area,
        hours_by_weekday=_hours(place),
        price_tier=place.price_tier or 2,
        duration_estimate_min=_duration_minutes(candidate_type, place.primary_type),
        dietary_tags=dietary_tags_from_place_types(place_types),
        weather_dependent=is_weather_dependent(place.primary_type, place.types),
        fatigue_cost=fatigue_cost(candidate_type, place.primary_type, place.types),
        category=place.primary_type,
        sources=[
            Source(
                type="discovery",
                subtype="google_places",
                via="google_places_text_search",
            )
        ],
        enrichment={
            "admission": admit_place(place, destination=city.name if city else trip.destination,
                                     city=city).model_dump(mode="json"),
            "google_place_id": place.place_id,
            "discovery_provider": "google_places",
            "discovery_queries": [query],
            "city": city.name if city else None,
            "hours_assumed": not bool(place.hours_by_weekday),
            "source_description": place.editorial_summary,
        },
    )


def _distance_km(left: CandidatePlace, right: CandidatePlace) -> float:
    return haversine_km(
        TransitLocation(lat=left.lat, lng=left.lng),
        TransitLocation(lat=right.lat, lng=right.lng),
    )


def _dense_clusters(candidates: list[CandidatePlace]) -> list[list[CandidatePlace]]:
    ranked = list(candidates)
    remaining = list(candidates)
    clusters: list[list[CandidatePlace]] = []
    while remaining:
        seed = max(
            remaining,
            key=lambda candidate: (
                sum(
                    _distance_km(candidate, other) <= _DENSE_CLUSTER_RADIUS_KM
                    for other in remaining
                ),
                -ranked.index(candidate),
            ),
        )
        cluster = [
            candidate
            for candidate in remaining
            if _distance_km(seed, candidate) <= _DENSE_CLUSTER_RADIUS_KM
        ]
        clusters.append(cluster)
        clustered_ids = {candidate.id for candidate in cluster}
        remaining = [candidate for candidate in remaining if candidate.id not in clustered_ids]
    clusters.sort(key=lambda group: (-len(group), ranked.index(group[0])))
    return clusters


def select_dense_pool(
    candidates: list[CandidatePlace],
    *,
    days: int,
    limit: int,
) -> list[CandidatePlace]:
    """Prefer enough nearby options per day over isolated headline landmarks."""
    if days <= 0 or limit <= 0:
        return []
    clusters = _dense_clusters(candidates)
    dense = [cluster for cluster in clusters if len(cluster) >= MIN_STOPS_PER_DAY]
    chosen = (dense or clusters)[:days]

    # A city destination collapses to one cluster that has to serve every day,
    # so the food each cluster reserves scales with the days it covers. Fixing
    # it per cluster is what left a five day Sapporo trip with three
    # restaurants in a forty card deck.
    days_per_cluster = -(-days // len(chosen)) if chosen else 1
    active = [_mix_day_types(cluster, days=days_per_cluster) for cluster in chosen]

    selected: list[CandidatePlace] = []
    offset = 0
    while len(selected) < limit:
        added = False
        for cluster in active:
            if offset < len(cluster):
                selected.append(cluster[offset])
                added = True
                if len(selected) == limit:
                    return selected
        if not added:
            break
        offset += 1

    selected_ids = {candidate.id for candidate in selected}
    for candidate in candidates:
        if candidate.id not in selected_ids:
            selected.append(candidate)
            if len(selected) == limit:
                break
    return selected


def _mix_day_types(
    cluster: list[CandidatePlace],
    *,
    days: int = 1,
) -> list[CandidatePlace]:
    """Front-load enough meals and sights for the days this cluster covers.

    ``select_dense_pool`` takes candidates off the front of each cluster, so
    whatever the pool limit cuts is decided here. Reserving the meal slots up
    front is what stops a day arriving at the solver with sights but nothing
    to eat.
    """
    activities = [candidate for candidate in cluster if candidate.type is not CandidateType.FOOD]
    food = [candidate for candidate in cluster if candidate.type is CandidateType.FOOD]

    days = max(1, days)
    head_food = food[: FOOD_PER_DAY_TARGET * days]
    head_activities = activities[: max(0, POOL_PER_DAY * days - len(head_food))]

    # Two sights then a meal, repeated, so the front of the cluster already
    # looks like a day rather than a block of sights with food behind it.
    mixed: list[CandidatePlace] = []
    activity_offset = 0
    food_offset = 0
    while activity_offset < len(head_activities) or food_offset < len(head_food):
        mixed.extend(head_activities[activity_offset : activity_offset + 2])
        activity_offset += 2
        if food_offset < len(head_food):
            mixed.append(head_food[food_offset])
            food_offset += 1

    mixed.extend(activities[len(head_activities) :])
    mixed.extend(food[len(head_food) :])
    return mixed


def limit_social_pool(candidates: list[CandidatePlace], limit: int) -> list[CandidatePlace]:
    """Preserve both discovery lanes when verification returns surplus cards."""
    gems = [c for c in candidates if c.trending_signals.get("selection_lane") == "for_you"]
    trending = [c for c in candidates if c.trending_signals.get("selection_lane") != "for_you"]
    # Reserve the front of the baseline for core places corroborated by
    # independent notes, while the separate low-key lane keeps its quota.
    trending.sort(key=lambda c: not (
        "core" in c.enrichment.get("guide_coverage", [])
        and len({s.url for s in c.sources if s.subtype == "rednote_guide" and s.url}) >= 2
    ))
    trending.sort(key=lambda c: not has_reel(c, automatic=True))
    gems.sort(key=lambda c: not has_reel(c, automatic=True))
    trending_count, gem_count = lane_slots(max(0, min(limit, len(candidates))))
    if len(gems) < gem_count:
        trending_count += gem_count - len(gems)
        gem_count = len(gems)
    if len(trending) < trending_count:
        gem_count += trending_count - len(trending)
        trending_count = len(trending)
    return trending[:trending_count] + gems[:gem_count]


def select_city_pool(swipeable: list[CandidatePlace], days: int) -> list[CandidatePlace]:
    """Preserve meal and lane coverage inside a city's day-based allocation."""
    target = days * POOL_PER_DAY
    # Buzz cards skip the density filter. A place several posts agree on is
    # often the reason to leave the city for a day, so it sits alone in its own
    # sparse cluster and the filter threw it away: an Otaru card mined from
    # Instagram and TikTok never reached a Sapporo deck.
    priority = [
        candidate
        for candidate in swipeable
        if any(
            source.type == "buzz"
            or (source.type == "personal" and source.subtype == "profile_driven")
            for source in candidate.sources
        )
    ]
    personal = [c for c in priority if any(s.type == "personal" for s in c.sources)]
    personal_ids = {c.id for c in personal}
    automatic = [c for c in priority if c.id not in personal_ids]
    priority_ids = {c.id for c in priority}
    fallback = [c for c in swipeable if c.id not in priority_ids]
    food_needed = max(0, days * MEALS_PER_DAY_MIN
                      - sum(c.type is CandidateType.FOOD for c in priority))
    meal_options = select_dense_pool(
        [c for c in fallback if c.type is CandidateType.FOOD],
        days=days, limit=food_needed,
    )
    sight_needed = max(0, days * ATTRACTIONS_PER_DAY_MIN
                       - sum(c.type is CandidateType.ATTRACTION for c in priority))
    sight_options = select_dense_pool(
        [c for c in fallback if c.type is CandidateType.ATTRACTION],
        days=days, limit=sight_needed,
    )
    social_food = sorted((c for c in automatic if c.type is CandidateType.FOOD),
                         key=lambda c: not has_reel(c, automatic=True))
    social_sights = [c for c in automatic if c.type is CandidateType.ATTRACTION]
    essentials = social_food[:days * MEALS_PER_DAY_MIN] + limit_social_pool(
        social_sights, days * ATTRACTIONS_PER_DAY_MIN
    )
    essential_ids = {c.id for c in essentials}
    automatic = essentials + limit_social_pool(
        [c for c in automatic if c.id not in essential_ids],
        max(0, round(target * BUZZ_RATIO) - len(meal_options) - len(sight_options) - len(essentials)),
    )
    selected = personal + automatic + meal_options + sight_options
    selected_ids = {c.id for c in selected}
    selected += select_dense_pool(
        [c for c in fallback if c.id not in selected_ids],
        days=days, limit=max(0, target + len(personal) - len(selected)),
    )
    return selected


def select_trip_pool(
    candidates: list[CandidatePlace], trip: Trip, city_names: list[str],
) -> list[CandidatePlace]:
    """A richer city cannot consume another city's automatic candidate slots."""
    pools = [
        select_city_pool([c for c in candidates if c.enrichment.get("city") == city], days)
        for city, days in zip(city_names, city_day_counts(trip), strict=True)
    ]
    # City provenance stays attached; alternating makes every city visible early.
    return [pool[index] for index in range(max(map(len, pools), default=0))
            for pool in pools if index < len(pool)]


async def discover_candidates(
    trip: Trip,
    travelers: list[Traveler] | None = None,
) -> list[CandidatePlace]:
    """Search the destination now, resolve real places, and build a dense pool.

    Two discovery paths feed one pool. The destination search supplies the
    foundation of real places in the city; Instagram, TikTok, and RedNote
    supply what people are currently posting about, steered by the group's
    stated interests. A place both paths find stays one card carrying both
    source rows (section 8.4).
    """
    cities = await resolve_trip_cities(trip)
    await report_progress("social_search")
    social = await discover_social_candidates(trip, list(travelers or []), cities)
    # Old saved/test sources may predate explicit city provenance. Resolve it
    # once before applying city quotas, using the same nearest-city rule.
    social = [c if c.enrichment.get("city") else c.model_copy(update={
        "enrichment": {**c.enrichment, "city": _nearest_city(c.lat, c.lng, cities).name}
    }) for c in social]
    google_discovery_calls = 0
    google_lodging_calls = 0
    by_place_id: dict[str, CandidatePlace] = {}
    merge_into_pool(by_place_id, social)
    city_days = city_day_counts(trip)
    city_targets = [days * POOL_PER_DAY for days in city_days]
    for city, city_target, day_count in zip(cities, city_targets, city_days, strict=True):
        for query in build_search_queries(city.name):
            await report_progress("place_verification", city.name)
            city_pool = [c for c in by_place_id.values()
                         if c.enrichment.get("city") == city.name
                         and c.type is not CandidateType.LODGING]
            if social and len(city_pool) >= city_target and "hotel" not in query.lower():
                food_query = "restaurant" in query.lower() or "breakfast" in query.lower()
                kind = CandidateType.FOOD if food_query else CandidateType.ATTRACTION
                needed = MEALS_PER_DAY_MIN if food_query else ATTRACTIONS_PER_DAY_MIN
                if sum(c.type is kind for c in city_pool) >= day_count * needed:
                    continue
            included_type = None
            if "restaurant" in query.lower():
                included_type = "restaurant"
            elif "hotel" in query.lower():
                included_type = "hotel"
            if included_type == "hotel":
                google_lodging_calls += 1
            else:
                google_discovery_calls += 1
            result = await run_tool(
                make_place_search_tool(),
                PlaceSearchInput(
                    query=query,
                    destination=city.name,
                    included_type=included_type,
                    location_bias=search_bias(city),
                    city_center=PlaceSearchBias(lat=city.lat, lng=city.lng),
                    city_radius_km=city.radius_km,
                ),
            )
            for place in result.matches:
                if not admit_place(place, destination=city.name, city=city).accepted:
                    continue
                existing = by_place_id.get(place.place_id)
                if existing is not None:
                    if not any(source.type == "discovery" for source in existing.sources):
                        existing = existing.model_copy(update={
                            "sources": [*existing.sources, Source(type="discovery", subtype="google_places")]
                        })
                    queries = list(existing.enrichment.get("discovery_queries", []))
                    if query not in queries:
                        queries.append(query)
                        by_place_id[place.place_id] = existing.model_copy(
                            update={
                                "enrichment": {
                                    **existing.enrichment,
                                    "discovery_queries": queries,
                                }
                            }
                        )
                    continue
                by_place_id[place.place_id] = candidate_from_place(
                    place, trip, query, city=city
                )

    activity_clusters = _dense_clusters(
        [
            candidate
            for candidate in by_place_id.values()
            if candidate.type is CandidateType.ATTRACTION
        ]
    )
    dense_activity_clusters = [cluster for cluster in activity_clusters if len(cluster) >= 3]
    for cluster in (dense_activity_clusters or activity_clusters)[: trip.days]:
        center_lat = sum(candidate.lat for candidate in cluster) / len(cluster)
        center_lng = sum(candidate.lng for candidate in cluster) / len(cluster)
        anchor = min(
            cluster,
            key=lambda candidate: (
                (candidate.lat - center_lat) ** 2
                + (candidate.lng - center_lng) ** 2,
                candidate.name_canonical,
            ),
        )
        city = _nearest_city(center_lat, center_lng, cities)
        nearby_food = [c for c in by_place_id.values()
                       if c.type is CandidateType.FOOD
                       and _distance_km(c, anchor) <= _DENSE_CLUSTER_RADIUS_KM]
        if len(nearby_food) >= FOOD_PER_DAY_TARGET and social:
            continue
        for query_template, included_type in CLUSTER_FOOD_QUERIES:
            query = query_template.format(anchor=anchor.name_canonical)
            google_discovery_calls += 1
            result = await run_tool(
                make_place_search_tool(),
                PlaceSearchInput(
                    query=query,
                    destination=city.name,
                    included_type=included_type,
                    location_bias=PlaceSearchBias(lat=center_lat, lng=center_lng),
                    city_center=PlaceSearchBias(lat=city.lat, lng=city.lng),
                    city_radius_km=city.radius_km,
                ),
            )
            for place in result.matches:
                if not admit_place(place, destination=city.name, city=city).accepted:
                    continue
                if place.place_id not in by_place_id:
                    by_place_id[place.place_id] = candidate_from_place(
                        place, trip, query, city=city
                    )

    social_ids = {candidate.enrichment["google_place_id"] for candidate in social}

    profile = await discover_profile_candidates(trip, list(travelers or []))
    profile_ids: set[str] = set()
    for candidate in profile:
        place_id = candidate.enrichment["google_place_id"]
        profile_ids.add(place_id)
        existing = by_place_id.get(place_id)
        if existing is None:
            by_place_id[place_id] = candidate
            continue
        by_place_id[place_id] = existing.model_copy(
            update={
                "sources": [*existing.sources, *candidate.sources],
                "enrichment": {
                    **candidate.enrichment,
                    **existing.enrichment,
                    "source_description": (
                        existing.enrichment.get("source_description")
                        or candidate.enrichment.get("source_description")
                    ),
                },
            }
        )

    # Buzz first, so the share the pool limit keeps is the share configured
    # above rather than whatever happened to be appended last.
    all_candidates = [
        candidate
        for place_id, candidate in by_place_id.items()
        if place_id in social_ids
    ] + [
        candidate
        for place_id, candidate in by_place_id.items()
        if place_id not in social_ids
    ]
    # Section 8.4: collapse duplicate listings before the pool is sized, or a
    # museum indexed twice under two place ids takes two slots and can be
    # scheduled on two different days.
    all_candidates = dedup_candidates(all_candidates)
    swipeable = [
        candidate for candidate in all_candidates if candidate.type is not CandidateType.LODGING
    ]
    lodging = [
        candidate for candidate in all_candidates if candidate.type is CandidateType.LODGING
    ]

    selected = select_trip_pool(swipeable, trip, [city.name for city in cities])
    if not selected:
        raise LiveDiscoveryInsufficient("Discovery returned no admissible places")
    with get_tracer().start_as_current_span("gather.coverage") as span:
        span.set_attribute("google.discovery_calls", google_discovery_calls)
        span.set_attribute("google.lodging_calls", google_lodging_calls)
        for city, city_target in zip(cities, city_targets, strict=True):
            count = sum(c.enrichment.get("city") == city.name for c in selected)
            span.set_attribute(f"{city.name}.shortage", max(0, city_target - count))
    logger.info("gather.google discovery_calls=%s lodging_calls=%s",
                google_discovery_calls, google_lodging_calls)
    lodging.sort(
        key=lambda candidate: (
            candidate.enrichment.get("google_place_id") not in profile_ids,
            candidate.name_canonical,
        )
    )
    await report_progress("deck_build")
    return await localize_candidates(selected + lodging[:3], trip.output_locale)


def _pool_already_discovered(candidates: list[CandidatePlace]) -> bool:
    """Whether discovery has already built this trip's pool.

    Personal attachments do not count. They are additive (CLAUDE.md section
    16) and are created the moment someone pastes a link, which since M7a
    happens in the trip chat long before anyone runs a gather. Treating any
    row as "already gathered" meant one pasted link permanently suppressed
    discovery and left the group with a one-card deck.
    """
    return any(not _is_personal_only(candidate) for candidate in candidates)


def _is_personal_only(candidate: CandidatePlace) -> bool:
    """A card that exists only because someone attached it.

    A row carrying no sources at all is not one of these: it cannot have come
    from a paste, and the safe reading is that a pool is already there, so a
    resumed run reuses rather than gathering twice.
    """
    return bool(candidate.sources) and all(
        source.type == "personal" for source in candidate.sources
    )


async def _localize_saved_candidates(
    candidates: list[CandidatePlace], locale: str,
) -> list[CandidatePlace]:
    """Translate both new and reused cards, then retain that shared wording."""
    localized = await localize_candidates(candidates, locale)
    if localized == candidates:
        return localized
    async with session_scope() as session:
        await CandidatePlaceRepository(session).update_localized_display(localized)
    return localized


async def gather_node(state: TripState) -> dict[str, Any]:
    """LangGraph node that persists a live pool and safely reuses it on resume."""
    trip = state.trip
    tracer = get_tracer()
    with tracer.start_as_current_span("gather.live") as span:
        span.set_attribute("trip_id", str(trip.id))
        span.set_attribute("destination", trip.destination)
        span.set_attribute("gather.source", "google_places_live+social_buzz")

        async with session_scope() as session:
            repo = CandidatePlaceRepository(session)
            existing = await repo.list_for_trip(trip.id)
            pool_exists = _pool_already_discovered(existing)
            attached = list(existing)

        if pool_exists:
            existing = filter_dietary_conflicts(existing, state.constraints)
            existing = await _localize_saved_candidates(existing, trip.output_locale)
            span.set_attribute("gather.reused_existing", True)
            span.set_attribute("gather.candidate_count", len(existing))
            record_source_mix(existing)
            return {"candidates": existing}

        candidates = filter_dietary_conflicts(
            await discover_candidates(trip, state.travelers),
            state.constraints,
        )

        async with session_scope() as session:
            repo = CandidatePlaceRepository(session)
            existing = await repo.list_for_trip(trip.id)
            if _pool_already_discovered(existing):
                # Another gather finished while this one was running.
                saved = filter_dietary_conflicts(existing, state.constraints)
                reused = True
            else:
                # Keep the pasted cards and add what discovery found, skipping
                # a place someone had already attached so the group does not
                # see it twice.
                attached_by_place = {c.enrichment.get("google_place_id"): c for c in attached}
                fresh = []
                for candidate in candidates:
                    place_id = candidate.enrichment.get("google_place_id")
                    if place_id in attached_by_place:
                        merged = merge_candidate_evidence(attached_by_place[place_id], candidate)
                        attached_by_place[place_id] = await repo.update_evidence(merged)
                    else:
                        fresh.append(candidate)
                saved = [*attached_by_place.values(), *await repo.add_many(fresh)]
                reused = False

        saved = filter_dietary_conflicts(saved, state.constraints)
        saved = await _localize_saved_candidates(saved, trip.output_locale)

        span.set_attribute("gather.reused_existing", reused)
        span.set_attribute("gather.candidate_count", len(saved))
        record_source_mix(saved)
        return {"candidates": saved}


__all__ = [
    "LiveDiscoveryInsufficient",
    "build_search_queries",
    "candidate_from_place",
    "discover_candidates",
    "gather_node",
    "select_dense_pool",
]
