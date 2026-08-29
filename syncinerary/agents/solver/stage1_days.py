"""Deterministic geographic day assignment for the current milestone."""
from __future__ import annotations

from collections.abc import Sequence

from ortools.sat.python import cp_model

from syncinerary.config.solver import (
    ATTRACTIONS_PER_DAY_MIN,
    FOOD_PER_DAY_MAX,
    MEALS_PER_DAY_MIN,
)
from syncinerary.domain.models import CandidatePlace, CandidateType
from syncinerary.tools.transit import TransitLocation, haversine_km


def chunk_evenly[T](items: Sequence[T], bucket_count: int) -> list[list[T]]:
    """Contiguous score-ordered buckets whose sizes differ by at most one."""
    if bucket_count <= 0:
        return []
    base, remainder = divmod(len(items), bucket_count)
    buckets: list[list[T]] = []
    offset = 0
    for index in range(bucket_count):
        size = base + (1 if index < remainder else 0)
        buckets.append(list(items[offset : offset + size]))
        offset += size
    return buckets


def cluster_nearby_evenly(
    candidates: Sequence[CandidatePlace],
    bucket_count: int,
) -> list[list[CandidatePlace]]:
    """Build balanced geographic day groups without losing score priority.

    The highest-ranked candidate is the first seed. Later seeds are the
    places farthest from every existing seed, which spreads days across the
    destination before the optimizer assigns each remaining candidate to a
    nearby day. Shortlist rank and day index are deterministic tiebreaks.

    Every day also receives a share of both kinds of candidate. Grouping on
    distance alone let one day take every restaurant in an area and leave the
    next with nothing to eat, and let food fill a day that was supposed to be
    sightseeing. Food has a floor for lunch and dinner and a ceiling so it
    cannot crowd out the sights; attractions have a floor of their own. Each
    quota degrades to what the pool can supply, so an unbalanced shortlist
    stays feasible instead of failing to solve.
    """
    capacities = [len(bucket) for bucket in chunk_evenly(candidates, bucket_count)]
    ranked = list(candidates)
    active_bucket_count = sum(capacity > 0 for capacity in capacities)
    if active_bucket_count == 0:
        return [[] for _capacity in capacities]

    rank_by_id = {candidate.id: index for index, candidate in enumerate(ranked)}
    seeds = [ranked[0]]
    while len(seeds) < active_bucket_count:
        next_seed = max(
            (candidate for candidate in ranked if candidate not in seeds),
            key=lambda candidate: (
                min(_distance_km(candidate, seed) for seed in seeds),
                -rank_by_id[candidate.id],
            ),
        )
        seeds.append(next_seed)

    assignment = cp_model.CpModel()
    choices = {
        (candidate_index, bucket_index): assignment.new_bool_var(
            f"candidate_{candidate_index}_day_{bucket_index}"
        )
        for candidate_index in range(len(ranked))
        for bucket_index in range(active_bucket_count)
    }
    for candidate_index in range(len(ranked)):
        assignment.add(
            sum(
                choices[(candidate_index, bucket_index)]
                for bucket_index in range(active_bucket_count)
            )
            == 1
        )
    for bucket_index in range(active_bucket_count):
        target_capacity = capacities[bucket_index]
        assigned_count = sum(
            choices[(candidate_index, bucket_index)]
            for candidate_index in range(len(ranked))
        )
        assignment.add(assigned_count >= max(1, target_capacity - 2))
        assignment.add(assigned_count <= target_capacity + 2)
    for bucket_index, seed in enumerate(seeds):
        assignment.add(choices[(rank_by_id[seed.id], bucket_index)] == 1)

    food_indices = [
        index
        for index, candidate in enumerate(ranked)
        if candidate.type is CandidateType.FOOD
    ]
    attraction_indices = [
        index
        for index, candidate in enumerate(ranked)
        if candidate.type is not CandidateType.FOOD
    ]

    available_food = len(food_indices) // active_bucket_count
    food_floor = min(MEALS_PER_DAY_MIN, available_food)
    # Every candidate has to land somewhere, so the ceiling can never sit below
    # the share a day must absorb. Capping under that made the model infeasible
    # rather than balanced.
    unavoidable_food = -(-len(food_indices) // active_bucket_count)
    food_ceiling = max(food_floor, FOOD_PER_DAY_MAX, unavoidable_food)
    attraction_floor = min(
        ATTRACTIONS_PER_DAY_MIN,
        len(attraction_indices) // active_bucket_count,
    )

    for bucket_index in range(active_bucket_count):
        food_in_bucket = sum(
            choices[(candidate_index, bucket_index)]
            for candidate_index in food_indices
        )
        if food_floor >= 1:
            assignment.add(food_in_bucket >= food_floor)
        if food_indices:
            assignment.add(food_in_bucket <= food_ceiling)
        if attraction_floor >= 1:
            assignment.add(
                sum(
                    choices[(candidate_index, bucket_index)]
                    for candidate_index in attraction_indices
                )
                >= attraction_floor
            )

    costs = []
    for candidate_index, candidate in enumerate(ranked):
        for bucket_index, seed in enumerate(seeds):
            distance_meters = round(_distance_km(candidate, seed) * 1000)
            deterministic_tiebreak = (candidate_index + 1) * (bucket_index + 1)
            costs.append(
                (distance_meters * 1000 + deterministic_tiebreak)
                * choices[(candidate_index, bucket_index)]
            )
    assignment.minimize(sum(costs))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(assignment)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Could not build balanced geographic day groups")

    buckets = [[] for _index in range(active_bucket_count)]
    for candidate_index, candidate in enumerate(ranked):
        for bucket_index in range(active_bucket_count):
            if solver.value(choices[(candidate_index, bucket_index)]):
                buckets[bucket_index].append(candidate)
                break

    buckets.extend([] for _capacity in capacities[active_bucket_count:])
    return buckets


def _distance_km(origin: CandidatePlace, destination: CandidatePlace) -> float:
    return haversine_km(
        TransitLocation(lat=origin.lat, lng=origin.lng),
        TransitLocation(lat=destination.lat, lng=destination.lng),
    )


__all__ = ["chunk_evenly", "cluster_nearby_evenly"]
